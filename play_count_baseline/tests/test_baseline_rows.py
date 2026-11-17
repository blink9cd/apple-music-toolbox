"""baseline_rows: the play-count listing parsed strictly, a bad row counted and never raised.

Pure: every input is a string built here. The property test holds the parser to its
two promises over any text at all: it never raises, and it never accounts for more
rows than the text has segments.
"""

from __future__ import annotations

import sys
import unittest
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import _play_count_baseline_fuzz_profile  # noqa: E402, F401 - loads the deterministic profile before any @given
import baseline_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import baseline_rows as br  # noqa: E402 - import follows the sys.path bootstrap above

#: Text rich in what the escape and the row shape turn on: every escaped character, the
#: digits and letters an escape's code is spelled with, a path's slash and a combining
#: mark, mixed with any character at all.
_RICH_TEXT = st.text(
    alphabet=st.sampled_from("%\t\n\r\x1f0129ADF/\u0301") | st.characters()
)
#: Every field of one well-formed row, invented, in the listing's order.
_FIELDS = {
    "pid": "0123456789abcdef",
    "name": "Invented Song",
    "artist": "The Placeholder Band",
    "album": "Invented Album",
    "album_artist": "",
    "disc": "2",
    "duration": "215000",
    "count": "7",
    "date": "2024/3/9/45296",
    "genre": "Invented Genre",
    "year": "2001",
    "path": "/Invented/Library/Invented Song.m4a",
}
_EXPECTED = br.RawTrack(
    persistent_id="0123456789abcdef",
    name="Invented Song",
    artist="The Placeholder Band",
    album="Invented Album",
    album_artist="",
    disc_number=2,
    duration_ms=215000,
    played_count=7,
    played_date="2024/3/9/45296",
    genre="Invented Genre",
    year=2001,
    path="/Invented/Library/Invented Song.m4a",
)


def _row(**fields: str) -> str:
    """One listing row with every field invented, any of them replaced by *fields*."""
    values = dict(_FIELDS)
    values.update(fields)
    return "\t".join(values.values()) + "\n"


class ParsePlayRowsTest(unittest.TestCase):
    """`parse_play_rows` returns each well-formed row and counts the rest."""

    def test_the_field_count_is_the_row_s(self) -> None:
        self.assertEqual(br.FIELD_COUNT, len(_FIELDS))

    def test_a_well_formed_row_parses_to_the_exact_track(self) -> None:
        parsed = br.parse_play_rows(_row() + "\n")
        self.assertEqual(parsed, br.ParsedRows((_EXPECTED,), 0))

    def test_empty_duration_and_date_give_none_and_empty(self) -> None:
        (track,) = br.parse_play_rows(_row(duration="", date="")).rows
        self.assertIsNone(track.duration_ms)
        self.assertEqual(track.played_date, "")

    def test_empty_text_fields_and_no_file_parse(self) -> None:
        (track,) = br.parse_play_rows(
            _row(album="", genre="", path="", disc="0", year="0")
        ).rows
        self.assertEqual((track.album, track.genre, track.path), ("", "", ""))
        self.assertEqual((track.disc_number, track.year), (0, 0))

    def test_a_row_short_or_long_one_field_is_counted(self) -> None:
        short = "\t".join(list(_FIELDS.values())[:-1]) + "\n"
        long = "\t".join([*_FIELDS.values(), "extra"]) + "\n"
        self.assertEqual(br.parse_play_rows(short + long), br.ParsedRows((), 2))

    def test_a_non_hex_persistent_id_is_counted(self) -> None:
        for bad in ("0123456789ABCDEG", "0123456789ABCDE", "0123456789ABCDEF0"):
            self.assertEqual(
                br.parse_play_rows(_row(pid=bad)), br.ParsedRows((), 1), bad
            )

    def test_a_non_decimal_number_is_counted(self) -> None:
        for field in ("count", "disc", "year", "duration"):
            for bad in ("x", "-1", "1.5", "١", "1234567890"):
                parsed = br.parse_play_rows(_row(**{field: bad}))
                self.assertEqual(parsed, br.ParsedRows((), 1), (field, bad))

    def test_an_empty_count_disc_or_year_is_counted(self) -> None:
        for field in ("count", "disc", "year"):
            self.assertEqual(br.parse_play_rows(_row(**{field: ""})).unparsed, 1, field)

    def test_a_malformed_date_is_counted(self) -> None:
        for bad in ("2024/3/9", "2024-03-09", "Saturday, 9 March 2024", "2024/3/9/x"):
            self.assertEqual(br.parse_play_rows(_row(date=bad)).unparsed, 1, bad)

    def test_a_relative_path_or_a_carriage_return_is_counted(self) -> None:
        for fields in ({"path": "relative/song.m4a"}, {"name": "Invented\rSong"}):
            self.assertEqual(br.parse_play_rows(_row(**fields)).unparsed, 1, fields)

    def test_a_good_row_beside_a_bad_one_still_parses(self) -> None:
        parsed = br.parse_play_rows(_row(count="x") + _row() + "\n")
        self.assertEqual(parsed, br.ParsedRows((_EXPECTED,), 1))

    def test_the_trailing_linefeed_and_an_empty_reply_give_zero_rows(self) -> None:
        for reply in ("", "\n", "\n\n"):
            self.assertEqual(
                br.parse_play_rows(reply), br.ParsedRows((), 0), repr(reply)
            )

    def test_a_final_row_cut_short_is_counted(self) -> None:
        parsed = br.parse_play_rows(_row() + _row().rstrip("\n"))
        self.assertEqual(parsed, br.ParsedRows((_EXPECTED,), 1))

    @given(_RICH_TEXT)
    def test_fuzz_parse_play_rows(self, text: str) -> None:
        parsed = br.parse_play_rows(text)
        self.assertLessEqual(len(parsed.rows) + parsed.unparsed, text.count("\n") + 1)
        for track in parsed.rows:
            self.assertGreaterEqual(track.played_count, 0)
            self.assertTrue(track.path == "" or track.path.startswith("/"))


