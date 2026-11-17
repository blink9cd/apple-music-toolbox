"""Render the per-package results as text or JSON, with the family's one-line trailer.

Private to ``swift_gate``. Pure: results in, a string out; the CLI owns every write. The
text report shows each package from ``~`` when it sits under the home the CLI passes; the
JSON keeps the resolved path, for a reader that opens it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from swgate_model import Finding, GateResult, Subject
from swgate_signing import render_path

JSON_INDENT = 2


def _finding_dict(finding: Finding) -> dict[str, object]:
    """One finding as a JSON object."""
    return {
        "code": finding.code,
        "path": finding.path,
        "line": finding.line,
        "message": finding.message,
    }


def _package_dict(subject: Subject, result: GateResult) -> dict[str, object]:
    """One package's result as a JSON object."""
    return {
        "package": str(subject.root),
        "exit_code": result.returncode,
        "percent": result.percent,
        "findings": [_finding_dict(f) for f in result.findings],
        "misses": list(result.misses),
        "detail": result.detail,
    }


def _package_lines(subject: Subject, result: GateResult, home: Path) -> list[str]:
    """One package's header, findings, misses, detail and verdict as report lines."""
    lines = [f"== {render_path(subject.root, home)}"]
    for f in result.findings:
        where = f"{f.path}:{f.line}" if f.line else f.path
        lines.append(f"{f.code} {where}: {f.message}")
    lines.extend(f"miss {miss}" for miss in result.misses)
    if result.detail:
        lines.append(result.detail)
    coverage = (
        f", region coverage {result.percent:.2f}%" if result.percent is not None else ""
    )
    verdict = "PASS" if result.returncode == 0 else "FAIL"
    lines.append(f"{verdict}: {len(result.findings)} finding(s){coverage}")
    return lines


def format_results(
    results: Sequence[tuple[Subject, GateResult]],
    min_percent: float,
    *,
    as_json: bool,
    home: Path,
) -> str:
    """Every package's result, then the overall verdict; *home* is shown as ``~``."""
    code = max((result.returncode for _, result in results), default=0)
    if as_json:
        return json.dumps(
            {
                "exit_code": code,
                "min_percent": min_percent,
                "packages": [_package_dict(s, r) for s, r in results],
            },
            indent=JSON_INDENT,
        )
    lines: list[str] = []
    for subject, result in results:
        lines.extend(_package_lines(subject, result, home))
    verdict = "PASS" if code == 0 else "FAIL"
    lines.append(
        f"Gated {len(results)} SwiftPM package(s) at >= {min_percent:g}% regions.\n"
        f"SWIFT_GATE FINAL RESULT: {verdict}"
    )
    return "\n".join(lines)
