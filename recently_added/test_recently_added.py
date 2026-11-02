"""Tests for recently_added: Apple Music's own "date added" via AppleScript.

Every test here drives a fake `run`: nothing in this file spawns a real `osascript`
process or touches Music.app. `_real_run` is the real-process seam and is exercised
end to end only by the live tests of the separate media_feeds project, such as
`album_scan/tests/test_live_music.py`, as `cover_art.py`'s `_real_fetch` there is
proven only by `cover_art/tests/test_live_artwork.py`.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
import unittest
import unittest.mock

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
        # has appeared in band names). When a name does contain a tab, the failure
        # mode is to skip the malformed line (it no longer has exactly 3 fields),
        # never a mis-split record, falling through to the next complete, valid
        # candidate exactly like the empty-field and bad-date cases above, not a
        # crash and not a corrupted field boundary.
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


#: The reference day every test below injects. Fixed, and deliberately far from any
#: date these tests will ever run on: a row's distance from "today" is then a property
#: of the test, and a call site that quietly read the real clock instead of the
#: injected day would keep a row dated two days past this one (twenty-odd years in
#: its past) and fail here, rather than agreeing with the injection by coincidence.
_TODAY = dt.date(2000, 6, 15)


def _rows(*lines: str) -> recently_added.Runner:
    """A fake `run` whose Music.app answers with exactly these rows, one per line."""

    def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        return _completed(0, "".join(f"{line}\n" for line in lines))

    return run


class RowBoundaryTest(unittest.TestCase):
    """Where one Music.app row ends and what a row is allowed to claim.

    The AppleScript joins each track's date, album artist and album with `tab` and
    ends the row with `linefeed`, with the tag text itself concatenated unescaped.
    A tag can therefore carry the row terminator, and whatever follows it in that
    tag is read as a row of its own, one whose every field, the date included,
    the tag's author chose.
    """

    def test_a_forged_future_dated_row_cannot_outrank_a_genuine_one(self) -> None:
        # An album tag holding a line break, then a date-artist-album triple dated
        # far in the future: read as a row, it ranked newest forever, ahead of every
        # real addition. The genuine newest row must win, and the forged row must be
        # absent at any count, not merely ranked lower.
        run = _rows(
            "2000-06-01T10:00:00\tThe Invented Quartet\tPlaceholder Album",
            "2000-05-01T10:00:00\tArtist A\tAn Album\n"
            "9999-12-31T23:59:59\tForged Artist\tForged Album",
        )
        refs = newest_albums_from_music(5, run=run, today=_TODAY)
        self.assertEqual(refs[0].album, "Placeholder Album")
        self.assertNotIn("Forged Artist", [ref.artist for ref in refs])

    def test_a_forged_row_in_another_iso_shape_cannot_outrank_a_genuine_one(
        self,
    ) -> None:
        # `fromisoformat` reads far more than the one shape `«class isot» as string`
        # emits. A check that parses a row only to bound it, then ranks the raw
        # string, lets another shape pass the bound and sort wherever its characters
        # land: `'0'` and `'W'` both sort above `'-'`, and a separator other than `T`
        # leaves the digits in place. Each row below parses inside the future bound
        # and sorts above the genuine one, so each took the newest slot. That is
        # the bypass the future-date fix alone does not close, its own test planting
        # only the `9999-` shape.
        for forged in (
            "20000101T000000",  # the basic form, no separators
            "2000-W20-1T00:00:00",  # an ISO week date
            "2000-06-16X00:00:00",  # any single character where the `T` goes
        ):
            with self.subTest(forged=forged):
                run = _rows(
                    "2000-06-14T10:00:00\tThe Invented Quartet\tPlaceholder Album",
                    f"{forged}\tForged Artist\tForged Album",
                )
                refs = newest_albums_from_music(5, run=run, today=_TODAY)
                self.assertEqual(refs[0].album, "Placeholder Album")
                self.assertNotIn("Forged Artist", [ref.artist for ref in refs])

    def test_a_row_shaped_like_a_date_but_holding_impossible_numbers_is_skipped(
        self,
    ) -> None:
        # The shape check passes a row the parser still refuses, so both refusals
        # have to hold: this row is all digits in all the right places and names a
        # thirteenth month.
        run = _rows(
            "2000-13-45T99:99:99\tArtist A\tImpossible",
            "2000-06-01T10:00:00\tThe Invented Quartet\tPlaceholder Album",
        )
        refs = newest_albums_from_music(2, run=run, today=_TODAY)
        self.assertEqual([ref.album for ref in refs], ["Placeholder Album"])

    def test_the_rank_is_keyed_on_the_parsed_date_not_the_raw_stamp(self) -> None:
        # The shape check above makes the two keys agree (every stamp it admits
        # sorts as its own parsed value), so nothing else here can tell them apart,
        # and the parsed key would be deletable at full coverage. It is kept because
        # it is what stops a later loosening of the shape from re-opening the bypass,
        # and that is the guarantee this test pins: with the shape check widened to
        # admit the basic form, a raw-string rank puts the forged row first again
        # while a parsed rank still refuses it the slot.
        loose = re.compile(r"[0-9A-Z:-]+")
        run = _rows(
            "2000-06-14T10:00:00\tThe Invented Quartet\tPlaceholder Album",
            "20000101T000000\tForged Artist\tForged Album",
        )
        with unittest.mock.patch.object(recently_added, "_ISOT_STAMP", loose):
            refs = newest_albums_from_music(5, run=run, today=_TODAY)
        self.assertEqual(refs[0].album, "Placeholder Album")

    def test_a_row_dated_one_day_ahead_is_kept(self) -> None:
        # Music.app's ISO date is local time with no offset, so a track added late
        # in the evening reads as "tomorrow" to a run whose own clock sits in another
        # zone. One day of slack keeps it; it is a real addition, not a forgery.
        run = _rows(
            "2000-06-16T00:30:00\tArtist A\tTomorrow",
            "2000-06-14T10:00:00\tArtist B\tYesterday",
        )
        refs = newest_albums_from_music(2, run=run, today=_TODAY)
        self.assertEqual([ref.album for ref in refs], ["Tomorrow", "Yesterday"])

    def test_a_row_dated_two_days_ahead_is_dropped(self) -> None:
        run = _rows(
            "2000-06-17T00:30:00\tArtist A\tToo Far Ahead",
            "2000-06-14T10:00:00\tArtist B\tYesterday",
        )
        refs = newest_albums_from_music(2, run=run, today=_TODAY)
        self.assertEqual([ref.album for ref in refs], ["Yesterday"])

    def test_a_name_holding_an_exotic_line_separator_survives_whole(self) -> None:
        # `str.splitlines` also breaks a string at a form feed, at the ASCII
        # separator controls, at the C1 NEL and at U+2028/U+2029. A legitimate name
        # holding one was cut there, and its remainder read as a malformed row. Only
        # the linefeed the AppleScript itself emits may end a row.
        for separator in (" ", "", "\x0c", "\x1c"):
            with self.subTest(codepoint=hex(ord(separator))):
                album = f"Side{separator}Two"
                run = _rows(f"2000-06-01T10:00:00\tArtist A\t{album}")
                refs = newest_albums_from_music(1, run=run, today=_TODAY)
                self.assertEqual([ref.album for ref in refs], [album])

    def test_a_row_carrying_a_nul_is_skipped_while_the_rest_are_kept(self) -> None:
        # No real tag carries a NUL, and a name that does cannot be handed to a
        # subprocess at all: the per-album counts query built from it would be
        # refused before it ran. Skipping the row here keeps every other row.
        run = _rows(
            "2000-06-01T10:00:00\tArtist\x00A\tAn Album",
            "2000-05-01T10:00:00\tThe Stand-In Trio\tFiller Songs",
        )
        refs = newest_albums_from_music(2, run=run, today=_TODAY)
        self.assertEqual(
            refs,
            [
                AlbumRef(
                    artist="The Stand-In Trio",
                    album="Filler Songs",
                    added=dt.date(2000, 5, 1),
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
