"""Two spellings of one name: the loose key that pairs them, and the note that tells them apart.

`loose_fold` is for pairing the halves of a split album only, never for grouping:
Music.app keeps two spellings of an album apart, so the audit's album groups do too
(`audit_groups.normalized`), and this key decides only whether two such groups could be
one album a spelling divided. It folds what a person reads as the same name: case and
compatibility forms (NFKC), every dash and hyphen lookalike, curly and straight quotes,
an ``&`` against the word ``and``, punctuation and spacing.

`differing_characters` names what the key folded away, for the report: two spellings
that print alike (a typographic hyphen against an ASCII one) differ only in characters a
reader cannot see, so each is named by its code point and Unicode name.
"""

from __future__ import annotations

import difflib
import unicodedata

__all__ = ["differing_characters", "loose_fold"]

#: Dash lookalikes outside the dash-punctuation category, or worth naming anyway; every
#: other dash is caught by its category. All read as an ASCII hyphen.
_DASHES = "‐‑‒–—―−﹘﹣－"
#: Apostrophe and single-quote lookalikes, primes and the two spacing accents a keyboard
#: offers as one, all read as an ASCII apostrophe.
_SINGLE_QUOTES = "‘’‚‛′‵´`＇"
#: Double-quote lookalikes and double primes, all read as an ASCII double quote.
_DOUBLE_QUOTES = "“”„‟″‶＂"
_LOOKALIKES = str.maketrans(
    {
        **dict.fromkeys(_DASHES, "-"),
        **dict.fromkeys(_SINGLE_QUOTES, "'"),
        **dict.fromkeys(_DOUBLE_QUOTES, '"'),
    }
)
#: The quotes, dropped outright: they sit inside or around a word (``Don't``), so a
#: space in their place would split one word in two.
_QUOTES = frozenset("'\"")
#: The ampersand, and the word it reads as: its own token wherever it stands, so
#: ``Rock&Roll`` and ``Rock and Roll`` compare alike.
_AMPERSAND = "&"
_AND = " and "
#: The Unicode category prefix of every punctuation character.
_PUNCTUATION = "P"
#: How many differences a note names, and how many characters of one side, before it
#: says how many more there are: a note is a pointer, not a transcript.
_MAX_CHANGES = 3
_MAX_SIDE = 3
#: What a note names one side of a difference as when that side holds nothing.
_NOTHING = "nothing"


def _folded_form(text: str) -> str:
    """*text* in compatibility form and casefolded, composed again after the folding."""
    return unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", text).casefold())


def _unpunctuated(text: str) -> str:
    """*text* with its quotes dropped and every other punctuation mark a space."""
    return "".join(
        ""
        if char in _QUOTES
        else " "
        if unicodedata.category(char).startswith(_PUNCTUATION)
        else char
        for char in text
    )


def loose_fold(text: str) -> str:
    """*text* as split albums are paired: two spellings a reader takes as one fold alike.

    Lookalike quotes are read as ASCII before the compatibility fold, which would
    otherwise turn a spacing accent into a space and a combining mark. An ``&`` reads
    as the word ``and``, spaced or not (after the fold, which makes a full-width one
    ASCII). The result is folded once
    more, since dropping a quote can leave a combining mark beside a letter it composes
    with.
    """
    folded = _folded_form(text.translate(_LOOKALIKES)).translate(_LOOKALIKES)
    spaced = _unpunctuated(folded.replace(_AMPERSAND, _AND))
    return " ".join(_folded_form(spaced).split())


def _named(char: str) -> str:
    """*char* as a note names it: its code point, then its Unicode name if it has one."""
    name = unicodedata.name(char, "")
    point = f"U+{ord(char):04X}"
    return f"{point} {name}" if name else point


def _side(chars: str) -> str:
    """One side of a difference: each character named, or nothing, cut short when long."""
    if not chars:
        return _NOTHING
    named = " + ".join(_named(char) for char in chars[:_MAX_SIDE])
    more = len(chars) - _MAX_SIDE
    return f"{named} + {more} more" if more > 0 else named


def differing_characters(first: str, second: str) -> str:
    """The characters *first* and *second* differ in, each side named; "" when equal.

    Each difference reads ``<first's characters> vs <second's>``, in the order they
    occur, separated by ``;``. The spellings are compared as tagged, not folded, since
    the folded-away characters are the point.
    """
    matcher = difflib.SequenceMatcher(None, first, second, autojunk=False)
    changes = [
        f"{_side(first[a0:a1])} vs {_side(second[b0:b1])}"
        for tag, a0, a1, b0, b1 in matcher.get_opcodes()
        if tag != "equal"
    ]
    note = "; ".join(changes[:_MAX_CHANGES])
    more = len(changes) - _MAX_CHANGES
    return f"{note}; and {more} more" if more > 0 else note
