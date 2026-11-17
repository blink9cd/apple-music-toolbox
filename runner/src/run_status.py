"""`status` and `locate`: is the runner app installed and intact, and may a job use it.

Both judge the installed bundle more strictly than the app judges itself: its signature
must verify strictly AND meet the designated requirement `install` recorded
(`run_signer`), so a bundle another identity signed is caught, and only then is the
allowlist in its Info.plist read. codesign's exit tells the two failures apart: a valid
signature that does not meet the requirement exits `REQUIREMENT_UNMET_EXIT`, anything
else nonzero is a signature that does not verify. Neither codesign's output nor the
recorded requirement is ever shown, since both name the signing certificate.

`status` prints a verdict line and its reasons, and exits 2 when the app is not
installed, 1 when the bundle cannot be trusted (its signer was never recorded or the
record cannot be read, its signature fails, another identity signed it, codesign cannot
run, or its allowlist is unreadable) and 0 otherwise, listing what the app may start.

`locate` is what a scheduled job's installer asks before it writes the app into its own
agent: given the interpreter and the script the job will pass, it prints the installed
executable's absolute path on one line. Every reason it cannot is `Refused` (exit 2):
not installed, a signer record missing or unreadable, a signature that does not verify,
another identity's signature, or a path that is not in the installed bundle's
allowlist.

Entry point assumptions: imported by the runner's modules, with `src/`, signed_app's
``src/`` and the shared libraries on `sys.path`.
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path
from typing import Final
from xml.parsers.expat import ExpatError

import run_allowlist
import run_signer
from app_bundle import (
    CODESIGN_TIMEOUT_S,
    REQUIREMENT_UNMET_EXIT,
    Refused,
    bundle_executable,
    verify_argv,
)
from app_host import Host
from run_layout import RunLayout, RunPaths

#: status's exit codes.
EXIT_HEALTHY: Final = 0
EXIT_ATTENTION: Final = 1
EXIT_NOT_INSTALLED: Final = 2
#: The runner app's own words for a bundle whose signature fails.
SIGNATURE_FAILED: Final = "the runner's own signature does not verify"
#: The bundle's property list, inside the bundle.
_INFO_PLIST: Final = Path("Contents") / "Info.plist"


class _Untrusted(Exception):
    """The installed bundle cannot be trusted; its message says why, with no secret."""


def _verify_exit(host: Host, paths: RunPaths) -> int:
    """The exit code of codesign's strict check of the installed bundle's recorded signer.

    Refused when the signer record is missing, unreadable or malformed, before codesign
    runs, and when codesign cannot run at all, so no two cases ever read as one.
    """
    requirement = run_signer.recorded_signer(host, paths)
    try:
        done = host.run(
            verify_argv(paths.app_bundle, requirement),
            cwd=paths.data_dir,
            timeout=CODESIGN_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused(f"codesign could not run ({type(error).__name__})") from None
    return done.returncode


def installed_allowlist(bundle: Path) -> run_allowlist.Allowlist:
    """The allowlist in `bundle`'s Info.plist; Refused when missing or malformed."""
    try:
        info = plistlib.loads((bundle / _INFO_PLIST).read_bytes())
    except (OSError, ValueError, ExpatError):
        # A file that is absent, is not a property list, or is damaged XML.
        raise Refused(run_allowlist.UNREADABLE) from None
    value = info.get(run_allowlist.INFO_KEY) if isinstance(info, dict) else None
    allowlist = run_allowlist.from_info_value(value)
    if allowlist is None:
        raise Refused(run_allowlist.UNREADABLE)
    return allowlist


def _trusted_allowlist(host: Host, paths: RunPaths) -> run_allowlist.Allowlist:
    """The installed bundle's allowlist, read only once its signature has verified."""
    try:
        code = _verify_exit(host, paths)
        if code == REQUIREMENT_UNMET_EXIT:
            raise _Untrusted(run_signer.NOT_INSTALLED_SIGNER)
        if code != 0:
            raise _Untrusted(f"the app fails codesign --verify --strict (exit {code})")
        return installed_allowlist(paths.app_bundle)
    except Refused as error:
        raise _Untrusted(str(error)) from None


def status(host: Host, layout: RunLayout) -> int:
    """Print the installed app's verdict; 2 not installed, 1 untrusted, 0 otherwise."""
    paths = layout.paths(host.home)
    name = layout.display_name
    if not paths.app_bundle.exists():
        print(f"{name}: NOT INSTALLED (exit {EXIT_NOT_INSTALLED})", file=host.out)
        return EXIT_NOT_INSTALLED
    try:
        allowlist = _trusted_allowlist(host, paths)
    except _Untrusted as error:
        print(f"{name}: NEEDS ATTENTION (exit {EXIT_ATTENTION})", file=host.out)
        print(f"- {error}", file=host.out)
        return EXIT_ATTENTION
    lines = [
        f"{name}: HEALTHY (exit {EXIT_HEALTHY})",
        f"- app: {paths.app_bundle}",
        "- signature: verifies, by the identity it was installed with",
        f"- interpreter: {allowlist['python']}",
        *[f"- script: {script}" for script in allowlist["scripts"]],
    ]
    print("\n".join(lines), file=host.out)
    return EXIT_HEALTHY


def locate(host: Host, layout: RunLayout, *, python: str, script: str) -> int:
    """Print the installed executable's path for a job running `script` under `python`.

    Refused when the app is not installed, its signer record cannot be used, its
    signature does not verify or is another identity's, or either path is not in the
    installed bundle's allowlist.
    """
    paths = layout.paths(host.home)
    if not paths.app_bundle.exists():
        raise Refused(
            f"{layout.display_name} is not installed; run {host.script.name} install"
        )
    code = _verify_exit(host, paths)
    if code == REQUIREMENT_UNMET_EXIT:
        raise Refused(run_signer.NOT_INSTALLED_SIGNER)
    if code != 0:
        raise Refused(SIGNATURE_FAILED)
    allowlist = installed_allowlist(paths.app_bundle)
    run_allowlist.check(allowlist, python=python, script=script)
    print(bundle_executable(paths.app_bundle, layout), file=host.out)
    return 0
