"""Every walked file's tags, read without ever opening an iCloud placeholder.

Opening a placeholder makes iCloud download it, so `read_library_tags` never hands
one to the tag reader. A placeholder matched to a Music.app track takes its tags from
that track's listing row instead (`row_tags`). The row holds what Music.app last read
from the file, so the placeholder groups and gap-checks as its file would while the
two agree; a file retagged outside Music.app since then groups by the older names. A
placeholder with no track has no tags at all; it is left out of the tags, so it
groups by its folder as a file whose tags cannot be read does, but it is not listed
as unreadable, because its tags were never tried.

The count check then sees a matched placeholder and its track as one item in one
group, exactly as any other matched file: the placeholder's group is the one its
own track's row gives, and the track counts toward its file's group.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from audit_rows import TrackRow
from audit_tags import LARGEST_NUMBER, FileTags, TagReader
from audit_walk import AudioFile
from refresh_core import FileKey

#: Music.app's disc 0 is "no disc number", which a file's absent disc tag reads as 1.
_FIRST_DISC = 1


@dataclass(frozen=True)
class ReadTags:
    """Every file's tags that could be had, and the two lists the reading makes."""

    tags: dict[Path, FileTags]
    unreadable: tuple[Path, ...]
    no_track_number: tuple[Path, ...]


def _bounded(number: int) -> int | None:
    """*number*, or None when it is 0 or past the largest a tag is read as holding."""
    return number if 0 < number <= LARGEST_NUMBER else None


def row_tags(row: TrackRow) -> FileTags:
    """The tags a listed track says its file holds.

    The row's artist is already the album artist, else the artist, as a file's is.
    A track number of 0 is no track number, and the row has no track count. A number
    past `LARGEST_NUMBER` is no number, as in a file's tag, so one stray row cannot
    make the gap check enumerate millions of missing numbers.
    """
    return FileTags(
        row.artist,
        row.album,
        _bounded(row.disc) or _FIRST_DISC,
        _bounded(row.track),
        None,
        row.compilation,
    )


def _tags_of(
    audio: AudioFile,
    reader: TagReader,
    matched: Mapping[FileKey, tuple[TrackRow, ...]],
) -> FileTags | None:
    """*audio*'s tags: read from the file, or for a placeholder from its first track.

    None for a file whose tags cannot be read, and for a placeholder with no track.
    """
    if not audio.dataless:
        return reader(audio.path)
    rows = matched.get(audio.key, ())
    # Several rows mean a duplicate in Music.app; the first in listing order names the
    # group, and the counts are unaffected since every row counts toward this file's group.
    return row_tags(rows[0]) if rows else None


def read_library_tags(
    files: Sequence[AudioFile],
    reader: TagReader,
    matched: Mapping[FileKey, tuple[TrackRow, ...]],
) -> ReadTags:
    """Each file's tags; the unreadable ones and the unnumbered ones, in path order.

    A placeholder is never opened: see the module docstring.
    """
    tags: dict[Path, FileTags] = {}
    unreadable: list[Path] = []
    for audio in files:
        read = _tags_of(audio, reader, matched)
        if read is not None:
            tags[audio.path] = read
        elif not audio.dataless:
            unreadable.append(audio.path)
    unnumbered = tuple(path for path, read in tags.items() if read.track is None)
    return ReadTags(tags, tuple(unreadable), unnumbered)
