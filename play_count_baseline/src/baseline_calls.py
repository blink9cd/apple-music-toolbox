"""The play-count read: one AppleScript listing a range of tracks, sent through tag_refresh.

Read-only. `list_play_counts` sends `PLAY_COUNTS_SCRIPT` for a 1-based inclusive range
and returns its raw reply, one tab-separated row a track, for `baseline_rows` to
parse; nothing is parsed here.

The seam is a documented contract, as it is for library_audit: this tool reaches
Music.app only through `music_calls`, in the sibling ``tag_refresh/src/`` folder, with
its bounds, failure types, and ``Runner`` shape. Importing this module puts that folder
on ``sys.path``; renaming or moving it breaks this import loudly, at start.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: tag_refresh's private modules, the Music.app seam this tool shares: the sibling
#: tool folder's ``src/``, one fixed place under the project root.
SEAM_DIR = Path(__file__).resolve().parents[2] / "tag_refresh" / "src"
sys.path[:0] = [str(SEAM_DIR)]

import music_calls  # noqa: E402 - import follows the sys.path bootstrap above

# music_calls is at the 500-line file cap, so its one call primitive is imported under a
# public name here rather than renamed there, which would touch ten other suites.
from music_calls import _call as call_script  # noqa: E402 - follows the sys.path bootstrap above

# argv: the first and last index, 1-based and inclusive. Read-only. Built line for line
# on music_calls.LIST_TRACKS_SCRIPT, whose comment gives the reasons: plain track ranges,
# one Apple event a property for the whole range inside the shared in-script bound,
# `location` per file track in a `try` that re-raises -1712 when the range holds another
# class, every list's length checked against the persistent IDs', the rows built after
# the `tell` from locals alone, and `flatText` on every text field. `dateParts` and
# `milliseconds` are the scrobbler's own (scrobbler/app/Sources/ScrobblerCore/
# MusicScripts.swift), so a played date leaves as local parts and a duration as whole
# milliseconds. The row's fields are `list_play_counts`'s; the album artist is raw, with
# no fall-back to the artist.
PLAY_COUNTS_SCRIPT = f"""on flatText(theText)
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

on dateParts(d)
    if d is missing value then return ""
    set ymd to (year of d) as text & "/" & ((month of d) as integer) & "/" & (day of d)
    return ymd & "/" & (time of d)
end dateParts

on milliseconds(s)
    -- A 149-hour ceiling: from 536870 seconds on, the millisecond count overflows
    -- AppleScript's integers, so a longer length reads as empty.
    if s is missing value then return ""
    if s is greater than or equal to 536870 then return ""
    return (round (s * 1000)) as text
end milliseconds

on run argv
    set lowIndex to (item 1 of argv) as integer
    set highIndex to (item 2 of argv) as integer
    tell application "Music"
        with timeout of {music_calls.IN_SCRIPT_TIMEOUT_SECONDS} seconds
            set trackClasses to class of tracks lowIndex thru highIndex of library playlist 1
            set trackIDs to persistent ID of tracks lowIndex thru highIndex of library playlist 1
            set trackNames to name of tracks lowIndex thru highIndex of library playlist 1
            set trackArtists to artist of tracks lowIndex thru highIndex of library playlist 1
            set trackAlbums to album of tracks lowIndex thru highIndex of library playlist 1
            set albumArtists to album artist of tracks lowIndex thru highIndex of library playlist 1
            set discNumbers to disc number of tracks lowIndex thru highIndex of library playlist 1
            set trackDurations to duration of tracks lowIndex thru highIndex of library playlist 1
            set playedCounts to played count of tracks lowIndex thru highIndex of library playlist 1
            set playedDates to played date of tracks lowIndex thru highIndex of library playlist 1
            set trackGenres to genre of tracks lowIndex thru highIndex of library playlist 1
            set trackYears to year of tracks lowIndex thru highIndex of library playlist 1
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
        end timeout
    end tell
    set expectedLength to count of trackIDs
    if (count of trackClasses) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackNames) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackArtists) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackAlbums) is not expectedLength then error "the listed property lists differ in length"
    if (count of albumArtists) is not expectedLength then error "the listed property lists differ in length"
    if (count of discNumbers) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackDurations) is not expectedLength then error "the listed property lists differ in length"
    if (count of playedCounts) is not expectedLength then error "the listed property lists differ in length"
    if (count of playedDates) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackGenres) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackYears) is not expectedLength then error "the listed property lists differ in length"
    if (count of trackFiles) is not expectedLength then error "the listed property lists differ in length"
    set trackRows to {{}}
    repeat with i from 1 to expectedLength
        set trackFile to item i of trackFiles
        set trackPath to ""
        if trackFile is not missing value then set trackPath to POSIX path of trackFile
        set rowText to (item i of trackIDs) & tab & (my flatText(item i of trackNames)) & tab & (my flatText(item i of trackArtists)) & tab & (my flatText(item i of trackAlbums)) & tab & (my flatText(item i of albumArtists)) & tab & (my numberText(item i of discNumbers)) & tab & (my milliseconds(item i of trackDurations)) & tab & (my numberText(item i of playedCounts)) & tab & (my dateParts(item i of playedDates)) & tab & (my flatText(item i of trackGenres)) & tab & (my numberText(item i of trackYears)) & tab & trackPath
        set end of trackRows to rowText
    end repeat
    set savedDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to linefeed
    set output to (trackRows as text) & linefeed
    set AppleScript's text item delimiters to savedDelimiters
    return output
end run"""


def list_play_counts(first: int, last: int, *, run: music_calls.Runner) -> str:
    """The raw play-count rows for tracks *first* to *last* (1-based, inclusive).

    Each row is persistent ID, name, artist, album, album artist (raw), disc number
    (0 for none), duration in milliseconds (empty for none), played count, played
    date parts (``Y/M/D/seconds-after-midnight``, empty for none), genre, year (0 for
    none), and POSIX path (empty for none), tab separated and ended by a linefeed;
    osascript adds one linefeed after the whole reply. Raises `ValueError` for a
    range that cannot exist, before any call is made, and `music_calls.CallTimedOut`
    or `music_calls.CallFailed` as every call there does.
    """
    if not 1 <= first <= last:
        raise ValueError(f"not a 1-based inclusive range: {first} to {last}")
    return call_script(PLAY_COUNTS_SCRIPT, (str(first), str(last)), run)
