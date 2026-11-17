"""Build a Swift package's executable, assemble it into an `.app` bundle, and sign it.

`swift_build` runs ``swift build -c release`` on the package a caller names, into the
scratch folder a caller has already made private (never into the checkout, as swift_gate
builds, and never under a shared temporary folder where another user could swap the
product before it is signed), and asks SwiftPM where it put the product rather than
assuming the layout. `assemble` lays out ``<out>/<app name>/Contents/{MacOS/<executable>,
Info.plist}`` from the built executable and the property list `info_plist` writes.
`sign_bundle` signs the bundle and verifies the signature strictly.
`designated_requirement` reads the signature's designated requirement, which an app can
record and later demand of its installed bundle through `verify_argv`'s `requirement`.

The signing identity is a local setting, read by swift_gate's own reader from a file that
must live outside every checkout: `read_identity` refuses a setting inside one, and
refuses an absent setting with how to write it. The identity is never printed: every
codesign output passes through `redact` first. Info.plist holds no signing value.

A refusal is `Refused` (exit 2); a build, sign or verify that fails is `BuildFailed`
(exit 1). Both carry a message that is safe to print.

Entry point assumptions: imported by an app's modules, with this library's ``src/`` and
the shared libraries on `sys.path`. Every tool runs from the entry script's folder.
"""

from __future__ import annotations

import plistlib
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol

import swgate_signing
from app_host import Host

#: The bound on one swift build: a cold release build of a package takes minutes.
SWIFT_TIMEOUT_S: Final = 900.0
#: The bound on one codesign call.
CODESIGN_TIMEOUT_S: Final = 60.0
#: The bound on one git call.
GIT_TIMEOUT_S: Final = 5.0
#: The oldest macOS an app runs on, as each package's platform floor states it.
MINIMUM_SYSTEM: Final = "14.0"
#: The bundle's executable folder and its property list, inside `Contents/`.
_CONTENTS: Final = "Contents"
_MACOS: Final = "MacOS"
_INFO_PLIST: Final = "Info.plist"
#: codesign --verify's exit for a valid signature that does not meet the -R requirement.
REQUIREMENT_UNMET_EXIT: Final = 3
#: The line of ``codesign -d -r-``'s standard output that states the designated
#: requirement. An implicit one (an ad hoc signature's) is marked as a comment.
_DESIGNATED: Final = re.compile(r"^(?:# )?designated => (.*)$")
#: No extra Info.plist keys: read-only, so the shared default can never be changed.
_NO_EXTRA: Final[Mapping[str, object]] = MappingProxyType({})


class Refused(Exception):
    """The command will not run as asked; its message says why and is safe to print."""


class BuildFailed(Exception):
    """A build, sign or verify step failed; its message is safe to print."""


class BundleSpec(Protocol):
    """A bundle's names and version, as an app's layout holds them.

    Read-only, so a frozen dataclass's fields satisfy it.
    """

    @property
    def bundle_id(self) -> str:
        """The bundle identifier, `CFBundleIdentifier`."""

    @property
    def display_name(self) -> str:
        """The name macOS shows, `CFBundleName` and `CFBundleDisplayName`."""

    @property
    def executable(self) -> str:
        """The executable's file name in `Contents/MacOS/`, and SwiftPM's product."""

    @property
    def version(self) -> str:
        """The version both version keys carry."""

    @property
    def app_name(self) -> str:
        """The bundle folder's name, ending in `.app`."""


def bundle_executable(bundle: Path, bundle_info: BundleSpec) -> Path:
    """The executable inside `bundle`."""
    return bundle / _CONTENTS / _MACOS / bundle_info.executable


def info_plist(
    bundle_info: BundleSpec,
    *,
    automation_prompt: str,
    extra: Mapping[str, object] = _NO_EXTRA,
) -> bytes:
    """The bundle's Info.plist: its names, its version, the Automation prompt, and `extra`.

    `extra` is merged last, so a key it holds replaces the one built here.
    """
    return plistlib.dumps(
        {
            "CFBundleIdentifier": bundle_info.bundle_id,
            "CFBundleName": bundle_info.display_name,
            "CFBundleDisplayName": bundle_info.display_name,
            "CFBundleExecutable": bundle_info.executable,
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": bundle_info.version,
            "CFBundleVersion": bundle_info.version,
            "LSMinimumSystemVersion": MINIMUM_SYSTEM,
            "LSUIElement": True,
            "NSAppleEventsUsageDescription": automation_prompt,
            **extra,
        }
    )


