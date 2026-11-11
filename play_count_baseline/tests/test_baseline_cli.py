"""The entry point: each refusal and its exit code, the write and its confirmation, and the summary.

Every run goes through `main` with a `baseline_fixtures.FakeMusic` runner, so nothing
reaches Music.app, and writes only into a `tempfile` folder outside any checkout, so the
toolbox's working-tree refusal passes. A refusal before the read is asserted to have
asked Music nothing at all, or only whether it runs.
"""

from __future__ import annotations

import builtins
import dataclasses
import json
import os
import stat
import sys
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import play_count_baseline as pcb  # noqa: E402 - import follows the sys.path bootstrap above
import baseline_fixtures as bf  # noqa: E402 - import follows the sys.path bootstrap above
import baseline_schema  # noqa: E402 - import follows the sys.path bootstrap above
import music_calls  # noqa: E402 - import follows the sys.path bootstrap above
import report_file  # noqa: E402 - import follows the sys.path bootstrap above

from baseline_cli_fixtures import (  # noqa: E402 - import follows the sys.path bootstrap above
    CANNOT as _CANNOT,
    NOW as _NOW,
    REFUSED as _REFUSED,
    SECOND as _SECOND,
    WRITTEN as _WRITTEN,
    CliCase,
    tracks as _tracks,
)


class OptionsTest(CliCase):
    """1: one required option, a self-documenting help, and macOS only."""

    def test_help_shows_the_output_option_and_the_prerequisites(self) -> None:
        result = self.run_main(bf.FakeMusic(), ["--help"])
        self.assertEqual(result.code, _WRITTEN)
        self.assertIn("--output FILE", result.stdout)
        self.assertIn("Music.app", result.stdout)
        self.assertIn("contract", result.stdout)

    def test_the_output_option_is_required(self) -> None:
        music = bf.FakeMusic()
        result = self.run_main(music, [])
        self.assertEqual(result.code, _CANNOT)
        self.assertIn("--output", result.stderr)
        self.assertEqual(music.calls, [])

    def test_off_macos_nothing_is_asked(self) -> None:
        music = bf.FakeMusic(tracks=[bf.INVENTED_TRACK])
        result = self.run_main(music, platform="linux")
        self.assertEqual(result.code, _CANNOT)
        self.assertIn("needs macOS", result.stderr)
        self.assertEqual(music.calls, [])
        self.assertFalse(self.target.exists())

    def test_the_real_wiring_binds_osascript_the_clock_and_this_process(self) -> None:
        real = pcb.real_wiring()
        self.assertIs(real.run, music_calls.real_run)
        self.assertIs(real.stderr, sys.stderr)
        self.assertEqual(real.platform, sys.platform)
        self.assertIsInstance(real.now(), float)

    def test_the_version_is_the_module_constant(self) -> None:
        self.assertEqual(pcb.VERSION, "0.1.0")


class BeforeMusicTest(CliCase):
    """2: exit 2 with nothing asked of Music: the target, or the extra, is refused."""

    def test_an_existing_file_is_refused_and_left_as_it_was(self) -> None:
        self.target.write_bytes(b"an earlier snapshot\n")
        music = bf.FakeMusic(tracks=[bf.INVENTED_TRACK])
        result = self.run_main(music)
        self.assertEqual(result.code, _CANNOT)
        self.assertIn("exists already", result.stderr)
        self.assertEqual(self.target.read_bytes(), b"an earlier snapshot\n")
        self.assertEqual(music.calls, [])

    def test_a_dangling_link_counts_as_existing(self) -> None:
        self.target.symlink_to(self.root / "absent")
        music = bf.FakeMusic(tracks=[bf.INVENTED_TRACK])
        self.assertEqual(self.run_main(music).code, _CANNOT)
        self.assertEqual(music.calls, [])

    def test_a_target_inside_a_working_tree_is_refused(self) -> None:
        (self.root / report_file.GIT_ENTRY).mkdir()
        music = bf.FakeMusic(tracks=[bf.INVENTED_TRACK])
        result = self.run_main(music)
        self.assertEqual(result.code, _CANNOT)
        self.assertIn("git working tree", result.stderr)
        self.assertEqual(music.calls, [])
        self.assertFalse(self.target.exists())

    def test_a_missing_folder_is_refused(self) -> None:
        music = bf.FakeMusic(tracks=[bf.INVENTED_TRACK])
        missing = self.root / "absent" / "baseline.json"
        result = self.run_main(music, ["--output", str(missing)])
        self.assertEqual(result.code, _CANNOT)
        self.assertIn("is not a folder", result.stderr)
        self.assertEqual(music.calls, [])

    def test_a_missing_contract_extra_is_refused_naming_it(self) -> None:
        real = builtins.__import__

        def importer(
            name: str,
            globals_: Mapping[str, object] | None = None,
            locals_: Mapping[str, object] | None = None,
            fromlist: Sequence[str] = (),
            level: int = 0,
        ) -> ModuleType:
            if name.partition(".")[0] in ("jsonschema", "referencing"):
                raise ImportError(f"No module named {name!r}")
            return real(name, globals_, locals_, fromlist, level)

        music = bf.FakeMusic(tracks=[bf.INVENTED_TRACK])
        with mock.patch("builtins.__import__", side_effect=importer):
            result = self.run_main(music)
        self.assertEqual(result.code, _CANNOT)
        self.assertIn("pip install '.[contract]'", result.stderr)
        self.assertEqual(music.calls, [])
        self.assertFalse(self.target.exists())


