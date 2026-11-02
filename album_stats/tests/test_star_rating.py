"""Tests for album_stats' star-rating mode: `min_stars` and `--favorite-min-stars`.

The default favorites signal is Music.app's `favorited`; a caller may instead ask for
tracks the listener rated at least N stars. Music.app stores a rating as 0-100, twenty
per star, so N stars is `rating >= N*20`, and only a user rating counts: Music can
derive a track rating from an album rating (see album_stats.md, "Why `favorited`, and
not `rating`").

Every test here drives a fake `run`: nothing spawns `osascript` or touches Music.app.
The rating script meets the real Music.app only in `tests/test_live_star_rating.py`,
run by hand against a real library. These tests pin its text, and
that it stays the favorited script's structure line for line, because the
dictionary-collision trap (`-10003 Access not allowed`) is invisible to any faked test.

Reached through `test_album_stats.load_tests`, which runs every suite in this folder.
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import album_stats  # noqa: E402 - import follows the sys.path bootstrap above
from album_stats import AlbumFacts, album_facts  # noqa: E402 - as above

# Words measured to collide with Music's scripting dictionary when bound as a script
# variable (see album_stats.md, "Why a `whose` clause, and not a loop").
_KNOWN_DICTIONARY_COLLISIONS = frozenset({"matched", "computed"})

#: Music.app's rating scale: 0-100, twenty per star.
_PER_STAR = 20

_REPLY = "10\t4\t1994"


def _completed(returncode: int, stdout: str) -> subprocess.CompletedProcess[str]:
    """Build a fake `osascript` result without spawning a real process."""
    return subprocess.CompletedProcess(
        args=["osascript"], returncode=returncode, stdout=stdout, stderr=""
    )


def _capturing_runner() -> tuple[album_stats.Runner, list[str]]:
    """A fake `run` that records each script it is handed and answers `_REPLY`."""
    scripts: list[str] = []

    def run(args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        scripts.append(args[-1])
        return _completed(0, _REPLY)

    return run, scripts


def _script_for(min_stars: int | None) -> str:
    """The AppleScript `album_facts` would send for a fixed album at `min_stars`."""
    run, scripts = _capturing_runner()
    album_facts(artist="Fictionals", album="Blue", run=run, min_stars=min_stars)
    return scripts[0]


class RatingQueryShapeTest(unittest.TestCase):
    """What the rating script asks Music.app, and what it must never ask."""

    def test_the_rating_query_counts_user_ratings_at_the_star_threshold(self) -> None:
        # `rating kind is user` is mandatory: counting album-derived ratings would
        # credit tracks the listener never rated.
        for stars in range(1, 6):
            with self.subTest(stars=stars):
                script = _script_for(stars)
                self.assertIn(
                    f"rating kind is user and rating >= {stars * _PER_STAR})", script
                )
                self.assertNotIn("favorited", script)

    def test_the_rating_query_keeps_the_favorited_scripts_shape(self) -> None:
        # Only the qualifying clause changes: the album match, the track count, the
        # year loop and the reply are the favorited script's, line for line, so the
        # rating script cannot drift into a structure the live test never ran.
        favorited = _script_for(None).splitlines()
        rating = _script_for(4).splitlines()
        self.assertEqual(len(favorited), len(rating))
        differing = [
            (left, right) for left, right in zip(favorited, rating) if left != right
        ]
        self.assertEqual(len(differing), 1)
        left, right = differing[0]
        self.assertEqual(
            left.replace("favorited is true", "rating kind is user and rating >= 80"),
            right,
        )

    def test_neither_script_uses_the_removed_loved_property(self) -> None:
        # `loved` was renamed to `favorited`; a script using it fails outright with
        # "The variable loved is not defined. (-2753)".
        for min_stars in (None, 1, 5):
            with self.subTest(min_stars=min_stars):
                self.assertNotIn("loved", _script_for(min_stars))

    def test_no_rating_script_variable_is_a_known_dictionary_term(self) -> None:
        bound = re.findall(r"\b(?:set|repeat with)\s+(\w+)", _script_for(3))
        self.assertTrue(bound)  # the pattern found the bindings; not vacuous
        for name in bound:
            with self.subTest(name=name):
                self.assertNotIn(name, _KNOWN_DICTIONARY_COLLISIONS)


class MinStarsContractTest(unittest.TestCase):
    """The settled interface: `album_facts(artist, album, *, run, min_stars)`."""

    def test_a_star_threshold_outside_one_to_five_is_refused(self) -> None:
        # A programming error, not a Music.app outcome, so it raises rather than
        # hiding behind the never-raises `None`. A bool is refused too: `True` is an
        # int to Python and would otherwise quietly mean one star.
        run, scripts = _capturing_runner()
        for bad in (0, 6, -1, True):
            with self.subTest(min_stars=bad), self.assertRaises(ValueError):
                album_facts(artist="A", album="B", run=run, min_stars=bad)
        self.assertEqual(scripts, [])

    def test_artist_and_album_may_be_passed_positionally(self) -> None:
        run, _scripts = _capturing_runner()
        facts = album_facts("Fictionals", "Blue", run=run, min_stars=3)
        self.assertEqual(facts, AlbumFacts(tracks=10, favorited=4, year=1994))

    def test_min_stars_defaults_to_the_favorited_signal(self) -> None:
        kwdefaults = album_facts.__kwdefaults__
        assert kwdefaults is not None  # narrows for mypy; every kw-only param has one
        self.assertIsNone(kwdefaults["min_stars"])

    def test_zero_qualifying_tracks_is_a_real_answer(self) -> None:
        # "Asked, none rated that high" is 0, never None: None means Music.app
        # could not be asked at all, and a consumer must tell the two apart.
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(0, "10\t0\t1994")

        facts = album_facts(artist="A", album="B", run=run, min_stars=5)
        self.assertEqual(facts, AlbumFacts(tracks=10, favorited=0, year=1994))


class StarRatingCommandLineTest(unittest.TestCase):
    """`--favorite-min-stars N` maps onto `min_stars`."""

    def test_the_option_switches_to_the_rating_query(self) -> None:
        run, scripts = _capturing_runner()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
            code = album_stats.main(
                ["--artist", "A", "--album", "B", "--favorite-min-stars", "4"], run=run
            )
        self.assertEqual(code, 0)
        self.assertIn("rating kind is user and rating >= 80", scripts[0])
        # The record's shape does not change with the signal; only the narration does.
        self.assertEqual(
            stdout.getvalue(),
            '{\n  "tracks": 10,\n  "favorited": 4,\n  "year": 1994\n}\n',
        )
        self.assertEqual(
            stderr.getvalue(), "album_stats: 4 of 10 rated at least 4 stars\n"
        )

    def test_a_one_star_threshold_reads_in_the_singular(self) -> None:
        run, _scripts = _capturing_runner()
        stderr = io.StringIO()
        with mock.patch("sys.stdout", io.StringIO()), mock.patch("sys.stderr", stderr):
            album_stats.main(
                ["--artist", "A", "--album", "B", "--favorite-min-stars", "1"], run=run
            )
        self.assertEqual(
            stderr.getvalue(), "album_stats: 4 of 10 rated at least 1 star\n"
        )

    def test_without_the_option_the_cli_reads_favorited(self) -> None:
        self.assertIsNone(album_stats.build_parser().get_default("favorite_min_stars"))
        run, scripts = _capturing_runner()
        with (
            mock.patch("sys.stdout", io.StringIO()),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            album_stats.main(["--artist", "A", "--album", "B"], run=run)
        self.assertIn("favorited is true", scripts[0])

    def test_a_star_count_outside_one_to_five_is_a_usage_error(self) -> None:
        # Refused at parse time, exit 2, with the seam never reached: the same
        # treatment `--timeout` gives a value that cannot bound a query.
        for value in ("0", "6", "x", "2.5"):
            with self.subTest(stars=value):
                run, scripts = _capturing_runner()
                stderr = io.StringIO()
                argv = ["--artist", "A", "--album", "B", "--favorite-min-stars", value]
                with (
                    mock.patch("sys.stdout", io.StringIO()),
                    mock.patch("sys.stderr", stderr),
                    self.assertRaises(SystemExit) as exited,
                ):
                    album_stats.main(argv, run=run)
                self.assertEqual(exited.exception.code, 2)
                self.assertIn("--favorite-min-stars", stderr.getvalue())
                self.assertEqual(scripts, [])

    def test_help_names_the_option(self) -> None:
        self.assertIn("--favorite-min-stars", album_stats.build_parser().format_help())

    def test_help_shows_no_default_for_the_unset_option(self) -> None:
        # Its unset default is None, which no one could type: the help says what
        # leaving it out means, as every sibling CLI's does, not "(default: None)".
        self.assertNotIn("default: None", album_stats.build_parser().format_help())


if __name__ == "__main__":
    unittest.main()
