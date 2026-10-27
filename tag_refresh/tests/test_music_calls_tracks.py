"""The track-level AppleScript calls: the lookup by album names and the refresh by id.

Driven through the recording fake runner of `test_music_calls.py`, so nothing spawns a
real `osascript`. The load-bearing assertion is that an album name only ever travels
as an argv value after `--`, never inside the script text: a name holding a quote, a
backslash or a leading dash then needs no escaping and cannot become an option.
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

# Names chosen to break a script that interpolated them: a quote, a backslash, a
# leading dash osascript would take as its own option, an attempt to close the literal
# and run a command, a tab and a linefeed that would forge a row.
_HOSTILE_NAMES = [
    'Say "Hello"',
    "Back\\slash",
    "-x",
    "--help",
    'Quiet" & (do shell script "true") & "',
    "Tab\tName",
    "Line\nFeed",
]

_PID_A = "0123456789ABCDEF"
_PID_B = "FEDCBA9876543210"


class LookupByAlbumsTest(unittest.TestCase):
    """Names in, raw rows out; the rows are T1's to parse."""

    def test_names_travel_as_argv_after_the_option_end(self) -> None:
        rows = f"12\t{_PID_A}\t/Music/A/01.mp3\n"
        run = FakeRunner(completed(rows + "\n"))
        reply = music_calls.lookup_by_albums(_HOSTILE_NAMES, run=run)
        self.assertEqual(reply, rows + "\n")
        self.assertEqual(
            run.calls,
            [
                (
                    [
                        "osascript",
                        "-e",
                        music_calls.LOOKUP_SCRIPT,
                        "--",
                        *_HOSTILE_NAMES,
                    ],
                    music_calls.CALL_TIMEOUT_SECONDS,
                )
            ],
        )

    def test_no_name_ever_appears_in_the_script(self) -> None:
        run = FakeRunner(completed(""))
        music_calls.lookup_by_albums(_HOSTILE_NAMES, run=run)
        argv = run.calls[0][0]
        script = argv[argv.index("-e") + 1]
        self.assertEqual(script, music_calls.LOOKUP_SCRIPT)
        for name in _HOSTILE_NAMES:
            with self.subTest(name=name):
                self.assertNotIn(name, script)
                self.assertNotIn(name, argv[: argv.index("--")])

    def test_the_script_asks_by_album_and_emits_the_three_fields(self) -> None:
        script = music_calls.LOOKUP_SCRIPT
        self.assertIn("whose album is", script)
        self.assertIn("every file track of library playlist 1", script)
        for field in ("id of", "persistent ID of", "POSIX path of"):
            with self.subTest(field=field):
                self.assertIn(field, script)
        self.assertIn("linefeed", script)

    def test_the_path_is_coerced_from_a_local_never_from_a_location_reference(
        self,
    ) -> None:
        # Inside `tell application "Music"`, `POSIX path of (location of t)` is sent
        # to Music as part of the object specifier, and Music answers -1728 for every
        # track. Read into a variable first, `POSIX path of` is a local coercion of
        # the alias, which answered with well-formed rows live.
        script = music_calls.LOOKUP_SCRIPT
        self.assertIsNone(re.search(r"POSIX path of \(*\s*location of", script))
        lines = stripped_lines(script)
        read = lines.index("set trackFile to location of albumTrack")
        emit = lines[read + 1]
        self.assertTrue(
            emit.startswith("if trackFile is not missing value then set output to "),
            emit,
        )
        self.assertTrue(emit.endswith(" & (POSIX path of trackFile) & linefeed"), emit)
        self.assertEqual(lines[read + 2], "end repeat")

    def test_the_album_filter_compares_against_a_local(self) -> None:
        lines = stripped_lines(music_calls.LOOKUP_SCRIPT)
        bind = lines.index("set albumText to contents of albumName")
        self.assertEqual(
            lines[bind + 1],
            "set albumTracks to (every file track of library playlist 1"
            " whose album is albumText)",
        )

    def test_no_names_make_no_call(self) -> None:
        run = FakeRunner(completed("unused"))
        self.assertEqual(music_calls.lookup_by_albums([], run=run), "")
        self.assertEqual(run.calls, [])

    def test_a_non_zero_exit_is_a_failed_call(self) -> None:
        run = FakeRunner(completed(returncode=1, stderr="not allowed (-1743)\n"))
        with self.assertRaises(music_calls.CallFailed) as caught:
            music_calls.lookup_by_albums(["A"], run=run)
        self.assertEqual(caught.exception.reason, "not allowed (-1743)")

    def test_the_in_script_timeout_is_a_timeout(self) -> None:
        stderr = "execution error: Music got an error: AppleEvent timed out. (-1712)"
        run = FakeRunner(completed(returncode=1, stderr=stderr))
        with self.assertRaises(music_calls.CallTimedOut):
            music_calls.lookup_by_albums(["A"], run=run)

    def test_a_client_kill_is_a_timeout(self) -> None:
        with self.assertRaises(music_calls.CallTimedOut):
            music_calls.lookup_by_albums(["A"], run=FakeRunner(killed()))


