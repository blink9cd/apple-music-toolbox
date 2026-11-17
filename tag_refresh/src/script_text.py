"""The percent escape the listing scripts write into their text fields, and its undoing.

Pure: nothing here talks to Music.app or runs a process. A listing script writes each
row's fields joined by tabs and each row ended by a linefeed, so a field holding a tab
or a line break would split its row or forge another. The scripts therefore write each
percent sign, U+001F, tab, linefeed and carriage return in a text field or path as a
percent sign and that character's two uppercase hex digits, and their parsers call
`unescape_field` on each field after the row's shape is checked. One copy of each half
lives here, shared by play_count_baseline, library_audit and tag_refresh.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType

#: The AppleScript handlers every listing script opens with: ``escapedText`` writes a
#: text field or path with each percent sign, U+001F, tab, linefeed and carriage return
#: as a percent sign and its two hex digits, and reads `missing value` as "".
#:
#: Two steps, because AppleScript's text item search works on whole characters
#: (grapheme clusters), not code points. The text item passes are the fast path: one
#: split and join a delimiter, the percent sign first so no later pass leaves a sign the
#: parser would misread, and the CR LF pair before either alone. A delimiter followed by
#: a combining mark or a variation selector is one character with that mark, though,
#: and a search passes it by (measured with osascript and no Music.app: a tab, linefeed,
#: carriage return or U+001F before U+0301 or U+FE0F came back raw). So the handler then
#: reads the text's code points, and only when one of those four is still there does
#: ``escapedPoints`` rebuild the text from them, each of the four as its escape's code
#: points. Running it on text the passes already escaped is safe: every percent sign in
#: it begins an escape, or is one fused with a following mark that the passes left
#: alone, and the decoder keeps a sign that begins no escape. ``id of`` gives one value
#: a code point, an emoji outside the Basic Multilingual Plane included (measured: one
#: value, 128512, for U+1F600), and ``string id`` builds the same text back, so the
#: rebuild loses nothing. The rebuild keeps both lists as properties of a script object,
#: reads them by index and grows its output with ``set end of``. Each step of a loop
#: over a handler's local list, or of one growing a list with ``&``, costs time in the
#: list's length, so the first version was quadratic: about 10 s at 16,000 code points,
#: which a crafted tag could push past a call's time bound. This one is about linear
#: (measured on an idle machine: about 0.1, 0.4 and 4.4 s at 4,000, 16,000 and 64,000
#: code points; about three times that under heavy load). An empty list is answered
#: first, because ``string id {}`` crashes osascript (measured: exit 139). The Swift
#: copy in the scrobbler's ``MusicScripts.swift`` is held equal to this text by
#: tag_refresh's ``test_script_text.py``.
ESCAPE_HANDLER = """on escapedText(theText)
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
#: Each escape the scripts write, and the character it stands for: a percent sign and
#: the character's two uppercase hex digits.
ESCAPES: Mapping[str, str] = MappingProxyType(
    {f"%{ord(char):02X}": char for char in "%\x1f\t\n\r"}
)
#: Any one of `ESCAPES`, matched left to right in one pass, so the ``%09`` that
#: ``%2509`` leaves once its sign is read is never read again.
_ESCAPE = re.compile("|".join(ESCAPES))


# fuzz-target
def unescape_field(text: str) -> str:
    """*text* with every one of `ESCAPES` replaced by the character it stands for.

    Never raises: a percent sign that begins no escape is kept as it is, so a sign the
    script left unescaped (one fused with a following combining mark) still reads.
    """
    return _ESCAPE.sub(lambda found: ESCAPES[found.group(0)], text)
