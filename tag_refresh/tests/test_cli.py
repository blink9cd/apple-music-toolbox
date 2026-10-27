"""The entry point's refusals, its options, and how it reports what it could not collect.

Every run here goes through `main` with a `cli_fixtures.FakeMusic` runner and a
temporary tree; nothing reaches Music.app. A refusal is asserted to have made no Music
call at all, or only the ``is running`` probe where that is the refusal's subject.
"""

from __future__ import annotations

import io
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

#: Exit codes, as the plan and the companion doc number them.
_OK, _PARTIAL, _USAGE, _INTERRUPTED = 0, 1, 2, 130


class RefusalTest(cf.CliCase):
    """Each way a run cannot start: exit 2, one line, and no refresh."""

    def test_off_macos_is_refused_before_any_music_call(self) -> None:
        music = cf.FakeMusic()
        result = cf.run_main(["--whole-library"], cf.wiring(music, platform="linux"))
        self.assertEqual(result.code, _USAGE)
        self.assertEqual(music.calls, [])
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertIn("needs macOS", result.stderr)
        self.assertIn("linux", result.stderr)

    def test_off_macos_is_refused_before_a_list_is_read(self) -> None:
        reads: list[int] = []

        def read_stdin() -> bytes:
            reads.append(1)
            return b""

        seams = cf.wiring(cf.FakeMusic(), platform="win32")
        seams = amr.Wiring(seams.run, seams.stat, seams.platform, None, read_stdin)
        result = cf.run_main(["--tracks-from", "-"], seams)
        self.assertEqual(result.code, _USAGE)
        self.assertEqual(reads, [])

    def test_no_mode_is_a_usage_error(self) -> None:
        music = cf.FakeMusic()
        result = cf.run_main([], cf.wiring(music))
        self.assertEqual(result.code, _USAGE)
        self.assertIn("--whole-library", result.stderr)
        self.assertEqual(music.calls, [])

    def test_dry_run_alone_is_no_mode(self) -> None:
        result = cf.run_main(["--dry-run"], cf.wiring(cf.FakeMusic()))
        self.assertEqual(result.code, _USAGE)

    def test_whole_library_with_a_source_is_refused(self) -> None:
        mp3 = self.album("A/B", "01 x.mp3")[0]
        for extra in (
            ["--track", str(mp3)],
            ["--album", str(mp3.parent)],
            ["--tracks-from", "-"],
        ):
            with self.subTest(extra=extra[0]):
                music = cf.FakeMusic()
                result = cf.run_main(["--whole-library", *extra], cf.wiring(music))
                self.assertEqual(result.code, _USAGE)
                self.assertIn("cannot be combined", result.stderr)
                self.assertEqual(music.calls, [])

    def test_a_second_tracks_from_is_a_usage_error(self) -> None:
        # argparse's plain store would keep the last list and drop the first silently.
        one = self.list_file(self.album("A/B", "01 x.mp3")[0])
        music = cf.FakeMusic()
        result = cf.run_main(
            ["--tracks-from", str(one), "--tracks-from", "-"], cf.wiring(music)
        )
        self.assertEqual(result.code, _USAGE)
        self.assertIn("--tracks-from is given once", result.stderr)
        self.assertEqual(music.calls, [])

    def test_music_not_running_is_refused_after_the_probe_alone(self) -> None:
        mp3 = self.album("A/B", "01 x.mp3")[0]
        for argv in (["--whole-library"], ["--track", str(mp3)]):
            with self.subTest(argv=argv[0]):
                music = cf.FakeMusic(running=False)
                result = cf.run_main(argv, cf.wiring(music))
                self.assertEqual(result.code, _USAGE)
                self.assertEqual(music.kinds(), [cf.IS_RUNNING])
                self.assertIn("Music.app is not running", result.stderr)
                self.assertIn("open Music", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_a_probe_that_cannot_answer_is_refused_naming_why(self) -> None:
        for answer in (cf.killed(), cf.failed()):
            with self.subTest(answer=type(answer).__name__):
                music = cf.FakeMusic(answers={(cf.IS_RUNNING, 1): answer})
                result = cf.run_main(["--whole-library"], cf.wiring(music))
                self.assertEqual(result.code, _USAGE)
                self.assertEqual(music.kinds(), [cf.IS_RUNNING])
                self.assertIn("cannot ask whether Music.app is running", result.stderr)
                self.assertIn("open Music", result.stderr)

    def test_an_unreadable_list_file_is_refused_before_music(self) -> None:
        music = cf.FakeMusic()
        missing = self.root / "absent.txt"
        result = cf.run_main(["--tracks-from", str(missing)], cf.wiring(music))
        self.assertEqual(result.code, _USAGE)
        self.assertIn("cannot read the list file", result.stderr)
        self.assertIn(str(missing), result.stderr)
        self.assertEqual(music.calls, [])

    def test_a_folder_named_as_the_list_file_is_unreadable(self) -> None:
        result = cf.run_main(
            ["--tracks-from", str(self.root)], cf.wiring(cf.FakeMusic())
        )
        self.assertEqual(result.code, _USAGE)
        self.assertIn("cannot read the list file", result.stderr)

    def test_an_empty_collection_is_nothing_to_refresh(self) -> None:
        music = cf.FakeMusic()
        text = self.touch("A/B/notes.txt", b"x")
        result = cf.run_main(["--track", str(text)], cf.wiring(music))
        self.assertEqual(result.code, _USAGE)
        self.assertIn("nothing to refresh", result.stderr)
        self.assertIn("not an MP3", result.stderr)
        self.assertEqual(music.calls, [])

    def test_an_empty_list_on_standard_input_is_nothing_to_refresh(self) -> None:
        result = cf.run_main(
            ["--tracks-from", "-"], cf.wiring(cf.FakeMusic(), stdin=b"")
        )
        self.assertEqual(result.code, _USAGE)
        self.assertIn("nothing to refresh", result.stderr)


class CollectionProblemTest(cf.CliCase):
    """Each skipped input is one stderr line, by source and line number, and exit 1."""

    def test_list_problems_are_reported_by_line_and_the_rest_run(self) -> None:
        good = self.album("Artist/Album", "01 a.mp3")[0]
        music = cf.FakeMusic(tracks=[cf.Track(7, cf.pid(7), "Album", good)])
        data = (
            f"{good}\n\nrelative/x.mp3\n".encode()
            + b"\xff\xfe\n"
            + str(self.root / "gone.mp3").encode()
            + b"\n/last-line.mp3"
        )
        result = cf.run_main(["--tracks-from", "-"], cf.wiring(music, stdin=data))
        self.assertEqual(result.code, _PARTIAL)
        problems = [
            line
            for line in result.stderr.splitlines()
            if line.startswith("--tracks-from")
        ]
        self.assertEqual(
            problems,
            [
                "--tracks-from -, line 3: relative/x.mp3: not an absolute path",
                "--tracks-from -, line 4: not UTF-8",
                "--tracks-from -, line 6: /last-line.mp3: not ended by a linefeed",
                f"--tracks-from -, line 5: {self.root / 'gone.mp3'}: not a file",
            ],
        )
        self.assertIn(f"{good.parent}: refreshed 1", result.stdout)

    def test_a_list_file_is_labeled_by_the_path_given(self) -> None:
        good = self.album("Artist/Album", "01 a.mp3")[0]
        listed = self.list_file(good, "rel.mp3")
        music = cf.FakeMusic(tracks=[cf.Track(7, cf.pid(7), "Album", good)])
        result = cf.run_main(["--tracks-from", str(listed)], cf.wiring(music))
        self.assertEqual(result.code, _PARTIAL)
        self.assertIn(
            f"--tracks-from {listed}, line 2: rel.mp3: not an absolute path",
            result.stderr,
        )

    def test_track_and_album_problems_name_their_option(self) -> None:
        good = self.album("Artist/Album", "01 a.mp3")[0]
        empty = self.root / "Artist" / "Empty"
        empty.mkdir()
        text = self.touch("Artist/Album/cover.txt", b"x")
        music = cf.FakeMusic(tracks=[cf.Track(7, cf.pid(7), "Album", good)])
        argv = [
            "--track",
            str(good),
            "--track",
            str(text),
            "--album",
            str(empty),
            "--album",
            str(text),
        ]
        result = cf.run_main(argv, cf.wiring(music))
        self.assertEqual(result.code, _PARTIAL)
        lines = result.stderr.splitlines()
        self.assertIn(f"--track: {text}: not an MP3", lines)
        self.assertIn(f"--album: {empty}: holds no MP3", lines)
        self.assertIn(f"--album: {text}: not a folder", lines)

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symbolic links")
    def test_a_folder_reached_twice_is_reported_and_does_not_count(self) -> None:
        good = self.album("Artist/Album", "01 a.mp3")[0]
        (good.parent / "loop").symlink_to(good.parent)
        music = cf.FakeMusic(tracks=[cf.Track(7, cf.pid(7), "Album", good)])
        result = cf.run_main(["--album", str(good.parent)], cf.wiring(music))
        self.assertEqual(result.code, _OK)
        self.assertIn("reaches a folder already walked", result.stderr)


class HelpTest(unittest.TestCase):
    """The help names every option, its prerequisites and its exit codes."""

    def test_the_help_holds_the_prerequisites_and_every_exit_code(self) -> None:
        text = amr.build_parser().format_help()
        for needle in (
            "--whole-library",
            "--track",
            "--album",
            "--tracks-from",
            "--dry-run",
            "Prerequisites",
            "macOS",
            "Music.app",
            "automation",
            "130",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_the_exit_2_line_names_an_unanswered_probe(self) -> None:
        text = amr.build_parser().format_help()
        self.assertIn("Music.app not running or the probe unanswered", text)

    def test_a_none_default_is_not_shown(self) -> None:
        self.assertNotIn("default: None", amr.build_parser().format_help())


class WiringTest(unittest.TestCase):
    """The real wiring binds the real seams, and reading it makes no call."""

    def test_the_real_wiring_binds_the_real_seams(self) -> None:
        real = amr.real_wiring()
        self.assertIs(real.run, music_calls.real_run)
        self.assertIs(real.stat, os.stat)
        self.assertEqual(real.platform, sys.platform)

    def test_the_real_stdin_reader_reads_bytes(self) -> None:
        fake_stdin = io.TextIOWrapper(io.BytesIO(b"/a.mp3\n"), encoding="utf-8")
        with mock.patch.object(sys, "stdin", fake_stdin):
            self.assertEqual(amr.real_wiring().read_stdin(), b"/a.mp3\n")

    def test_main_without_wiring_uses_the_real_one(self) -> None:
        seams = cf.wiring(cf.FakeMusic(), platform="linux")
        with mock.patch.object(amr, "real_wiring", return_value=seams) as real:
            result = cf.run_main(["--whole-library"], None)
        real.assert_called_once_with()
        self.assertEqual(result.code, _USAGE)


if __name__ == "__main__":
    unittest.main()
