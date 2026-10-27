"""The walk-through in samples/README.md, run for real against a fake Music.app.

The list is built by running the README's own block in bash, from the samples folder,
with ``TMPDIR`` pointed inside this test's directory, which the block's ``mktemp``
template honors. Both commands then run in
process, from the samples folder, with the arguments the README's command lines give,
the real stat and tag reader, and a fake Music holding no tracks, as a Music.app that
has none of the invented albums answers. Every block must appear in the README as
written, and each report must equal its block with ``<samples>`` filled in.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import tag_refresh as amr  # noqa: E402 - import follows the sys.path bootstrap above
import cli_fixtures as cf  # noqa: E402 - import follows the sys.path bootstrap above

_SAMPLES = _HERE.parent / "samples"
_README = _SAMPLES / "README.md"
#: How long the list-building block may take.
_BUILD_TIMEOUT_S = 30
#: How each command line starts, as the shell splits it.
_PREFIX = ("python", "../tag_refresh.py")
_PLACEHOLDER = "<samples>"

BUILD = """\
SAMPLES="$PWD"  # run from this tool's samples/ folder
LIST="$(mktemp -d "${TMPDIR:-/tmp}/amr-sample.XXXXXX")/changed.txt"
find "$SAMPLES/library" -name '*.mp3' | LC_ALL=C sort > "$LIST"
"""

LIST_COMMAND = """\
python ../tag_refresh.py --tracks-from "$LIST" --dry-run
"""

ALBUM_COMMAND = """\
python ../tag_refresh.py --album "library/The Made-Up Trio/Two Disc Placeholder" --dry-run
"""

_QUARTET = "<samples>/library/The Invented Quartet/Placeholder Album"
_TRIO = "<samples>/library/The Made-Up Trio/Two Disc Placeholder"

LIST_REPORT = f"""\
{_QUARTET}: would refresh 0, not in Music 2
{_TRIO}/Disc 1: would refresh 0, not in Music 1
{_TRIO}/Disc 2: would refresh 0, not in Music 1
not in Music:
  {_QUARTET}/01 First Placeholder.mp3
  {_QUARTET}/02 Second Placeholder.mp3
  {_TRIO}/Disc 1/01 Third Placeholder.mp3
  {_TRIO}/Disc 2/01 Fourth Placeholder.mp3
total: would refresh 0, not in Music 4, stale 0, errors 0, stopped 0 (album folders 3, MP3s 4)
"""

ALBUM_REPORT = f"""\
{_TRIO}/Disc 1: would refresh 0, not in Music 1
{_TRIO}/Disc 2: would refresh 0, not in Music 1
not in Music:
  {_TRIO}/Disc 1/01 Third Placeholder.mp3
  {_TRIO}/Disc 2/01 Fourth Placeholder.mp3
total: would refresh 0, not in Music 2, stale 0, errors 0, stopped 0 (album folders 2, MP3s 2)
"""


def _fenced(body: str, language: str) -> str:
    """*body* as the README fences it."""
    return f"```{language}\n{body}```\n"


class SamplesTest(cf.CliCase):
    """The README's blocks, as written, and what its commands print."""

    def setUp(self) -> None:
        """Run from the samples folder, as the README says, and come back after."""
        super().setUp()
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(_SAMPLES)

    def build_list(self) -> str:
        """Run the README's build block in bash; return the list file's path.

        The block's ``$LIST`` is reported through a file, not a pipe, so the timeout
        binds: nothing captured can be held open by a grandchild.
        """
        env = {**os.environ, "TMPDIR": str(self.root)}
        report = self.root / "list-path.txt"
        subprocess.run(
            ["bash", "-c", BUILD + 'printf "%s" "$LIST" > "$1"', "bash", str(report)],
            cwd=_SAMPLES,
            env=env,
            check=True,
            timeout=_BUILD_TIMEOUT_S,
        )
        return report.read_text(encoding="utf-8")

    def run_command(self, command: str, list_path: str = "") -> cf.Outcome:
        """Run one README command line in process, against a Music holding nothing."""
        words = shlex.split(command.replace('"$LIST"', shlex.quote(list_path)))
        self.assertEqual(tuple(words[: len(_PREFIX)]), _PREFIX)
        self.music = cf.FakeMusic()
        seams = cf.wiring(self.music, tag_reader=amr.load_tag_reader())
        return cf.run_main(words[len(_PREFIX) :], seams)

    def expected(self, report: str) -> str:
        """*report* with the placeholder filled in."""
        return report.replace(_PLACEHOLDER, str(_SAMPLES))

    def test_every_block_appears_in_the_readme_as_written(self) -> None:
        text = _README.read_text(encoding="utf-8")
        for body, language in (
            (BUILD, "bash"),
            (LIST_COMMAND, "bash"),
            (ALBUM_COMMAND, "bash"),
            (LIST_REPORT, "text"),
            (ALBUM_REPORT, "text"),
        ):
            with self.subTest(block=body.splitlines()[0]):
                self.assertIn(_fenced(body, language), text)

    def test_the_list_command_prints_its_report(self) -> None:
        listed = self.build_list()
        self.assertTrue(Path(listed).is_relative_to(self.root), listed)
        result = self.run_command(LIST_COMMAND, listed)
        self.assertEqual(result.code, 0)
        self.assertEqual(result.stdout, self.expected(LIST_REPORT))
        self.assertNotIn(cf.REFRESH_IDS, self.music.kinds())

    def test_the_album_command_prints_its_report(self) -> None:
        result = self.run_command(ALBUM_COMMAND)
        self.assertEqual(result.code, 0)
        self.assertEqual(result.stdout, self.expected(ALBUM_REPORT))
        self.assertEqual(self.music.kinds(), [cf.IS_RUNNING, cf.LOOKUP, cf.LOOKUP])

    def test_every_sample_mp3_is_a_zero_byte_placeholder(self) -> None:
        found = sorted(_SAMPLES.rglob("*.mp3"))
        self.assertEqual(len(found), 4)
        for path in found:
            with self.subTest(path=path.name):
                self.assertEqual(path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
