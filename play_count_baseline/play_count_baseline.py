"""play_count_baseline: write Music.app's per-track play counts as a baseline file. Read-only.

The entry point of the tool folder, and the only module here that writes anything: the
baseline goes to ``--output``; progress, every refusal, and the summary to stderr.
Importing it puts the folder's private modules, under ``src/``, on ``sys.path``, then
tag_refresh's ``src/``, whose Music.app calls are this tool's seam (`baseline_calls`
reads through `music_calls`; `report_file` guards and writes the file), then the shared
libraries, each at one fixed place directly under the project root.

`main` validates, acts, confirms, and records: it refuses a target that exists, lies in
a git working tree, or has no folder, and a missing contract extra, before anything is
said to Music.app; asks Music whether it is running (this tool never launches it);
counts, lists in batches, and counts again, refusing a partial picture; maps the rows
(`baseline_map`) and checks the document against the contract copy (`baseline_schema`);
writes it atomically, at mode 0600; reads it back and checks it again; and prints only
aggregates. Nothing here ever writes to Music.app. The real runner, clock, stderr, and
platform are bound by `real_wiring`; a test passes its own `Wiring` instead.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

#: The private modules' folder, beside this file.
SRC_DIR = Path(__file__).resolve().parent / "src"
#: tag_refresh's private modules, the Music.app seam this tool shares: the sibling
#: tool folder's ``src/``, one fixed place under the project root.
SEAM_DIR = Path(__file__).resolve().parents[1] / "tag_refresh" / "src"
sys.path[:0] = [str(SRC_DIR), str(SEAM_DIR)]
# The shared libraries, each at one fixed place: directly under the project root, which
# is this file's grandparent. Deliberately not a search up the ancestors: that would
# also put any same-named folder above the checkout on sys.path, and whatever it holds
# would be imported in place of the real module. See stdio_utf8/stdio_utf8.md, "How this
# project's tools import it".
sys.path += [
    str(Path(__file__).resolve().parents[1] / name)
    for name in ("stdio_utf8", "help_formatter")
]

import baseline_calls  # noqa: E402 - import follows the sys.path bootstrap above
import baseline_map  # noqa: E402 - import follows the sys.path bootstrap above
import baseline_rows  # noqa: E402 - import follows the sys.path bootstrap above
import baseline_schema  # noqa: E402 - import follows the sys.path bootstrap above
import help_formatter  # noqa: E402 - import follows the sys.path bootstrap above
import music_calls  # noqa: E402 - import follows the sys.path bootstrap above
import report_file  # noqa: E402 - import follows the sys.path bootstrap above
import stdio_utf8  # noqa: E402 - import follows the sys.path bootstrap above

# music_calls is at the 500-line file cap, so its trailing-number match is imported
# under a public name, as baseline_calls imports its call primitive.
from music_calls import _error_number as error_number  # noqa: E402 - bootstrap above

#: The version every baseline names as its ``submission_client_version``.
VERSION = "0.1.0"
#: The one platform Music.app and ``osascript`` exist on.
_DARWIN = "darwin"
#: Tracks listed a call: library_audit's measured batch, twelve properties a call, far
#: inside music_calls' 35 s bound.
BATCH_TRACKS = 1000
#: How many schema findings a refusal prints; the rest are counted.
_FINDINGS_SHOWN = 10
#: The exit codes: written; the library refused (changed, partial, empty, invalid);
#: could not start or write; interrupted.
EXIT_WRITTEN, EXIT_REFUSED, EXIT_CANNOT, EXIT_INTERRUPTED = 0, 1, 2, 130


# --- Wiring --------------------------------------------------------------------------


@dataclass(frozen=True)
class Wiring:
    """What a run reaches outside the process: its runner, clock, stderr, and platform."""

    run: music_calls.Runner
    now: Callable[[], float]
    stderr: TextIO
    platform: str


def real_wiring() -> Wiring:
    """The real seams: ``osascript``, the clock, and this process's stderr and platform."""
    return Wiring(music_calls.real_run, time.time, sys.stderr, sys.platform)


# --- The options ---------------------------------------------------------------------

_EPILOG = """\
Prerequisites:
  macOS, with Music.app already running: it is asked whether it is running and is
  never launched by this tool, and it is only ever read from. The terminal that runs
  this needs the automation permission to control Music (System Settings > Privacy &
  Security > Automation); the first run asks for it. The toolbox's contract extra,
  pip install '.[contract]', which checks the baseline against the listensmith
  contract before it is written; without it the run exits 2 before reading anything.

Loading it:
  listensmith store import --path FILE

Exit codes:
  0    the baseline was written and read back valid
  1    the library refused: it changed during the read, a batch or row could not be
       read, no track could be written, the document failed the schema, or the
       written file could not be confirmed
  2    could not start or write: not macOS, --output exists, has no folder, or lies
       inside a git working tree, the contract extra is missing, Music.app is not
       running, a Music.app call failed or timed out, or the file could not be written
  130  interrupted (Ctrl-C): before the file is written, nothing is; during its
       read-back, --output was written but not confirmed"""


