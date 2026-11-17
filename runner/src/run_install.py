"""`build`, `install` and `uninstall`: the runner app's bundle, and its place on this Mac.

`build_bundle` resolves the allowlist first (so a bad one stops before the compiler
runs), builds the Swift package under ``app/`` beside the entry script into a private
scratch folder inside the runner's data folder, and assembles the bundle with the
allowlist in its Info.plist. With an identity it signs the bundle and verifies the
signature, which then covers the allowlist: the runner app checks its own signature
before it reads the list, so an edited list refuses to run.

`install` refuses an entry script in a linked git worktree (the allowlist would name
scripts in a checkout that is often removed) and an absent signing setting. It removes
the work folders an install no longer running left, then builds, signs and verifies in
a staging folder inside the data folder, and reads the new bundle's designated
requirement there, so a failed build leaves the installed app untouched. It swaps the
new bundle in, in one atomic step, removes the staging folder (now holding the old
bundle), records that requirement as the app's signer
(`run_signer`), and then runs the grant check (`run_grant`), whose verdict is install's
exit code. The app has no agent of its own:
launchd starts it from each scheduled job's own agent.

`uninstall` unloads a grant agent a stopped install may have left, and removes the
bundle; the data folder's logs stay.

The steps themselves are signed_app's; this module holds their order, the runner's
values, and its messages. A refusal is `Refused` (exit 2); a build, sign, verify or swap
that fails is `BuildFailed` (exit 1). The signing identity is never printed.

Entry point assumptions: imported by the runner's modules, with `src/`, the grant
probe's folder, signed_app's ``src/`` and the shared libraries on `sys.path`.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Final

import app_bundle
import grant_probe
import launchd_agent
import run_allowlist
import run_grant
import run_signer
import swgate_signing
from app_bundle import BuildFailed, Refused
from app_host import Host
from app_install import (
    make_private,
    refuse_linked_worktree,
    swap_in,
    sweep_stale_work,
)
from run_layout import RunLayout, RunPaths

#: The Swift package's folder, beside the entry script.
APP_PACKAGE_DIRNAME: Final = "app"
#: The folder inside the data folder every build scratches into.
SCRATCH_DIRNAME: Final = ".scratch"
#: How many hex digits of the package path's digest name its scratch folder.
_SCRATCH_HASH_CHARS: Final = 16
#: What macOS shows when the app first asks to control Music.app.
RUNNER_PROMPT: Final = (
    "Apple Music Toolbox Runner runs the Apple Music tools you schedule on this Mac, "
    "so they can read your library while you are away. It never changes playback."
)


def app_package(host: Host) -> Path:
    """The Swift package beside this checkout's entry script."""
    return host.script.parent / APP_PACKAGE_DIRNAME


def probe_script(host: Host) -> Path:
    """The grant probe in this checkout: in its own folder beside the entry script."""
    probe = Path(grant_probe.__file__)
    return host.script.parent / probe.parent.name / probe.name


def scratch_path(host: Host, layout: RunLayout) -> Path:
    """The package's own scratch folder in the data folder, keyed on the package's path."""
    resolved = str(app_package(host).resolve()).encode("utf-8")
    digest = hashlib.sha256(resolved).hexdigest()[:_SCRATCH_HASH_CHARS]
    return layout.paths(host.home).data_dir / SCRATCH_DIRNAME / digest


def prepare_scratch(host: Host, layout: RunLayout) -> Path:
    """The scratch folder, made private along with the two folders that hold it."""
    scratch = scratch_path(host, layout)
    for folder in (scratch.parent.parent, scratch.parent, scratch):
        make_private(folder)
    return scratch


def info_plist(layout: RunLayout, allowlist: run_allowlist.Allowlist) -> bytes:
    """The bundle's Info.plist: its names, its version, the prompt and the allowlist."""
    # Plain dicts and lists: plistlib refuses any other mapping nested as a value.
    allowed = {"python": allowlist["python"], "scripts": list(allowlist["scripts"])}
    return app_bundle.info_plist(
        layout,
        automation_prompt=RUNNER_PROMPT,
        extra={run_allowlist.INFO_KEY: allowed},
    )


def read_identity(host: Host, layout: RunLayout) -> str:
    """The configured signing identity; Refused when absent, in a checkout or malformed."""
    return app_bundle.read_identity(host, layout.paths(host.home).signing_config)


