"""`install` and `uninstall`: the app's LaunchAgent, and the bundle it runs.

`install` refuses an entry script in a linked git worktree: such a checkout is often
removed once its work is done, and an agent should run from the repository's main
checkout, which stays. It refuses an absent signing setting with how to write it. It then
removes the work folders an install no longer running left, and builds, signs and
verifies the bundle in a staging folder inside the data folder, so a failed build leaves
the running app untouched.

Only then does it touch the running app. An agent launchd answers about unexpectedly is
refused before anything is replaced. A loaded agent is stopped with its plist kept, so a
failure from here on still reads as installed. The bundle is swapped in, the new one and
the old one exchanged in one atomic step, and the staging folder, now holding the old
one, is deleted, a failure to delete it being its own warning since the new app is
already in place. A copy of the app left under an
earlier folder name, found by its bundle id and told from the new one by the entry it
names, never its spelling, is removed the same way. The agent is then
loaded through `launchd_agent`, whose read-back confirms launchd loaded it. Last, it confirms the app
itself started: it polls `status.json` until its `started_at` is newer than the moment
the old agent was stopped, inside a 30 s deadline with waits escalating from 0.5 s to
4 s, and exits 1 when it never is. Taking that moment after the stop, not before the
build, means a start the old app reported during a long build cannot pass for the new
one's. A file-system failure on the way is one failure, never a traceback.

What it prints last depends on that same status: when the app's request for Automation
of Music is in flight, whatever its age, it says so, since a prompt may be on the screen
at that moment; otherwise it says when the prompt will come.

`uninstall` unloads the agent and removes its plist; the app, the queue, the state and
the config stay.

The linked-worktree check, the swap and the private folders are signed_app's
(`app_install`); this module holds the order of steps and the scrobbler's own messages.

Entry point assumptions: imported by the scrobbler's modules, with `src/`, signed_app's
``src/`` and the shared libraries on `sys.path`.
"""

from __future__ import annotations

import plistlib
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Final

import launchd_agent
import scrob_bundle
import scrob_status
from app_install import (
    make_private,
    refuse_linked_worktree,
    same_entry,
    swap_in,
    sweep_stale_work,
)
from scrob_bundle import BuildFailed
from scrob_host import Host
from scrob_layout import Layout, ScrobPaths

#: The agent's whole PATH: launchd's own is minimal, and the app needs nothing more.
PATH_VALUE: Final = "/usr/bin:/bin"
#: The argument the app's executable runs under launchd with.
RUN_ARGUMENT: Final = "run"
#: How long install waits for the app to report its start.
CONFIRM_DEADLINE_S: Final = 30.0
#: The waits between reads of status.json; the last repeats until the deadline.
CONFIRM_WAITS_S: Final = (0.5, 1.0, 2.0, 4.0)


def agent_plist(layout: Layout, paths: ScrobPaths) -> bytes:
    """The agent's plist: the installed app's `run`, from the data folder.

    launchd restarts it only after a failed exit or a crash: the app exits 0 on a refusal
    no restart can cure (a data folder it may not use), so such a refusal ends instead of
    restarting every throttle interval with a line in err.log each time.
    """
    executable = scrob_bundle.bundle_executable(paths.app_bundle, layout)
    return launchd_agent.build_keepalive_plist(
        label=layout.launchd_label,
        program_arguments=[str(executable), RUN_ARGUMENT],
        working_directory=str(paths.data_dir),
        log_paths=(str(paths.out_log), str(paths.err_log)),
        path_value=PATH_VALUE,
        keep_alive=launchd_agent.RESTART_AFTER_FAILURE,
    )


