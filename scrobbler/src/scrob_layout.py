"""The scrobbler's layout: its names, its version and every home-relative path.

One JSON file, ``layout.json`` beside this module's folder, holds them, and both halves
read it: this module at runtime, and the Swift package through constants a Swift test
holds equal to the file. Every later module reads a path only through `load_layout` and
`Layout.paths`, so a name or a folder changes in one place.

A layout file the loader cannot trust (unreadable, not a JSON object, a missing, unknown,
empty or non-string key, a path value that is not home-relative or holds a ".." part,
or a name that is not one path part) is a `LayoutError` naming the problem, never a
partial layout. Those last two refusals are what keep every derived path under the home
a caller names.

Entry point assumptions: imported with this folder on ``sys.path``; reads no environment
and never touches the real home, which a caller passes to `Layout.paths`.
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
_PATH_KEYS: Final = frozenset(
    {"data_dir", "config_file", "token_file", "signing_config", "launch_agents_dir"}
)
#: The keys whose values each name one file or folder inside a derived folder.
_NAME_KEYS: Final = frozenset({"app_name", "launchd_label", "executable"})
#: The path parts that would step out of, or stay at, the folder they are joined to.
_DOT_PARTS: Final = frozenset({".", ".."})


class LayoutError(ValueError):
    """The layout file cannot be read or does not hold exactly the expected keys."""


@dataclass(frozen=True)
class ScrobPaths:
    """Every file and folder the scrobbler reads or writes, under one home."""

    data_dir: Path
    queue_dir: Path
    refused_dir: Path
    state_dir: Path
    status_file: Path
    open_play_file: Path
    lock_file: Path
    logs_dir: Path
    out_log: Path
    err_log: Path
    app_bundle: Path
    config_file: Path
    token_file: Path
    signing_config: Path
    launch_agents_dir: Path
    launch_agent_plist: Path


@dataclass(frozen=True)
class Layout:
    """The layout file's values, one field per key, each spelled as its key."""

    version: str
    submission_client: str
    bundle_id: str
    launchd_label: str
    display_name: str
    app_name: str
    executable: str
    data_dir: str
    config_file: str
    token_file: str
    signing_config: str
    launch_agents_dir: str

    def paths(self, home: Path) -> ScrobPaths:
        """Every path the scrobbler uses, derived under *home*."""
        data = home / self.data_dir
        state = data / "state"
        logs = data / "logs"
        agent_dir = home / self.launch_agents_dir
        return ScrobPaths(
            data_dir=data,
            queue_dir=data / "queue",
            refused_dir=data / "refused",
            state_dir=state,
            status_file=state / "status.json",
            open_play_file=state / "open_play.json",
            lock_file=state / "scrobbler.lock",
            logs_dir=logs,
            out_log=logs / "out.log",
            err_log=logs / "err.log",
            app_bundle=data / self.app_name,
            config_file=home / self.config_file,
            token_file=home / self.token_file,
            signing_config=home / self.signing_config,
            launch_agents_dir=agent_dir,
            launch_agent_plist=agent_dir / f"{self.launchd_label}.plist",
        )


def layout_keys() -> frozenset[str]:
    """The keys a layout file must hold: `Layout`'s field names, exactly."""
    return frozenset(field.name for field in dataclasses.fields(Layout))


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


def load_layout(path: Path = LAYOUT_FILE) -> Layout:
    """Read and check the layout file at *path*; raise LayoutError when it is untrusted."""
    document = _read_object(path)
    _check_keys(document)
    values = {key: _check_value(key, document[key]) for key in sorted(document)}
    return Layout(**values)
