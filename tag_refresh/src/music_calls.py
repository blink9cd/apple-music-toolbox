"""The AppleScript calls tag_refresh and library_audit make to Music.app, each bounded twice.

One function per call, each taking an injected `Runner` (the shape of
`recently_added.Runner`), so every unit test drives a fake and none can reach
Music.app; `real_run` is the real seam, built on `bounded_run`.

1. `is_running` asks `application "Music" is running`, which answers without
   launching the application. It is the only script that names Music outside a
   `tell` block, and the caller asks it before anything else, so Music is never
   launched.
2. `count_file_tracks` counts the file tracks of the library.
3. `refresh_range` refreshes a 1-based inclusive range of them in one call.
4. `lookup_by_albums` returns each track's `id`, persistent ID and POSIX path for the
   tracks whose album is one of the names given, as raw tab-separated rows the caller
   parses (`refresh_match.parse_rows`); this module checks only the exit status.
5. `refresh_ids` refreshes tracks by direct `track id N` reference, each only after
   its persistent ID is confirmed, and returns how many were refreshed and stale.
6. `count_tracks` counts every track of the library, of any class, and
   `list_tracks` reads a 1-based inclusive range of them, one raw tab-separated row a
   track, for library_audit to parse (`audit_rows`). Both only read: library_audit
   never writes to Music.app.

Every value a script needs travels as an `argv` item after `--`, never spliced into
the script text, so a name holding a quote or a backslash needs no escaping and a
name starting with a dash cannot be read as an osascript option. Only this module's
own integer constant,
the in-script bound, is interpolated.

Outcomes: a call returns its value, or raises one of two documented types the caller
turns into its report. `CallTimedOut` means a bound expired: the in-script one
(`with timeout`, which turns one Apple event's late reply into error -1712) or the
client kill of the whole call; it ends the run, because in either case Music is still
working on the abandoned request and the next call would queue behind it. `CallFailed`
is every other failure: a non-zero exit, an osascript that could not start, or a
reply that is not the one shape its script emits. A `ValueError` is a caller's bug
(an impossible range, a malformed id pair), raised before any call is made.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple

# The shared bounded-subprocess runner, at one fixed place: directly under the project
# root, which is this file's great-grandparent, since it sits in the tool's src/. See
# bounded_run/bounded_run.md, "Importing it", and stdio_utf8/stdio_utf8.md for why this
# is not a search upward.
sys.path += [str(Path(__file__).resolve().parents[2] / "bounded_run")]

import bounded_run

# (argv, timeout_seconds) -> completed process: the shape of recently_added's
# `Runner`. Injected so every branch is reachable with no real `osascript`.
Runner = Callable[[list[str], float], "subprocess.CompletedProcess[str]"]

# How long AppleScript waits for the reply to each Apple event the script sends, set
# by `with timeout of`. On expiry the script gets error -1712 and stops, while Music
# goes on with the request: the bound turns one slow event into a typed failure
# instead of a kill, and it does not stop Music. The slowest call worth making was
# measured well under it, on a library of about 21,000 file tracks: a 500-track batch
# refresh took 4.04 s, and 12 tracks by direct `track id` 0.58 s. What it guards is the
# event that never answers: on the same library, a `whose location is` lookup gave no
# answer in 120 s, and the default AppleScript bound is two minutes.
IN_SCRIPT_TIMEOUT_SECONDS = 30

# The client-side kill, through `bounded_run`, which bounds the whole call: the
# in-script bound is per event, and a lookup sends several events per track, so many
# events each under it can still add up past it. Five seconds past the in-script
# bound, so a single slow event's -1712 normally arrives first. Killing the client
# does not stop Music: it stayed busy about 20 s after a killed call, which is
# why either expiry ends the run instead of moving on.
CALL_TIMEOUT_SECONDS = 35.0

# The error number AppleScript reports when an Apple event outlives `with timeout of`.
_APPLE_EVENT_TIMED_OUT = -1712

# The error number osascript prints at the end of its reason line, `... (-1712)`.
# Anchored to the end, so a "(-1712)" quoted earlier in the text (inside a name, say)
# is not mistaken for the error itself.
_TRAILING_ERROR_NUMBER = re.compile(r"\((-?[0-9]+)\)\s*$")

# The ends of a reply: osascript prints the script's result and one linefeed.
_BOOLEAN_REPLY = re.compile(r"(true|false)\n?")
_COUNT_REPLY = re.compile(r"([0-9]+)\n?")
_REFRESH_COUNTS_REPLY = re.compile(r"([0-9]+)\t([0-9]+)\n?")

# A persistent ID as Music.app reports it: sixteen hexadecimal digits. Either case is
# accepted, as AppleScript's `is` compares strings ignoring case anyway.
_PERSISTENT_ID = re.compile(r"[0-9A-Fa-f]{16}")

# How much of an unexpected reply a failure reason quotes.
_REPLY_EXCERPT_CHARS = 60

# Not inside `tell application "Music"`: any such block launches the application.
IS_RUNNING_SCRIPT = 'application "Music" is running'

COUNT_SCRIPT = f"""tell application "Music"
    with timeout of {IN_SCRIPT_TIMEOUT_SECONDS} seconds
        return count of file tracks of library playlist 1
    end timeout
