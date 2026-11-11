"""Read ``[tool.swift_gate]`` from the nearest ``pyproject.toml`` above the target.

Private to ``swift_gate``. Two keys: ``exclude`` (paths relative to that pyproject's dir,
pruned from discovery and from the coverage scope) and ``macos_floor`` (the one deployment
floor every package must declare exactly). The floor has no default on purpose: a gate
that silently assumed one would pass a package against a floor nobody chose, so a missing
key is exit 2 through :func:`require_floor`.

The walk, the parse and the exclude list's validation are ``pyproject_config``'s, the
family's one config policy: the NEAREST pyproject answers, even when it lacks the table,
so nothing above the checkout can supply a floor, and a diagnostic names that file
relative to the target rather than by its absolute path, which would carry the home
directory's layout. Only the
scalar ``macos_floor`` is validated here, as that library leaves scalars to its caller.

Entry point assumptions
-----------------------
Reads the filesystem through two injectable seams (``is_file`` / ``read_text``) and
nothing else. Needs the ``pyproject_config`` sibling library, resolved from this file's
own location.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent.parent / "pyproject_config")
)

import pyproject_config  # noqa: E402 - import follows the sys.path bootstrap above

from swgate_model import Config, ConfigError  # noqa: E402 - same

_TABLE = "swift_gate"  # the pyproject [tool.<name>] table this tool reads
_EXCLUDE_KEY = "exclude"  # the path-list key, resolved against the pyproject's dir
_FLOOR_KEY = "macos_floor"  # the scalar key, validated here


def read_config(
    start: Path,
    *,
    is_file: pyproject_config.IsFileFn = pyproject_config.default_is_file,
    read_text: pyproject_config.ReadTextFn = pyproject_config.default_read_text,
) -> Config:
    """The ``[tool.swift_gate]`` config of the nearest pyproject at or above *start*.

    No pyproject, or a nearest one without the table, gives an empty :class:`Config`.
    A malformed file or a wrongly typed value raises :class:`ConfigError`, whose message
    carries no absolute path.
    """
    try:
        found = pyproject_config.read_tool_table(
            start, table=_TABLE, is_file=is_file, read_text=read_text
        )
        if found is None:
            return Config()
        excludes = pyproject_config.read_path_lists(
            start,
            table=_TABLE,
            keys=(_EXCLUDE_KEY,),
            is_file=is_file,
            read_text=read_text,
        )[_EXCLUDE_KEY]
    except pyproject_config.ConfigError as exc:
        # One exit-2 class for the whole tool: callers catch swgate_model's ConfigError.
        raise ConfigError(str(exc)) from exc
    _, table = found
    return Config(excludes=tuple(excludes), macos_floor=_floor_from(table))


def _floor_from(table: dict[str, object]) -> str | None:
    """The table's ``macos_floor``, None when absent; :class:`ConfigError` if not a string."""
    floor = table.get(_FLOOR_KEY)
    if floor is not None and not isinstance(floor, str):
        raise ConfigError(f'[tool.{_TABLE}] {_FLOOR_KEY} must be a string, like "14"')
    return floor


def require_floor(config: Config) -> str:
    """The configured macOS floor; :class:`ConfigError` when the key is missing."""
    if config.macos_floor is None:
        raise ConfigError(
            f"no [tool.{_TABLE}] {_FLOOR_KEY} in the nearest pyproject.toml: the floor "
            'is never a silent default; set it, for example macos_floor = "14"'
        )
    return config.macos_floor
