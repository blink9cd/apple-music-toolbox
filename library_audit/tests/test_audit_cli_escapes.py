"""A path, album or artist holding a delimiter: listed, matched, and compared as before.

The listing script escapes each tab, line break, U+001F and percent sign in a track's
path and names, and the row parser undoes it, so such a track is placed like any other
rather than splitting its row and ending the run. The comparison of names is the one
it always was: both sides flattened, so a tab in one and a space in the other are one
album. Every runner is a `FakeMusic`, whose rows are escaped as the script writes them.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent), str(_HERE.parent / "src")]

import audit_fixtures as af  # noqa: E402 - import follows the sys.path bootstrap above

#: The summary of a clean audit of one file matched to one track.
_ONE_CLEAN = "summary: findings 0; audio files 1, Music.app tracks 1;"


class EscapedListingTest(af.AuditCase):
    """Delimiters in a track's path and names never cost it its place."""

    def test_a_path_holding_a_tab_and_line_breaks_matches_its_file(self) -> None:
        (path,) = self.album("Band/Al\tbum", "01 a\nb\rc%25.mp3")
        track = af.Track(1, str(path), track=1)
        tags = af.tag_table({path: af.tagged(1, 1)})
        result = self.audit(af.FakeMusic(tracks=[track]), tag_reader=tags)
        self.assertEqual(result.code, af.OK, result.stdout)
        self.assertIn(_ONE_CLEAN, result.stdout)
        self.assertIn("unparsed rows 0,", result.stdout)

    def test_names_holding_delimiters_read_back_and_group_with_their_file(self) -> None:
        (path,) = self.album("Band/Album", "01 a.mp3")
        artist, album = "The\nPlaceholder\x1fBand", "Invented\tAlbum 100%"
        track = af.Track(1, str(path), album=album, artist=artist, track=1)
        tags = af.tag_table({path: af.tagged(1, 1, artist=artist, album=album)})
        result = self.audit(af.FakeMusic(tracks=[track]), tag_reader=tags)
        self.assertEqual(result.code, af.OK, result.stdout)
        self.assertIn(_ONE_CLEAN, result.stdout)

    def test_a_tab_in_music_and_a_space_in_the_tag_are_one_album(self) -> None:
        # The comparison flattens both sides, as it did when the script flattened.
        (path,) = self.album("Band/Album", "01 a.mp3")
        track = af.Track(1, str(path), album="Invented\tAlbum", track=1)
        tags = af.tag_table({path: af.tagged(1, 1, album="Invented Album")})
        result = self.audit(af.FakeMusic(tracks=[track]), tag_reader=tags)
        self.assertEqual(result.code, af.OK, result.stdout)
        self.assertIn(_ONE_CLEAN, result.stdout)


if __name__ == "__main__":
    unittest.main()
