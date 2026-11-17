"""library_audit's read-only listing: every track of a range, one raw row a track.

Split from `music_calls`, whose seam it shares (`call`, `Runner`, the in-script bound
and the two failure types), so that module stays within the file-length bar.
`list_tracks` reads a 1-based inclusive range of the library's tracks, of any class,
and returns the raw reply for library_audit's parser (`audit_rows`); `count_tracks`,
in `music_calls`, counts what it indexes. Nothing here writes to Music.app.
"""

from __future__ import annotations

import script_text
from music_calls import IN_SCRIPT_TIMEOUT_SECONDS, Runner, call

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
# LOOKUP_SCRIPT), and joined once; the fields are `list_tracks`'s. The path, the album
# and the artist go through `escapedText`, the shared handler the script opens with
# (`script_text.ESCAPE_HANDLER`, whose comment says how it works), so none can split or
# forge a row and each reads back exactly once `audit_rows` undoes it; the flattening
# it replaced turned a tab or line break into a space, and left a path raw, so a path
# holding a line break split its row and ended the audit. `sizeText` writes a size as
# exact digits: AppleScript integers stop at 536,870,911, and `as string` writes a larger
# size, a real, in exponent form (`6.0E+8`), so millions and the rest go out as two
# integers (checked by hand in an osascript with no Music: 600000123.0 wrote 600000123).
LIST_TRACKS_SCRIPT = (
    script_text.ESCAPE_HANDLER
    + f"""
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
        set rowText to (item i of trackIDs) & tab & (item i of statusNames) & tab & (my numberText(item i of discNumbers)) & tab & (my numberText(item i of trackNumbers)) & tab & (my escapedText(trackPath)) & tab & (my escapedText(item i of trackAlbums)) & tab & (my escapedText(artistName)) & tab & ((item i of trackCompilations) as string) & tab & (item i of classNames) & tab & ((item i of trackEnabled) as string) & tab & (my sizeText(item i of trackSizes))
        set end of trackRows to rowText
    end repeat
    set savedDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to linefeed
    set output to (trackRows as text) & linefeed
    set AppleScript's text item delimiters to savedDelimiters
    return output
end run"""
)


def list_tracks(first: int, last: int, *, run: Runner) -> str:
    """The raw rows for tracks *first* to *last* (1-based, inclusive), read-only.

    Each row is persistent ID, cloud status, disc and track number (0 for none),
    POSIX path (empty for no file, and for every track that is not a file track),
    album, artist (the album artist, else the track's), compilation flag, class,
    enabled flag and size in bytes (decimal digits, 0 for none), tab separated and
    ended by a linefeed; the last two follow the class so the fields before them keep
    their places. The path, album and artist are escaped (`script_text.unescape_field`
    reverses it). osascript adds one linefeed after the whole reply. Nothing is
    parsed here: the caller's strict row parser owns that. Raises `ValueError` for a
    range that cannot exist, before any call is made.
    """
    if not 1 <= first <= last:
        raise ValueError(f"not a 1-based inclusive range: {first} to {last}")
    return call(LIST_TRACKS_SCRIPT, (str(first), str(last)), run)
