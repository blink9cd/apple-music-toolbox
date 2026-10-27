"""afc_calls: the one seam to afcclient, allowlisted to reads, every call bounded.

Every call here goes to a recording runner built in this file, except one, which runs
this interpreter through the real runner to show the child's environment; nothing here
can start afcclient or reach a phone.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import phone_audit  # noqa: E402, F401 - puts src/ and the shared helpers on sys.path
import afc_calls as ac  # noqa: E402 - import follows the sys.path bootstrap above

_BIN = "/fake/bin/afcclient"


class _Recorder:
    """A runner answering every call with one canned reply, recording each argv."""

    def __init__(
        self,
        reply: subprocess.CompletedProcess[str] | BaseException | None = None,
        *,
        write: bool = False,
    ) -> None:
        self.reply = reply or subprocess.CompletedProcess([_BIN], 0, "", "")
        self.write = write
        self.calls: list[tuple[list[str], float]] = []

    def __call__(
        self, argv: list[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), timeout))
        if isinstance(self.reply, BaseException):
            raise self.reply
        if self.write:
            Path(argv[-1]).write_bytes(b"copied")
        return self.reply


def _done(stdout: str = "", code: int = 0, stderr: str = "") -> _Recorder:
    """A recorder replying with these streams and exit status."""
    return _Recorder(subprocess.CompletedProcess([_BIN], code, stdout, stderr))


class AllowlistTest(unittest.TestCase):
    """Only reads may be built, and a refused command starts nothing."""

    def test_the_allowlist_is_exactly_the_two_reads(self) -> None:
        # Pinned: widening it is a decision, never an accident.
        self.assertEqual(ac.ALLOWED_COMMANDS, frozenset({"ls", "get"}))

    def test_a_command_goes_after_the_separator(self) -> None:
        self.assertEqual(
            ac.command_argv(_BIN, "ls", ["-l", "/x"]), [_BIN, "--", "ls", "-l", "/x"]
        )

    def test_a_udid_goes_before_the_separator(self) -> None:
        self.assertEqual(
            ac.command_argv(_BIN, "get", ["/a", "/b"], udid="0000-FAKE"),
            [_BIN, "-u", "0000-FAKE", "--", "get", "/a", "/b"],
        )

    def test_every_write_command_is_refused_before_a_process_starts(self) -> None:
        for command in ("put", "rm", "remove", "mv", "rename", "mkdir", "ln", "LS", ""):
            with self.subTest(command=command):
                runner = _Recorder()
                with self.assertRaises(ac.ForbiddenCommand):
                    ac.Afc(_BIN, None, runner).run(command, ["/x"], 1.0)
                self.assertEqual(runner.calls, [])

    def test_an_overwriting_or_recursive_get_is_refused(self) -> None:
        for flag in ("-f", "-r", "-rf", "-fr"):
            with self.subTest(flag=flag):
                runner = _Recorder()
                with self.assertRaises(ac.ForbiddenCommand):
                    ac.Afc(_BIN, None, runner).run("get", [flag, "/a", "/b"], 1.0)
                self.assertEqual(runner.calls, [])


class FailureTest(unittest.TestCase):
    """A failed command exits 0 and says so on stdout; a failed connection exits 1."""

    def test_an_error_line_on_stdout_is_a_failed_command(self) -> None:
        line = "Error: Failed to list '/x': Permission denied (10)"
        with self.assertRaises(ac.CommandFailed) as caught:
            ac.Afc(_BIN, None, _done(line + "\n")).list_dir("/x")
        self.assertEqual(caught.exception.reason, line)

    def test_an_error_after_progress_output_is_still_found(self) -> None:
        stdout = "\r10% (1.0 MB/s)   \nError: Failed to write to local file\n"
        with self.assertRaises(ac.CommandFailed):
            ac.Afc(_BIN, None, _done(stdout)).run("ls", ["/x"], 1.0)

    def test_progress_output_alone_is_success(self) -> None:
        stdout = "\r50% (2.0 MB/s)   \r100% (2.0 MB/s)   \n"
        self.assertEqual(
            ac.Afc(_BIN, None, _done(stdout)).run("ls", ["/x"], 1.0), stdout
        )

    def test_a_disconnect_line_is_an_unreachable_phone(self) -> None:
        # Unplugged mid-command, afcclient prints this on stdout and exits 0.
        for stdout in ("\n[disconnected]\n", "partial\n[disconnected]\n"):
            with self.subTest(stdout=stdout):
                with self.assertRaises(ac.Unreachable) as caught:
                    ac.Afc(_BIN, None, _done(stdout)).list_dir("/x")
                self.assertIn("disconnected", caught.exception.reason)

    def test_a_name_holding_the_word_is_not_a_disconnect(self) -> None:
        stdout = "-rw-r--r--    1 mobile mobile 1 26 Oct 2026 13:01:02 [disconnected]\n"
        self.assertEqual(ac.Afc(_BIN, None, _done(stdout)).list_dir("/x"), stdout)

    def test_a_nonzero_exit_is_an_unreachable_phone(self) -> None:
        stderr = "No device found. Plug in a device or pass UDID with -u to wait.\n"
        with self.assertRaises(ac.Unreachable) as caught:
            ac.Afc(_BIN, None, _done(code=1, stderr=stderr)).list_dir("/x")
        self.assertIn("No device found", caught.exception.reason)

    def test_a_nonzero_exit_with_no_stderr_still_names_the_exit(self) -> None:
        with self.assertRaises(ac.Unreachable) as caught:
            ac.Afc(_BIN, None, _done(code=2)).list_dir("/x")
        self.assertIn("exit 2", caught.exception.reason)

    def test_a_timeout_is_an_unreachable_phone(self) -> None:
        expired = subprocess.TimeoutExpired(cmd=[_BIN], timeout=ac.LS_TIMEOUT_S)
        with self.assertRaises(ac.Unreachable) as caught:
            ac.Afc(_BIN, None, _Recorder(expired)).list_dir("/x")
        self.assertIn("did not answer", caught.exception.reason)

    def test_a_binary_that_cannot_start_is_an_unreachable_phone(self) -> None:
        with self.assertRaises(ac.Unreachable) as caught:
            ac.Afc(_BIN, None, _Recorder(PermissionError(13, "denied"))).list_dir("/x")
        self.assertIn("cannot run", caught.exception.reason)


class CallTest(unittest.TestCase):
    """What each read sends, and the bound each is given."""

    def test_a_listing_is_ls_dash_l_under_the_listing_bound(self) -> None:
        runner = _done("listing\n")
        self.assertEqual(ac.Afc(_BIN, "U1", runner).list_dir("/x"), "listing\n")
        self.assertEqual(
            runner.calls,
            [([_BIN, "-u", "U1", "--", "ls", "-l", "/x"], ac.LS_TIMEOUT_S)],
        )

    def test_a_copy_may_take_longer_than_a_listing(self) -> None:
        self.assertGreater(ac.GET_TIMEOUT_S, ac.LS_TIMEOUT_S)

    def test_a_copy_lands_where_asked_and_is_confirmed(self) -> None:
        with TemporaryDirectory() as scratch:
            local = Path(scratch) / "copy.db"
            runner = _Recorder(write=True)
            self.assertTrue(ac.Afc(_BIN, None, runner).copy_file("/r/a.db", local))
            self.assertEqual(local.read_bytes(), b"copied")
        self.assertEqual(
            runner.calls,
            [([_BIN, "--", "get", "/r/a.db", str(local)], ac.GET_TIMEOUT_S)],
        )

    def test_a_file_the_phone_lacks_is_reported_absent(self) -> None:
        line = "Error: Failed to read from file '/r/a.db-wal': Not found (8)\n"
        with TemporaryDirectory() as scratch:
            local = Path(scratch) / "copy.db-wal"
            self.assertFalse(
                ac.Afc(_BIN, None, _done(line)).copy_file("/r/a.db-wal", local)
            )

    def test_any_other_copy_error_is_a_failure(self) -> None:
        line = "Error: Failed to read from file '/r/a.db': Unknown error (1)\n"
        with TemporaryDirectory() as scratch, self.assertRaises(ac.CommandFailed):
            ac.Afc(_BIN, None, _done(line)).copy_file("/r/a.db", Path(scratch) / "c")

    def test_a_copy_that_leaves_no_file_is_a_failure(self) -> None:
        with (
            TemporaryDirectory() as scratch,
            self.assertRaises(ac.CommandFailed) as caught,
        ):
            ac.Afc(_BIN, None, _done()).copy_file("/r/a.db", Path(scratch) / "c")
        self.assertIn("no file", caught.exception.reason)

    def test_a_copy_never_targets_an_existing_file(self) -> None:
        with TemporaryDirectory() as scratch:
            local = Path(scratch) / "taken"
            local.write_bytes(b"mine")
            runner = _Recorder(write=True)
            with self.assertRaises(FileExistsError):
                ac.Afc(_BIN, None, runner).copy_file("/r/a.db", local)
            self.assertEqual(local.read_bytes(), b"mine")
        self.assertEqual(runner.calls, [])


class VersionTest(unittest.TestCase):
    """``-v`` read, and any failure to read it answered with None."""

    def test_the_proven_version(self) -> None:
        self.assertEqual(ac.PROVEN_VERSION, "1.4.0")

    def test_the_version_line_is_read(self) -> None:
        for stdout in ("afcclient 1.4.0\n", "afcclient 1.4.0 (readline)\n"):
            with self.subTest(stdout=stdout):
                runner = _done(stdout)
                self.assertEqual(ac.Afc(_BIN, "U1", runner).version(), "1.4.0")
                self.assertEqual(runner.calls, [([_BIN, "-v"], ac.VERSION_TIMEOUT_S)])

    def test_an_unreadable_version_is_none(self) -> None:
        expired = subprocess.TimeoutExpired(cmd=[_BIN], timeout=1)
        for runner in (
            _done("something else\n"),
            _done(""),
            _done("afcclient 1.4.0\n", code=1),
            _Recorder(expired),
            _Recorder(FileNotFoundError(2, "gone")),
        ):
            with self.subTest(reply=runner.reply):
                self.assertIsNone(ac.Afc(_BIN, None, runner).version())


class EnvironmentTest(unittest.TestCase):
    """The child runs with colors off, through the real bounded runner."""

    def test_colors_are_turned_off_and_the_rest_kept(self) -> None:
        self.assertEqual(
            ac.child_env({"PATH": "/p", "COLOR": "1"}), {"PATH": "/p", "COLOR": "0"}
        )

    def test_the_real_runner_hands_the_child_that_environment(self) -> None:
        probe = "import os; print(os.environ['COLOR'])"
        result = ac.real_run([sys.executable, "-I", "-c", probe], 60)
        self.assertEqual((result.returncode, result.stdout), (0, "0\n"))


if __name__ == "__main__":
    unittest.main()