class MusicTest(CliCase):
    """3: exit 2 when Music.app is not running, or any call fails."""

    def test_music_not_running_is_refused_after_the_probe_alone(self) -> None:
        music = bf.FakeMusic(running=False, tracks=[bf.INVENTED_TRACK])
        result = self.run_main(music)
        self.assertEqual(result.code, _CANNOT)
        self.assertIn("start Music.app first", result.stderr)
        self.assertIn("never launches it", result.stderr)
        self.assertEqual(music.kinds(), [bf.IS_RUNNING])
        self.assertFalse(self.target.exists())


class ReadTest(CliCase):
    """4: count, list in batches, count again; a partial picture is refused (exit 1)."""

    def test_the_library_is_listed_in_batches_with_a_line_each(self) -> None:
        music = bf.FakeMusic(tracks=_tracks(pcb.BATCH_TRACKS + 1))
        result = self.run_main(music)
        self.assertEqual(result.code, _WRITTEN)
        self.assertEqual(
            music.kinds(), [bf.IS_RUNNING, bf.COUNT, bf.LIST, bf.LIST, bf.COUNT]
        )
        script = bf.baseline_calls.PLAY_COUNTS_SCRIPT
        lists = [argv[-2:] for argv in music.calls if argv[2] == script]
        self.assertEqual(lists, [["1", "1000"], ["1001", "1001"]])
        self.assertIn("tracks 1-1000 of 1001", result.stderr)
        self.assertIn("tracks 1001-1001 of 1001", result.stderr)

    def test_the_capture_time_is_noted_before_the_read_in_whole_seconds(self) -> None:
        self.run_main(bf.FakeMusic(tracks=[bf.INVENTED_TRACK]))
        self.assertEqual(self.written()["captured_at"], int(_NOW))
        self.assertEqual(self.written()["submission_client_version"], pcb.VERSION)

    def test_a_count_that_changes_is_refused(self) -> None:
        music = bf.FakeMusic(
            tracks=[bf.INVENTED_TRACK], answers={(bf.COUNT, 2): bf.completed("2\n")}
        )
        result = self.run_main(music)
        self.assertEqual(result.code, _REFUSED)
        self.assertIn("changed during the read", result.stderr)
        self.assertFalse(self.target.exists())

    def test_a_batch_short_of_its_range_is_refused(self) -> None:
        music = bf.FakeMusic(
            tracks=[bf.INVENTED_TRACK, _SECOND],
            answers={(bf.LIST, 1): bf.completed(bf.row_of(bf.INVENTED_TRACK) + "\n")},
        )
        result = self.run_main(music)
        self.assertEqual(result.code, _REFUSED)
        self.assertIn("answered 1 row(s) for 2 tracks", result.stderr)
        self.assertFalse(self.target.exists())

    def test_an_unparsed_row_is_refused(self) -> None:
        reply = bf.row_of(bf.INVENTED_TRACK) + "not a row\n\n"
        music = bf.FakeMusic(
            tracks=[bf.INVENTED_TRACK, _SECOND],
            answers={(bf.LIST, 1): bf.completed(reply)},
        )
        result = self.run_main(music)
        self.assertEqual(result.code, _REFUSED)
        self.assertIn("1 row(s) could not be read", result.stderr)
        self.assertFalse(self.target.exists())


