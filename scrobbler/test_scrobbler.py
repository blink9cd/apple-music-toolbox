"""The entry point's commands and bootstrap, and a runner's way into the suites in tests/.

A runner that runs only each folder's top-level test file reaches the suites in tests/
only through this file, so `load_tests` below folds every suite there into this module's
run; without it the private modules in src/ would be measured with no tests at all.
Every command runs in-process, with its output captured; nothing reaches the real home.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_TOOL_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOL_ROOT))

sys.path.insert(0, str(_TOOL_ROOT / "tests"))

import _scrob_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import scrobbler  # noqa: E402 - import follows the sys.path bootstrap above


def _grouped_suite() -> unittest.TestSuite:
    """Every test in tests/, discovered by walking the directory."""
    suite_dir = _TOOL_ROOT / "tests"
    return unittest.TestLoader().discover(
        str(suite_dir), pattern="test_*.py", top_level_dir=str(suite_dir)
    )


def _run(*argv: str, host: fx.scrob_host.Host | None = None) -> tuple[int, str, str]:
    """Run the command line in-process; return its exit code, stdout and stderr."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = scrobbler.main(list(argv), prog="scrobbler", host=host)
        except SystemExit as stopped:
            code = int(stopped.code or 0)
    return code, out.getvalue(), err.getvalue()


class BootstrapTest(unittest.TestCase):
    """Importing the entry point puts its private src/ folder on sys.path."""

    def test_the_private_src_folder_is_its_own(self) -> None:
        self.assertEqual(scrobbler.SRC_DIR, _TOOL_ROOT / "src")
        self.assertIn(str(scrobbler.SRC_DIR), sys.path)

    def test_the_layout_file_is_the_one_beside_this_file(self) -> None:
        self.assertEqual(scrobbler.LAYOUT_FILE, _TOOL_ROOT / "layout.json")

    def test_the_grouped_suites_are_found(self) -> None:
        self.assertGreater(_grouped_suite().countTestCases(), 0)


class VersionCommandTest(unittest.TestCase):
    """`version` prints the layout file's version, or refuses an untrusted layout."""

    def test_it_prints_the_layout_version(self) -> None:
        document = json.loads(scrobbler.LAYOUT_FILE.read_text(encoding="utf-8"))
        self.assertEqual(_run("version"), (0, f"{document['version']}\n", ""))

    def test_an_untrusted_layout_is_one_error_line_and_exit_2(self) -> None:
        with TemporaryDirectory() as scratch:
            broken = Path(scratch) / "layout.json"
            broken.write_text("[]", encoding="utf-8", newline="\n")
            with mock.patch.object(scrobbler, "LAYOUT_FILE", broken):
                code, out, err = _run("version")
        self.assertEqual((code, out), (scrobbler.EXIT_CANNOT, ""))
        self.assertTrue(err.startswith("ERROR: "), err)
        self.assertEqual(err.count("\n"), 1)


class CommandCase(unittest.TestCase):
    """A fake host per test; each command's output is read from the kit's streams."""

    def setUp(self) -> None:
        self.kit = fx.make_kit(self)

    def run_cli(self, *argv: str) -> int:
        """Run one command against the kit; nothing may reach the process's streams."""
        code, out, err = _run(*argv, host=self.kit.host)
        self.assertEqual((out, err), ("", ""))
        return code

    def error_line(self) -> str:
        """The one line on the kit's stderr."""
        lines = self.kit.err.getvalue().splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("ERROR: "), lines[0])
        return lines[0]


class BuildCommandTest(CommandCase):
    """`build`'s exits: 0 built, 1 failed, 2 refused."""

    def test_a_build_is_exit_0(self) -> None:
        out_dir = self.kit.home.parent / "out"
        self.assertEqual(self.run_cli("build", "--out", str(out_dir)), 0)
        self.assertTrue((out_dir / "listensmith scrobbler.app").is_dir())

    def test_a_failed_build_is_exit_1(self) -> None:
        self.kit.tools.build_rc = 1
        out_dir = str(self.kit.home.parent / "out")
        self.assertEqual(self.run_cli("build", "--out", out_dir), 1)
        self.assertIn("swift build failed", self.error_line())

    def test_a_signed_build_with_no_setting_is_exit_2_saying_how(self) -> None:
        out_dir = str(self.kit.home.parent / "out")
        self.assertEqual(self.run_cli("build", "--out", out_dir, "--sign"), 2)
        self.assertIn('identity = "<codesign identity>"', self.error_line())

    def test_a_signed_build_never_shows_the_identity(self) -> None:
        self.kit.write_identity()
        self.kit.tools.sign_rc = 1
        self.kit.tools.sign_output = f"{fx.FAKE_IDENTITY}: invented failure\n"
        out_dir = str(self.kit.home.parent / "out")
        self.assertEqual(self.run_cli("build", "--out", out_dir, "--sign"), 1)
        for secret in (fx.FAKE_IDENTITY, fx.FAKE_NAME, fx.FAKE_TEAM):
            self.assertNotIn(secret, self.kit.output())


