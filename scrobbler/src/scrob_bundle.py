"""`build`: compile the app package, assemble the `.app` bundle, and sign and verify it.

`build_bundle` runs ``swift build -c release`` on the package under ``app/`` beside the
entry script, into a private scratch folder inside the scrobbler's data folder (never
into the checkout, as swift_gate builds, and never under a shared temporary folder where
another user could swap the product before it is signed), asks SwiftPM where it put the product rather than
assuming the layout, and assembles ``<out>/<app name>/Contents/{MacOS/<executable>,
Info.plist}``. With an identity it then signs the bundle and verifies the signature.

The signing identity is a local setting, read by swift_gate's own reader from a file that
must live outside every checkout: `read_identity` refuses a setting inside one, and refuses
an absent setting with how to write it. The identity is never printed: it is shown only by
`render_identity`, and every codesign output passes through `redact` first. Info.plist
holds no signing value.

`make_private` makes every folder the scrobbler keeps to itself: mode 0700, refusing a
symbolic link planted where the folder should be, so a chmod never lands on its target.

A refusal is `Refused` (exit 2); a build, sign or verify that fails is `BuildFailed`
(exit 1). Both carry a message that is safe to print.

Entry point assumptions: imported by the scrobbler's modules, with `src/` and the shared
libraries on `sys.path`.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import shutil
import subprocess
from pathlib import Path
from typing import Final

import swgate_signing
from scrob_host import Host
from scrob_layout import Layout

#: The Swift package's folder, beside the entry script.
APP_PACKAGE_DIRNAME: Final = "app"
#: The folder inside the data folder every build scratches into.
SCRATCH_DIRNAME: Final = ".scratch"
#: The mode of every folder the scrobbler keeps to itself: its user's alone.
PRIVATE_MODE: Final = 0o700
#: How many hex digits of the package path's digest name its scratch folder.
_SCRATCH_HASH_CHARS: Final = 16
#: The bound on one swift build: a cold release build of the package takes minutes.
SWIFT_TIMEOUT_S: Final = 900.0
#: The bound on one codesign call.
CODESIGN_TIMEOUT_S: Final = 60.0
#: The bound on one git call.
GIT_TIMEOUT_S: Final = 5.0
#: The oldest macOS the app runs on, as the package's platform floor states it.
MINIMUM_SYSTEM: Final = "14.0"
#: What macOS shows when the app first asks to read Music.app.
AUTOMATION_PROMPT: Final = (
    "listensmith scrobbler reads the track Music is playing so it can log your plays "
    "on this Mac. It never changes playback or your library."
)
#: The bundle's executable folder and its property list, inside `Contents/`.
_CONTENTS: Final = "Contents"
_MACOS: Final = "MacOS"
_INFO_PLIST: Final = "Info.plist"


class Refused(Exception):
    """The command will not run as asked; its message says why and is safe to print."""


class BuildFailed(Exception):
    """A build, sign or verify step failed; its message is safe to print."""


def app_package(host: Host) -> Path:
    """The Swift package beside this checkout's entry script."""
    return host.script.parent / APP_PACKAGE_DIRNAME


def make_private(folder: Path) -> None:
    """Create `folder` and its parents, the folder itself mode 0700; Refused for a symlink."""
    if folder.is_symlink():
        raise Refused(
            f"{folder} is a symbolic link; refusing to use it as a private folder"
        )
    folder.mkdir(mode=PRIVATE_MODE, parents=True, exist_ok=True)
    # Not following links where the platform can say so; the check above already refused
    # one, and Linux has no lchmod, so there the call must follow.
    os.chmod(
        folder,
        PRIVATE_MODE,
        follow_symlinks=os.chmod not in os.supports_follow_symlinks,
    )


def scratch_path(host: Host, layout: Layout) -> Path:
    """The package's own scratch folder in the data folder, keyed on the package's path."""
    resolved = str(app_package(host).resolve()).encode("utf-8")
    digest = hashlib.sha256(resolved).hexdigest()[:_SCRATCH_HASH_CHARS]
    return layout.paths(host.home).data_dir / SCRATCH_DIRNAME / digest


def prepare_scratch(host: Host, layout: Layout) -> Path:
    """The scratch folder, made private along with the two folders that hold it."""
    scratch = scratch_path(host, layout)
    for folder in (scratch.parent.parent, scratch.parent, scratch):
        make_private(folder)
    return scratch


def bundle_executable(bundle: Path, layout: Layout) -> Path:
    """The executable inside `bundle`."""
    return bundle / _CONTENTS / _MACOS / layout.executable


