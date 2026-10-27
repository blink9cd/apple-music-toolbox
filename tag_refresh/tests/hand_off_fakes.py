"""A stand-in for lyricsmith's album writing its ``--changed-list`` file.

The hand-off suite proves that ``--tracks-from`` reads the list a lyrics run writes.
album lives in another project now, so this suite no longer runs it: it writes the same
bytes that album's writer does instead. `format_changed_list` and `refusal` are copied
from ``format_changed_list`` and ``refusal`` in lyricsmith's ``album/src/lyrics_changed.py``:
UTF-8, one absolute path per line, each line ended by a linefeed, each path normalized
lexically and written once, and a path the reader's contract refuses left out with the
reason. Should that writer change its format, this copy must change with it: the
tripwire is ``test_changed_list_golden.py``, which pins this copy to the same literal
corpus and output that lyricsmith's ``album/tests/test_lyrics_changed_golden.py`` pins
the writer to, so the two literals must change together.

`build_album` makes the one album the suite hands off: three placeholder MP3s, the first
two the ones a lyrics run there saves, and the third the one it never touches.

Not discovered as a suite (no ``test_`` prefix). Suites import it by bare name with
this directory on ``sys.path``.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

#: Why a path is left out of the list, one per rule of the reader's contract.
REASON_LINEFEED = "holds a linefeed, which would split it into two lines"
REASON_CR = "ends in a carriage return, which reads as a CRLF line ending"
REASON_NUL = "holds a NUL"
REASON_NOT_UTF8 = "is not UTF-8"
REASON_RELATIVE = "is not an absolute path"

_LINEFEED = "\n"
_CR = "\r"
_NUL = "\x00"
_ENCODING = "utf-8"

#: The album's folder name, which is also the album name the fake Music files it under.
ALBUM = "album"
#: The album's placeholder tracks. The suite lists the first two as a run's changes, and
#: the third, never listed, stands for a track the run leaves as it was.
TRACKS = ("01 Keeper.mp3", "CD2/02 Orchard.mp3", "CD2/03 Mill.mp3")
#: Invented bytes standing in for an MP3: the reader matches files by device and inode.
_PLACEHOLDER_MP3 = b"ID3 invented"


@dataclass(frozen=True)
class LeftOut:
    """A path the list cannot hold, as it was given, and why."""

    path: str
    reason: str


def refusal(path: str) -> str | None:
    """Why the reader could not read *path* back from a list line, or None when it can."""
    if _LINEFEED in path:
        return REASON_LINEFEED
    if _NUL in path:
        return REASON_NUL
    if path.endswith(_CR):
        return REASON_CR
    try:
        path.encode(_ENCODING)
    except UnicodeEncodeError:
        return REASON_NOT_UTF8
    if not Path(path).is_absolute():
        return REASON_RELATIVE
    return None


def format_changed_list(paths: Iterable[str]) -> tuple[bytes, tuple[LeftOut, ...]]:
    """The list file's bytes for *paths*, and each path left out of it, with why.

    Each path is normalized lexically, as the reader normalizes what it reads, so
    every written line reads back as itself; it is written once, where first named.
    A path left out is named once too. No paths make an empty file.
    """
    lines: dict[str, None] = {}
    left: dict[str, LeftOut] = {}
    for path in paths:
        normal = os.path.normpath(path)
        reason = refusal(normal)
        if reason is None:
            lines[normal] = None
        else:
            left.setdefault(path, LeftOut(path, reason))
    data = "".join(f"{line}{_LINEFEED}" for line in lines).encode(_ENCODING)
    return data, tuple(left.values())


def write_changed_list(target: Path, paths: Iterable[Path]) -> Path:
    """Write the list naming *paths* to *target*, as album writes it; return *target*.

    Each path is named as album names a track, absolute but never resolved.
    """
    data, _ = format_changed_list(os.path.abspath(path) for path in paths)
    target.write_bytes(data)
    return target


def build_album(root: Path) -> tuple[Path, ...]:
    """Make `ALBUM` under *root*, one placeholder MP3 per name in `TRACKS`; their paths."""
    made = []
    for relative in TRACKS:
        path = root / ALBUM / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_PLACEHOLDER_MP3)
        made.append(path)
    return tuple(made)
