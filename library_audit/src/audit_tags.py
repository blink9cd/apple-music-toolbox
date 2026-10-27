r"""What an audio file's tags say, through mutagen when it imports: its album and numbers.

mutagen lives in the project's ``refresh_tags`` extra, and the core tools import no
third-party package, so it is optional here as in tag_refresh: `load_tag_reader`
returns None without it, and the audit then skips its tag checks and says so.

The audit groups files into albums by these tags: the album artist (the
artist when that is empty), the album and the disc. Each format spells them its own
way, and `file_tags_from` reads both spellings the collected formats carry from
whatever tag object mutagen hands back: ID3 frames (``TPE2``, ``TPE1``, ``TALB``, and
``TRCK`` and ``TPOS``, each ``n`` or ``n/total``: an MP3's, an AIFF's or a WAV's) and
MP4 atoms (``aART``, ``\xa9ART``, ``\xa9alb``, and ``trkn`` and ``disk``, each an
``(n, total)`` pair). The compilation flag is ID3 ``TCMP`` (the text ``1``) or MP4
``cpil`` (a true value): a flagged file groups under one fixed artist key, as Music.app
files a compilation, whatever artist each track names. No collected suffix carries
Vorbis comments: Music.app imports no FLAC. That half is pure, so every spelling is tested without a real audio file.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

#: The suffix read as a bare ID3 tag rather than through mutagen's format detection,
#: which looks for audio frames first and so cannot read a tag on a file holding none.
_ID3_SUFFIX = ".mp3"
#: Each format's key for the album artist, the artist, the album, the track number and
#: the disc number: ID3 first, then MP4.
_ALBUM_ARTIST_KEYS = ("TPE2", "aART")
_ARTIST_KEYS = ("TPE1", "\xa9ART")
_ALBUM_KEYS = ("TALB", "\xa9alb")
_ID3_TRACK = "TRCK"
_TRACK_KEYS = (_ID3_TRACK, "trkn")
#: The lowest track number each format can mean. MusicBrainz numbers a pregap ("hidden
#: track one") track 0, and Picard writes that into ID3; iTunes stores a blank number
#: beside a set total as an MP4 ``(0, total)``, so there a 0 is no number.
_ID3_LOWEST_TRACK, _MP4_LOWEST_TRACK = 0, 1
_DISC_KEYS = ("TPOS", "disk")
#: The compilation flag: an ID3 text frame reading ``1``, and an MP4 boolean atom.
_ID3_COMPILATION, _MP4_COMPILATION = "TCMP", "cpil"
_ID3_FLAG_SET = "1"
#: A disc tag that is absent or unreadable is disc 1: most albums are one disc, untagged.
_DEFAULT_DISC = 1
#: No album runs past four digits of tracks, and a bound keeps one stray tag from
#: making the gap check list thousands of missing numbers.
_MAX_DIGITS = 4
#: The largest disc or track number read, from any source: a Music.app listing row
#: (`audit_read.row_tags`) is held to the same bound a file's tag is.
LARGEST_NUMBER = 10**_MAX_DIGITS - 1
#: ``n`` or ``n/total``, spaces allowed around each part and an empty total read as none.
_NUMBER_PAIR = re.compile(
    rf"\s*([0-9]{{1,{_MAX_DIGITS}}})\s*(?:/\s*([0-9]{{0,{_MAX_DIGITS}}})\s*)?"
)


@dataclass(frozen=True)
class FileTags:
    """What a file's tags say: its album group, and its numbers when it has them.

    ``artist`` is the album artist, or the artist when that is empty; either name is
    the empty string when absent. ``track`` is at least 1 (or 0, a pregap track, from
    an ID3 tag), or None when the tags hold no usable track number (and ``total`` is
    then None too). ``compilation`` is the
    compilation flag.
    """

    artist: str
    album: str
    disc: int
    track: int | None
    total: int | None
    compilation: bool = False


class TagMapping(Protocol):
    """What the reading needs of a tag object: a lookup by key, None when absent.

    mutagen's ID3 and MP4 tags each answer it, and so does a plain dict.
    """

    def get(self, key: str, /) -> object:
        """The value under *key*, or None."""
        ...


#: The tag reader: a file's tags, or None when they cannot be read at all (no tag
#: object, or a file mutagen cannot open or parse). A reader catches its own errors:
#: nothing calling it guards the call.
TagReader = Callable[[Path], FileTags | None]


def parse_number_pair(text: str) -> tuple[int, int | None] | None:
    """``n`` or ``n/total`` as ``(n, total)``; a total of 0 or none is None.

    Returns None when *text* holds no number in that shape.
    """
    found = _NUMBER_PAIR.fullmatch(text)
    if found is None:
        return None
    number, total = found.groups()
    return int(number), (int(total) if total else None) or None


def _first_text(tags: TagMapping, keys: tuple[str, ...]) -> str | None:
    """The first value under the first of *keys* that *tags* holds, as text.

    An ID3 frame holds its values under ``text``; an MP4 pair is joined as ``n/total``.
    A value that is not a list of values is no number.
    """
    for key in keys:
        value = tags.get(key)
        if value is None:
            continue
        values: object = getattr(value, "text", value)
        if not isinstance(values, (list, tuple)) or not values:
            return None
        first = values[0]
        if isinstance(first, tuple):
            return "/".join(str(part) for part in first)
        return str(first)
    return None


def _numbers(tags: TagMapping) -> tuple[int | None, int | None]:
    """The track number and track-count tag *tags* holds; ``(None, None)`` for none.

    An ID3 track number of 0 is a pregap track; an MP4 one is no number.
    """
    track = parse_number_pair(_first_text(tags, _TRACK_KEYS) or "")
    has_id3 = tags.get(_ID3_TRACK) is not None
    lowest = _ID3_LOWEST_TRACK if has_id3 else _MP4_LOWEST_TRACK
    if track is None or track[0] < lowest:
        return None, None
    return track


def _is_compilation(tags: TagMapping) -> bool:
    """Whether *tags* flags its file as part of a compilation.

    mutagen hands ``cpil`` back as a bare boolean; a list of values is read by its
    first, so a stand-in holding one reads the same way.
    """
    frame = tags.get(_ID3_COMPILATION)
    texts: object = getattr(frame, "text", None)
    if isinstance(texts, (list, tuple)) and texts:
        return str(texts[0]).strip() == _ID3_FLAG_SET
    atom = tags.get(_MP4_COMPILATION)
    if isinstance(atom, (list, tuple)):
        return bool(atom) and bool(atom[0])
    return bool(atom)


def file_tags_from(tags: TagMapping | None) -> FileTags | None:
    """What *tags* says of its file, or None when there is no tag object to read."""
    if tags is None:
        return None
    artist = _first_text(tags, _ALBUM_ARTIST_KEYS) or _first_text(tags, _ARTIST_KEYS)
    disc = parse_number_pair(_first_text(tags, _DISC_KEYS) or "")
    track, total = _numbers(tags)
    return FileTags(
        artist or "",
        _first_text(tags, _ALBUM_KEYS) or "",
        disc[0] if disc and disc[0] >= 1 else _DEFAULT_DISC,
        track,
        total,
        _is_compilation(tags),
    )


def load_tag_reader() -> TagReader | None:
    """Return mutagen's tag reader when mutagen imports, else None.

    The reader returns None for a file it cannot open or parse, and for one holding
    no tag object, so either lands in the audit's unreadable list; tags read with no
    track number come back with ``track`` None, for the audit's own list of those.
    """
    try:
        import mutagen
        from mutagen.id3 import ID3
    except ImportError:
        return None

    def read_tags(path: Path) -> FileTags | None:
        """What *path*'s tags say, or None."""
        # Catching Exception, deliberately and only around mutagen's own calls: it is a
        # third-party parser fed untrusted bytes, and beyond its own errors it has let
        # struct.error, KeyError and IndexError escape on crafted frames. One file listed
        # under unreadable tags is better than a crashed run.
        try:
            if path.suffix.lower() == _ID3_SUFFIX:
                tags: TagMapping | None = ID3(path)
            else:
                audio = mutagen.File(path)
                tags = None if audio is None else audio.tags
        except Exception:
            return None
        return file_tags_from(tags)

    return read_tags
