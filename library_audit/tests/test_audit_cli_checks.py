"""Every check at once, end to end: one invented library holding one case of each.

The run goes through `main` with an `audit_fixtures.FakeMusic` runner and a tag table;
nothing reaches Music.app. The text report is asserted whole, so its wording is pinned
here as the companion doc shows it.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import audit_fixtures as af  # noqa: E402 - import follows the sys.path bootstrap above

_BAND, _ALBUM = af.BAND, af.ALBUM
_TRIO, _SECOND = "The Made-Up Trio", "Second Invented Album"
_VARIOUS = "Various Placeholders"


class EveryCheckTest(af.AuditCase):
    """One file Music lacks, two tracks gone, a gap, an unnumbered file, and more."""

    def setUp(self) -> None:
        """Make the library and the Music that disagrees with it in every way."""
        super().setUp()
        self.first, self.third, self.bonus = self.album(
            f"{_BAND}/{_ALBUM}", "01 a.mp3", "03 c.mp3", "04 bonus.mp3"
        )
        self.shared, self.untitled = self.album(
            f"{_TRIO}/{_SECOND}", "01 x.mp3", "untitled.mp3"
        )
        outside = self.touch("elsewhere/01 y.mp3")
        self.gone = self.library / _BAND / _ALBUM / "02 b.mp3"
        self.music = af.FakeMusic(
            tracks=[
                af.Track(1, str(self.first), track=1),
                af.Track(2, str(self.third), track=3),
                af.Track(3, str(self.gone), track=2),
                af.Track(4, "", "removed", "Lost Album", _TRIO, 1, 5),
                af.Track(5, "", "subscription"),
                af.Track(6, str(outside)),
                af.Track(7, str(self.shared), album=_SECOND, artist=_TRIO),
                af.Track(8, str(self.shared), album=_SECOND, artist=_TRIO),
                af.Track(9, str(self.untitled), album=_SECOND, artist=_TRIO),
            ]
        )
        self.tags = af.tag_table(
            {
                self.first: af.tagged(1, 3),
                self.third: af.tagged(3, 3),
                self.shared: af.tagged(1, 1, album=_SECOND, artist=_TRIO),
                self.untitled: af.tagged(None, album=_SECOND, artist=_TRIO),
            }
        )

    def test_the_text_report_lists_each_finding_under_its_check(self) -> None:
        result = self.audit(self.music, tag_reader=self.tags)
        lib = self.library
        self.assertEqual(result.code, af.FINDINGS)
        self.assertEqual(
            result.stdout,
            f"library: {lib}\n"
            "files with no Music.app track: 1\n"
            f"  {self.bonus}\n"
            "Music.app tracks whose file is gone: 2\n"
            f"  {_TRIO} / Lost Album, disc 1 track 5 [removed]: no location\n"
            f"  {_BAND} / {_ALBUM}, disc 1 track 2 [local only]: {self.gone}\n"
            "track-number gaps: 1\n"
            f"  {_BAND} / {_ALBUM}, disc 1: missing 2 (files 2, track-count tag 3)\n"
            "albums split by spelling: 0\n"
            "files with no track number: 1\n"
            f"  {self.untitled}\n"
            "files and Music.app tracks differ: 4\n"
            f"  {_TRIO} / Lost Album, disc 1: files 0, Music.app tracks 1\n"
            f"  {_TRIO} / {_SECOND}, disc 1: files 2, Music.app tracks 3\n"
            f"  {_BAND} / {_ALBUM}, disc 1: files 2, Music.app tracks 3\n"
            f"  {lib}/{_BAND}/{_ALBUM} (by folder): files 1, Music.app tracks 0\n"
            "unreadable tags: 1\n"
            f"  {self.bonus}\n"
            "unreadable files and folders: 0\n"
            "iCloud placeholders: 0\n"
            "Music.app size differs from the file: 0\n"
            "unchecked tracks: 0\n"
            "decode check not run (--decode)\n"
            "the sync checks see this Mac only: Music.app cannot see an iPhone, so a track"
            " the phone lists but cannot play is not found here\n"
            "summary: findings 10; audio files 5, Music.app tracks 9;"
            " cloud-only 1, outside --library 1, unparsed rows 0, sizes unknown 0\n",
        )

    def test_without_mutagen_the_counts_go_by_folder_gone_tracks_included(
        self,
    ) -> None:
        result = self.audit(self.music, tag_reader=None)
        self.assertEqual(result.code, af.FINDINGS)
        lines = result.stdout.splitlines()
        self.assertIn("tag checks skipped: mutagen not installed", lines)
        self.assertNotIn("unreadable tags: 0", lines)
        self.assertFalse(any(line.startswith("track-number gaps") for line in lines))
        self.assertFalse(
            any(line.startswith("files with no track n") for line in lines)
        )
        self.assertIn("files with no Music.app track: 1", lines)
        # The first album's gone track counts toward its folder, so its 3 files and
        # 2 matched tracks plus 1 gone agree; the trio's doubled track does not.
        self.assertIn("files and Music.app tracks differ: 1", lines)
        self.assertIn(
            f"  {self.library}/{_TRIO}/{_SECOND} (by folder): files 2, Music.app tracks 3",
            lines,
        )
        self.assertTrue(lines[-1].startswith("summary: findings 4;"), lines[-1])

    def test_the_json_report_holds_every_finding(self) -> None:
        result = self.audit(self.music, "--format", "json", tag_reader=self.tags)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], 4)
        self.assertEqual(
            report["file_gone"][0],
            {
                "persistent_id": af.pid(4),
                "cloud_status": "removed",
                "artist": _TRIO,
                "album": "Lost Album",
                "disc": 1,
                "track": 5,
                "location": "",
            },
        )
        self.assertEqual(
            report["track_gaps"],
            [
                {
                    "artist": _BAND,
                    "album": _ALBUM,
                    "disc": 1,
                    "missing": [2],
                    "files": 2,
                    "track_count": 3,
                }
            ],
        )
        self.assertEqual(report["no_track_number"], [str(self.untitled)])
        self.assertEqual(
            report["count_differs"][0],
            {
                "grouped_by": "tags",
                "artist": _TRIO,
                "album": "Lost Album",
                "disc": 1,
                "folder": None,
                "files": 0,
                "tracks": 1,
            },
        )
        self.assertEqual(
            report["count_differs"][-1],
            {
                "grouped_by": "folder",
                "artist": None,
                "album": None,
                "disc": None,
                "folder": str(self.library / _BAND / _ALBUM),
                "files": 1,
                "tracks": 0,
            },
        )
        self.assertEqual(
            (report["cloud_only"], report["outside_library"], report["unparsed_rows"]),
            (1, 1, 0),
        )
        self.assertEqual((report["audio_files"], report["music_tracks"]), (5, 9))
        self.assertEqual(report["unreadable_paths"], [])
        self.assertEqual(report["findings"], 10)

    def test_json_marks_the_no_track_number_list_null_without_mutagen(self) -> None:
        result = self.audit(self.music, "--format", "json", tag_reader=None)
        self.assertIsNone(json.loads(result.stdout)["no_track_number"])


class AlbumGroupTest(af.AuditCase):
    """Album grouping end to end: an album is its tags, wherever its files are filed."""

    def test_an_album_split_across_artist_folders_is_clean(self) -> None:
        one = self.touch("library/One Artist/Shared Album/01 a.mp3")
        two = self.touch("library/Other Artist/Shared Album/02 b.mp3")
        music = af.FakeMusic(
            tracks=[
                af.Track(1, str(one), track=1, album="Shared Album", artist=_VARIOUS),
                af.Track(2, str(two), track=2, album="Shared Album", artist=_VARIOUS),
            ]
        )
        tags = af.tag_table(
            {
                one: af.tagged(1, 2, album="Shared Album", artist=_VARIOUS),
                two: af.tagged(2, 2, album="Shared Album", artist=_VARIOUS),
            }
        )
        result = self.audit(music, tag_reader=tags)
        self.assertEqual(result.code, af.OK, result.stdout)

    def test_names_match_whatever_their_case_and_ends(self) -> None:
        (path,) = self.album("Band/Album", "01 a.mp3")
        music = af.FakeMusic(tracks=[af.Track(1, str(path), album="INVENTED ALBUM ")])
        result = self.audit(music, tag_reader=af.tag_table({path: af.tagged(1, 1)}))
        self.assertEqual(result.code, af.OK, result.stdout)

    def test_a_file_retagged_since_import_counts_toward_its_own_tags(self) -> None:
        # The tags now say album B while Music.app still lists A: one item, one group.
        (path,) = self.album("Band/Album", "01 a.mp3")
        music = af.FakeMusic(tracks=[af.Track(1, str(path), album="Album A")])
        tags = af.tag_table({path: af.tagged(1, 1, album="Album B")})
        result = self.audit(music, tag_reader=tags)
        self.assertEqual(result.code, af.OK, result.stdout)

    def test_a_compilation_of_many_artists_is_one_album(self) -> None:
        artists = ("First Placeholder", "Second Placeholder", "Third Placeholder")
        paths = self.album(
            "Compilations/Placeholder Hits", "01 a.mp3", "02 b.mp3", "03 c.mp3"
        )
        music = af.FakeMusic(
            tracks=[
                af.Track(
                    n,
                    str(path),
                    album="Placeholder Hits",
                    artist=artist,
                    track=n,
                    compilation=True,
                )
                for n, (path, artist) in enumerate(zip(paths, artists), start=1)
            ]
        )
        tags = af.tag_table(
            {
                path: af.tagged(
                    n, 3, album="Placeholder Hits", artist=artist, compilation=True
                )
                for n, (path, artist) in enumerate(zip(paths, artists), start=1)
            }
        )
        result = self.audit(music, tag_reader=tags)
        self.assertEqual(result.code, af.OK, result.stdout)

    def test_a_gone_track_outside_the_library_makes_no_count_difference(
        self,
    ) -> None:
        (path,) = self.album("Band/Album", "01 a.mp3")
        elsewhere = self.root / "elsewhere" / "Band" / "Album" / "02 b.mp3"
        music = af.FakeMusic(
            tracks=[af.Track(1, str(path)), af.Track(2, str(elsewhere), track=2)]
        )
        result = self.audit(music, tag_reader=af.tag_table({path: af.tagged(1, 2)}))
        lines = result.stdout.splitlines()
        # Still listed as gone (check 2), but never counted against the library.
        self.assertIn("Music.app tracks whose file is gone: 1", lines)
        self.assertIn("files and Music.app tracks differ: 0", lines)

    def test_a_gone_track_beside_unreadable_files_counts_toward_their_folder(
        self,
    ) -> None:
        kept = self.album("Band/Album", "01 a.mp3")[0]
        gone = kept.parent / "02 b.mp3"
        music = af.FakeMusic(tracks=[af.Track(1, str(kept)), af.Track(2, str(gone))])
        result = self.audit(music, tag_reader=af.tag_table({}))
        lines = result.stdout.splitlines()
        self.assertIn(
            f"  {kept.parent} (by folder): files 1, Music.app tracks 2", lines
        )
        self.assertIn("files and Music.app tracks differ: 1", lines)


class ShownTextTest(af.AuditCase):
    """A name this tool did not write cannot split a line or drive the terminal."""

    def test_control_characters_in_a_name_are_escaped(self) -> None:
        music = af.FakeMusic(tracks=[af.Track(1, "", album="Bad\x1b[2JName")])
        result = self.audit(music, tag_reader=af.tag_table({}))
        self.assertIn("Bad\\x1b[2JName", result.stdout)
        self.assertNotIn("\x1b", result.stdout)

    def test_a_gap_with_no_count_tag_says_so(self) -> None:
        files = self.album("Band/Album", "01 a.mp3", "03 c.mp3")
        tracks = [af.Track(n + 1, str(p)) for n, p in enumerate(files)]
        tags = af.tag_table({files[0]: af.tagged(1), files[1]: af.tagged(3)})
        result = self.audit(af.FakeMusic(tracks=tracks), tag_reader=tags)
        self.assertIn(
            f"  {_BAND} / {_ALBUM}, disc 1: missing 2 (files 2, no track-count tag)\n",
            result.stdout,
        )

    def test_an_unreadable_folder_is_listed_with_its_reason(self) -> None:
        def _walk(
            top: str, on_error: af.audit_walk.OnError
        ) -> af.audit_walk.WalkResult:
            on_error(PermissionError(13, "Permission denied", f"{top}/Locked"))
            yield from ()

        seams = af.wiring(af.FakeMusic(), tag_reader=af.tag_table({}))
        seams = dataclasses.replace(seams, walk=_walk)
        result = af.run_main(["--library", str(self.library)], seams)
        self.assertEqual(result.code, af.FINDINGS)
        self.assertIn(
            f"unreadable files and folders: 1\n  {self.library}/Locked: Permission denied\n",
            result.stdout,
        )


if __name__ == "__main__":
    unittest.main()
