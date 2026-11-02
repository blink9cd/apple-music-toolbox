"""library_audit: find where a library folder's files and Music.app disagree. Read-only.

The entry point of the tool folder, and the only module here that writes output: the
report goes to stdout (or to ``--report``), progress and every refusal to stderr.
Importing it puts the folder's private modules, under ``src/``, on ``sys.path``,
then tag_refresh's ``src/``, whose Music.app calls are this tool's seam, then the
shared libraries, each at one fixed place directly under the project root.

The seam is a documented contract: this tool reads Music.app only through
`music_calls`, in the sibling ``tag_refresh/src/`` folder, with the same bounds,
failure types and ``Runner`` shape, so both tools stay one set of calls to get right.
Renaming or moving that folder breaks this import loudly, at start.

`main` checks the platform, the library folder, and asks Music whether it is running
before anything else is said to it (this tool never launches it). It then lists every
track in batches, confirms each batch accounted for its whole range and that the
count still holds after the last, walks the folder, places each track, reads the tags
(`audit_read`, which never opens an iCloud placeholder), groups files and tracks into
albums (`audit_groups`), finds the albums a spelling split (`audit_splits`) before
the gaps of the rest, runs the sync checks (`audit_sync`, with the full decode only
under ``--decode``), and prints the report (`audit_report`; the HTML page, which
goes to ``--report`` only, is `audit_html`'s). Nothing here ever writes
to Music.app or to a library file. The real runner, ``stat``, platform, walk, tag
reader, access check and decode runner are bound by `real_wiring`; a test passes its
own `Wiring` instead.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

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
    for name in ("stdio_utf8", "help_formatter", "bounded_run", "html_page")
]

import audit_checks  # noqa: E402 - import follows the sys.path bootstrap above
import audit_groups  # noqa: E402 - import follows the sys.path bootstrap above
import audit_html  # noqa: E402 - import follows the sys.path bootstrap above
import audit_read  # noqa: E402 - import follows the sys.path bootstrap above
import audit_report  # noqa: E402 - import follows the sys.path bootstrap above
import audit_rows  # noqa: E402 - import follows the sys.path bootstrap above
import audit_splits  # noqa: E402 - import follows the sys.path bootstrap above
import audit_sync  # noqa: E402 - import follows the sys.path bootstrap above
import audit_tags  # noqa: E402 - import follows the sys.path bootstrap above
import audit_walk  # noqa: E402 - import follows the sys.path bootstrap above
import bounded_run  # noqa: E402 - import follows the sys.path bootstrap above
import help_formatter  # noqa: E402 - import follows the sys.path bootstrap above
import html_page  # noqa: E402 - import follows the sys.path bootstrap above
import music_calls  # noqa: E402 - import follows the sys.path bootstrap above
import refresh_core  # noqa: E402 - import follows the sys.path bootstrap above
import report_file  # noqa: E402 - import follows the sys.path bootstrap above
import stdio_utf8  # noqa: E402 - import follows the sys.path bootstrap above

#: The one platform Music.app and ``osascript`` exist on.
_DARWIN = "darwin"
#: The three report formats. HTML goes to a file only (``--report``), and no format is
#: ever inferred from the report's name.
FORMAT_TEXT, FORMAT_JSON, FORMAT_HTML = "text", "json", "html"
#: The refusal of ``--format html`` with no ``--report``.
HTML_NEEDS_REPORT = "--format html needs --report: the page is written to a file only"
#: Tracks listed a call. Each call reads twelve properties for the whole range, one
#: Apple event each. Measured read-only on a library of about 20,000 tracks, reading them over
#: a plain track range took roughly 1 s per 250 tracks and 2.4 s per 2000, so a
#: thousand stays far inside the 35 s bound while keeping the calls few.
BATCH_TRACKS = 1000


# --- Wiring --------------------------------------------------------------------------


@dataclass(frozen=True)
class Wiring:
    """What a run reaches outside the process through.

    The call runner, ``stat``, the platform string, the folder walk, the tag
    reader (None when mutagen cannot be imported), the read-access check, and the
    runner each ``--decode`` call goes through.
    """

    run: music_calls.Runner
    stat: refresh_core.StatFn
    platform: str
    walk: audit_walk.WalkFn
    tag_reader: audit_tags.TagReader | None
    access: audit_sync.AccessFn
    decode: audit_sync.DecodeRunner


def real_decode_run(
    argv: list[str], timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run one decode through `bounded_run`, which kills the whole tree at *timeout*.

    Excluded from coverage as the real-process seam every test replaces.
    """
    return bounded_run.run_bounded(  # pragma: no cover - real-process IO seam, see docstring
        argv, timeout=timeout
    )


