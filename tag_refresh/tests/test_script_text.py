"""script_text: the shared field escape's decoder, and the handler text every script holds.

Pure: every input is a string built here, and nothing runs ``osascript``; the one
suite that runs the handler for real is `test_script_text_osascript.py`. The property
test holds the decoder to a reference escape built here character by character.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import _tag_refresh_fuzz_profile  # noqa: E402, F401 - loads the deterministic profile before any @given
import script_text  # noqa: E402 - import follows the sys.path bootstrap above

#: The scrobbler's script source, which holds its own copy of the handler in Swift.
_MUSIC_SCRIPTS_SWIFT = (
    Path(__file__).resolve().parents[2]
    / "scrobbler"
    / "app"
    / "Sources"
    / "ScrobblerCore"
    / "MusicScripts.swift"
)
#: The line that opens the Swift copy's multi-line string literal.
_SWIFT_OPENING = 'private static let escapeHandler = """'
#: The handler, verbatim. The text item passes catch every delimiter AppleScript sees
#: as a character of its own; the code-point check then catches one fused with a
#: following mark, which those passes skip, and rewrites the text from its code points.
_EXPECTED_HANDLER = """on escapedText(theText)
  if theText is missing value then return ""
  set savedDelimiters to AppleScript's text item delimiters
  set escapePairs to {{"%", "%25"}, {return & linefeed, "%0D%0A"}}
  set escapePairs to escapePairs & {{return, "%0D"}, {linefeed, "%0A"}}
  set escapePairs to escapePairs & {{tab, "%09"}, {character id 31, "%1F"}}
  repeat with escapePair in escapePairs
    set AppleScript's text item delimiters to item 1 of escapePair
    set theParts to text items of theText
    set AppleScript's text item delimiters to item 2 of escapePair
    set theText to theParts as text
  end repeat
  set AppleScript's text item delimiters to savedDelimiters
  set codePoints to id of theText
  if class of codePoints is not list then set codePoints to {codePoints}
  if codePoints contains 9 or codePoints contains 10 then return my escapedPoints(codePoints)
  if codePoints contains 13 or codePoints contains 31 then return my escapedPoints(codePoints)
  return theText
end escapedText

on escapedPoints(codePoints)
  if codePoints is {} then return ""
  script pointStore
    property pts : codePoints
    property outs : {}
  end script
  repeat with i from 1 to count of pointStore's pts
    set pointValue to item i of pointStore's pts
    if pointValue is 9 then
      set end of pointStore's outs to 37
      set end of pointStore's outs to 48
      set end of pointStore's outs to 57
    else if pointValue is 10 then
      set end of pointStore's outs to 37
      set end of pointStore's outs to 48
      set end of pointStore's outs to 65
    else if pointValue is 13 then
      set end of pointStore's outs to 37
      set end of pointStore's outs to 48
      set end of pointStore's outs to 68
    else if pointValue is 31 then
      set end of pointStore's outs to 37
      set end of pointStore's outs to 49
      set end of pointStore's outs to 70
    else
      set end of pointStore's outs to pointValue
    end if
  end repeat
  return string id (pointStore's outs)
end escapedPoints
"""


def swift_escape_handler() -> str:
    """The handler text the scrobbler's Swift string literal holds, as Swift reads it.

    The literal's lines run from its opening line to the line holding only its closing
    delimiter, whose indentation Swift strips from every line; the last line break
    before the delimiter is the value's own last character, and a line ending in a
    backslash continues on the next.
    """
    lines = _MUSIC_SCRIPTS_SWIFT.read_text(encoding="utf-8").split("\n")
    start = next(i for i, line in enumerate(lines) if line.strip() == _SWIFT_OPENING)
    end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == '"""')
    indent = len(lines[end]) - len(lines[end].lstrip())
    text = "\n".join(line[indent:] for line in lines[start + 1 : end])
    # A backslash ending a line is Swift's line continuation: the break is not text.
    return text.replace("\\\n", "")


