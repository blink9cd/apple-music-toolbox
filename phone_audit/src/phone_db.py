"""The phone's music database: copied twice and compared, checked, then read.

The phone's media daemon may write to the database at any moment, and its main file
and ``-wal`` and ``-shm`` files are not copied in one instant, so one copy can be torn.
`load_rows` therefore copies all three twice, each set into its own folder under one
private temporary folder (mode 0700), and refuses to go on unless every file is
present or absent alike in both and hashes the same. It then opens the first copy
read-only, with its ``-wal`` beside it under the same base name (SQLite reads committed
rows from there), and requires ``PRAGMA integrity_check`` to answer exactly ``ok``.
The temporary folder is removed however the load ends.

The copying goes through a `Copier` (the seam's ``copy_file``), so this module never
builds an afcclient argv. A missing ``-wal`` or ``-shm`` is normal; a missing main
database is a refusal.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import shutil
import sqlite3
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from phone_compare import PhoneRow

#: The phone's music database, relative to the AFC service's root, which is the
#: device's ``/var/mobile/Media``; the device-absolute path is not found.
DB_REMOTE = "/iTunes_Control/iTunes/MediaLibrary.sqlitedb"
#: The files SQLite keeps beside it, each of which may be absent.
SIDE_SUFFIXES = ("-wal", "-shm")
#: The two copy folders' names, in order.
_COPY_FOLDERS = ("1", "2")
#: A private folder's mode: readable by the user running the tool, and no one else.
_PRIVATE = 0o700
#: A sync folder's name, the last component of a row's base location path.
SYNC_FOLDER = re.compile(r"F\d{2}", re.ASCII)
#: The one answer of a sound database to ``PRAGMA integrity_check``.
_INTEGRITY_OK = [("ok",)]

#: Every row and what names it. A row's file is ``base_location.path`` + ``/`` +
#: ``item_extra.location``, joined through ``item.base_location_id``, as a read-only
#: probe of a current iPhone's database confirmed; the name columns (title, album,
#: artist, disc and track) are the ones the live smoke test confirms. Every join is a
#: LEFT JOIN, so no row is dropped: one missing a name or a file name is reported with
#: it empty, and one with no base location is counted outside the sync.
ROWS_QUERY = """
SELECT item.item_pid, base_location.path, item_extra.location, item_extra.file_size,
       item_extra.title, item.disc_number, item.track_number,
       album.album, item_artist.item_artist
FROM item
LEFT JOIN item_extra ON item_extra.item_pid = item.item_pid
LEFT JOIN base_location ON base_location.base_location_id = item.base_location_id
LEFT JOIN album ON album.album_pid = item.album_pid
LEFT JOIN item_artist ON item_artist.item_artist_pid = item.item_artist_pid
"""

#: Copies a phone path to a local one: True when copied, False when the phone lacks it.
Copier = Callable[[str, Path], bool]


class DatabaseRefused(Exception):
    """The database copy cannot be trusted or read: the one-line reason."""


@dataclass(frozen=True)
class PhoneRows:
    """The rows in the sync, and how many rows lie outside it."""

    rows: tuple[PhoneRow, ...]
    outside_sync: int


# --- Copying -----------------------------------------------------------------------------


def _remote_names() -> list[str]:
    """The main database and its side files, as phone paths."""
    return [DB_REMOTE, *(DB_REMOTE + s for s in SIDE_SUFFIXES)]


def _digest(path: Path) -> str:
    """*path*'s SHA-256, hex."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _copy_set(copier: Copier, folder: Path) -> dict[str, str | None]:
    """Copy every file into *folder*; each file's name to its digest, None when absent."""
    folder.mkdir(mode=_PRIVATE)
    found: dict[str, str | None] = {}
    for remote in _remote_names():
        local = folder / Path(remote).name
        found[local.name] = _digest(local) if copier(remote, local) else None
    return found


