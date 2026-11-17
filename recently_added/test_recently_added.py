"""Tests for recently_added: Apple Music's own "date added" via AppleScript.

Every test here drives a fake `run`: nothing in this file spawns a real `osascript`
process or touches Music.app. `_real_run` is the real-process seam and is exercised
end to end only by the live tests of the separate media_feeds project, such as
`album_scan/tests/test_live_music.py`, as `cover_art.py`'s `_real_fetch` there is
proven only by `cover_art/tests/test_live_artwork.py`.

`load_tests` below also runs every suite in `tests/`: the row-boundary tests, and the
escaped-field tests, which read tag_refresh's shared escape to pin this tool's copy of
it. A runner that runs only each folder's top-level test file reaches them only
through this file.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
import unittest
from pathlib import Path

import recently_added
from recently_added import AlbumRef, newest_albums_from_music


def _completed(returncode: int, stdout: str) -> subprocess.CompletedProcess[str]:
    """Build a fake `osascript` result without spawning a real process."""
    return subprocess.CompletedProcess(
        args=["osascript"], returncode=returncode, stdout=stdout, stderr=""
    )


class NewestAlbumsFromMusicTest(unittest.TestCase):
    """The never-raises contract: every failure mode below returns `[]`.

    The AppleScript emits one row per track (Music.app has no per-album "date
    added"), so these also pin the collapse before ranking. A duplicate album
    cannot appear in a result of size one, so the collapse tests ask for more.
    """

    def test_a_single_valid_line_resolves_to_its_album(self) -> None:
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(
                0, "2001-03-15T10:00:00\tThe Invented Quartet\tPlaceholder Album\n"
            )

        refs = newest_albums_from_music(1, run=run)
        self.assertEqual(
            refs,
            [
                AlbumRef(
                    artist="The Invented Quartet",
                    album="Placeholder Album",
                    added=dt.date(2001, 3, 15),
                )
            ],
        )

    def test_a_twelve_track_album_appears_once_not_twelve_times(self) -> None:
        """The AppleScript emits one row per track. Without a dedupe by
        (artist, album), --count 3 on a freshly-added album returns the same
        album three times.
        """
        # Twelve rows, one per track. Two-digit minutes on purpose: `10:0{n}` would
        # read "10:010:00" from the tenth row on, which is not a timestamp at all,
        # and the parser would skip those rows as malformed rather than dedupe them.
        rows = "\n".join(
            f"2001-03-01T10:{n:02d}:00\tThe Band\tOne Album" for n in range(12)
        )

        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(0, rows)

        refs = newest_albums_from_music(3, run=run)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].album, "One Album")

    def test_an_album_takes_its_newest_track_as_its_added_date(self) -> None:
        # An album whose tracks were added on different days must report the later
        # date: the point of grouping before ranking, not merely deduplicating.
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(
                0,
                "2001-03-01T10:00:00\tThe Band\tOne Album\n"
                "2001-03-03T10:00:00\tThe Band\tOne Album",
            )

        refs = newest_albums_from_music(1, run=run)
        self.assertEqual(refs[0].added, dt.date(2001, 3, 3))

    def test_an_earlier_duplicate_row_arriving_second_does_not_override_the_newest(
        self,
    ) -> None:
        # The mirror of the test above: proves the false arm of the per-album
        # "is this row newer than what we already kept" comparison is also
        # reachable and correct, not merely "whichever row is seen last wins".
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(
                0,
                "2001-03-03T10:00:00\tThe Band\tOne Album\n"
                "2001-03-01T10:00:00\tThe Band\tOne Album",
            )

        refs = newest_albums_from_music(1, run=run)
        self.assertEqual(refs[0].added, dt.date(2001, 3, 3))

    def test_albums_come_back_newest_first(self) -> None:
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(
                0,
                "2001-03-01T10:00:00\tA\tOlder\n2001-03-05T10:00:00\tB\tNewer",
            )

        refs = newest_albums_from_music(2, run=run)
        self.assertEqual([r.album for r in refs], ["Newer", "Older"])

    def test_the_newest_album_leads_even_when_its_name_sorts_first(self) -> None:
        # The ranking key is the date, not the album reference. In the test above
        # the two orders agree by accident ("B" > "A" and newer > older), so a
        # rank keyed on the reference passes it. Here they disagree: the newest
        # album's artist sorts first alphabetically, so only a date-keyed rank
        # puts it first.
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(
                0,
                "2001-03-01T10:00:00\tThe Stand-In Trio\tFiller Songs\n"
                "2001-03-05T10:00:00\tThe Ample Ensemble\tDemo Tape\n",
            )

        refs = newest_albums_from_music(2, run=run)
        self.assertEqual([r.album for r in refs], ["Demo Tape", "Filler Songs"])

    def test_asking_for_more_than_the_result_holds_returns_what_exists(self) -> None:
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(
                0, "2001-03-15T10:00:00\tThe Invented Quartet\tPlaceholder Album\n"
            )

        refs = newest_albums_from_music(5, run=run)
        self.assertEqual(len(refs), 1)

    def test_a_line_with_the_wrong_field_count_is_skipped_not_fatal(self) -> None:
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(
                0,
                "not-a-valid-line-at-all\n2001-03-15T10:00:00\tThe Invented Quartet\tPlaceholder Album\n",
            )

        refs = newest_albums_from_music(1, run=run)
        self.assertEqual(refs[0].artist, "The Invented Quartet")

    def test_a_line_whose_date_will_not_parse_is_skipped_not_fatal(self) -> None:
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(
                0,
                "not-a-real-date\tSome Artist\tSome Album\n"
                "2001-03-15T10:00:00\tThe Invented Quartet\tPlaceholder Album\n",
            )

        refs = newest_albums_from_music(1, run=run)
        self.assertEqual(refs[0].artist, "The Invented Quartet")

    def test_an_empty_album_artist_is_skipped_not_grouped_as_a_real_album(self) -> None:
        # AppleScript reports an unset `album artist` (a compilation, a track with no
        # album artist tag) as "", not an error. Without this guard an empty-artist
        # row would group and rank as a genuine album, AlbumRef(artist="",
        # album="Untitled Compilation"), so --source auto would never fall back to
        # the folder scan, and the record would carry a blank artist.
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(
                0,
                "2001-03-15T10:00:00\t\tUntitled Compilation\n"
                "2001-02-14T09:00:00\tThe Ample Ensemble\tDemo Tape\n",
            )

        refs = newest_albums_from_music(1, run=run)
        self.assertEqual(
            refs,
            [
                AlbumRef(
                    artist="The Ample Ensemble",
                    album="Demo Tape",
                    added=dt.date(2001, 2, 14),
                )
            ],
        )

    def test_an_empty_album_is_skipped_not_grouped_as_a_real_album(self) -> None:
        # The mirror case: a single with an empty album.
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(
                0,
                "2001-03-15T10:00:00\tSome Artist\t\n"
                "2001-02-14T09:00:00\tThe Ample Ensemble\tDemo Tape\n",
            )

        refs = newest_albums_from_music(1, run=run)
        self.assertEqual(refs[0].album, "Demo Tape")

    def test_every_candidate_with_an_empty_field_yields_no_albums(self) -> None:
        # Not an accidental empty result: this is the caller's fallback signal
        # working as designed when nothing complete is available: --source auto
        # then falls back to the folder scan rather than writing a record with a
        # blank field.
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(
                0,
                "2001-03-15T10:00:00\t\tUntitled Compilation\n"
                "2001-02-14T09:00:00\tSome Artist\t\n",
            )

        self.assertEqual(newest_albums_from_music(1, run=run), [])

    def test_a_quote_in_the_album_name_parses_correctly(self) -> None:
        # The script never interpolates track text into the AppleScript source (only
        # the integer lookback-days constant is interpolated), so a quote in a real
        # album title poses no escaping risk to the script itself. This proves the
        # parse side is equally unaffected: a quote is not one of the two delimiters
        # (tab, linefeed), so it must pass through byte-for-byte rather than being
        # stripped or mis-split.
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(0, '2001-03-15T10:00:00\tSome Artist\tThe "Best" Album\n')

        refs = newest_albums_from_music(1, run=run)
        self.assertEqual(refs[0].album, 'The "Best" Album')

    def test_a_tab_embedded_in_a_name_causes_that_line_to_be_skipped(self) -> None:
        # Tab is the field separator (see `_MUSIC_SCRIPT`'s comment: not "|", which
        # has appeared in band names). The script escapes a tab inside a name, so a
        # raw one comes only from a reply it did not write; such a line is skipped
        # (it no longer has exactly 3 fields), never a mis-split record, falling
        # through to the next complete, valid candidate exactly like the empty-field
        # and bad-date cases above, not a crash and not a corrupted field boundary.
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(
                0,
                "2001-03-15T10:00:00\tSome\tArtist\tWith An Embedded Tab\n"
                "2001-02-14T09:00:00\tThe Ample Ensemble\tDemo Tape\n",
            )

        refs = newest_albums_from_music(1, run=run)
        self.assertEqual(refs[0].artist, "The Ample Ensemble")

    def test_empty_output_yields_no_albums(self) -> None:
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(0, "")

        self.assertEqual(newest_albums_from_music(1, run=run), [])

    def test_output_with_only_malformed_lines_yields_no_albums(self) -> None:
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(0, "garbage\nmore garbage\n")

        self.assertEqual(newest_albums_from_music(1, run=run), [])

    def test_a_nonzero_exit_yields_no_albums_regardless_of_stdout(self) -> None:
        # Covers Music.app not running, not scriptable, or automation permission
        # denied: osascript reports all three as a non-zero exit with a message
        # on stderr, which this function never inspects: only the exit code gates.
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            return _completed(
                1, "2001-03-15T10:00:00\tThe Invented Quartet\tPlaceholder Album\n"
            )

        self.assertEqual(newest_albums_from_music(1, run=run), [])

    def test_the_runner_raising_oserror_yields_no_albums(self) -> None:
        # `osascript` itself absent from this host: the spawn raises before Music.app
        # is ever asked anything.
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError("osascript: command not found")

        self.assertEqual(newest_albums_from_music(1, run=run), [])

    def test_the_runner_timing_out_yields_no_albums(self) -> None:
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(cmd=["osascript"], timeout=_timeout)

        self.assertEqual(newest_albums_from_music(1, run=run), [])

    def test_the_runner_refusing_its_argv_yields_no_albums(self) -> None:
        # `subprocess.Popen` raises ValueError, not OSError, for an argv element
        # holding a NUL: the one exception the seam raises that is neither an
        # OSError nor a SubprocessError, and the one that escaped this contract.
        def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            raise ValueError("embedded null byte")

        self.assertEqual(newest_albums_from_music(1, run=run), [])

    def test_the_timeout_is_passed_through_to_the_runner(self) -> None:
        seen: list[float] = []

        def run(_args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
            seen.append(timeout)
            return _completed(0, "")

        newest_albums_from_music(1, run=run, timeout=2.5)
        self.assertEqual(seen, [2.5])

    def test_the_command_invokes_osascript(self) -> None:
        seen: list[list[str]] = []

        def run(args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            seen.append(args)
            return _completed(0, "")

        newest_albums_from_music(1, run=run)
        self.assertEqual(seen[0][0], "osascript")

    def test_the_script_coerces_the_date_to_isot_not_a_locale_string(self) -> None:
        # Nothing else here pins the `«class isot»` coercion, so a regression to plain
        # `as string`, which is locale-dependent ("Thursday, March 15, 2001 at
        # 11:00:33 PM" on one machine, something else entirely on another) and would
        # silently fail the date-shape check for every row on any host with a
        # different locale, would stay green here.
        seen: list[list[str]] = []

        def run(args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            seen.append(args)
            return _completed(0, "")

        newest_albums_from_music(1, run=run)
        self.assertIn("«class isot»", seen[0][2])

    def test_real_run_is_the_default_runner(self) -> None:
        # Pins the injection contract (mirrors cover_art.artwork_url's `fetch`
        # default) without calling it: `_real_run` itself is only exercised by
        # the live smoke tests.
        kwdefaults = recently_added.newest_albums_from_music.__kwdefaults__
        assert kwdefaults is not None  # narrows for mypy; every kw-only param has one
        self.assertIs(kwdefaults["run"], recently_added._real_run)


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
    """This module's real test load carries every test `tests/` holds.

    Built from `loadTestsFromModule` (what a bare run and a coverage run use, and what
    honors `load_tests`), so deleting the hook fails here rather than leaving the
    grouped suites silently unrun.
    """

    def test_the_module_load_includes_every_grouped_test(self) -> None:
        loaded = _test_ids(
            unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
        )
        self.assertLessEqual(_test_ids(_grouped_suite()), loaded)


if __name__ == "__main__":
    unittest.main()