class RefreshIdsTest(unittest.TestCase):
    """Pairs in, (refreshed, stale) out, the reply strictly checked."""

    def test_pairs_travel_flat_as_argv(self) -> None:
        run = FakeRunner(completed("1\t1\n"))
        counts = music_calls.refresh_ids([(12, _PID_A), (345, _PID_B)], run=run)
        self.assertEqual(counts, music_calls.RefreshCounts(refreshed=1, stale=1))
        self.assertEqual(
            run.calls,
            [
                (
                    [
                        "osascript",
                        "-e",
                        music_calls.REFRESH_IDS_SCRIPT,
                        "--",
                        "12",
                        _PID_A,
                        "345",
                        _PID_B,
                    ],
                    music_calls.CALL_TIMEOUT_SECONDS,
                )
            ],
        )

    def test_the_script_checks_the_persistent_id_before_refreshing(self) -> None:
        script = music_calls.REFRESH_IDS_SCRIPT
        self.assertIn("track id trackNumber of library playlist 1", script)
        self.assertLess(
            script.index("persistent ID of"), script.index("refresh foundTrack")
        )
        # The order alone passes with the guard deleted: the refresh must sit inside
        # the branch taken only when the persistent ID read back is the expected one.
        lines = stripped_lines(script)
        refresh = lines.index("refresh foundTrack")
        self.assertEqual(lines[refresh - 1], "if foundID is expectedID then")

    def test_a_reply_without_its_linefeed_still_reads(self) -> None:
        run = FakeRunner(completed("2\t0"))
        counts = music_calls.refresh_ids([(1, _PID_A), (2, _PID_B)], run=run)
        self.assertEqual(counts, music_calls.RefreshCounts(2, 0))

    def test_no_pairs_make_no_call(self) -> None:
        run = FakeRunner(completed("unused"))
        self.assertEqual(
            music_calls.refresh_ids([], run=run), music_calls.RefreshCounts(0, 0)
        )
        self.assertEqual(run.calls, [])

    def test_a_malformed_pair_is_refused_before_any_call(self) -> None:
        for pair in (
            (0, _PID_A),
            (-3, _PID_A),
            (1, "0123"),
            (1, "0123456789ABCDEG"),
            (1, "0123456789ABCDEF0"),
            (1, "-123456789ABCDEF"),
            (1, "0123456789abcdef\n"),
        ):
            with self.subTest(pair=pair):
                run = FakeRunner(completed("1\t0\n"))
                with self.assertRaises(ValueError):
                    music_calls.refresh_ids([pair], run=run)
                self.assertEqual(run.calls, [])

    def test_a_lower_case_persistent_id_is_accepted(self) -> None:
        run = FakeRunner(completed("1\t0\n"))
        counts = music_calls.refresh_ids([(1, _PID_A.lower())], run=run)
        self.assertEqual(counts.refreshed, 1)

    def test_garbage_is_a_failed_call(self) -> None:
        for reply in ("", "1\n", "1 0\n", "a\t0\n", "1\t0\t0\n", "1\t0\n\n", "-1\t2\n"):
            with self.subTest(reply=reply):
                run = FakeRunner(completed(reply))
                with self.assertRaises(music_calls.CallFailed) as caught:
                    music_calls.refresh_ids([(1, _PID_A)], run=run)
                self.assertIn("unexpected reply", caught.exception.reason)

    def test_counts_that_do_not_add_up_are_a_failed_call(self) -> None:
        for reply in ("2\t0\n", "0\t0\n", "1\t1\n"):
            with self.subTest(reply=reply):
                run = FakeRunner(completed(reply))
                with self.assertRaises(music_calls.CallFailed) as caught:
                    music_calls.refresh_ids([(1, _PID_A)], run=run)
                self.assertIn("1 pair", caught.exception.reason)

    def test_a_non_zero_exit_is_a_failed_call(self) -> None:
        run = FakeRunner(completed(returncode=1, stderr="refresh failed (-54)\n"))
        with self.assertRaises(music_calls.CallFailed):
            music_calls.refresh_ids([(1, _PID_A)], run=run)

    def test_the_in_script_timeout_is_a_timeout(self) -> None:
        run = FakeRunner(completed(returncode=1, stderr="timed out. (-1712)\n"))
        with self.assertRaises(music_calls.CallTimedOut):
            music_calls.refresh_ids([(1, _PID_A)], run=run)

    def test_a_client_kill_is_a_timeout(self) -> None:
        with self.assertRaises(music_calls.CallTimedOut):
            music_calls.refresh_ids([(1, _PID_A)], run=FakeRunner(killed()))


if __name__ == "__main__":
    unittest.main()
