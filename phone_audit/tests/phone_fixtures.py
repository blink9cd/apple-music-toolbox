"""Shared fixtures for the phone_audit suites: an invented phone, wiring, a captured run.

`FakePhone` is the `Runner` every CLI test hands the entry point in place of the real
``afcclient``. It answers the commands the audit sends (``-v``, ``ls -l``, ``get``) in
afcclient 1.4.0's own output format, from an invented phone: a music database built
here from SQL text, and ``Fnn`` folders of invented files. It records every argv, so a
test can assert that nothing but a read was ever sent. Nothing here spawns a process,
so no test can reach a phone.

The database is built by `database_bytes` from `fixture_sql`, the same SQL shape the
samples folder commits as text: no binary fixture is ever committed.

Not discovered as a suite (no ``test_`` prefix). Suites import it by bare name with
this directory on ``sys.path``.
"""

from __future__ import annotations

import contextlib
import io
import sqlite3
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent), str(_HERE.parent / "src")]

import phone_audit as pa  # noqa: E402 - import follows the sys.path bootstrap above

#: Where the fake binary is said to live: never a real path, never run.
BINARY = "/fake/bin/afcclient"
#: The phone's music database and its folders, as the tool names them: relative to the
#: AFC service's root, which is the device's ``/var/mobile/Media``. The fake serves these
#: paths alone, so a tool asking for the device-absolute form finds nothing.
DB_REMOTE = "/iTunes_Control/iTunes/MediaLibrary.sqlitedb"
MUSIC = "/iTunes_Control/Music"
#: The names an invented row carries unless told otherwise.
BAND, ALBUM = "The Placeholder Band", "Invented Album"
#: The exit codes, as the companion doc names them.
OK, FINDINGS, USAGE, INTERRUPTED = 0, 1, 2, 130
#: afcclient's line for a path the phone does not have (AFC_E_OBJECT_NOT_FOUND).
NOT_FOUND = "Error: Failed to read from file '{path}': Not found (8)\n"
LS_NOT_FOUND = "Error: Failed to list '{path}': Not found (8)\n"
#: What afcclient prints on stdout when the phone is unplugged mid-command; it exits 0.
DISCONNECTED = "\n[disconnected]\n"
#: A fixed modification time for every listed entry: the tool never reads it.
_STAMP = "26 Oct 2026 13:01:02"

Answer = subprocess.CompletedProcess[str] | BaseException


# --- The database ----------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """One invented track row: where its file is, and what names it.

    ``base`` is the base location's path, None for a row with no base location at all;
    ``location`` the file name in it, None for a row with no ``item_extra`` name.
    """

    pid: int
    base: str | None
    location: str | None
    size: int | None
    title: str = "Invented Title"
    disc: int = 1
    track: int = 1
    album: str | None = ALBUM
    artist: str | None = BAND


#: The schema, the columns the tool reads under the names the phone's own database uses.
SCHEMA = """\
CREATE TABLE base_location (base_location_id INTEGER PRIMARY KEY, path TEXT);
CREATE TABLE item (item_pid INTEGER PRIMARY KEY, base_location_id INTEGER,
  album_pid INTEGER, item_artist_pid INTEGER, disc_number INTEGER, track_number INTEGER);
CREATE TABLE item_extra (item_pid INTEGER PRIMARY KEY, location TEXT,
  file_size INTEGER, title TEXT);
CREATE TABLE album (album_pid INTEGER PRIMARY KEY, album TEXT);
CREATE TABLE item_artist (item_artist_pid INTEGER PRIMARY KEY, item_artist TEXT);
"""


def _literal(value: str | int | None) -> str:
    """*value* as an SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return "'" + value.replace("'", "''") + "'"


def _ids(values: Iterable[str | None]) -> dict[str, int]:
    """A numeric id for each distinct non-None value, in first-seen order."""
    found: dict[str, int] = {}
    for value in values:
        if value is not None and value not in found:
            found[value] = len(found) + 1
    return found


