"""audit_sync: the Mac-side causes of a track that will not sync, and the opt-in decode.

Every seam is a fake: the access check is a table, the decoder a recording runner that
never starts a process, and every file an `AudioFile` built here, so nothing reads a
real library, reaches ``afconvert`` or opens an audio file. The one real thing is the
private temporary folder the decode writes into, which the suite checks is made and
removed.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import unittest
from collections.abc import Callable, Iterable
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import audit_fixtures as af  # noqa: E402 - import follows the sys.path bootstrap above
import audit_rows as ar  # noqa: E402 - import follows the sys.path bootstrap above
import audit_sync as asy  # noqa: E402 - import follows the sys.path bootstrap above
import audit_walk as aw  # noqa: E402 - import follows the sys.path bootstrap above

_LIB = Path("/invented/library")


def _file(
    name: str, number: int, *, size: int = 0, dataless: bool = False
) -> aw.AudioFile:
    """An invented walked file *name*, keyed by *number*."""
    return aw.AudioFile(_LIB / name, (1, number), size, dataless)


def _row(
    number: int,
    *,
    size: int | None = 0,
    enabled: bool = True,
    path: str = "",
    artist: str = af.BAND,
) -> ar.TrackRow:
    """An invented listing row."""
    return ar.TrackRow(
        af.pid(number),
        "local only",
        1,
        number,
        path,
        af.ALBUM,
        artist,
        False,
        ar.FILE_TRACK,
        enabled,
        size,
    )


def _placed(pairs: Iterable[tuple[aw.AudioFile, ar.TrackRow]]) -> aw.Placed:
    """Each file matched to its row, nothing gone or tallied."""
    matched: dict[tuple[int, int], tuple[ar.TrackRow, ...]] = {}
    for audio, row in pairs:
        matched[audio.key] = (*matched.get(audio.key, ()), row)
    return aw.Placed(matched, (), 0, 0)


def _access(refused: Iterable[Path] = ()) -> tuple[asy.AccessFn, list[tuple[str, int]]]:
    """An access check refusing *refused*, and the list of every question asked."""
    asked: list[tuple[str, int]] = []
    shut = {str(p) for p in refused}

    def _check(path: str, mode: int) -> bool:
        asked.append((path, mode))
        return path not in shut

    return _check, asked


_Answer = subprocess.CompletedProcess[str] | BaseException


def _always(answer: _Answer) -> Callable[[str], _Answer]:
    """A decoder answer that is *answer* whatever the source."""

    def _answer(_source: str) -> _Answer:
        return answer

    return _answer


class _Decoder:
    """A recording stand-in for ``afconvert``: never starts a process.

    Each call writes the output file it was asked for, so the suite can see it was
    removed; *answer* says what a call returns or raises, by the source path.
    """

    def __init__(
        self,
        answer: Callable[[str], _Answer] | None = None,
    ) -> None:
        """Hold *answer*; record nothing yet."""
        self.answer = answer
        self.calls: list[tuple[list[str], float]] = []
        self.outputs: list[Path] = []

    def __call__(
        self, argv: list[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        """Record the call, write its output file, then answer."""
        self.calls.append((list(argv), timeout))
        out = Path(argv[-1])
        out.write_bytes(b"invented")
        self.outputs.append(out)
        found = af.completed() if self.answer is None else self.answer(argv[-2])
        if isinstance(found, BaseException):
            raise found
        return found


class PlaceholderFlagTest(unittest.TestCase):
    """The iCloud placeholder flag, as macOS defines it."""

    def test_the_flag_is_macos_sf_dataless(self) -> None:
        self.assertEqual(aw.SF_DATALESS, 0x40000000)
        self.assertEqual(aw.SF_DATALESS, getattr(stat, "SF_DATALESS", 0x40000000))


class PlaceholderTest(unittest.TestCase):
    """A placeholder is listed, and never so much as asked about."""

    def test_each_placeholder_is_listed_and_never_access_checked(self) -> None:
        here, away = _file("a.mp3", 1), _file("b.mp3", 2, dataless=True)
        check, asked = _access()
        result = asy.run_sync_checks(
            [here, away], _placed([]), [], access=check, decode_run=None, progress=print
        )
        self.assertEqual(result.placeholders, (away.path,))
        self.assertEqual(asked, [(str(here.path), os.R_OK)])
        self.assertEqual(result.refused, ())


class RefusedTest(unittest.TestCase):
    """A file the tool may not read is listed with a reason."""

    def test_a_refused_file_is_unreadable_with_its_reason(self) -> None:
        shut, fine = _file("a.mp3", 1), _file("b.mp3", 2)
        check, _ = _access([shut.path])
        result = asy.run_sync_checks(
            [shut, fine], _placed([]), [], access=check, decode_run=None, progress=print
        )
        self.assertEqual(
            result.refused, (aw.Unreadable(shut.path, asy.REFUSED_REASON),)
        )


class SizeTest(unittest.TestCase):
    """Music.app's size against the file's; unknown is counted, never a mismatch."""

    def run_sizes(
        self, pairs: list[tuple[aw.AudioFile, ar.TrackRow]]
    ) -> asy.SyncResult:
        """The checks over *pairs*, every file readable."""
        check, _ = _access()
        return asy.run_sync_checks(
            list(dict.fromkeys(audio for audio, _ in pairs)),
            _placed(pairs),
            [row for _, row in pairs],
            access=check,
            decode_run=None,
            progress=print,
        )

    def test_a_size_out_of_step_is_listed_with_both_numbers(self) -> None:
        audio, row = _file("a.mp3", 1, size=900), _row(1, size=1200)
        result = self.run_sizes([(audio, row)])
        self.assertEqual(
            result.size_differs, (asy.SizeDiffers(audio.path, row, 1200, 900),)
        )
        self.assertEqual(result.sizes_unknown, 0)

    def test_equal_sizes_and_no_listed_size_are_not_findings(self) -> None:
        result = self.run_sizes(
            [
                (_file("a.mp3", 1, size=900), _row(1, size=900)),
                (_file("b.mp3", 2, size=900), _row(2, size=0)),
            ]
        )
        self.assertEqual(result.size_differs, ())
        self.assertEqual(result.sizes_unknown, 0)

    def test_an_unknown_size_is_counted_and_never_a_mismatch(self) -> None:
        result = self.run_sizes([(_file("a.mp3", 1, size=900), _row(1, size=None))])
        self.assertEqual(result.size_differs, ())
        self.assertEqual(result.sizes_unknown, 1)

    def test_a_size_past_applescript_s_integers_compares_exactly(self) -> None:
        # 536,870,911 is AppleScript's largest integer: one byte past it still differs.
        big = 600_000_123
        audio, row = _file("a.mp3", 1, size=big + 1), _row(1, size=big)
        self.assertEqual(len(self.run_sizes([(audio, row)]).size_differs), 1)

    def test_each_track_two_tracks_share_is_judged(self) -> None:
        audio = _file("a.mp3", 1, size=5)
        result = self.run_sizes([(audio, _row(1, size=6)), (audio, _row(2, size=7))])
        self.assertEqual([d.music_size for d in result.size_differs], [6, 7])


class UncheckedTest(unittest.TestCase):
    """Every unchecked track is listed, in artist, album, disc, track order."""

    def test_unchecked_tracks_of_any_placement_are_listed_in_order(self) -> None:
        rows = [
            _row(3, enabled=False, artist="Zed"),
            _row(1, enabled=True),
            _row(2, enabled=False, path="/invented/elsewhere.mp3"),
        ]
        check, _ = _access()
        result = asy.run_sync_checks(
            [], _placed([]), rows, access=check, decode_run=None, progress=print
        )
        self.assertEqual(result.unchecked, (rows[2], rows[0]))


class DecodeTest(unittest.TestCase):
    """The opt-in decode: which files, how it is called, and what it leaves behind."""

    def setUp(self) -> None:
        """Three matched files: one local, one placeholder, one refused; one unmatched."""
        super().setUp()
        self.local = _file("1.mp3", 1)
        self.away = _file("2.mp3", 2, dataless=True)
        self.shut = _file("3.mp3", 3)
        self.loose = _file("4.mp3", 4)
        self.placed = _placed(
            [(self.local, _row(1)), (self.away, _row(2)), (self.shut, _row(3))]
        )
        self.notices: list[str] = []

    def decode(self, decoder: _Decoder) -> asy.SyncResult:
        """The checks with *decoder* as the decode runner."""
        check, _ = _access([self.shut.path])
        return asy.run_sync_checks(
            [self.local, self.away, self.shut, self.loose],
            self.placed,
            [],
            access=check,
            decode_run=decoder,
            progress=self.notices.append,
        )

    def test_without_a_runner_the_decode_does_not_run(self) -> None:
        check, _ = _access()
        result = asy.run_sync_checks(
            [self.local], self.placed, [], access=check, decode_run=None, progress=print
        )
        self.assertIsNone(result.decoded)

    def test_only_matched_local_readable_files_are_decoded(self) -> None:
        decoder = _Decoder()
        result = self.decode(decoder)
        self.assertEqual(
            [argv[-2] for argv, _ in decoder.calls], [str(self.local.path)]
        )
        self.assertEqual(result.decoded, asy.Decoded((), 2))

    def test_the_call_is_afconvert_to_wave_with_its_bound(self) -> None:
        decoder = _Decoder()
        self.decode(decoder)
        argv, timeout = decoder.calls[0]
        self.assertEqual(
            argv[:-1],
            ["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16", str(self.local.path)],
        )
        self.assertEqual(timeout, asy.DECODE_TIMEOUT_S)
        self.assertTrue(argv[-1].endswith(".wav"))

    def test_the_output_goes_to_a_private_folder_removed_after(self) -> None:
        seen: list[tuple[Path, int]] = []

        def _answer(_source: str) -> subprocess.CompletedProcess[str]:
            folder = decoder.outputs[-1].parent
            seen.append((folder, stat.S_IMODE(folder.stat().st_mode)))
            return af.completed()

        decoder = _Decoder(_answer)
        self.decode(decoder)
        folder, mode = seen[0]
        self.assertNotEqual(folder, self.local.path.parent)
        self.assertEqual(mode, 0o700)
        self.assertFalse(decoder.outputs[0].exists())
        self.assertFalse(folder.exists())

    def test_each_output_is_deleted_before_the_next_decode(self) -> None:
        self.placed = _placed([(self.local, _row(1)), (self.loose, _row(4))])
        alive: list[bool] = []

        def _answer(_source: str) -> subprocess.CompletedProcess[str]:
            alive.extend(out.exists() for out in decoder.outputs[:-1])
            return af.completed()

        decoder = _Decoder(_answer)
        self.decode(decoder)
        self.assertEqual(len(decoder.calls), 2)
        self.assertEqual(alive, [False])

    def test_a_failed_decode_is_a_finding_with_afconvert_s_last_line(self) -> None:
        failed = af.completed(
            "", returncode=1, stderr="reading\nError: invented damage ('dta?')\n\n"
        )
        result = self.decode(_Decoder(_always(failed)))
        assert result.decoded is not None
        self.assertEqual(
            result.decoded.failed,
            (asy.DecodeFailure(self.local.path, "Error: invented damage ('dta?')"),),
        )

    def test_a_failure_with_no_stderr_falls_back_to_stdout_then_the_code(self) -> None:
        for answer, reason in (
            (af.completed("said on stdout\n", returncode=3), "said on stdout"),
            (af.completed("", returncode=3), "afconvert exited 3"),
        ):
            with self.subTest(reason=reason):
                result = self.decode(_Decoder(_always(answer)))
                assert result.decoded is not None
                self.assertEqual(result.decoded.failed[0].reason, reason)

    def test_a_decode_past_its_bound_is_a_finding(self) -> None:
        late = subprocess.TimeoutExpired(cmd=["afconvert"], timeout=1)
        result = self.decode(_Decoder(_always(late)))
        assert result.decoded is not None
        self.assertIn("did not finish within", result.decoded.failed[0].reason)

    def test_an_afconvert_that_cannot_start_ends_the_check(self) -> None:
        with self.assertRaises(asy.DecodeUnavailable) as raised:
            self.decode(_Decoder(_always(FileNotFoundError(2, "No such file"))))
        self.assertIn("cannot run /usr/bin/afconvert", raised.exception.reason)

    def test_the_private_folder_is_removed_when_the_decode_is_cut_short(self) -> None:
        for raised, stops in (
            (KeyboardInterrupt(), KeyboardInterrupt),
            (FileNotFoundError(2, "No such file"), asy.DecodeUnavailable),
        ):
            with self.subTest(stops=stops.__name__):
                decoder = _Decoder(_always(raised))
                with self.assertRaises(stops):
                    self.decode(decoder)
                folder = decoder.outputs[0].parent
                self.assertNotEqual(folder, self.local.path.parent)
                self.assertFalse(folder.exists())

    def test_one_progress_line_per_five_hundred_files(self) -> None:
        files = [_file(f"{n:04}.mp3", n) for n in range(1, 1002)]
        placed = _placed((audio, _row(n)) for n, audio in enumerate(files, 1))
        check, _ = _access()
        asy.run_sync_checks(
            files,
            placed,
            [],
            access=check,
            decode_run=_Decoder(),
            progress=self.notices.append,
        )
        self.assertEqual(self.notices, ["decoded 500 of 1001", "decoded 1000 of 1001"])


if __name__ == "__main__":
    unittest.main()
