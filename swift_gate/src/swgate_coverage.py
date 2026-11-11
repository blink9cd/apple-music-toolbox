"""Parse the ``llvm-cov export`` JSON SwiftPM writes, and measure region coverage.

Private to ``swift_gate``. The shape read here was verified live against Swift 6.4
(``swift_gate.md`` -> *Coverage parsing*): ``data[0].functions[]`` each carry
``filenames`` and ``regions``, and each region is the 8-tuple ``[line_start, col_start,
line_end, col_end, count, file_id, expanded_file_id, kind]``, where ``file_id`` indexes
that function's ``filenames``. Only ``kind == 0`` (a code region) is measured: expansion,
skipped, gap and branch regions are not statements a test can execute.

Why regions and not branches: Swift's export reports ``branches.count == 0`` for code with
real untested outcomes, so a branch percent would read 100% over nothing. Regions are the
unit llvm-cov actually counts for Swift.

Entry point assumptions
-----------------------
Pure apart from ``Path.resolve`` on the filenames the export names, which lets a symlinked
temp dir (``/var`` versus ``/private/var``) compare equal to the package root.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from swgate_model import ParseError

_CODE_REGION = 0
_REGION_FIELDS = 8
_PERCENT = 100.0

# The identity of a region regardless of its hit count: file and span.
RegionKey = tuple[Path, int, int, int, int]


@dataclass(frozen=True)
class Region:
    """One code region inside the package's ``Sources/``."""

    file: Path
    line: int
    col: int
    end_line: int
    end_col: int
    count: int

    @property
    def key(self) -> RegionKey:
        """The region's span, the unit a marker excludes and duplicates collapse on."""
        return (self.file, self.line, self.col, self.end_line, self.end_col)


@dataclass(frozen=True)
class FunctionRegions:
    """One function's measured code regions, in export order."""

    file: Path
    regions: tuple[Region, ...]


@dataclass(frozen=True)
class Measurement:
    """Covered over total code regions, after marker exclusions.

    ``percent`` is None when nothing was measured: distinct from 0.0, because a vacuous
    reading must never be compared against a threshold as though it were real.
    """

    covered: int
    total: int
    percent: float | None
    misses: tuple[str, ...]


def parse_export(  # fuzz-target
    text: str, package: Path, excludes: Sequence[Path]
) -> tuple[FunctionRegions, ...]:
    """The functions with code regions under *package*/``Sources``, minus *excludes*."""
    try:
        data = json.loads(text)
        functions = data["data"][0]["functions"]
        if not isinstance(functions, list):
            raise TypeError("functions is not an array")
        scope = _Scope(package.resolve() / "Sources", tuple(excludes))
        parsed = (_function(entry, scope) for entry in functions)
        return tuple(function for function in parsed if function.regions)
    except (ValueError, KeyError, IndexError, TypeError, OverflowError) as exc:
        raise ParseError(f"coverage export has an unexpected shape: {exc!r}") from exc


@dataclass(frozen=True)
class _Scope:
    """Which files count: under the package's Sources/, and under no exclude."""

    sources: Path
    excludes: tuple[Path, ...]

    def admits(self, file: Path) -> bool:
        """True when *file* is package source this gate measures."""
        inside = file == self.sources or self.sources in file.parents
        return inside and not any(
            file == ex or ex in file.parents for ex in self.excludes
        )


def _function(entry: object, scope: _Scope) -> FunctionRegions:
    """One export function, keeping only its in-scope code regions."""
    if not isinstance(entry, dict):
        raise TypeError("a function entry is not an object")
    files = [Path(str(name)).resolve() for name in entry["filenames"]]
    regions = tuple(
        region
        for region in (_region(raw, files) for raw in entry["regions"])
        if region is not None and scope.admits(region.file)
    )
    return FunctionRegions(files[0] if files else Path(), regions)


def _region(raw: object, files: Sequence[Path]) -> Region | None:
    """A code region from its 8-tuple, or None for any other kind."""
    if not isinstance(raw, list) or len(raw) != _REGION_FIELDS:
        raise TypeError(f"a region is not an {_REGION_FIELDS}-tuple: {raw!r}")
    line, col, end_line, end_col, count, file_id, _expanded, kind = (
        int(value) for value in raw
    )
    if kind != _CODE_REGION:
        return None
    return Region(files[file_id], line, col, end_line, end_col, count)


def measure(
    functions: Sequence[FunctionRegions],
    excluded: frozenset[RegionKey],
    package: Path,
) -> Measurement:
    """Covered / total over every distinct region not in *excluded*.

    A span reported more than once (one function compiled into two instantiations)
    counts once, and is covered if any report of it executed.
    """
    hits: dict[RegionKey, int] = {}
    for function in functions:
        for region in function.regions:
            if region.key not in excluded:
                hits[region.key] = max(hits.get(region.key, 0), region.count)
    total = len(hits)
    covered = sum(1 for count in hits.values() if count > 0)
    misses = tuple(_render(key, package) for key in sorted(hits) if hits[key] == 0)
    percent = _PERCENT * covered / total if total else None
    return Measurement(covered, total, percent, misses)


def _render(key: RegionKey, package: Path) -> str:
    """``file:line:col``, the file relative to *package*."""
    file, line, col = key[0], key[1], key[2]
    return f"{os.path.relpath(file, package.resolve())}:{line}:{col}"
