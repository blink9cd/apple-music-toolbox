"""The hand run in samples/README.md, run for real against the sample's fake afcclient.

The README's command runs in process, from the samples folder, with the arguments its
command line gives, the real runner, and ``afcclient`` looked up on a PATH holding
the samples folder's ``fake_bin`` alone, so this suite cannot reach a real afcclient
even if the fake went missing: the run would then fail, not fall through. Every block
must appear in the README as written, and the report must equal its block.
"""

from __future__ import annotations

import os
import shlex
import shutil
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
import bounded_run  # noqa: E402 - import follows the sys.path bootstrap above

_SAMPLES = _HERE.parent / "samples"
_README = _SAMPLES / "README.md"
_FAKE_BIN = _SAMPLES / "fake_bin"
_FAKE = _FAKE_BIN / "afcclient"
#: The variables that make the fake misbehave on request: unplug the phone, or fail
#: the stat of the named file in a listing.
_DISCONNECT = "FAKE_AFCCLIENT_DISCONNECT"
_STAT_FAIL = "FAKE_AFCCLIENT_STAT_FAIL"
#: The guard each command line opens with: the fake must be here, or nothing runs.
_GUARD = "test -x fake_bin/afcclient"
#: How the running line starts after its guard, and as the shell splits it after that.
_PATH_PREFIX = f'{_GUARD} && PATH="$PWD/fake_bin:$PATH"'
_PREFIX = ("python", "../phone_audit.py")
#: What the guard says when the command is run from the wrong folder.
_WRONG_FOLDER = "run this from the samples folder"
#: How long a shell or a fake call may take: each does a little local work and stops.
_SHELL_TIMEOUT_S = 30

COMMAND = f"""\
{_GUARD} || echo "{_WRONG_FOLDER}: fake_bin/afcclient is not here" >&2
{_PATH_PREFIX} python ../phone_audit.py
"""

#: Where the HTML run writes its page: outside any repository, as --report requires.
_HTML_TARGET = '"${TMPDIR:-/tmp}/phone_audit_sample.html"'
HTML_COMMAND = f"""\
{_PATH_PREFIX} python ../phone_audit.py --format html --report {_HTML_TARGET}
"""

REPORT = """\
rows with no file on the phone: 1
  The Placeholder Band / Invented Album, disc 1 track 2: Second Placeholder [F00/BBBB.mp3]
  note: a plain Finder sync does not repair these; add a character to each title, sync, restore it and sync again (phone_audit.md, "Repairing a row with no file")
size differs: 1
  The Placeholder Band / Invented Album, disc 1 track 3: Third Placeholder [F01/CCCC.m4a]: phone file 8000, database 8192
files with no row: 1
  F01/ZZZZ.mp3: 2048 bytes
  note: listed only; neither a sync nor this tool removes them
summary: findings 2; rows in the sync 3, files 3; outside the sync 1, unparsed lines 0, sizes unknown 0, other entries 0
"""


def _fenced(body: str, language: str) -> str:
    """*body* as the README fences it."""
    return f"```{language}\n{body}```\n"