def _run(
    host: Host, argv: list[str], timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run one tool from the entry script's folder; one that cannot run is BuildFailed."""
    try:
        return host.run(argv, cwd=host.script.parent, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BuildFailed(f"could not run {argv[0]} ({type(error).__name__})") from None


def _last_line(done: subprocess.CompletedProcess[str]) -> str:
    """The last line of a tool's output, stderr first, for a one-line failure."""
    lines = (done.stderr or done.stdout).strip().splitlines()
    return lines[-1] if lines else "no output"


def swift_build(host: Host, package: Path, scratch: Path, executable: str) -> Path:
    """Build `package` in release into `scratch`; return the built `executable`'s path."""
    common = [
        "swift",
        "build",
        "-c",
        "release",
        "--package-path",
        str(package),
        "--scratch-path",
        str(scratch),
    ]
    done = _run(host, common, SWIFT_TIMEOUT_S)
    if done.returncode != 0:
        raise BuildFailed(
            f"swift build failed (exit {done.returncode}): {_last_line(done)}"
        )
    where = _run(host, [*common, "--show-bin-path"], SWIFT_TIMEOUT_S)
    lines = where.stdout.strip().splitlines()
    if where.returncode != 0 or not lines:
        raise BuildFailed("swift build --show-bin-path did not name the product folder")
    built = Path(lines[-1].strip()) / executable
    if not built.is_file():
        raise BuildFailed(f"swift build left no {executable} in its product folder")
    return built


def assemble(bundle_info: BundleSpec, out_dir: Path, built: Path, plist: bytes) -> Path:
    """Assemble the bundle in `out_dir` from `built` and the `plist`; return the bundle."""
    bundle = out_dir / bundle_info.app_name
    if bundle.exists():
        raise Refused(f"{bundle} already exists; remove it or choose another --out")
    executable = bundle_executable(bundle, bundle_info)
    try:
        executable.parent.mkdir(parents=True)
        shutil.copy2(built, executable)
        (bundle / _CONTENTS / _INFO_PLIST).write_bytes(plist)
    except OSError as error:
        raise BuildFailed(
            f"could not assemble {bundle} ({type(error).__name__})"
        ) from None
    return bundle


def read_identity(host: Host, signing_config: Path) -> str:
    """The identity set in `signing_config`; Refused when absent, in a checkout or malformed."""
    try:
        roots = (
            *swgate_signing.checkout_roots(
                host.script.parent, host.run, timeout=GIT_TIMEOUT_S
            ),
            *swgate_signing.enclosing_checkout(
                signing_config, host.run, timeout=GIT_TIMEOUT_S
            ),
        )
        setting = swgate_signing.read_signing_identity(
            signing_config, checkout_roots=roots
        )
    except swgate_signing.SigningConfigError as error:
        raise Refused(str(error)) from None
    if isinstance(setting, swgate_signing.NotConfigured):
        shown = swgate_signing.render_path(signing_config, host.home)
        raise Refused(
            f'no signing identity is set: write identity = "<codesign identity>" to '
            f"{shown}, a file outside every checkout, then run this again"
        )
    return setting.identity


def _codesign(host: Host, identity: str, step: str, argv: list[str]) -> None:
    """Run one codesign step; a nonzero exit is BuildFailed with its output redacted."""
    done = _run(host, argv, CODESIGN_TIMEOUT_S)
    if done.returncode != 0:
        output = swgate_signing.redact(
            (done.stdout + done.stderr).strip(), identity, home=host.home
        )
        raise BuildFailed(f"codesign {step} failed (exit {done.returncode}):\n{output}")


def verify_argv(bundle: Path, requirement: str | None = None) -> list[str]:
    """The strict signature check of `bundle`; with `requirement`, demanding it too.

    codesign reads ``-R``'s value as a file path unless it starts with ``=``, which marks
    the rest as requirement text, so the text travels as ``-R=<text>``. A signature that
    is valid but does not meet the requirement exits `REQUIREMENT_UNMET_EXIT`.
    """
    demand = [] if requirement is None else [f"-R={requirement}"]
    return ["codesign", "--verify", "--strict", "--verbose=2", *demand, str(bundle)]


def _designated_line(stdout: str) -> str | None:
    """The requirement on the one ``designated =>`` line of codesign's display, if one."""
    found = [
        match.group(1).strip()
        for match in map(_DESIGNATED.match, stdout.splitlines())
        if match is not None
    ]
    return found[0] if len(found) == 1 and found[0] else None


def designated_requirement(host: Host, bundle: Path) -> str:
    """The designated requirement of `bundle`'s signature, as codesign states it.

    It names the signing certificate, so neither it nor codesign's output is ever put in
    a message: a display that fails, or that does not print exactly one requirement, is
    BuildFailed saying only which.
    """
    done = _run(host, ["codesign", "-d", "-r-", str(bundle)], CODESIGN_TIMEOUT_S)
    if done.returncode != 0:
        raise BuildFailed(
            "codesign could not read the app's designated requirement "
            f"(exit {done.returncode})"
        )
    requirement = _designated_line(done.stdout)
    if requirement is None:
        raise BuildFailed("codesign did not print one designated requirement")
    return requirement


def sign_bundle(host: Host, bundle: Path, identity: str) -> None:
    """Sign `bundle` with `identity`, then verify the signature strictly."""
    sign = ["codesign", "--force", "--sign", identity, "--timestamp=none", str(bundle)]
    _codesign(host, identity, "sign", sign)
    _codesign(host, identity, "verify", verify_argv(bundle))
