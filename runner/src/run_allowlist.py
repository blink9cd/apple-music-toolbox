"""The runner's allowlist: the one interpreter and the scripts the installed app may start.

``allowlist.json`` beside this module's folder names the scripts, each relative to the
repository root, so the file holds no machine's paths. A build resolves them against the
checkout that holds the entry script (the folder git names for it) and pairs them with
the interpreter running the build, unresolved: a virtual environment's ``python`` is a
link, and the allowlist must hold the link's own path, the very string a scheduled job
passes. The resolved value is written into the bundle's Info.plist under `INFO_KEY`,
which the signature then covers.

`resolve` refuses anything that could name a file outside the checkout (an absolute
entry, a ``~``, a ``..`` part), an entry that is not a file, and an interpreter that is
not an absolute path. `from_info_value` and `check` read an installed bundle's value back
exactly as the Swift runner does: an exact string match, no path normalized.

A refusal is `app_bundle.Refused` (exit 2), with a message that is safe to print.

Entry point assumptions: imported by the runner's modules, with `src/`, signed_app's
``src/`` and the shared libraries on `sys.path`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final, TypedDict

from app_bundle import GIT_TIMEOUT_S, Refused
from app_host import Host

#: The allowlist file, beside this module's ``src/`` folder.
ALLOWLIST_FILE: Path = Path(__file__).resolve().parents[1] / "allowlist.json"
#: The Info.plist key the build writes the allowlist under; the Swift runner reads it.
INFO_KEY: Final = "AMTRunnerAllowlist"
#: The allowlist file's one key.
_SCRIPTS_KEY: Final = "scripts"
#: The Swift runner's own words for each refusal, so both halves say the same thing.
NOT_ALLOWED: Final = "not in the runner's allowlist: {path}"
UNREADABLE: Final = "the runner's allowlist is missing or malformed"


class Allowlist(TypedDict):
    """The value under `INFO_KEY`: the interpreter and the scripts, all absolute paths."""

    python: str
    scripts: list[str]


def _unchecked(_path: Path) -> bool:
    """Take every path as a file: `resolve`'s default, for a caller with no checkout."""
    return True


def load(path: Path = ALLOWLIST_FILE) -> object:
    """The JSON document in the allowlist file; Refused when there is none to read.

    Its shape is `resolve`'s to judge.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        raise Refused(
            f"cannot read the allowlist file ({type(error).__name__})"
        ) from None
    except json.JSONDecodeError as error:
        raise Refused(f"the allowlist file is not JSON: {error}") from None


def _entries(document: object) -> list[str]:
    """The script entries of an allowlist document, once it holds exactly a list of text."""
    if not isinstance(document, dict) or document.keys() != {_SCRIPTS_KEY}:
        raise Refused(f"the allowlist file must hold one key, {_SCRIPTS_KEY}")
    entries = document[_SCRIPTS_KEY]
    if not isinstance(entries, list) or not all(
        isinstance(entry, str) for entry in entries
    ):
        raise Refused(f"the allowlist's {_SCRIPTS_KEY} must be a list of paths")
    return entries


def _script_path(entry: str, root: Path, is_file: Callable[[Path], bool]) -> str:
    """`entry` under `root`, refused when it could leave `root` or is not a file."""
    if not entry:
        raise Refused("the allowlist holds an empty path")
    relative = Path(entry)
    # "~" would be expanded by nothing here and read as a folder literally named "~".
    if relative.is_absolute() or entry.startswith("~") or ".." in relative.parts:
        raise Refused(
            f"the allowlist's {entry} must be relative to the repository root, "
            "with no .. part"
        )
    script = root / relative
    if not is_file(script):
        raise Refused(f"the allowlist's {entry} is not a file in {root}")
    return str(script)


def resolve(
    document: object,
    *,
    root: Path,
    python: str,
    is_file: Callable[[Path], bool] = _unchecked,
) -> Allowlist:
    """The allowlist a bundle carries: `python`, and each script joined to `root`.

    `python` is kept exactly as given and must be absolute. `is_file` judges each
    resolved script; by default nothing is read, so this stays pure path arithmetic,
    and `for_host` passes the real check.
    """
    if not Path(python).is_absolute():
        raise Refused(
            f"the interpreter must be an absolute path, not {python or 'unknown'}"
        )
    scripts = [_script_path(entry, root, is_file) for entry in _entries(document)]
    return {"python": python, "scripts": scripts}


def checkout_root(host: Host) -> Path:
    """The root of the checkout holding the entry script, as git names it."""
    folder = host.script.parent
    argv = ["git", "-C", str(folder), "rev-parse", "--show-toplevel"]
    try:
        done = host.run(argv, cwd=folder, timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused(
            f"could not ask git for the checkout that holds {folder} "
            f"({type(error).__name__})"
        ) from None
    lines = done.stdout.strip().splitlines()
    if done.returncode != 0 or not lines:
        raise Refused(
            f"git could not find the checkout that holds {folder} "
            f"(exit {done.returncode}); the allowlist's paths are relative to its root"
        )
    return Path(lines[-1])


def for_host(host: Host) -> Allowlist:
    """The committed allowlist, resolved for the entry script's checkout and this Python.

    Every script must be a file there. The interpreter is `sys.executable` as it stands.
    """
    # The file is named here, at the call, so a test can point the module's name elsewhere.
    return resolve(
        load(ALLOWLIST_FILE),
        root=checkout_root(host),
        python=sys.executable,
        is_file=Path.is_file,
    )


def from_info_value(value: object) -> Allowlist | None:
    """Decode an Info.plist's `INFO_KEY` value; None when any part has another shape."""
    if not isinstance(value, dict):
        return None
    python, scripts = value.get("python"), value.get("scripts")
    if not isinstance(python, str) or not isinstance(scripts, list):
        return None
    if not all(isinstance(script, str) for script in scripts):
        return None
    return {"python": python, "scripts": list(scripts)}


def check(allowlist: Allowlist, *, python: str, script: str) -> None:
    """Refused unless `python` and `script` each match an entry exactly."""
    if python != allowlist["python"]:
        raise Refused(NOT_ALLOWED.format(path=python))
    if script not in allowlist["scripts"]:
        raise Refused(NOT_ALLOWED.format(path=script))
