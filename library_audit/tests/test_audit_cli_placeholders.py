"""The tag checks never open an iCloud placeholder: they take its tags from its track.

Opening a placeholder makes iCloud download it, so the tag reader here fails the test
outright when it is handed one. A placeholder matched to a Music.app track takes its
album, artist, disc, track number and compilation flag from that track's listing row;
one with no track groups by its folder and is not listed as having unreadable tags.
The placeholder flag is an invented stat flag (a real one cannot be made here), Music
is the `audit_fixtures.FakeMusic` runner, and nothing reaches Music.app or the host.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import audit_fixtures as af  # noqa: E402 - import follows the sys.path bootstrap above
import audit_tags  # noqa: E402 - import follows the sys.path bootstrap above
import audit_walk  # noqa: E402 - import follows the sys.path bootstrap above


class PlaceholderTagsTest(af.AuditCase):
    """An album of three files whose middle one is an iCloud placeholder."""

    def setUp(self) -> None:
        """The three files; the first and last carry tags, the middle is a placeholder."""
        super().setUp()
        self.first, self.away, self.last = self.album(
            "Band/Album", "a.mp3", "b.mp3", "c.mp3"
        )
        self.tags = {self.first: af.tagged(1, 3), self.last: af.tagged(3, 3)}

    def reader(self) -> audit_tags.TagReader:
        """The tag reader: the table's tags, and a test failure for the placeholder."""

        def _read(path: Path) -> audit_tags.FileTags | None:
            if path == self.away:
                raise AssertionError(f"the tag reader opened a placeholder: {path}")
            return self.tags.get(path)

        return _read

    def report(self, *tracks: af.Track) -> dict[str, object]:
        """The JSON report of the album against *tracks*, the placeholder flagged."""

        def _stat(path: str) -> os.stat_result:
            real = os.stat(path)
            flags = audit_walk.SF_DATALESS if path == str(self.away) else 0
            return os.stat_result(tuple(real)[:10], {"st_flags": flags})

        seams = af.wiring(af.FakeMusic(tracks=tracks), tag_reader=self.reader())
        argv = ["--library", str(self.library), "--format", "json"]
        result = af.run_main(argv, dataclasses.replace(seams, stat=_stat))
        self.assertEqual(result.code, af.FINDINGS, result.stderr)
        report: dict[str, object] = json.loads(result.stdout)
        return report

    def matched(self, placeholder: af.Track) -> dict[str, object]:
        """The report with every file matched, *placeholder* the placeholder's track."""
        return self.report(
            af.Track(1, str(self.first), track=1),
            placeholder,
            af.Track(3, str(self.last), track=3),
        )

    def track(
        self,
        *,
        track: int,
        disc: int = 1,
        artist: str = af.BAND,
        album: str = af.ALBUM,
        compilation: bool = False,
    ) -> af.Track:
        """The placeholder's track, numbered *track* on *disc* of *artist*'s *album*."""
        return af.Track(
            2,
            str(self.away),
            album=album,
            artist=artist,
            disc=disc,
            track=track,
            compilation=compilation,
        )

    def test_a_matched_placeholder_fills_its_album_with_no_gap_or_count_difference(
        self,
    ) -> None:
        # Disc 0 is Music.app's "no disc number", the first disc as a file's absent tag.
        report = self.matched(self.track(track=2, disc=0))
        self.assertEqual(report["icloud_placeholders"], [str(self.away)])
        self.assertEqual(report["track_gaps"], [])
        self.assertEqual(report["count_differs"], [])
        self.assertEqual(report["unreadable_tags"], [])
        self.assertEqual(report["no_track_number"], [])
        self.assertEqual(report["findings"], 1)

    def test_a_matched_placeholder_groups_by_its_track_album(self) -> None:
        # Another album by another artist, track 1 of its own: the placeholder leaves
        # the folder's album, which then lacks its track 2.
        report = self.matched(
            self.track(track=1, artist="Other Invented", album="Other Invented Album")
        )
        self.assertEqual(report["count_differs"], [])
        self.assertEqual(report["split_albums"], [])
        gaps = report["track_gaps"]
        assert isinstance(gaps, list)
        self.assertEqual(
            [(gap["album"], gap["missing"]) for gap in gaps], [(af.ALBUM, [2])]
        )

    def test_a_compilation_track_groups_its_placeholder_as_a_compilation(self) -> None:
        self.tags = {
            self.first: af.tagged(1, 3, artist="One Invented", compilation=True),
            self.last: af.tagged(3, 3, artist="Two Invented", compilation=True),
        }
        report = self.matched(
            self.track(track=2, artist="Three Invented", compilation=True)
        )
        self.assertEqual(report["track_gaps"], [])
        self.assertEqual(report["count_differs"], [])

    def test_a_track_number_of_zero_is_no_track_number(self) -> None:
        report = self.matched(self.track(track=0))
        self.assertEqual(report["no_track_number"], [str(self.away)])
        self.assertEqual(report["unreadable_tags"], [])

    def test_an_unmatched_placeholder_groups_by_folder_without_unreadable_tags(
        self,
    ) -> None:
        report = self.report(
            af.Track(1, str(self.first), track=1),
            af.Track(3, str(self.last), track=3),
        )
        self.assertEqual(report["no_track"], [str(self.away)])
        self.assertEqual(report["unreadable_tags"], [])
        self.assertEqual(report["no_track_number"], [])
        self.assertEqual(
            report["count_differs"],
            [
                {
                    "grouped_by": "folder",
                    "artist": None,
                    "album": None,
                    "disc": None,
                    "folder": str(self.away.parent),
                    "files": 1,
                    "tracks": 0,
                }
            ],
        )
        gaps = report["track_gaps"]
        assert isinstance(gaps, list)
        self.assertEqual([gap["missing"] for gap in gaps], [[2]])


if __name__ == "__main__":
    unittest.main()
