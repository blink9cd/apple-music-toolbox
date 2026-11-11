"""The play-count listing's reply, parsed strictly: one `RawTrack` a well-formed row, the rest counted.

Pure: nothing here talks to Music.app, runs a process, or prints. `parse_play_rows`
reads what `baseline_calls.list_play_counts` returns and never raises on a bad row;
it counts it, so the run can say its picture of the library is incomplete rather than
write a baseline that silently lacks a track.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple

#: The one row terminator. Never ``splitlines``, which also breaks on
#: ``\v \f \x1c-\x1e \x85 U+2028 U+2029`` and so would split a name holding one.
_TERMINATOR = "\n"
#: How many tab-separated fields a row holds.
FIELD_COUNT = 12
#: Nine digits bounds a number below 10**9, so a row cannot make the parser build an
#: arbitrarily large integer; every count here is smaller, and the script's 149-hour
#: duration ceiling (536,870,000 ms) is too.
_MAX_NUMBER_DIGITS = 9
#: A number field: plain ASCII digits, ``[0-9]`` and never ``\d``, which takes every
#: Unicode digit.
_NUMBER = rf"[0-9]{{1,{_MAX_NUMBER_DIGITS}}}"
#: Any text field: no tab (a field boundary) and no carriage return (a text-mode read
#: turns one into a linefeed).
_TEXT = r"[^\t\r]*"
#: The scrobbler's date parts, ``Y/M/D/seconds-after-midnight``, or empty for none.
_DATE_PARTS = r"(?:[0-9]{1,4}/[0-9]{1,2}/[0-9]{1,2}/[0-9]{1,5})?"
#: A listing row, tab separated, in this order: a 16-digit hex persistent ID (either
#: case), name, artist, album, album artist, disc number, duration in milliseconds
#: (empty for none), played count, played date parts, genre, year, and the POSIX path
#: (empty for none, else absolute, and never holding a NUL, on which ``os.stat``
#: raises).
_ROW = re.compile(
    rf"([0-9A-Fa-f]{{16}})\t({_TEXT})\t({_TEXT})\t({_TEXT})\t({_TEXT})"
    rf"\t({_NUMBER})\t((?:{_NUMBER})?)\t({_NUMBER})\t({_DATE_PARTS})"
    rf"\t({_TEXT})\t({_NUMBER})\t((?:/[^\t\r\x00]*)?)"
)


@dataclass(frozen=True)
class RawTrack:
    """One track as the play-count listing reported it, before any mapping.

    ``album_artist`` is Music's own, empty when it has none (never the artist).
    ``disc_number`` and ``year`` are 0 for none, ``duration_ms`` None for none,
    ``played_date`` the raw date parts (``""`` for never played), and ``path`` the
    POSIX path (``""`` for a track with no file).
    """

    persistent_id: str
    name: str
    artist: str
    album: str
    album_artist: str
    disc_number: int
    duration_ms: int | None
    played_count: int
    played_date: str
    genre: str
    year: int
    path: str


class ParsedRows(NamedTuple):
    """The well-formed rows, and how many non-empty rows were not."""

    rows: tuple[RawTrack, ...]
    unparsed: int


def _track_of(segment: str) -> RawTrack | None:
    """The track one terminated segment holds, or None when it is in no row's shape."""
    found = _ROW.fullmatch(segment)
    if found is None:
        return None
    (
        pid,
        name,
        artist,
        album,
        album_artist,
        disc,
        duration,
        count,
        date,
        genre,
        year,
        path,
    ) = found.groups()
    return RawTrack(
        persistent_id=pid,
        name=name,
        artist=artist,
        album=album,
        album_artist=album_artist,
        disc_number=int(disc),
        duration_ms=int(duration) if duration else None,
        played_count=int(count),
        played_date=date,
        genre=genre,
        year=int(year),
        path=path,
    )


# fuzz-target
def parse_play_rows(reply: str) -> ParsedRows:
    """Parse the listing's reply strictly; count, never raise on, a bad row.

    A row ends only at a linefeed. Empty segments are skipped (``osascript`` adds a
    linefeed of its own after the last row's); a final segment with no linefeed is
    counted, as a row cut short.
    """
    *terminated, tail = reply.split(_TERMINATOR)
    rows: list[RawTrack] = []
    unparsed = 1 if tail else 0
    for segment in terminated:
        if not segment:
            continue
        track = _track_of(segment)
        if track is None:
            unparsed += 1
        else:
            rows.append(track)
    return ParsedRows(tuple(rows), unparsed)
