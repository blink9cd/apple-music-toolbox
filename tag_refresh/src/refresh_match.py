"""The lookup's reply, parsed strictly, and its rows matched to the named MP3s.

Pure, like `refresh_core`, whose `Mp3` and seams it takes: nothing here talks to
Music.app, runs a process or prints. `parse_rows` reads the lookup script's output
into rows and counts the lines in none of their shape; `match_tracks` keeps a row only
when its own path stats to a named MP3's device and inode. ``stat`` is the one seam.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass

from refresh_core import FileKey, Mp3, StatFn
from script_text import unescape_field

#: The one row terminator. Never ``splitlines``, which also breaks on
#: ``\v \f \x1c-\x1e \x85 U+2028 U+2029`` and so would split a path holding one.
_TERMINATOR = "\n"
#: Music's track ids start at 1, and `music_calls.refresh_ids` refuses a lower one as a
#: caller's bug, so no row holding one is ever returned.
_FIRST_TRACK_ID = 1
#: Music's track ids are small positive integers; 18 digits bounds an id below 10**18
#: so a row cannot make the parser build an arbitrarily large integer.
_MAX_ID_DIGITS = 18
#: A lookup row: a decimal id from 1 with no leading zero (as Music prints it), a
#: 16-digit hex persistent ID, and an absolute path, escaped, tab separated. Music
#: emits the ID in uppercase; either case is read, to agree with the refresh call's own
#: check of the pairs it is handed. ``[0-9]``, never ``\d``, which takes every Unicode
#: digit. The escaped path holds no raw tab (a field boundary) or CR (a text-mode read
#: turns one into a linefeed), and no NUL (``os.stat`` raises on it); its escapes are
#: read back once the row has matched.
_ROW = re.compile(
    rf"([1-9][0-9]{{0,{_MAX_ID_DIGITS - 1}}})\t([0-9A-Fa-f]{{16}})\t(/[^\t\r\x00]*)"
)
#: The persistent ID's shape alone, for `is_row`.
_PERSISTENT_ID = re.compile(r"[0-9A-Fa-f]{16}")
#: What a returned row's decoded path may never hold: no escape stands for a NUL.
_ROW_PATH_FORBIDDEN = frozenset("\x00")


@dataclass(frozen=True)
class Row:
    """One lookup row: Music's track id, its persistent ID, and its file's POSIX path."""

    track_id: int
    persistent_id: str
    path: str


@dataclass(frozen=True)
class ParsedRows:
    """The well-formed rows, and how many non-empty rows were not."""

    rows: tuple[Row, ...]
    unparsed: int


@dataclass(frozen=True)
class Matches:
    """The ``(id, persistent ID)`` pairs per named MP3, and the MP3s matching none."""

    matched: tuple[tuple[Mp3, tuple[tuple[int, str], ...]], ...]
    not_in_music: tuple[Mp3, ...]


def is_row(row: Row) -> bool:
    """Return whether ``row`` has the shape every row `parse_rows` returns has."""
    return (
        row.track_id >= _FIRST_TRACK_ID
        and _PERSISTENT_ID.fullmatch(row.persistent_id) is not None
        and row.path.startswith("/")
        and not _ROW_PATH_FORBIDDEN.intersection(row.path)
    )


# fuzz-target
def parse_rows(text: str) -> ParsedRows:
    """Parse the lookup script's output strictly; count, never raise on, a bad row.

    A row ends only at a linefeed and is a decimal id of at least 1, a 16-digit hex
    persistent ID and an absolute path, tab separated. Empty segments are skipped
    (``osascript`` adds a linefeed of its own after the last row's); a final segment
    with no linefeed is counted, as a row cut short. The script escapes the path, so a
    tab, line break, U+001F or percent sign in it stays inside its own row, and
    `unescape_field` reads it back after the row matches; a path can no longer forge
    a row. `match_tracks` still trusts no row's text, only what its path stats to.
    """
    *terminated, tail = text.split(_TERMINATOR)
    rows: list[Row] = []
    unparsed = 1 if tail else 0
    for segment in terminated:
        if not segment:
            continue
        found = _ROW.fullmatch(segment)
        if found is None:
            unparsed += 1
            continue
        track_id, persistent_id, path = found.groups()
        rows.append(Row(int(track_id), persistent_id, unescape_field(path)))
    return ParsedRows(tuple(rows), unparsed)


def _row_key(path: str, stat: StatFn) -> FileKey | None:
    """Return the device and inode ``path`` stats to, or None when it cannot be."""
    try:
        info = stat(path)
    except (OSError, ValueError):
        # A vanished or unreadable path matches nothing, nor does one os.stat refuses.
        return None
    return info.st_dev, info.st_ino


def match_tracks(
    rows: Sequence[Row], mp3s: Sequence[Mp3], *, stat: StatFn = os.stat
) -> Matches:
    """Match lookup rows to the named MP3s by the device and inode their paths stat to.

    A row is kept only when its own path stats to a named MP3's key, and a vanished
    path is simply no match. The rows reach it from callers too, not only from
    `parse_rows`, so a row naming the named file's path but another track's
    ``(id, persistent ID)`` pair would attach that pair to the MP3. Since the refresh
    call checks each pair's persistent ID, the worst outcome is a tag reread of the
    other, real track the pair names. Each MP3 keeps its ``(id, persistent ID)`` pairs once each, in row
    order; an MP3 matching none is listed as not in Music, in the order given.
    """
    by_key: dict[FileKey, dict[tuple[int, str], None]] = {mp3.key: {} for mp3 in mp3s}
    for row in rows:
        key = _row_key(row.path, stat)
        if key is not None and key in by_key:
            by_key[key][(row.track_id, row.persistent_id)] = None
    matched = tuple((mp3, tuple(by_key[mp3.key])) for mp3 in mp3s if by_key[mp3.key])
    missing = tuple(mp3 for mp3 in mp3s if not by_key[mp3.key])
    return Matches(matched, missing)