end tell"""

# The count `list_tracks` indexes into: every track of the library playlist, of any
# class, since its ranges are plain `tracks i thru j` (see LIST_TRACKS_SCRIPT).
COUNT_TRACKS_SCRIPT = f"""tell application "Music"
    with timeout of {IN_SCRIPT_TIMEOUT_SECONDS} seconds
        return count of tracks of library playlist 1
    end timeout
end tell"""

# argv: the first and last index, 1-based and inclusive. One `refresh` of the whole
# range is one Apple event (measured: one call for 12 tracks cost 0.32 s, 12 calls
# 2.1 s).
REFRESH_RANGE_SCRIPT = f"""on run argv
    set lowIndex to (item 1 of argv) as integer
    set highIndex to (item 2 of argv) as integer
    tell application "Music"
        with timeout of {IN_SCRIPT_TIMEOUT_SECONDS} seconds
            refresh (file tracks lowIndex thru highIndex of library playlist 1)
        end timeout
    end tell
    return ""
end run"""

# argv: album names. `whose album is` answered in about 0.2 s on a library of about
# 21,000 file tracks, where a lookup by location or persistent ID scans the library;
# each name is bound to a local first, so the filter compares against text rather
# than an argv reference.
# Each track's `location` is read into a local before `POSIX path of`: inside this
# `tell`, `POSIX path of (location of t)` is sent to Music as part of the object
# specifier and Music answered -1728 for every track, where `POSIX path of` a local
# is a coercion of the alias done in the script (verified live, 2026-10-19: no rows
# the first way, 12 well-formed ones this way). The one expected absence, a track
# with no file, reads as `missing value` and is skipped by the `if`. There is no
# `try`: every other error ends the call non-zero, Music's -1712 included, so a
# failure can never read as "these tracks are not in Music".
LOOKUP_SCRIPT = f"""on run argv
    set output to ""
    tell application "Music"
        with timeout of {IN_SCRIPT_TIMEOUT_SECONDS} seconds
            repeat with albumName in argv
                set albumText to contents of albumName
                set albumTracks to (every file track of library playlist 1 whose album is albumText)
                repeat with albumTrack in albumTracks
                    set trackFile to location of albumTrack
                    if trackFile is not missing value then set output to output & ((id of albumTrack) as string) & tab & (persistent ID of albumTrack) & tab & (POSIX path of trackFile) & linefeed
                end repeat
            end repeat
        end timeout
    end tell
    return output
end run"""

# argv: flat pairs of track id and expected persistent ID. `track id N` is a direct
# reference, not a search (measured: 0.58 s for 12); the persistent ID is read before
# acting because `id` is the less durable identifier, so a track that holds another
# persistent ID, or is gone, is counted stale and never refreshed blind. A gone track
# answers -1728 (measured read-only, 2026-10-19: `track id 987654321 of library
# playlist 1` raised -1728), and that number alone is caught. Any other error, Music's
# timeout included, is re-raised. The reply is the two counts.
REFRESH_IDS_SCRIPT = f"""on run argv
    set refreshedCount to 0
    set staleCount to 0
    tell application "Music"
        with timeout of {IN_SCRIPT_TIMEOUT_SECONDS} seconds
            repeat with pairStart from 1 to (count of argv) by 2
                set trackNumber to (item pairStart of argv) as integer
                set expectedID to item (pairStart + 1) of argv
                set foundID to missing value
                try
                    set foundTrack to track id trackNumber of library playlist 1
                    set foundID to persistent ID of foundTrack
                on error errorText number errorNumber
                    if errorNumber is not -1728 then error errorText number errorNumber
                end try
                if foundID is expectedID then
                    refresh foundTrack
                    set refreshedCount to refreshedCount + 1
                else
                    set staleCount to staleCount + 1
                end if
            end repeat
        end timeout
    end tell
    return (refreshedCount as string) & tab & (staleCount as string)
