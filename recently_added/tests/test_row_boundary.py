"""Where one Music.app row ends, and what a row is allowed to claim.

Moved from `test_recently_added.py`, which runs this suite through its `load_tests`
hook. Every test drives a fake `run`: nothing here spawns a real `osascript` process or
touches Music.app.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import recently_added  # noqa: E402 - import follows the sys.path bootstrap above
from recently_added import (  # noqa: E402 - import follows the sys.path bootstrap above
    AlbumRef,
    newest_albums_from_music,
)


def _completed(returncode: int, stdout: str) -> subprocess.CompletedProcess[str]:
    """Build a fake `osascript` result without spawning a real process."""
    return subprocess.CompletedProcess(
        args=["osascript"], returncode=returncode, stdout=stdout, stderr=""
    )


#: The reference day every test below injects. Fixed, and deliberately far from any
#: date these tests will ever run on: a row's distance from "today" is then a property
#: of the test, and a call site that quietly read the real clock instead of the
#: injected day would keep a row dated two days past this one (twenty-odd years in
#: its past) and fail here, rather than agreeing with the injection by coincidence.
_TODAY = dt.date(2000, 6, 15)


def _rows(*lines: str) -> recently_added.Runner:
    """A fake `run` whose Music.app answers with exactly these rows, one per line."""

    def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        return _completed(0, "".join(f"{line}\n" for line in lines))

    return run


class RowBoundaryTest(unittest.TestCase):
    """Where one Music.app row ends and what a row is allowed to claim.

    The AppleScript joins each track's date, album artist and album with `tab` and
    ends the row with `linefeed`. It escapes the names, so a tag's own line break no
    longer ends a row (`test_escaped_rows.py`); these tests feed raw rows, a reply the
    script did not write, and hold the parser's own refusals, which stay as defense in
    depth: whatever followed a raw line break would read as a row of its own, one
    whose every field, the date included, its author chose.
    """

    def test_a_forged_future_dated_row_cannot_outrank_a_genuine_one(self) -> None:
        # An album tag holding a line break, then a date-artist-album triple dated
        # far in the future: read as a row, it ranked newest forever, ahead of every
        # real addition. The genuine newest row must win, and the forged row must be
        # absent at any count, not merely ranked lower.
        run = _rows(
            "2000-06-01T10:00:00\tThe Invented Quartet\tPlaceholder Album",
            "2000-05-01T10:00:00\tArtist A\tAn Album\n"
            "9999-12-31T23:59:59\tForged Artist\tForged Album",
        )
        refs = newest_albums_from_music(5, run=run, today=_TODAY)
        self.assertEqual(refs[0].album, "Placeholder Album")
        self.assertNotIn("Forged Artist", [ref.artist for ref in refs])

    def test_a_forged_row_in_another_iso_shape_cannot_outrank_a_genuine_one(
        self,
    ) -> None:
        # `fromisoformat` reads far more than the one shape `«class isot» as string`
        # emits. A check that parses a row only to bound it, then ranks the raw
        # string, lets another shape pass the bound and sort wherever its characters
        # land: `'0'` and `'W'` both sort above `'-'`, and a separator other than `T`
        # leaves the digits in place. Each row below parses inside the future bound
        # and sorts above the genuine one, so each took the newest slot. That is
        # the bypass the future-date fix alone does not close, its own test planting
        # only the `9999-` shape.
        for forged in (
            "20000101T000000",  # the basic form, no separators
            "2000-W20-1T00:00:00",  # an ISO week date
            "2000-06-16X00:00:00",  # any single character where the `T` goes
        ):
            with self.subTest(forged=forged):
                run = _rows(
                    "2000-06-14T10:00:00\tThe Invented Quartet\tPlaceholder Album",
                    f"{forged}\tForged Artist\tForged Album",
                )
                refs = newest_albums_from_music(5, run=run, today=_TODAY)
                self.assertEqual(refs[0].album, "Placeholder Album")
                self.assertNotIn("Forged Artist", [ref.artist for ref in refs])

    def test_a_row_shaped_like_a_date_but_holding_impossible_numbers_is_skipped(
        self,
    ) -> None:
        # The shape check passes a row the parser still refuses, so both refusals
        # have to hold: this row is all digits in all the right places and names a
        # thirteenth month.
        run = _rows(
            "2000-13-45T99:99:99\tArtist A\tImpossible",
            "2000-06-01T10:00:00\tThe Invented Quartet\tPlaceholder Album",
        )
        refs = newest_albums_from_music(2, run=run, today=_TODAY)
        self.assertEqual([ref.album for ref in refs], ["Placeholder Album"])

    def test_the_rank_is_keyed_on_the_parsed_date_not_the_raw_stamp(self) -> None:
        # The shape check above makes the two keys agree (every stamp it admits
        # sorts as its own parsed value), so nothing else here can tell them apart,
        # and the parsed key would be deletable at full coverage. It is kept because
        # it is what stops a later loosening of the shape from re-opening the bypass,
        # and that is the guarantee this test pins: with the shape check widened to
        # admit the basic form, a raw-string rank puts the forged row first again
        # while a parsed rank still refuses it the slot.
        loose = re.compile(r"[0-9A-Z:-]+")
        run = _rows(
            "2000-06-14T10:00:00\tThe Invented Quartet\tPlaceholder Album",
            "20000101T000000\tForged Artist\tForged Album",
        )
        with unittest.mock.patch.object(recently_added, "_ISOT_STAMP", loose):
            refs = newest_albums_from_music(5, run=run, today=_TODAY)
        self.assertEqual(refs[0].album, "Placeholder Album")

    def test_a_row_dated_one_day_ahead_is_kept(self) -> None:
        # Music.app's ISO date is local time with no offset, so a track added late
        # in the evening reads as "tomorrow" to a run whose own clock sits in another
        # zone. One day of slack keeps it; it is a real addition, not a forgery.
        run = _rows(
            "2000-06-16T00:30:00\tArtist A\tTomorrow",
            "2000-06-14T10:00:00\tArtist B\tYesterday",
        )
        refs = newest_albums_from_music(2, run=run, today=_TODAY)
        self.assertEqual([ref.album for ref in refs], ["Tomorrow", "Yesterday"])

    def test_a_row_dated_two_days_ahead_is_dropped(self) -> None:
        run = _rows(
            "2000-06-17T00:30:00\tArtist A\tToo Far Ahead",
            "2000-06-14T10:00:00\tArtist B\tYesterday",
        )
        refs = newest_albums_from_music(2, run=run, today=_TODAY)
        self.assertEqual([ref.album for ref in refs], ["Yesterday"])

    def test_a_name_holding_an_exotic_line_separator_survives_whole(self) -> None:
        # `str.splitlines` also breaks a string at a form feed, at the ASCII
        # separator controls, at the C1 NEL and at U+2028/U+2029. A legitimate name
        # holding one was cut there, and its remainder read as a malformed row. Only
        # the linefeed the AppleScript itself emits may end a row.
        for separator in (" ", "", "\x0c", "\x1c"):
            with self.subTest(codepoint=hex(ord(separator))):
                album = f"Side{separator}Two"
                run = _rows(f"2000-06-01T10:00:00\tArtist A\t{album}")
                refs = newest_albums_from_music(1, run=run, today=_TODAY)
                self.assertEqual([ref.album for ref in refs], [album])

    def test_a_row_carrying_a_nul_is_skipped_while_the_rest_are_kept(self) -> None:
        # No real tag carries a NUL, and a name that does cannot be handed to a
        # subprocess at all: the per-album counts query built from it would be
        # refused before it ran. Skipping the row here keeps every other row.
        run = _rows(
            "2000-06-01T10:00:00\tArtist\x00A\tAn Album",
            "2000-05-01T10:00:00\tThe Stand-In Trio\tFiller Songs",
        )
        refs = newest_albums_from_music(2, run=run, today=_TODAY)
        self.assertEqual(
            refs,
            [
                AlbumRef(
                    artist="The Stand-In Trio",
                    album="Filler Songs",
                    added=dt.date(2000, 5, 1),
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
