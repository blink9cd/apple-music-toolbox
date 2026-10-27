"""The hand run in samples/README.md, run for real against the sample's fake osascript.

The README's command runs in process, from the samples folder, with the arguments its
command line gives, the real ``stat``, walk and tag reader, and a runner that hands
each call to the samples folder's ``fake_bin/osascript`` through ``bash``. The fake is named
by its path, never looked up on ``PATH``, so this suite cannot reach the real
``osascript`` even if the fake went missing: the run would then fail, not fall through.
Every block must appear in the README as written, and the report must equal its block
with ``<samples>`` filled in.
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

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import library_audit as la  # noqa: E402 - import follows the sys.path bootstrap above
import audit_fixtures as af  # noqa: E402 - import follows the sys.path bootstrap above
import audit_tags  # noqa: E402 - import follows the sys.path bootstrap above
import audit_walk  # noqa: E402 - import follows the sys.path bootstrap above
import bounded_run  # noqa: E402 - import follows the sys.path bootstrap above

_SAMPLES = _HERE.parent / "samples"
_README = _SAMPLES / "README.md"
_FAKE = _SAMPLES / "fake_bin" / "osascript"
#: The guard each command line opens with: the fake must be here, or nothing runs.
_GUARD = "test -x fake_bin/osascript"
#: How the running line starts after its guard, and as the shell splits it after that.
_PATH_PREFIX = f'{_GUARD} && PATH="$PWD/fake_bin:$PATH"'
_PREFIX = ("python", "../library_audit.py")
_PLACEHOLDER = "<samples>"
#: What the guard says when the command is run from the wrong folder.
_WRONG_FOLDER = "run this from the samples folder"
#: An ID3v2 tag's header: ``ID3``, version, flags and the tag's size.
_ID3_HEADER = 10
#: How long the guard's shell may take: it runs one builtin and stops.
_GUARD_TIMEOUT_S = 30

COMMAND = f"""\
{_GUARD} || echo "{_WRONG_FOLDER}: fake_bin/osascript is not here" >&2
{_PATH_PREFIX} python ../library_audit.py --library library
"""
#: Where the HTML run writes its page: outside any repository, as --report requires.
_HTML_TARGET = '"${TMPDIR:-/tmp}/library_audit_sample.html"'
HTML_COMMAND = f"""\
{_PATH_PREFIX} python ../library_audit.py --library library --format html --report {_HTML_TARGET}
"""

_QUARTET = "<samples>/library/The Invented Quartet/Placeholder Album"
_TRIO = "<samples>/library/The Made-Up Trio/Lone Placeholder"
_DUO, _SPLIT = "The Split-Level Duo", "Split Placeholder Album"
_DUO_FOLDER = f"<samples>/library/{_DUO}/{_SPLIT}"
#: The duo as two of its three files spell it, with a typographic hyphen, U+2010.
_DUO_TYPOGRAPHIC = "The Split\u2010Level Duo"
#: The duo's files: not zero-byte, each an ID3 tag and no audio.
_TAG_ONLY = 3
#: The zero-byte placeholders: the quartet's three, the trio's one and the one outside.
_ZERO_BYTE = 5

REPORT = f"""\
library: <samples>/library
files with no Music.app track: 1
  {_QUARTET}/05 Stray Placeholder.mp3
Music.app tracks whose file is gone: 1
  The Invented Quartet / Placeholder Album, disc 1 track 2 [local only]: {_QUARTET}/02 Second Placeholder.mp3
track-number gaps: 0
albums split by spelling: 1
  {_DUO} / {_SPLIT}, disc 1: 2 spellings, still missing 4
    1. {_DUO} / {_SPLIT}: track 2
    2. {_DUO_TYPOGRAPHIC} / {_SPLIT}: tracks 1, 3
    1 and 2 differ in the artist: U+002D HYPHEN-MINUS vs U+2010 HYPHEN
files with no track number: 0
files and Music.app tracks differ: 0
unreadable tags: 4
  {_QUARTET}/01 First Placeholder.mp3
  {_QUARTET}/04 Fourth Placeholder.mp3
  {_QUARTET}/05 Stray Placeholder.mp3
  {_TRIO}/01 Lone Placeholder.m4a
unreadable files and folders: 0
iCloud placeholders: 0
Music.app size differs from the file: 1
  {_QUARTET}/01 First Placeholder.mp3: Music.app 4096, file 0
  note: Music.app's record is stale; tag_refresh makes it reread the file
unchecked tracks: 1
  The Split-Level Duo / Split Placeholder Album, disc 1 track 2: {_DUO_FOLDER}/02 Split Placeholder.mp3
  note: an unchecked track is skipped only when the phone syncs only checked songs
