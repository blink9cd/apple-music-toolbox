"""phone_listing: afcclient's ``ls -l`` lines parsed strictly, a stray line counted.

Pure: every input is a string built here, in afcclient 1.4.0's own byte layout. The
property test holds the parser to its promise over any text at all: every line comes
back either as an entry or as an unparsed line, never dropped and never split.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import phone_fixtures as pf  # noqa: E402 - import follows the sys.path bootstrap above
import phone_listing as pl  # noqa: E402 - import follows the sys.path bootstrap above


class ParseTest(unittest.TestCase):
    """Each line's type, size and name, exactly as printed."""

    def test_a_file_line(self) -> None:
        line = (
            "-rw-r--r--    1 mobile mobile    4823041 26 Oct 2026 13:01:02 ABCD.mp3\n"
        )
        self.assertEqual(
            pl.parse_listing(line),
            pl.Listing((pl.Entry("-", 4823041, "ABCD.mp3"),), ()),
        )

    def test_every_type_afcclient_prints(self) -> None:
        text = "".join(pf.listing_line(f"n{kind}", 7, kind=kind) for kind in "dl-fbcs")
        kinds = [e.kind for e in pl.parse_listing(text).entries]
        self.assertEqual(kinds, list("dl-fbcs"))

    def test_a_name_with_spaces_is_kept_whole(self) -> None:
        listing = pl.parse_listing(pf.listing_line("a  name with spaces ", 3))
        self.assertEqual(listing.entries[0].name, "a  name with spaces ")

    def test_wide_numbers_overflow_their_padding(self) -> None:
        line = "-rw-r--r-- 12345 mobile mobile 12345678901 01 Jan 2026 00:00:00 BIG\n"
        self.assertEqual(
            pl.parse_listing(line).entries, (pl.Entry("-", 12345678901, "BIG"),)
        )

    def test_color_escapes_around_the_name_are_removed(self) -> None:
        line = pf.listing_line("\x1b[36mF00\x1b[0m", kind="d")
        self.assertEqual(pl.parse_listing(line).entries[0].name, "F00")

    def test_a_line_in_another_shape_is_unparsed_never_dropped(self) -> None:
        odd = [
            "garbage",
            "",
            "-rwxrwxrwx    1 mobile mobile          0 26 Oct 2026 13:01:02 X",
            "-rw-r--r--    1 root mobile          0 26 Oct 2026 13:01:02 X",
            "-rw-r--r--    1 mobile mobile         -1 26 Oct 2026 13:01:02 X",
            "-rw-r--r--    1 mobile mobile          0 26 Oct 2026 13:01:02 ",
        ]
        text = pf.listing_line("GOOD") + "".join(f"{line}\n" for line in odd)
        listing = pl.parse_listing(text)
        self.assertEqual([e.name for e in listing.entries], ["GOOD"])
        self.assertEqual(listing.unparsed, tuple(odd))

    def test_a_failed_stat_line_is_unparsed_never_a_zero_byte_file(self) -> None:
        # afcclient prints a zeroed stat when one entry's stat fails: link count 0.
        zeroed = pf.zeroed_line("GONE.mp3")
        listing = pl.parse_listing(pf.listing_line("GOOD", 5) + zeroed)
        self.assertEqual([e.name for e in listing.entries], ["GOOD"])
        self.assertEqual(listing.unparsed, (zeroed.rstrip("\n"),))

    def test_a_last_line_with_no_linefeed_is_still_read(self) -> None:
        listing = pl.parse_listing(
            pf.listing_line("A") + pf.listing_line("B").rstrip("\n")
        )
        self.assertEqual([e.name for e in listing.entries], ["A", "B"])

    def test_empty_text_holds_nothing(self) -> None:
        self.assertEqual(pl.parse_listing(""), pl.Listing((), ()))

    @given(st.text())
    def test_fuzz_parse_listing(self, text: str) -> None:
        listing = pl.parse_listing(text)
        lines = text.split("\n")
        if lines[-1] == "":
            lines.pop()
        self.assertEqual(len(listing.entries) + len(listing.unparsed), len(lines))
        for entry in listing.entries:
            self.assertTrue(entry.name)
            self.assertNotIn("\n", entry.name)
            self.assertGreaterEqual(entry.size, 0)


#: A name afcclient could list: not empty, and no linefeed or slash. No escape
#: character either, since the parser removes color escapes wherever they appear.
_NAME = st.text(st.characters(exclude_characters="\n/\x1b"), min_size=1)


class RoundTripTest(unittest.TestCase):
    """A line in afcclient's layout comes back field for field."""

    @given(st.sampled_from("dl-fbcs"), st.integers(0, 2**63 - 1), _NAME)
    def test_a_listed_line_round_trips(self, kind: str, size: int, name: str) -> None:
        listing = pl.parse_listing(pf.listing_line(name, size, kind=kind))
        self.assertEqual(listing.entries, (pl.Entry(kind, size, name),))


if __name__ == "__main__":
    unittest.main()