#: What the scripts write for each character they escape: a percent sign and the
#: character's two uppercase hex digits. Every other character is kept.
_ESCAPED = {char: f"%{ord(char):02X}" for char in "%\x1f\t\n\r"}
#: A combining acute accent, spelled by its code point so the source shows it.
_ACUTE = chr(0x0301)
#: Text with no escapes in it, but a percent sign a script left as it was. The last is
#: the one sign AppleScript leaves: fused with a combining mark into one character,
#: which its text item search does not split.
_LONE_SIGNS = (
    "100% Invented",
    "%",
    "Invented %",
    "%G0",
    "%0",
    "%1f",
    "%" + _ACUTE + "09",
)
#: Text rich in what the escape turns on: every escaped character, the digits and
#: letters an escape's code is spelled with, and a combining mark, mixed with any
#: character at all.
_RICH_TEXT = st.text(
    alphabet=st.sampled_from("%\t\n\r\x1f0129ADF\u0301") | st.characters()
)


def escaped(text: str) -> str:
    """*text* with every character the scripts escape replaced by its escape.

    A reference for the decoder, character by character. It is not a model of the
    AppleScript handler, which leaves a percent sign fused with a following mark as it
    is; the decoder reads both forms the same, and `test_script_text_osascript.py`,
    which runs the handler itself, is the ground truth for what it writes.
    """
    return "".join(_ESCAPED.get(char, char) for char in text)


class UnescapeFieldTest(unittest.TestCase):
    """Every escape is undone in one pass, and nothing else is touched."""

    def test_every_escape_is_undone(self) -> None:
        self.assertEqual(
            script_text.unescape_field("a%25b%1Fc%09d%0Ae%0Df%0D%0Ag"),
            "a%b\x1fc\td\ne\rf\r\ng",
        )

    def test_a_sign_that_begins_no_escape_is_kept(self) -> None:
        for text in _LONE_SIGNS:
            with self.subTest(text=text):
                self.assertEqual(script_text.unescape_field(text), text)

    def test_an_escaped_sign_is_not_read_again(self) -> None:
        self.assertEqual(script_text.unescape_field("%2509"), "%09")

    def test_the_escapes_are_the_five_characters(self) -> None:
        self.assertEqual(dict(script_text.ESCAPES), {v: k for k, v in _ESCAPED.items()})

    @given(_RICH_TEXT)
    def test_fuzz_unescape_field(self, text: str) -> None:
        self.assertEqual(script_text.unescape_field(escaped(text)), text)
        self.assertLessEqual(len(script_text.unescape_field(text)), len(text))


class HandlerTextTest(unittest.TestCase):
    """One handler text, held verbatim, and the Swift copy held equal to it."""

    def test_the_handler_is_the_agreed_text(self) -> None:
        self.assertEqual(script_text.ESCAPE_HANDLER, _EXPECTED_HANDLER)

    def test_the_swift_copy_is_the_same_text(self) -> None:
        self.assertEqual(swift_escape_handler(), script_text.ESCAPE_HANDLER)

    def test_the_handler_writes_only_escapes_the_decoder_reads(self) -> None:
        # Each code the slow path spells as code points, and each pass's replacement.
        codes = {
            "%" + chr(digit) + chr(letter)
            for digit, letter in ((48, 57), (48, 65), (48, 68), (49, 70))
        }
        self.assertLessEqual(codes, set(script_text.ESCAPES))
        for pair in ('"%25"', '"%0D"', '"%0A"', '"%09"', '"%1F"'):
            self.assertIn(pair, script_text.ESCAPE_HANDLER)

    def test_the_handler_restores_the_delimiters_before_returning(self) -> None:
        lines = [line.strip() for line in script_text.ESCAPE_HANDLER.splitlines()]
        restore = lines.index(
            "set AppleScript's text item delimiters to savedDelimiters"
        )
        # The one early return, for missing value, comes before the delimiters change.
        returns = [i for i, line in enumerate(lines) if " return " in f" {line} "]
        self.assertEqual(returns[0], 1)
        self.assertTrue(all(i > restore for i in returns[1:]))


if __name__ == "__main__":
    unittest.main()