class AgentCommandTest(CommandCase):
    """`install` and `uninstall`'s exits."""

    def test_install_from_a_linked_worktree_is_exit_2(self) -> None:
        self.kit.write_identity()
        self.kit.tools.git_dir = ".git/worktrees/lane"
        self.assertEqual(self.run_cli("install"), 2)
        self.assertIn("linked git worktree", self.error_line())

    def test_an_install_the_app_confirms_is_exit_0(self) -> None:
        self.kit.write_identity()
        self.kit.launchd.on_bootstrap = lambda: self.kit.write_status(
            started_at=self.kit.clock.wall + 1
        )
        self.assertEqual(self.run_cli("install"), 0)
        self.assertIn("Automation", self.kit.out.getvalue())

    def test_a_launchd_that_answers_unknown_is_exit_1(self) -> None:
        self.kit.write_identity()
        self.kit.launchd.unknown.add(self.kit.layout.launchd_label)
        self.assertEqual(self.run_cli("install"), 1)
        self.error_line()

    def test_an_unwritable_launch_agents_folder_is_one_error_line_and_exit_1(
        self,
    ) -> None:
        self.kit.write_identity()
        launch_folder = self.kit.paths.launch_agents_dir
        launch_folder.mkdir(parents=True)
        launch_folder.chmod(0o500)
        self.addCleanup(launch_folder.chmod, 0o700)
        self.assertEqual(self.run_cli("install"), 1)
        self.assertIn("PermissionError", self.error_line())

    def test_uninstall_is_exit_0(self) -> None:
        self.kit.install_app()
        self.assertEqual(self.run_cli("uninstall"), 0)
        self.assertFalse(self.kit.paths.launch_agent_plist.exists())


class StatusCommandTest(CommandCase):
    """`status` exits its verdict; `status --session-check` always exits 0."""

    def test_a_healthy_install_prints_its_table_and_exits_0(self) -> None:
        self.kit.install_app()
        self.kit.write_status()
        self.assertEqual(self.run_cli("status"), 0)
        out = self.kit.out.getvalue()
        self.assertTrue(out.startswith("listensmith scrobbler: HEALTHY (exit 0)\n"))
        self.assertIn("| Item | State |", out)

    def test_no_install_exits_2(self) -> None:
        self.assertEqual(self.run_cli("status"), 2)
        self.assertIn("- cannot judge: not installed", self.kit.out.getvalue())

    def test_the_session_check_is_silent_when_not_installed(self) -> None:
        self.assertEqual(self.run_cli("status", "--session-check"), 0)
        self.assertEqual(self.kit.out.getvalue(), "")

    def test_the_session_check_prints_each_problem_and_exits_0(self) -> None:
        self.kit.install_app()
        self.kit.write_status(automation_denied=True)
        self.assertEqual(self.run_cli("status", "--session-check"), 0)
        (line,) = self.kit.out.getvalue().splitlines()
        self.assertIn("details: scrobbler.py status", line)

    def test_the_session_check_with_an_untrusted_layout_is_one_line_and_exit_0(
        self,
    ) -> None:
        broken = self.kit.home / "layout.json"
        broken.write_text("[]", encoding="utf-8", newline="\n")
        with mock.patch.object(scrobbler, "LAYOUT_FILE", broken):
            self.assertEqual(self.run_cli("status", "--session-check"), 0)
        (line,) = self.kit.out.getvalue().splitlines()
        self.assertTrue(line.startswith("listensmith scrobbler: session check failed"))
        self.assertNotIn(str(self.kit.home), line)

    def test_an_untrusted_layout_is_exit_2_on_the_host_stream(self) -> None:
        broken = self.kit.home / "layout.json"
        broken.write_text("[]", encoding="utf-8", newline="\n")
        with mock.patch.object(scrobbler, "LAYOUT_FILE", broken):
            self.assertEqual(self.run_cli("status"), 2)
        self.assertIn("JSON object", self.error_line())


class ParserTest(unittest.TestCase):
    """The command line's shape: a command is required, and --help names each."""

    def test_no_command_is_a_usage_error(self) -> None:
        code, out, err = _run()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("usage: scrobbler", err)

    def test_help_names_every_command_and_the_prerequisites(self) -> None:
        code, out, _ = _run("--help")
        self.assertEqual(code, 0)
        for command in ("version", "build", "install", "uninstall", "status"):
            self.assertIn(command, out)
        self.assertIn("Prerequisites", out)

    def test_build_requires_its_output_folder(self) -> None:
        code, _, err = _run("build")
        self.assertEqual(code, 2)
        self.assertIn("--out", err)

    def test_the_program_name_defaults_to_argv0(self) -> None:
        with mock.patch.object(sys, "argv", ["renamed-scrobbler"]):
            self.assertEqual(scrobbler.build_parser().prog, "renamed-scrobbler")


def load_tests(
    _loader: unittest.TestLoader, tests: unittest.TestSuite, _pattern: str | None
) -> unittest.TestSuite:
    """unittest's hook: fold every suite in tests/ in beside this file's own tests."""
    return unittest.TestSuite([tests, _grouped_suite()])


if __name__ == "__main__":
    unittest.main()
