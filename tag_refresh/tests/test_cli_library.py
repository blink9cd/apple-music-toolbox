"""``--whole-library``: the count, the batches, a failed batch, the timeout stop, Ctrl-C.

Every run goes through `main` with a `cli_fixtures.FakeMusic` runner whose library holds
only a track count; nothing reaches Music.app. The report on stdout is asserted whole,
so its wording is pinned here as the companion doc shows it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import tag_refresh as amr  # noqa: E402 - import follows the sys.path bootstrap above
import cli_fixtures as cf  # noqa: E402 - import follows the sys.path bootstrap above

_OK, _PARTIAL, _INTERRUPTED = 0, 1, 130
#: A library of three batches, the last one short.
_TOTAL = 1203


class WholeLibraryTest(unittest.TestCase):
    """The probe, then the count, then one refresh per batch of 500."""

    def run_library(self, music: cf.FakeMusic, *extra: str) -> cf.Outcome:
        """Run ``--whole-library`` with *extra* options against *music*."""
        return cf.run_main(["--whole-library", *extra], cf.wiring(music))

    def test_every_batch_is_refreshed_in_order_after_the_probe_and_count(self) -> None:
        music = cf.FakeMusic(file_tracks=_TOTAL)
        result = self.run_library(music)
        self.assertEqual(result.code, _OK)
        self.assertEqual(
            music.kinds(), [cf.IS_RUNNING, cf.COUNT] + [cf.REFRESH_RANGE] * 3
        )
        self.assertEqual(
            music.args_of(cf.REFRESH_RANGE),
            [["1", "500"], ["501", "1000"], ["1001", "1203"]],
        )
        self.assertEqual(
            result.stdout,
            "whole library: refreshed 1203 of 1203 file tracks in 3 batches\ntotal: refreshed 1203 of 1203 file tracks\n",
        )
        self.assertIn("batch 2/3: tracks 501-1000", result.stderr)

    def test_a_dry_run_counts_and_refreshes_nothing(self) -> None:
        music = cf.FakeMusic(file_tracks=_TOTAL)
        result = self.run_library(music, "--dry-run")
        self.assertEqual(result.code, _OK)
        self.assertEqual(music.kinds(), [cf.IS_RUNNING, cf.COUNT])
        self.assertEqual(
            result.stdout,
            "whole library: would refresh 1203 of 1203 file tracks in 3 batches\ntotal: would refresh 1203 of 1203 file tracks\n",
        )

    def test_an_empty_library_refreshes_nothing_and_succeeds(self) -> None:
        music = cf.FakeMusic(file_tracks=0)
        result = self.run_library(music)
        self.assertEqual(result.code, _OK)
        self.assertEqual(music.kinds(), [cf.IS_RUNNING, cf.COUNT])
        self.assertIn("refreshed 0 of 0 file tracks in 0 batches", result.stdout)

    def test_a_timeout_on_batch_two_stops_the_run_naming_the_range_left(self) -> None:
        for answer in (
            cf.killed(),
            cf.completed(returncode=1, stderr=cf.TIMED_OUT_STDERR),
        ):
            with self.subTest(answer=type(answer).__name__):
                music = cf.FakeMusic(
                    file_tracks=_TOTAL, answers={(cf.REFRESH_RANGE, 2): answer}
                )
                result = self.run_library(music)
                self.assertEqual(result.code, _PARTIAL)
                self.assertEqual(music.kinds().count(cf.REFRESH_RANGE), 2)
                lines = result.stdout.splitlines()
                self.assertEqual(
                    lines[0],
                    "whole library: refreshed 500 of 1203 file tracks in 3 batches",
                )
                self.assertEqual(lines[1], "not refreshed (stopped): tracks 501-1203")
                self.assertTrue(lines[2].startswith("stopped at a timeout: "), lines[2])
                self.assertEqual(lines[3], "total: refreshed 500 of 1203 file tracks")

    def test_a_failed_batch_is_reported_and_the_rest_still_run(self) -> None:
        music = cf.FakeMusic(
            file_tracks=_TOTAL, answers={(cf.REFRESH_RANGE, 1): cf.failed()}
        )
        result = self.run_library(music)
        self.assertEqual(result.code, _PARTIAL)
        self.assertEqual(music.kinds().count(cf.REFRESH_RANGE), 3)
        self.assertEqual(
            result.stdout,
            "whole library: refreshed 703 of 1203 file tracks in 3 batches\n"
            f"error: tracks 1-500: {cf.FAILED_REASON}\n"
            "total: refreshed 703 of 1203 file tracks\n",
        )

    def test_a_count_that_fails_ends_the_run_with_nothing_refreshed(self) -> None:
        music = cf.FakeMusic(file_tracks=_TOTAL, answers={(cf.COUNT, 1): cf.failed()})
        result = self.run_library(music)
        self.assertEqual(result.code, _PARTIAL)
        self.assertEqual(music.kinds(), [cf.IS_RUNNING, cf.COUNT])
        self.assertEqual(
            result.stdout,
            f"error: counting the file tracks: {cf.FAILED_REASON}\ntotal: refreshed 0 file tracks\n",
        )

    def test_a_count_that_times_out_stops_with_every_track_left(self) -> None:
        music = cf.FakeMusic(file_tracks=_TOTAL, answers={(cf.COUNT, 1): cf.killed()})
        result = self.run_library(music)
        self.assertEqual(result.code, _PARTIAL)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "not refreshed (stopped): every file track")
        self.assertTrue(lines[1].startswith("stopped at a timeout: "))
        self.assertEqual(lines[2], "total: refreshed 0 file tracks")

    def test_ctrl_c_during_a_batch_reports_what_finished_and_exits_130(self) -> None:
        music = cf.FakeMusic(
            file_tracks=_TOTAL, answers={(cf.REFRESH_RANGE, 3): KeyboardInterrupt()}
        )
        result = self.run_library(music)
        self.assertEqual(result.code, _INTERRUPTED)
        self.assertEqual(
            result.stdout,
            "whole library: refreshed 1000 of 1203 file tracks in 3 batches\n"
            "not refreshed (stopped): tracks 1001-1203\n"
            "stopped: interrupted (Ctrl-C)\n"
            "total: refreshed 1000 of 1203 file tracks\n",
        )

    def test_ctrl_c_in_a_progress_line_still_reports_and_exits_130(self) -> None:
        # The second notice is batch 1's progress line, before its call; the third is
        # batch 2's, after batch 1 finished.
        cases = {
            2: ("refreshed 0", "tracks 1-1203", 0),
            3: ("refreshed 500", "tracks 501-1203", 1),
        }
        for nth, (done, left, calls) in cases.items():
            with self.subTest(nth=nth):
                music = cf.FakeMusic(file_tracks=_TOTAL)
                with mock.patch.object(amr, "_notice", cf.interrupt_notice(nth)):
                    result = self.run_library(music)
                self.assertEqual(result.code, _INTERRUPTED)
                self.assertEqual(music.kinds().count(cf.REFRESH_RANGE), calls)
                self.assertEqual(
                    result.stdout,
                    f"whole library: {done} of 1203 file tracks in 3 batches\n"
                    f"not refreshed (stopped): {left}\n"
                    "stopped: interrupted (Ctrl-C)\n"
                    f"total: {done} of 1203 file tracks\n",
                )

    def test_ctrl_c_in_the_counting_line_reports_every_track_left(self) -> None:
        music = cf.FakeMusic(file_tracks=_TOTAL)
        with mock.patch.object(amr, "_notice", cf.interrupt_notice(1)):
            result = self.run_library(music)
        self.assertEqual(result.code, _INTERRUPTED)
        self.assertEqual(music.kinds(), [cf.IS_RUNNING])
        self.assertIn("not refreshed (stopped): every file track", result.stdout)

    def test_ctrl_c_during_the_count_reports_and_exits_130(self) -> None:
        music = cf.FakeMusic(
            file_tracks=_TOTAL, answers={(cf.COUNT, 1): KeyboardInterrupt()}
        )
        result = self.run_library(music)
        self.assertEqual(result.code, _INTERRUPTED)
        self.assertIn("not refreshed (stopped): every file track", result.stdout)

    def test_ctrl_c_during_the_probe_exits_130_with_no_report(self) -> None:
        music = cf.FakeMusic(answers={(cf.IS_RUNNING, 1): KeyboardInterrupt()})
        result = self.run_library(music)
        self.assertEqual(result.code, _INTERRUPTED)
        self.assertEqual(result.stdout, "")
        self.assertIn("interrupted", result.stderr)


if __name__ == "__main__":
    unittest.main()
