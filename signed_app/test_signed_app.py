"""The signed_app library's bootstrap and host helper, and a runner's way into tests/.

A runner that runs only each folder's top-level test file reaches the suites in tests/
only through this file, so `load_tests` below folds every suite there into this module's
run; without it the modules in src/ would be measured with no tests at all.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_LIBRARY_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_LIBRARY_ROOT))

import signed_app  # noqa: E402 - import follows the sys.path bootstrap above
import app_host  # noqa: E402 - on sys.path once signed_app is imported


def _grouped_suite() -> unittest.TestSuite:
    """Every test in tests/, discovered by walking the directory."""
    suite_dir = _LIBRARY_ROOT / "tests"
    return unittest.TestLoader().discover(
        str(suite_dir), pattern="test_*.py", top_level_dir=str(suite_dir)
    )


class BootstrapTest(unittest.TestCase):
    """Importing the front module puts this library's src/ folder on sys.path."""

    def test_the_src_folder_is_this_library_s(self) -> None:
        self.assertEqual(signed_app.SRC_DIR, _LIBRARY_ROOT / "src")
        self.assertIn(str(signed_app.SRC_DIR), sys.path)

    def test_the_shared_libraries_it_needs_are_importable(self) -> None:
        for folder, module in signed_app._LIBRARIES:
            with self.subTest(module=module):
                self.assertTrue(
                    any(
                        entry.endswith(folder) and Path(entry, f"{module}.py").is_file()
                        for entry in sys.path
                    )
                )

    def test_the_grouped_suites_are_found(self) -> None:
        self.assertGreater(_grouped_suite().countTestCases(), 0)


class HostTest(unittest.TestCase):
    """The host seam's one pure helper."""

    def test_tools_speak_untranslated_english_and_ignore_inherited_git_settings(
        self,
    ) -> None:
        inherited = {
            "LANG": "fr_FR.UTF-8",
            "GIT_DIR": "/invented/.git",
            "GIT_WORK_TREE": "/invented",
            "GIT_COMMON_DIR": "/invented/.git",
            "GIT_CEILING_DIRECTORIES": "/invented",
        }
        self.assertEqual(
            app_host.tool_environment(inherited),
            {"LANG": "fr_FR.UTF-8", "LC_ALL": "C"},
        )


def load_tests(
    _loader: unittest.TestLoader, tests: unittest.TestSuite, _pattern: str | None
) -> unittest.TestSuite:
    """unittest's hook: fold every suite in tests/ in beside this file's own tests."""
    return unittest.TestSuite([tests, _grouped_suite()])


if __name__ == "__main__":
    unittest.main()
