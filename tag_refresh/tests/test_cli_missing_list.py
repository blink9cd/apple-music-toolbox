"""``--missing-list``: the paths Music.app lacks, written to a file after an explicit run.

Every run goes through `main` with a `cli_fixtures.FakeMusic` runner; nothing reaches
Music.app. The list is a file in the list format ``--tracks-from`` reads, replaced
atomically, and refused before any call when it would land inside a git working tree,
where a list of library paths must never be committed.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import tag_refresh as amr  # noqa: E402 - import follows the sys.path bootstrap above
import cli_fixtures as cf  # noqa: E402 - import follows the sys.path bootstrap above

_OK, _PARTIAL, _USAGE, _INTERRUPTED = 0, 1, 2, 130


class MissingListCase(cf.CliCase):
    """One album of three MP3s, of which Music holds the first only."""

    def setUp(self) -> None:
        """Make the album, a Music holding one of its tracks, and an output folder."""
        super().setUp()
        self.mp3s = self.album(
            "Band/Invented Album", "01 a.mp3", "02 b.mp3", "03 c.mp3"
        )
        self.music = cf.FakeMusic(
            tracks=[cf.Track(11, cf.pid(11), "Invented Album", self.mp3s[0])]
        )
        (self.root / "out").mkdir()
        self.target = self.root / "out" / "missing.txt"

    def run_album(self, *extra: str) -> cf.Outcome:
        """Run explicit mode over the album with *extra* options."""
        argv = ["--album", str(self.mp3s[0].parent), *extra]
        return cf.run_main(argv, cf.wiring(self.music))


class MissingListTest(MissingListCase):
    """What the file holds, and when the run refuses to write it."""

    def test_the_paths_music_lacks_are_written_one_per_line(self) -> None:
        result = self.run_album("--missing-list", str(self.target))
        self.assertEqual(result.code, _OK)
        self.assertEqual(
            self.target.read_bytes(),
            f"{self.mp3s[1]}\n{self.mp3s[2]}\n".encode(),
        )

    def test_a_dry_run_writes_the_list_too(self) -> None:
        result = self.run_album("--dry-run", "--missing-list", str(self.target))
        self.assertEqual(result.code, _OK)
        self.assertEqual(self.target.read_bytes().count(b"\n"), 2)

    def test_nothing_missing_writes_an_empty_list(self) -> None:
        self.music.tracks = tuple(
            cf.Track(10 + n, cf.pid(10 + n), "Invented Album", mp3)
            for n, mp3 in enumerate(self.mp3s)
        )
        self.target.write_bytes(b"stale\n")
        result = self.run_album("--missing-list", str(self.target))
        self.assertEqual(result.code, _OK)
        self.assertEqual(self.target.read_bytes(), b"")

    def test_without_the_option_no_file_is_written(self) -> None:
        result = self.run_album()
        self.assertEqual(result.code, _OK)
        self.assertEqual(list((self.root / "out").iterdir()), [])

    def test_a_target_inside_a_working_tree_is_refused_before_any_call(self) -> None:
        (self.root / "repo" / ".git").mkdir(parents=True)
        target = self.root / "repo" / "missing.txt"
        result = self.run_album("--missing-list", str(target))
        self.assertEqual(result.code, _USAGE)
        self.assertEqual(self.music.calls, [])
        self.assertIn("git working tree", result.stderr)
        self.assertFalse(target.exists())

    def test_a_target_in_a_missing_folder_is_refused_before_any_call(self) -> None:
        result = self.run_album("--missing-list", str(self.root / "no" / "list.txt"))
        self.assertEqual(result.code, _USAGE)
        self.assertEqual(self.music.calls, [])

    def test_the_whole_library_mode_refuses_the_option(self) -> None:
        argv = ["--whole-library", "--missing-list", str(self.target)]
        result = cf.run_main(argv, cf.wiring(self.music))
        self.assertEqual(result.code, _USAGE)
        self.assertIn("--missing-list", result.stderr)
        self.assertEqual(self.music.calls, [])

    def test_a_failed_write_is_reported_and_exits_one(self) -> None:
        with mock.patch.object(
            amr.report_file, "write_atomically", side_effect=OSError("invented")
        ):
            result = self.run_album("--missing-list", str(self.target))
        self.assertEqual(result.code, _PARTIAL)
        self.assertIn("cannot write the missing list", result.stderr)

    def test_a_target_refused_when_the_run_ends_is_not_written(self) -> None:
        # Fine at start, refusable by the time the list is written (a repository made
        # around its folder mid-run, say): asked again just before the write.
        with mock.patch.object(
            amr.report_file, "refusal", side_effect=[None, "invented refusal"]
        ) as refusal:
            result = self.run_album("--missing-list", str(self.target))
        self.assertEqual(result.code, _PARTIAL)
        self.assertIn("--missing-list: invented refusal", result.stderr)
        self.assertEqual(refusal.call_count, 2)
        self.assertFalse(self.target.exists())

    def test_an_interrupted_run_still_writes_what_it_found(self) -> None:
        with mock.patch.object(amr, "_notice", cf.interrupt_notice(1)):
            result = self.run_album("--missing-list", str(self.target))
        self.assertEqual(result.code, _INTERRUPTED)
        self.assertTrue(self.target.exists())

    def test_a_path_holding_a_linefeed_is_reported_not_written(self) -> None:
        odd = self.touch("Band/Invented Album/04 line\nfeed.mp3")
        result = self.run_album("--missing-list", str(self.target))
        self.assertEqual(result.code, _OK)
        written = self.target.read_bytes()
        self.assertNotIn(b"line\nfeed", written)
        self.assertEqual(written.count(b"\n"), 2)
        self.assertIn("holds a linefeed", result.stderr)
        self.assertTrue(odd.exists())


if __name__ == "__main__":
    unittest.main()
