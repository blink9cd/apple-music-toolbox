"""The entry point's bootstrap, and a runner's way into the grouped suites in tests/.

A runner that runs only each folder's top-level test file (the README's loop, or a gate
that prunes tests/ and src/ by name) reaches the suites in tests/ only through this
file, so `load_tests` below folds every suite in tests/ into this module's run; without
it none of them would run there, and the private modules in src/ would be measured with
no tests at all. The ``__main__`` block matters as much: such a runner runs this file as
a script, under coverage or not, so with no ``unittest.main()`` nothing would run.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_TOOL_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOL_ROOT))

import phone_audit  # noqa: E402 - import follows the sys.path bootstrap above

#: How long the bootstrap probe's interpreter may take to start and import.
_PROBE_TIMEOUT_S = 60
#: tag_refresh's own run modules, which importing this tool must not load.
_NOT_LOADED = ("refresh_report", "refresh_run", "music_calls")


def _grouped_suite() -> unittest.TestSuite:
    """Every test in tests/, discovered by walking the directory."""
    suite_dir = _TOOL_ROOT / "tests"
    return unittest.TestLoader().discover(
        str(suite_dir), pattern="test_*.py", top_level_dir=str(suite_dir)
    )


class BootstrapTest(unittest.TestCase):
    """Importing the entry point makes its own modules and the shared helpers importable."""

    def test_the_private_src_folder_is_its_own(self) -> None:
        self.assertEqual(phone_audit.SRC_DIR, _TOOL_ROOT / "src")

    def test_the_report_helpers_are_tag_refresh_s_own_src(self) -> None:
        self.assertEqual(
            phone_audit.SHARED_DIR, _TOOL_ROOT.parent / "tag_refresh" / "src"
        )

    def test_the_entry_point_alone_makes_every_module_importable(self) -> None:
        # A fresh, isolated interpreter whose path holds only the tool folder, so no
        # suite's own sys.path insert can stand in for the entry point's. It reports
        # through a file rather than a pipe, so the timeout binds.
        with TemporaryDirectory() as scratch:
            report = Path(scratch) / "found.txt"
            probe = (
                "import sys, pathlib; sys.path.insert(0, sys.argv[1]); "
                "import phone_audit, afc_calls, phone_listing, phone_db, phone_compare, "
                "phone_report, phone_html, report_file, html_page, "
                "stdio_utf8, help_formatter, bounded_run; "
                "pathlib.Path(sys.argv[2]).write_text("
                "'\\n'.join((afc_calls.__file__, report_file.__file__, "
                "html_page.__file__)), "
                "encoding='utf-8')"
            )
            subprocess.run(
                [sys.executable, "-B", "-I", "-c", probe, str(_TOOL_ROOT), str(report)],
                check=True,
                cwd=scratch,
                timeout=_PROBE_TIMEOUT_S,
            )
            own, shared, page = report.read_text(encoding="utf-8").splitlines()
        self.assertEqual(Path(own).parent, phone_audit.SRC_DIR)
        self.assertEqual(Path(shared).parent, phone_audit.SHARED_DIR)
        # The page frame is the shared library, in its own folder, not a sibling
        # tool's private module.
        self.assertEqual(Path(page).parent.name, "html_page")

    def test_importing_it_loads_none_of_tag_refresh_s_run_modules(self) -> None:
        # The escape every line is shown through is html_page's own; reaching it
        # through refresh_report would load tag_refresh's run modules too, among them
        # the Music.app calls this tool never makes.
        with TemporaryDirectory() as scratch:
            report = Path(scratch) / "loaded.txt"
            probe = (
                "import sys, pathlib; sys.path.insert(0, sys.argv[1]); "
                "import phone_audit; "
                "pathlib.Path(sys.argv[2]).write_text("
                "'\\n'.join(sorted(set(sys.modules) & set(sys.argv[3:]))), "
                "encoding='utf-8')"
            )
            subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-I",
                    "-c",
                    probe,
                    str(_TOOL_ROOT),
                    str(report),
                    *_NOT_LOADED,
                ],
                check=True,
                cwd=scratch,
                timeout=_PROBE_TIMEOUT_S,
            )
            loaded = report.read_text(encoding="utf-8")
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