def real_wiring() -> Wiring:
    """The real seams: ``osascript``, ``os.stat``, ``os.walk``, mutagen, ``afconvert``."""
    return Wiring(
        music_calls.real_run,
        os.stat,
        sys.platform,
        audit_walk.real_walk,
        audit_tags.load_tag_reader(),
        os.access,
        real_decode_run,
    )


# --- The options ---------------------------------------------------------------------


class _HelpFormatter(
    help_formatter.ReqAwareDefaultsFormatter, argparse.RawDescriptionHelpFormatter
):
    """Every real default shown, the epilog's breaks kept.

    The two bases override different methods, so they compose. A default of None, which
    --decode takes in place of False, is no value a person could type, so it is not
    shown: each such option's help says instead what leaving it out or giving it means.
    """

    def _get_help_string(self, action: argparse.Action) -> str | None:
        """*action*'s help, with its default appended unless that default is None."""
        if action.default is None:
            return action.help
        return super()._get_help_string(action)


_EPILOG = f"""\
Prerequisites:
  macOS, with Music.app already running: it is asked whether it is running and is
  never launched by this tool (though a call in flight would relaunch it if it
  quit mid-run), and it is only ever read from. The terminal that runs this needs
  the automation permission to control Music (System Settings > Privacy & Security
  > Automation); the first run asks for it. The tag checks need mutagen, in the
  project's refresh_tags extra; without it they are skipped and the rest still run.

Formats:
  text (the default) and json print to stdout or --report; html writes one
  self-contained page of tables, so --format html needs --report. The format is
  never inferred from the report's name: --report audit.html alone writes text.

What it compares:
  every audio file under --library, hidden files and folders skipped, against every
  track Music.app lists, shared tracks included, {BATCH_TRACKS} tracks a call, matched
  by device and inode. Tracks with no local file but a cloud copy, and tracks whose
  files lie outside --library, are counted, not listed. Albums are grouped by their
  album artist (else artist), album and disc tags; by folder where tags cannot be
  read. The sync checks list iCloud placeholders, files that cannot be read, sizes
  Music.app has out of step with the file, and unchecked tracks; --decode adds a
  full decode of every matched local file with /usr/bin/afconvert, which takes
  hours on a large library. They see this Mac only, never the iPhone. See the
  companion doc.

Exit codes:
  0    nothing found
  1    findings
  2    could not start or run: not macOS, Music.app not running or the probe unanswered,
       --library not a readable folder, bad options (--format html without --report
       among them), a --report inside a git working tree or in a folder that does not
       exist, the tracks could not be listed (or the library changed while they were),
       afconvert could not be run (--decode), or the report could not be written
  130  interrupted (Ctrl-C): before the report, nothing is printed or written;
       while it is delivered, a --report file is left as it was and printed text
       may stop part way"""


def build_parser() -> argparse.ArgumentParser:
    """The CLI: every argument a named option, every real default shown."""
    parser = argparse.ArgumentParser(
        description="Find where a library folder's audio files and Music.app disagree. "
        "Read-only.",
        formatter_class=_HelpFormatter,
        epilog=_EPILOG,
    )
    parser.add_argument(
        "--library",
        required=True,
        type=Path,
        metavar="FOLDER",
        help="The library folder to walk. Required: there is no default.",
    )
    parser.add_argument(
        "--format",
        choices=(FORMAT_TEXT, FORMAT_JSON, FORMAT_HTML),
        default=FORMAT_TEXT,
        help="The report's form; html needs --report, and is never inferred from it.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        metavar="FILE",
        help="Write the report to FILE, replaced whole, instead of stdout; refused "
        "inside a git working tree. Left out, the report goes to stdout.",
    )
    parser.add_argument(
        "--decode",
        action="store_true",
        default=None,
        help="Also decode every matched, local, readable file in full with afconvert, "
        "listing each that does not decode. Slow: hours on a large library.",
    )
    return parser


