"""The read-only listing calls: the library's track count, and every track in a range.

Driven through the recording fake runner of `test_music_calls.py`, so nothing spawns a
real `osascript`. The calls are library_audit's, not tag_refresh's own: they live beside
the other calls so that both tools share one seam, one set of bounds and one pair of
failure types. What is pinned here is the argv the range travels in, the range
refused before any call, the script's shape as text (it reads, never writes, and
addresses plain tracks rather than file tracks), and each outcome the shared `_call`
turns a reply into.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import music_calls  # noqa: E402 - import follows the sys.path bootstrap above
from test_music_calls import (  # noqa: E402 - import follows the sys.path bootstrap above
    FakeRunner,
    completed,
    killed,
    stripped_lines,
)

_PID = "0123456789ABCDEF"
#: A ``set`` statement's target, everything between ``set`` and its ``to``. A read
#: assigns to a bare variable; a write assigns to an object's property (``set name of
#: track 1 to ...``, ``set the rating of ...``), so a target holding more is a write.
_SET_TARGET = re.compile(r"\bset\s+(.+?)\s+to\b", re.IGNORECASE)
#: The one target with a space a read-only script may set: its own delimiters.
_LOCAL_TARGETS = frozenset({"AppleScript's text item delimiters"})
#: A bare variable name, the only other target allowed.
_VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
#: An append to a local list, ``set end of rowList to ...``: a local, not a property.
_LOCAL_APPEND = re.compile(r"end of [A-Za-z_][A-Za-z0-9_]*")
#: Music.app's commands that change the library or a file, as whole words.
_WRITING_COMMAND = re.compile(
    r"\b(?:add|refresh|delete|duplicate|move|make|copy|convert|reveal|download)\b",
    re.IGNORECASE,
)
#: The script's one range, every property read over it.
_RANGE = "tracks lowIndex thru highIndex of library playlist 1"
#: The error line every length check raises.
_LENGTH_ERROR = 'error "the listed property lists differ in length"'


def writes_found(script: str) -> list[str]:
    """Every property write and writing command in *script*, as written."""
    targets = [
        found.group(0)
        for found in _SET_TARGET.finditer(script)
        if found.group(1) not in _LOCAL_TARGETS
        and _VARIABLE.fullmatch(found.group(1)) is None
        and _LOCAL_APPEND.fullmatch(found.group(1)) is None
    ]
    return targets + [found.group(0) for found in _WRITING_COMMAND.finditer(script)]


class CountTracksTest(unittest.TestCase):
    """The count of every track in the library playlist, strictly a decimal."""

    def test_a_count_reads_as_an_int_from_its_own_script(self) -> None:
        run = FakeRunner(completed("20000\n"))
        self.assertEqual(music_calls.count_tracks(run=run), 20000)
        self.assertEqual(
            run.calls,
            [
                (
                    ["osascript", "-e", music_calls.COUNT_TRACKS_SCRIPT],
                    music_calls.CALL_TIMEOUT_SECONDS,
                )
            ],
        )

    def test_it_counts_plain_tracks_not_file_tracks(self) -> None:
        # The listing reads `tracks i thru j`, so its count must count the same set.
        lines = stripped_lines(music_calls.COUNT_TRACKS_SCRIPT)
        self.assertIn("return count of tracks of library playlist 1", lines)
        self.assertNotIn("file track", music_calls.COUNT_TRACKS_SCRIPT)

    def test_garbage_is_a_failed_call(self) -> None:
        for reply in ("", "-1\n", "1 2\n", "7\n\n"):
            with self.subTest(reply=reply):
                with self.assertRaises(music_calls.CallFailed):
                    music_calls.count_tracks(run=FakeRunner(completed(reply)))

    def test_a_kill_raises_call_timed_out(self) -> None:
        with self.assertRaises(music_calls.CallTimedOut):
            music_calls.count_tracks(run=FakeRunner(killed()))


class ListTracksTest(unittest.TestCase):
    """A range in, raw rows out; the rows are the caller's to parse."""

    def test_the_range_travels_as_argv_after_the_option_end(self) -> None:
        rows = f"{_PID}\tmatched\t1\t2\t/L/a.mp3\tAlbum\tArtist\tfalse\tfile track\ttrue\t4096\n"
        run = FakeRunner(completed(rows + "\n"))
        reply = music_calls.list_tracks(3, 7, run=run)
        self.assertEqual(reply, rows + "\n")
        self.assertEqual(
            run.calls,
            [
                (
                    [
                        "osascript",
                        "-e",
                        music_calls.LIST_TRACKS_SCRIPT,
                        "--",
                        "3",
                        "7",
                    ],
                    music_calls.CALL_TIMEOUT_SECONDS,
                )
            ],
        )

    def test_a_range_that_cannot_exist_is_refused_before_any_call(self) -> None:
        for first, last in ((0, 3), (5, 4), (-1, -1)):
            with self.subTest(first=first, last=last):
                run = FakeRunner(completed(""))
                with self.assertRaises(ValueError):
                    music_calls.list_tracks(first, last, run=run)
                self.assertEqual(run.calls, [])

    def test_a_failed_call_raises_call_failed(self) -> None:
        run = FakeRunner(
            completed(returncode=1, stderr="0:1: execution error (-1728)\n")
        )
        with self.assertRaises(music_calls.CallFailed):
            music_calls.list_tracks(1, 2, run=run)

    def test_a_kill_raises_call_timed_out(self) -> None:
        with self.assertRaises(music_calls.CallTimedOut):
            music_calls.list_tracks(1, 2, run=FakeRunner(killed()))


