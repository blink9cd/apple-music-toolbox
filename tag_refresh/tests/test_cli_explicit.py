"""Explicit mode: per album folder, look the names up, match by inode, refresh by id.

Every run goes through `main` with a `cli_fixtures.FakeMusic` runner whose invented
tracks point at placeholder MP3s in a temporary tree; nothing reaches Music.app. The
report is asserted whole where its wording is the subject.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import tag_refresh as amr  # noqa: E402 - import follows the sys.path bootstrap above
import cli_fixtures as cf  # noqa: E402 - import follows the sys.path bootstrap above
import music_calls  # noqa: E402 - import follows the sys.path bootstrap above

_OK, _PARTIAL, _INTERRUPTED = 0, 1, 130
#: The hint printed when mutagen is absent and a file was not found in Music.
_HINT = "hint: "


class ExplicitCase(cf.CliCase):
    """Two invented albums, one of two discs, each track known to the fake Music."""

    def setUp(self) -> None:
        """Make the albums and a Music holding every track but one."""
        super().setUp()
        self.first = self.album("Quartet/First Album", "01 a.mp3", "02 b.mp3")
        self.disc1 = self.album("Trio/Second Album/Disc 1", "01 c.mp3")
        self.disc2 = self.album("Trio/Second Album/Disc 2", "01 d.mp3")
        self.tracks = [
            cf.Track(11, cf.pid(11), "First Album", self.first[0]),
            cf.Track(12, cf.pid(12), "First Album", self.first[1]),
            cf.Track(21, cf.pid(21), "Second Album", self.disc1[0]),
        ]

    def music(self) -> cf.FakeMusic:
        """A fake Music holding `tracks`, with no canned answers."""
        return cf.FakeMusic(tracks=self.tracks)


class ExplicitRunTest(ExplicitCase):
    """The calls made, in order, and the report they produce."""

    def test_albums_are_looked_up_then_refreshed_by_id(self) -> None:
        music = self.music()
        argv = [
            "--album",
            str(self.first[0].parent),
            "--album",
            str(self.disc1[0].parent.parent),
        ]
        result = cf.run_main(argv, cf.wiring(music))
        self.assertEqual(result.code, _OK)
        self.assertEqual(
            music.kinds(),
            [cf.IS_RUNNING] + [cf.LOOKUP, cf.REFRESH_IDS] * 2 + [cf.LOOKUP],
        )
        self.assertEqual(
            music.args_of(cf.REFRESH_IDS)[0], ["11", cf.pid(11), "12", cf.pid(12)]
        )
        self.assertEqual(music.args_of(cf.LOOKUP)[0], ["First Album", "Quartet"])
        self.assertEqual(music.args_of(cf.LOOKUP)[1], ["Disc 1", "Second Album"])
        self.assertEqual(
            result.stdout,
            f"{self.first[0].parent}: refreshed 2\n"
            f"{self.disc1[0].parent}: refreshed 1\n"
            f"{self.disc2[0].parent}: refreshed 0, not in Music 1\n"
            "not in Music:\n"
            f"  {self.disc2[0]}\n"
            f"{amr.NO_MUTAGEN_HINT}\n"
            "total: refreshed 3, not in Music 1, stale 0, errors 0, stopped 0"
            " (album folders 3, MP3s 4)\n",
        )
        self.assertIn(f"album 1/3: {self.first[0].parent}", result.stderr)

    def test_the_probe_comes_first_and_no_name_enters_a_script_body(self) -> None:
        music = self.music()
        cf.run_main(["--track", str(self.first[0])], cf.wiring(music))
        self.assertEqual(music.kinds()[0], cf.IS_RUNNING)
        scripts = {argv[2] for argv in music.calls}
        for script in scripts:
            for name in ("First Album", "Quartet"):
                self.assertNotIn(name, script)

    def test_a_dry_run_looks_up_and_never_refreshes(self) -> None:
        music = self.music()
        result = cf.run_main(
            ["--album", str(self.first[0].parent), "--dry-run"], cf.wiring(music)
        )
        self.assertEqual(result.code, _OK)
        self.assertNotIn(cf.REFRESH_IDS, music.kinds())
        self.assertFalse(
            [argv for argv in music.calls if argv[2] == music_calls.REFRESH_IDS_SCRIPT]
        )
        self.assertEqual(
            result.stdout,
            f"{self.first[0].parent}: would refresh 2\n"
            "total: would refresh 2, not in Music 0, stale 0, errors 0, stopped 0"
            " (album folders 1, MP3s 2)\n",
        )

    def test_a_list_on_standard_input_is_collected(self) -> None:
        music = self.music()
        data = f"{self.first[1]}\n{self.first[0]}\n".encode()
        result = cf.run_main(["--tracks-from", "-"], cf.wiring(music, stdin=data))
        self.assertEqual(result.code, _OK)
        self.assertEqual(
            music.args_of(cf.REFRESH_IDS), [["12", cf.pid(12), "11", cf.pid(11)]]
        )

    def test_sources_combine_and_a_file_named_twice_counts_once(self) -> None:
        music = self.music()
        listed = self.list_file(self.first[0])
        argv = [
            "--track",
            str(self.first[0]),
            "--album",
            str(self.first[0].parent),
            "--tracks-from",
            str(listed),
        ]
        result = cf.run_main(argv, cf.wiring(music))
        self.assertEqual(result.code, _OK)
        self.assertIn("(album folders 1, MP3s 2)", result.stdout)

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symbolic links")
    def test_a_row_in_another_path_form_matches_by_inode(self) -> None:
        alias = self.root / "resolved"
        alias.symlink_to(self.first[0].parent)
        self.tracks[0] = cf.Track(11, cf.pid(11), "First Album", alias / "01 a.mp3")
        result = cf.run_main(["--track", str(self.first[0])], cf.wiring(self.music()))
        self.assertEqual(result.code, _OK)
        self.assertIn("refreshed 1", result.stdout)

    def test_the_album_tag_is_asked_for_when_a_reader_is_wired(self) -> None:
        music = self.music()
        seams = cf.wiring(music, tag_reader=lambda path: "Tagged Name")
        cf.run_main(["--track", str(self.first[0])], seams)
        self.assertEqual(
            music.args_of(cf.LOOKUP), [["First Album", "Quartet", "Tagged Name"]]
        )


class ExplicitOutcomeTest(ExplicitCase):
    """Stale tracks, failed calls, unparsed rows, the timeout stop and Ctrl-C."""

    def argv(self) -> list[str]:
        """Both albums, the first album first."""
        return [
            "--album",
            str(self.first[0].parent),
            "--album",
            str(self.disc1[0].parent.parent),
        ]

    def test_a_stale_track_is_counted_and_exits_1(self) -> None:
        music = self.music()
        music.answers[(cf.REFRESH_IDS, 1)] = cf.completed("1\t1\n")
        result = cf.run_main(["--album", str(self.first[0].parent)], cf.wiring(music))
        self.assertEqual(result.code, _PARTIAL)
        self.assertIn(f"{self.first[0].parent}: refreshed 1, stale 1\n", result.stdout)
        self.assertIn("stale 1, errors 0", result.stdout)

    def test_a_failed_lookup_is_that_albums_error_and_the_run_goes_on(self) -> None:
        music = self.music()
        music.answers[(cf.LOOKUP, 1)] = cf.failed()
        result = cf.run_main(self.argv(), cf.wiring(music))
        self.assertEqual(result.code, _PARTIAL)
        self.assertIn(
            f"{self.first[0].parent}: error: {cf.FAILED_REASON}\n", result.stdout
        )
        self.assertIn(f"{self.disc1[0].parent}: refreshed 1\n", result.stdout)
        self.assertIn("errors 1, stopped 0", result.stdout)

    def test_a_failed_refresh_is_that_albums_error_and_the_run_goes_on(self) -> None:
        music = self.music()
        music.answers[(cf.REFRESH_IDS, 1)] = cf.failed()
        result = cf.run_main(self.argv(), cf.wiring(music))
        self.assertEqual(result.code, _PARTIAL)
        self.assertIn(
            f"{self.first[0].parent}: error: {cf.FAILED_REASON}\n", result.stdout
        )
        self.assertEqual(music.kinds().count(cf.LOOKUP), 3)

    def test_unparsed_rows_are_counted_in_the_row(self) -> None:
        music = self.music()
        music.answers[(cf.LOOKUP, 1)] = cf.completed(
            f"11\t{cf.pid(11)}\t{self.first[0]}\nnot a row\n\n"
        )
        result = cf.run_main(["--album", str(self.first[0].parent)], cf.wiring(music))
        self.assertEqual(result.code, _OK)
        self.assertIn(
            f"{self.first[0].parent}: refreshed 1, not in Music 1, unparsed rows 1\n",
            result.stdout,
        )

    def test_a_row_with_track_id_zero_is_unparsed_never_a_crash(self) -> None:
        # refresh_ids refuses an id below 1 as a caller's bug, and a row forged through
        # a name holding a linefeed could carry 0: the core's row shape refuses it, so
        # it is counted unparsed and never reaches the refresh.
        music = self.music()
        reply = (
            f"0\t{cf.pid(1)}\t{self.first[0]}\n11\t{cf.pid(11)}\t{self.first[0]}\n\n"
        )
        music.answers[(cf.LOOKUP, 1)] = cf.completed(reply)
        result = cf.run_main(["--track", str(self.first[0])], cf.wiring(music))
        self.assertEqual(result.code, _OK)
        self.assertEqual(music.args_of(cf.REFRESH_IDS), [["11", cf.pid(11)]])
        self.assertIn(": refreshed 1, unparsed rows 1\n", result.stdout)

    def test_a_timeout_stops_the_run_naming_the_albums_left(self) -> None:
        # Music goes on working after a timeout, so a folder whose refresh call timed
        # out may be partly refreshed; one whose lookup timed out was never refreshed.
        cases = {
            cf.LOOKUP: "not refreshed (stopped)",
            cf.REFRESH_IDS: "stopped (may be partly refreshed)",
        }
        for kind, in_hand in cases.items():
            with self.subTest(kind=kind):
                music = self.music()
                music.answers[(kind, 2)] = cf.killed()
                result = cf.run_main(self.argv(), cf.wiring(music))
                self.assertEqual(result.code, _PARTIAL)
                lines = result.stdout.splitlines()
                self.assertEqual(lines[0], f"{self.first[0].parent}: refreshed 2")
                self.assertEqual(lines[1], f"{self.disc1[0].parent}: {in_hand}")
                self.assertEqual(
                    lines[2], f"{self.disc2[0].parent}: not refreshed (stopped)"
                )
                self.assertTrue(lines[3].startswith("stopped at a timeout: "), lines[3])
                self.assertIn("stopped 2 (album folders 3, MP3s 4)", lines[4])
                self.assertEqual(music.kinds().count(kind), 2)

    def test_ctrl_c_reports_what_finished_and_exits_130(self) -> None:
        music = self.music()
        music.answers[(cf.LOOKUP, 2)] = KeyboardInterrupt()
        result = cf.run_main(self.argv(), cf.wiring(music))
        self.assertEqual(result.code, _INTERRUPTED)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], f"{self.first[0].parent}: refreshed 2")
        self.assertEqual(lines[1], f"{self.disc1[0].parent}: not refreshed (stopped)")
        self.assertIn("stopped: interrupted (Ctrl-C)", lines)

    def test_ctrl_c_during_a_refresh_call_marks_that_folder_maybe_partly_done(
        self,
    ) -> None:
        music = self.music()
        music.answers[(cf.REFRESH_IDS, 2)] = KeyboardInterrupt()
        result = cf.run_main(self.argv(), cf.wiring(music))
        self.assertEqual(result.code, _INTERRUPTED)
        lines = result.stdout.splitlines()
        self.assertEqual(
            lines[1], f"{self.disc1[0].parent}: stopped (may be partly refreshed)"
        )
        self.assertEqual(lines[2], f"{self.disc2[0].parent}: not refreshed (stopped)")

    def test_ctrl_c_in_a_progress_line_still_reports_and_exits_130(self) -> None:
        # No input problem is noticed, so the second notice is album 2's progress line,
        # between album 1's last call and album 2's first.
        music = self.music()
        with mock.patch.object(amr, "_notice", cf.interrupt_notice(2)):
            result = cf.run_main(self.argv(), cf.wiring(music))
        self.assertEqual(result.code, _INTERRUPTED)
        self.assertEqual(music.kinds(), [cf.IS_RUNNING, cf.LOOKUP, cf.REFRESH_IDS])
        self.assertEqual(
            result.stdout.splitlines(),
            [
                f"{self.first[0].parent}: refreshed 2",
                f"{self.disc1[0].parent}: not refreshed (stopped)",
                f"{self.disc2[0].parent}: not refreshed (stopped)",
                "stopped: interrupted (Ctrl-C)",
                "total: refreshed 2, not in Music 0, stale 0, errors 0, stopped 2 "
                "(album folders 3, MP3s 4)",
            ],
        )

    def test_ctrl_c_while_collecting_exits_130_with_no_report(self) -> None:
        def interrupted() -> bytes:
            raise KeyboardInterrupt

        seams = cf.wiring(self.music())
        seams = type(seams)(seams.run, seams.stat, seams.platform, None, interrupted)
        result = cf.run_main(["--tracks-from", "-"], seams)
        self.assertEqual(result.code, _INTERRUPTED)
        self.assertEqual(result.stdout, "")


class ShownTest(cf.CliCase):
    """A name this tool did not write cannot split a row or drive the terminal."""

    def test_a_linefeed_and_an_escape_in_a_folder_name_are_shown_escaped(self) -> None:
        mp3 = self.album("Artist/Line\nBreak\x1b[31m", "01 a.mp3")[0]
        result = cf.run_main(["--track", str(mp3)], cf.wiring(cf.FakeMusic()))
        self.assertEqual(result.code, _OK)
        first = result.stdout.splitlines()[0]
        self.assertTrue(
            first.endswith("Line\\x0aBreak\\x1b[31m: refreshed 0, not in Music 1"),
            first,
        )
        self.assertNotIn("\x1b", result.stdout + result.stderr)


class HintTest(ExplicitCase):
    """The mutagen hint: only with no tag reader, and only when a file was not found."""

    def test_no_reader_and_a_file_not_in_music_prints_the_hint(self) -> None:
        result = cf.run_main(["--track", str(self.disc2[0])], cf.wiring(self.music()))
        self.assertEqual(result.code, _OK)
        hints = [line for line in result.stdout.splitlines() if line.startswith(_HINT)]
        self.assertEqual(len(hints), 1)
        self.assertIn("refresh_tags", hints[0])
        self.assertIn("mutagen", hints[0])

    def test_a_reader_wired_prints_no_hint(self) -> None:
        seams = cf.wiring(self.music(), tag_reader=lambda path: None)
        result = cf.run_main(["--track", str(self.disc2[0])], seams)
        self.assertNotIn(_HINT, result.stdout)

    def test_everything_found_prints_no_hint(self) -> None:
        result = cf.run_main(["--track", str(self.first[0])], cf.wiring(self.music()))
        self.assertNotIn(_HINT, result.stdout)


if __name__ == "__main__":
    unittest.main()
