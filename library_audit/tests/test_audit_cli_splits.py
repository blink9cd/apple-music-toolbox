"""Albums split by a spelling difference, end to end through `main`.

Each case is an invented library whose files carry one album under two spellings of its
artist, with every file matched to a track of an `audit_fixtures.FakeMusic` runner, so
the split is the run's only possible finding. Nothing reaches Music.app.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import audit_fixtures as af  # noqa: E402 - import follows the sys.path bootstrap above

_DUO = "The Split-Level Duo"
#: The same artist with a typographic hyphen, U+2010: it prints just like the other.
_DUO_TYPOGRAPHIC = "The Split‐Level Duo"
_ALBUM = af.ALBUM
_NOTE = "U+002D HYPHEN-MINUS vs U+2010 HYPHEN"


class SplitAlbumTest(af.AuditCase):
    """One album under two spellings is one finding, in its own section."""

    def library_of(
        self, halves: dict[str, tuple[int, ...]], total: int | None, **albums: str
    ) -> tuple[af.FakeMusic, af.audit_tags.TagReader]:
        """Files for each artist spelling's track numbers, all matched in Music.

        Each half is of the invented album unless *albums* names another for it, keyed
        ``first`` or ``second`` in the order *halves* gives.
        """
        tracks: list[af.Track] = []
        table: dict[Path, af.audit_tags.FileTags] = {}
        for which, (artist, numbers) in zip(
            ("first", "second"), halves.items(), strict=True
        ):
            album = albums.get(which, _ALBUM)
            for number in numbers:
                (path,) = self.album(album, f"{number:02d} {len(tracks)}.mp3")
                table[path] = af.tagged(number, total, artist=artist, album=album)
                tracks.append(
                    af.Track(
                        len(tracks) + 1,
                        str(path),
                        album=album,
                        artist=artist,
                        track=number,
                    )
                )
        return af.FakeMusic(tracks=tracks), af.tag_table(table)

    def test_an_album_split_by_an_invisible_hyphen_is_one_finding(self) -> None:
        music, tags = self.library_of({_DUO_TYPOGRAPHIC: (1, 3), _DUO: (2, 4)}, 4)
        result = self.audit(music, tag_reader=tags)
        self.assertEqual(result.code, af.FINDINGS)
        self.assertEqual(
            result.stdout,
            f"library: {self.library}\n"
            "files with no Music.app track: 0\n"
            "Music.app tracks whose file is gone: 0\n"
            "track-number gaps: 0\n"
            "albums split by spelling: 1\n"
            f"  {_DUO} / {_ALBUM}, disc 1: 2 spellings\n"
            f"    1. {_DUO} / {_ALBUM}: tracks 2, 4\n"
            f"    2. {_DUO_TYPOGRAPHIC} / {_ALBUM}: tracks 1, 3\n"
            f"    1 and 2 differ in the artist: {_NOTE}\n"
            "files with no track number: 0\n"
            "files and Music.app tracks differ: 0\n"
            "unreadable tags: 0\n"
            "unreadable files and folders: 0\n"
            "iCloud placeholders: 0\n"
            "Music.app size differs from the file: 0\n"
            "unchecked tracks: 0\n"
            "decode check not run (--decode)\n"
            "the sync checks see this Mac only: Music.app cannot see an iPhone, so a track"
            " the phone lists but cannot play is not found here\n"
            "summary: findings 1; audio files 4, Music.app tracks 4;"
            " cloud-only 0, outside --library 0, unparsed rows 0, sizes unknown 0\n",
        )

    def test_a_number_the_joined_album_still_lacks_is_shown_once(self) -> None:
        music, tags = self.library_of({_DUO_TYPOGRAPHIC: (1, 2, 3), _DUO: (4,)}, 6)
        result = self.audit(music, tag_reader=tags)
        self.assertEqual(result.code, af.FINDINGS)
        lines = result.stdout.splitlines()
        self.assertIn("track-number gaps: 0", lines)
        self.assertIn(
            f"  {_DUO} / {_ALBUM}, disc 1: 2 spellings, still missing 5-6", lines
        )
        self.assertIn(f"    1. {_DUO} / {_ALBUM}: track 4", lines)
        self.assertIn(f"    2. {_DUO_TYPOGRAPHIC} / {_ALBUM}: tracks 1-3", lines)
        self.assertEqual(sum("5-6" in line for line in lines), 1)
        self.assertTrue(lines[-1].startswith("summary: findings 1;"), lines[-1])

    def test_complementary_numbers_under_unrelated_names_stay_two_gaps(self) -> None:
        music, tags = self.library_of(
            {"The Made-Up Trio": (1, 3), "The Invented Quartet": (2, 4)},
            4,
            second="Second Invented Album",
        )
        result = self.audit(music, tag_reader=tags)
        lines = result.stdout.splitlines()
        self.assertIn("track-number gaps: 2", lines)
        self.assertIn("albums split by spelling: 0", lines)
        self.assertTrue(lines[-1].startswith("summary: findings 2;"), lines[-1])

    def test_the_json_report_lists_the_split(self) -> None:
        music, tags = self.library_of({_DUO_TYPOGRAPHIC: (1, 3), _DUO: (2,)}, 4)
        result = self.audit(music, "--format", "json", tag_reader=tags)
        self.assertEqual(result.code, af.FINDINGS)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], 4)
        self.assertEqual(report["findings"], 1)
        self.assertEqual(report["track_gaps"], [])
        self.assertEqual(
            report["split_albums"],
            [
                {
                    "disc": 1,
                    "spellings": [
                        {"artist": _DUO, "album": _ALBUM, "tracks": [2]},
                        {"artist": _DUO_TYPOGRAPHIC, "album": _ALBUM, "tracks": [1, 3]},
                    ],
                    "still_missing": [4],
                    "differs": [
                        {"between": [0, 1], "artist": _NOTE, "album": None},
                    ],
                }
            ],
        )

    def test_without_mutagen_the_split_section_is_skipped_too(self) -> None:
        music, _tags = self.library_of({_DUO_TYPOGRAPHIC: (1, 3), _DUO: (2, 4)}, 4)
        result = self.audit(music, tag_reader=None)
        self.assertEqual(result.code, af.OK)
        self.assertIn("tag checks skipped: mutagen not installed", result.stdout)
        self.assertNotIn("albums split by spelling", result.stdout)
        report = json.loads(self.audit(music, "--format", "json").stdout)
        self.assertIsNone(report["split_albums"])


if __name__ == "__main__":
    unittest.main()
