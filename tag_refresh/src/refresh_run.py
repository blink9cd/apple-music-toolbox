"""The two refresh runs: the whole library in batches, and named album folders by id.

Each run drives `music_calls` through the `Runner` it is handed and returns what it
did as a frozen record; nothing here prints, so the entry point owns both streams and
the progress callback is how a run reports as it goes. The rules both runs keep:

- **A timeout ends the run.** `CallTimedOut` means Music is still working on the
  abandoned request (measured: about 20 s after a killed call), so the next call
  would queue behind it. The record names what was not refreshed: the track range
  from the batch that timed out, or the album folder in hand and every one after it.
  A folder whose refresh call timed out is recorded as maybe partly refreshed, since
  Music may have begun it.
- **A failure is local.** `CallFailed` on one batch or one album is that batch's or
  that album's error, and the run goes on.
- **Ctrl-C ends the run with a record.** A ``KeyboardInterrupt`` anywhere in a run,
  during a call or between two, is caught here, so the report still covers every
  call that finished before it. Only one before the run starts reaches the caller.

The ``is running`` probe is not here: the entry point asks it before either run starts.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import music_calls
import refresh_core
import refresh_match


class Stop(enum.Enum):
    """How a run ended."""

    FINISHED = "finished"
    TIMED_OUT = "timed out"
    INTERRUPTED = "interrupted"


#: The progress callback: one line of text per batch or album, written by the caller.
Progress = Callable[[str], None]


@dataclass(frozen=True)
class Seams:
    """What a run reaches out through: the call runner, ``stat``, and progress."""

    run: music_calls.Runner
    stat: refresh_core.StatFn
    progress: Progress


@dataclass(frozen=True)
class BatchFailure:
    """One batch whose refresh call failed: its 1-based inclusive range, and why."""

    first: int
    last: int
    reason: str


@dataclass(frozen=True)
class LibraryRun:
    """What ``--whole-library`` did.

    ``total`` is None when the count never answered. ``refreshed`` counts the tracks
    of every batch whose call succeeded (on a dry run, every track counted).
    ``unrefreshed`` is the range a stop left, None when the run did not stop inside
    the batches or the stop left none. ``reason`` is the timeout's text, empty otherwise.
    """

    total: int | None
    batches: int
    refreshed: int
    failures: tuple[BatchFailure, ...]
    count_error: str | None
    unrefreshed: tuple[int, int] | None
    stop: Stop
    reason: str


@dataclass(frozen=True)
class AlbumOutcome:
    """What explicit mode did for one album folder.

    ``refreshed`` counts tracks refreshed (on a dry run, the pairs that would be).
    ``error`` is a failed call's reason; ``stopped`` marks a folder a stop left, and
    ``partly`` one of those whose refresh call the stop interrupted, which Music may
    have partly carried out.
    """

    folder: str
    refreshed: int = 0
    stale: int = 0
    not_in_music: tuple[refresh_core.Mp3, ...] = ()
    unparsed: int = 0
    error: str | None = None
    stopped: bool = False
    partly: bool = False


@dataclass(frozen=True)
class AlbumsRun:
    """What explicit mode did: one outcome per album folder, in order, and the stop."""

    albums: tuple[AlbumOutcome, ...]
    mp3s: int
    stop: Stop
    reason: str


def _stop_of(error: music_calls.CallTimedOut | KeyboardInterrupt) -> tuple[Stop, str]:
    """How a run that met *error* stopped, and the reason a timeout gave."""
    if isinstance(error, music_calls.CallTimedOut):
        return Stop.TIMED_OUT, error.reason
    return Stop.INTERRUPTED, ""


# --- The whole library -------------------------------------------------------------


#: One batch whose call ended: its 1-based inclusive range, and the failure's reason,
#: None when it was refreshed.
_Batch = tuple[int, int, str | None]


def _count(seams: Seams) -> int | LibraryRun:
    """The library's file-track count, or the record of a run that ends at the count."""
    try:
        seams.progress("counting the file tracks")
        return music_calls.count_file_tracks(run=seams.run)
    except music_calls.CallFailed as error:
        return LibraryRun(None, 0, 0, (), error.reason, None, Stop.FINISHED, "")
    except (music_calls.CallTimedOut, KeyboardInterrupt) as error:
        return LibraryRun(None, 0, 0, (), None, None, *_stop_of(error))


def _run_batches(
    ranges: Sequence[tuple[int, int]], seams: Seams, ended: list[_Batch]
) -> None:
    """Refresh each range in turn, appending each batch to *ended* as its call ends.

    Each batch is recorded by one append, so wherever a timeout or Ctrl-C lands,
    *ended* holds exactly the batches whose outcome is known.
    """
    for index, (first, last) in enumerate(ranges, start=1):
        seams.progress(f"batch {index}/{len(ranges)}: tracks {first}-{last}")
        try:
            music_calls.refresh_range(first, last, run=seams.run)
        except music_calls.CallFailed as error:
            ended.append((first, last, error.reason))
        else:
            ended.append((first, last, None))


def _library_of(
    total: int, batches: int, ended: Sequence[_Batch], why: tuple[Stop, str]
) -> LibraryRun:
    """The record of a library run whose *ended* batches are known, stopped as *why*.

    A stop leaves the tracks after the last batch that ended, none when it ended last.
    """
    refreshed = sum(last - first + 1 for first, last, reason in ended if reason is None)
    failures = tuple(
        BatchFailure(first, last, reason)
        for first, last, reason in ended
        if reason is not None
    )
    next_first = ended[-1][1] + 1 if ended else 1
    stopped = why[0] is not Stop.FINISHED and next_first <= total
    left = (next_first, total) if stopped else None
    return LibraryRun(total, batches, refreshed, failures, None, left, *why)


