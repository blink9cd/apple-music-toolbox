"""Shared fixtures for the CLI suites: a fake Music.app, wiring, and a captured run.

`FakeMusic` is the `Runner` every CLI test hands the entry point in place of
``osascript``. It recognizes each of the five scripts tag_refresh sends by its text, answers
from an invented library of tracks, and records every argv, so a test can assert what
was asked, in which order, and that nothing was refreshed on a dry run. Nothing here
spawns a process, so no test can reach Music.app, the real library or the host.

The MP3s are made under `refresh_fixtures.TreeCase`'s temporary directory, and an
invented track's path is that file's real path, so the real ``os.stat`` matches a row
to a named MP3 by device and inode exactly as it does live.

Not discovered as a suite (no ``test_`` prefix). Suites import it by bare name with
this directory on ``sys.path``.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent), str(_HERE.parent / "src")]

import tag_refresh as amr  # noqa: E402 - import follows the sys.path bootstrap above
import music_calls  # noqa: E402 - import follows the sys.path bootstrap above
import refresh_core  # noqa: E402 - import follows the sys.path bootstrap above
import refresh_fixtures as rf  # noqa: E402 - import follows the sys.path bootstrap above

#: The kind of each script, the key a canned answer is filed under.
IS_RUNNING, COUNT, REFRESH_RANGE, LOOKUP, REFRESH_IDS = (
    "is_running",
    "count",
    "refresh_range",
    "lookup",
    "refresh_ids",
)
_KINDS = {
    music_calls.IS_RUNNING_SCRIPT: IS_RUNNING,
    music_calls.COUNT_SCRIPT: COUNT,
    music_calls.REFRESH_RANGE_SCRIPT: REFRESH_RANGE,
    music_calls.LOOKUP_SCRIPT: LOOKUP,
    music_calls.REFRESH_IDS_SCRIPT: REFRESH_IDS,
}
#: Where a script's own arguments start in an argv: ``osascript -e <script> --``.
_ARGS_START = 4
#: The platform string the tool runs on.
DARWIN = "darwin"
#: The stderr osascript prints when an Apple event outlives the in-script bound.
TIMED_OUT_STDERR = (
    "0:120: execution error: Music got an error: AppleEvent timed out. (-1712)\n"
)
#: The reason a failing call's stderr gives, and the stderr carrying it.
FAILED_REASON = "0:10: execution error: Music got an error: invented failure. (-10000)"


def completed(
    stdout: str = "", *, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """A finished ``osascript`` with the given streams and exit status."""
    return subprocess.CompletedProcess(["osascript"], returncode, stdout, stderr)


def failed() -> subprocess.CompletedProcess[str]:
    """A call that exits non-zero with `FAILED_REASON`, which is not a timeout."""
    return completed(returncode=1, stderr=FAILED_REASON + "\n")


def killed() -> subprocess.TimeoutExpired:
    """What `bounded_run` raises when its client-side bound kills the call."""
    return subprocess.TimeoutExpired(
        cmd=["osascript"], timeout=music_calls.CALL_TIMEOUT_SECONDS
    )


def pid(number: int) -> str:
    """An invented 16-digit persistent ID, uppercase as Music reports it."""
    return f"{number:016X}"


@dataclass(frozen=True)
class Track:
    """One invented file track: Music's id, its persistent ID, its album, its file."""

    track_id: int
    persistent_id: str
    album: str
    path: Path


Answer = subprocess.CompletedProcess[str] | BaseException


def interrupt_notice(nth: int) -> mock.Mock:
    """A stand-in for the entry point's stderr notice raising Ctrl-C on its *nth* call.

    Progress lines are notices, so patched over ``_notice`` this lands the signal
    between two calls rather than inside one, where no runner can put it.
    """
    calls = 0

    def _notice(_text: str) -> None:
        nonlocal calls
        calls += 1
        if calls == nth:
            raise KeyboardInterrupt

    return mock.Mock(side_effect=_notice)


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
        file_tracks: int = 0,
        answers: Mapping[tuple[str, int], Answer] | None = None,
    ) -> None:
        """Hold the library and the canned answers; record nothing yet."""
        self.running = running
        self.tracks = tuple(tracks)
        self.file_tracks = file_tracks
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
            return f"{self.file_tracks}\n"
        if kind == LOOKUP:
            rows = (
                f"{t.track_id}\t{t.persistent_id}\t{t.path}\n"
                for t in self.tracks
                if t.album in args
            )
            return "".join(rows) + "\n"
        if kind == REFRESH_IDS:
            known = {(str(t.track_id), t.persistent_id) for t in self.tracks}
            pairs = list(zip(args[::2], args[1::2], strict=True))
            fresh = sum(1 for pair in pairs if pair in known)
            return f"{fresh}\t{len(pairs) - fresh}\n"
        return "\n"

    def kinds(self) -> list[str]:
        """The kind of every call made, in order."""
        return [_KINDS[argv[2]] for argv in self.calls]

    def args_of(self, kind: str) -> list[list[str]]:
        """The script arguments of every call of *kind*, in order."""
        return [argv[_ARGS_START:] for argv in self.calls if _KINDS[argv[2]] == kind]


def wiring(
    music: FakeMusic,
    *,
    platform: str = DARWIN,
    tag_reader: refresh_core.TagReader | None = None,
    stdin: bytes = b"",
) -> amr.Wiring:
    """The entry point's wiring with *music* as the runner and the real ``os.stat``."""
    return amr.Wiring(
        run=music,
        stat=os.stat,
        platform=platform,
        tag_reader=tag_reader,
        read_stdin=lambda: stdin,
    )


@dataclass(frozen=True)
class Outcome:
    """A finished `main`: its exit code and what it wrote to each stream."""

    code: int
    stdout: str
    stderr: str


def run_main(argv: Sequence[str], seams: amr.Wiring | None) -> Outcome:
    """Run the entry point with *argv* and *seams*, capturing both streams.

    An ``argparse`` refusal raises ``SystemExit``; its code is returned like any other.
    *seams* None runs with the real wiring, which a test patches first.
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = amr.main(list(argv), wiring=seams)
        except SystemExit as stop:
            code = int(stop.code or 0)
    return Outcome(code, out.getvalue(), err.getvalue())


class CliCase(rf.TreeCase):
    """A temporary tree, with helpers that make invented albums of placeholder MP3s."""

    def album(self, relative: str, *names: str) -> list[Path]:
        """Make one placeholder MP3 per name under *relative*; return their paths."""
        return [self.touch(f"{relative}/{name}") for name in names]

    def list_file(self, *paths: Path | str) -> Path:
        """Write a list file naming *paths*, one per line, under the root; return it."""
        target = self.root / "changed.txt"
        target.write_bytes(rf.list_bytes(*(str(path) for path in paths)))
        return target
