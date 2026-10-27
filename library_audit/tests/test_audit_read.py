"""audit_read: each walked file's tags, a placeholder's taken from its track's row.

Every file is an `AudioFile` built here and the tag reader a table that fails the test
when handed a placeholder, so nothing opens a file or reaches the host.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import audit_fixtures as af  # noqa: E402 - import follows the sys.path bootstrap above
import audit_read  # noqa: E402 - import follows the sys.path bootstrap above
import audit_rows as ar  # noqa: E402 - import follows the sys.path bootstrap above
import audit_tags  # noqa: E402 - import follows the sys.path bootstrap above
import audit_walk as aw  # noqa: E402 - import follows the sys.path bootstrap above

_LIB = Path("/invented/library")


def _row(number: int, *, disc: int = 1, track: int = 1) -> ar.TrackRow:
    """An invented listing row, a compilation."""
    return ar.TrackRow(
        af.pid(number), "local only", disc, track, "", af.ALBUM, af.BAND, True
    )


def _reader(table: dict[Path, audit_tags.FileTags]) -> audit_tags.TagReader:
    """A reader answering from *table*; handed a placeholder, it fails the test."""

    def _read(path: Path) -> audit_tags.FileTags | None:
        if path.name.startswith("away"):
            raise AssertionError(f"opened a placeholder: {path}")
        return table.get(path)

    return _read


class RowTagsTest(unittest.TestCase):
    """What a listed track says its file's tags are."""

    def test_the_row_s_fields_with_no_track_count(self) -> None:
        self.assertEqual(
            audit_read.row_tags(_row(1, disc=2, track=5)),
            audit_tags.FileTags(af.BAND, af.ALBUM, 2, 5, None, True),
        )

    def test_disc_and_track_zero_read_as_a_file_s_absent_tags_do(self) -> None:
        tags = audit_read.row_tags(_row(1, disc=0, track=0))
        self.assertEqual((tags.disc, tags.track), (1, None))

    def test_a_number_past_four_digits_reads_as_none_as_a_file_s_does(self) -> None:
        # Regression: a row's track 100000 reached the gap check, which enumerated
        # every number up to it; the file path has always dropped such a number.
        tags = audit_read.row_tags(_row(1, disc=100000, track=100000))
        self.assertEqual((tags.disc, tags.track), (1, None))

    def test_a_four_digit_number_is_kept(self) -> None:
        tags = audit_read.row_tags(_row(1, disc=9999, track=9999))
        self.assertEqual((tags.disc, tags.track), (9999, 9999))


class ReadLibraryTagsTest(unittest.TestCase):
    """Files read by the reader, placeholders by their track or not at all."""

    def test_each_kind_of_file(self) -> None:
        good, bad = _LIB / "a.mp3", _LIB / "b.mp3"
        files = [
            aw.AudioFile(good, (1, 1)),
            aw.AudioFile(bad, (1, 2)),
            aw.AudioFile(_LIB / "away1.mp3", (1, 3), dataless=True),
            aw.AudioFile(_LIB / "away2.mp3", (1, 4), dataless=True),
        ]
        read = audit_read.read_library_tags(
            files,
            _reader({good: af.tagged(1)}),
            {(1, 3): (_row(3, track=0), _row(9, track=7))},
        )
        self.assertEqual(
            read.tags,
            {
                good: af.tagged(1),
                _LIB / "away1.mp3": audit_read.row_tags(_row(3, track=0)),
            },
        )
        self.assertEqual(read.unreadable, (bad,))
        self.assertEqual(read.no_track_number, (_LIB / "away1.mp3",))


if __name__ == "__main__":
    unittest.main()