decode check not run (--decode)
the sync checks see this Mac only: Music.app cannot see an iPhone, so a track the phone lists but cannot play is not found here
summary: findings 9; audio files 7, Music.app tracks 9; cloud-only 1, outside --library 1, unparsed rows 0, sizes unknown 0
"""


def _fenced(body: str, language: str) -> str:
    """*body* as the README fences it."""
    return f"```{language}\n{body}```\n"


def _fake_osascript(
    argv: list[str], timeout: float
) -> subprocess.CompletedProcess[str]:
    """Hand one call's arguments to the sample's fake, by its path, through bash.

    Through `bounded_run`, as the real runner is: a captured ``subprocess.run`` would
    not hold its timeout if the fake left a child holding the pipes.
    """
    return bounded_run.run_bounded(["bash", str(_FAKE), *argv[1:]], timeout=timeout)


def _holds_only_an_id3_tag(path: Path) -> bool:
    """Whether *path* is one ID3v2 tag and not a byte more: no audio, no padding.

    The tag's size is the header's four 7-bit bytes, after the ten-byte header.
    """
    data = path.read_bytes()
    size = sum(byte << (7 * (3 - i)) for i, byte in enumerate(data[6:10]))
    return data[:3] == b"ID3" and len(data) == _ID3_HEADER + size


class SamplesTest(unittest.TestCase):
    """The README's blocks, as written, and what its command prints."""

    def setUp(self) -> None:
        """Run from the samples folder, as the README says, and come back after."""
        super().setUp()
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(_SAMPLES)

    def run_command(
        self, command: str = COMMAND, report: Path | None = None
    ) -> af.Outcome:
        """Run *command*'s running line in process, against the fake.

        *report*, when given, stands in for the line's own ``--report`` target, which
        names a shell variable the in-process run cannot expand.
        """
        running = command.splitlines()[-1]
        if report is not None:
            running = running.replace(_HTML_TARGET, shlex.quote(str(report)))
        self.assertTrue(running.startswith(_PATH_PREFIX + " "))
        self.assertTrue((_SAMPLES / "fake_bin" / "osascript").is_file())
        words = shlex.split(running[len(_PATH_PREFIX) :])
        self.assertEqual(tuple(words[: len(_PREFIX)]), _PREFIX)
        seams = la.Wiring(
            run=_fake_osascript,
            stat=os.stat,
            platform=af.DARWIN,
            walk=audit_walk.real_walk,
            tag_reader=audit_tags.load_tag_reader(),
            access=os.access,
            decode=af.never_decode,
        )
        return af.run_main(words[len(_PREFIX) :], seams)

    def test_every_block_appears_in_the_readme_as_written(self) -> None:
        text = _README.read_text(encoding="utf-8")
        for body, language in (
            (COMMAND, "bash"),
            (REPORT, "text"),
            (HTML_COMMAND, "bash"),
        ):
            with self.subTest(block=body.splitlines()[0]):
                self.assertIn(_fenced(body, language), text)

    @unittest.skipIf(audit_tags.load_tag_reader() is None, "mutagen is not installed")
    def test_the_command_prints_its_report(self) -> None:
        result = self.run_command()
        self.assertEqual(result.code, af.FINDINGS, result.stderr)
        self.assertEqual(
            result.stdout, REPORT.replace(_PLACEHOLDER, str(_SAMPLES.resolve()))
        )

    def test_the_html_command_writes_its_page(self) -> None:
        with TemporaryDirectory() as scratch:
            target = Path(scratch) / "library_audit_sample.html"
            result = self.run_command(HTML_COMMAND, target)
            page = target.read_text(encoding="utf-8")
        self.assertEqual(result.code, af.FINDINGS, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertTrue(page.startswith("<!DOCTYPE html>\n"))
        self.assertIn("<title>Library audit</title>", page)
        self.assertIn('<section id="no-track">', page)

    def test_from_another_folder_the_command_runs_nothing(self) -> None:
        # A real shell, in an empty folder, with an empty PATH: the guard must stop
        # the line before python, so the real osascript can never be found.
        bash = shutil.which("bash")
        assert bash is not None
        with TemporaryDirectory() as scratch:
            empty = Path(scratch) / "empty_bin"
            empty.mkdir()
            result = bounded_run.run_bounded(
                [bash, "-c", COMMAND],
                timeout=_GUARD_TIMEOUT_S,
                cwd=scratch,
                env={"PATH": str(empty)},
            )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(_WRONG_FOLDER, result.stderr)
        self.assertNotIn("command not found", result.stderr)

    def test_the_fake_refuses_a_script_it_does_not_know(self) -> None:
        result = _fake_osascript(["osascript", "-e", "anything else"], 30)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a script this sample answers", result.stderr)

    def test_every_sample_audio_file_is_a_placeholder_holding_no_audio(self) -> None:
        found = sorted(
            p for p in _SAMPLES.rglob("*") if p.suffix in audit_walk.AUDIO_SUFFIXES
        )
        tag_only = [p for p in found if p.parent.parent.name == _DUO]
        self.assertEqual(len(found), _ZERO_BYTE + _TAG_ONLY)
        self.assertEqual(len(tag_only), _TAG_ONLY)
        for path in found:
            with self.subTest(path=path.name):
                if path in tag_only:
                    self.assertTrue(_holds_only_an_id3_tag(path))
                else:
                    self.assertEqual(path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
