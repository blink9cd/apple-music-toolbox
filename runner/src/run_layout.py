"""The runner's layout: its names, its version and every home-relative path.

One JSON file, ``layout.json`` beside this module's folder, holds them. Every later
module reads a path only through `load_layout` and `RunLayout.paths`, so a name or a
folder changes in one place.

A layout file the loader cannot trust (unreadable, not a JSON object, a missing, unknown,
empty or non-string key, a path value that is not home-relative or holds a ".." part,
or a name that is not one path part) is a `LayoutError` naming the problem, never a
partial layout. Those last two refusals are what keep every derived path under the home
a caller names.

Entry point assumptions: imported with this folder on ``sys.path``; reads no environment
and never touches the real home, which a caller passes to `RunLayout.paths`.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: The layout file, beside this module's ``src/`` folder.
LAYOUT_FILE: Final = Path(__file__).resolve().parents[1] / "layout.json"
#: The keys whose values are paths under the home a caller names.
_PATH_KEYS: Final = frozenset({"data_dir", "signing_config"})
#: The keys whose values each name one file or folder inside a derived folder.
_NAME_KEYS: Final = frozenset(
    {"app_name", "launchd_label", "grant_label", "executable"}
)
#: The path parts that would step out of, or stay at, the folder they are joined to.
_DOT_PARTS: Final = frozenset({".", ".."})


class LayoutError(ValueError):
    """The layout file cannot be read or does not hold exactly the expected keys."""


@dataclass(frozen=True)
class RunPaths:
    """Every file and folder the runner's command line reads or writes, under one home."""

    data_dir: Path
    app_bundle: Path
    logs_dir: Path
    grant_err_log: Path
    grant_dir: Path
    grant_result: Path
    signer_record: Path
    signing_config: Path
    grant_plist: Path


@dataclass(frozen=True)
class RunLayout:
    """The layout file's values, one field per key, each spelled as its key."""

    version: str
    bundle_id: str
    launchd_label: str
    grant_label: str
    display_name: str
    app_name: str
    executable: str
    data_dir: str
    signing_config: str

    def paths(self, home: Path) -> RunPaths:
        """Every path the runner's command line uses, derived under *home*."""
        data = home / self.data_dir
        logs = data / "logs"
        grant = data / "grant"
        return RunPaths(
            data_dir=data,
            app_bundle=data / self.app_name,
            logs_dir=logs,
            grant_err_log=logs / "grant.err.log",
            grant_dir=grant,
            grant_result=grant / "result.json",
            signer_record=data / "signer_requirement.txt",
            signing_config=home / self.signing_config,
            # In the runner's own folder, not ~/Library/LaunchAgents: launchd loads every
            # plist there at login, and an uninstall launchd cannot confirm keeps its
            # plist for a retry. `launchctl bootstrap` takes a plist at any path.
            grant_plist=grant / f"{self.grant_label}.plist",
        )


def layout_keys() -> frozenset[str]:
    """The keys a layout file must hold: `RunLayout`'s field names, exactly."""
    return frozenset(field.name for field in dataclasses.fields(RunLayout))


def _read_object(path: Path) -> dict[str, object]:
    """The JSON object in *path*, or a LayoutError saying why there is none."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        raise LayoutError(f"cannot read the layout file: {error}") from error
    except json.JSONDecodeError as error:
        raise LayoutError(f"the layout file is not JSON: {error}") from error
    if not isinstance(document, dict):
        raise LayoutError("the layout file must hold one JSON object")
    return document


def _check_keys(document: dict[str, object]) -> None:
    """Refuse a missing or an unknown key, naming every one."""
    expected = layout_keys()
    missing = sorted(expected - document.keys())
    if missing:
        raise LayoutError(f"the layout file is missing key(s): {', '.join(missing)}")
    unknown = sorted(document.keys() - expected)
    if unknown:
        raise LayoutError(f"the layout file has unknown key(s): {', '.join(unknown)}")


def _check_value(key: str, value: object) -> str:
    """*value*, once it is a nonempty string that stays where it is joined.

    A path key must be home-relative with no ".." part; a name key must be one path part.
    """
    if not isinstance(value, str):
        raise LayoutError(f"layout key {key} must be a string")
    if not value:
        raise LayoutError(f"layout key {key} is empty")
    # "~" would be expanded by nothing here and read as a folder literally named "~".
    if key in _PATH_KEYS and (Path(value).is_absolute() or value.startswith("~")):
        raise LayoutError(f"layout key {key} must be relative to the home folder")
    if key in _PATH_KEYS and ".." in Path(value).parts:
        raise LayoutError(f"layout key {key} must not hold a .. part")
    if key in _NAME_KEYS and ("/" in value or value in _DOT_PARTS):
        raise LayoutError(f"layout key {key} must be one path part, not . or ..")
    return value


def load_layout(path: Path = LAYOUT_FILE) -> RunLayout:
    """Read and check the layout file at *path*; raise LayoutError when it is untrusted."""
    document = _read_object(path)
    _check_keys(document)
    values = {key: _check_value(key, document[key]) for key in sorted(document)}
    return RunLayout(**values)
