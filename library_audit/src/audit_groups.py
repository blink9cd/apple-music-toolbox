"""Which album group each file and each Music.app track counts toward.

An album group is the album artist (else the artist), the album and the disc: a
file's from its tags, a track's from the listing's same three fields. A file or track
flagged as a compilation takes one fixed artist key instead of any artist name, as
Music.app files a compilation, so its tracks' many artists make one album. Both sides
are compared through `normalized`, so a difference of case, of composed against
decomposed accents, or of surrounding spaces is no difference. A file whose tags
cannot be read, and every file when mutagen is absent, falls back to the folder it
sits in, and the report marks such a group ``(by folder)``.

`file_groups` gives each walked file its group; `music_groups` gives the Music.app
side, one group a counted track: every matched track, and every gone one inside the
library folder. A matched track and its file are one item, so the track counts toward
its file's group, whatever album Music.app lists for it. Cloud-only tracks hold no
file, so they are never counted, and nor are tracks outside the library folder, whose
files the walk never saw.

A gone track whose location's parent folder is a walked folder whose every file is
grouped by folder counts toward that folder group; that folder is found by device and
inode, or, when it cannot be stat (it is gone too, say), by its normalized path text.
Otherwise, with tags read, a gone track with no location, or one inside the library
folder, counts toward its listed album, and one outside it is not counted; without mutagen it is not counted either. Inside means
the location's folder, or a folder above it, stats to the library folder's device and
inode, or, failing that, its normalized path text lies under the library folder's.
"""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from audit_rows import TrackRow
from audit_tags import FileTags
from audit_walk import AudioFile
from refresh_core import FileKey, StatFn

__all__ = [
    "COMPILATION_KEY",
    "Group",
    "StatFn",
    "file_groups",
    "folder_group",
    "group_label",
    "group_order",
    "music_groups",
    "normalized",
    "row_group",
    "tag_group",
    "tags_group",
]

#: What the listing script turns into a space inside a name, done to a tag's name too,
#: so both sides of a name holding one compare alike.
_FLATTENED = str.maketrans({"\t": " ", "\n": " ", "\r": " "})
#: Music.app answers disc 0 for a track with no disc number, where a file's absent disc
#: tag reads as disc 1: both are the album's only disc.
_FIRST_DISC = 1
#: How the report marks a group taken from a folder rather than from tags.
_BY_FOLDER = "(by folder)"
#: The artist key every compilation shares. `normalized` strips its result, so no
#: artist name can ever produce this key, which opens with a space.
COMPILATION_KEY = " compilation"
#: The artist a compilation group is shown with, in place of any one track's artist.
_COMPILATION_ARTIST = "(compilation)"


@dataclass(frozen=True)
class Group:
    """One album group: by tags, or by folder when ``folder`` is set.

    Equal by the normalized names, the disc and the folder only; ``artist`` and
    ``album`` are the names as first seen, for the report to show.
    """

    folder: Path | None
    artist_key: str
    album_key: str
    disc: int
    artist: str = field(compare=False)
    album: str = field(compare=False)


def normalized(text: str) -> str:
    """*text* as both sides are compared: flattened, composed, stripped and casefolded."""
    composed = unicodedata.normalize("NFC", text.translate(_FLATTENED)).strip()
    # Casefolding can decompose (a dotted capital I, say), so compose once more.
    return unicodedata.normalize("NFC", composed.casefold())


def tag_group(
    artist: str, album: str, disc: int, *, compilation: bool = False
) -> Group:
    """The group of *artist*'s *album*, disc *disc* (0 read as the first disc).

    A *compilation* takes the shared compilation key, whatever *artist* is.
    """
    if compilation:
        artist_key, artist = COMPILATION_KEY, _COMPILATION_ARTIST
    else:
        artist_key = normalized(artist)
    return Group(
        None, artist_key, normalized(album), disc or _FIRST_DISC, artist, album
    )


def tags_group(tags: FileTags) -> Group:
    """The group a file counts toward, by its read tags."""
    return tag_group(tags.artist, tags.album, tags.disc, compilation=tags.compilation)


def row_group(row: TrackRow) -> Group:
    """The group a listed track counts toward, by its own album fields."""
    return tag_group(row.artist, row.album, row.disc, compilation=row.compilation)


def folder_group(folder: Path) -> Group:
    """The group of the files in *folder*, for when tags cannot say."""
    return Group(folder, "", "", 0, "", "")


def group_order(group: Group) -> tuple[bool, str, str, str, int]:
    """The report order: tag groups by names and disc, then folder groups by path."""
    return (
        group.folder is not None,
        str(group.folder or ""),
        group.artist_key,
        group.album_key,
        group.disc,
    )


def group_label(group: Group) -> str:
    """How the text report names *group*."""
    if group.folder is not None:
        return f"{group.folder} {_BY_FOLDER}"
    return f"{group.artist} / {group.album}, disc {group.disc}"