def stage_bundle(host: Host, layout: Layout, paths: ScrobPaths, identity: str) -> Path:
    """Build, sign and verify a new bundle in a fresh staging folder; return the bundle.

    The staging folder is named by this process's id, so a folder of that name is one an
    earlier run of this command left, and is replaced. A failure removes it.
    """
    staging = paths.data_dir / f".staging-{host.pid}"
    if staging.exists():
        shutil.rmtree(staging)
    make_private(staging)
    try:
        return scrob_bundle.build_bundle(host, layout, staging, identity)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _swap(host: Host, paths: ScrobPaths, staged: Path) -> None:
    """Swap the staged bundle in, in one step, then remove the staging folder.

    After an upgrade the staging folder holds the old bundle, so removing it removes
    that too; a failure to remove it is a warning, since the new app is in place.
    """
    try:
        swap_in(staged, paths.app_bundle)
    except OSError as error:
        raise BuildFailed(
            f"could not swap the new app into {paths.app_bundle} "
            f"({type(error).__name__})"
        ) from None
    try:
        shutil.rmtree(staged.parent)
    except OSError as error:
        # The new app is in place; only the old copy is left behind.
        print(
            f"WARNING: the new app is in place, but could not remove the old app in "
            f"the staging folder {staged.parent} ({type(error).__name__}); remove it "
            "by hand",
            file=host.err,
        )