def refresh_library(seams: Seams, *, dry_run: bool) -> LibraryRun:
    """Count the file tracks, then refresh them a batch at a time (only count, dry).

    A failed batch is recorded and the next one runs; a timeout or Ctrl-C, wherever it
    lands, stops the run and records the range from the batch in hand to the last track.
    """
    total = _count(seams)
    if isinstance(total, LibraryRun):
        return total
    ranges = refresh_core.batch_ranges(total)
    if dry_run:
        return LibraryRun(total, len(ranges), total, (), None, None, Stop.FINISHED, "")
    ended: list[_Batch] = []
    try:
        _run_batches(ranges, seams, ended)
    except (music_calls.CallTimedOut, KeyboardInterrupt) as error:
        return _library_of(total, len(ranges), ended, _stop_of(error))
    return _library_of(total, len(ranges), ended, (Stop.FINISHED, ""))


# --- Explicit mode -----------------------------------------------------------------


class _StoppedInRefresh(Exception):
    """A timeout or Ctrl-C during a folder's refresh call, which Music may have begun.

    Music goes on working on an abandoned request, so the folder in
    hand may be partly refreshed; this carries the stop out of `_refresh_album` so the
    run can say so.
    """

    def __init__(self, error: music_calls.CallTimedOut | KeyboardInterrupt) -> None:
        """Hold the timeout or Ctrl-C that stopped the refresh call."""
        super().__init__()
        self.error = error


def _pairs_of(matches: refresh_match.Matches) -> tuple[tuple[int, str], ...]:
    """Every matched ``(id, persistent ID)`` pair once, in match order."""
    pairs = (pair for _mp3, found in matches.matched for pair in found)
    return tuple(dict.fromkeys(pairs))


def _refresh_album(
    group: refresh_core.AlbumGroup, seams: Seams, *, dry_run: bool
) -> AlbumOutcome:
    """Look one album folder's names up, match the rows, and refresh the matches.

    A `CallFailed` from either call is this folder's error; a timeout or Ctrl-C
    propagates to the run, which stops, as `_StoppedInRefresh` from the refresh call.
    """
    folder = str(group.folder)
    try:
        reply = music_calls.lookup_by_albums(group.names, run=seams.run)
    except music_calls.CallFailed as error:
        return AlbumOutcome(folder, error=error.reason)
    parsed = refresh_match.parse_rows(reply)
    matches = refresh_match.match_tracks(parsed.rows, group.mp3s, stat=seams.stat)
    pairs = _pairs_of(matches)
    found = AlbumOutcome(folder, len(pairs), 0, matches.not_in_music, parsed.unparsed)
    if dry_run:
        return found
    try:
        # The outcome is built inside the try, so a Ctrl-C landing after the call
        # returned still marks the folder as maybe refreshed, never as untouched.
        counts = music_calls.refresh_ids(pairs, run=seams.run)
        return replace(found, refreshed=counts.refreshed, stale=counts.stale)
    except music_calls.CallFailed as error:
        return replace(found, refreshed=0, error=error.reason)
    except (music_calls.CallTimedOut, KeyboardInterrupt) as error:
        raise _StoppedInRefresh(error) from error


def _albums_stopped(
    done: list[AlbumOutcome],
    left: Sequence[refresh_core.AlbumGroup],
    mp3s: int,
    why: tuple[Stop, str],
    *,
    partly: bool = False,
) -> AlbumsRun:
    """The record of an explicit run that stopped with the folders *left* unfinished.

    *partly* marks the first of them, the folder in hand, as maybe partly refreshed.
    """
    stopped = [AlbumOutcome(str(group.folder), stopped=True) for group in left]
    if partly:
        stopped[0] = replace(stopped[0], partly=True)
    return AlbumsRun(tuple(done + stopped), mp3s, *why)


def _run_albums(
    groups: Sequence[refresh_core.AlbumGroup],
    seams: Seams,
    dry_run: bool,
    done: list[AlbumOutcome],
) -> None:
    """Refresh each album folder in turn, appending each outcome to *done* as it ends.

    Each folder is recorded by one append, so wherever a stop lands, the folders not
    in *done* are exactly the ones it left.
    """
    for index, group in enumerate(groups, start=1):
        seams.progress(f"album {index}/{len(groups)}: {group.folder}")
        done.append(_refresh_album(group, seams, dry_run=dry_run))


def refresh_albums(
    groups: Sequence[refresh_core.AlbumGroup], seams: Seams, *, dry_run: bool
) -> AlbumsRun:
    """Refresh each album folder in turn (only look up and match, dry).

    A timeout or Ctrl-C, wherever it lands, stops the run: the folder in hand and every
    later one are recorded as stopped, the one in hand as maybe partly refreshed when
    the stop came during its refresh call.
    """
    mp3s = sum(len(group.mp3s) for group in groups)
    done: list[AlbumOutcome] = []
    try:
        _run_albums(groups, seams, dry_run, done)
    except _StoppedInRefresh as stop:
        why = _stop_of(stop.error)
        return _albums_stopped(done, groups[len(done) :], mp3s, why, partly=True)
    except (music_calls.CallTimedOut, KeyboardInterrupt) as error:
        return _albums_stopped(done, groups[len(done) :], mp3s, _stop_of(error))
    return AlbumsRun(tuple(done), mp3s, Stop.FINISHED, "")
