"""The causes of a track that will not sync to an iPhone that this Mac can see.

Read-only, like the rest of the tool. The cheap checks use only what the walk, its one
``stat`` per file, and the listing already hold, plus one ``access`` question per file:
an iCloud placeholder (its audio is not on this Mac, so a Finder sync cannot copy it),
a file this process may not read, Music.app's size out of step with the file's, and an
unchecked track. None of them opens a file. `decode_files` is the slow, opt-in check: a
full decode of each matched, local, readable file with ``afconvert`` into a private
temporary folder, never beside the audio.

What none of this can see is the phone: Music.app cannot script an iPhone, so a track
the phone lists but cannot play is invisible here. The access check, the decoder and
the progress line are seams, so a test reaches neither a real file's bytes nor
``afconvert``.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from audit_rows import TrackRow
from audit_walk import AudioFile, Placed, Unreadable

#: The decoder, by its absolute path: a decode never depends on what ``PATH`` finds.
AFCONVERT = "/usr/bin/afconvert"
#: Decode to 16-bit little-endian PCM in a WAVE file: every byte of audio is decoded.
_DECODE_FORMAT = ("-f", "WAVE", "-d", "LEI16")
#: One file's decode bound. Measured here, a 7-minute 320 kbps track decoded in well
#: under 5 s, so a 2-minute bound leaves room for an hour-long file on a slow disk while
#: still ending a decoder that hangs on a damaged file.
DECODE_TIMEOUT_S = 120.0
#: One progress line per this many files decoded: a full library takes hours.
PROGRESS_EVERY = 500
#: Why a file the access check refuses is listed.
REFUSED_REASON = "read access refused"
#: The decoded copy's suffix, inside the private folder.
_WAVE_SUFFIX = ".wav"

#: ``os.access``'s shape: a path and a mode, answering whether it is allowed.
AccessFn = Callable[[str, int], bool]
#: Runs one decode: ``(argv, timeout_seconds) -> completed process``.
DecodeRunner = Callable[[list[str], float], "subprocess.CompletedProcess[str]"]
#: Takes one line of progress.
ProgressFn = Callable[[str], None]


class DecodeUnavailable(Exception):
    """``afconvert`` could not be started at all; ``reason`` says why."""

    def __init__(self, reason: str) -> None:
        """Keep *reason*, one line fit for the caller's refusal."""
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SizeDiffers:
    """A matched track whose listed size is not its file's: Music.app's record is stale."""

    path: Path
    row: TrackRow
    music_size: int
    file_size: int


@dataclass(frozen=True)
class DecodeFailure:
    """A file ``afconvert`` could not decode, and its one-line reason."""

    path: Path
    reason: str


@dataclass(frozen=True)
class Decoded:
    """What the decode found, and how many matched files it skipped.

    A matched file is skipped when it is an iCloud placeholder (decoding would download
    it) or when this process may not read it.
    """

    failed: tuple[DecodeFailure, ...]
    skipped: int


@dataclass(frozen=True)
class SyncResult:
    """What the sync checks found, every list in report order.

    ``refused`` joins the report's unreadable files and folders. ``sizes_unknown``
    counts the matched tracks whose listed size was not an exact integer, which are
    never judged. ``decoded`` is None when the decode did not run.
    """

    placeholders: tuple[Path, ...]
    refused: tuple[Unreadable, ...]
    size_differs: tuple[SizeDiffers, ...]
    unchecked: tuple[TrackRow, ...]
    sizes_unknown: int
    decoded: Decoded | None


def _refused(files: Iterable[AudioFile], access: AccessFn) -> tuple[Unreadable, ...]:
    """Each file, not a placeholder, that *access* says this process may not read."""
    return tuple(
        Unreadable(f.path, REFUSED_REASON)
        for f in files
        if not f.dataless and not access(str(f.path), os.R_OK)
    )