def fixture_sql(rows: Sequence[Row]) -> str:
    """The SQL text that builds a database holding *rows*."""
    bases = _ids(r.base for r in rows)
    albums = _ids(r.album for r in rows)
    artists = _ids(r.artist for r in rows)
    lines = [SCHEMA]
    lines += [
        f"INSERT INTO base_location VALUES ({n}, {_literal(p)});"
        for p, n in bases.items()
    ]
    lines += [
        f"INSERT INTO album VALUES ({n}, {_literal(a)});" for a, n in albums.items()
    ]
    lines += [
        f"INSERT INTO item_artist VALUES ({n}, {_literal(a)});"
        for a, n in artists.items()
    ]
    for r in rows:
        base_id = bases.get(r.base) if r.base is not None else None
        album_id = albums.get(r.album) if r.album is not None else None
        artist_id = artists.get(r.artist) if r.artist is not None else None
        lines.append(
            f"INSERT INTO item VALUES ({r.pid}, {_literal(base_id)}, {_literal(album_id)},"
            f" {_literal(artist_id)}, {r.disc}, {r.track});"
        )
        if r.location is not None:
            lines.append(
                f"INSERT INTO item_extra VALUES ({r.pid}, {_literal(r.location)},"
                f" {_literal(r.size)}, {_literal(r.title)});"
            )
    return "\n".join(lines) + "\n"


def database_bytes(sql: str) -> bytes:
    """The bytes of a fresh database built from *sql*, in rollback-journal mode."""
    with TemporaryDirectory() as scratch:
        path = Path(scratch) / "built.sqlitedb"
        with contextlib.closing(sqlite3.connect(path)) as connection:
            connection.executescript(sql)
            connection.commit()
        return path.read_bytes()


def base(folder: str) -> str:
    """The base location path of a sync folder, as the phone's database spells it."""
    return f"iTunes_Control/Music/{folder}"


# --- The listing -----------------------------------------------------------------------


def listing_line(name: str, size: int = 0, *, kind: str = "-") -> str:
    """One ``ls -l`` line, byte for byte as afcclient 1.4.0 prints it."""
    mode = {"d": "drwxr-xr-x", "l": "lrwxrwxrwx"}.get(kind, f"{kind}rw-r--r--")
    return f"{mode} {1:4d} mobile mobile {size:10d} {_STAMP} {name}\n"


def zeroed_line(name: str) -> str:
    """The line afcclient prints for *name* when its stat fails: every field zero.

    The time is the epoch in the local zone, so its date varies; the link count of 0 is
    what marks it.
    """
    return f"-rw-r--r-- {0:4d} mobile mobile {0:10d} 01 Jan 1970 00:00:00 {name}\n"


# --- The fake afcclient ----------------------------------------------------------------


