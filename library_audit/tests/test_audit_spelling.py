"""audit_spelling: the loose fold that pairs split albums, and the note naming a difference.

Pure string functions, so every case is a literal. Every name is invented.
"""

from __future__ import annotations

import sys
import unicodedata
import unittest
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

_TOOL = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_TOOL / "src"), str(_TOOL.parent / "tag_refresh" / "src")]

import audit_spelling as sp  # noqa: E402 - import follows the sys.path bootstrap above

#: Every hyphen and dash lookalike the fold must read as an ASCII hyphen.
_DASHES = (
    "‐",
    "‑",
    "‒",
    "–",
    "—",
    "―",
    "−",
    "﹘",
    "﹣",
    "－",
)


class LooseFoldTest(unittest.TestCase):
    """Two spellings a person reads as one fold to one key."""

    def assert_same(self, first: str, second: str) -> None:
        """*first* and *second* fold alike."""
        self.assertEqual(sp.loose_fold(first), sp.loose_fold(second))

    def test_every_dash_lookalike_is_a_hyphen(self) -> None:
        for dash in _DASHES:
            with self.subTest(dash=f"U+{ord(dash):04X}"):
                self.assert_same(f"The Split{dash}Level Duo", "The Split-Level Duo")

    def test_a_hyphen_reads_as_the_space_it_separates_with(self) -> None:
        self.assert_same("Rock-n-Roll Placeholders", "Rock n Roll Placeholders")

    def test_curly_and_straight_quotes_are_one(self) -> None:
        self.assert_same("Don’t Invent", "Don't Invent")
        self.assert_same("“Quoted” Album", '"Quoted" Album')
        self.assert_same("Don´t Invent", "Dont Invent")

    def test_a_standalone_ampersand_is_the_word_and(self) -> None:
        self.assert_same("Placeholder & Invented", "Placeholder and Invented")
        self.assert_same("Placeholder & Invented", "Placeholder AND Invented")

    def test_an_ampersand_anywhere_is_the_word_and(self) -> None:
        self.assert_same("A&B", "A and B")
        self.assert_same("Rock&Roll", "Rock and Roll")
        self.assert_same("Rock& Roll", "Rock &Roll")
        self.assertEqual(sp.loose_fold("Rock&Roll"), "rock and roll")
        self.assertEqual(sp.loose_fold("&"), "and")

    def test_punctuation_and_spacing_are_dropped(self) -> None:
        self.assert_same("Invented Album, Vol. 1!", "invented   album vol 1")
        self.assertEqual(sp.loose_fold("  (Invented)  Album. "), "invented album")

    def test_case_and_compatibility_forms_fold(self) -> None:
        self.assert_same("INVENTED ﬁLE", "invented file")
        self.assert_same("Ｉｎｖｅｎｔｅｄ", "Invented")

    def test_letters_and_symbols_are_kept(self) -> None:
        self.assertNotEqual(sp.loose_fold("Café"), sp.loose_fold("Cafe"))
        self.assertEqual(sp.loose_fold("Placeholder + 1"), "placeholder + 1")

    def test_different_words_stay_different(self) -> None:
        self.assertNotEqual(
            sp.loose_fold("Invented Album"), sp.loose_fold("Other Album")
        )

    @given(st.text())
    def test_property_the_key_is_stable_and_holds_no_punctuation(
        self, text: str
    ) -> None:
        key = sp.loose_fold(text)
        self.assertEqual(sp.loose_fold(key), key)
        self.assertEqual(key, key.strip())
        self.assertNotIn("  ", key)
        self.assertFalse(
            any(unicodedata.category(c).startswith("P") for c in key), repr(key)
        )


class DifferingCharactersTest(unittest.TestCase):
    """Each differing character named by code point and Unicode name."""

    def test_a_hyphen_lookalike(self) -> None:
        self.assertEqual(
            sp.differing_characters("The Split‐Level Duo", "The Split-Level Duo"),
            "U+2010 HYPHEN vs U+002D HYPHEN-MINUS",
        )

    def test_a_quote_style(self) -> None:
        self.assertEqual(
            sp.differing_characters("Don’t Invent", "Don't Invent"),
            "U+2019 RIGHT SINGLE QUOTATION MARK vs U+0027 APOSTROPHE",
        )

    def test_an_ampersand_against_and(self) -> None:
        self.assertEqual(
            sp.differing_characters(
                "Placeholder & Invented", "Placeholder and Invented"
            ),
            "U+0026 AMPERSAND vs U+0061 LATIN SMALL LETTER A"
            " + U+006E LATIN SMALL LETTER N + U+0064 LATIN SMALL LETTER D",
        )

    def test_an_accented_letter(self) -> None:
        self.assertEqual(
            sp.differing_characters("Café Placeholder", "Cafe Placeholder"),
            "U+00E9 LATIN SMALL LETTER E WITH ACUTE vs U+0065 LATIN SMALL LETTER E",
        )

    def test_a_character_only_one_side_holds(self) -> None:
        self.assertEqual(
            sp.differing_characters("Invented Album ", "Invented Album"),
            "U+0020 SPACE vs nothing",
        )
        self.assertEqual(
            sp.differing_characters("Invented Album", "Invented, Album"),
            "nothing vs U+002C COMMA",
        )

    def test_a_character_with_no_name_is_its_code_point_alone(self) -> None:
        self.assertEqual(
            sp.differing_characters("Invented\x07", "Invented!"),
            "U+0007 vs U+0021 EXCLAMATION MARK",
        )

    def test_several_differences_are_each_named(self) -> None:
        self.assertEqual(
            sp.differing_characters("A‐B’C", "A-B'C"),
            "U+2010 HYPHEN vs U+002D HYPHEN-MINUS;"
            " U+2019 RIGHT SINGLE QUOTATION MARK vs U+0027 APOSTROPHE",
        )

    def test_a_long_note_is_cut_short_and_says_how_much_more(self) -> None:
        note = sp.differing_characters("a1b2c3d4e5", "a-b-c-d-e-")
        self.assertEqual(
            note,
            "U+0031 DIGIT ONE vs U+002D HYPHEN-MINUS;"
            " U+0032 DIGIT TWO vs U+002D HYPHEN-MINUS;"
            " U+0033 DIGIT THREE vs U+002D HYPHEN-MINUS; and 2 more",
        )
        side = sp.differing_characters("x", "xabcdef")
        self.assertEqual(
            side,
            "nothing vs U+0061 LATIN SMALL LETTER A + U+0062 LATIN SMALL LETTER B"
            " + U+0063 LATIN SMALL LETTER C + 3 more",
        )

    def test_equal_spellings_have_no_note(self) -> None:
        self.assertEqual(sp.differing_characters("Invented", "Invented"), "")


if __name__ == "__main__":
    unittest.main()