def _sizes(
    files: Iterable[AudioFile], placed: Placed
) -> tuple[tuple[SizeDiffers, ...], int]:
    """Each matched track whose known, non-zero size differs; and the unknown count."""
    differs: list[SizeDiffers] = []
    unknown = 0
    for audio in files:
        for row in placed.matched.get(audio.key, ()):
            if row.size is None:
                unknown += 1
            elif row.size and row.size != audio.size:
                differs.append(SizeDiffers(audio.path, row, row.size, audio.size))
    return tuple(differs), unknown


def _track_order(row: TrackRow) -> tuple[str, str, int, int, str]:
    """The report order of tracks: artist, album, disc, track."""
    return row.artist, row.album, row.disc, row.track, row.persistent_id


def _one_line(result: subprocess.CompletedProcess[str]) -> str:
    """The last non-blank line ``afconvert`` wrote, stderr first, else its exit code."""
    for stream in (result.stderr, result.stdout):
        lines = [line.strip() for line in stream.splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return f"afconvert exited {result.returncode}"


def _decode_one(path: Path, out: Path, run: DecodeRunner) -> str | None:
    """Decode *path* into *out*; None when it decoded, else why it did not.

    *out* is deleted whatever happened, so no decoded copy outlives its own check.
    """
    argv = [AFCONVERT, *_DECODE_FORMAT, str(path), str(out)]
    try:
        result = run(argv, DECODE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"did not finish within {DECODE_TIMEOUT_S:g} s"
    except OSError as error:
        raise DecodeUnavailable(
            f"cannot run {AFCONVERT}: {error.strerror or error}"
        ) from None
    finally:
        out.unlink(missing_ok=True)
    return None if result.returncode == 0 else _one_line(result)


def decode_files(
    paths: Sequence[Path], *, run: DecodeRunner, progress: ProgressFn
) -> tuple[DecodeFailure, ...]:
    """Decode each of *paths* fully, in order, into a private temporary folder.

    The folder is made readable by this user only and removed at the end; each decoded
    copy is deleted as soon as its decode ends. Raises `DecodeUnavailable` when
    ``afconvert`` cannot be started.
    """
    failed: list[DecodeFailure] = []
    with tempfile.TemporaryDirectory(prefix="library_audit-decode-") as scratch:
        for done, path in enumerate(paths, 1):
            out = Path(scratch) / f"{done}{_WAVE_SUFFIX}"
            reason = _decode_one(path, out, run)
            if reason is not None:
                failed.append(DecodeFailure(path, reason))
            if done % PROGRESS_EVERY == 0:
                progress(f"decoded {done} of {len(paths)}")
    return tuple(failed)


def _decode(
    files: Sequence[AudioFile],
    placed: Placed,
    refused: Iterable[Unreadable],
    run: DecodeRunner,
    progress: ProgressFn,
) -> Decoded:
    """Decode every matched file that is local and readable; count the rest skipped."""
    shut = {u.path for u in refused}
    matched = [f for f in files if f.key in placed.matched]
    wanted = [f.path for f in matched if not f.dataless and f.path not in shut]
    failed = decode_files(wanted, run=run, progress=progress)
    return Decoded(failed, len(matched) - len(wanted))


def run_sync_checks(
    files: Sequence[AudioFile],
    placed: Placed,
    rows: Iterable[TrackRow],
    *,
    access: AccessFn,
    decode_run: DecodeRunner | None,
    progress: ProgressFn,
) -> SyncResult:
    """Every sync check over the walked *files*, their placing and the listed *rows*.

    The decode runs only when *decode_run* is given (``--decode``).
    """
    refused = _refused(files, access)
    differs, unknown = _sizes(files, placed)
    decoded = None
    if decode_run is not None:
        decoded = _decode(files, placed, refused, decode_run, progress)
    return SyncResult(
        placeholders=tuple(f.path for f in files if f.dataless),
        refused=refused,
        size_differs=differs,
        unchecked=tuple(sorted((r for r in rows if not r.enabled), key=_track_order)),
        sizes_unknown=unknown,
        decoded=decoded,
    )
