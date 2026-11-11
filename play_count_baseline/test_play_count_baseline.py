"""The entry point's bootstrap, and a runner's way into the grouped suites in tests/.

A runner that runs only each folder's top-level test file (a gate that prunes tests/
and src/ by name) reaches the suites in tests/ only through this file, so `load_tests`
below folds every suite in tests/ into this module's run; without it none of them
would run there, and the private modules in src/ would be measured with no tests at
all. The ``__main__`` block matters as much: such a runner runs this file as a script,
under coverage or not, so with no ``unittest.main()`` nothing would run.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_TOOL_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOL_ROOT))

import play_count_baseline  # noqa: E402 - import follows the sys.path bootstrap above

#: How long the bootstrap probe's interpreter may take to start and import.
_PROBE_TIMEOUT_S = 60
#: tag_refresh's own run modules, which importing this tool must not load.
_NOT_LOADED = ("refresh_report", "refresh_run")


def _grouped_suite() -> unittest.TestSuite:
    """Every test in tests/, discovered by walking the directory."""
    suite_dir = _TOOL_ROOT / "tests"
    return unittest.TestLoader().discover(
        str(suite_dir), pattern="test_*.py", top_level_dir=str(suite_dir)
    )


def _probe(code: str, *extra: str) -> str:
    """What *code* writes to its report file, run in a fresh, isolated interpreter.

    Its path holds only the tool folder, so no suite's own sys.path insert can stand
    in for the entry point's. It reports through a file rather than a pipe, so the
    timeout binds.
    """
    with TemporaryDirectory() as scratch:
        report = Path(scratch) / "report.txt"
        subprocess.run(
            [
                sys.executable,
                "-B",
                "-I",
                "-c",
                code,
                str(_TOOL_ROOT),
                str(report),
                *extra,
            ],
            check=True,
            cwd=scratch,
            timeout=_PROBE_TIMEOUT_S,
        )
        return report.read_text(encoding="utf-8")


class BootstrapTest(unittest.TestCase):
    """Importing the entry point makes its own modules and tag_refresh's seam importable."""

    def test_the_private_src_folder_is_its_own(self) -> None:
        self.assertEqual(play_count_baseline.SRC_DIR, _TOOL_ROOT / "src")

    def test_the_seam_is_tag_refresh_s_own_src(self) -> None:
        self.assertEqual(
            play_count_baseline.SEAM_DIR, _TOOL_ROOT.parent / "tag_refresh" / "src"
        )

    def test_the_entry_point_alone_makes_every_module_importable(self) -> None:
        found = _probe(
            "import sys, pathlib; sys.path.insert(0, sys.argv[1]); "
            "import play_count_baseline, baseline_calls, baseline_rows, music_calls; "
            "import help_formatter, report_file, stdio_utf8; "
            "pathlib.Path(sys.argv[2]).write_text("
            "'\\n'.join((baseline_rows.__file__, music_calls.__file__)), "
            "encoding='utf-8')"
        )
        own, seam = found.splitlines()
        self.assertEqual(Path(own).parent, play_count_baseline.SRC_DIR)
        self.assertEqual(Path(seam).parent, play_count_baseline.SEAM_DIR)

    def test_the_calls_module_finds_the_same_seam_alone(self) -> None:
        # baseline_calls bootstraps the seam itself, so a suite importing it from src/
        # needs no entry point; both must name one folder.
        found = _probe(
            "import sys, pathlib; sys.path.insert(0, sys.argv[1] + '/src'); "
            "import baseline_calls, music_calls; "
            "pathlib.Path(sys.argv[2]).write_text(music_calls.__file__, encoding='utf-8')"
        )
        self.assertEqual(Path(found).parent, play_count_baseline.SEAM_DIR)

    def test_importing_it_loads_none_of_tag_refresh_s_run_modules(self) -> None:
        loaded = _probe(
            "import sys, pathlib; sys.path.insert(0, sys.argv[1]); "
            "import play_count_baseline, baseline_calls; "
            "pathlib.Path(sys.argv[2]).write_text("
            "'\\n'.join(sorted(set(sys.modules) & set(sys.argv[3:]))), "
            "encoding='utf-8')",
            *_NOT_LOADED,
        )
        self.assertEqual(loaded, "")

    def test_the_grouped_suites_are_found(self) -> None:
        self.assertGreater(_grouped_suite().countTestCases(), 0)


def load_tests(
    _loader: unittest.TestLoader, tests: unittest.TestSuite, _pattern: str | None
) -> unittest.TestSuite:
    """unittest's hook: fold every suite in tests/ in beside this file's own tests."""
    return unittest.TestSuite([tests, _grouped_suite()])


if __name__ == "__main__":
    unittest.main()
