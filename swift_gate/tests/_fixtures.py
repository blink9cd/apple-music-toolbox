"""The fixtures swift_gate's grouped suites are built on.

Shared by composition: imported, never subclassed. The JSON fixtures beside this module
are trimmed copies of real ``swift package dump-package`` and ``llvm-cov export`` output
captured from ``fixtures/floorpkg``; every absolute path in them is a ``<PKG>`` or
``<SCRATCH>`` placeholder, substituted here, so no machine path is committed.

Importing this module puts the tool folder and its ``src/`` dir on ``sys.path``, which is
what lets each suite import the private modules by name.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOL_DIR))
sys.path.insert(0, str(TOOL_DIR / "src"))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FLOORPKG = FIXTURES / "floorpkg"


def write(path: Path, text: str) -> Path:
    """Create *path*'s parents and write *text*, returning the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def dump_package(**changes: object) -> dict[str, object]:
    """The captured dump-package JSON as a dict, with top-level keys replaced."""
    data: dict[str, object] = json.loads(
        (FIXTURES / "dump_package.json").read_text(encoding="utf-8")
    )
    data.update(changes)
    return data


def export_data(package: Path, scratch: Path) -> dict[str, object]:
    """The captured coverage export with its placeholders pointed at real dirs."""
    text = (FIXTURES / "codecov_export.json").read_text(encoding="utf-8")
    text = text.replace("<PKG>", str(package)).replace("<SCRATCH>", str(scratch))
    data: dict[str, object] = json.loads(text)
    return data


def export_functions(data: dict[str, object]) -> list[dict[str, object]]:
    """The mutable function list inside an export dict, for per-case edits."""
    runs = data["data"]
    assert isinstance(runs, list)
    functions = runs[0]["functions"]
    assert isinstance(functions, list)
    return functions


def make_package(root: Path, sources: dict[str, str] | None = None) -> Path:
    """A minimal SwiftPM package tree under *root*, returned resolved."""
    write(root / "Package.swift", "// swift-tools-version: 6.0\n")
    for rel, text in (sources or {"Sources/Lib/Lib.swift": "let x = 1\n"}).items():
        write(root / rel, text)
    return root.resolve()


def completed(
    argv: Sequence[str], code: int = 0, out: str = "", err: str = ""
) -> subprocess.CompletedProcess[str]:
    """A ``CompletedProcess`` as the seam returns one."""
    return subprocess.CompletedProcess(list(argv), code, out, err)


class StagedRunner:
    """A programmable fake for the ``_run_swift`` seam.

    Keyed on a substring of the joined argv so each stage can be steered on its own: the
    pipeline is ordered, so a test reaching a late stage must let every earlier one pass.
    The ``--show-codecov-path`` stage prints *codecov*'s path, and the ``swift test`` run
    writes *report* there, as the real tool does; ``--show-bin-path`` prints *bin_path*.
    """

    def __init__(
        self,
        *,
        dump: dict[str, object] | None = None,
        codecov: Path | None = None,
        report: dict[str, object] | None = None,
        outcomes: Sequence[tuple[str, int, str]] = (),
        raises: dict[str, BaseException] | None = None,
        bin_path: Path | None = None,
    ) -> None:
        self.dump = dump if dump is not None else dump_package()
        self.bin_path = bin_path
        self.codecov = codecov
        self.report = report
        self.outcomes = outcomes
        self.raises = raises or {}
        self.calls: list[list[str]] = []
        self.cwds: list[Path] = []

    def __call__(
        self, argv: Sequence[str], *, cwd: Path, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        del timeout  # the fake never waits
        self.calls.append(list(argv))
        self.cwds.append(cwd)
        joined = " ".join(argv)
        for needle, exc in self.raises.items():
            if needle in joined:
                raise exc
        for needle, code, output in self.outcomes:
            if needle in joined:
                return completed(argv, code, output)
        return self._default(argv, joined)

    def _default(
        self, argv: Sequence[str], joined: str
    ) -> subprocess.CompletedProcess[str]:
        """The passing answer for each stage."""
        if "dump-package" in joined:
            return completed(argv, 0, json.dumps(self.dump))
        if "--show-codecov-path" in joined:
            return completed(argv, 0, f"{self.codecov}\n")
        if "--show-bin-path" in joined:
            return completed(argv, 0, f"{self.bin_path}\n")
        if " test " in f"{joined} " and self.codecov and self.report is not None:
            write(self.codecov, json.dumps(self.report))
        return completed(argv, 0, "ok")

    def stage_names(self) -> list[str]:
        """The pipeline order as stage labels, for order assertions."""
        names = []
        for argv in self.calls:
            joined = " ".join(argv)
            if "dump-package" in joined:
                names.append("manifest")
            elif "--show-codecov-path" in joined:
                names.append("codecov-path")
            elif "--show-bin-path" in joined:
                names.append("bin-path")
            elif argv[1:2] == ["build"]:
                names.append("build")
            else:
                names.append("test")
        return names
