"""The report a run prints, and the exit code it ends with.

Pure: each function turns a run's record (`refresh_run`) into text or a code, and the
entry point prints the text. The report's wording is the companion doc's, which shows
an example of each mode; the suites pin it whole.

Every line is shown through `shown`, the shared escape `html_page` owns (the HTML pages
escape their cells with it too), since a file or folder name, or a reason quoted from
``osascript``, is text this tool did not write: a control character in one would break a
row in two, or drive the terminal. tag_refresh's entry point reaches it as
``refresh_report.shown``; the audits import it from ``html_page`` directly.
"""

from __future__ import annotations

from collections.abc import Iterable

import refresh_core
from html_page import shown
from refresh_run import AlbumOutcome, AlbumsRun, LibraryRun, Stop

#: Exit codes: everything done, something not done, could not start, Ctrl-C.
EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

#: The verbs a report counts with: a real run, and a dry run.
_REFRESHED = "refreshed"
_WOULD_REFRESH = "would refresh"
#: The row of a folder or range a stop left.
NOT_REFRESHED = "not refreshed (stopped)"
#: The row of a folder whose refresh call a stop interrupted: Music goes on working on
#: an abandoned request, so some of its tracks may have been refreshed.
PARTLY_REFRESHED = "stopped (may be partly refreshed)"
#: The line naming why a run stopped, for each way it can.
_STOP_LINES = {
    Stop.TIMED_OUT: "stopped at a timeout: {reason}",
    Stop.INTERRUPTED: "stopped: interrupted (Ctrl-C)",
}


def _joined(lines: Iterable[str]) -> str:
    """*lines* shown, each ended by a linefeed."""
    return "".join(f"{shown(line)}\n" for line in lines)


def _verb(dry_run: bool) -> str:
    """How a report counts: what was refreshed, or what would be."""
    return _WOULD_REFRESH if dry_run else _REFRESHED


def _stop_lines(stop: Stop, reason: str) -> list[str]:
    """The line naming why a run stopped, or none when it finished."""
    template = _STOP_LINES.get(stop)
    return [] if template is None else [template.format(reason=reason)]


# --- The whole library -------------------------------------------------------------


def format_library(run: LibraryRun, *, dry_run: bool) -> str:
    """The ``--whole-library`` report: the row, errors, what a stop left, the total."""
    verb = _verb(dry_run)
    lines: list[str] = []
    if run.total is not None:
        lines.append(
            f"whole library: {verb} {run.refreshed} of {run.total} file tracks in {run.batches} batches"
        )
    if run.count_error is not None:
        lines.append(f"error: counting the file tracks: {run.count_error}")
    lines += [f"error: tracks {f.first}-{f.last}: {f.reason}" for f in run.failures]
    if run.stop is not Stop.FINISHED and run.total is None:
        lines.append(f"{NOT_REFRESHED}: every file track")
    elif run.unrefreshed is not None:
        first, last = run.unrefreshed
        lines.append(f"{NOT_REFRESHED}: tracks {first}-{last}")
    lines += _stop_lines(run.stop, run.reason)
    of_total = "" if run.total is None else f" of {run.total}"
    lines.append(f"total: {verb} {run.refreshed}{of_total} file tracks")
    return _joined(lines)


def library_exit_code(run: LibraryRun) -> int:
    """130 for Ctrl-C; 1 for a failed count or batch, or a timeout; else 0."""
    if run.stop is Stop.INTERRUPTED:
        return EXIT_INTERRUPTED
    if run.count_error is not None or run.failures or run.stop is Stop.TIMED_OUT:
        return EXIT_PARTIAL
    return EXIT_OK


# --- Explicit mode -----------------------------------------------------------------


def _album_status(album: AlbumOutcome, verb: str) -> str:
    """One album folder's status: stopped, its error, or what it counted."""
    if album.stopped:
        return PARTLY_REFRESHED if album.partly else NOT_REFRESHED
    if album.error is not None:
        return f"error: {album.error}"
    parts = [f"{verb} {album.refreshed}"]
    counted = (
        ("not in Music", len(album.not_in_music)),
        ("stale", album.stale),
        ("unparsed rows", album.unparsed),
    )
    parts += [f"{label} {count}" for label, count in counted if count]
    return ", ".join(parts)


def _not_in_music(albums: Iterable[AlbumOutcome]) -> list[refresh_core.Mp3]:
    """Every named MP3 no row matched, in report order."""
    return [mp3 for album in albums for mp3 in album.not_in_music]


def _album_total(run: AlbumsRun, verb: str) -> str:
    """The explicit report's total line."""
    albums = run.albums
    counts = (
        f"{verb} {sum(a.refreshed for a in albums)}",
        f"not in Music {len(_not_in_music(albums))}",
        f"stale {sum(a.stale for a in albums)}",
        f"errors {sum(1 for a in albums if a.error is not None)}",
        f"stopped {sum(1 for a in albums if a.stopped)}",
    )
    return f"total: {', '.join(counts)} (album folders {len(albums)}, MP3s {run.mp3s})"


def format_albums(run: AlbumsRun, *, dry_run: bool, hint: str | None) -> str:
    """The explicit report: one row per album folder, the files not in Music, the total.

    *hint* follows the not-in-Music list when one was found; None prints none.
    """
    verb = _verb(dry_run)
    lines = [f"{a.folder}: {_album_status(a, verb)}" for a in run.albums]
    missing = _not_in_music(run.albums)
    if missing:
        lines.append("not in Music:")
        lines += [f"  {mp3.path}" for mp3 in missing]
        if hint is not None:
            lines.append(hint)
    lines += _stop_lines(run.stop, run.reason)
    lines.append(_album_total(run, verb))
    return _joined(lines)


def albums_exit_code(run: AlbumsRun, *, problems: int) -> int:
    """130 for Ctrl-C; 1 for an error, a stale track, a stop or a skipped input; else 0."""
    if run.stop is Stop.INTERRUPTED:
        return EXIT_INTERRUPTED
    albums = run.albums
    if (
        problems
        or run.stop is Stop.TIMED_OUT
        or any(a.error is not None or a.stale for a in albums)
    ):
        return EXIT_PARTIAL
    return EXIT_OK