def build_parser() -> argparse.ArgumentParser:
    """The CLI: one required named option, the prerequisites in the epilog."""
    parser = stdio_utf8.EscapingArgumentParser(
        description="Write Music.app's per-track play counts as a listensmith baseline "
        "file. Read-only.",
        formatter_class=help_formatter.RawNoneHidingFormatter,
        epilog=_EPILOG,
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        metavar="FILE",
        help="The baseline file to write, at mode 0600. Required: there is no default. "
        "Refused when it exists already, its folder does not, or it lies inside a git "
        "working tree.",
    )
    return parser


# --- The run -------------------------------------------------------------------------


class _CannotStart(Exception):
    """The run cannot start or cannot write (exit 2): its one-line reason."""


class _InterruptedUnconfirmed(Exception):
    """Ctrl-C after the file was written, before its read-back confirmed it (exit 130)."""


class _Refused(Exception):
    """The library's answer cannot be written as a baseline (exit 1).

    Its message is the one-line reason; ``details`` are further lines printed under it.
    """

    def __init__(self, reason: str, details: Sequence[str] = ()) -> None:
        """Hold the reason and its detail lines."""
        super().__init__(reason)
        self.details = tuple(details)


def _notice(stream: TextIO, text: str) -> None:
    """One line of progress, a refusal, or the summary, escaped, on *stream*."""
    stdio_utf8.print_escaped(stdio_utf8.spell_unsafe(text), stream)


def _check_output(output: Path) -> None:
    """Refuse a target that exists (a dangling link too), or that `report_file` refuses."""
    if os.path.lexists(output):
        raise _CannotStart(
            f"--output {output} exists already; a snapshot is never replaced"
        )
    reason = report_file.refusal(output)
    if reason is not None:
        raise _CannotStart(f"--output: {reason}")


def _failed_call(stage: str, error: music_calls.MusicCallError) -> _CannotStart:
    """The refusal for a failed call at *stage*: its class and error number, no text.

    The reason is osascript's last stderr line or an excerpt of the reply, and an
    AppleScript runtime error quotes the value it failed on, a title or a path; so only
    what was being asked, whether it timed out, and the trailing number are kept.
    """
    kind = "timed out" if isinstance(error, music_calls.CallTimedOut) else "failed"
    number = error_number(error.reason)
    told = "no error number" if number is None else f"error {number}"
    return _CannotStart(f"Music.app {kind} at {stage} ({told})")


@contextlib.contextmanager
def _asking(stage: str) -> Iterator[None]:
    """Turn a failed Music.app call inside the block into `_failed_call`'s refusal."""
    try:
        yield
    except music_calls.MusicCallError as error:
        raise _failed_call(stage, error) from None


def _require_music(run: music_calls.Runner) -> None:
    """Ask Music.app whether it is running, without launching it; else cannot start."""
    with _asking("the probe"):
        running = music_calls.is_running(run=run)
    if not running:
        raise _CannotStart("start Music.app first; this tool never launches it")


def _list_batch(
    first: int, last: int, run: music_calls.Runner
) -> baseline_rows.ParsedRows:
    """Tracks *first* to *last*, refused unless one row answers for each index asked."""
    with _asking(f"the list of tracks {first}-{last}"):
        reply = baseline_calls.list_play_counts(first, last, run=run)
    parsed = baseline_rows.parse_play_rows(reply)
    answered, asked = len(parsed.rows) + parsed.unparsed, last - first + 1
    if answered != asked:
        raise _Refused(
            f"tracks {first}-{last} answered {answered} row(s) for {asked} tracks"
        )
    return parsed


def _read_library(wiring: Wiring) -> tuple[baseline_rows.RawTrack, ...]:
    """Every track: counted, listed a batch at a time, then counted again.

    A count that changed shifts every index after the change, so the batches no longer
    name one library; it, a batch short of its range, and any unparsed row are refused,
    because a baseline silently missing a track would read later as its first play.
    """
    with _asking("the count"):
        total = music_calls.count_tracks(run=wiring.run)
    rows: list[baseline_rows.RawTrack] = []
    unparsed = 0
    for first in range(1, total + 1, BATCH_TRACKS):
        last = min(first + BATCH_TRACKS - 1, total)
        _notice(wiring.stderr, f"tracks {first}-{last} of {total}")
        parsed = _list_batch(first, last, wiring.run)
        rows += parsed.rows
        unparsed += parsed.unparsed
    with _asking("the recount"):
        recount = music_calls.count_tracks(run=wiring.run)
    if recount != total:
        raise _Refused(
            f"Music.app's library changed during the read ({total} track(s), then "
            f"{recount}); run it again once nothing is importing"
        )
    if unparsed:
        raise _Refused(f"{unparsed} row(s) could not be read; no partial baseline")
    return tuple(rows)


