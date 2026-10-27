"""The library folder's audio files, and where each Music.app track's file is.

`walk_library` collects every visible audio file under the library folder with its
device and inode, and reports what it could not read instead of skipping it in
silence. `place_tracks` puts each listed track in exactly one place: matched to a
walked file, gone, tallied as cloud-only, or tallied as outside the library folder.

A track is matched to a file by the ``(st_dev, st_ino)`` its own path stats to, never
by the path text: Music answers the resolved path (an iCloud Drive library's real
location, say), which is rarely the one the library folder was named by. ``stat`` and
the walk are the seams, so a test can drive every branch without a real library.
"""

from __future__ import annotations

import os
import stat as stat_module
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from audit_rows import TrackRow
from refresh_core import FileKey, StatFn

#: The suffixes the walk collects, compared without case: what Music.app imports.
#: Not ``.flac``: Music.app does not import FLAC, so a FLAC file would always be
#: reported as having no track, a finding about Music.app nobody can act on.
AUDIO_SUFFIXES = frozenset({".mp3", ".m4a", ".m4p", ".aac", ".aif", ".aiff", ".wav"})
#: The cloud statuses that say a copy of the track exists in the cloud, so a track
#: with no local file and one of these is tallied as cloud-only rather than listed as
#: gone. The text is what Music.app's scripting dictionary names each value. A
#: read-only live run confirmed a status coerces to a word, but saw none of these four
#: (the companion doc, "What a live run confirmed").
CLOUD_COPY_STATUSES = frozenset({"purchased", "matched", "uploaded", "subscription"})
#: The ``st_flags`` bit macOS sets on an iCloud Drive placeholder ("dataless"): its
#: data is not on this Mac, and opening the file makes iCloud download it. The
#: ``stat`` module names it from Python 3.13; this project's floor is older, so the
#: value from macOS's <sys/stat.h> stands in where the module lacks it.
SF_DATALESS: int = getattr(stat_module, "SF_DATALESS", 0x40000000)
#: A name starting with this is hidden: skipped as a folder, and as a file (``._x.mp3``
#: is the AppleDouble resource fork a copy to a foreign volume leaves beside ``x.mp3``).
_HIDDEN_PREFIX = "."

#: Called with each error the walk meets reading a folder.
OnError = Callable[[OSError], None]
#: What the walk yields: ``os.walk``'s ``(folder, subfolders, files)`` triples.
WalkResult = Iterator[tuple[str, list[str], list[str]]]
#: The walk seam: ``os.walk``'s shape, with its error callback.
WalkFn = Callable[[str, OnError], WalkResult]


@dataclass(frozen=True)
class AudioFile:
    """A walked audio file: its path, device and inode, size, and placeholder flag.

    ``size`` is the file's ``st_size`` and ``dataless`` whether it is an iCloud
    placeholder, both from the one ``stat`` the walk takes, so neither opens it.
    """

    path: Path
    key: FileKey
    size: int = 0
    dataless: bool = False


@dataclass(frozen=True)
class Unreadable:
    """A folder the walk could not read, or a file it could not stat, and why."""

    path: Path
    reason: str


@dataclass(frozen=True)
class Walked:
    """Every audio file collected, in path order, and everything that could not be read."""

    files: tuple[AudioFile, ...]
    unreadable: tuple[Unreadable, ...]


@dataclass(frozen=True)
class Placed:
    """Where the listed tracks are.

    ``matched`` maps each walked file's key to the tracks whose file it is, in listing
    order; ``gone`` holds the tracks with no file and no cloud copy. The two counts are
    tallies, never listed.
    """

    matched: Mapping[FileKey, tuple[TrackRow, ...]]
    gone: tuple[TrackRow, ...]
    cloud_only: int
    outside: int


def real_walk(top: str, on_error: OnError) -> WalkResult:
    """``os.walk`` from *top*, top-down, symbolic links to folders not followed."""
    return os.walk(top, onerror=on_error)


def _reason(error: OSError) -> str:
    """One line saying why *error* happened."""
    return error.strerror or str(error) or repr(error)


def _is_audio_name(name: str) -> bool:
    """Whether a file name is a visible audio file, its suffix compared without case."""
    return (
        not name.startswith(_HIDDEN_PREFIX)
        and Path(name).suffix.lower() in AUDIO_SUFFIXES
    )


def _audio_file(path: Path, stat: StatFn) -> AudioFile | Unreadable:
    """The walked file at *path* with its key, or why it could not be stat."""
    try:
        info = stat(str(path))
    except OSError as error:
        return Unreadable(path, _reason(error))
    # st_flags exists on macOS and the BSDs only, and is None on a stat_result built
    # without it: either way no flag is set, so no file there is a placeholder.
    flags = getattr(info, "st_flags", 0) or 0
    return AudioFile(
        path, (info.st_dev, info.st_ino), info.st_size, bool(flags & SF_DATALESS)
    )


def walk_library(library: Path, *, walk: WalkFn, stat: StatFn) -> Walked:
    """Every visible audio file under *library*, hidden folders pruned, in path order."""
    unreadable: list[Unreadable] = []

    def _on_error(error: OSError) -> None:
        unreadable.append(Unreadable(Path(error.filename or library), _reason(error)))

    files: list[AudioFile] = []
    for folder, subfolders, names in walk(str(library), _on_error):
        # Pruned in place, so the walk never descends into a hidden folder.
        subfolders[:] = sorted(
            n for n in subfolders if not n.startswith(_HIDDEN_PREFIX)
        )
        for name in sorted(n for n in names if _is_audio_name(n)):
            found = _audio_file(Path(folder) / name, stat)
            if isinstance(found, AudioFile):
                files.append(found)
            else:
                unreadable.append(found)
    files.sort(key=lambda f: f.path)
    unreadable.sort(key=lambda u: u.path)
    return Walked(tuple(files), tuple(unreadable))


def _track_key(path: str, stat: StatFn) -> FileKey | None:
    """The device and inode a track's *path* stats to; None when empty or gone."""
    if not path:
        return None
    try:
        info = stat(path)
    except (OSError, ValueError):
        # A vanished path is no file, nor is one os.stat refuses (a NUL in it).
        return None
    return info.st_dev, info.st_ino


def place_tracks(
    rows: Iterable[TrackRow], files: Sequence[AudioFile], *, stat: StatFn
) -> Placed:
    """Put each listed track in one place: matched, gone, cloud-only or outside."""
    walked = {f.key for f in files}
    matched: dict[FileKey, list[TrackRow]] = {}
    gone: list[TrackRow] = []
    cloud_only = outside = 0
    for row in rows:
        key = _track_key(row.path, stat)
        if key is None and row.cloud_status in CLOUD_COPY_STATUSES:
            cloud_only += 1
        elif key is None:
            gone.append(row)
        elif key in walked:
            matched.setdefault(key, []).append(row)
        else:
            outside += 1
    return Placed(
        {key: tuple(found) for key, found in matched.items()},
        tuple(gone),
        cloud_only,
        outside,
    )