def _fake(
    *argv: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the fake with ``--`` then *argv*, with *env* added to this environment."""
    return bounded_run.run_bounded(
        [str(_FAKE), "--", *argv],
        timeout=_SHELL_TIMEOUT_S,
        env={**os.environ, **(env or {})},
    )


def _fake_only(name: str) -> str | None:
    """*name* looked up on a PATH holding the fake's folder and nothing else."""
    return shutil.which(name, path=str(_FAKE_BIN))


@unittest.skipIf(
    shutil.which("sqlite3") is None, "the fake builds its database with sqlite3"
)
class SamplesTest(unittest.TestCase):
    """The README's blocks, as written, and what its command prints."""

    def setUp(self) -> None:
        """Run from the samples folder, as the README says, and come back after."""
        super().setUp()
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(_SAMPLES)

    def test_every_block_appears_in_the_readme_as_written(self) -> None:
        text = _README.read_text(encoding="utf-8")
        for body, language in (
            (COMMAND, "bash"),
            (REPORT, "text"),
            (HTML_COMMAND, "bash"),
        ):
            with self.subTest(block=body.splitlines()[0]):
                self.assertIn(_fenced(body, language), text)

    def test_the_command_prints_its_report(self) -> None:
        running = COMMAND.splitlines()[-1]
        self.assertTrue(running.startswith(_PATH_PREFIX + " "))
        words = shlex.split(running[len(_PATH_PREFIX) :])
        self.assertEqual(tuple(words[: len(_PREFIX)]), _PREFIX)
        seams = pa.Wiring(run=afc_calls.real_run, which=_fake_only)
        result = pf.run_main(words[len(_PREFIX) :], seams)
        self.assertEqual(result.code, pf.FINDINGS, result.stderr)
        self.assertEqual(result.stdout, REPORT)
        self.assertNotIn("proven against", result.stderr)

    def test_the_html_command_writes_its_page(self) -> None:
        # The README's target is the temporary folder; this run writes to its own.
        with TemporaryDirectory() as scratch:
            page = Path(scratch) / "page.html"
            running = HTML_COMMAND.strip().replace(_HTML_TARGET, shlex.quote(str(page)))
            self.assertTrue(running.startswith(_PATH_PREFIX + " "))
            words = shlex.split(running[len(_PATH_PREFIX) :])
            self.assertEqual(tuple(words[: len(_PREFIX)]), _PREFIX)
            seams = pa.Wiring(run=afc_calls.real_run, which=_fake_only)
            result = pf.run_main(words[len(_PREFIX) :], seams)
            written = page.read_text(encoding="utf-8")
        self.assertEqual(result.code, pf.FINDINGS, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertTrue(written.startswith("<!DOCTYPE html>\n"))
        for cell in ("<td>F00/BBBB.mp3</td>", "<td>F01/ZZZZ.mp3</td>"):
            with self.subTest(cell=cell):
                self.assertIn(cell, written)

    def test_from_another_folder_the_command_runs_nothing(self) -> None:
        # A real shell, in an empty folder, with an empty PATH: the guard must stop
        # the line before python, so a real afcclient can never be found.
        bash = shutil.which("bash")
        assert bash is not None
        with TemporaryDirectory() as scratch:
            empty = Path(scratch) / "empty_bin"
            empty.mkdir()
            result = bounded_run.run_bounded(
                [bash, "-c", COMMAND],
                timeout=_SHELL_TIMEOUT_S,
                cwd=scratch,
                env={"PATH": str(empty)},
            )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(_WRONG_FOLDER, result.stderr)
        self.assertNotIn("command not found", result.stderr)

    def test_the_fake_refuses_a_command_it_does_not_serve(self) -> None:
        for argv in (
            ["--", "rm", "/x"],
            ["--", "put", "a", "/x"],
            ["--", "get", "-f", "/x", "y"],
        ):
            with self.subTest(argv=argv):
                result = afc_calls.real_run([str(_FAKE), *argv], _SHELL_TIMEOUT_S)
                self.assertEqual(result.returncode, 1)
                self.assertIn("not a command this sample serves", result.stderr)

    def test_the_fake_serves_only_the_jail_relative_paths(self) -> None:
        # AFC's root is the device's /var/mobile/Media, so the device-absolute form of
        # each path is a missing object, as afcclient reports one.
        absolute = "/var/mobile/Media"
        music = absolute + pf.MUSIC
        for argv, line in (
            (["ls", "-l", music], pf.LS_NOT_FOUND.format(path=music)),
            (["ls", "-l", music + "/F00"], pf.LS_NOT_FOUND.format(path=music + "/F00")),
            (["ls", "-l", "F00"], pf.LS_NOT_FOUND.format(path="F00")),
        ):
            with self.subTest(argv=argv):
                result = _fake(*argv)
                self.assertEqual((result.returncode, result.stdout), (0, line))
        with TemporaryDirectory() as scratch:
            local = Path(scratch) / "copy"
            remote = absolute + pf.DB_REMOTE
            result = _fake("get", remote, str(local))
            self.assertFalse(local.exists())
        self.assertEqual(result.stdout, pf.NOT_FOUND.format(path=remote))

    def test_the_fake_disconnects_on_request(self) -> None:
        result = _fake("ls", "-l", pf.MUSIC, env={_DISCONNECT: "1"})
        self.assertEqual((result.returncode, result.stdout), (0, pf.DISCONNECTED))

    def test_the_fake_fails_a_stat_on_request(self) -> None:
        result = _fake("ls", "-l", pf.MUSIC + "/F00", env={_STAT_FAIL: "AAAA.mp3"})
        self.assertEqual(result.stdout, pf.zeroed_line("AAAA.mp3"))

    def test_the_sample_run_refuses_a_disconnect_and_counts_a_failed_stat(self) -> None:
        seams = pa.Wiring(run=afc_calls.real_run, which=_fake_only)
        with mock.patch.dict(os.environ, {_DISCONNECT: "1"}):
            gone = pf.run_main([], seams)
        self.assertEqual(gone.code, pf.USAGE)
        self.assertIn("disconnected", gone.stderr)
        with mock.patch.dict(os.environ, {_STAT_FAIL: "AAAA.mp3"}):
            stat = pf.run_main([], seams)
        self.assertEqual(stat.code, pf.FINDINGS, stat.stderr)
        self.assertIn("unparsed lines 1,", stat.stdout)
        self.assertIn("listing line(s) unparsed", stat.stderr)

    def test_the_fake_refuses_to_overwrite_a_local_file(self) -> None:
        with TemporaryDirectory() as scratch:
            taken = Path(scratch) / "taken"
            taken.write_bytes(b"mine")
            result = afc_calls.real_run(
                [str(_FAKE), "--", "get", pf.DB_REMOTE, str(taken)], _SHELL_TIMEOUT_S
            )
            self.assertEqual(taken.read_bytes(), b"mine")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith("Error: Failed to overwrite"))


if __name__ == "__main__":
    unittest.main()
