"""audit_checks: track-number gaps per album group, and files against tracks per group.

Pure: the inputs are paths, tags and groups built here, and nothing is read from disk.
An album group is the files' album artist (else artist), album and disc tags, so
a lone single sitting in a folder of its own, and an album split across
folders, are each judged as the one album they are. Every name and path is invented.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_TOOL = Path(__file__).resolve().parent.parent
# The tool's own src/, and tag_refresh's, whose types the checks are built on.
sys.path[:0] = [str(_TOOL / "src"), str(_TOOL.parent / "tag_refresh" / "src")]

import audit_checks as ac  # noqa: E402 - import follows the sys.path bootstrap above
import audit_groups as ag  # noqa: E402 - import follows the sys.path bootstrap above
import audit_tags as at  # noqa: E402 - import follows the sys.path bootstrap above

_BAND, _ALBUM, _OTHER = "The Placeholder Band", "Invented Album", "Second Album"
_FOLDER = Path("/L/The Placeholder Band/Invented Album")


def _tagged(
    *numbers: tuple[int | None, int | None, int],
    album: str = _ALBUM,
    folder: Path = _FOLDER,
) -> list[tuple[Path, at.FileTags]]:
    """One invented file per ``(track, total, disc)`` of *album*, under *folder*."""
    return [
        (folder / f"{album} {n:02d}.mp3", at.FileTags(_BAND, album, disc, track, total))
        for n, (track, total, disc) in enumerate(numbers)
    ]


def _group(album: str = _ALBUM, disc: int = 1) -> ag.Group:
    """The tag group of *album*'s *disc*."""
    return ag.tag_group(_BAND, album, disc)


def _gaps(tagged: list[tuple[Path, at.FileTags]]) -> tuple[ac.Gap, ...]:
    """The gaps in *tagged*, as the audit finds them: each album's numbers, then holes."""
    return ac.gaps_of(ac.album_numbers(tagged))


class GapsTest(unittest.TestCase):
    """A disc's numbers run 1 to its track count, or 1 to its highest number."""

    def test_a_complete_album_has_no_gap(self) -> None:
        tagged = _tagged((1, 3, 1), (2, 3, 1), (3, 3, 1))
        self.assertEqual(_gaps(tagged), ())

    def test_a_hole_below_the_highest_number_is_a_gap(self) -> None:
        tagged = _tagged((1, None, 1), (4, None, 1))
        self.assertEqual(_gaps(tagged), (ac.Gap(_group(), (2, 3), 2, None),))

    def test_fewer_files_than_the_track_count_tag_is_a_gap(self) -> None:
        # The case the tool exists for: the first and last of an album only.
        tagged = _tagged((1, 12, 1), (12, 12, 1))
        self.assertEqual(_gaps(tagged), (ac.Gap(_group(), tuple(range(2, 12)), 2, 12),))

    def test_a_missing_last_track_is_found_only_through_the_count_tag(self) -> None:
        tagged = _tagged((1, 3, 1), (2, 3, 1))
        self.assertEqual(_gaps(tagged), (ac.Gap(_group(), (3,), 2, 3),))

    def test_duplicate_numbers_with_too_few_distinct_tracks_are_a_gap(self) -> None:
        tagged = _tagged((1, 2, 1), (1, 2, 1))
        self.assertEqual(_gaps(tagged), (ac.Gap(_group(), (2,), 2, 2),))

    def test_more_files_than_the_count_tag_is_no_gap(self) -> None:
        tagged = _tagged((1, 1, 1), (2, 1, 1))
        self.assertEqual(_gaps(tagged), ())

    def test_each_disc_is_judged_alone_in_order(self) -> None:
        tagged = _tagged((2, None, 2), (1, 2, 1), (2, 2, 1), (3, None, 2))
        self.assertEqual(_gaps(tagged), (ac.Gap(_group(disc=2), (1,), 2, None),))

    def test_an_album_split_across_folders_is_one_album(self) -> None:
        # A false gap to avoid: a multi-artist album filed under two folders.
        tagged = [
            *_tagged((1, 2, 1), folder=Path("/L/One Artist/Invented Album")),
            *_tagged((2, 2, 1), folder=Path("/L/Other Artist/Invented Album")),
        ]
        self.assertEqual(_gaps(tagged), ())

    def test_a_lone_single_in_a_shared_folder_is_its_own_album(self) -> None:
        # Another false gap to avoid: a single beside an album in one folder.
        tagged = [*_tagged((1, 2, 1), (2, 2, 1)), *_tagged((1, 1, 1), album=_OTHER)]
        self.assertEqual(_gaps(tagged), ())

    def test_groups_are_reported_in_order_and_files_without_a_number_skipped(
        self,
    ) -> None:
        tagged = [
            *_tagged((2, None, 1), album=_OTHER),
            *_tagged((3, None, 1), (None, None, 1)),
        ]
        self.assertEqual([gap.group.album for gap in _gaps(tagged)], [_ALBUM, _OTHER])
        self.assertEqual(_gaps(tagged)[0].files, 1)

    def test_the_group_shows_the_first_file_s_spelling(self) -> None:
        tagged = [
            (Path("/L/b.mp3"), at.FileTags(_BAND, "INVENTED ALBUM", 1, 3, None)),
            (Path("/L/a.mp3"), at.FileTags(_BAND, "Invented Album ", 1, 1, None)),
        ]
        (gap,) = _gaps(tagged)
        self.assertEqual(gap.group.album, "Invented Album ")
        self.assertEqual(gap.missing, (2,))

    def test_a_pregap_track_starts_the_album_at_zero(self) -> None:
        tagged = _tagged((0, 3, 1), (1, 3, 1), (2, 3, 1))
        self.assertEqual(_gaps(tagged), ())

    def test_a_pregap_album_short_of_its_count_misses_its_last(self) -> None:
        tagged = _tagged((0, 3, 1), (1, 3, 1))
        self.assertEqual(_gaps(tagged), (ac.Gap(_group(), (2,), 2, 3),))

    def test_nothing_numbered_has_no_gap(self) -> None:
        self.assertEqual(_gaps([]), ())