class BuildTest(CliCase):
    """5: a document with no track, or one the schema fails, is refused (exit 1)."""

    def test_an_empty_library_is_refused(self) -> None:
        result = self.run_main(bf.FakeMusic())
        self.assertEqual(result.code, _REFUSED)
        self.assertIn("no track to write", result.stderr)
        self.assertFalse(self.target.exists())

    def test_a_library_of_excluded_tracks_is_refused(self) -> None:
        nameless = dataclasses.replace(bf.INVENTED_TRACK, name="")
        result = self.run_main(bf.FakeMusic(tracks=[nameless]))
        self.assertEqual(result.code, _REFUSED)
        self.assertIn("no track to write", result.stderr)
        self.assertFalse(self.target.exists())

    def test_schema_findings_are_refused_at_most_ten_shown(self) -> None:
        found = [
            f"$.tracks[{n}].ls_year: fails the schema's 'type' rule" for n in range(12)
        ]
        with mock.patch.object(baseline_schema, "located_findings", return_value=found):
            result = self.run_main(bf.FakeMusic(tracks=[bf.INVENTED_TRACK]))
        self.assertEqual(result.code, _REFUSED)
        self.assertIn("12 schema finding(s)", result.stderr)
        self.assertIn("$.tracks[9].ls_year", result.stderr)
        self.assertNotIn("$.tracks[10].ls_year", result.stderr)
        self.assertFalse(self.target.exists())


