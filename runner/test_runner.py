"""The entry point's commands and bootstrap, and a test runner's way into the suites in tests/.

A test runner that runs only each folder's top-level test file reaches the suites in
tests/ only through this file, so `load_tests` below folds every suite there into this
module's run; without it the private modules in src/ would be measured with no tests at
all. Every command runs in-process against a fake host, with its output captured; nothing
reaches the real home, launchd, codesign, osascript or Music.app.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import os
import subprocess
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_TOOL_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOL_ROOT))

sys.path.insert(0, str(_TOOL_ROOT / "tests"))

import _run_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import runner  # noqa: E402 - import follows the sys.path bootstrap above

#: What every in-process run sets: no color, so argparse's usage, help and errors are
#: plain text that an assertion can search.
_NO_COLOR = {"NO_COLOR": "1"}
#: The variables that turn argparse's color on (3.14 on); removed for each run, and
#: restored after it with the rest of the environment.
_COLOR_FORCING = ("FORCE_COLOR", "PYTHON_COLORS")
#: Every command the command line takes.
_COMMANDS = ("build", "install", "uninstall", "status", "locate")
_APP = "Apple Music Toolbox Runner.app"


def _grouped_suite() -> unittest.TestSuite:
    """Every test in tests/, discovered by walking the directory."""
    suite_dir = _TOOL_ROOT / "tests"
    return unittest.TestLoader().discover(
        str(suite_dir), pattern="test_*.py", top_level_dir=str(suite_dir)
    )


def _probe_suite() -> unittest.TestSuite:
    """The grant probe's own suite, in its folder beside this file.

    A test runner that goes no deeper than a tool's top-level test file and the folder
    below it never runs that suite, so it is folded in here too.
    """
    probe_dir = _TOOL_ROOT / "grant_probe"
    return unittest.TestLoader().discover(
        str(probe_dir), pattern="test_*.py", top_level_dir=str(probe_dir)
    )


def _run(*argv: str, host: fx.app_host.Host | None = None) -> tuple[int, str, str]:
    """Run the command line in-process, uncolored; return its exit code, stdout, stderr."""
    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch.dict(os.environ, _NO_COLOR),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        for forcing in _COLOR_FORCING:
            os.environ.pop(forcing, None)
        try:
            code = runner.main(list(argv), prog="runner", host=host)
        except SystemExit as stopped:
            code = int(stopped.code or 0)
    return code, out.getvalue(), err.getvalue()


class BootstrapTest(unittest.TestCase):
    """Importing the entry point puts its private src/ folder on sys.path."""

    def test_the_private_src_folder_is_its_own(self) -> None:
        self.assertEqual(runner.SRC_DIR, _TOOL_ROOT / "src")
        self.assertIn(str(runner.SRC_DIR), sys.path)

    def test_the_layout_file_is_the_one_beside_this_file(self) -> None:
        self.assertEqual(runner.LAYOUT_FILE, _TOOL_ROOT / "layout.json")

    def test_the_grouped_suites_are_found(self) -> None:
        self.assertGreater(_grouped_suite().countTestCases(), 0)

    def test_the_probes_suite_is_found(self) -> None:
        self.assertGreater(_probe_suite().countTestCases(), 0)


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
        self.assertTrue((out_dir / _APP).is_dir())

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


class InstallCommandTest(CommandCase):
    """`install` and `uninstall`'s exits."""

    def test_install_from_a_linked_worktree_is_exit_2(self) -> None:
        self.kit.write_identity()
        self.kit.tools.git_dir = ".git/worktrees/lane"
        self.assertEqual(self.run_cli("install"), 2)
        self.assertIn("linked git worktree", self.error_line())

    def test_an_install_macos_allows_is_exit_0(self) -> None:
        self.kit.write_identity()
        self.kit.probe_reports("granted", "playing")
        self.assertEqual(self.run_cli("install"), 0)
        self.assertIn("may control Music", self.kit.out.getvalue())

    def test_an_install_macos_denies_is_exit_1(self) -> None:
        self.kit.write_identity()
        self.kit.probe_reports("denied", "invented (-1743)")
        self.assertEqual(self.run_cli("install"), 1)
        self.assertIn("Automation", self.error_line())

    def test_a_launchd_that_answers_unknown_is_exit_1(self) -> None:
        self.kit.write_identity()
        self.kit.launchd.unknown.add(self.kit.layout.grant_label)
        self.assertEqual(self.run_cli("install"), 1)
        self.error_line()

    def test_uninstall_is_exit_0(self) -> None:
        self.kit.install_app()
        self.assertEqual(self.run_cli("uninstall"), 0)
        self.assertFalse(self.kit.paths.app_bundle.exists())


