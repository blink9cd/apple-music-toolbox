"""`build`: compile the app package, assemble the `.app` bundle, and sign and verify it.

`build_bundle` runs ``swift build -c release`` on the package under ``app/`` beside the
entry script, into a private scratch folder inside the scrobbler's data folder (never
into the checkout, as swift_gate builds, and never under a shared temporary folder where
another user could swap the product before it is signed), asks SwiftPM where it put the
product rather than assuming the layout, and assembles ``<out>/<app name>/Contents/
{MacOS/<executable>, Info.plist}``. With an identity it then signs the bundle and
verifies the signature.

The steps themselves are signed_app's (`app_bundle` builds, assembles and signs,
`app_install.make_private` makes each private folder); this module supplies the
scrobbler's values: its package, its scratch folder, its Automation prompt, the
loopback http key its Info.plist adds, and the signing setting its layout names.

The signing identity is a local setting, read by swift_gate's own reader from a file that
must live outside every checkout: `read_identity` refuses a setting inside one, and refuses
an absent setting with how to write it. The identity is never printed: it is shown only by
`render_identity`, and every codesign output passes through `redact` first. Info.plist
holds no signing value.

A refusal is `Refused` (exit 2); a build, sign or verify that fails is `BuildFailed`
(exit 1). Both carry a message that is safe to print.

Entry point assumptions: imported by the scrobbler's modules, with `src/`, signed_app's
``src/`` and the shared libraries on `sys.path`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

import app_bundle
import swgate_signing
from app_bundle import BuildFailed, Refused, bundle_executable, verify_argv
from app_install import make_private
from scrob_host import Host
from scrob_layout import Layout

__all__ = [
    "APP_PACKAGE_DIRNAME",
    "AUTOMATION_PROMPT",
    "SCRATCH_DIRNAME",
    "BuildFailed",
    "Refused",
    "app_package",
    "assemble",
    "build_bundle",
    "bundle_executable",
    "info_plist",
    "prepare_scratch",
    "read_identity",
    "run_build",
    "scratch_path",
    "swift_build",
    "verify_argv",
]

#: The Swift package's folder, beside the entry script.
APP_PACKAGE_DIRNAME: Final = "app"
#: The folder inside the data folder every build scratches into.
SCRATCH_DIRNAME: Final = ".scratch"
#: How many hex digits of the package path's digest name its scratch folder.
_SCRATCH_HASH_CHARS: Final = 16
#: What macOS shows when the app first asks to read Music.app.
AUTOMATION_PROMPT: Final = (
    "Listensmith Scrobbler reads the track Music is playing so it can log your plays "
    "on this Mac. It never changes playback or your library."
)
#: The App Transport Security rule only the scrobbler's Info.plist carries. The store is
#: plain http on 127.0.0.1; this allows the loopback and local addresses only, never an
#: arbitrary insecure load. Read-only at rest; `info_plist` hands plistlib a plain-dict
#: copy, since plistlib refuses a mapping proxy nested as a value.
_LOCAL_NETWORKING: Final[Mapping[str, object]] = MappingProxyType(
    {"NSAllowsLocalNetworking": True}
)


def app_package(host: Host) -> Path:
    """The Swift package beside this checkout's entry script."""
    return host.script.parent / APP_PACKAGE_DIRNAME


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


def info_plist(layout: Layout) -> bytes:
    """The bundle's Info.plist: its names, its version, the Automation prompt and local http."""
    return app_bundle.info_plist(
        layout,
        automation_prompt=AUTOMATION_PROMPT,
        extra=MappingProxyType({"NSAppTransportSecurity": dict(_LOCAL_NETWORKING)}),
    )


def swift_build(host: Host, layout: Layout) -> Path:
    """Build the package in release and return the built executable's path."""
    scratch = prepare_scratch(host, layout)
    return app_bundle.swift_build(host, app_package(host), scratch, layout.executable)


def assemble(layout: Layout, out_dir: Path, built: Path) -> Path:
    """Assemble the bundle in `out_dir` from the `built` executable; return the bundle."""
    return app_bundle.assemble(layout, out_dir, built, info_plist(layout))


def read_identity(host: Host, layout: Layout) -> str:
    """The configured signing identity; Refused when absent, inside a checkout or malformed."""
    return app_bundle.read_identity(host, layout.paths(host.home).signing_config)


def build_bundle(
    host: Host, layout: Layout, out_dir: Path, identity: str | None
) -> Path:
    """Build, assemble and, with an `identity`, sign and verify; return the bundle."""
    built = swift_build(host, layout)
    bundle = assemble(layout, out_dir, built)
    if identity is not None:
        app_bundle.sign_bundle(host, bundle, identity)
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