class WriteTest(CliCase):
    """6: the document is written whole at 0600, then read back and confirmed."""

    def test_the_file_is_the_sorted_document_at_mode_0600(self) -> None:
        result = self.run_main(bf.FakeMusic(tracks=[_SECOND, bf.INVENTED_TRACK]))
        self.assertEqual(result.code, _WRITTEN)
        self.assertEqual(stat.S_IMODE(os.stat(self.target).st_mode), 0o600)
        document = self.written()
        self.assertEqual(baseline_schema.findings(document), [])
        text = self.target.read_text(encoding="utf-8")
        self.assertEqual(
            text,
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        tracks = document["tracks"]
        assert isinstance(tracks, list)
        self.assertEqual(
            [t["ls_persistent_id"] for t in tracks],
            [bf.INVENTED_TRACK.persistent_id, _SECOND.persistent_id],
        )

    def test_non_ascii_text_is_written_as_utf8_unescaped(self) -> None:
        accented = dataclasses.replace(bf.INVENTED_TRACK, name="Café Inventé")
        self.run_main(bf.FakeMusic(tracks=[accented]))
        self.assertIn("Café Inventé".encode(), self.target.read_bytes())

    def test_a_file_that_does_not_read_back_is_unconfirmed(self) -> None:
        def scribble(target: Path, _data: bytes) -> None:
            target.write_bytes(b"{not json")

        with mock.patch.object(report_file, "write_atomically", side_effect=scribble):
            result = self.run_main(bf.FakeMusic(tracks=[bf.INVENTED_TRACK]))
        self.assertEqual(result.code, _REFUSED)
        self.assertIn("unconfirmed", result.stderr)

    def test_a_file_that_reads_back_invalid_is_unconfirmed(self) -> None:
        def scribble(target: Path, _data: bytes) -> None:
            target.write_bytes(b"{}\n")

        with mock.patch.object(report_file, "write_atomically", side_effect=scribble):
            result = self.run_main(bf.FakeMusic(tracks=[bf.INVENTED_TRACK]))
        self.assertEqual(result.code, _REFUSED)
        self.assertIn("unconfirmed", result.stderr)

    def test_a_file_that_cannot_be_read_back_is_unconfirmed(self) -> None:
        real_write = report_file.write_atomically

        def write_then_break_reads(target: Path, data: bytes) -> None:
            real_write(target, data)
            broken.start()

        broken = mock.patch.object(
            Path, "read_bytes", side_effect=OSError(5, "Input/output error")
        )
        self.addCleanup(mock.patch.stopall)
        with mock.patch.object(
            report_file, "write_atomically", side_effect=write_then_break_reads
        ):
            result = self.run_main(bf.FakeMusic(tracks=[bf.INVENTED_TRACK]))
        mock.patch.stopall()
        self.assertEqual(result.code, _REFUSED)
        self.assertIn("unconfirmed", result.stderr)
        self.assertTrue(self.target.exists())

    def test_a_failed_write_cannot_run(self) -> None:
        with mock.patch.object(
            report_file, "write_atomically", side_effect=OSError(28, "No space left")
        ):
            result = self.run_main(bf.FakeMusic(tracks=[bf.INVENTED_TRACK]))
        self.assertEqual(result.code, _CANNOT)
        self.assertIn("cannot write", result.stderr)
        self.assertFalse(self.target.exists())

    def test_a_file_made_during_the_read_is_not_replaced(self) -> None:
        class Arriving(bf.FakeMusic):
            """A Music whose second count happens as another writer makes the file."""

            def __init__(self, target: Path) -> None:
                super().__init__(tracks=[bf.INVENTED_TRACK])
                self.target = target

            def _answer(self, kind: str, args: Sequence[str]) -> str:
                if kind == bf.COUNT and self.kinds().count(bf.COUNT) == 2:
                    self.target.write_bytes(b"arrived\n")
                return super()._answer(kind, args)

        result = self.run_main(Arriving(self.target))
        self.assertEqual(result.code, _CANNOT)
        self.assertIn("exists already", result.stderr)
        self.assertEqual(self.target.read_bytes(), b"arrived\n")

    def test_an_interrupt_writes_nothing(self) -> None:
        music = bf.FakeMusic(
            tracks=[bf.INVENTED_TRACK], answers={(bf.LIST, 1): KeyboardInterrupt()}
        )
        result = self.run_main(music)
        self.assertEqual(result.code, pcb.EXIT_INTERRUPTED)
        self.assertIn("interrupted; nothing written", result.stderr)
        self.assertFalse(self.target.exists())

    def test_an_interrupt_during_the_read_back_says_written_not_confirmed(self) -> None:
        real_findings = baseline_schema.located_findings
        calls: list[object] = []

        def interrupt_the_read_back(document: object) -> list[str]:
            # The first check is before the write; the second is the read-back.
            calls.append(document)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return real_findings(document)

        with mock.patch.object(
            baseline_schema, "located_findings", side_effect=interrupt_the_read_back
        ):
            result = self.run_main(bf.FakeMusic(tracks=[bf.INVENTED_TRACK]))
        self.assertEqual(result.code, pcb.EXIT_INTERRUPTED)
        self.assertIn(
            "interrupted; --output was written but not confirmed", result.stderr
        )
        self.assertNotIn("nothing written", result.stderr)
        self.assertTrue(self.target.exists())


class SummaryTest(CliCase):
    """7: aggregates only on stderr, never a name, title, or path; exit 0."""

    def test_the_summary_counts_read_written_excluded_and_missing(self) -> None:
        nameless = dataclasses.replace(
            bf.INVENTED_TRACK, persistent_id="1111111111111111", name=""
        )
        artistless = dataclasses.replace(
            bf.INVENTED_TRACK, persistent_id="2222222222222222", artist=""
        )
        tracks = [bf.INVENTED_TRACK, _SECOND, nameless, artistless]
        result = self.run_main(bf.FakeMusic(tracks=tracks))
        self.assertEqual(result.code, _WRITTEN)
        for line in (
            "tracks read: 4",
            "tracks written: 2",
            "excluded, no name: 1",
            "excluded, no artist: 1",
            "missing ls_album_artist: 1",
            "missing last_played_at: 1",
            "missing ls_file_path: 1",
            "missing release_name: 0",
        ):
            with self.subTest(line=line):
                self.assertIn(line, result.stderr.splitlines())

    def test_no_invented_title_name_or_path_reaches_stderr(self) -> None:
        tracks = [bf.INVENTED_TRACK, _SECOND]
        result = self.run_main(bf.FakeMusic(tracks=tracks))
        self.assertEqual(result.code, _WRITTEN)
        for track in tracks:
            for value in (
                track.name,
                track.artist,
                track.album,
                track.album_artist,
                track.genre,
                track.path,
            ):
                if value:
                    with self.subTest(value=value):
                        self.assertNotIn(value, result.stderr)


if __name__ == "__main__":
    unittest.main()