class ListScriptTextTest(unittest.TestCase):
    """The script as text: bounded, read-only, and safe for any name it reads."""

    def test_it_holds_the_in_script_timeout_inside_one_tell(self) -> None:
        script = music_calls.LIST_TRACKS_SCRIPT
        bound = f"with timeout of {music_calls.IN_SCRIPT_TIMEOUT_SECONDS} seconds"
        self.assertIn(bound, script)
        self.assertEqual(script.count('tell application "Music"'), 1)

    def test_it_reads_its_range_from_argv(self) -> None:
        lines = stripped_lines(music_calls.LIST_TRACKS_SCRIPT)
        self.assertIn("on run argv", lines)
        self.assertIn("set lowIndex to (item 1 of argv) as integer", lines)
        self.assertIn("set highIndex to (item 2 of argv) as integer", lines)
        self.assertTrue(music_calls.LIST_TRACKS_SCRIPT.endswith("end run"))

    def test_it_never_writes_to_music(self) -> None:
        self.assertEqual(writes_found(music_calls.LIST_TRACKS_SCRIPT), [])

    def test_the_write_check_finds_each_kind_of_write(self) -> None:
        # The check above can fail: each invented write here must be found.
        for script in (
            'set name of track 1 to "x"',
            "set the rating of current track to 40",
            "set x of y to 1",
            "set end of track 1 to 2",
            "refresh track 1",
            "add aFile to library playlist 1",
            "delete track 1",
            "duplicate track 1 to playlist 2",
            "move track 1 to playlist 2",
            "make new playlist",
        ):
            with self.subTest(script=script):
                self.assertNotEqual(writes_found(script), [])

    def test_the_write_check_lets_a_local_list_grow(self) -> None:
        self.assertEqual(writes_found("set end of trackRows to rowText"), [])

    def test_every_property_list_is_checked_against_the_first_s_length(self) -> None:
        # Act, then confirm: lists of unequal length would pair one track's path with
        # another's ID, so the script errors (a CallFailed) instead of answering.
        lines = stripped_lines(music_calls.LIST_TRACKS_SCRIPT)
        self.assertIn("set expectedLength to count of trackIDs", lines)
        for name in (
            "trackClasses",
            "trackFiles",
            "trackStatuses",
            "trackAlbums",
            "albumArtists",
            "trackArtists",
            "discNumbers",
            "trackNumbers",
            "trackCompilations",
            "trackEnabled",
            "trackSizes",
            "classNames",
            "statusNames",
        ):
            with self.subTest(name=name):
                self.assertIn(
                    f"if (count of {name}) is not expectedLength then {_LENGTH_ERROR}",
                    lines,
                )

    def test_each_property_is_read_over_plain_tracks_for_the_whole_range(self) -> None:
        # One Apple event a property, not one a track: the reason a batch is cheap.
        # `file tracks i thru j` made Music filter the library up to j on every event.
        for prop in (
            "class",
            "persistent ID",
            "cloud status",
            "album",
            "album artist",
            "artist",
            "disc number",
            "track number",
            "compilation",
            "enabled",
            "size",
        ):
            with self.subTest(prop=prop):
                self.assertIn(f" to {prop} of {_RANGE}", music_calls.LIST_TRACKS_SCRIPT)
        self.assertNotIn("file tracks", music_calls.LIST_TRACKS_SCRIPT)

    def test_location_is_read_in_one_event_only_when_every_track_is_a_file(
        self,
    ) -> None:
        lines = stripped_lines(music_calls.LIST_TRACKS_SCRIPT)
        whole = lines.index("if allFileTracks then")
        self.assertEqual(lines[whole + 1], f"set trackFiles to location of {_RANGE}")
        self.assertEqual(lines[whole + 2], "else")

    def test_otherwise_only_a_file_track_s_location_is_read_one_by_one(self) -> None:
        lines = stripped_lines(music_calls.LIST_TRACKS_SCRIPT)
        self.assertIn("if contents of trackClass is file track then", lines)
        self.assertIn(
            "set trackFile to location of track (lowIndex + k - 1) of library playlist 1",
            lines,
        )
        self.assertIn("set end of trackFiles to trackFile", lines)

    def test_the_one_by_one_read_re_raises_music_s_timeout(self) -> None:
        # A timeout swallowed by the `try` would read as "no file", a false finding.
        lines = stripped_lines(music_calls.LIST_TRACKS_SCRIPT)
        header = lines.index("on error errorText number errorNumber")
        self.assertEqual(
            lines[header + 1],
            "if errorNumber is -1712 then error errorText number errorNumber",
        )
        self.assertEqual(lines[header + 2], "end try")

    def test_the_rows_are_built_after_the_tell_and_joined_once(self) -> None:
        # Outside the tell no statement can become an Apple event, and one join
        # replaces a concatenation that copies the whole reply once a row.
        lines = stripped_lines(music_calls.LIST_TRACKS_SCRIPT)
        self.assertLess(
            lines.index("end tell"),
            lines.index("repeat with i from 1 to expectedLength"),
        )
        self.assertIn("set end of trackRows to rowText", lines)
        self.assertIn("set output to (trackRows as text) & linefeed", lines)
        self.assertNotIn("set output to output &", music_calls.LIST_TRACKS_SCRIPT)

    def test_the_delimiters_are_restored_after_each_join(self) -> None:
        script = music_calls.LIST_TRACKS_SCRIPT
        self.assertEqual(
            script.count("set savedDelimiters to AppleScript's text item delimiters"),
            script.count("set AppleScript's text item delimiters to savedDelimiters"),
        )

    def test_names_are_flattened_so_a_tab_or_linefeed_cannot_forge_a_row(self) -> None:
        lines = stripped_lines(music_calls.LIST_TRACKS_SCRIPT)
        self.assertIn(
            "set AppleScript's text item delimiters to {tab, linefeed, return}", lines
        )
        self.assertEqual(music_calls.LIST_TRACKS_SCRIPT.count("my flatText("), 2)

    def test_the_class_follows_the_compilation_flag(self) -> None:
        # The ninth field, after the compilation flag: library_audit's parser reads it.
        self.assertIn(
            "((item i of trackCompilations) as string) & tab & (item i of classNames)",
            music_calls.LIST_TRACKS_SCRIPT,
        )

    def test_enabled_and_size_are_the_row_s_last_fields(self) -> None:
        # Appended after the class, so the nine fields before them keep their places.
        self.assertIn(
            "(item i of classNames) & tab & ((item i of trackEnabled) as string)"
            " & tab & (my sizeText(item i of trackSizes))",
            music_calls.LIST_TRACKS_SCRIPT,
        )

    def test_a_size_is_written_as_exact_decimal_digits(self) -> None:
        # AppleScript integers stop at 536,870,911, so a larger size is a real, which
        # `as string` writes in exponent form (6.0E+8), no exact integer. The
        # handler splits it into millions and the rest, each an exact integer, and
        # pads the rest to six digits. Verified by hand in a plain osascript with no
        # Music: 600000123.0 wrote 600000123, and missing value wrote 0.
        lines = stripped_lines(music_calls.LIST_TRACKS_SCRIPT)
        start = lines.index("on sizeText(theSize)")
        self.assertEqual(
            lines[start + 1 : start + 8],
            [
                'if theSize is missing value then return "0"',
                "set highPart to theSize div 1000000",
                "set lowPart to (theSize mod 1000000) as integer",
                "if highPart is 0 then return lowPart as string",
                "set lowText to (1000000 + lowPart) as string",
                "return (highPart as string) & (text 2 thru -1 of lowText)",
                "end sizeText",
            ],
        )


if __name__ == "__main__":
    unittest.main()