def _build(
    host: Host,
    layout: RunLayout,
    out_dir: Path,
    identity: str | None,
    allowlist: run_allowlist.Allowlist,
) -> Path:
    """Build, assemble with `allowlist`, and, with an `identity`, sign and verify."""
    scratch = prepare_scratch(host, layout)
    built = app_bundle.swift_build(host, app_package(host), scratch, layout.executable)
    plist = info_plist(layout, allowlist)
    bundle = app_bundle.assemble(layout, out_dir, built, plist)
    if identity is not None:
        app_bundle.sign_bundle(host, bundle, identity)
    return bundle


def build_bundle(
    host: Host, layout: RunLayout, out_dir: Path, identity: str | None
) -> Path:
    """Build the bundle in `out_dir` for this checkout's allowlist; return the bundle."""
    return _build(host, layout, out_dir, identity, run_allowlist.for_host(host))


def run_build(host: Host, layout: RunLayout, out_dir: Path, *, sign: bool) -> int:
    """`build --out DIR [--sign]`: 0 built, and with --sign signed and verified."""
    identity = read_identity(host, layout) if sign else None
    bundle = build_bundle(host, layout, out_dir, identity)
    note = ""
    if identity is not None:
        note = f", signed and verified with {swgate_signing.render_identity(identity)}"
    print(f"built {bundle}{note}", file=host.out)
    return 0


def _stage_bundle(
    host: Host,
    layout: RunLayout,
    paths: RunPaths,
    identity: str,
    allowlist: run_allowlist.Allowlist,
) -> tuple[Path, str]:
    """Build, sign and verify a new bundle in a fresh staging folder.

    Returns the bundle and its designated requirement, the signer `install` records. The
    staging folder is named by this process's id, so a folder of that name is one an
    earlier run of this command left, and is replaced. A failure removes it.
    """
    staging = paths.data_dir / f".staging-{host.pid}"
    if staging.exists():
        shutil.rmtree(staging)
    make_private(staging)
    try:
        bundle = _build(host, layout, staging, identity, allowlist)
        return bundle, app_bundle.designated_requirement(host, bundle)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _swap(host: Host, paths: RunPaths, staged: Path) -> None:
    """Swap the staged bundle in, in one step, then remove the staging folder.

    After an upgrade the staging folder holds the old bundle, so removing it removes
    that too. A job running through the old app keeps running: it holds the old
    executable open.
    """
    try:
        swap_in(staged, paths.app_bundle)
    except OSError as error:
        # Nothing moved: the staging folder still holds the new bundle.
        shutil.rmtree(staged.parent, ignore_errors=True)
        raise BuildFailed(
            f"could not swap the new app into {paths.app_bundle} "
            f"({type(error).__name__})"
        ) from None
    try:
        shutil.rmtree(staged.parent)
    except OSError as error:
        # The new app is in place; only the old copy is left behind.
        print(
            f"WARNING: the new app is in place, but could not remove the staging "
            f"folder {staged.parent}, which holds the old app "
            f"({type(error).__name__}); remove it by hand",
            file=host.err,
        )


def install(host: Host, layout: RunLayout) -> int:
    """Build, sign and install the app, then check its grant; 0 once it may control Music."""
    refuse_linked_worktree(host)
    identity = read_identity(host, layout)
    allowlist = run_allowlist.for_host(host)
    probe = probe_script(host)
    if str(probe) not in allowlist["scripts"]:
        raise Refused(
            f"the allowlist does not hold {probe.name}, the script install checks the "
            "grant with"
        )
    paths = layout.paths(host.home)
    make_private(paths.data_dir)
    sweep_stale_work(paths.data_dir, host.pid, host.err)
    staged, requirement = _stage_bundle(host, layout, paths, identity, allowlist)
    _swap(host, paths, staged)
    run_signer.record_signer(paths, requirement)
    # Flushed: the next step can wait minutes on a person, who should see this first.
    print(
        f"installed {paths.app_bundle}; checking that it may control Music "
        "(if macOS asks, allow it)",
        file=host.out,
        flush=True,
    )
    result = run_grant.run_check(
        host, layout, paths, python=allowlist["python"], probe=probe
    )
    return run_grant.report(host, layout, paths, result)


def uninstall(host: Host, layout: RunLayout) -> int:
    """Unload a leftover grant agent and remove the bundle; keep the data folder's logs."""
    paths = layout.paths(host.home)
    launchd_agent.uninstall_agent(
        host.launchctl, label=layout.grant_label, plist_path=paths.grant_plist
    )
    if not paths.app_bundle.exists():
        print(
            f"{layout.display_name} is not installed; nothing was removed",
            file=host.out,
        )
        return 0
    shutil.rmtree(paths.app_bundle)
    print(
        f"removed {paths.app_bundle}. A scheduled job that starts through the runner "
        "fails from now on: reinstall that job, or install the runner again.",
        file=host.out,
    )
    return 0