class AlbumNumbersTest(unittest.TestCase):
    """Each numbered group's numbers, what it lacks, and what the gap check makes of it."""

    def test_each_group_holds_its_numbers_and_count_tag(self) -> None:
        tagged = [*_tagged((3, 4, 1), (1, None, 1), (None, None, 1))]
        (album,) = ac.album_numbers(tagged)
        self.assertEqual(album, ac.AlbumNumbers(_group(), frozenset({1, 3}), 2, 4))
        self.assertEqual(album.missing, (2, 4))

    def test_without_a_count_tag_the_highest_number_ends_the_album(self) -> None:
        (album,) = ac.album_numbers(_tagged((1, None, 1), (3, None, 1)))
        self.assertEqual(album.missing, (2,))
        self.assertEqual(ac.missing_numbers([None, 0], [1, 3]), (2,))
        self.assertEqual(ac.missing_numbers([2, None, 5], [1]), (2, 3, 4, 5))

    def test_a_pregap_track_s_count_tag_includes_it(self) -> None:
        # Numbered 0 to total - 1, as MusicBrainz numbers a disc with a pregap track.
        self.assertEqual(ac.missing_numbers([14], range(13)), (13,))
        self.assertEqual(ac.missing_numbers([None], [0, 2]), (1,))

    def test_the_gaps_of_whole_albums_are_none(self) -> None:
        albums = ac.album_numbers(
            [*_tagged((1, 2, 1), (2, 2, 1)), *_tagged((2, None, 2))]
        )
        self.assertEqual(ac.gaps_of(albums), (ac.Gap(_group(disc=2), (1,), 1, None),))


class CompareCountsTest(unittest.TestCase):
    """Per group, the files on one side against Music.app's tracks on the other."""

    def test_equal_counts_are_no_difference(self) -> None:
        self.assertEqual(ac.compare_counts([_group()] * 2, [_group()] * 2), ())

    def test_each_side_alone_is_a_difference(self) -> None:
        self.assertEqual(
            ac.compare_counts([_group()], [_group(_OTHER)]),
            (
                ac.CountDiffers(_group(), 1, 0),
                ac.CountDiffers(_group(_OTHER), 0, 1),
            ),
        )

    def test_tag_groups_come_before_folder_groups(self) -> None:
        folder = ag.folder_group(_FOLDER)
        self.assertEqual(
            ac.compare_counts([folder, _group()], []),
            (ac.CountDiffers(_group(), 1, 0), ac.CountDiffers(folder, 1, 0)),
        )

    def test_the_files_spelling_is_shown_before_music_s(self) -> None:
        files = ag.tag_group(_BAND, "Invented Album", 1)
        music = ag.tag_group(_BAND, "INVENTED album", 1)
        (differs,) = ac.compare_counts([files], [music, music])
        self.assertEqual(differs.group.album, "Invented Album")
        (only_music,) = ac.compare_counts([], [music])
        self.assertEqual(only_music.group.album, "INVENTED album")


class MissingRangesTest(unittest.TestCase):
    """How a gap's numbers are shown: runs collapsed to ``first-last``."""

    def test_runs_and_singles(self) -> None:
        cases = {
            (): "",
            (3,): "3",
            (2, 3): "2-3",
            (2, 3, 4, 7, 9, 10): "2-4, 7, 9-10",
        }
        for numbers, expected in cases.items():
            with self.subTest(numbers=numbers):
                self.assertEqual(ac.missing_ranges(numbers), expected)


if __name__ == "__main__":
    unittest.main()