def _is_earlier_copy(
    layout: Layout,
    paths: ScrobPaths,
    candidate: Path,
    same: Callable[[Path, Path], bool],
) -> bool:
    """Whether `candidate` is this app under another folder name: same bundle id, not a link.

    The installed bundle is told apart by `same`, the entry each path names, never by
    spelling: on a volume that ignores case, a folder spelled otherwise can BE the bundle
    just installed. A link is never followed, and a folder whose Info.plist is absent or
    unreadable is not ours to judge, so both are kept.
    """
    if (
        same(candidate, paths.app_bundle)
        or candidate.is_symlink()
        or not candidate.is_dir()
    ):
        return False
    try:
        with (candidate / "Contents" / "Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return False
    return isinstance(info, dict) and info.get("CFBundleIdentifier") == layout.bundle_id


def remove_earlier_copies(
    host: Host,
    layout: Layout,
    paths: ScrobPaths,
    *,
    same_entry: Callable[[Path, Path], bool] = same_entry,
) -> None:
    """Remove this app left in the data folder under an earlier name, once the new one is in.

    Renaming the app (its `app_name`) changes its folder, and the swap replaces only the
    folder of the current name, so the earlier one would sit there for good. It is found by
    its bundle id, never by a remembered name, so the next rename is covered too. A copy
    that cannot be removed is a warning: the new app is already in place. `same_entry`
    is the identity seam a test replaces.
    """
    for candidate in sorted(paths.data_dir.glob("*.app")):
        if not _is_earlier_copy(layout, paths, candidate, same_entry):
            continue
        try:
            shutil.rmtree(candidate)
        except OSError as error:
            print(
                f"WARNING: the new app is in place, but could not remove an earlier copy "
                f"at {candidate} ({type(error).__name__}); remove it by hand",
                file=host.err,
            )


def _started_since(paths: ScrobPaths, began: float) -> scrob_status.AppStatus | None:
    """The status reporting a start newer than `began`; None while status.json has none."""
    try:
        status = scrob_status.read_app_status(paths.status_file)
    except scrob_status.StatusFileError:
        return None
    started = status.started_at is not None and status.started_at > began
    return status if started else None


def confirm_started(
    host: Host, paths: ScrobPaths, began: float
) -> scrob_status.AppStatus | None:
    """Poll status.json until the app reports a start after `began`, or the deadline.

    Returns the status that reported the start, or None when the deadline passed first.
    """
    deadline = host.clock() + CONFIRM_DEADLINE_S
    attempt = 0
    while (status := _started_since(paths, began)) is None:
        remaining = deadline - host.clock()
        if remaining <= 0:
            return None
        wait = CONFIRM_WAITS_S[min(attempt, len(CONFIRM_WAITS_S) - 1)]
        host.sleep(min(wait, remaining))
        attempt += 1
    return status


def prompt_advice(status: scrob_status.AppStatus) -> str:
    """What a finished install says about the Automation prompt, from the app's `status`.

    A request in flight is named at any age: the install reads the status moments after
    the app starts, long before `status` would call the wait too long, and a prompt on
    the screen then is exactly what the reader must act on. A request already decided
    answers within milliseconds, so the wording allows that no prompt is showing.
    """
    if status.automation_asked_at is not None:
        return (
            "The app's request for Automation of Music is in flight: if macOS is "
            f"showing a prompt asking whether {scrob_status.STEM} may control Music, "
            "allow it, or no play is logged."
        )
    return (
        f"macOS asks whether {scrob_status.STEM} may control Music (Automation): at "
        "once when Music.app is running as the app starts, otherwise at the first "
        "play, pause or track change. Allow it, or no play is logged."
    )


def _stop_old_agent(host: Host, layout: Layout) -> None:
    """Stop a loaded agent, keeping its plist; refuse an agent launchd answers oddly about.

    An unexpected answer is refused here, before the swap, because the swap deletes the
    old app and nothing after it can undo that.
    """
    label = layout.launchd_label
    state = launchd_agent.agent_state(host.launchctl, label)
    if state is launchd_agent.AgentState.UNKNOWN:
        raise launchd_agent.LaunchdError(
            f"{label}: launchctl gave an unexpected answer, so the running app was "
            "left untouched"
        )
    if state is launchd_agent.AgentState.LOADED:
        launchd_agent.stop_agent(host.launchctl, label=label)


def _replace_agent(
    host: Host, layout: Layout, paths: ScrobPaths, staged: Path
) -> float:
    """Stop the old agent, swap the bundle in, load the agent; return when it was stopped."""
    # Made first: a refused folder (a planted symlink) must stop install before the old
    # agent is stopped or its app swapped out, and neither folder needs the new bundle.
    for folder in (paths.logs_dir, paths.state_dir):
        make_private(folder)
    _stop_old_agent(host, layout)
    stopped = host.now()
    _swap(host, paths, staged)
    # After the swap and with the old agent stopped, so an earlier-named copy is never
    # the only app left, nor one still running.
    remove_earlier_copies(host, layout, paths)
    launchd_agent.install_agent(
        host.launchctl,
        label=layout.launchd_label,
        plist_path=paths.launch_agent_plist,
        plist=agent_plist(layout, paths),
    )
    return stopped


def _install_bundle(
    host: Host, layout: Layout, paths: ScrobPaths, identity: str
) -> float:
    """Stage the new bundle and put it in place under a loaded agent; return the stop time.

    A file-system failure anywhere here (a folder that cannot be made, a plist that cannot
    be written) is BuildFailed, one line naming its type, never a traceback.
    """
    try:
        make_private(paths.data_dir)
        sweep_stale_work(paths.data_dir, host.pid, host.err)
        staged = stage_bundle(host, layout, paths, identity)
        try:
            return _replace_agent(host, layout, paths, staged)
        finally:
            # Gone already once the swap succeeds; left when a step before it failed
            # (launchd, the swap itself) or its removal after the swap did.
            shutil.rmtree(staged.parent, ignore_errors=True)
    except OSError as error:
        raise BuildFailed(f"install failed: {type(error).__name__}: {error}") from None


def install(host: Host, layout: Layout) -> int:
    """Install the app and its agent; 0 once the app reports its start, 1 when it never does."""
    refuse_linked_worktree(host)
    identity = scrob_bundle.read_identity(host, layout)
    paths = layout.paths(host.home)
    stopped = _install_bundle(host, layout, paths, identity)
    started = confirm_started(host, paths, stopped)
    if started is None:
        print(
            f"ERROR: the agent is loaded, but the app did not report a start within "
            f"{CONFIRM_DEADLINE_S:g} s; read {paths.err_log}",
            file=host.err,
        )
        return 1
    print(
        f"installed {paths.app_bundle} and started it under launchd. "
        f"{prompt_advice(started)}",
        file=host.out,
    )
    return 0


def uninstall(host: Host, layout: Layout) -> None:
    """Unload the agent and remove its plist; keep the app, queue, state and config."""
    paths = layout.paths(host.home)
    launchd_agent.uninstall_agent(
        host.launchctl, label=layout.launchd_label, plist_path=paths.launch_agent_plist
    )
    print(
        f"uninstalled the agent; kept the app, the queue and the state in "
        f"{paths.data_dir}, and the config in {paths.config_file.parent}",
        file=host.out,
    )
