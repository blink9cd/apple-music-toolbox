"""Shared fixtures for the play_count_baseline suites: a fake Music.app and invented tracks.

`FakeMusic` is the `Runner` a test hands the tool in place of ``osascript``. It
recognizes the three scripts the tool sends (the ``is running`` probe, the count, and
the play-count listing) by their text, answers from a list of invented `RawTrack`s
rendered in the listing's row format, and records every argv, so a test can assert
what was asked and that nothing but a read was ever sent. Nothing here spawns a
process, so no test can reach Music.app, the real library, or the host.

Not discovered as a suite (no ``test_`` prefix). Suites import it by bare name with
this directory on ``sys.path``.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import baseline_calls  # noqa: E402 - import follows the sys.path bootstrap above
import baseline_rows  # noqa: E402 - import follows the sys.path bootstrap above
import music_calls  # noqa: E402 - baseline_calls put tag_refresh's src/ on sys.path

#: The kind of each script, the key a canned answer is filed under.
IS_RUNNING, COUNT, LIST = "is_running", "count", "list"
_KINDS = {
    music_calls.IS_RUNNING_SCRIPT: IS_RUNNING,
    music_calls.COUNT_TRACKS_SCRIPT: COUNT,
    baseline_calls.PLAY_COUNTS_SCRIPT: LIST,
}
#: Where a script's own arguments start in an argv: ``osascript -e <script> --``.
_ARGS_START = 4

Answer = subprocess.CompletedProcess[str] | BaseException

#: One invented track with every field set, a file track played on an invented date.
INVENTED_TRACK = baseline_rows.RawTrack(
    persistent_id="0123456789ABCDEF",
    name="Invented Song",
    artist="The Placeholder Band",
    album="Invented Album",
    album_artist="Placeholder Collective",
    disc_number=1,
    duration_ms=215000,
    played_count=7,
    played_date="2024/3/9/45296",
    genre="Invented Genre",
    year=2001,
    path="/Invented/Library/Invented Song.m4a",
)


def completed(
    stdout: str = "", *, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """A finished ``osascript`` with the given streams and exit status."""
    return subprocess.CompletedProcess(["osascript"], returncode, stdout, stderr)


def row_of(track: baseline_rows.RawTrack) -> str:
    """The listing row Music would print for *track*, its linefeed included."""
    fields = (
        track.persistent_id,
        track.name,
        track.artist,
        track.album,
        track.album_artist,
        str(track.disc_number),
        "" if track.duration_ms is None else str(track.duration_ms),
        str(track.played_count),
        track.played_date,
        track.genre,
        str(track.year),
        track.path,
    )
    return "\t".join(fields) + "\n"


class FakeMusic:
    """A `Runner` playing ``osascript`` and Music.app from invented tracks.

    ``answers`` maps ``(kind, n)`` to what the n-th call (1-based) of that kind answers
    instead: a `CompletedProcess`, or an exception to raise (a kill, a Ctrl-C).
    """

    def __init__(
        self,
        *,
        running: bool = True,
        tracks: Iterable[baseline_rows.RawTrack] = (),
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
        return "".join(row_of(t) for t in self.tracks[first - 1 : last]) + "\n"

    def kinds(self) -> list[str]:
        """The kind of every call made, in order."""
        return [_KINDS[argv[2]] for argv in self.calls]
