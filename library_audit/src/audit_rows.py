"""The listing's reply, parsed strictly: one `TrackRow` a well-formed line, the rest counted.

Pure: nothing here talks to Music.app, runs a process or prints. `parse_track_rows`
reads what `music_calls.list_tracks` returns and never raises on a bad row; it
counts it, so the audit can say its picture of Music.app is incomplete rather than
report a file as having no track because that track's row was unreadable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The one row terminator. Never ``splitlines``, which also breaks on
#: ``\v \f \x1c-\x1e \x85 U+2028 U+2029`` and so would split a name holding one.
_TERMINATOR = "\n"
#: Disc and track numbers are small; nine digits bounds one below 10**9 so a row
#: cannot make the parser build an arbitrarily large integer.
_MAX_NUMBER_DIGITS = 9
#: How the listing script writes an AppleScript boolean (``compilation``, ``enabled``).
_TRUE, _FALSE = "true", "false"
#: A size the parser takes as exact: plain ASCII digits, at most fifteen, so below
#: 10**15 bytes and so below 2**53, the largest integer an AppleScript real holds
#: exactly. Anything else (``6.0E+8``, a fraction, a sign) is an unknown size.
_EXACT_SIZE = re.compile(r"[0-9]{1,15}")
#: The class of a track that has a file, as the listing script writes it.
FILE_TRACK = "file track"
#: A listing row, tab separated: a 16-digit hex persistent ID (either case, as the
#: lookup's parser reads it), the cloud status as Music spells it, the disc and track
#: numbers in decimal, the POSIX path (empty for a track with no file, else absolute),
#: the album, the artist, and the compilation flag as AppleScript writes a boolean
#: (``true`` or ``false``), the track's class as Music spells it (``file track``,
#: ``shared track``), never empty, the enabled flag (``true`` or ``false``), and
#: Music's size in bytes, any text holding no tab or carriage return (`size_of` reads
#: it). A new field goes at the end, so the fields before it keep their places.
#: ``[0-9]``, never ``\d``, which takes every Unicode digit.
#: No field may hold a tab (a field boundary) or a carriage return (a text-mode read
#: turns one into a linefeed), and the path no NUL either (``os.stat`` raises on it).
_ROW = re.compile(
    rf"([0-9A-Fa-f]{{16}})\t([^\t\r]*)\t([0-9]{{1,{_MAX_NUMBER_DIGITS}}})"
    rf"\t([0-9]{{1,{_MAX_NUMBER_DIGITS}}})\t((?:/[^\t\r\x00]*)?)\t([^\t\r]*)\t([^\t\r]*)"
    rf"\t({_TRUE}|{_FALSE})\t([^\t\r]+)\t({_TRUE}|{_FALSE})\t([^\t\r]*)"
)
#: The persistent ID's shape alone, for `is_track_row`.
_PERSISTENT_ID = re.compile(r"[0-9A-Fa-f]{16}")
#: What no text field of a returned row may hold, and what its path may not either.
_FIELD_FORBIDDEN = frozenset("\t\n\r")
_PATH_FORBIDDEN = _FIELD_FORBIDDEN | {"\x00"}


@dataclass(frozen=True)
class TrackRow:
    """One track as Music.app listed it.

    ``path`` is the empty string when the track has no file, which is always so for a
    track whose ``track_class`` is not `FILE_TRACK` (a shared or URL track); ``artist``
    is the album artist, or the track's artist when the album artist is empty.
    ``compilation`` is Music.app's compilation flag, and ``enabled`` its checkbox
    (false for an unchecked track). ``size`` is Music.app's byte size, 0 when it
    gave none, and None when the listing's text was not an exact integer.
    """

    persistent_id: str
    cloud_status: str
    disc: int
    track: int
    path: str
    album: str
    artist: str
    compilation: bool = False
    track_class: str = FILE_TRACK
    enabled: bool = True
    size: int | None = 0


@dataclass(frozen=True)
class ParsedTracks:
    """The well-formed rows, and how many non-empty rows were not."""

    rows: tuple[TrackRow, ...]
    unparsed: int


def is_track_row(row: TrackRow) -> bool:
    """Return whether *row* has the shape every row `parse_track_rows` returns has."""
    texts = (row.cloud_status, row.album, row.artist, row.track_class)
    return (
        _PERSISTENT_ID.fullmatch(row.persistent_id) is not None
        and row.disc >= 0
        and row.track >= 0
        and row.track_class != ""
        and (row.size is None or row.size >= 0)
        and (row.path == "" or row.path.startswith("/"))
        and not _PATH_FORBIDDEN.intersection(row.path)
        and not any(_FIELD_FORBIDDEN.intersection(text) for text in texts)
    )


def size_of(text: str) -> int | None:
    """The byte size *text* states exactly, or None when it is not plain digits."""
    return int(text) if _EXACT_SIZE.fullmatch(text) else None


def _row_of(segment: str) -> TrackRow | None:
    """The row one terminated segment holds, or None when it is in no row's shape."""
    found = _ROW.fullmatch(segment)
    if found is None:
        return None
    (
        persistent_id,
        status,
        disc,
        track,
        path,
        album,
        artist,
        flag,
        kind,
        enabled,
        size,
    ) = found.groups()
    return TrackRow(
        persistent_id,
        status,
        int(disc),
        int(track),
        path,
        album,
        artist,
        flag == _TRUE,
        kind,
        enabled == _TRUE,
        size_of(size),
    )


# fuzz-target
def parse_track_rows(text: str) -> ParsedTracks:
    """Parse the listing's output strictly; count, never raise on, a bad row.

    A row ends only at a linefeed. Empty segments are skipped (``osascript`` adds a
    linefeed of its own after the last row's); a final segment with no linefeed is
    counted, as a row cut short.
    """
    *terminated, tail = text.split(_TERMINATOR)
    rows: list[TrackRow] = []
    unparsed = 1 if tail else 0
    for segment in terminated:
        if not segment:
            continue
        row = _row_of(segment)
        if row is None:
            unparsed += 1
        else:
            rows.append(row)
    return ParsedTracks(tuple(rows), unparsed)