end run"""


# argv: the first and last index, 1-based and inclusive. Read-only. The range is plain
# `tracks i thru j`, never `file tracks i thru j`, which Music filters from the start of
# the library on every event (about 5 s a read near the end of 20,000 tracks; why, and
# what else was measured: library_audit.md, "Why plain track ranges"). Each property is
# read for the whole range in one event (twelve a batch, whatever its size). Only a file
# track has a `location`: with any other class in the range, it is read one file track at
# a time in a `try` that re-raises Music's -1712, so a timeout never reads as "no file".
# Class and cloud status become text inside the `tell`, where Music's terminology names
# them. The lists come from separate events, so a library changing between them could
# pair one track's path with another's ID: every list's length is checked against the
# first's, and a mismatch errors (a `CallFailed`). The rows are built after the `tell`,
# from locals alone, so no step can become an Apple event (`POSIX path of` a local, as in
# LOOKUP_SCRIPT), and joined once; the fields are `list_tracks`'s. `flatText` turns each
# tab and line break in a name into a space, so no name can split or forge a row; a path
# is left as Music gives it, for the caller's strict parser. `sizeText` writes a size as
# exact digits: AppleScript integers stop at 536,870,911, and `as string` writes a larger
# size, a real, in exponent form (`6.0E+8`), so millions and the rest go out as two
# integers (checked by hand in an osascript with no Music: 600000123.0 wrote 600000123).
LIST_TRACKS_SCRIPT = f"""on flatText(theText)
    if theText is missing value then return ""
    set savedDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to {{tab, linefeed, return}}
    set theParts to text items of theText
    set AppleScript's text item delimiters to " "
    set flatResult to theParts as text
    set AppleScript's text item delimiters to savedDelimiters
    return flatResult
end flatText

on numberText(theNumber)
    if theNumber is missing value then return "0"
    return theNumber as string
end numberText

on sizeText(theSize)
    if theSize is missing value then return "0"
    set highPart to theSize div 1000000
    set lowPart to (theSize mod 1000000) as integer
    if highPart is 0 then return lowPart as string
    set lowText to (1000000 + lowPart) as string
    return (highPart as string) & (text 2 thru -1 of lowText)
end sizeText

on run argv
    set lowIndex to (item 1 of argv) as integer
    set highIndex to (item 2 of argv) as integer
    tell application "Music"
        with timeout of {IN_SCRIPT_TIMEOUT_SECONDS} seconds
            set trackClasses to class of tracks lowIndex thru highIndex of library playlist 1
            set trackIDs to persistent ID of tracks lowIndex thru highIndex of library playlist 1
            set trackStatuses to cloud status of tracks lowIndex thru highIndex of library playlist 1
            set trackAlbums to album of tracks lowIndex thru highIndex of library playlist 1
            set albumArtists to album artist of tracks lowIndex thru highIndex of library playlist 1
            set trackArtists to artist of tracks lowIndex thru highIndex of library playlist 1
            set discNumbers to disc number of tracks lowIndex thru highIndex of library playlist 1
            set trackNumbers to track number of tracks lowIndex thru highIndex of library playlist 1
            set trackCompilations to compilation of tracks lowIndex thru highIndex of library playlist 1
            set trackEnabled to enabled of tracks lowIndex thru highIndex of library playlist 1
            set trackSizes to size of tracks lowIndex thru highIndex of library playlist 1
            set allFileTracks to true
            repeat with trackClass in trackClasses
                if contents of trackClass is not file track then set allFileTracks to false
            end repeat
            if allFileTracks then
                set trackFiles to location of tracks lowIndex thru highIndex of library playlist 1
            else
                set trackFiles to {{}}
                repeat with k from 1 to count of trackClasses
                    set trackClass to item k of trackClasses
                    set trackFile to missing value
                    if contents of trackClass is file track then
                        try
                            set trackFile to location of track (lowIndex + k - 1) of library playlist 1
                        on error errorText number errorNumber
                            if errorNumber is -1712 then error errorText number errorNumber
                        end try
                    end if
                    set end of trackFiles to trackFile
                end repeat
            end if
            set savedDelimiters to AppleScript's text item delimiters
            set AppleScript's text item delimiters to linefeed
            set classText to trackClasses as text
            set statusText to trackStatuses as text
            set classNames to text items of classText
            set statusNames to text items of statusText
            set AppleScript's text item delimiters to savedDelimiters
        end timeout
    end tell
    set expectedLength to count of trackIDs
    if (count of trackClasses) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackFiles) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackStatuses) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackAlbums) is not expectedLength then error "the listed property lists differ in length"
    if (count of albumArtists) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackArtists) is not expectedLength then error "the listed property lists differ in length"
    if (count of discNumbers) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackNumbers) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackCompilations) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackEnabled) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackSizes) is not expectedLength then error "the listed property lists differ in length"
    if (count of classNames) is not expectedLength then error "the listed property lists differ in length"
    if (count of statusNames) is not expectedLength then error "the listed property lists differ in length"
    set trackRows to {{}}
    repeat with i from 1 to expectedLength
        set trackFile to item i of trackFiles
        set trackPath to ""
        if trackFile is not missing value then set trackPath to POSIX path of trackFile
        set artistName to item i of albumArtists
        if artistName is missing value or artistName is "" then set artistName to item i of trackArtists
        set rowText to (item i of trackIDs) & tab & (item i of statusNames) & tab & (my numberText(item i of discNumbers)) & tab & (my numberText(item i of trackNumbers)) & tab & trackPath & tab & (my flatText(item i of trackAlbums)) & tab & (my flatText(artistName)) & tab & ((item i of trackCompilations) as string) & tab & (item i of classNames) & tab & ((item i of trackEnabled) as string) & tab & (my sizeText(item i of trackSizes))
        set end of trackRows to rowText
    end repeat
    set savedDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to linefeed
    set output to (trackRows as text) & linefeed
    set AppleScript's text item delimiters to savedDelimiters
    return output
