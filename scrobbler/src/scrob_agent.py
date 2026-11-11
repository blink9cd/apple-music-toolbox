"""`install` and `uninstall`: the app's LaunchAgent, and the bundle it runs.

`install` refuses an entry script in a linked git worktree: such a checkout is often
removed once its work is done, and an agent should run from the repository's main
checkout, which stays. It refuses an absent signing setting with how to write it. It then
builds, signs and verifies the bundle in a staging folder inside the data folder, so a
failed build leaves the running app untouched.

Only then does it touch the running app. An agent launchd answers about unexpectedly is
refused before anything is replaced. A loaded agent is stopped with its plist kept, so a
failure from here on still reads as installed. The bundle is swapped in (the old one
renamed aside, the new one renamed in, the old one deleted, a failure to delete it being
its own warning since the new app is already in place), and the agent is loaded through
`launchd_agent`, whose read-back confirms launchd loaded it. Last, it confirms the app
itself started: it polls `status.json` until its `started_at` is newer than the moment
the old agent was stopped, inside a 30 s deadline with waits escalating from 0.5 s to
4 s, and exits 1 when it never is. Taking that moment after the stop, not before the
build, means a start the old app reported during a long build cannot pass for the new
one's. A file-system failure on the way is one failure, never a traceback.

`uninstall` unloads the agent and removes its plist; the app, the queue, the state and
the config stay.

Entry point assumptions: imported by the scrobbler's modules, with `src/` and the shared
libraries on `sys.path`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

import launchd_agent
import scrob_bundle
import scrob_status
from scrob_bundle import BuildFailed, Refused
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
#: The bound on the one git call.
GIT_TIMEOUT_S: Final = 5.0
#: What `rev-parse` is asked, one answer line each, in this order.
_DIR_QUESTIONS: Final = ("--git-dir", "--git-common-dir")
#: git's own words for a folder outside every repository.
_NOT_A_REPOSITORY: Final = (
    "not a git repository (or any of the parent directories)",
    "not a git repository (or any parent up to mount point",
)


def refuse_linked_worktree(host: Host) -> None:
    """Refused when the entry script sits in a linked git worktree.

    A linked worktree's `--git-dir` differs from its `--git-common-dir`. A folder outside
    every repository (an exported copy), as git's own message says, may install; any
    other git failure, an answer short of two lines, or a git that cannot answer refuses.
    """
    folder = host.script.parent
    argv = ["git", "-C", str(folder), "rev-parse", *_DIR_QUESTIONS]
    try:
        done = host.run(argv, cwd=folder, timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused(
            f"could not ask git whether {folder} is a linked worktree "
            f"({type(error).__name__})"
        ) from None
    if done.returncode != 0 and any(
        phrase in done.stderr for phrase in _NOT_A_REPOSITORY
    ):
        return
    lines = done.stdout.splitlines()
    if done.returncode != 0 or len(lines) < len(_DIR_QUESTIONS):
        raise Refused(
            f"git could not say whether {folder} is a linked worktree "
            f"(exit {done.returncode})"
        )
    git_dir, common_dir = ((folder / line).resolve() for line in lines[:2])
    if git_dir != common_dir:
        raise Refused(
            f"{folder} is in a linked git worktree, which is often removed once its "
            "work is done; install from the repository's main checkout"
        )


def agent_plist(layout: Layout, paths: ScrobPaths) -> bytes:
    """The agent's plist: the installed app's `run`, kept alive, from the data folder."""
    executable = scrob_bundle.bundle_executable(paths.app_bundle, layout)
    return launchd_agent.build_keepalive_plist(
        label=layout.launchd_label,
        program_arguments=[str(executable), RUN_ARGUMENT],
        working_directory=str(paths.data_dir),
        log_paths=(str(paths.out_log), str(paths.err_log)),
        path_value=PATH_VALUE,
    )


def stage_bundle(host: Host, layout: Layout, paths: ScrobPaths, identity: str) -> Path:
    """Build, sign and verify a new bundle in a fresh staging folder; return the bundle.

    The staging folder is named by this process's id, so a folder of that name is one an
    earlier run of this command left, and is replaced. A failure removes it.
    """
    staging = paths.data_dir / f".staging-{host.pid}"
    if staging.exists():
        shutil.rmtree(staging)
    scrob_bundle.make_private(staging)
    try:
        return scrob_bundle.build_bundle(host, layout, staging, identity)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def swap_in(staged: Path, final: Path, aside: Path) -> None:
    """Rename `final` aside to `aside`, then `staged` in as `final`.

    A folder already at `aside` is one an earlier run with this process's id left, and is
    removed first, or the rename aside would fail after the agent was already stopped.
    When the new bundle cannot be renamed in, the old one is put back before the error
    propagates, so a failed swap never leaves no app at all.
    """
    if aside.exists():
        shutil.rmtree(aside)
    if final.exists():
        final.rename(aside)
    try:
        staged.rename(final)
    except OSError:
        if aside.exists():
            aside.rename(final)
        raise


def _swap(host: Host, layout: Layout, paths: ScrobPaths, staged: Path) -> None:
    """Swap the staged bundle in, then remove the old bundle and the emptied staging folder."""
    aside = paths.data_dir / f".old-{host.pid}-{layout.app_name}"
    try:
        swap_in(staged, paths.app_bundle, aside)
        staged.parent.rmdir()
    except OSError as error:
        raise BuildFailed(
            f"could not swap the new app into {paths.app_bundle} "
            f"({type(error).__name__})"
        ) from None
    try:
        if aside.exists():
            shutil.rmtree(aside)
    except OSError as error:
        # The new app is in place; only the old copy is left behind.
        print(
            f"WARNING: the new app is in place, but could not remove the old app at "
            f"{aside} ({type(error).__name__}); remove it by hand",
            file=host.err,
        )


def _started_since(paths: ScrobPaths, began: float) -> bool:
    """Whether status.json reports a start newer than `began`."""
    try:
        status = scrob_status.read_app_status(paths.status_file)
    except scrob_status.StatusFileError:
        return False
    return status.started_at is not None and status.started_at > began


def confirm_started(host: Host, paths: ScrobPaths, began: float) -> bool:
    """Poll status.json until the app reports a start after `began`, or the deadline."""
    deadline = host.clock() + CONFIRM_DEADLINE_S
    attempt = 0
    while not _started_since(paths, began):
        remaining = deadline - host.clock()
        if remaining <= 0:
            return False
        wait = CONFIRM_WAITS_S[min(attempt, len(CONFIRM_WAITS_S) - 1)]
        host.sleep(min(wait, remaining))
        attempt += 1
    return True


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
        scrob_bundle.make_private(folder)
    _stop_old_agent(host, layout)
    stopped = host.now()
    _swap(host, layout, paths, staged)
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
        scrob_bundle.make_private(paths.data_dir)
        staged = stage_bundle(host, layout, paths, identity)
        try:
            return _replace_agent(host, layout, paths, staged)
        finally:
            # Gone already once the swap succeeds; left only when launchd failed first.
            shutil.rmtree(staged.parent, ignore_errors=True)
    except OSError as error:
        raise BuildFailed(f"install failed: {type(error).__name__}: {error}") from None


def install(host: Host, layout: Layout) -> int:
    """Install the app and its agent; 0 once the app reports its start, 1 when it never does."""
    refuse_linked_worktree(host)
    identity = scrob_bundle.read_identity(host, layout)
    paths = layout.paths(host.home)
    stopped = _install_bundle(host, layout, paths, identity)
    if not confirm_started(host, paths, stopped):
        print(
            f"ERROR: the agent is loaded, but the app did not report a start within "
            f"{CONFIRM_DEADLINE_S:g} s; read {paths.err_log}",
            file=host.err,
        )
        return 1
    print(
        f"installed {paths.app_bundle} and started it under launchd. At the first play, "
        "macOS asks whether listensmith scrobbler may control Music (Automation): "
        "allow it, or no play is logged.",
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
