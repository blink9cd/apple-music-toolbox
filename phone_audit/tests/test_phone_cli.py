"""The entry point: what stops a run, each exit code, the formats, and the read-only seam.

Every run goes through `main` with a `phone_fixtures.FakePhone` runner; nothing reaches
a phone. Each run's recorded argvs are checked to be reads only: ``-v``, or an
allowlisted command after ``--``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import phone_audit as pa  # noqa: E402 - import follows the sys.path bootstrap above
import phone_fixtures as pf  # noqa: E402 - import follows the sys.path bootstrap above
import afc_calls  # noqa: E402 - import follows the sys.path bootstrap above

_IN_SYNC = pf.Row(1, pf.base("F00"), "AAAA.mp3", 100, "First Title", 1, 1)
_GONE = pf.Row(2, pf.base("F00"), "BBBB.mp3", 100, "Second Title", 1, 2)
_SIZED = pf.Row(3, pf.base("F01"), "CCCC.mp3", 300, "Third Title", 1, 3)
_OUTSIDE = pf.Row(4, "iTunes_Control/Purchases", "DDDD.mp3", 5)
_FOLDERS = {"F00": {"AAAA.mp3": 100, "ZZZZ.mp3": 7}, "F01": {"CCCC.mp3": 299}}
#: ``get`` flags that would overwrite or recurse: never sent.
_WRITE_FLAGS = frozenset({"-f", "-r", "-rf", "-fr"})


def _clean_phone() -> pf.FakePhone:
    """A phone whose one row has its file, at its size."""
    return pf.phone_with([_IN_SYNC], {"F00": {"AAAA.mp3": 100}})


class _Case(unittest.TestCase):
    """Runs the entry point and checks every argv it sent was a read."""

    def run_on(
        self, phone: pf.FakePhone, *argv: str, found: str | None = pf.BINARY
    ) -> pf.Outcome:
        """Run with *argv* against *phone*, then check its argvs."""
        result = pf.run_main(argv, pf.wiring(phone, found=found))
        self.assert_reads_only(phone)
        return result

    def assert_reads_only(self, phone: pf.FakePhone) -> None:
        """Each recorded argv is ``-v`` alone, or ``--`` then an allowlisted command."""
        for argv in phone.calls:
            with self.subTest(argv=argv):
                if argv == [pf.BINARY, "-v"]:
                    continue
                cut = argv.index("--")
                self.assertIn(argv[:cut], ([pf.BINARY], [pf.BINARY, "-u", "0000-FAKE"]))
                self.assertIn(argv[cut + 1], afc_calls.ALLOWED_COMMANDS)
                self.assertFalse(_WRITE_FLAGS.intersection(argv[cut + 1 :]))


class CannotStartTest(_Case):
    """Exit 2 with one line, and nothing more asked of the phone."""

    def test_no_afcclient_on_path_names_the_install(self) -> None:
        phone = _clean_phone()
        result = self.run_on(phone, found=None)
        self.assertEqual(result.code, pf.USAGE)
        self.assertIn("brew install libimobiledevice", result.stderr)
        self.assertEqual(phone.calls, [])

    def test_no_device_says_to_connect_and_unlock(self) -> None:
        stderr = "No device found. Plug in a device or pass UDID with -u to wait for device to be available.\n"
        phone = pf.FakePhone(
            answers={("get", 1): pf.completed(returncode=1, stderr=stderr)}
        )
        result = self.run_on(phone)
        self.assertEqual(result.code, pf.USAGE)
        self.assertIn("No device found", result.stderr)
        self.assertIn("unlock", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_a_lockdown_failure_or_a_timeout_cannot_run(self) -> None:
        lockdown = "ERROR: Could not connect to lockdownd: Password protected (-17)\n"
        for answer in (
            pf.completed(returncode=1, stderr=lockdown),
            subprocess.TimeoutExpired(cmd=[pf.BINARY], timeout=1),
        ):
            with self.subTest(answer=answer):
                phone = pf.phone_with([_IN_SYNC], _FOLDERS)
                phone.answers = {("ls", 1): answer}
                result = self.run_on(phone)
                self.assertEqual(result.code, pf.USAGE)
                self.assertIn("connect", result.stderr)
                self.assertIn("unlock", result.stderr)

    def test_a_disconnect_mid_run_says_to_connect_and_unlock(self) -> None:
        phone = pf.phone_with([_IN_SYNC], _FOLDERS)
        phone.answers = {("ls", 2): pf.completed(pf.DISCONNECTED)}
        result = self.run_on(phone)
        self.assertEqual(result.code, pf.USAGE)
        self.assertIn("disconnected", result.stderr)
        self.assertIn("unlock", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_a_local_file_error_is_one_line_never_a_traceback(self) -> None:
        for target in ("tempfile.mkdtemp", "hashlib.file_digest"):
            with self.subTest(target=target):
                phone = _clean_phone()
                with mock.patch(
                    f"phone_db.{target}", side_effect=OSError(28, "No space left")
                ):
                    result = self.run_on(phone)
                self.assertEqual(result.code, pf.USAGE)
                said = [s for s in result.stderr.splitlines() if "No space left" in s]
                self.assertEqual(len(said), 1, result.stderr)
                self.assertIn("a local file could not be used", said[0])
                self.assertNotIn("Traceback", result.stderr)

    def test_the_device_absolute_paths_find_nothing(self) -> None:
        # The fake is strict: afcclient's paths start at the AFC root, the device's
        # /var/mobile/Media, so the device-absolute form is a missing object.
        phone = pf.phone_with([_IN_SYNC], _FOLDERS)
        absolute = "/var/mobile/Media" + pf.DB_REMOTE
        with TemporaryDirectory() as scratch:
            local = Path(scratch) / "copy"
            reply = phone([pf.BINARY, "--", "get", absolute, str(local)], 1.0)
            self.assertFalse(local.exists())
        self.assertEqual(reply.stdout, pf.NOT_FOUND.format(path=absolute))
        music = "/var/mobile/Media" + pf.MUSIC
        for path in (music, music + "/F00"):
            with self.subTest(path=path):
                reply = phone([pf.BINARY, "--", "ls", "-l", path], 1.0)
                self.assertEqual(reply.stdout, pf.LS_NOT_FOUND.format(path=path))

    def test_the_tool_lists_the_jail_relative_music_folder(self) -> None:
        self.assertEqual(pa.MUSIC_FOLDER, "/iTunes_Control/Music")

    def test_a_phone_with_no_database(self) -> None:
        result = self.run_on(pf.FakePhone())
        self.assertEqual(result.code, pf.USAGE)
        self.assertIn("no music database", result.stderr)

    def test_a_database_that_changed_while_copied(self) -> None:
        sql = pf.fixture_sql([_IN_SYNC])
        phone = pf.FakePhone(
            database=[
                pf.database_bytes(sql),
                pf.database_bytes(sql + "SELECT 1;\nCREATE TABLE x (y);"),
            ]
        )
        result = self.run_on(phone)
        self.assertEqual(result.code, pf.USAGE)
        self.assertIn("close Music on the phone and run again", result.stderr)

    def test_a_listing_that_fails_ends_the_run(self) -> None:
        phone = pf.phone_with([_IN_SYNC], _FOLDERS)
        phone.answers = {
            ("ls", 2): pf.completed(
                "Error: Failed to list 'x': Permission denied (10)\n"
            )
        }
        result = self.run_on(phone)
        self.assertEqual(result.code, pf.USAGE)
        self.assertIn("Permission denied", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_an_empty_udid_is_refused(self) -> None:
        phone = _clean_phone()
        result = self.run_on(phone, "--udid", "")
        self.assertEqual(result.code, pf.USAGE)
        self.assertEqual(phone.calls, [])

    def test_a_report_inside_a_working_tree_is_refused_before_any_call(self) -> None:
        with TemporaryDirectory() as scratch:
            (Path(scratch) / "repo" / ".git").mkdir(parents=True)
            phone = _clean_phone()
            result = self.run_on(
                phone, "--report", str(Path(scratch) / "repo" / "r.txt")
            )
        self.assertEqual(result.code, pf.USAGE)
        self.assertIn("git working tree", result.stderr)
        self.assertEqual(phone.calls, [])


class RunTest(_Case):
    """What a run asks, finds and prints."""

    def test_a_clean_phone_exits_zero(self) -> None:
        phone = _clean_phone()
        result = self.run_on(phone)
        self.assertEqual(result.code, pf.OK, result.stderr)
        self.assertIn(
            "summary: findings 0; rows in the sync 1, files 1;", result.stdout
        )
        self.assertEqual(phone.commands(), ["-v", *["get"] * 6, "ls", "ls"])

    def test_findings_exit_one_and_are_reported(self) -> None:
        phone = pf.phone_with([_IN_SYNC, _GONE, _SIZED, _OUTSIDE], _FOLDERS)
        result = self.run_on(phone)
        self.assertEqual(result.code, pf.FINDINGS)
        self.assertIn("rows with no file on the phone: 1\n", result.stdout)
        self.assertIn("Second Title [F00/BBBB.mp3]", result.stdout)
        self.assertIn("[F01/CCCC.mp3]: phone file 299, database 300", result.stdout)
        self.assertIn("  F00/ZZZZ.mp3: 7 bytes\n", result.stdout)
        self.assertIn("outside the sync 1,", result.stdout)

    def test_the_udid_is_passed_before_the_separator(self) -> None:
        phone = _clean_phone()
        self.run_on(phone, "--udid", "0000-FAKE")
        self.assertTrue(all(a[1:3] == ["-u", "0000-FAKE"] for a in phone.calls[1:]))

    def test_only_fnn_folders_are_listed_and_odd_entries_counted(self) -> None:
        phone = _clean_phone()
        phone.music_lines = [pf.listing_line("Other", kind="d"), pf.listing_line("F99")]
        phone.folder_lines = {"F00": [pf.listing_line("Sub", kind="d"), "odd line\n"]}
        result = self.run_on(phone)
        listed = [a[-1] for a in phone.calls if pf.command_of(a) == "ls"]
        self.assertEqual(listed, [pf.MUSIC, pf.MUSIC + "/F00"])
        self.assertIn(
            "unparsed lines 1, sizes unknown 0, other entries 1", result.stdout
        )
        self.assertEqual(result.code, pf.FINDINGS)
        self.assertIn("1 listing line(s) unparsed", result.stderr)

    def test_each_call_is_bounded(self) -> None:
        phone = _clean_phone()
        self.run_on(phone)
        expected = {
            "-v": afc_calls.VERSION_TIMEOUT_S,
            "get": afc_calls.GET_TIMEOUT_S,
            "ls": afc_calls.LS_TIMEOUT_S,
        }
        pairs = list(zip(phone.commands(), phone.timeouts, strict=True))
        self.assertEqual(pairs, [(c, expected[c]) for c, _ in pairs])

    def test_a_failed_stat_in_a_listing_is_a_finding_not_a_file(self) -> None:
        phone = _clean_phone()
        phone.folder_lines = {"F00": [pf.zeroed_line("GONE.mp3")]}
        result = self.run_on(phone)
        self.assertEqual(result.code, pf.FINDINGS)
        self.assertIn("unparsed lines 1,", result.stdout)
        self.assertNotIn("GONE.mp3", result.stdout)
        self.assertIn(
            "1 listing line(s) unparsed in " + pf.MUSIC + "/F00", result.stderr
        )

    def test_another_version_warns_and_goes_on(self) -> None:
        for version in ("afcclient 1.5.0\n", "nonsense\n"):
            with self.subTest(version=version):
                phone = _clean_phone()
                phone.version = version
                result = self.run_on(phone)
                self.assertEqual(result.code, pf.OK)
                self.assertIn("proven against afcclient 1.4.0", result.stderr)

    def test_ctrl_c_exits_130_with_no_report(self) -> None:
        phone = _clean_phone()
        phone.answers = {("ls", 1): KeyboardInterrupt()}
        result = self.run_on(phone)
        self.assertEqual(result.code, pf.INTERRUPTED)
        self.assertIn("interrupted", result.stderr)
        self.assertEqual(result.stdout, "")


class DeliveryTest(_Case):
    """The JSON form, and a report written to a file."""

    def test_json_to_stdout(self) -> None:
        result = self.run_on(_clean_phone(), "--format", "json")
        self.assertEqual(json.loads(result.stdout)["summary"]["rows_in_sync"], 1)

    def test_a_report_file_is_written_whole(self) -> None:
        with TemporaryDirectory() as scratch:
            target = Path(scratch) / "report.txt"
            result = self.run_on(_clean_phone(), "--report", str(target))
            self.assertEqual(result.code, pf.OK)
            self.assertEqual(result.stdout, "")
            self.assertIn("summary: findings 0;", target.read_text(encoding="utf-8"))

    def test_a_report_refused_at_the_moment_of_writing(self) -> None:
        with TemporaryDirectory() as scratch:
            target = Path(scratch) / "r.txt"
            phone = _clean_phone()

            def make_repo(
                argv: list[str], timeout: float
            ) -> subprocess.CompletedProcess[str]:
                (Path(scratch) / ".git").mkdir(exist_ok=True)
                return pf.FakePhone.__call__(phone, argv, timeout)

            result = pf.run_main(
                ["--report", str(target)],
                pa.Wiring(run=make_repo, which=lambda _n: pf.BINARY),
            )
            self.assertFalse(target.exists())
        self.assertEqual(result.code, pf.USAGE)
        self.assertIn("git working tree", result.stderr)

    def test_a_report_that_cannot_be_written(self) -> None:
        with TemporaryDirectory() as scratch:
            target = Path(scratch) / "r.txt"
            phone = _clean_phone()

            def lock(
                argv: list[str], timeout: float
            ) -> subprocess.CompletedProcess[str]:
                Path(scratch).chmod(0o500)
                return pf.FakePhone.__call__(phone, argv, timeout)

            try:
                result = pf.run_main(
                    ["--report", str(target)],
                    pa.Wiring(run=lock, which=lambda _n: pf.BINARY),
                )
            finally:
                Path(scratch).chmod(0o700)
        self.assertEqual(result.code, pf.USAGE)
        self.assertIn("cannot write the report", result.stderr)

    def test_ctrl_c_while_delivering(self) -> None:
        phone = _clean_phone()
        with mock.patch.object(
            pa.phone_report, "format_text", side_effect=KeyboardInterrupt
        ):
            result = self.run_on(phone)
        self.assertEqual(result.code, pf.INTERRUPTED)
        self.assertIn("incomplete or not written", result.stderr)


class RealWiringTest(unittest.TestCase):
    """The real seams: the bounded runner and the PATH lookup."""

    def test_the_real_wiring(self) -> None:
        self.assertEqual(
            pa.real_wiring(), pa.Wiring(afc_calls.real_run, pa.shutil.which)
        )


class HelpTest(unittest.TestCase):
    """``--help`` states the prerequisites and the exit codes."""

    def test_the_epilog(self) -> None:
        text = pa.build_parser().format_help()
        for words in (
            "brew install libimobiledevice",
            "unlocked",
            "130",
            "(default: text)",
        ):
            with self.subTest(words=words):
                self.assertIn(words, text)


if __name__ == "__main__":
    unittest.main()