def copy_twice(copier: Copier, scratch: Path, progress: Callable[[str], None]) -> Path:
    """Copy the database twice under *scratch*; return the first copy's main file."""
    sets = []
    for number, name in enumerate(_COPY_FOLDERS, start=1):
        progress(
            f"copying the phone's music database ({number} of {len(_COPY_FOLDERS)})"
        )
        sets.append(_copy_set(copier, scratch / name))
    main = Path(DB_REMOTE).name
    if sets[0][main] is None:
        raise DatabaseRefused(
            f"the phone has no music database at {DB_REMOTE}; has it been synced with this Mac?"
        )
    if sets[0] != sets[1]:
        raise DatabaseRefused(
            "the database changed while it was copied; close Music on the phone and run again"
        )
    return scratch / _COPY_FOLDERS[0] / main


# --- Reading -----------------------------------------------------------------------------


def integrity_problem(answer: Sequence[tuple[object, ...]]) -> str | None:
    """Why ``PRAGMA integrity_check``'s *answer* is not a sound database, or None."""
    if list(answer) == _INTEGRITY_OK:
        return None
    lines = [str(row[0]) if row else "" for row in answer]
    not_ok = [line for line in lines if line != "ok"]
    if not_ok:
        said = not_ok[0]
    elif lines:
        said = f"returned {len(lines)} rows"
    else:
        said = "no answer"
    return f"the copied database failed its integrity check: {said}"


def _text(value: object) -> str:
    """A database value as text: empty for NULL."""
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _number(value: object) -> int:
    """A database value as a whole number: 0 for NULL or anything not an integer."""
    return value if isinstance(value, int) else 0


def _size(value: object) -> int | None:
    """An expected size: None when it is not a positive integer."""
    return value if isinstance(value, int) and value > 0 else None


def _sync_folder(base_path: object) -> str | None:
    """The sync folder a base location path ends in, or None when it is outside the sync."""
    if not isinstance(base_path, str):
        return None
    last = base_path.rstrip("/").rsplit("/", 1)[-1]
    return last if SYNC_FOLDER.fullmatch(last) else None


def rows_of(records: Iterable[Sequence[object]]) -> PhoneRows:
    """`ROWS_QUERY`'s records as rows in the sync, the rest tallied."""
    rows: list[PhoneRow] = []
    outside = 0
    for pid, base, location, size, title, disc, track, album, artist in records:
        folder = _sync_folder(base)
        if folder is None:
            outside += 1
            continue
        rows.append(
            PhoneRow(
                _number(pid),
                folder,
                _text(location),
                _size(size),
                _text(title),
                _number(disc),
                _number(track),
                _text(album),
                _text(artist),
            )
        )
    return PhoneRows(tuple(rows), outside)


def read_rows(path: Path) -> PhoneRows:
    """Open *path* read-only, check its integrity, and read its rows."""
    uri = f"{path.as_uri()}?mode=ro"
    try:
        with contextlib.closing(sqlite3.connect(uri, uri=True)) as connection:
            problem = integrity_problem(
                connection.execute("PRAGMA integrity_check").fetchall()
            )
            if problem is not None:
                raise DatabaseRefused(problem)
            records = connection.execute(ROWS_QUERY).fetchall()
    except sqlite3.DatabaseError as error:
        # A missing table or column: the query names what an iOS release may rename.
        if isinstance(error, sqlite3.OperationalError) and "no such" in str(error):
            raise DatabaseRefused(
                f"the phone's database does not have the expected tables ({error});"
                " its layout may have changed in this iOS release"
            ) from None
        raise DatabaseRefused(f"the copied database cannot be read: {error}") from None
    return rows_of(records)


def load_rows(
    copier: Copier,
    *,
    progress: Callable[[str], None],
    temp_parent: Path | None = None,
) -> PhoneRows:
    """Copy, compare, check and read the phone's database; remove every copy after.

    *temp_parent* is where the private temporary folder is made: the system's
    temporary folder unless a test names another.
    """
    scratch = Path(tempfile.mkdtemp(prefix="phone_audit.", dir=temp_parent))
    try:
        scratch.chmod(_PRIVATE)
        return read_rows(copy_twice(copier, scratch, progress))
    finally:
        # ignore_errors: a cleanup that fails must not replace the error that ended
        # the load, which is the one the caller has to see. Anything left stays in the
        # 0700 folder, under the system's temporary folder.
        shutil.rmtree(scratch, ignore_errors=True)
