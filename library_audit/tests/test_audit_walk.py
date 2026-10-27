"""audit_walk: the library folder's audio files, and where each Music.app track's file is.

The walk runs over a real temporary tree of invented files; placing tracks takes a fake
``stat`` where a test needs a path to report a device and inode of its choosing, and
the real one otherwise. Nothing reads a real library.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import audit_fixtures as af  # noqa: E402 - import follows the sys.path bootstrap above
import audit_rows as ar  # noqa: E402 - import follows the sys.path bootstrap above
import audit_walk as aw  # noqa: E402 - import follows the sys.path bootstrap above


def _row(path: str, status: str = "local only", number: int = 1) -> ar.TrackRow:
    """An invented listing row for a track whose file is at *path*."""
    return ar.TrackRow(af.pid(number), status, 1, number, path, "Album", "Band")


def _key(path: Path) -> tuple[int, int]:
    """The device and inode *path* stats to."""
    info = os.stat(path)
    return info.st_dev, info.st_ino


class WalkLibraryTest(af.AuditCase):
    """Which files the walk collects, and what it reports instead of collecting."""

    def walk(self) -> aw.Walked:
        """Walk the case's library with the real seams."""
        return aw.walk_library(self.library, walk=aw.real_walk, stat=os.stat)

    def test_audio_files_of_every_suffix_are_collected_in_path_order(self) -> None:
        names = [
            f"0{n} t{suffix}" for n, suffix in enumerate(sorted(aw.AUDIO_SUFFIXES))
        ]
        made = self.album("Band/Album", *names)
        upper = self.touch("library/Band/Album/99 LOUD.MP3")
        walked = self.walk()
        self.assertEqual([f.path for f in walked.files], sorted([*made, upper]))
        self.assertEqual(walked.files[0].key, _key(walked.files[0].path))
        self.assertEqual(walked.unreadable, ())

    def test_flac_is_not_collected_since_music_app_does_not_import_it(self) -> None:
        self.assertNotIn(".flac", aw.AUDIO_SUFFIXES)
        self.album("Band/Album", "01 a.flac")
        self.assertEqual(self.walk().files, ())

    def test_hidden_files_hidden_folders_and_other_files_are_skipped(self) -> None:
        kept = self.album("Band/Album", "01 a.mp3")
        self.touch("library/Band/Album/._01 a.mp3")
        self.touch("library/Band/Album/cover.jpg")
        self.touch("library/.hidden/01 b.mp3")
        self.assertEqual([f.path for f in self.walk().files], kept)

    def test_an_empty_library_holds_nothing(self) -> None:
        self.assertEqual(self.walk(), aw.Walked((), ()))

    def test_a_folder_the_walk_cannot_read_is_reported(self) -> None:
        def _walk(top: str, on_error: aw.OnError) -> aw.WalkResult:
            on_error(PermissionError(13, "Permission denied", f"{top}/Locked"))
            yield top, [], ["01 a.mp3"]

        self.album("", "01 a.mp3")
        walked = aw.walk_library(self.library, walk=_walk, stat=os.stat)
        self.assertEqual(len(walked.files), 1)
        self.assertEqual(
            walked.unreadable,
            (aw.Unreadable(self.library / "Locked", "Permission denied"),),
        )

    def test_a_file_that_cannot_be_stat_is_reported(self) -> None:
        self.album("Band/Album", "01 a.mp3")

        def _stat(path: str) -> os.stat_result:
            raise FileNotFoundError(2, "No such file or directory", path)

        walked = aw.walk_library(self.library, walk=aw.real_walk, stat=_stat)
        self.assertEqual(walked.files, ())
        self.assertEqual(
            walked.unreadable,
            (
                aw.Unreadable(
                    self.library / "Band/Album/01 a.mp3", "No such file or directory"
                ),
            ),
        )

    def test_each_file_keeps_its_size_and_placeholder_flag_from_the_one_stat(
        self,
    ) -> None:
        # A real placeholder cannot be made here, so the stat that marks one is
        # invented: the real stat, with the dataless flag among others in st_flags.
        here, away = self.album("Band/Album", "01 a.mp3", "02 b.mp3")
        here.write_bytes(b"12345")
        calls: list[str] = []

        def _stat(path: str) -> os.stat_result:
            calls.append(path)
            real = os.stat(path)
            flags = aw.SF_DATALESS | 0x20 if path == str(away) else 0x20
            return os.stat_result(tuple(real)[:10], {"st_flags": flags})

        walked = aw.walk_library(self.library, walk=aw.real_walk, stat=_stat)
        self.assertEqual(
            [(f.size, f.dataless) for f in walked.files],
            [(5, False), (len(af.FAKE_AUDIO), True)],
        )
        self.assertEqual(calls, [str(here), str(away)])

    def test_a_stat_with_no_flags_field_reads_as_local(self) -> None:
        # st_flags exists on macOS and the BSDs only: elsewhere no file is a placeholder.
        self.album("Band/Album", "01 a.mp3")

        def _stat(path: str) -> os.stat_result:
            return os.stat_result(tuple(os.stat(path))[:10])

        walked = aw.walk_library(self.library, walk=aw.real_walk, stat=_stat)
        self.assertFalse(walked.files[0].dataless)

    def test_an_error_with_no_text_or_filename_still_reports(self) -> None:
        def _walk(top: str, on_error: aw.OnError) -> aw.WalkResult:
            on_error(OSError())
            yield from ()

        walked = aw.walk_library(self.library, walk=_walk, stat=os.stat)
        self.assertEqual(walked.unreadable, (aw.Unreadable(self.library, "OSError()"),))


