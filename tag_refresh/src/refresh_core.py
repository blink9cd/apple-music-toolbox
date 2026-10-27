"""The pure core of tag_refresh: what to refresh, what to ask Music, what matched.

Nothing here talks to Music.app, runs a process or prints. It collects the MP3s the
explicit sources name (``--track``, ``--album`` and list files), groups them by album
folder with the names to ask Music for, and cuts the whole library into refresh
batches; parsing the lookup's reply and matching it to these MP3s is `refresh_match`. Every reach outside the process is a seam the caller passes:
``stat`` for the file system checks, and a tag reader for the album tag, which is
``None`` when mutagen cannot be imported.

A list file's bytes are handed in already read, so standard input and a file share one
parser, and an unreadable list stays the caller's exit-2 case. An empty collection is
the caller's to refuse too: this module only reports what it found and why it skipped
the rest.
"""

from __future__ import annotations

import os
import stat as stat_mode
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

#: A file's identity: ``(st_dev, st_ino)``. Paths never match as strings, because Music
#: reports the resolved, iCloud Drive form of a path the caller named another way.
FileKey = tuple[int, int]
#: The stat seam: ``os.stat`` outside tests.
StatFn = Callable[[str], os.stat_result]
#: The album tag reader: the tag's text, or None when there is none or it cannot be read.
#: A reader catches its own errors and returns None: nothing here guards the call.
TagReader = Callable[[Path], str | None]

#: Whole-library refresh batch size. Measured on a library of about 21,000 file tracks:
#: one call refreshing tracks 101-600 took 4.04 s, about 8 ms a track,
#: well inside the 30 s in-script bound, so the library takes about 3 minutes.
BATCH_TRACKS = 500

#: The source label of a ``--track`` problem.
SOURCE_TRACK = "--track"
#: The source label of an ``--album`` problem.
SOURCE_ALBUM = "--album"

#: Why a path was skipped, one constant per reason so the caller's report can test them.
REASON_RELATIVE = "not an absolute path"
REASON_NOT_UTF8 = "not UTF-8"
REASON_NUL = "holds a NUL"
REASON_UNTERMINATED = "not ended by a linefeed"
REASON_CRLF = "ends in a carriage return (a CRLF line ending)"
REASON_NOT_A_FILE = "not a file"
REASON_NOT_MP3 = "not an MP3"
REASON_NOT_A_FOLDER = "not a folder"
REASON_UNREADABLE = "cannot be read"
REASON_NO_MP3 = "holds no MP3"
REASON_ALREADY_WALKED = "reaches a folder already walked"

#: The only suffix collected, compared without case.
_MP3_SUFFIX = ".mp3"
#: A name starting with this is hidden: skipped as a folder, and as a file (``._x.mp3``
#: is the AppleDouble resource fork a copy to a foreign volume leaves beside ``x.mp3``).
_HIDDEN_PREFIX = "."
#: The one list-line terminator. Never ``splitlines``, which also breaks on
#: ``\v \f \x1c-\x1e \x85 U+2028 U+2029`` and so would split a path holding one.
_TERMINATOR = "\n"
_TERMINATOR_BYTE = b"\n"
_NUL = "\x00"
_NUL_BYTE = b"\x00"
_CR = "\r"


@dataclass(frozen=True)
class Problem:
    """One skipped argument or list line: where it came from, what it was, and why.

    ``source`` is ``--track``, ``--album`` or the list's own label; ``line`` is the
    1-based list line, or None for a command-line argument; ``subject`` is the path
    text, empty when the line could not be decoded or held a NUL.
    """

    source: str
    line: int | None
    subject: str
    reason: str


@dataclass(frozen=True)
class Mp3:
    """A collected MP3: the path it was first named by, and its device and inode.

    ``aliases`` are the other paths that named the same file, in naming order: a hard
    link, a symlink, or a list line beside an ``--album``. Album names come from all.
    """

    path: Path
    key: FileKey
    aliases: tuple[Path, ...] = ()


@dataclass(frozen=True)
class Collected:
    """Every MP3 the sources named, each once, and every problem met collecting them."""

    mp3s: tuple[Mp3, ...]
    problems: tuple[Problem, ...]


@dataclass(frozen=True)
class ListSource:
    """A list file's bytes, already read, and the label its problems carry."""

    label: str
    data: bytes


@dataclass(frozen=True)
class ParsedList:
    """A parsed list: ``(line number, path)`` pairs and the lines skipped."""

    paths: tuple[tuple[int, Path], ...]
    problems: tuple[Problem, ...]


@dataclass(frozen=True)
class AlbumGroup:
    """The MP3s of one album folder, and the album names to ask Music for."""

    folder: Path
    mp3s: tuple[Mp3, ...]
    names: tuple[str, ...]


def is_list_path(path: Path) -> bool:
    """Return whether ``path`` has the shape every path `parse_list` returns has."""
    text = str(path)
    return path.is_absolute() and _TERMINATOR not in text and _NUL not in text