def completed(
    stdout: str = "", *, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """A finished ``afcclient`` with the given streams and exit status."""
    return subprocess.CompletedProcess([BINARY], returncode, stdout, stderr)


@dataclass
class FakePhone:
    """An invented phone behind a fake ``afcclient``; records every argv it is handed.

    *database* is the main database's bytes, or a list served one per copy, so a test
    can make it change between the two copies; None leaves the phone without one.
    *side* maps ``-wal`` and ``-shm`` to their bytes; a suffix missing is absent.
    *folders* maps each ``Fnn`` folder to its files' names and sizes. *music_lines* and
    *folder_lines* add raw lines to a listing. *answers* replaces the reply to the nth
    call (from 1) of a command, ``-v`` included, with a result or an exception.

    It serves the AFC-root-relative paths `DB_REMOTE` and `MUSIC` alone; any other path
    is a missing object, answered as afcclient answers one. An unplugged phone is an
    answer of ``completed(DISCONNECTED)``; an entry whose stat failed is a
    `zeroed_line` in *folder_lines*.
    """

    database: bytes | list[bytes] | None = None
    side: Mapping[str, bytes] = field(default_factory=dict)
    folders: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    music_lines: Sequence[str] = ()
    folder_lines: Mapping[str, Sequence[str]] = field(default_factory=dict)
    answers: Mapping[tuple[str, int], Answer] = field(default_factory=dict)
    version: str = "afcclient 1.4.0\n"
    calls: list[list[str]] = field(default_factory=list)
    timeouts: list[float] = field(default_factory=list)
    _database_copies: int = 0

    def __call__(
        self, argv: list[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        """Record *argv*, then answer it as afcclient would."""
        self.calls.append(list(argv))
        self.timeouts.append(timeout)
        command = command_of(argv)
        nth = sum(command_of(a) == command for a in self.calls)
        canned = self.answers.get((command, nth))
        if isinstance(canned, BaseException):
            raise canned
        if canned is not None:
            return canned
        return self._answer(
            command, argv[argv.index("--") + 1 :] if "--" in argv else []
        )

    def _answer(
        self, command: str, args: list[str]
    ) -> subprocess.CompletedProcess[str]:
        """The reply to one command and its arguments."""
        if command == "-v":
            return completed(self.version)
        if command == "ls":
            return completed(self._listing(args[-1]))
        if command == "get":
            return completed(self._get(args[1], Path(args[2])))
        return completed(f"Unknown command '{command}'.\n")

    def _listing(self, path: str) -> str:
        """What ``ls -l`` prints for *path*."""
        if path == MUSIC:
            dirs = [listing_line(f, kind="d") for f in self.folders]
            return "".join([*dirs, *self.music_lines])
        folder = path.rsplit("/", 1)[-1]
        if path == f"{MUSIC}/{folder}" and folder in self.folders:
            files = [listing_line(n, s) for n, s in self.folders[folder].items()]
            return "".join([*files, *self.folder_lines.get(folder, ())])
        return LS_NOT_FOUND.format(path=path)

    def _get(self, remote: str, local: Path) -> str:
        """Copy *remote* to *local* as ``get`` does, refusing to overwrite."""
        data = self._remote_bytes(remote)
        if data is None:
            return NOT_FOUND.format(path=remote)
        if local.exists():
            return f"Error: Failed to overwrite existing file without '-f' option: {local}\n"
        local.write_bytes(data)
        return ""

    def _remote_bytes(self, remote: str) -> bytes | None:
        """The bytes the phone holds at *remote*, or None."""
        if remote == DB_REMOTE:
            if isinstance(self.database, list):
                self._database_copies += 1
                return self.database[min(self._database_copies, len(self.database)) - 1]
            return self.database
        for suffix, data in self.side.items():
            if remote == DB_REMOTE + suffix:
                return data
        return None

    def commands(self) -> list[str]:
        """Each recorded call's command, in order."""
        return [command_of(a) for a in self.calls]


def command_of(argv: Sequence[str]) -> str:
    """The command an argv runs: the word after ``--``, or ``-v``."""
    if "--" in argv:
        return argv[list(argv).index("--") + 1]
    return argv[-1]


def phone_with(
    rows: Sequence[Row], folders: Mapping[str, Mapping[str, int]]
) -> FakePhone:
    """A phone whose database holds *rows* and whose music folders hold *folders*."""
    return FakePhone(database=database_bytes(fixture_sql(rows)), folders=folders)


# --- Running the entry point -------------------------------------------------------------


def wiring(phone: FakePhone, *, found: str | None = BINARY) -> pa.Wiring:
    """The seams of a test run: *phone* as the runner, ``afcclient`` found at *found*."""
    return pa.Wiring(run=phone, which=lambda _name: found)


@dataclass(frozen=True)
class Outcome:
    """A finished `main`: its exit code and what it wrote to each stream."""

    code: int
    stdout: str
    stderr: str


def run_main(argv: Sequence[str], seams: pa.Wiring | None) -> Outcome:
    """Run the entry point with *argv* and *seams*, capturing both streams.

    An ``argparse`` refusal raises ``SystemExit``; its code is returned like any other.
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = pa.main(list(argv), wiring=seams)
        except SystemExit as stop:
            code = int(stop.code or 0)
    return Outcome(code, out.getvalue(), err.getvalue())