class StatusCommandTest(CommandCase):
    """`status` exits its verdict."""

    def test_no_install_exits_2(self) -> None:
        self.assertEqual(self.run_cli("status"), 2)
        self.assertIn("NOT INSTALLED", self.kit.out.getvalue())

    def test_an_install_that_verifies_exits_0(self) -> None:
        self.kit.install_app()
        self.assertEqual(self.run_cli("status"), 0)
        self.assertIn("HEALTHY", self.kit.out.getvalue())

    def test_an_install_that_does_not_verify_exits_1(self) -> None:
        self.kit.install_app()
        self.kit.tools.verify_rc = 1
        self.assertEqual(self.run_cli("status"), 1)

    def test_an_untrusted_layout_is_exit_2_on_the_host_stream(self) -> None:
        broken = self.kit.home / "layout.json"
        broken.write_text("[]", encoding="utf-8", newline="\n")
        with mock.patch.object(runner, "LAYOUT_FILE", broken):
            self.assertEqual(self.run_cli("status"), 2)
        self.assertIn("JSON object", self.error_line())


class LocateCommandTest(CommandCase):
    """`locate`: exit 0 and the path on one line, or exit 2 and one ERROR line."""

    def locate(self, python: str, script: str) -> int:
        """Run locate for `python` and `script`."""
        return self.run_cli("locate", "--python", python, "--script", script)

    def test_an_allowlisted_job_gets_the_executable_s_path(self) -> None:
        self.kit.install_app()
        self.assertEqual(self.locate(sys.executable, str(self.kit.probe)), 0)
        self.assertEqual(self.kit.out.getvalue(), f"{self.kit.executable}\n")
        self.assertEqual(self.kit.err.getvalue(), "")

    def test_not_installed_is_exit_2(self) -> None:
        self.assertEqual(self.locate(sys.executable, str(self.kit.probe)), 2)
        self.assertIn("is not installed", self.error_line())
        self.assertEqual(self.kit.out.getvalue(), "")

    def test_a_bundle_that_fails_its_signature_check_is_exit_2(self) -> None:
        self.kit.install_app()
        self.kit.tools.verify_rc = 1
        self.assertEqual(self.locate(sys.executable, str(self.kit.probe)), 2)
        self.assertEqual(
            self.error_line(), "ERROR: the runner's own signature does not verify"
        )

    def test_an_interpreter_not_allowlisted_is_exit_2(self) -> None:
        self.kit.install_app()
        self.assertEqual(self.locate(fx.OTHER_PYTHON, str(self.kit.probe)), 2)
        self.assertIn(fx.OTHER_PYTHON, self.error_line())

    def test_a_script_not_allowlisted_is_exit_2(self) -> None:
        self.kit.install_app()
        other = str(self.kit.checkout / "elsewhere.py")
        self.assertEqual(self.locate(sys.executable, other), 2)
        self.assertIn("not in the runner's allowlist", self.error_line())

    def test_both_paths_are_required(self) -> None:
        for given, missing in (("--python", "--script"), ("--script", "--python")):
            with self.subTest(missing=missing):
                code, _, err = _run("locate", given, "/opt/example/x")
                self.assertEqual(code, 2)
                self.assertIn(missing, err)