class PlaceTracksTest(af.AuditCase):
    """Each track lands in exactly one place: matched, gone, cloud-only or outside."""

    def setUp(self) -> None:
        """One library file, walked."""
        super().setUp()
        self.inside = self.album("Band/Album", "01 a.mp3")[0]
        self.files = aw.walk_library(
            self.library, walk=aw.real_walk, stat=os.stat
        ).files

    def place(self, *rows: ar.TrackRow) -> aw.Placed:
        """Place *rows* against the case's one file, with the real ``stat``."""
        return aw.place_tracks(rows, self.files, stat=os.stat)

    def test_a_track_whose_file_is_walked_is_matched_by_inode(self) -> None:
        row = _row(str(self.inside))
        placed = self.place(row)
        self.assertEqual(placed.matched, {_key(self.inside): (row,)})
        self.assertEqual((placed.gone, placed.cloud_only, placed.outside), ((), 0, 0))

    def test_two_tracks_of_one_file_are_both_matched(self) -> None:
        rows = (_row(str(self.inside), number=1), _row(str(self.inside), number=2))
        self.assertEqual(self.place(*rows).matched, {_key(self.inside): rows})

    def test_a_track_spelled_another_way_still_matches(self) -> None:
        link = self.root / "elsewhere"
        link.symlink_to(self.library)
        row = _row(str(link / "Band/Album/01 a.mp3"))
        self.assertEqual(self.place(row).matched, {_key(self.inside): (row,)})

    def test_a_track_whose_file_is_gone_is_listed(self) -> None:
        rows = (_row(str(self.library / "Band/Album/02 gone.mp3")), _row("", number=2))
        placed = self.place(*rows)
        self.assertEqual(placed.gone, rows)
        self.assertEqual(placed.matched, {})

    def test_no_local_file_with_a_cloud_copy_is_tallied(self) -> None:
        for status in sorted(aw.CLOUD_COPY_STATUSES):
            with self.subTest(status=status):
                rows = (
                    _row("", status),
                    _row(str(self.root / "gone.mp3"), status, number=2),
                )
                placed = self.place(*rows)
                self.assertEqual((placed.cloud_only, placed.gone), (2, ()))

    def test_a_track_of_another_class_with_no_path_follows_the_same_rule(
        self,
    ) -> None:
        # The listing gives a shared or URL track an empty path: a cloud copy status
        # tallies it as cloud-only, any other lists it as gone, like a file track.
        shared = ar.TrackRow(
            af.pid(1), "matched", 1, 1, "", "A", "B", False, "shared track"
        )
        url = ar.TrackRow(
            af.pid(2), "local only", 1, 2, "", "A", "B", False, "URL track"
        )
        placed = self.place(shared, url)
        self.assertEqual((placed.cloud_only, placed.gone), (1, (url,)))

    def test_a_cloud_status_with_a_local_file_is_matched_not_tallied(self) -> None:
        placed = self.place(_row(str(self.inside), "matched"))
        self.assertEqual((len(placed.matched), placed.cloud_only), (1, 0))

    def test_other_statuses_with_no_file_are_listed_as_gone(self) -> None:
        for status in ("local only", "ineligible", "removed", "error", ""):
            with self.subTest(status=status):
                self.assertEqual(len(self.place(_row("", status)).gone), 1)

    def test_a_track_whose_file_is_outside_the_library_is_tallied(self) -> None:
        outside = self.touch("elsewhere/01 x.mp3")
        placed = self.place(_row(str(outside)))
        self.assertEqual((placed.outside, placed.matched, placed.gone), (1, {}, ()))

    def test_a_path_stat_refuses_is_gone(self) -> None:
        def _stat(path: str) -> os.stat_result:
            raise ValueError("embedded null byte")

        placed = aw.place_tracks([_row("/L/a.mp3")], self.files, stat=_stat)
        self.assertEqual(len(placed.gone), 1)


if __name__ == "__main__":
    unittest.main()