def _schema_refusal(found: Sequence[str]) -> _Refused:
    """The refusal of a document with *found* findings, the first few named."""
    return _Refused(
        f"{len(found)} schema finding(s); nothing written", found[:_FINDINGS_SHOWN]
    )


def _build_and_check(
    rows: Sequence[baseline_rows.RawTrack], captured_at: int
) -> tuple[dict[str, object], baseline_map.Summary]:
    """The baseline document and its summary, refused when empty or invalid."""
    document, summary = baseline_map.build_document(
        rows, captured_at=captured_at, version=VERSION
    )
    if not summary.written:
        raise _Refused(
            f"no track to write ({summary.read} read); the contract needs at least one"
        )
    found = baseline_schema.located_findings(document)
    if found:
        raise _schema_refusal(found)
    return document, summary


def _reads_back_valid(output: Path) -> bool:
    """Whether *output* can be read, parses as JSON, and passes the schema."""
    try:
        return not baseline_schema.located_findings(json.loads(output.read_bytes()))
    # OSError: the file cannot be read back; ValueError: it is not UTF-8 JSON.
    except (OSError, ValueError):
        return False


def _write_and_confirm(output: Path, document: dict[str, object]) -> None:
    """Write *document* atomically, then read it back and check it again.

    The target is checked again first: a file made while Music was read is not
    replaced, and a folder that became part of a repository is not written into.
    """
    _check_output(output)
    text = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        report_file.write_atomically(output, text.encode("utf-8"))
    except OSError as error:
        raise _CannotStart(
            f"cannot write --output {output}: {error.strerror or error}"
        ) from None
    try:
        confirmed = _reads_back_valid(output)
    except KeyboardInterrupt:
        raise _InterruptedUnconfirmed from None
    if not confirmed:
        raise _Refused(
            f"--output {output} was written but is unconfirmed: it does not read back valid"
        )


def _report(stream: TextIO, summary: baseline_map.Summary) -> None:
    """The summary, aggregates only: never a name, a title, or a path."""
    _notice(stream, f"tracks read: {summary.read}")
    _notice(stream, f"tracks written: {summary.written}")
    for reason, count in summary.excluded.items():
        _notice(stream, f"excluded, {reason.value}: {count}")
    for key, count in summary.missing.items():
        _notice(stream, f"missing {key}: {count}")


def _run(output: Path, wiring: Wiring) -> baseline_map.Summary:
    """Validate, read, build, write, and confirm; return what was written."""
    _check_output(output)
    baseline_schema.require_contract()
    _require_music(wiring.run)
    captured_at = int(wiring.now())
    rows = _read_library(wiring)
    document, summary = _build_and_check(rows, captured_at)
    _write_and_confirm(output, document)
    return summary


def main(argv: Sequence[str] | None = None, *, wiring: Wiring | None = None) -> int:
    """Parse the options and write the baseline; return the exit code.

    *wiring* is the real one unless a test passes its own.
    """
    stdio_utf8.force_utf8_streams(sys.stdout, sys.stderr)
    parser = build_parser()
    args = parser.parse_args(argv)
    wiring = wiring or real_wiring()
    stream, prog = wiring.stderr, parser.prog
    # Before anything is read or asked: there is no Music.app to ask elsewhere.
    if wiring.platform != _DARWIN:
        _notice(
            stream,
            f"{prog}: needs macOS, where Music.app runs; this is {wiring.platform}",
        )
        return EXIT_CANNOT
    try:
        summary = _run(Path(os.path.abspath(args.output)), wiring)
    except (_CannotStart, baseline_schema.ContractMissing) as refusal:
        _notice(stream, f"{prog}: {refusal}")
        return EXIT_CANNOT
    except _Refused as refusal:
        _notice(stream, f"{prog}: {refusal}")
        for detail in refusal.details:
            _notice(stream, f"  {detail}")
        return EXIT_REFUSED
    # The file is written atomically at the very end, so an interrupt before
    # write_atomically returns leaves nothing, and one during it leaves no partial file.
    # One during the read-back after it leaves a file written but never confirmed.
    except KeyboardInterrupt:
        _notice(stream, f"{prog}: interrupted; nothing written")
        return EXIT_INTERRUPTED
    except _InterruptedUnconfirmed:
        _notice(stream, f"{prog}: interrupted; --output was written but not confirmed")
        return EXIT_INTERRUPTED
    _report(stream, summary)
    return EXIT_WRITTEN


if __name__ == "__main__":  # pragma: no cover - the CLI entry point; main() is tested
    sys.exit(main())