end run"""


class MusicCallError(Exception):
    """A call to Music.app that did not produce its value; `reason` says why."""

    def __init__(self, reason: str) -> None:
        """Keep *reason*, a one-line description fit for the caller's report."""
        super().__init__(reason)
        self.reason = reason


class CallTimedOut(MusicCallError):
    """A bound expired, the in-script one or the client kill: the caller ends its run."""


class CallFailed(MusicCallError):
    """A non-zero exit, an osascript that could not start, or an unexpected reply."""


class RefreshCounts(NamedTuple):
    """What `refresh_ids` did: tracks refreshed, and tracks stale and left alone."""

    refreshed: int
    stale: int


def real_run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """Run *argv* through `bounded_run`, which kills the whole tree at *timeout*.

    Not `subprocess.run`: on expiry it kills only the direct child and can then block
    reading pipes a grandchild inherited (`bounded_run.md`). Excluded from coverage
    as the real-process seam every unit test replaces with a fake runner.
    """
    return bounded_run.run_bounded(  # pragma: no cover - real-process IO seam, see docstring
        argv, timeout=timeout
    )


def _failure_reason(result: subprocess.CompletedProcess[str]) -> str:
    """The last non-blank stderr line of a failed call, or its exit status."""
    lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
    return lines[-1] if lines else f"osascript exited {result.returncode}"


def _error_number(reason: str) -> int | None:
    """The error number ending *reason*, `(-1712)` say, or None when it ends in none."""
    match = _TRAILING_ERROR_NUMBER.search(reason)
    return int(match.group(1)) if match else None


def _unexpected(reply: str) -> CallFailed:
    """The failure for a reply that is not the one shape its script emits."""
    return CallFailed(
        f"unexpected reply from osascript: {reply[:_REPLY_EXCERPT_CHARS]!r}"
    )