#: Every character the script escapes, the pair Windows text ends lines with, an
#: escape's own text left as plain text, and a sign followed by an unknown code.
_AWKWARD = ("\t", "\n", "\r", "\r\n", "\x1f", "%", "%09", "%25", "%41", "100%")
#: The text fields the script escapes, each with the invented track holding a value there.
_TEXT_FIELDS: dict[str, Callable[[str], br.RawTrack]] = {
    "name": lambda value: replace(fx.INVENTED_TRACK, name=value),
    "artist": lambda value: replace(fx.INVENTED_TRACK, artist=value),
    "album": lambda value: replace(fx.INVENTED_TRACK, album=value),
    "album_artist": lambda value: replace(fx.INVENTED_TRACK, album_artist=value),
    "genre": lambda value: replace(fx.INVENTED_TRACK, genre=value),
}
#: A path an awkward character is placed in the middle of.
_PATH = "/Invented/Library/Invented{}Song.m4a"


class EscapedFieldsTest(unittest.TestCase):
    """A text field or path holding a delimiter, or the escape sign, reads back exactly."""

    def test_each_awkward_character_reads_back_in_each_text_field(self) -> None:
        for field, track_with in _TEXT_FIELDS.items():
            for awkward in _AWKWARD:
                track = track_with(f"Invented{awkward}Song")
                with self.subTest(field=field, awkward=awkward):
                    parsed = br.parse_play_rows(fx.row_of(track) + "\n")
                    self.assertEqual(parsed, br.ParsedRows((track,), 0))

    def test_each_awkward_character_reads_back_in_a_path(self) -> None:
        for awkward in _AWKWARD:
            track = replace(fx.INVENTED_TRACK, path=_PATH.format(awkward))
            with self.subTest(awkward=awkward):
                parsed = br.parse_play_rows(fx.row_of(track) + "\n")
                self.assertEqual(parsed, br.ParsedRows((track,), 0))

    @given(_RICH_TEXT, _RICH_TEXT, _RICH_TEXT.filter(lambda path: "\x00" not in path))
    def test_any_text_and_path_read_back(
        self, name: str, artist: str, path: str
    ) -> None:
        track = replace(fx.INVENTED_TRACK, name=name, artist=artist, path="/" + path)
        parsed = br.parse_play_rows(fx.row_of(track) + "\n")
        self.assertEqual(parsed, br.ParsedRows((track,), 0))


if __name__ == "__main__":
    unittest.main()