def refuse_bad_report(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    """Exit 2 through *parser* when ``--report`` cannot be written, before any work."""
    if args.report is None:
        return
    reason = report_file.refusal(args.report)
    if reason is not None:
        parser.error(f"--report: {reason}")


def refuse_html_to_stdout(args: argparse.Namespace) -> str | None:
    """Why the options cannot run, when ``--format html`` names no ``--report``."""
    if args.format == FORMAT_HTML and args.report is None:
        return HTML_NEEDS_REPORT
    return None


# --- Output --------------------------------------------------------------------------


def _notice(text: str) -> None:
    """One line of progress or a refusal, on stderr."""
    stdio_utf8.print_escaped(html_page.shown(text), sys.stderr)


# --- The run -------------------------------------------------------------------------


class _CannotStart(Exception):
    """A run that cannot start, or cannot get what it compares: its one-line reason."""


def _require_folder(library: Path) -> None:
    """Refuse a library that is not a folder this process can list."""
    if not (library.is_dir() and os.access(library, os.R_OK | os.X_OK)):
        raise _CannotStart(f"--library {library} is not a readable folder")


def _require_music(wiring: Wiring) -> None:
    """Ask Music.app whether it is running, without launching it; else cannot start."""
    try:
        running = music_calls.is_running(run=wiring.run)
    except music_calls.MusicCallError as error:
        raise _CannotStart(
            f"cannot ask whether Music.app is running ({error.reason}); open Music and run this again"
        ) from None
    if not running:
        raise _CannotStart(
            "Music.app is not running: open Music and run this again (it is never launched for you)"
        )


def _list_batch(
    first: int, last: int, run: music_calls.Runner
) -> audit_rows.ParsedTracks:
    """Tracks *first* to *last*, confirmed to account for every index asked.

    A row parsed or counted unparsed stands for one track, so any other number of
    rows means the reply is not the range asked for, and is a failed call.
    """
    parsed = audit_rows.parse_track_rows(music_calls.list_tracks(first, last, run=run))
    answered, asked = len(parsed.rows) + parsed.unparsed, last - first + 1
    if answered != asked:
        raise music_calls.CallFailed(
            f"tracks {first}-{last} answered {answered} row(s) for {asked} tracks"
        )
    return parsed


def _list_batches(total: int, run: music_calls.Runner) -> audit_rows.ParsedTracks:
    """Every track 1 to *total*, listed a batch at a time with a progress line."""
    rows: list[audit_rows.TrackRow] = []
    unparsed = 0
    for first in range(1, total + 1, BATCH_TRACKS):
        last = min(first + BATCH_TRACKS - 1, total)
        _notice(f"tracks {first}-{last} of {total}")
        parsed = _list_batch(first, last, run)
        rows += parsed.rows
        unparsed += parsed.unparsed
    return audit_rows.ParsedTracks(tuple(rows), unparsed)


def _list_tracks(wiring: Wiring) -> tuple[int, audit_rows.ParsedTracks]:
    """Music.app's track count and every track listed; a failed call cannot run.

    A partial listing would report the unlisted tracks' files as having no track, so
    any failed or timed-out call, a batch short of its range, or a count that no
    longer holds after the last batch (tracks added or removed meanwhile shift every
    index after them) ends the run with no report at all.
    """
    try:
        total = music_calls.count_tracks(run=wiring.run)
        listed = _list_batches(total, wiring.run)
        recount = music_calls.count_tracks(run=wiring.run)
    except music_calls.MusicCallError as error:
        raise _CannotStart(f"cannot list Music.app's tracks ({error.reason})") from None
    if recount != total:
        raise _CannotStart(
            f"Music.app's library changed during the audit ({total} track(s), then"
            f" {recount}); run it again once nothing is importing"
        )
    if listed.unparsed:
        _notice(
            f"{listed.unparsed} listing row(s) unparsed: those tracks could not be placed"
        )
    return total, listed


def _count_differences(
    library: Path,
    walked: audit_walk.Walked,
    placed: audit_walk.Placed,
    read: audit_read.ReadTags | None,
    stat: refresh_core.StatFn,
) -> tuple[audit_checks.CountDiffers, ...]:
    """Files against Music.app's matched and gone tracks, per album group of *library*."""
    groups = audit_groups.file_groups(walked.files, None if read is None else read.tags)
    music = audit_groups.music_groups(
        walked.files,
        groups,
        placed.matched,
        placed.gone,
        library=library,
        by_folder=read is None,
        stat=stat,
    )
    return audit_checks.compare_counts(groups.values(), music)


@dataclass(frozen=True)
class _TagChecks:
    """What the tag checks found: the gaps, and the albums split by spelling."""

    gaps: tuple[audit_checks.Gap, ...]
    splits: tuple[audit_splits.Split, ...]


def _tag_checks(read: audit_read.ReadTags) -> _TagChecks:
    """The split albums, then the gaps of every group no split holds.

    A split album's halves would each show as a gap, so they are named once, as the
    split, and the numbers the joined album still lacks are reported there.
    """
    albums = audit_checks.album_numbers(read.tags.items())
    splits = audit_splits.find_splits(albums)
    joined = audit_splits.split_groups(splits)
    gaps = audit_checks.gaps_of(a for a in albums if a.group not in joined)
    return _TagChecks(gaps, splits)


def _gone_order(row: audit_rows.TrackRow) -> tuple[str, str, int, int, str]:
    """The report order of gone tracks: artist, album, disc, track."""
    return row.artist, row.album, row.disc, row.track, row.persistent_id


def _audit(library: Path, wiring: Wiring, decode: bool) -> audit_report.Audit:
    """Compare *library* with Music.app's tracks; return what was found."""
    _require_folder(library)
    _require_music(wiring)
    total, listed = _list_tracks(wiring)
    walked = audit_walk.walk_library(library, walk=wiring.walk, stat=wiring.stat)
    placed = audit_walk.place_tracks(listed.rows, walked.files, stat=wiring.stat)
    read = None
    checks: _TagChecks | None = None
    if wiring.tag_reader is not None:
        read = audit_read.read_library_tags(
            walked.files, wiring.tag_reader, placed.matched
        )
        checks = _tag_checks(read)
    sync = audit_sync.run_sync_checks(
        walked.files,
        placed,
        listed.rows,
        access=wiring.access,
        decode_run=wiring.decode if decode else None,
        progress=_notice,
    )
    return audit_report.Audit(
        library=library,
        audio_files=len(walked.files),
        music_tracks=total,
        no_track=tuple(f.path for f in walked.files if f.key not in placed.matched),
        file_gone=tuple(sorted(placed.gone, key=_gone_order)),
        gaps=None if checks is None else checks.gaps,
        splits=None if checks is None else checks.splits,
        no_track_number=None if read is None else read.no_track_number,
        count_differs=_count_differences(library, walked, placed, read, wiring.stat),
        unreadable_tags=None if read is None else read.unreadable,
        unreadable_paths=walked.unreadable,
        unparsed_rows=listed.unparsed,
        cloud_only=placed.cloud_only,
        outside_library=placed.outside,
        sync=sync,
    )


def _deliver(args: argparse.Namespace, audit: audit_report.Audit, prog: str) -> int:
    """Print or write the report in its format; return the run's exit code."""
    if args.format == FORMAT_JSON:
        text = audit_report.format_json(audit)
    elif args.format == FORMAT_HTML:
        # The JSON format's own object, so the page and the JSON never disagree.
        text = audit_html.format_html(audit_report.report_dict(audit))
    else:
        text = audit_report.format_text(audit)
    if args.report is None:
        print(text, end="")
        return audit_report.exit_code(audit)
    # Asked again at the moment of writing: the answer given at start may no longer
    # hold (a repository made around the folder while the audit ran, say).
    reason = report_file.refusal(args.report)
    if reason is not None:
        _notice(f"{prog}: --report: {reason}")
        return audit_report.EXIT_USAGE
    try:
        report_file.write_atomically(args.report, text.encode("utf-8"))
    except OSError as error:
        _notice(
            f"{prog}: cannot write the report {args.report}: {error.strerror or error}"
        )
        return audit_report.EXIT_USAGE
    return audit_report.exit_code(audit)


def main(argv: Sequence[str] | None = None, *, wiring: Wiring | None = None) -> int:
    """Parse the options and run the audit; return the exit code.

    *wiring* is the real one unless a test passes its own.
    """
    stdio_utf8.force_utf8_streams(sys.stdout, sys.stderr)
    parser = build_parser()
    args = parser.parse_args(argv)
    refuse_bad_report(parser, args)
    refusal = refuse_html_to_stdout(args)
    if refusal is not None:
        _notice(f"{parser.prog}: {refusal}")
        return audit_report.EXIT_USAGE
    wiring = wiring or real_wiring()
    # Before anything is read or asked: there is no Music.app to ask elsewhere.
    if wiring.platform != _DARWIN:
        _notice(
            f"{parser.prog}: needs macOS, where Music.app runs; this is {wiring.platform}"
        )
        return audit_report.EXIT_USAGE
    try:
        audit = _audit(Path(os.path.abspath(args.library)), wiring, bool(args.decode))
    # An afconvert that cannot start (--decode) cannot run the audit either.
    except (_CannotStart, audit_sync.DecodeUnavailable) as refusal:
        _notice(f"{parser.prog}: {refusal}")
        return audit_report.EXIT_USAGE
    # The audit prints nothing until it has everything: Ctrl-C anywhere before the
    # report leaves nothing half-written to report.
    except KeyboardInterrupt:
        _notice(f"{parser.prog}: interrupted; no report")
        return audit_report.EXIT_INTERRUPTED
    try:
        return _deliver(args, audit, parser.prog)
    # The atomic write leaves a --report file as it was; printed text may stop part way.
    except KeyboardInterrupt:
        _notice(f"{parser.prog}: interrupted; the report is incomplete or not written")
        return audit_report.EXIT_INTERRUPTED


if __name__ == "__main__":  # pragma: no cover - the CLI entry point; main() is tested
    sys.exit(main())
