"""phone_compare: the database's sync rows against the files the phone lists.

Pure: every row and file is invented here.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE.parent / "src")]

import phone_compare as pc  # noqa: E402 - import follows the sys.path bootstrap above


def _row(
    pid: int, folder: str, name: str, size: int | None = 100, **names: str | int
) -> pc.PhoneRow:
    """An invented row; *names* replaces any of its naming fields."""
    fields: dict[str, str | int] = {
        "title": "Invented Title",
        "disc": 1,
        "track": pid,
        "album": "Invented Album",
        "artist": "The Placeholder Band",
    }
    fields.update(names)
    return pc.PhoneRow(
        item_pid=pid,
        folder=folder,
        name=name,
        size=size,
        title=str(fields["title"]),
        disc=int(fields["disc"]),
        track=int(fields["track"]),
        album=str(fields["album"]),
        artist=str(fields["artist"]),
    )


class CompareTest(unittest.TestCase):
    """Rows with no file and sizes that differ are findings; files with no row are listed."""

    def test_a_row_and_its_file_of_the_same_size_agree(self) -> None:
        compared = pc.compare(
            [_row(1, "F00", "AAAA.mp3")], [pc.PhoneFile("F00", "AAAA.mp3", 100)]
        )
        self.assertEqual(compared, pc.Compared((), (), (), 0))

    def test_a_row_with_no_file(self) -> None:
        row = _row(1, "F00", "AAAA.mp3")
        compared = pc.compare([row], [pc.PhoneFile("F01", "AAAA.mp3", 100)])
        self.assertEqual(compared.no_file, (row,))
        self.assertEqual(compared.no_row, (pc.PhoneFile("F01", "AAAA.mp3", 100),))

    def test_a_size_that_differs(self) -> None:
        row = _row(1, "F00", "AAAA.mp3", 100)
        compared = pc.compare([row], [pc.PhoneFile("F00", "AAAA.mp3", 99)])
        self.assertEqual(compared.size_differs, (pc.SizeDiffers(row, 99),))
        self.assertEqual(compared.no_file, ())

    def test_a_row_with_no_known_size_is_not_judged_but_counted(self) -> None:
        row = _row(1, "F00", "AAAA.mp3", None)
        compared = pc.compare([row], [pc.PhoneFile("F00", "AAAA.mp3", 99)])
        self.assertEqual((compared.size_differs, compared.sizes_unknown), ((), 1))

    def test_a_row_with_no_known_size_and_no_file_is_still_a_finding(self) -> None:
        row = _row(1, "F00", "AAAA.mp3", None)
        compared = pc.compare([row], [])
        self.assertEqual((compared.no_file, compared.sizes_unknown), ((row,), 0))

    def test_the_key_is_the_folder_and_the_name_exactly(self) -> None:
        row = _row(1, "F00", "aaaa.mp3")
        compared = pc.compare([row], [pc.PhoneFile("F00", "AAAA.mp3", 100)])
        self.assertEqual(compared.no_file, (row,))

    def test_every_list_is_sorted(self) -> None:
        rows = [
            _row(3, "F00", "C.mp3", artist="Band B"),
            _row(2, "F00", "B.mp3", artist="Band A", disc=2, track=1),
            _row(1, "F00", "A.mp3", artist="Band A", disc=1, track=9),
            _row(4, "F01", "D.mp3", 100, artist="Band A", disc=1, track=1),
            _row(
                5,
                "F01",
                "E.mp3",
                100,
                artist="Band A",
                disc=1,
                track=1,
                title="Earlier",
            ),
        ]
        files = [
            pc.PhoneFile("F02", "Z.mp3", 1),
            pc.PhoneFile("F01", "E.mp3", 5),
            pc.PhoneFile("F01", "D.mp3", 5),
            pc.PhoneFile("F02", "Y.mp3", 1),
        ]
        compared = pc.compare(rows, files)
        self.assertEqual([r.item_pid for r in compared.no_file], [1, 2, 3])
        self.assertEqual([d.row.item_pid for d in compared.size_differs], [5, 4])
        self.assertEqual([f.name for f in compared.no_row], ["Y.mp3", "Z.mp3"])


if __name__ == "__main__":
    unittest.main()
