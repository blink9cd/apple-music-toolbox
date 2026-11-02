"""The entry point: what stops a run before it starts, each exit code, the two formats.

Every run goes through `main` with an `audit_fixtures.FakeMusic` runner; nothing reaches
Music.app. A refusal is asserted to have made no call at all, or only the probe, so
"cannot start" is shown to mean that nothing was asked of Music.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import library_audit as la  # noqa: E402 - import follows the sys.path bootstrap above
import audit_fixtures as af  # noqa: E402 - import follows the sys.path bootstrap above
import music_calls  # noqa: E402 - import follows the sys.path bootstrap above

#: A tag reader that reads nothing: tag checks run, and find every file unreadable.
_NO_TAGS = af.tag_table({})


def _empty_report(library: Path) -> str:
    """The whole text report of an empty library and an empty Music."""
    return (
        f"library: {library}\n"
        "files with no Music.app track: 0\n"
        "Music.app tracks whose file is gone: 0\n"
        "track-number gaps: 0\n"
        "albums split by spelling: 0\n"
        "files with no track number: 0\n"
        "files and Music.app tracks differ: 0\n"
        "unreadable tags: 0\n"
        "unreadable files and folders: 0\n"
        "iCloud placeholders: 0\n"
        "Music.app size differs from the file: 0\n"
        "unchecked tracks: 0\n"
        "decode check not run (--decode)\n"
        "the sync checks see this Mac only: Music.app cannot see an iPhone, so a track"
        " the phone lists but cannot play is not found here\n"
        "summary: findings 0; audio files 0, Music.app tracks 0;"
        " cloud-only 0, outside --library 0, unparsed rows 0, sizes unknown 0\n"
    )


class CannotStartTest(af.AuditCase):
    """Exit 2, with nothing asked of Music beyond, at most, whether it runs."""

    def test_the_library_option_is_required(self) -> None:
        result = af.run_main([], af.wiring(af.FakeMusic()))
        self.assertEqual(result.code, af.USAGE)
        self.assertIn("--library", result.stderr)

    def test_off_macos_nothing_is_asked(self) -> None:
        music = af.FakeMusic()
        result = af.run_main(
            ["--library", str(self.library)], af.wiring(music, platform="linux")
        )
        self.assertEqual(result.code, af.USAGE)
        self.assertIn("needs macOS", result.stderr)
        self.assertEqual(music.calls, [])

    def test_a_library_that_is_not_a_folder_is_refused_before_the_probe(self) -> None:
        for target in (self.root / "absent", self.touch("a-file.mp3")):
            with self.subTest(target=target.name):
                music = af.FakeMusic()
                result = af.run_main(["--library", str(target)], af.wiring(music))
                self.assertEqual(result.code, af.USAGE)
                self.assertIn("not a readable folder", result.stderr)
                self.assertEqual(music.calls, [])

    # getattr, since os.geteuid exists on POSIX only and the type check covers win32.
    @unittest.skipIf(
        getattr(os, "geteuid", lambda: -1)() == 0,
        "root reads a folder whatever its mode",
    )
    def test_a_library_that_cannot_be_read_is_refused(self) -> None:
        locked = self.root / "locked"
        locked.mkdir(mode=0)
        self.addCleanup(locked.chmod, 0o700)
        result = af.run_main(["--library", str(locked)], af.wiring(af.FakeMusic()))
        self.assertEqual(result.code, af.USAGE)

    def test_music_not_running_is_never_launched(self) -> None:
        music = af.FakeMusic(running=False)
        result = self.audit(music)
        self.assertEqual(result.code, af.USAGE)
        self.assertIn("Music.app is not running", result.stderr)
        self.assertEqual(music.kinds(), [af.IS_RUNNING])

    def test_an_unanswered_probe_cannot_start(self) -> None:
        music = af.FakeMusic(
            answers={(af.IS_RUNNING, 1): af.completed(returncode=1, stderr="no\n")}
        )
        result = self.audit(music)
        self.assertEqual(result.code, af.USAGE)
        self.assertIn("cannot ask whether Music.app is running", result.stderr)

    def test_a_report_inside_a_working_tree_is_refused_before_any_call(self) -> None:
        (self.root / "repo" / ".git").mkdir(parents=True)
        music = af.FakeMusic()
        result = self.audit(music, "--report", str(self.root / "repo" / "r.txt"))
        self.assertEqual(result.code, af.USAGE)
        self.assertIn("git working tree", result.stderr)
        self.assertEqual(music.calls, [])

    def test_a_failed_count_or_listing_ends_the_run_with_no_report(self) -> None:
        failed = af.completed(returncode=1, stderr="0:1: execution error (-10000)\n")
        killed = music_calls.subprocess.TimeoutExpired(cmd=["osascript"], timeout=35)
        for answers in (
            {(af.COUNT, 1): failed},
            {(af.LIST, 1): failed},
            {(af.LIST, 1): killed},
        ):
            with self.subTest(answers=answers):
                music = af.FakeMusic(tracks=[af.Track(1, "")], answers=answers)
                result = self.audit(music, tag_reader=_NO_TAGS)
                self.assertEqual(result.code, af.USAGE)
                self.assertIn("cannot list Music.app's tracks", result.stderr)
                self.assertEqual(result.stdout, "")


class ExitCodeTest(af.AuditCase):
    """0 clean, 1 findings, 130 interrupted."""

    def test_an_empty_library_and_an_empty_music_is_clean(self) -> None:
        music = af.FakeMusic()
        result = self.audit(music, tag_reader=_NO_TAGS)
        self.assertEqual(result.code, af.OK)
        self.assertEqual(result.stdout, _empty_report(self.library))
        # No track to list, but the count is still asked again to confirm it held.
        self.assertEqual(music.kinds(), [af.IS_RUNNING, af.COUNT, af.COUNT])

    def test_matched_files_with_whole_tags_are_clean(self) -> None:
        files = self.album("Band/Album", "01 a.mp3", "02 b.mp3")
        tracks = [af.Track(n + 1, str(p), track=n + 1) for n, p in enumerate(files)]
        tags = af.tag_table({p: af.tagged(n + 1, 2) for n, p in enumerate(files)})
        result = self.audit(af.FakeMusic(tracks=tracks), tag_reader=tags)
        self.assertEqual(result.code, af.OK, result.stdout)
        self.assertIn(
            "summary: findings 0; audio files 2, Music.app tracks 2;",
            result.stdout,
        )

    def test_a_finding_exits_one(self) -> None:
        self.album("Band/Album", "01 a.mp3")
        result = self.audit(af.FakeMusic(), tag_reader=_NO_TAGS)
        self.assertEqual(result.code, af.FINDINGS)

    def test_ctrl_c_during_a_call_exits_130_with_no_report(self) -> None:
        music = af.FakeMusic(
            tracks=[af.Track(1, "")], answers={(af.LIST, 1): KeyboardInterrupt()}
        )
        result = self.audit(music)
        self.assertEqual(result.code, af.INTERRUPTED)
        self.assertIn("interrupted", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_an_unparsed_row_is_a_finding(self) -> None:
        music = af.FakeMusic(
            tracks=[af.Track(1, "")],
            answers={(af.LIST, 1): af.completed("garbage\n\n")},
        )
        result = self.audit(music, tag_reader=_NO_TAGS)
        self.assertEqual(result.code, af.FINDINGS)
        self.assertIn("unparsed rows 1,", result.stdout)
        self.assertIn("unparsed", result.stderr)


class ListingTest(af.AuditCase):
    """The tracks are listed in batches, and nothing but a read is ever sent."""

    def test_the_tracks_are_listed_a_batch_at_a_time(self) -> None:
        music = af.FakeMusic(tracks=[af.Track(n, "", "purchased") for n in (1, 2, 3)])
        with mock.patch.object(la, "BATCH_TRACKS", 2):
            result = self.audit(music, tag_reader=_NO_TAGS)
        self.assertEqual(result.code, af.OK)
        self.assertEqual(music.args_of(af.LIST), [["1", "2"], ["3", "3"]])
        self.assertIn("cloud-only 3", result.stdout)
        self.assertIn("tracks 1-2 of 3", result.stderr)

    def test_a_batch_is_a_thousand_tracks(self) -> None:
        # Measured on a real library: plain track ranges cost about 1 s per 250
        # tracks and 2.4 s per 2000, well inside the 35 s bound.
        self.assertEqual(la.BATCH_TRACKS, 1000)

    def test_tracks_of_another_class_are_listed_and_placed(self) -> None:
        music = af.FakeMusic(
            tracks=[
                af.Track(1, "", "matched", kind="shared track"),
                af.Track(2, "", "local only", kind="URL track"),
            ]
        )
        result = self.audit(music, tag_reader=_NO_TAGS)
        self.assertEqual(result.code, af.FINDINGS)
        self.assertIn("cloud-only 1,", result.stdout)
        self.assertIn("Music.app tracks whose file is gone: 1\n", result.stdout)

    def test_a_library_that_changed_names_both_track_counts(self) -> None:
        music = af.FakeMusic(
            tracks=[af.Track(1, "", "purchased")],
            answers={(af.COUNT, 2): af.completed("2\n")},
        )
        result = self.audit(music, tag_reader=_NO_TAGS)
        self.assertIn("(1 track(s), then 2)", result.stderr)

    def test_a_batch_answering_too_few_or_too_many_rows_ends_the_run(self) -> None:
        # Act, then confirm: a batch must account for every index it asked about, or
        # the unlisted tracks' files would be reported as having no track.
        one, two = af.Track(1, "").row(), af.Track(2, "").row()
        for reply in (one + "\n", one + two + one + "\n"):
            with self.subTest(rows=reply.count("\n") - 1):
                music = af.FakeMusic(
                    tracks=[af.Track(1, ""), af.Track(2, "")],
                    answers={(af.LIST, 1): af.completed(reply)},
                )
                result = self.audit(music, tag_reader=_NO_TAGS)
                self.assertEqual(result.code, af.USAGE)
                self.assertIn("cannot list Music.app's tracks", result.stderr)
                self.assertIn("for 2 tracks", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_an_unparsed_row_still_accounts_for_its_index(self) -> None:
        music = af.FakeMusic(
            tracks=[af.Track(1, ""), af.Track(2, "", "purchased")],
            answers={
                (af.LIST, 1): af.completed(
                    "garbage\n" + af.Track(2, "", "purchased").row() + "\n"
                )
            },
        )
        result = self.audit(music, tag_reader=_NO_TAGS)
        self.assertEqual(result.code, af.FINDINGS)
        self.assertIn("unparsed rows 1,", result.stdout)

    def test_a_library_that_changes_during_the_audit_ends_the_run(self) -> None:
        music = af.FakeMusic(
            tracks=[af.Track(1, "", "purchased")],
            answers={(af.COUNT, 2): af.completed("2\n")},
        )
        result = self.audit(music, tag_reader=_NO_TAGS)
        self.assertEqual(result.code, af.USAGE)
        self.assertIn("changed during the audit", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(music.kinds(), [af.IS_RUNNING, af.COUNT, af.LIST, af.COUNT])

    def test_a_failed_second_count_ends_the_run(self) -> None:
        music = af.FakeMusic(
            tracks=[af.Track(1, "", "purchased")],
            answers={(af.COUNT, 2): af.completed(returncode=1, stderr="no\n")},
        )
        result = self.audit(music, tag_reader=_NO_TAGS)
        self.assertEqual(result.code, af.USAGE)
        self.assertIn("cannot list Music.app's tracks", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_only_the_three_reading_scripts_are_sent(self) -> None:
        self.album("Band/Album", "01 a.mp3")
        music = af.FakeMusic(tracks=[af.Track(1, ""), af.Track(2, "")])
        self.audit(music, tag_reader=_NO_TAGS)
        self.assertEqual(set(music.kinds()), {af.IS_RUNNING, af.COUNT, af.LIST})
        self.assertEqual(music.kinds()[0], af.IS_RUNNING)


class FormatAndReportTest(af.AuditCase):
    """``--format json`` and ``--report FILE``."""

    def setUp(self) -> None:
        """A library of one file Music lacks, and a folder outside it for reports."""
        super().setUp()
        self.lost = self.album("Band/Album", "01 a.mp3")[0]
        (self.root / "out").mkdir()

    def test_json_carries_the_same_content(self) -> None:
        result = self.audit(af.FakeMusic(), "--format", "json", tag_reader=_NO_TAGS)
        self.assertEqual(result.code, af.FINDINGS)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], 4)
        self.assertEqual(report["library"], str(self.library))
        self.assertEqual(report["no_track"], [str(self.lost)])
        self.assertEqual(report["unreadable_tags"], [str(self.lost)])
        self.assertEqual(report["track_gaps"], [])
        self.assertEqual(report["split_albums"], [])
        self.assertEqual(report["findings"], 3)

    def test_json_marks_skipped_tag_checks_as_null(self) -> None:
        result = self.audit(af.FakeMusic(), "--format", "json")
        report = json.loads(result.stdout)
        self.assertIsNone(report["track_gaps"])
        self.assertIsNone(report["split_albums"])
        self.assertIsNone(report["unreadable_tags"])
        self.assertIsNone(report["no_track_number"])

    def test_a_report_file_takes_the_report_instead_of_stdout(self) -> None:
        target = self.root / "out" / "audit.txt"
        result = self.audit(
            af.FakeMusic(), "--report", str(target), tag_reader=_NO_TAGS
        )
        self.assertEqual(result.code, af.FINDINGS)
        self.assertEqual(result.stdout, "")
        self.assertIn(f"  {self.lost}\n", target.read_text(encoding="utf-8"))

    def test_a_json_report_file_is_json(self) -> None:
        target = self.root / "out" / "audit.json"
        self.audit(af.FakeMusic(), "--format", "json", "--report", str(target))
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["schema"], 4)

    def test_a_report_that_cannot_be_written_exits_two(self) -> None:
        target = self.root / "out" / "audit.txt"
        with mock.patch.object(
            la.report_file, "write_atomically", side_effect=OSError("invented")
        ):
            result = self.audit(af.FakeMusic(), "--report", str(target))
        self.assertEqual(result.code, af.USAGE)
        self.assertIn("cannot write the report", result.stderr)

    def test_a_report_refused_at_delivery_is_not_written_and_exits_two(self) -> None:
        # The folder was fine at start, then became refusable (a repository made
        # around it, say) while the audit ran: asked again just before the write.
        target = self.root / "out" / "audit.txt"
        with mock.patch.object(
            la.report_file, "refusal", side_effect=[None, "invented refusal"]
        ) as refusal:
            result = self.audit(af.FakeMusic(), "--report", str(target))
        self.assertEqual(result.code, af.USAGE)
        self.assertIn("--report: invented refusal", result.stderr)
        self.assertEqual(refusal.call_count, 2)
        self.assertFalse(target.exists())

    def test_ctrl_c_while_the_report_is_written_exits_130(self) -> None:
        target = self.root / "out" / "audit.txt"
        with mock.patch.object(
            la.report_file, "write_atomically", side_effect=KeyboardInterrupt
        ):
            result = self.audit(af.FakeMusic(), "--report", str(target))
        self.assertEqual(result.code, af.INTERRUPTED)
        self.assertIn("interrupted", result.stderr)
        self.assertFalse(target.exists())

    def test_ctrl_c_while_the_report_is_formatted_exits_130(self) -> None:
        with mock.patch.object(
            la.audit_report, "format_text", side_effect=KeyboardInterrupt
        ):
            result = self.audit(af.FakeMusic())
        self.assertEqual(result.code, af.INTERRUPTED)
        self.assertEqual(result.stdout, "")

    def test_help_shows_the_defaults_and_the_prerequisites(self) -> None:
        result = af.run_main(["--help"], None)
        self.assertEqual(result.code, af.OK)
        self.assertIn("(default: text)", result.stdout)
        self.assertIn("Prerequisites:", result.stdout)
        self.assertIn("never launched", result.stdout)
        self.assertIn("--decode", result.stdout)
        self.assertIn("afconvert", result.stdout)

    def test_help_hides_the_off_switch_default(self) -> None:
        # No one types False: --decode's help says what giving it does instead.
        # Joined, because argparse wraps this annotation across two lines.
        text = " ".join(la.build_parser().format_help().split())
        self.assertNotIn("default: False", text)

    def test_decode_is_falsy_omitted_and_true_given(self) -> None:
        parser = la.build_parser()
        self.assertFalse(parser.parse_args(["--library", "lib"]).decode)
        self.assertIs(parser.parse_args(["--library", "lib", "--decode"]).decode, True)


class RealWiringTest(unittest.TestCase):
    """The real wiring binds the real seams; nothing here calls one."""

    def test_the_real_seams(self) -> None:
        wiring = la.real_wiring()
        self.assertIs(wiring.run, music_calls.real_run)
        self.assertIs(wiring.stat, os.stat)
        self.assertEqual(wiring.platform, sys.platform)
        self.assertIs(wiring.walk, la.audit_walk.real_walk)
        self.assertIs(wiring.access, os.access)
        self.assertIs(wiring.decode, la.real_decode_run)


if __name__ == "__main__":
    unittest.main()