class OSErrorTest(CommandCase):
    """An OSError escaping any command is one ERROR line and exit 1, never a traceback."""

    #: One argv per command, each reaching the layout read the test makes fail.
    COMMANDS = (
        ("build", "--out", "unused"),
        ("install",),
        ("uninstall",),
        ("status",),
        ("locate", "--python", "/opt/example/p", "--script", "/opt/example/s.py"),
    )

    def assert_one_error_line(self, *argv: str) -> str:
        """Run `argv`: exit 1, and the kit's stderr is one ERROR line, no traceback."""
        self.kit.err.seek(0)
        self.kit.err.truncate()
        self.assertEqual(self.run_cli(*argv), runner.EXIT_FAILED)
        err = self.kit.err.getvalue()
        self.assertNotIn("Traceback", err)
        (line,) = err.splitlines()
        self.assertTrue(line.startswith("ERROR: "), line)
        return line

    def test_every_command_is_covered_here(self) -> None:
        self.assertEqual(tuple(argv[0] for argv in self.COMMANDS), _COMMANDS)

    def test_each_command_reports_an_oserror_as_one_line(self) -> None:
        failure = PermissionError(13, "Permission denied", "invented")
        for argv in self.COMMANDS:
            with (
                self.subTest(command=argv[0]),
                mock.patch.object(
                    runner.run_layout, "load_layout", side_effect=failure
                ),
            ):
                self.assertIn("Permission denied", self.assert_one_error_line(*argv))

    def test_uninstall_with_an_unrunnable_launchctl_is_one_line(self) -> None:
        self.kit.install_app()
        missing = FileNotFoundError(2, "No such file or directory", "launchctl")

        def answer(
            argv: Sequence[str], _timeout_s: float
        ) -> subprocess.CompletedProcess[str]:
            raise missing

        launchctl = dataclasses.replace(self.kit.host.launchctl, run=answer)
        self.kit.host = dataclasses.replace(self.kit.host, launchctl=launchctl)
        self.assertIn("launchctl bootout", self.assert_one_error_line("uninstall"))
        self.assertTrue(self.kit.paths.app_bundle.exists())

    def test_a_failure_before_any_host_is_built_goes_to_this_process_s_stderr(
        self,
    ) -> None:
        with TemporaryDirectory() as scratch:
            broken = Path(scratch) / "layout.json"
            broken.write_text("[]", encoding="utf-8", newline="\n")
            with (
                mock.patch.object(runner, "LAYOUT_FILE", broken),
                mock.patch.object(runner, "real_host") as real_host,
            ):
                code, out, err = _run("status")
        real_host.assert_not_called()
        self.assertEqual((code, out), (runner.EXIT_CANNOT, ""))
        self.assertTrue(err.startswith("ERROR: "), err)
        self.assertEqual(err.count("\n"), 1)


class ParserTest(unittest.TestCase):
    """The command line's shape: a command is required, and --help names each."""

    def test_no_command_is_a_usage_error(self) -> None:
        code, out, err = _run()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("usage: runner", err)

    def test_help_names_every_command_and_the_prerequisites(self) -> None:
        code, out, _ = _run("--help")
        self.assertEqual(code, 0)
        for command in _COMMANDS:
            self.assertIn(command, out)
        self.assertIn("Prerequisites", out)

    def test_each_command_has_its_own_help(self) -> None:
        for command in _COMMANDS:
            with self.subTest(command=command):
                code, out, err = _run(command, "--help")
                self.assertEqual((code, err), (0, ""))
                self.assertIn(f"usage: runner {command}", out)
                self.assertIn("Prerequisites", out)

    def test_build_requires_its_output_folder(self) -> None:
        code, _, err = _run("build")
        self.assertEqual(code, 2)
        self.assertIn("--out", err)

    def test_the_program_name_defaults_to_argv0(self) -> None:
        with mock.patch.object(sys, "argv", ["renamed-runner"]):
            self.assertEqual(runner.build_parser().prog, "renamed-runner")


def load_tests(
    _loader: unittest.TestLoader, tests: unittest.TestSuite, _pattern: str | None
) -> unittest.TestSuite:
    """unittest's hook: fold tests/ and the probe's suite in beside this file's own tests."""
    return unittest.TestSuite([tests, _grouped_suite(), _probe_suite()])


if __name__ == "__main__":
    unittest.main()
