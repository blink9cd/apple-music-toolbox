"""The sync checks through the entry point: their sections, their JSON, ``--decode``.

One invented album of five files, each showing one Mac-side cause of a track that will
not sync: a size out of step, an unchecked track, a size the listing could not give
exactly, an iCloud placeholder (an invented stat flag: a real one cannot be made here)
and a file the access check refuses. Music is the `audit_fixtures.FakeMusic` runner and
the decoder a recording fake, so nothing reaches Music.app or ``afconvert``. The tag
checks are left out (no reader), so the sections pinned here are the only findings.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import library_audit as la  # noqa: E402 - import follows the sys.path bootstrap above
import audit_fixtures as af  # noqa: E402 - import follows the sys.path bootstrap above
import audit_walk  # noqa: E402 - import follows the sys.path bootstrap above

_NOT_RUN = "decode check not run (--decode)"
_MAC_ONLY = (
    "the sync checks see this Mac only: Music.app cannot see an iPhone, so a track"
    " the phone lists but cannot play is not found here"
)
_PLACEHOLDER_NOTE = (
    "  note: a placeholder's audio is not on this Mac, so a Finder sync cannot copy it"
)
_SIZE_NOTE = "  note: Music.app's record is stale; tag_refresh makes it reread the file"
_UNCHECKED_NOTE = (
    "  note: an unchecked track is skipped only when the phone syncs only checked songs"
)
_DECODE_NOTE = "  note: afconvert tolerates some damage, so a file that decodes is not proven sound"


class _Decoder:
    """A recording decode runner: fails the sources named in *failing*, else succeeds."""

    def __init__(self, failing: dict[str, subprocess.CompletedProcess[str]]) -> None:
        """Hold the failures; record nothing yet."""
        self.failing = failing
        self.sources: list[str] = []

    def __call__(
        self, argv: list[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        """Record the source decoded, and answer for it."""
        self.sources.append(argv[-2])
        return self.failing.get(argv[-2], af.completed())


def _unstartable(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """A decode runner whose ``afconvert`` is missing."""
    raise FileNotFoundError(2, "No such file or directory", argv[0])


class SyncSectionsTest(af.AuditCase):
    """Each sync section, as the text report, the JSON report and the exit code show it."""

    def setUp(self) -> None:
        """The five files and their five tracks."""
        super().setUp()
        self.stale, self.off, self.vague, self.away, self.shut = self.album(
            "Band/Album", "a.mp3", "b.mp3", "c.mp3", "d.mp3", "e.mp3"
        )
        size = str(len(af.FAKE_AUDIO))
        self.music = af.FakeMusic(
            tracks=[
                af.Track(1, str(self.stale), track=1, size="1200"),
                af.Track(2, str(self.off), track=2, size=size, enabled=False),
                af.Track(3, str(self.vague), track=3, size="6.0E+8"),
                af.Track(4, str(self.away), track=4),
                af.Track(5, str(self.shut), track=5),
            ]
        )

    def seams(self, decode: la.audit_sync.DecodeRunner = af.never_decode) -> la.Wiring:
        """The wiring: the placeholder flagged by its stat, the refused file by access."""

        def _stat(path: str) -> os.stat_result:
            real = os.stat(path)
            flags = audit_walk.SF_DATALESS if path == str(self.away) else 0
            return os.stat_result(tuple(real)[:10], {"st_flags": flags})

        def _access(path: str, mode: int) -> bool:
            return path != str(self.shut)

        seams = af.wiring(self.music, access=_access, decode=decode)
        return dataclasses.replace(seams, stat=_stat)

    def run_audit(
        self, *extra: str, decode: la.audit_sync.DecodeRunner = af.never_decode
    ) -> af.Outcome:
        """The audit of the album with *extra* options."""
        argv = ["--library", str(self.library), *extra]
        return af.run_main(argv, self.seams(decode))

    def test_the_text_report_lists_each_sync_finding_with_its_note(self) -> None:
        result = self.run_audit()
        self.assertEqual(result.code, af.FINDINGS)
        lib = self.library
        self.assertEqual(
            result.stdout,
            f"library: {lib}\n"
            "files with no Music.app track: 0\n"
            "Music.app tracks whose file is gone: 0\n"
            "tag checks skipped: mutagen not installed\n"
            "files and Music.app tracks differ: 0\n"
            "unreadable files and folders: 1\n"
            f"  {self.shut}: read access refused\n"
            "iCloud placeholders: 1\n"
            f"  {self.away}\n"
            f"{_PLACEHOLDER_NOTE}\n"
            "Music.app size differs from the file: 1\n"
            f"  {self.stale}: Music.app 1200, file {len(af.FAKE_AUDIO)}\n"
            f"{_SIZE_NOTE}\n"
            "unchecked tracks: 1\n"
            f"  {af.BAND} / {af.ALBUM}, disc 1 track 2: {self.off}\n"
            f"{_UNCHECKED_NOTE}\n"
            f"{_NOT_RUN}\n"
            f"{_MAC_ONLY}\n"
            "summary: findings 4; audio files 5, Music.app tracks 5; cloud-only 0,"
            " outside --library 0, unparsed rows 0, sizes unknown 1\n",
        )

    def test_the_json_report_holds_every_sync_key(self) -> None:
        report = json.loads(self.run_audit("--format", "json").stdout)
        self.assertEqual(report["schema"], 4)
        self.assertEqual(report["findings"], 4)
        self.assertEqual(report["icloud_placeholders"], [str(self.away)])
        self.assertEqual(
            report["unreadable_paths"],
            [{"path": str(self.shut), "reason": "read access refused"}],
        )
        self.assertEqual(
            report["size_differs"],
            [
                {
                    "path": str(self.stale),
                    "persistent_id": af.pid(1),
                    "music_size": 1200,
                    "file_size": len(af.FAKE_AUDIO),
                }
            ],
        )
        self.assertEqual(
            report["unchecked"],
            [
                {
                    "persistent_id": af.pid(2),
                    "artist": af.BAND,
                    "album": af.ALBUM,
                    "disc": 1,
                    "track": 2,
                    "location": str(self.off),
                }
            ],
        )
        self.assertEqual(report["sizes_unknown"], 1)
        self.assertIsNone(report["decode_failed"])
        self.assertIsNone(report["decode_skipped"])

    def test_decode_lists_what_does_not_decode_and_counts_what_it_skipped(self) -> None:
        damaged = af.completed(returncode=1, stderr="Error: invented damage\n")
        decoder = _Decoder({str(self.vague): damaged})
        result = self.run_audit("--decode", decode=decoder)
        self.assertEqual(result.code, af.FINDINGS)
        self.assertEqual(
            decoder.sources, [str(self.stale), str(self.off), str(self.vague)]
        )
        tail = result.stdout.split(f"{_UNCHECKED_NOTE}\n", 1)[1]
        self.assertEqual(
            tail,
            "files that do not decode: 1\n"
            f"  {self.vague}: Error: invented damage\n"
            f"{_DECODE_NOTE}\n"
            "decode skipped: 2 (iCloud placeholders and files that cannot be read)\n"
            f"{_MAC_ONLY}\n"
            "summary: findings 5; audio files 5, Music.app tracks 5; cloud-only 0,"
            " outside --library 0, unparsed rows 0, sizes unknown 1\n",
        )

    def test_decode_in_json(self) -> None:
        decoder = _Decoder({str(self.stale): af.completed(returncode=1)})
        report = json.loads(
            self.run_audit("--decode", "--format", "json", decode=decoder).stdout
        )
        self.assertEqual(
            report["decode_failed"],
            [{"path": str(self.stale), "reason": "afconvert exited 1"}],
        )
        self.assertEqual(report["decode_skipped"], 2)
        self.assertEqual(report["findings"], 5)

    def test_a_clean_decode_has_an_empty_section_and_no_note(self) -> None:
        result = self.run_audit("--decode", decode=_Decoder({}))
        lines = result.stdout.splitlines()
        self.assertIn("files that do not decode: 0", lines)
        self.assertNotIn(_DECODE_NOTE, lines)

    def test_an_afconvert_that_cannot_run_ends_the_run_with_no_report(self) -> None:
        result = self.run_audit("--decode", decode=_unstartable)
        self.assertEqual(result.code, af.USAGE)
        self.assertIn("cannot run /usr/bin/afconvert", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_only_the_three_reading_scripts_are_sent_with_decode(self) -> None:
        self.run_audit("--decode", decode=_Decoder({}))
        self.assertEqual(set(self.music.kinds()), {af.IS_RUNNING, af.COUNT, af.LIST})


class CleanSyncTest(af.AuditCase):
    """A library with no sync finding shows each section empty and no note."""

    def test_empty_sections_carry_no_note(self) -> None:
        result = self.audit(af.FakeMusic())
        lines = result.stdout.splitlines()
        for header in (
            "iCloud placeholders: 0",
            "Music.app size differs from the file: 0",
            "unchecked tracks: 0",
            _NOT_RUN,
            _MAC_ONLY,
        ):
            with self.subTest(header=header):
                self.assertIn(header, lines)
        self.assertFalse(any(line.startswith("  note:") for line in lines))


if __name__ == "__main__":
    unittest.main()