def file_groups(
    files: Iterable[AudioFile], tags: Mapping[Path, FileTags] | None
) -> dict[Path, Group]:
    """Each file's group: its tags', else its folder; every folder when *tags* is None."""
    groups: dict[Path, Group] = {}
    for audio in files:
        read = None if tags is None else tags.get(audio.path)
        groups[audio.path] = (
            folder_group(audio.path.parent) if read is None else tags_group(read)
        )
    return groups


def _path_text(path: str) -> str:
    """A folder path as text compares: collapsed separators and dots, composed."""
    return unicodedata.normalize("NFC", os.path.normpath(path))


def _stat_key(path: str, stat: StatFn) -> FileKey | None:
    """The device and inode *path* stats to, or None when it cannot be stat."""
    try:
        info = stat(path)
    except (OSError, ValueError):
        # Gone, unreadable, or a path os.stat refuses (a NUL in it).
        return None
    return info.st_dev, info.st_ino


@dataclass(frozen=True)
class _FolderIndex:
    """The walked files' folder groups, by device and inode and by path text."""

    by_key: Mapping[FileKey, Group]
    by_text: Mapping[str, Group]


def _index_folders(groups: Mapping[Path, Group], stat: StatFn) -> _FolderIndex:
    """Index each folder group of *groups* whose folder holds no tag-grouped file.

    A folder holding both kinds is left out: a gone track there is placed by its
    listed album, as the readable files beside it are. Each folder is stat once.
    """
    tagged = {path.parent for path, group in groups.items() if group.folder is None}
    by_key: dict[FileKey, Group] = {}
    by_text: dict[str, Group] = {}
    for group in groups.values():
        if group.folder is None or group.folder in tagged:
            continue
        if str(group.folder) in by_text:
            continue
        by_text[str(group.folder)] = group
        key = _stat_key(str(group.folder), stat)
        if key is not None:
            by_key.setdefault(key, group)
    return _FolderIndex(by_key, {_path_text(t): g for t, g in by_text.items()})


def _gone_folder(row: TrackRow, index: _FolderIndex, stat: StatFn) -> Group | None:
    """The walked folder a gone track's file was in, or None for none of them."""
    if not row.path:
        return None
    parent = os.path.dirname(row.path)
    key = _stat_key(parent, stat)
    if key is None:
        return index.by_text.get(_path_text(parent))
    return index.by_key.get(key)


@dataclass(frozen=True)
class _Library:
    """The library folder, as the containment test compares it."""

    key: FileKey | None
    text: str


def _library(folder: Path, stat: StatFn) -> _Library:
    """*folder*'s device and inode (None when it cannot be stat) and path text."""
    return _Library(_stat_key(str(folder), stat), _path_text(str(folder)))


def _ancestors(folder: str) -> Iterator[str]:
    """*folder*, then each folder above it, up to the root."""
    while True:
        yield folder
        above = os.path.dirname(folder)
        if above == folder:
            return
        folder = above


def _inside(path: str, library: _Library, stat: StatFn) -> bool:
    """Whether a gone track's *path* lies under the library folder.

    By device and inode first: Music.app answers the resolved path, rarely the one the
    library was named by. By the normalized path text when no folder above it matches
    that way (the library itself cannot be stat, say).
    """
    parent = os.path.dirname(path)
    if library.key is not None and any(
        _stat_key(folder, stat) == library.key for folder in _ancestors(parent)
    ):
        return True
    text = _path_text(parent)
    return text == library.text or text.startswith(library.text.rstrip(os.sep) + os.sep)


@dataclass(frozen=True)
class _GonePlacing:
    """What placing a gone track needs: the folder groups, the library, the seam."""

    index: _FolderIndex
    library: _Library
    by_folder: bool
    stat: StatFn


def _gone_group(row: TrackRow, placing: _GonePlacing) -> Group | None:
    """The group a gone track counts toward, or None when it is not counted."""
    folder = _gone_folder(row, placing.index, placing.stat)
    if folder is not None or placing.by_folder:
        return folder
    if row.path and not _inside(row.path, placing.library, placing.stat):
        return None
    return row_group(row)


def music_groups(
    files: Sequence[AudioFile],
    groups: Mapping[Path, Group],
    matched: Mapping[FileKey, tuple[TrackRow, ...]],
    gone: Iterable[TrackRow],
    *,
    library: Path,
    by_folder: bool,
    stat: StatFn,
) -> list[Group]:
    """The Music.app side of the count check: one group a counted track.

    Every matched track counts toward its file's group in *groups*. Each gone track
    is placed as the module docstring says; *by_folder* (no tag reader) counts only
    the gone tracks a walked folder holds.
    """
    found = [groups[audio.path] for audio in files for _ in matched.get(audio.key, ())]
    placing = _GonePlacing(
        _index_folders(groups, stat), _library(library, stat), by_folder, stat
    )
    attributed = (_gone_group(row, placing) for row in gone)
    return found + [group for group in attributed if group is not None]
