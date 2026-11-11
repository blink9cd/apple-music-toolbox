"""The ``// coverage: ignore: <reason>`` marker: SWG003 and SWG004.

Private to ``swift_gate``. Swift has no compiler-honored coverage pragma, so the gate
defines one and applies it to the export itself:

* a marker excludes every code region that **starts on the marker's line**;
* a marker on a line declaring ``func`` or ``init`` also excludes **every region of that
  function**: the function whose first region starts on the first line, at or after the
  marker, whose code holds ``{``. That is how a wrapped signature, whose brace sits on a
  later line, is still reached.

A marker with no reason is SWG003 and excludes nothing: the standard is a pragma *and* a
reason. A reasoned marker that excludes no region at all is SWG004, checked once the
export is in, because a marker left behind after its code moved would otherwise go on
claiming an exemption nobody can see.

Entry point assumptions
-----------------------
Reads the source files it is handed, with ``errors="replace"`` so an undecodable file is
still scanned rather than skipped; no subprocess and no stream.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from swgate_coverage import FunctionRegions, RegionKey
from swgate_model import MARKER_TEXT, Finding

_MARKER_RE = re.compile(r"//\s*" + re.escape(MARKER_TEXT) + r"(?P<rest>.*)$")
_DECLARES_FUNCTION_RE = re.compile(r"\b(?:func|init)\b")


@dataclass(frozen=True)
class Marker:
    """One reasoned marker: where it is and, for a function marker, its body's line."""

    file: Path
    line: int
    reason: str
    declares_function: bool
    body_line: int | None


def _code_part(line: str) -> str:
    """The text of *line* before its ``//`` comment."""
    return line.split("//", 1)[0]


def _reason(rest: str) -> str:
    """The reason after ``ignore:``, or ``""`` when there is none."""
    text = rest.strip()
    return text[1:].strip() if text.startswith(":") else ""


def _body_line(lines: Sequence[str], start: int) -> int | None:
    """The 1-based number of the first line at or after *start* whose code holds ``{``."""
    for number in range(start, len(lines) + 1):
        if "{" in _code_part(lines[number - 1]):
            return number
    return None


def scan_markers(
    files: Sequence[Path], root: Path
) -> tuple[tuple[Marker, ...], tuple[Finding, ...]]:
    """Every reasoned marker in *files*, and SWG003 for each reasonless one."""
    markers: list[Marker] = []
    findings: list[Finding] = []
    for path in files:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for number, line in enumerate(lines, start=1):
            match = _MARKER_RE.search(line)
            if match is None:
                continue
            reason = _reason(match.group("rest"))
            if not reason:
                findings.append(
                    Finding(
                        "SWG003",
                        _shown(path, root),
                        number,
                        f"{MARKER_TEXT} with no reason: write "
                        f"'// {MARKER_TEXT}: <why no test can reach this>'",
                    )
                )
                continue
            declares = bool(_DECLARES_FUNCTION_RE.search(_code_part(line)))
            body = _body_line(lines, number) if declares else None
            markers.append(Marker(path, number, reason, declares, body))
    return tuple(markers), tuple(findings)


def _excluded_by(
    marker: Marker, functions: Sequence[FunctionRegions]
) -> set[RegionKey]:
    """The region keys one marker excludes."""
    keys: set[RegionKey] = set()
    for function in functions:
        in_file = [r for r in function.regions if r.file == marker.file]
        keys.update(r.key for r in in_file if r.line == marker.line)
        if (
            marker.body_line is not None
            and in_file
            and in_file[0].line == marker.body_line
        ):
            keys.update(r.key for r in in_file)
    return keys


def apply_markers(
    markers: Sequence[Marker], functions: Sequence[FunctionRegions], root: Path
) -> tuple[frozenset[RegionKey], tuple[Finding, ...]]:
    """The union of every marker's exclusions, and SWG004 for each that excludes none."""
    excluded: set[RegionKey] = set()
    findings: list[Finding] = []
    for marker in markers:
        keys = _excluded_by(marker, functions)
        if not keys:
            findings.append(
                Finding(
                    "SWG004",
                    _shown(marker.file, root),
                    marker.line,
                    f"{MARKER_TEXT} excludes no coverage region (dead): remove it, or "
                    "move it to the line the region starts on",
                )
            )
        excluded.update(keys)
    return frozenset(excluded), tuple(findings)


def _shown(path: Path, root: Path) -> str:
    """*path* relative to the package root, for a finding."""
    return os.path.relpath(path, root)
