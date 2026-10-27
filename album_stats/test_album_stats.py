"""Tests for album_stats: one album's track and favorited-track counts and year.

Every test that reaches the seam drives a FAKE `run` -- nothing in this file spawns a
real `osascript` process or touches Music.app. The real-process seam is
`recently_added._real_run`, which this tool REUSES rather than reimplementing; this
tool's favorited script meets the real Music.app in
`album_scan/tests/test_live_favorites.py`, and its star-rating script in
`tests/test_live_star_rating.py`.

Two of these tests pin rules a plausible-looking rewrite would silently undo:
`favorited`, not `rating`, is the property with data in it (measured against a real
library; see `album_stats.md`), and both the artist AND the album must constrain
the query.

`load_tests` below also runs every suite in `tests/`. A runner that runs only each
folder's top-level test file (the README's loop, or a gate that prunes `tests/` by
name) reaches them only through this file, so without the hook those suites run
nowhere there. One
of them, `tests/test_live_literal.py`, does spawn the real `/usr/bin/osascript` -- on a
bare string literal, with no `tell` block, so it reaches neither Music.app nor the
network, and it skips itself off macOS. Another, `tests/test_live_star_rating.py`,
sends one read-only query to the real Music.app, and skips itself off macOS, when
Music.app is unreachable, and whenever `APPLE_MUSIC_TOOLBOX_OFFLINE` is set.
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import album_stats
import recently_added
import help_formatter  # reachable only via album_stats' bootstrap
from album_stats import AlbumFacts, album_facts

# Words measured to collide with Music's scripting dictionary when bound as a script
# variable (see album_stats.md, "Why a `whose` clause, and not a loop").
_KNOWN_DICTIONARY_COLLISIONS = frozenset({"matched", "computed"})


def _completed(returncode: int, stdout: str) -> subprocess.CompletedProcess[str]:
    """Build a fake `osascript` result without spawning a real process."""
    return subprocess.CompletedProcess(
        args=["osascript"], returncode=returncode, stdout=stdout, stderr=""
    )


def _runner_returning(returncode: int, stdout: str) -> album_stats.Runner:
    """A fake `run` that answers every invocation with the same result."""

    def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        return _completed(returncode, stdout)

    return run


def _recording_runner(stdout: str) -> tuple[album_stats.Runner, list[float]]:
    """A fake `run` that records every timeout it is handed and answers `stdout`."""
    seen: list[float] = []

    def run(_args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        seen.append(timeout)
        return _completed(0, stdout)

    return run, seen


def _script_for(artist: str, album: str) -> str:
    """The AppleScript source `album_facts` would send for this artist/album.

    Captures the argv the seam receives rather than calling the script builder
    directly, so these assertions cover the whole path from public argument to the
    text that would actually reach `osascript` -- an escaping bug anywhere along it
    fails here.
    """
    captured: list[str] = []

    def run(args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        captured.append(args[-1])
        return _completed(0, "1\t0\t2000")

    album_facts(artist=artist, album=album, run=run)
    return captured[0]


class AlbumFactsTest(unittest.TestCase):
    """Never raises: each failure mode below returns `None`, a good reply its facts."""

    def test_a_three_field_reply_resolves_to_the_albums_facts(self) -> None:
        counts = album_facts(
            artist="Fictionals", album="Blue", run=_runner_returning(0, "10\t2\t1994\n")
        )
        self.assertEqual(counts, AlbumFacts(tracks=10, favorited=2, year=1994))

    def test_a_single_track_album_is_a_real_answer(self) -> None:
        # A single: one track, favorited. The floor is "no tracks matched", not "one
        # track" -- the boundary an off-by-one rewrite of the guard would move, and
        # the one no other test here pins on purpose.
        counts = album_facts(
            artist="Fictionals",
            album="A Single",
            run=_runner_returning(0, "1\t1\t1994"),
        )
        self.assertEqual(counts, AlbumFacts(tracks=1, favorited=1, year=1994))

    def test_zero_favorited_is_a_real_answer_not_a_missing_one(self) -> None:
        # The COMMON case for a newly added album: this must be a value, never None,
        # or a consumer could not tell "none favorited yet" from "could not tell".
        counts = album_facts(
            artist="Fictionals", album="Blue", run=_runner_returning(0, "10\t0\t2001")
        )
        self.assertEqual(counts, AlbumFacts(tracks=10, favorited=0, year=2001))

    def test_an_album_with_no_tracks_is_no_answer(self) -> None:
        # Nothing matched the artist/album pair. Zero counts would read as a
        # nonsensical "0 of 0", so absence is reported as absence.
        self.assertIsNone(
            album_facts(
                artist="Nobody", album="Nothing", run=_runner_returning(0, "0\t0\t0")
            )
        )

    def test_a_nonzero_exit_is_no_answer(self) -> None:
        self.assertIsNone(
            album_facts(artist="A", album="B", run=_runner_returning(1, ""))
        )

    def test_an_oserror_is_no_answer(self) -> None:
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            raise OSError("osascript not found")

        self.assertIsNone(album_facts(artist="A", album="B", run=run))

    def test_a_subprocess_error_is_no_answer(self) -> None:
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(cmd="osascript", timeout=1.0)

        self.assertIsNone(album_facts(artist="A", album="B", run=run))

    def test_a_refused_argv_is_no_answer(self) -> None:
        # A NUL in the artist or album lands in the script text, and
        # `subprocess.Popen` refuses an argv element holding one with ValueError
        # rather than OSError -- the one seam failure this contract did not cover.
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            raise ValueError("embedded null byte")

        self.assertIsNone(album_facts(artist="A", album="B", run=run))

    def test_a_wrong_field_count_is_no_answer(self) -> None:
        self.assertIsNone(
            album_facts(artist="A", album="B", run=_runner_returning(0, "10"))
        )

    def test_non_integer_output_is_no_answer(self) -> None:
        self.assertIsNone(
            album_facts(artist="A", album="B", run=_runner_returning(0, "ten\ttwo\tx"))
        )

    def test_empty_output_is_no_answer(self) -> None:
        self.assertIsNone(
            album_facts(artist="A", album="B", run=_runner_returning(0, ""))
        )

    def test_more_favorited_than_tracks_is_no_answer(self) -> None:
        # Not reachable from a correct Music.app, but the parse must not hand on a
        # record that reads "12 of 10" if it ever were.
        self.assertIsNone(
            album_facts(artist="A", album="B", run=_runner_returning(0, "10\t12\t1994"))
        )

    def test_a_negative_track_count_is_no_answer(self) -> None:
        self.assertIsNone(
            album_facts(artist="A", album="B", run=_runner_returning(0, "-1\t0\t1994"))
        )

    def test_a_negative_favorited_count_is_no_answer(self) -> None:
        self.assertIsNone(
            album_facts(artist="A", album="B", run=_runner_returning(0, "10\t-1\t1994"))
        )

    def test_a_zero_year_is_reported_as_no_year(self) -> None:
        # Music.app returns 0 for a track with no year tag. 0 is not a year, so the
        # absence has to survive as None all the way to the record, where a consumer
        # can omit the year rather than print it.
        facts = album_facts(
            artist="Fictionals", album="Blue", run=_runner_returning(0, "10\t2\t0")
        )
        assert facts is not None
        self.assertIsNone(facts.year)

    def test_a_non_integer_year_is_no_answer(self) -> None:
        self.assertIsNone(
            album_facts(artist="A", album="B", run=_runner_returning(0, "10\t2\tx"))
        )

    def test_a_negative_year_is_no_answer(self) -> None:
        self.assertIsNone(
            album_facts(artist="A", album="B", run=_runner_returning(0, "10\t2\t-5"))
        )

    def test_a_two_field_reply_is_no_answer(self) -> None:
        # Counts with no year field: accepting them would silently lose the year.
        self.assertIsNone(
            album_facts(artist="A", album="B", run=_runner_returning(0, "10\t2"))
        )

    def test_the_timeout_reaches_the_seam(self) -> None:
        seen: list[float] = []

        def run(_args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
            seen.append(timeout)
            return _completed(0, "1\t1\t1999")

        album_facts(artist="A", album="B", run=run, timeout=12.5)
        self.assertEqual(seen, [12.5])


class QueryShapeTest(unittest.TestCase):
    """What the generated AppleScript actually asks Music.app.

    These pin rules, not implementation detail: the two in the module docstring, and
    the escaping of a name into a string literal. A rewrite that looks right and
    quietly drops one produces a tool that returns plausible, wrong numbers on a real
    library, or a script that no longer compiles.
    """

    def test_the_query_constrains_both_artist_and_album(self) -> None:
        # Album alone is not enough: two albums can share a title across different
        # artists, and compilations make it worse.
        script = _script_for("Fictionals", "Blue")
        self.assertIn('album artist is "Fictionals"', script)
        self.assertIn('album is "Blue"', script)

    def test_the_default_query_reads_favorited_not_rating(self) -> None:
        # Measured against a real library: `rating kind is user and rating > 0`
        # matched almost none of the tracks; `favorited is true` matched a large
        # share. A star count keyed on `rating` reads 0 of N on nearly every album,
        # so `rating` is reached only on request (tests/test_star_rating.py).
        script = _script_for("Fictionals", "Blue")
        self.assertIn("favorited is true", script)
        self.assertNotIn("rating", script)

    def test_the_query_asks_for_the_year(self) -> None:
        self.assertIn("year of", _script_for("Fictionals", "Blue"))

    def test_the_year_is_not_read_from_the_first_matched_track_alone(self) -> None:
        # The defect this pins: reading only `item 1` recorded no year whenever the
        # first track Music.app returned was untagged, however many of the album's
        # other tracks carried one.
        self.assertNotIn("item 1 of", _script_for("Fictionals", "Blue"))

    def test_the_year_is_the_latest_tag_across_every_matched_track(self) -> None:
        # Text, not behavior: no faked test can run AppleScript. The loop's semantics
        # were proven through the real parser on a tell-free copy, and only the live
        # test runs it against Music.app. What this pins is that every matched track
        # is visited and the LARGER year is kept -- so an untagged track's 0 never
        # wins, and flipping the comparison to keep the earliest fails here.
        lines = [
            line.strip() for line in _script_for("Fictionals", "Blue").splitlines()
        ]
        self.assertIn("repeat with albTrk in albTracks", lines)
        self.assertIn("set trkYr to year of albTrk", lines)
        self.assertIn("if trkYr > yr then set yr to trkYr", lines)

    def test_no_script_variable_is_a_known_music_dictionary_term(self) -> None:
        # Binding a variable named after a term in Music's dictionary fails at RUNTIME
        # as "Access not allowed. (-10003)", which reads like a denied automation
        # permission. Both known collisions passed every faked test and were caught
        # only live; this keeps them from coming back by a rename.
        bound = re.findall(r"\b(?:set|repeat with)\s+(\w+)", _script_for("A", "B"))
        self.assertTrue(bound)  # the pattern found the bindings; not vacuous
        for name in bound:
            with self.subTest(name=name):
                self.assertNotIn(name, _KNOWN_DICTIONARY_COLLISIONS)

    def test_the_query_does_not_use_the_removed_loved_property(self) -> None:
        # `loved` was RENAMED to `favorited`; a script using it fails outright with
        # "The variable loved is not defined. (-2753)".
        self.assertNotIn("loved", _script_for("Fictionals", "Blue"))

    def test_a_double_quote_in_a_name_is_escaped(self) -> None:
        # Unescaped, this closes the AppleScript string literal early and the script
        # fails to compile -- or worse, changes what is queried.
        script = _script_for("Fictionals", 'The "Blue" Album')
        self.assertIn('album is "The \\"Blue\\" Album"', script)

    def test_a_backslash_in_a_name_is_escaped(self) -> None:
        # A lone backslash is doubled. Unescaped, it starts an escape sequence, and
        # `\D` is not one AppleScript knows: a compile error (measured with osascript).
        script = _script_for("AC\\DC", "Back In Black")
        self.assertIn('album artist is "AC\\\\DC"', script)

    def test_a_backslash_before_a_quote_survives_both_escapes(self) -> None:
        # The ordering trap made concrete: a naive quote-then-backslash pass turns
        # this into a literal that no longer means what the name says.
        script = _script_for("X", 'a\\"b')
        self.assertIn('album is "a\\\\\\"b"', script)

    def test_a_newline_in_a_name_is_escaped(self) -> None:
        # The escape denotes the same character a raw newline would -- a raw one also
        # compiles, to the same string (measured with osascript) -- so this pins only
        # that the generated script keeps each statement on one line.
        script = _script_for("X", "two\nlines")
        self.assertIn('album is "two\\nlines"', script)


class CommandLineTest(unittest.TestCase):
    """The CLI wrapper: named options, JSON on stdout, documented exit codes."""

    def test_success_writes_the_exact_record_and_narrates_on_stderr(self) -> None:
        # The stdout bytes exactly, not a parsed equivalent: a parse accepts any
        # indentation, and the two-space form is what a shell pipeline and the
        # sibling tool's record share. The stderr line is the whole of what a
        # terminal reader sees, so it is pinned as a line rather than a substring.
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
            code = album_stats.main(
                ["--artist", "Fictionals", "--album", "Blue"],
                run=_runner_returning(0, "10\t2\t1994"),
            )
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout.getvalue(),
            '{\n  "tracks": 10,\n  "favorited": 2,\n  "year": 1994\n}\n',
        )
        self.assertEqual(stderr.getvalue(), "album_stats: 2 of 10 favorited\n")

    def test_a_missing_artist_or_album_is_a_usage_error_before_any_query(
        self,
    ) -> None:
        # Both are required: an album alone is ambiguous across artists (the
        # measured finding QueryShapeTest pins), and an artist alone names no album.
        # Refused by argparse, exit 2, with the seam never reached.
        for argv in (["--album", "Blue"], ["--artist", "Fictionals"]):
            with self.subTest(argv=argv):
                run, seen = _recording_runner("10\t2\t1994")
                stderr = io.StringIO()
                with (
                    mock.patch("sys.stdout", io.StringIO()),
                    mock.patch("sys.stderr", stderr),
                    self.assertRaises(SystemExit) as exited,
                ):
                    album_stats.main(argv, run=run)
                self.assertEqual(exited.exception.code, 2)
                self.assertIn("required", stderr.getvalue())
                self.assertEqual(seen, [])

    def test_no_answer_exits_one_and_writes_no_record(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
            code = album_stats.main(
                ["--artist", "Nobody", "--album", "Nothing"],
                run=_runner_returning(0, "0\t0\t0"),
            )
        self.assertEqual(code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("album_stats:", stderr.getvalue())

    def test_the_timeout_option_reaches_the_seam(self) -> None:
        seen: list[float] = []

        def run(_args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
            seen.append(timeout)
            return _completed(0, "1\t1\t1999")

        with (
            mock.patch("sys.stdout", io.StringIO()),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            album_stats.main(
                ["--artist", "A", "--album", "B", "--timeout", "7.5"], run=run
            )
        self.assertEqual(seen, [7.5])

    def test_a_timeout_below_one_second_is_still_a_valid_timeout(self) -> None:
        # The floor is "positive", not "at least one": a fast library can be asked
        # for a sub-second bound, so a value like 0.5 must reach the seam unchanged.
        run, seen = _recording_runner("1\t1\t1999")
        with (
            mock.patch("sys.stdout", io.StringIO()),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            code = album_stats.main(
                ["--artist", "A", "--album", "B", "--timeout", "0.5"], run=run
            )
        self.assertEqual(code, 0)
        self.assertEqual(seen, [0.5])

    def test_a_timeout_that_cannot_bound_a_query_is_a_usage_error(self) -> None:
        # `bounded_run` expires a zero or negative timeout instantly, so without a
        # floor `--timeout 0` reported "no counts ... Music.app could not answer" on
        # exit 1 -- a usage error disguised as a data answer. A non-finite value is
        # no bound at all. Each is refused at parse time, exit 2, with the seam never
        # reached -- the same treatment a non-numeric value already gets.
        for value in ("0", "-1", "nan", "inf"):
            with self.subTest(timeout=value):
                run, seen = _recording_runner("10\t2\t1994")
                stderr = io.StringIO()
                with (
                    mock.patch("sys.stdout", io.StringIO()),
                    mock.patch("sys.stderr", stderr),
                    self.assertRaises(SystemExit) as exited,
                ):
                    album_stats.main(
                        ["--artist", "A", "--album", "B", "--timeout", value], run=run
                    )
                self.assertEqual(exited.exception.code, 2)
                self.assertIn("--timeout", stderr.getvalue())
                self.assertEqual(seen, [])

    def test_the_default_timeout_is_the_sibling_lookups_bound_not_a_copy(self) -> None:
        # Both tools' `whose` clauses visit the whole library, so they share ONE
        # bound. A restated 60.0 here agrees today and drifts on the next edit to
        # either side; pinned on the function default and the CLI's alike.
        shared = recently_added._MUSIC_TIMEOUT_SECONDS
        kwdefaults = album_facts.__kwdefaults__
        assert kwdefaults is not None  # narrows for mypy; every kw-only param has one
        self.assertEqual(kwdefaults["timeout"], shared)
        self.assertEqual(album_stats.build_parser().get_default("timeout"), shared)

    def test_help_shows_every_default_and_a_prerequisites_epilog(self) -> None:
        text = album_stats.build_parser().format_help()
        self.assertIn("(default:", text)
        self.assertIn("Prerequisites:", text)
        self.assertIn("Exit codes:", text)

    def test_the_parser_builds_its_formatter_on_the_shared_one(self) -> None:
        # Pinned as a BINDING, not a rendering: on 3.13 and later argparse already
        # drops the bogus "(default: None)" from a required option, so a --help
        # assertion here would pass just as well with the shared base removed
        # ("The version trap" in help_formatter.md). The floor is 3.12,
        # below that fix, and `--artist`/`--album` are both required -- so this tool
        # ships the shim or lies to every operator on a floor interpreter.
        #
        # An INSTANCE check, not assertIs: the local formatter MIXES the shared base
        # with RawDescriptionHelpFormatter, which is what keeps the epilog's own line
        # breaks (see _HelpFormatter's docstring), so the assertion is "built on", not
        # "is". Instantiated the way argparse itself does because `formatter_class` is
        # typed as a callable (`_FormatterClass`) rather than a `type`, which
        # `issubclass` rejects.
        self.assertIsInstance(
            album_stats.build_parser().formatter_class(prog="x"),
            help_formatter.ReqAwareDefaultsFormatter,
        )


#: The grouped-suite dir beside this file, which the gate reaches only through it.
_SUITE_DIR = Path(__file__).resolve().parent / "tests"


def _grouped_suite() -> unittest.TestSuite:
    """Every `test_*.py` under `tests/`, loaded as top-level modules."""
    loader = unittest.TestLoader()
    return loader.discover(str(_SUITE_DIR), top_level_dir=str(_SUITE_DIR))


def load_tests(
    _loader: unittest.TestLoader, tests: unittest.TestSuite, _pattern: str | None
) -> unittest.TestSuite:
    """unittest's hook: run this module's own tests plus every grouped suite."""
    return unittest.TestSuite([tests, _grouped_suite()])


def _test_ids(suite: unittest.TestSuite) -> set[str]:
    """Every test id in a possibly-nested suite."""
    ids: set[str] = set()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            ids |= _test_ids(item)
        else:
            ids.add(item.id())
    return ids


class GroupedSuiteWiringTest(unittest.TestCase):
    """This module's REAL test load carries every test `tests/` holds.

    Built from `loadTestsFromModule` -- what a bare run and the gate's coverage run use,
    and what honors `load_tests` -- so deleting the hook fails here rather than leaving
    the grouped suites silently unrun. It compares against discovery rather than a fixed
    floor because an export's proof run deletes `tests/test_live_literal.py` first (it is
    `uncontainable` there), and a floor would fail on exactly that deliberate absence.
    """

    def test_the_module_load_includes_every_grouped_test(self) -> None:
        loaded = _test_ids(
            unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
        )
        self.assertLessEqual(_test_ids(_grouped_suite()), loaded)


if __name__ == "__main__":
    unittest.main()
