"""audit_rows: the listing's reply parsed strictly, a bad row counted and never raised.

Pure: every input is a string built here. The property tests hold the parser to its
two promises over any text at all: every row it returns has the shape `is_track_row`
names, and it never returns more rows than the text has lines.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import _library_audit_fuzz_profile  # noqa: E402, F401 - loads the deterministic profile before any @given
import audit_rows as ar  # noqa: E402 - import follows the sys.path bootstrap above

_PID = "0123456789ABCDEF"
#: What the listing script writes for each character it escapes in a name or path.
_ESCAPED = {char: f"%{ord(char):02X}" for char in "%\x1f\t\n\r"}
#: Text rich in what the row shape and the escape turn on, mixed with any character.
_RICH_TEXT = st.text(
    alphabet=st.sampled_from("%\t\n\r\x1f0129ADF/\u0301") | st.characters()
)


def _escaped(text: str) -> str:
    """*text* with each character the listing script escapes replaced by its escape."""
    return "".join(_ESCAPED.get(char, char) for char in text)


def _row(**fields: str) -> str:
    """One listing row with every field invented, any of them replaced by *fields*."""
    values = {
        "pid": _PID,
        "status": "matched",
        "disc": "1",
        "track": "2",
        "path": "/L/Band/Album/02 b.mp3",
        "album": "Invented Album",
        "artist": "The Placeholder Band",
        "compilation": "false",
        "kind": "file track",
        "enabled": "true",
        "size": "4096",
    }
    values.update(fields)
    return "\t".join(values.values()) + "\n"


class ParseTrackRowsTest(unittest.TestCase):
    """Well-formed rows in, rows out; anything else counted."""

    def test_a_well_formed_row_is_read_field_by_field(self) -> None:
        parsed = ar.parse_track_rows(_row() + "\n")
        self.assertEqual(
            parsed,
            ar.ParsedTracks(
                (
                    ar.TrackRow(
                        _PID,
                        "matched",
                        1,
                        2,
                        "/L/Band/Album/02 b.mp3",
                        "Invented Album",
                        "The Placeholder Band",
                        False,
                        "file track",
                        True,
                        4096,
                    ),
                ),
                0,
            ),
        )

    def test_the_compilation_flag_is_read(self) -> None:
        parsed = ar.parse_track_rows(_row(compilation="true") + _row())
        self.assertEqual([r.compilation for r in parsed.rows], [True, False])

    def test_the_track_class_is_read(self) -> None:
        parsed = ar.parse_track_rows(_row(kind="shared track", path="") + _row())
        self.assertEqual(
            [r.track_class for r in parsed.rows], ["shared track", "file track"]
        )

    def test_the_enabled_flag_is_read(self) -> None:
        parsed = ar.parse_track_rows(_row(enabled="false") + _row())
        self.assertEqual([r.enabled for r in parsed.rows], [False, True])

    def test_a_size_past_applescript_s_largest_integer_is_read_exactly(self) -> None:
        # 536,870,911 is the largest AppleScript integer; the script writes a larger
        # size as plain digits, and the parser must keep every one of them.
        parsed = ar.parse_track_rows(_row(size="600000123") + _row(size="0"))
        self.assertEqual([r.size for r in parsed.rows], [600_000_123, 0])

    def test_a_size_that_is_not_an_exact_integer_is_unknown(self) -> None:
        # Still a row: the track is placed, and only its size is unknown.
        for size in ("6.0E+8", "600000123.0", "", "-1", "1" * 16, "\u0661"):
            with self.subTest(size=size):
                parsed = ar.parse_track_rows(_row(size=size))
                self.assertEqual(parsed.unparsed, 0)
                self.assertIsNone(parsed.rows[0].size)

    def test_a_track_with_no_location_has_an_empty_path(self) -> None:
        parsed = ar.parse_track_rows(_row(path="", status="purchased"))
        self.assertEqual(parsed.rows[0].path, "")
        self.assertEqual(parsed.unparsed, 0)

    def test_empty_names_and_a_zero_disc_or_track_are_kept(self) -> None:
        parsed = ar.parse_track_rows(_row(album="", artist="", disc="0", track="0"))
        self.assertEqual(
            (parsed.rows[0].album, parsed.rows[0].disc, parsed.rows[0].track),
            ("", 0, 0),
        )

    def test_rows_in_no_shape_of_the_listing_are_counted(self) -> None:
        malformed = [
            _row(pid="0123"),  # a short persistent ID
            _row(disc="one"),  # not a number
            _row(track="1" * 10),  # past any track number
            _row(path="relative/a.mp3"),  # not absolute
            _row(path="/L/a\r.mp3"),  # a carriage return
            _row(path="/L/a\x00.mp3"),  # a NUL
            _row(path="/L/a\tb.mp3"),  # a tab in the path: twelve fields
            _row(compilation="yes"),  # a flag that is neither true nor false
            _row(compilation=""),  # no flag
            _row(kind=""),  # no class
            _row(enabled="yes"),  # an enabled flag that is neither true nor false
            _row(size="1\r"),  # a carriage return in the size
            _row().rsplit("\t", 1)[0] + "\n",  # ten fields: no size
            _row().rsplit("\t", 2)[0] + "\n",  # nine fields: no enabled flag onward
            _row().rsplit("\t", 3)[0] + "\n",  # eight fields: no class onward
            "\t".join([_PID, "matched", "1"]) + "\n",  # three fields
        ]
        parsed = ar.parse_track_rows("".join(malformed))
        self.assertEqual(parsed, ar.ParsedTracks((), len(malformed)))

    def test_a_last_row_with_no_linefeed_is_counted_as_cut_short(self) -> None:
        parsed = ar.parse_track_rows(_row() + _row().rstrip("\n"))
        self.assertEqual((len(parsed.rows), parsed.unparsed), (1, 1))

    def test_empty_text_holds_nothing(self) -> None:
        self.assertEqual(ar.parse_track_rows(""), ar.ParsedTracks((), 0))

    def test_an_escaped_path_album_and_artist_read_back_exactly(self) -> None:
        parsed = ar.parse_track_rows(
            _row(path="/L/a%0Ab%09c.mp3", album="In%0Dvented%25", artist="Band%1F%2509")
        )
        self.assertEqual(parsed.unparsed, 0)
        row = parsed.rows[0]
        self.assertEqual(
            (row.path, row.album, row.artist),
            ("/L/a\nb\tc.mp3", "In\rvented%", "Band\x1f%09"),
        )

    def test_a_path_holding_a_row_forges_none(self) -> None:
        path = "/L/evil\n" + _row().rstrip("\n")
        parsed = ar.parse_track_rows(_row(path=_escaped(path)))
        self.assertEqual((len(parsed.rows), parsed.unparsed), (1, 0))
        self.assertEqual(parsed.rows[0].path, path)

    @given(_RICH_TEXT)
    def test_fuzz_parse_track_rows(self, text: str) -> None:
        parsed = ar.parse_track_rows(text)
        for row in parsed.rows:
            self.assertTrue(ar.is_track_row(row), row)
        self.assertLessEqual(len(parsed.rows) + parsed.unparsed, text.count("\n") + 1)


#: A field the listing writes raw (the cloud status, the class): no tab, no line break,
#: no carriage return.
_FIELD = st.text(st.characters(exclude_characters="\t\n\r"), max_size=12)
#: A name or path the listing escapes: any text, rich in what the escape turns on.
_ESCAPED_FIELD = st.text(
    alphabet=st.sampled_from("%\t\n\r\x1f0129ADF/\u0301") | st.characters(),
    max_size=12,
)


class RoundTripTest(unittest.TestCase):
    """A row in the listing's shape comes back field for field."""

    @given(
        st.integers(0, 2**64 - 1),
        _FIELD,
        st.integers(0, 10**9 - 1),
        st.integers(0, 10**9 - 1),
        st.one_of(
            st.just(""), _ESCAPED_FIELD.map(lambda t: "/" + t.replace("\x00", ""))
        ),
        _ESCAPED_FIELD,
        _ESCAPED_FIELD,
        st.booleans(),
        _FIELD.filter(bool),
        st.booleans(),
        st.integers(0, 10**15 - 1),
    )
    def test_parse_track_rows_round_trips(
        self,
        number: int,
        status: str,
        disc: int,
        track: int,
        path: str,
        album: str,
        artist: str,
        compilation: bool,
        kind: str,
        enabled: bool,
        size: int,
    ) -> None:
        expected = ar.TrackRow(
            f"{number:016X}",
            status,
            disc,
            track,
            path,
            album,
            artist,
            compilation,
            kind,
            enabled,
            size,
        )
        text = _row(
            pid=expected.persistent_id,
            status=status,
            disc=str(disc),
            track=str(track),
            path=_escaped(path),
            album=_escaped(album),
            artist=_escaped(artist),
            compilation="true" if compilation else "false",
            kind=kind,
            enabled="true" if enabled else "false",
            size=str(size),
        )
        self.assertEqual(ar.parse_track_rows(text), ar.ParsedTracks((expected,), 0))