def info_plist(layout: Layout) -> bytes:
    """The bundle's Info.plist: its names, its version, the Automation prompt and local http."""
    return plistlib.dumps(
        {
            "CFBundleIdentifier": layout.bundle_id,
            "CFBundleName": layout.display_name,
            "CFBundleDisplayName": layout.display_name,
            "CFBundleExecutable": layout.executable,
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": layout.version,
            "CFBundleVersion": layout.version,
            "LSMinimumSystemVersion": MINIMUM_SYSTEM,
            "LSUIElement": True,
            "NSAppleEventsUsageDescription": AUTOMATION_PROMPT,
            # The store is plain http on 127.0.0.1; this allows the loopback and local
            # addresses only, never an arbitrary insecure load.
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        }
    )


def _run(
    host: Host, argv: list[str], timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run one tool from the package folder; one that cannot run is BuildFailed."""
    try:
        return host.run(argv, cwd=host.script.parent, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BuildFailed(f"could not run {argv[0]} ({type(error).__name__})") from None


def _last_line(done: subprocess.CompletedProcess[str]) -> str:
    """The last line of a tool's output, stderr first, for a one-line failure."""
    lines = (done.stderr or done.stdout).strip().splitlines()
    return lines[-1] if lines else "no output"


def swift_build(host: Host, layout: Layout) -> Path:
    """Build the package in release and return the built executable's path."""
    scratch = prepare_scratch(host, layout)
    common = [
        "swift",
        "build",
        "-c",
        "release",
        "--package-path",
        str(app_package(host)),
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
    built = Path(lines[-1].strip()) / layout.executable
    if not built.is_file():
        raise BuildFailed(
            f"swift build left no {layout.executable} in its product folder"
        )
    return built


def assemble(layout: Layout, out_dir: Path, built: Path) -> Path:
    """Assemble the bundle in `out_dir` from the `built` executable; return the bundle."""
    bundle = out_dir / layout.app_name
    if bundle.exists():
        raise Refused(f"{bundle} already exists; remove it or choose another --out")
    executable = bundle_executable(bundle, layout)
    try:
        executable.parent.mkdir(parents=True)
        shutil.copy2(built, executable)
        (bundle / _CONTENTS / _INFO_PLIST).write_bytes(info_plist(layout))
    except OSError as error:
        raise BuildFailed(
            f"could not assemble {bundle} ({type(error).__name__})"
        ) from None
    return bundle


def read_identity(host: Host, layout: Layout) -> str:
    """The configured signing identity; Refused when absent, inside a checkout or malformed."""
    setting_path = layout.paths(host.home).signing_config
    try:
        roots = (
            *swgate_signing.checkout_roots(
                host.script.parent, host.run, timeout=GIT_TIMEOUT_S
            ),
            *swgate_signing.enclosing_checkout(
                setting_path, host.run, timeout=GIT_TIMEOUT_S
            ),
        )
        setting = swgate_signing.read_signing_identity(
            setting_path, checkout_roots=roots
        )
    except swgate_signing.SigningConfigError as error:
        raise Refused(str(error)) from None
    if isinstance(setting, swgate_signing.NotConfigured):
        shown = swgate_signing.render_path(setting_path, host.home)
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


def verify_argv(bundle: Path) -> list[str]:
    """The strict signature check of `bundle`."""
    return ["codesign", "--verify", "--strict", "--verbose=2", str(bundle)]


def sign_bundle(host: Host, bundle: Path, identity: str) -> None:
    """Sign `bundle` with `identity`, then verify the signature strictly."""
    sign = ["codesign", "--force", "--sign", identity, "--timestamp=none", str(bundle)]
    _codesign(host, identity, "sign", sign)
    _codesign(host, identity, "verify", verify_argv(bundle))


def build_bundle(
    host: Host, layout: Layout, out_dir: Path, identity: str | None
) -> Path:
    """Build, assemble and, with an `identity`, sign and verify; return the bundle."""
    built = swift_build(host, layout)
    bundle = assemble(layout, out_dir, built)
    if identity is not None:
        sign_bundle(host, bundle, identity)
    return bundle


def run_build(host: Host, layout: Layout, out_dir: Path, *, sign: bool) -> int:
    """`build --out DIR [--sign]`: 0 built, and with --sign signed and verified."""
    identity = read_identity(host, layout) if sign else None
    bundle = build_bundle(host, layout, out_dir, identity)
    note = ""
    if identity is not None:
        note = f", signed and verified with {swgate_signing.render_identity(identity)}"
    print(f"built {bundle}{note}", file=host.out)
    return 0