def _call(script: str, args: Sequence[str], run: Runner) -> str:
    """Run *script* with *args* as its argv; return stdout or raise a typed outcome.

    `--` precedes the arguments, so one starting with a dash reaches the script as
    data instead of being parsed as an osascript option.
    """
    argv = ["osascript", "-e", script]
    if args:
        argv += ["--", *args]
    try:
        result = run(argv, CALL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise CallTimedOut(
            f"osascript did not finish within {CALL_TIMEOUT_SECONDS:g} s"
            " and was killed; Music may still be busy"
        ) from None
    except OSError as exc:
        raise CallFailed(f"could not start osascript: {exc}") from exc
    if result.returncode != 0:
        reason = _failure_reason(result)
        if _error_number(reason) == _APPLE_EVENT_TIMED_OUT:
            raise CallTimedOut(reason)
        raise CallFailed(reason)
    return result.stdout


def is_running(*, run: Runner) -> bool:
    """Whether Music.app is running, asked without launching it.

    Raises `CallTimedOut` or `CallFailed` when the probe cannot answer; the caller
    treats both as "cannot start" and can name which in its message.
    """
    reply = _call(IS_RUNNING_SCRIPT, (), run)
    match = _BOOLEAN_REPLY.fullmatch(reply)
    if match is None:
        raise _unexpected(reply)
    return match.group(1) == "true"


def _count(script: str, run: Runner) -> int:
    """The one decimal count *script* replies with; any other reply is a failed call."""
    reply = _call(script, (), run)
    match = _COUNT_REPLY.fullmatch(reply)
    if match is None:
        raise _unexpected(reply)
    return int(match.group(1))


def count_file_tracks(*, run: Runner) -> int:
    """How many file tracks the library holds, as one decimal reply."""
    return _count(COUNT_SCRIPT, run)


def count_tracks(*, run: Runner) -> int:
    """How many tracks of any class the library holds: what `list_tracks` indexes."""
    return _count(COUNT_TRACKS_SCRIPT, run)


def refresh_range(first: int, last: int, *, run: Runner) -> None:
    """Refresh file tracks *first* to *last* (1-based, inclusive) in one call.

    Raises `ValueError` for a range that cannot exist, before any call is made.
    """
    if not 1 <= first <= last:
        raise ValueError(f"not a 1-based inclusive range: {first} to {last}")
    _call(REFRESH_RANGE_SCRIPT, (str(first), str(last)), run)


def lookup_by_albums(names: Sequence[str], *, run: Runner) -> str:
    """The raw rows for every file track whose album is one of *names*.

    Each row is `id`, tab, persistent ID, tab, POSIX path, linefeed, and osascript
    adds one linefeed after the whole reply. Nothing is parsed here: the caller's
    strict row parser owns that. No names makes no call and returns "".
    """
    if not names:
        return ""
    return _call(LOOKUP_SCRIPT, tuple(names), run)


def _validate_pairs(pairs: Sequence[tuple[int, str]]) -> None:
    """Refuse a non-positive id or a malformed persistent ID: a caller's bug."""
    for track_id, persistent_id in pairs:
        if track_id < 1 or _PERSISTENT_ID.fullmatch(persistent_id) is None:
            raise ValueError(f"not a track id pair: {track_id!r}, {persistent_id!r}")


def refresh_ids(pairs: Sequence[tuple[int, str]], *, run: Runner) -> RefreshCounts:
    """Refresh each `(id, persistent ID)` pair whose track still holds that ID.

    Raises `ValueError` for a malformed pair before any call, and `CallFailed` when
    the reply is not two decimal counts adding up to the pairs asked about. No pairs
    makes no call.
    """
    _validate_pairs(pairs)
    if not pairs:
        return RefreshCounts(0, 0)
    args = tuple(value for pair in pairs for value in (str(pair[0]), pair[1]))
    reply = _call(REFRESH_IDS_SCRIPT, args, run)
    match = _REFRESH_COUNTS_REPLY.fullmatch(reply)
    if match is None:
        raise _unexpected(reply)
    counts = RefreshCounts(int(match.group(1)), int(match.group(2)))
    if counts.refreshed + counts.stale != len(pairs):
        raise CallFailed(
            f"Music answered for {counts.refreshed + counts.stale} track(s),"
            f" asked about {len(pairs)} pair(s)"
        )
    return counts


def list_tracks(first: int, last: int, *, run: Runner) -> str:
    """The raw rows for tracks *first* to *last* (1-based, inclusive), read-only.

    Each row is persistent ID, cloud status, disc and track number (0 for none),
    POSIX path (empty for no file, and for every track that is not a file track),
    album, artist (the album artist, else the track's), compilation flag, class,
    enabled flag and size in bytes (decimal digits, 0 for none), tab separated and
    ended by a linefeed; the last two follow the class so the fields before them keep
    their places. osascript adds one linefeed after the whole reply. Nothing is
    parsed here: the caller's strict row parser owns that. Raises `ValueError` for a
    range that cannot exist, before any call is made.
    """
    if not 1 <= first <= last:
        raise ValueError(f"not a 1-based inclusive range: {first} to {last}")
    return _call(LIST_TRACKS_SCRIPT, (str(first), str(last)), run)
