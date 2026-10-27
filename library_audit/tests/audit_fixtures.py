"""Shared fixtures for the library_audit suites: a fake Music.app, wiring, a captured run.

`FakeMusic` is the `Runner` every CLI test hands the entry point in place of
``osascript``. It recognizes the three scripts the audit sends (the ``is running``
probe, the count and the listing) by their text, answers from an invented library,
and records every argv, so a test can assert what was asked and that nothing but a
read was ever sent. Nothing here spawns a process, so no test can reach Music.app,
the real library or the host.

`AuditCase` makes the library folder under a fresh temporary directory, and an
invented track's path is a real file's path there, so the real ``os.stat`` matches a
track to a file by device and inode exactly as it does live.

Not discovered as a suite (no ``test_`` prefix). Suites import it by bare name with
this directory on ``sys.path``.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import unittest
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent), str(_HERE.parent / "src")]

import library_audit as la  # noqa: E402 - import follows the sys.path bootstrap above
import audit_sync  # noqa: E402 - import follows the sys.path bootstrap above
import audit_tags  # noqa: E402 - import follows the sys.path bootstrap above
import audit_walk  # noqa: E402 - import follows the sys.path bootstrap above
import music_calls  # noqa: E402 - import follows the sys.path bootstrap above

#: The kind of each script, the key a canned answer is filed under.
IS_RUNNING, COUNT, LIST = "is_running", "count", "list"
_KINDS = {
    music_calls.IS_RUNNING_SCRIPT: IS_RUNNING,
    music_calls.COUNT_TRACKS_SCRIPT: COUNT,
    music_calls.LIST_TRACKS_SCRIPT: LIST,
}
#: Where a script's own arguments start in an argv: ``osascript -e <script> --``.
_ARGS_START = 4
#: The platform string the tool runs on.
DARWIN = "darwin"
#: Invented bytes standing in for an audio file: the audit never decodes audio.
FAKE_AUDIO = b"invented"
#: The names an invented track and an invented file's tags carry unless told otherwise.
BAND, ALBUM = "The Placeholder Band", "Invented Album"
#: The exit codes, as the companion doc names them.
OK, FINDINGS, USAGE, INTERRUPTED = 0, 1, 2, 130

Answer = subprocess.CompletedProcess[str] | BaseException


def completed(
    stdout: str = "", *, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """A finished ``osascript`` with the given streams and exit status."""
    return subprocess.CompletedProcess(["osascript"], returncode, stdout, stderr)


def pid(number: int) -> str:
    """An invented 16-digit persistent ID, uppercase as Music reports it."""
    return f"{number:016X}"


@dataclass(frozen=True)
class Track:
    """One invented track, as the listing reports it.

    ``path`` is the empty string for a track whose location is missing, and for a
    track of any class but ``file track`` (``kind``), which has no location.
    """

    number: int
    path: str
    status: str = "local only"
    album: str = ALBUM
    artist: str = BAND
    disc: int = 1
    track: int = 1
    compilation: bool = False
    kind: str = "file track"
    enabled: bool = True
    size: str = "0"

    def row(self) -> str:
        """The listing row Music would print for this track."""
        fields = (
            pid(self.number),
            self.status,
            str(self.disc),
            str(self.track),
            self.path,
            self.album,
            self.artist,
            "true" if self.compilation else "false",
            self.kind,
            "true" if self.enabled else "false",
            self.size,
        )
        return "\t".join(fields) + "\n"


class FakeMusic:
    """A `Runner` playing ``osascript`` and Music.app from an invented library.

    ``answers`` maps ``(kind, n)`` to what the n-th call (1-based) of that kind answers
    instead: a `CompletedProcess`, or an exception to raise (a kill, a Ctrl-C).
    """

    def __init__(
        self,
        *,
        running: bool = True,
        tracks: Iterable[Track] = (),
        answers: Mapping[tuple[str, int], Answer] | None = None,
    ) -> None:
        """Hold the library and the canned answers; record nothing yet."""
        self.running = running
        self.tracks = tuple(tracks)
        self.answers = dict(answers or {})
        self.calls: list[list[str]] = []

    def __call__(
        self, argv: list[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        """Record the call, then answer it from the canned answers or the library."""
        self.calls.append(list(argv))
        kind = _KINDS[argv[2]]
        canned = self.answers.get((kind, self.kinds().count(kind)))
        if isinstance(canned, BaseException):
            raise canned
        if canned is not None:
            return canned
        return completed(self._answer(kind, argv[_ARGS_START:]))

    def _answer(self, kind: str, args: Sequence[str]) -> str:
        """What Music would print for one call of *kind* with *args*."""
        if kind == IS_RUNNING:
            return "true\n" if self.running else "false\n"
        if kind == COUNT:
            return f"{len(self.tracks)}\n"
        first, last = int(args[0]), int(args[1])
        return "".join(t.row() for t in self.tracks[first - 1 : last]) + "\n"

    def kinds(self) -> list[str]:
        """The kind of every call made, in order."""
        return [_KINDS[argv[2]] for argv in self.calls]

    def args_of(self, kind: str) -> list[list[str]]:
        """The script arguments of every call of *kind*, in order."""
        return [argv[_ARGS_START:] for argv in self.calls if _KINDS[argv[2]] == kind]


def tagged(
    track: int | None,
    total: int | None = None,
    *,
    disc: int = 1,
    artist: str = BAND,
    album: str = ALBUM,
    compilation: bool = False,
) -> audit_tags.FileTags:
    """Invented tags: *track* of *total* on *disc* of *artist*'s *album*."""
    return audit_tags.FileTags(artist, album, disc, track, total, compilation)