class IsTrackRowTest(unittest.TestCase):
    """is_track_row: the shape every returned row has."""

    def test_each_broken_field_is_caught(self) -> None:
        good = ar.parse_track_rows(_row()).rows[0]
        self.assertTrue(ar.is_track_row(good))
        for broken in (
            ar.TrackRow("XYZ", "matched", 1, 2, "/a", "", ""),
            ar.TrackRow(_PID, "matched", -1, 2, "/a", "", ""),
            ar.TrackRow(_PID, "matched", 1, -2, "/a", "", ""),
            ar.TrackRow(_PID, "matched", 1, 2, "a", "", ""),
            ar.TrackRow(_PID, "matched", 1, 2, "/a\x00", "", ""),
            ar.TrackRow(_PID, "a\tb", 1, 2, "/a", "", ""),
            ar.TrackRow(_PID, "matched", 1, 2, "/a", "", "", False, ""),
            ar.TrackRow(_PID, "matched", 1, 2, "/a", "", "", False, "a\tb"),
            ar.TrackRow(_PID, "matched", 1, 2, "/a", "", "", False, "x", True, -1),
        ):
            with self.subTest(row=broken):
                self.assertFalse(ar.is_track_row(broken))

    def test_a_decoded_name_or_path_may_hold_a_delimiter(self) -> None:
        # The listing escapes the album, the artist and the path, so each reads back
        # whole, a tab or line break included.
        row = ar.TrackRow(_PID, "matched", 1, 2, "/a\nb\tc\rd", "x\ny", "p\tq")
        self.assertTrue(ar.is_track_row(row))


if __name__ == "__main__":
    unittest.main()
