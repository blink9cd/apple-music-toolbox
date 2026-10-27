"""The phone's database rows in the sync against the files its sync folders hold. Pure.

A row and a file are the same track when they share the key (sync folder, file name),
compared exactly: the phone's file system is case-sensitive. A row with no file is a
finding, and so is a row whose file is not the size the database expects. A row whose
expected size is unknown (zero or missing in the database) is not judged on size, and
is counted. A file with no row is listed, not a finding: neither a sync nor a read-only
tool can remove it.

Every list comes back sorted, so the same phone gives the same report.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class PhoneRow:
    """One database row in the sync: where its file should be, and what names it.

    *size* is the expected size in bytes, None when the database does not know it.
    """

    item_pid: int
    folder: str
    name: str
    size: int | None
    title: str
    disc: int
    track: int
    album: str
    artist: str


@dataclass(frozen=True)
class PhoneFile:
    """One file listed in a sync folder, and its size in bytes."""

    folder: str
    name: str
    size: int


@dataclass(frozen=True)
class SizeDiffers:
    """A row whose file is there, at another size than the database's."""

    row: PhoneRow
    phone_size: int


@dataclass(frozen=True)
class Compared:
    """What the comparison found, every list sorted."""

    no_file: tuple[PhoneRow, ...]
    size_differs: tuple[SizeDiffers, ...]
    no_row: tuple[PhoneFile, ...]
    sizes_unknown: int


def row_order(row: PhoneRow) -> tuple[str, str, int, int, str, str, str, int]:
    """The report order of rows: artist, album, disc, track, title, then the file."""
    return (
        row.artist,
        row.album,
        row.disc,
        row.track,
        row.title,
        row.folder,
        row.name,
        row.item_pid,
    )


def compare(rows: Iterable[PhoneRow], files: Iterable[PhoneFile]) -> Compared:
    """*rows* against *files*: rows with no file, sizes that differ, files with no row."""
    by_key = {(f.folder, f.name): f for f in files}
    no_file: list[PhoneRow] = []
    differs: list[SizeDiffers] = []
    claimed: set[tuple[str, str]] = set()
    unknown = 0
    for row in rows:
        key = (row.folder, row.name)
        found = by_key.get(key)
        if found is None:
            no_file.append(row)
            continue
        claimed.add(key)
        if row.size is None:
            unknown += 1
        elif row.size != found.size:
            differs.append(SizeDiffers(row, found.size))
    no_row = sorted(
        (f for k, f in by_key.items() if k not in claimed),
        key=lambda f: (f.folder, f.name),
    )
    return Compared(
        tuple(sorted(no_file, key=row_order)),
        tuple(sorted(differs, key=lambda d: row_order(d.row))),
        tuple(no_row),
        unknown,
    )