def tag_table(
    table: Mapping[Path, audit_tags.FileTags | None],
) -> audit_tags.TagReader:
    """A tag reader answering from *table*; a file absent from it reads as unreadable."""

    def _read(path: Path) -> audit_tags.FileTags | None:
        return table.get(path)

    return _read


def never_decode(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """The decode runner of a run without ``--decode``: any call is a test failure."""
    raise AssertionError(f"decoded without --decode: {argv!r}, {timeout}")


def wiring(
    music: FakeMusic,
    *,
    platform: str = DARWIN,
    tag_reader: audit_tags.TagReader | None = None,
    access: audit_sync.AccessFn = os.access,
    decode: audit_sync.DecodeRunner = never_decode,
) -> la.Wiring:
    """The entry point's wiring: *music* as the runner, the real ``stat`` and walk.

    The real ``os.access`` only asks, and opens nothing; the decode runner never
    starts a process unless a test hands in its own.
    """
    return la.Wiring(
        run=music,
        stat=os.stat,
        platform=platform,
        walk=audit_walk.real_walk,
        tag_reader=tag_reader,
        access=access,
        decode=decode,
    )


@dataclass(frozen=True)
class Outcome:
    """A finished `main`: its exit code and what it wrote to each stream."""

    code: int
    stdout: str
    stderr: str


def run_main(argv: Sequence[str], seams: la.Wiring | None) -> Outcome:
    """Run the entry point with *argv* and *seams*, capturing both streams.

    An ``argparse`` refusal raises ``SystemExit``; its code is returned like any other.
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = la.main(list(argv), wiring=seams)
        except SystemExit as stop:
            code = int(stop.code or 0)
    return Outcome(code, out.getvalue(), err.getvalue())


class AuditCase(unittest.TestCase):
    """A fresh temporary root holding a ``library`` folder, removed when the test ends."""

    def setUp(self) -> None:
        """Make the root and the library; ``resolve`` so walked paths compare equal."""
        super().setUp()
        holder = TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name).resolve()
        self.library = self.root / "library"
        self.library.mkdir()

    def touch(self, relative: str, data: bytes = FAKE_AUDIO) -> Path:
        """Write *data* at *relative* under the root, making its folders; return it."""
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def album(self, relative: str, *names: str) -> list[Path]:
        """One invented audio file per name under ``library/<relative>``."""
        return [self.touch(f"library/{relative}/{name}") for name in names]

    def audit(
        self,
        music: FakeMusic,
        *extra: str,
        tag_reader: audit_tags.TagReader | None = None,
    ) -> Outcome:
        """Run the audit of the library against *music*, with *extra* options."""
        argv = ["--library", str(self.library), *extra]
        return run_main(argv, wiring(music, tag_reader=tag_reader))