def _absolute(path: Path) -> Path:
    """Return ``path`` made absolute and normalized lexically, so no ``..`` survives.

    ``os.path.abspath`` normalizes as it joins. Never ``resolve``: album names are read
    from the components, and a symlink's target would replace the folder's own name.
    """
    return Path(os.path.abspath(path))


def _parse_list_line(raw: bytes, label: str, line: int) -> Path | Problem | None:
    """Return one terminated list line's path, its problem, or None when blank."""
    if _NUL_BYTE in raw:
        return Problem(label, line, "", REASON_NUL)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return Problem(label, line, "", REASON_NOT_UTF8)
    if not text.strip():
        return None
    if text.endswith(_CR):
        # A list saved with CRLF endings: every line keeps a CR no file name holds.
        return Problem(label, line, text.rstrip(_CR), REASON_CRLF)
    if not Path(text).is_absolute():
        return Problem(label, line, text, REASON_RELATIVE)
    return Path(os.path.normpath(text))


# fuzz-target
def parse_list(data: bytes, label: str) -> ParsedList:
    """Parse a list file's bytes into absolute paths, reporting each skipped line.

    The contract: UTF-8, one absolute path per line, each line ended by a linefeed,
    blank lines skipped, each path normalized lexically. A relative path, an
    undecodable line, a NUL, a CRLF ending, or a last line with no linefeed (a writer
    stopped mid-line) is reported by line number and skipped; nothing raises. Parsed from bytes, so a decoding failure is one line's,
    never the whole file's.
    """
    *terminated, tail = data.split(_TERMINATOR_BYTE)
    paths: list[tuple[int, Path]] = []
    problems: list[Problem] = []
    for line, raw in enumerate(terminated, start=1):
        parsed = _parse_list_line(raw, label, line)
        if isinstance(parsed, Path):
            paths.append((line, parsed))
        elif parsed is not None:
            problems.append(parsed)
    if tail:
        subject = tail.decode("utf-8", errors="replace").replace(_NUL, "")
        problems.append(
            Problem(label, len(terminated) + 1, subject, REASON_UNTERMINATED)
        )
    return ParsedList(tuple(paths), tuple(problems))


def _is_mp3_name(name: str) -> bool:
    """Return whether a file name is a visible ``.mp3``, compared without case."""
    return not name.startswith(_HIDDEN_PREFIX) and name.lower().endswith(_MP3_SUFFIX)


def _mp3_key(path: Path, stat: StatFn) -> FileKey | str:
    """Return the key of the MP3 at ``path``, or the reason it is not one."""
    try:
        info = stat(str(path))
    except (OSError, ValueError):
        return REASON_NOT_A_FILE
    if not stat_mode.S_ISREG(info.st_mode):
        return REASON_NOT_A_FILE
    if not path.name.lower().endswith(_MP3_SUFFIX):
        return REASON_NOT_MP3
    return info.st_dev, info.st_ino


def _folder_key(path: str, stat: StatFn) -> FileKey | None:
    """Return the key of the folder ``path`` reaches, or None when it reaches none."""
    try:
        info = stat(path)
    except (OSError, ValueError):
        return None
    if not stat_mode.S_ISDIR(info.st_mode):
        return None
    return info.st_dev, info.st_ino


def _admit_folders(
    folder: str,
    dirnames: Iterable[str],
    walk: tuple[set[FileKey], StatFn, list[Problem]],
) -> list[str]:
    """Return the visible subfolders of ``folder`` to enter, in name order.

    ``walk`` is the walk's visited keys, stat seam and problems. Links are followed, so
    a folder reached a second time (a link back up the tree, or two links to one
    place) is reported and not entered again: that is what ends a loop. One that
    cannot be stated is reported too, never skipped silently.
    """
    visited, stat, problems = walk
    admitted: list[str] = []
    for name in sorted(d for d in dirnames if not d.startswith(_HIDDEN_PREFIX)):
        path = os.path.join(folder, name)
        key = _folder_key(path, stat)
        if key is None:
            problems.append(Problem(SOURCE_ALBUM, None, path, REASON_UNREADABLE))
        elif key in visited:
            problems.append(Problem(SOURCE_ALBUM, None, path, REASON_ALREADY_WALKED))
        else:
            visited.add(key)
            admitted.append(name)
    return admitted


def _walk_album(
    album: Path, key: FileKey, stat: StatFn, problems: list[Problem]
) -> list[Path]:
    """Return every visible MP3 under ``album`` (whose key is ``key``), sorted per folder.

    Hidden folders are pruned, so a ``Disc 1`` / ``Disc 2`` album is walked whole and
    a ``.trash`` beside it is not. Linked subfolders are walked, each folder once. A
    subfolder that cannot be read is reported.
    """

    def _report(error: OSError) -> None:
        problems.append(
            Problem(SOURCE_ALBUM, None, str(error.filename), REASON_UNREADABLE)
        )

    walk = ({key}, stat, problems)
    found: list[Path] = []
    for folder, dirnames, filenames in os.walk(
        album, onerror=_report, followlinks=True
    ):
        dirnames[:] = _admit_folders(folder, dirnames, walk)
        found.extend(
            Path(folder) / name for name in sorted(filenames) if _is_mp3_name(name)
        )
    return found


