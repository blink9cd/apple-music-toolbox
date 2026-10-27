"""The names asked of Music for each album folder, and the whole library's batches.

Every album name and path here is invented; no test touches a file.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import refresh_core as rc  # noqa: E402 - import follows the sys.path bootstrap above

#: An invented library about the size of the one the batch size was measured on: a
#: round figure, never a real library's count.
_LIBRARY_LIKE_MEASURED = 21000
#: How many 500-track batches cover it.
_BATCHES_FOR_IT = 42


def _mp3(path: str, device: int, inode: int) -> rc.Mp3:
    """Return a named MP3 with this device and inode."""
    return rc.Mp3(Path(path), (device, inode))


def _tags(table: dict[str, str | None]) -> rc.TagReader:
    """Return a tag reader answering from ``table`` by file name."""

    def _read(path: Path) -> str | None:
        return table[path.name]

    return _read


class GroupAlbumsTest(unittest.TestCase):
    """group_albums: one group per folder, and the names to ask Music for."""

    def test_files_are_grouped_by_folder_in_first_seen_order(self) -> None:
        one = _mp3("/L/Artist/B/01.mp3", 1, 1)
        two = _mp3("/L/Artist/A/01.mp3", 1, 2)
        three = _mp3("/L/Artist/B/02.mp3", 1, 3)
        groups = rc.group_albums([one, two, three], tag_reader=None)
        self.assertEqual(
            [(group.folder, group.mp3s) for group in groups],
            [
                (Path("/L/Artist/B"), (one, three)),
                (Path("/L/Artist/A"), (two,)),
            ],
        )

    def test_without_a_tag_reader_the_names_are_the_folders(self) -> None:
        disc = _mp3("/L/Artist/Album/Disc 1/01.mp3", 1, 1)
        (group,) = rc.group_albums([disc], tag_reader=None)
        self.assertEqual(group.names, ("Disc 1", "Album"))

    def test_the_album_tag_is_added_once_and_empty_names_dropped(self) -> None:
        one = _mp3("/L/Artist/Album/01.mp3", 1, 1)
        two = _mp3("/L/Artist/Album/02.mp3", 1, 2)
        three = _mp3("/L/Artist/Album/03.mp3", 1, 3)
        four = _mp3("/L/Artist/Album/04.mp3", 1, 4)
        reader = _tags(
            {"01.mp3": "Tagged", "02.mp3": "Tagged", "03.mp3": "", "04.mp3": "Album"}
        )
        (group,) = rc.group_albums([one, two, three, four], tag_reader=reader)
        self.assertEqual(group.names, ("Album", "Artist", "Tagged"))

    def test_a_tag_that_cannot_be_read_adds_no_name(self) -> None:
        one = _mp3("/L/Artist/Album/01.mp3", 1, 1)
        (group,) = rc.group_albums([one], tag_reader=_tags({"01.mp3": None}))
        self.assertEqual(group.names, ("Album", "Artist"))

    def test_a_tag_holding_a_nul_adds_no_name(self) -> None:
        # mutagen joins several album values with a NUL, which no argv can carry.
        one = _mp3("/L/Artist/Album/01.mp3", 1, 1)
        reader = _tags({"01.mp3": "First\x00Second"})
        (group,) = rc.group_albums([one], tag_reader=reader)
        self.assertEqual(group.names, ("Album", "Artist"))

    def test_a_file_at_the_root_names_nothing_empty(self) -> None:
        loose = _mp3("/01.mp3", 1, 1)
        (group,) = rc.group_albums([loose], tag_reader=None)
        self.assertEqual(group.names, ())

    def test_no_files_make_no_groups(self) -> None:
        self.assertEqual(rc.group_albums([], tag_reader=None), ())


class BatchRangesTest(unittest.TestCase):
    """batch_ranges: 1-based inclusive ranges of BATCH_TRACKS covering every track."""

    def test_the_batch_is_the_measured_size(self) -> None:
        self.assertEqual(rc.BATCH_TRACKS, 500)

    def test_the_named_counts(self) -> None:
        cases = {
            0: (),
            1: ((1, 1),),
            500: ((1, 500),),
            501: ((1, 500), (501, 501)),
        }
        for total, expected in cases.items():
            with self.subTest(total=total):
                self.assertEqual(rc.batch_ranges(total), expected)

    def test_a_library_the_measured_size_is_covered_once_in_order(self) -> None:
        ranges = rc.batch_ranges(_LIBRARY_LIKE_MEASURED)
        self.assertEqual(len(ranges), _BATCHES_FOR_IT)
        self.assertEqual(ranges[0], (1, 500))
        self.assertEqual(ranges[-1], (20501, _LIBRARY_LIKE_MEASURED))
        covered = [index for first, last in ranges for index in range(first, last + 1)]
        self.assertEqual(covered, list(range(1, _LIBRARY_LIKE_MEASURED + 1)))

    def test_another_size_can_be_asked_for(self) -> None:
        self.assertEqual(rc.batch_ranges(5, size=2), ((1, 2), (3, 4), (5, 5)))

    def test_a_negative_total_or_a_size_below_one_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            rc.batch_ranges(-1)
        with self.assertRaises(ValueError):
            rc.batch_ranges(1, size=0)
