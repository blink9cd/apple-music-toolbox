"""The signer install records, so `status` and `locate` can demand it of the installed app.

A valid signature says only that someone signed the bundle. macOS grants Music.app
automation to a bundle at the installed path that another identity signed, ad hoc
included, so `install` records the designated requirement of the bundle it signed, and
`status` and `locate` then verify the installed bundle against that requirement. This
detects a swapped bundle; it does not stop macOS granting one, and a writer running as
the same user can rewrite this record too.

The record is one line, the requirement's text, in the runner's data folder, at mode
0600, replaced atomically. Its text names the signing certificate, so it is never
printed or logged: every message here names only the kind of failure.

Entry point assumptions: imported by the runner's modules, with `src/`, signed_app's
``src/`` and the shared libraries on `sys.path`.
"""

from __future__ import annotations

from typing import Final

import atomic_write
from app_bundle import BuildFailed, Refused
from app_host import Host
from run_layout import RunPaths

#: The record's mode: its user's alone.
RECORD_MODE: Final = 0o600
#: The most bytes a record may hold; a requirement is one line of well under this.
MAX_RECORD_BYTES: Final = 16_384
#: The runner's words for a bundle whose valid signature is another identity's.
NOT_INSTALLED_SIGNER: Final = (
    "the app is not signed by the identity it was installed with"
)
#: Characters a one-line requirement never holds.
_FORBIDDEN: Final = ("\n", "\r", "\0")


def record_signer(paths: RunPaths, requirement: str) -> None:
    """Record `requirement` as the installed app's signer; BuildFailed when it cannot."""
    try:
        atomic_write.replace_text(
            paths.signer_record, f"{requirement}\n", mode=RECORD_MODE
        )
    except OSError as error:
        raise BuildFailed(
            f"could not record the app's signer ({type(error).__name__})"
        ) from None


def _read_record(host: Host, paths: RunPaths) -> bytes:
    """The record's bytes, up to one past the bound; Refused when absent or unreadable."""
    again = f"run {host.script.name} install again"
    try:
        with paths.signer_record.open("rb") as record:
            return record.read(MAX_RECORD_BYTES + 1)
    except FileNotFoundError:
        raise Refused(f"the app's signer was never recorded; {again}") from None
    except OSError as error:
        raise Refused(
            f"the app's recorded signer cannot be read ({type(error).__name__}); "
            f"{again}"
        ) from None


def _parse_record(data: bytes) -> str | None:
    """The requirement in a record's `data`, or None when it is not one clean line."""
    if len(data) > MAX_RECORD_BYTES or not data.endswith(b"\n"):
        return None
    try:
        text = data[:-1].decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text or text != text.strip() or any(c in text for c in _FORBIDDEN):
        return None
    return text


def recorded_signer(host: Host, paths: RunPaths) -> str:
    """The requirement install recorded; Refused when missing, unreadable or malformed."""
    requirement = _parse_record(_read_record(host, paths))
    if requirement is None:
        raise Refused(
            f"the app's recorded signer is malformed; run {host.script.name} "
            "install again"
        )
    return requirement