def _named_paths(
    tracks: Sequence[Path],
    albums: Sequence[Path],
    lists: Sequence[ListSource],
    stat: StatFn,
    problems: list[Problem],
) -> Iterable[tuple[str, int | None, Path]]:
    """Yield ``(source, line, path)`` for every path the sources name, in order."""
    for track in tracks:
        yield SOURCE_TRACK, None, _absolute(track)
    for album in albums:
        folder = _absolute(album)
        key = _folder_key(str(folder), stat)
        if key is None:
            problems.append(
                Problem(SOURCE_ALBUM, None, str(folder), REASON_NOT_A_FOLDER)
            )
            continue
        found = _walk_album(folder, key, stat, problems)
        if not found:
            problems.append(Problem(SOURCE_ALBUM, None, str(folder), REASON_NO_MP3))
        for path in found:
            yield SOURCE_ALBUM, None, path
    for source in lists:
        parsed = parse_list(source.data, source.label)
        problems.extend(parsed.problems)
        for line, path in parsed.paths:
            yield source.label, line, path


def collect_mp3s(
    *,
    tracks: Sequence[Path] = (),
    albums: Sequence[Path] = (),
    lists: Sequence[ListSource] = (),
    stat: StatFn = os.stat,
) -> Collected:
    """Collect the MP3s the explicit sources name, each file once, with the problems.

    ``tracks`` are single MP3s, ``albums`` folders walked recursively, ``lists`` list
    files' bytes. A path that is not a regular file or not an ``.mp3`` is reported, by
    line number for a list, and so is an album folder holding no MP3. The sources are
    united by ``(st_dev, st_ino)``, so a file named twice, or reached through a link,
    appears once, first-named first, with its other paths kept as its ``aliases``.
    """
    problems: list[Problem] = []
    named: dict[FileKey, dict[Path, None]] = {}
    for source, line, path in _named_paths(tracks, albums, lists, stat, problems):
        found = _mp3_key(path, stat)
        if isinstance(found, str):
            problems.append(Problem(source, line, str(path), found))
        else:
            named.setdefault(found, {})[path] = None
    mp3s = (_mp3_of(key, tuple(paths)) for key, paths in named.items())
    return Collected(tuple(mp3s), tuple(problems))


def _mp3_of(key: FileKey, paths: tuple[Path, ...]) -> Mp3:
    """Return the MP3 with this key, named first by ``paths[0]`` and then the rest."""
    return Mp3(paths[0], key, paths[1:])


def _names_of(mp3: Mp3, tag_reader: TagReader | None) -> Iterable[str]:
    """Yield the album names one MP3 suggests: each path's folder and its parent, its tag."""
    for path in (mp3.path, *mp3.aliases):
        yield path.parent.name
        yield path.parent.parent.name
    if tag_reader is not None:
        tag = tag_reader(mp3.path)
        if tag is not None:
            yield tag


def _unique_names(mp3s: Sequence[Mp3], tag_reader: TagReader | None) -> tuple[str, ...]:
    """Return every usable name the MP3s suggest, once each, first-seen first.

    An empty name is dropped, and so is one holding a NUL: mutagen joins several album
    values with one, and a NUL cannot cross to the lookup as a process argument.
    """
    names = (name for mp3 in mp3s for name in _names_of(mp3, tag_reader))
    return tuple(dict.fromkeys(name for name in names if name and _NUL not in name))


def group_albums(
    mp3s: Sequence[Mp3], *, tag_reader: TagReader | None
) -> tuple[AlbumGroup, ...]:
    """Group the MP3s by their folder, with the album names to ask Music for each.

    The names are, for every path that named an MP3, its folder name and its parent
    folder's name (a ``Disc 1`` folder's parent is the album), plus its album tag when ``tag_reader`` is given;
    pass None when mutagen cannot be imported. A wrong name only finds nothing, so
    every plausible one is asked. Groups keep their folder's first-seen order.
    """
    by_folder: dict[Path, list[Mp3]] = {}
    for mp3 in mp3s:
        by_folder.setdefault(mp3.path.parent, []).append(mp3)
    return tuple(
        AlbumGroup(folder, tuple(members), _unique_names(members, tag_reader))
        for folder, members in by_folder.items()
    )


def batch_ranges(
    total: int, *, size: int = BATCH_TRACKS
) -> tuple[tuple[int, int], ...]:
    """Return 1-based inclusive ``(first, last)`` ranges of ``size`` covering ``total``.

    The form ``file tracks i thru j of library playlist 1`` takes. Zero tracks make no
    range; a negative total or a size below one is a caller's bug, so it raises.
    """
    if total < 0 or size < 1:
        raise ValueError(f"no batches for total={total}, size={size}")
    return tuple(
        (first, min(first + size - 1, total)) for first in range(1, total + 1, size)
    )
