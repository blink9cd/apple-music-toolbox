"""tag_refresh: make Music.app reread the tags of MP3s whose tags changed.

The entry point of the tool folder, and the only module here that writes output: the
report goes to stdout, progress and every refusal or skipped input to stderr.
Importing it puts the folder's private modules, under ``src/``, on ``sys.path``,
resolved from this file's own location, then the shared libraries it uses, each at
one fixed place directly under the project root.

Two modes: ``--whole-library`` refreshes every file track Music.app holds, a
batch at a time; explicit mode refreshes the MP3s that ``--track``, ``--album`` and
``--tracks-from`` name, looked up per album folder and matched by device and inode.
`main` checks the platform, collects the explicit sources, asks Music whether it is
running before anything else is said to it (it never launches Music itself, though a
``tell`` relaunches it if Music quits mid-run), runs the mode
(`refresh_run`) and prints its report (`refresh_report`); ``--missing-list`` then
writes the paths Music lacks to a file (`report_file`). The real runner, ``stat``,
platform, tag reader and standard input are bound by `real_wiring`; a test passes its
own `Wiring` instead.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The private modules' folder, beside this file.
SRC_DIR = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC_DIR))
# The shared libraries, each at one fixed place: directly under the project root, which
# is this file's grandparent. Deliberately not a search up the ancestors: that would
# also put any same-named folder above the checkout on sys.path, and whatever it holds
# would be imported in place of the real module. A library that is absent fails loudly
# at the import below rather than being silently skipped. See stdio_utf8/stdio_utf8.md,
# "How this project's tools import it".
sys.path += [
    str(Path(__file__).resolve().parents[1] / name)
    for name in ("stdio_utf8", "help_formatter", "html_page")
]

import help_formatter  # noqa: E402 - import follows the sys.path bootstrap above
import music_calls  # noqa: E402 - import follows the sys.path bootstrap above
import refresh_core  # noqa: E402 - import follows the sys.path bootstrap above
import refresh_report  # noqa: E402 - import follows the sys.path bootstrap above
import refresh_run  # noqa: E402 - import follows the sys.path bootstrap above
import report_file  # noqa: E402 - import follows the sys.path bootstrap above
import stdio_utf8  # noqa: E402 - import follows the sys.path bootstrap above

#: The one platform Music.app and ``osascript`` exist on.
_DARWIN = "darwin"
#: The ``--tracks-from`` value that reads the list from standard input.
STDIN_LIST = "-"
#: The explicit sources, as ``(attribute, option)``: any of them chooses explicit mode.
_SOURCES = (
    ("track", "--track"),
    ("album", "--album"),
    ("tracks_from", "--tracks-from"),
)
#: The hint printed after the not-in-Music list when mutagen could not be imported.
NO_MUTAGEN_HINT = (
    "hint: mutagen is not installed, so no album tag was asked for; installing the "
    "project's refresh_tags extra (pip install \".[refresh_tags]\") asks each MP3's album tag too"
)


# --- Wiring --------------------------------------------------------------------------


@dataclass(frozen=True)
class Wiring:
    """What a run reaches outside the process through.

    The call runner, ``stat``, the platform string, the album-tag reader (None when
    mutagen cannot be imported), and the reader of standard input's bytes.
    """

    run: music_calls.Runner
    stat: refresh_core.StatFn
    platform: str
    tag_reader: refresh_core.TagReader | None
    read_stdin: Callable[[], bytes]


def load_tag_reader() -> refresh_core.TagReader | None:
    """Return mutagen's album-tag (``TALB``) reader when mutagen imports, else None.

    mutagen lives in the project's ``refresh_tags`` extra, and the core tools import no
    third-party package, so it is optional here. The reader returns the tag's first
    value, and None for a file with no tag, no album frame or no text in it, and on
    any error reading it: `refresh_core` leaves the reader to catch its own.
    """
    try:
        from mutagen import MutagenError
        from mutagen.id3 import ID3
    except ImportError:
        return None

    def read_album_tag(path: Path) -> str | None:
        """The first album value of *path*'s ID3 tag, or None."""
        try:
            frame = ID3(path).get("TALB")
        except (MutagenError, OSError, ValueError):
            return None
        if frame is None or not frame.text:
            return None
        return str(frame.text[0])

    return read_album_tag


def _read_stdin() -> bytes:
    """Standard input's bytes, read to its end."""
    return sys.stdin.buffer.read()


def real_wiring() -> Wiring:
    """The real runner, ``os.stat``, this platform, mutagen's reader, real stdin."""
    return Wiring(
        music_calls.real_run, os.stat, sys.platform, load_tag_reader(), _read_stdin
    )


# --- The options ---------------------------------------------------------------------


class _HelpFormatter(
    help_formatter.ReqAwareDefaultsFormatter, argparse.RawDescriptionHelpFormatter
):
    """Every real default shown, the epilog's breaks kept.

    The two bases override different methods, so they compose. A default of None is no
    value a person could type, so it is not shown: each such option's help says instead
    what leaving it out means.
    """

    def _get_help_string(self, action: argparse.Action) -> str | None:
        """*action*'s help, with its default appended unless that default is None."""
        if action.default is None:
            return action.help
        return super()._get_help_string(action)


_EPILOG = f"""\
Prerequisites:
  macOS, with Music.app already running: it is asked whether it is running and is
  never launched by this tool (if Music quits mid-run, the next call relaunches
  it). The terminal that runs this needs the automation permission to
  control Music (System Settings > Privacy & Security > Automation); the first
  run asks for it. Album tags are asked for only when mutagen, in the project's
  refresh_tags extra, is installed.

Modes, exactly one:
  --whole-library refreshes every file track, {refresh_core.BATCH_TRACKS} tracks a call.
  Otherwise the MP3s that --track, --album and --tracks-from name, which combine,
  are looked up per album folder and refreshed by id. A list file is UTF-8, one
  absolute MP3 path per line, each line ended by a linefeed: a last line with no
  linefeed is reported and not read. See the companion doc.

  --missing-list FILE writes the MP3s an explicit run found not in Music to FILE,
  in the same list format, replaced whole; refused inside a git working tree, since
  it lists library paths. Nothing is ever added to Music.app.

Exit codes:
  0    everything asked for was refreshed, or reported not in Music
  1    a call failed, a track was stale, the run stopped at a timeout, a named
       input could not be used, or the missing list could not be written
  2    could not start: not macOS, Music.app not running or the probe unanswered,
       bad options, nothing to refresh, an unreadable list file, or a missing list
       inside a git working tree or a folder that does not exist
  130  interrupted (Ctrl-C); the report covers the calls that finished"""


class _GivenOnce(argparse.Action):
    """Store an option's value, refusing a second use of the option as a usage error.

    argparse's plain ``store`` keeps the last value given, so a repeated
    ``--tracks-from`` would drop every list but the last one without a word.
    """

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        """Set the value, or exit 2 through *parser* when it was already set."""
        if getattr(namespace, self.dest) is not None:
            parser.error(f"{option_string} is given once: one list a run")
        setattr(namespace, self.dest, values)


def build_parser() -> argparse.ArgumentParser:
    """The CLI: every argument a named option, every real default shown."""
    parser = argparse.ArgumentParser(
        description="Make Music.app reread the tags of MP3s: the whole library, or the "
        "files named.",
        formatter_class=_HelpFormatter,
        epilog=_EPILOG,
    )
    parser.add_argument(
        "--whole-library",
        action="store_true",
        # None, not False, so the help shows no default: no one types False, and the
        # help says what giving the switch does. Every reader tests it for truth.
        default=None,
        help="Refresh every file track Music.app holds, in batches. Refused with any "
        "other source.",
    )
    parser.add_argument(
        "--track",
        action="append",
        type=Path,
        metavar="MP3",
        help="One MP3 to refresh; repeatable.",
    )
    parser.add_argument(
        "--album",
        action="append",
        type=Path,
        metavar="FOLDER",
        help="Every MP3 under this folder, hidden folders skipped; repeatable.",
    )
    parser.add_argument(
        "--tracks-from",
        action=_GivenOnce,
        metavar="FILE",
        help=f"A list file of MP3 paths; {STDIN_LIST} reads standard input. Given "
        "once.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Do everything but refresh: count the batches, or look up and match the "
        "named files.",
    )
    parser.add_argument(
        "--missing-list",
        type=Path,
        metavar="FILE",
        help="Explicit mode: write the MP3s not in Music to FILE, one path a line. "
        "Left out, no file is written.",
    )
    return parser


def refuse_bad_modes(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Exit 2 through *parser* unless exactly one mode was chosen."""
    explicit = [flag for attr, flag in _SOURCES if getattr(args, attr) is not None]
    if args.whole_library and explicit:
        parser.error(f"--whole-library cannot be combined with {', '.join(explicit)}")
    if not args.whole_library and not explicit:
        parser.error(
            "choose a mode: --whole-library, or at least one of --track, --album, --tracks-from"
        )


def refuse_bad_missing_list(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    """Exit 2 through *parser* when ``--missing-list`` cannot be written, before any work.

    Only explicit mode finds files not in Music, and a list of library paths must never
    land inside a repository (`report_file.refusal`).
    """
    if args.missing_list is None:
        return
    if args.whole_library:
        parser.error(
            "--missing-list lists explicit mode's files: not with --whole-library"
        )
    reason = report_file.refusal(args.missing_list)
    if reason is not None:
        parser.error(f"--missing-list: {reason}")


# --- Output --------------------------------------------------------------------------


def _notice(text: str) -> None:
    """One line of progress, a refusal or a skipped input, on stderr."""
    stdio_utf8.print_escaped(refresh_report.shown(text), sys.stderr)


def _problem_line(problem: refresh_core.Problem) -> str:
    """One skipped input, by its source and, for a list, its line number."""
    where = (
        problem.source
        if problem.line is None
        else f"--tracks-from {problem.source}, line {problem.line}"
    )
    if problem.subject:
        return f"{where}: {problem.subject}: {problem.reason}"
    return f"{where}: {problem.reason}"


def _counted(problems: Sequence[refresh_core.Problem]) -> int:
    """How many problems make a run exit 1: all but a folder reached twice (a link)."""
    return sum(1 for p in problems if p.reason != refresh_core.REASON_ALREADY_WALKED)


# --- The run -------------------------------------------------------------------------


class _CannotStart(Exception):
    """A run that cannot start: its one-line reason, printed before exiting 2."""


def _list_sources(
    args: argparse.Namespace, wiring: Wiring
) -> list[refresh_core.ListSource]:
    """The ``--tracks-from`` list's bytes, read now; an unreadable file cannot start."""
    if args.tracks_from is None:
        return []
    if args.tracks_from == STDIN_LIST:
        return [refresh_core.ListSource(STDIN_LIST, wiring.read_stdin())]
    try:
        data = Path(args.tracks_from).read_bytes()
    except OSError as error:
        raise _CannotStart(
            f"cannot read the list file {args.tracks_from}: {error.strerror or error}"
        ) from None
    return [refresh_core.ListSource(args.tracks_from, data)]


def _collect(args: argparse.Namespace, wiring: Wiring) -> refresh_core.Collected:
    """The named MP3s, each skipped input reported; none at all cannot start."""
    collected = refresh_core.collect_mp3s(
        tracks=args.track or (),
        albums=args.album or (),
        lists=_list_sources(args, wiring),
        stat=wiring.stat,
    )
    for problem in collected.problems:
        _notice(_problem_line(problem))
    if not collected.mp3s:
        raise _CannotStart(
            "nothing to refresh: no MP3 was collected from the sources named"
        )
    return collected


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


def _seams(wiring: Wiring) -> refresh_run.Seams:
    """The run's seams from the wiring, with progress on stderr."""
    return refresh_run.Seams(wiring.run, wiring.stat, _notice)


def _whole_library(args: argparse.Namespace, wiring: Wiring) -> int:
    """Refresh the whole library, print its report; return its exit code."""
    _require_music(wiring)
    dry_run = bool(args.dry_run)
    run = refresh_run.refresh_library(_seams(wiring), dry_run=dry_run)
    print(refresh_report.format_library(run, dry_run=dry_run), end="")
    return refresh_report.library_exit_code(run)


def _missing_list_bytes(run: refresh_run.AlbumsRun) -> bytes:
    """The list file of every MP3 *run* found not in Music, in report order.

    Each path is written as the file system's own bytes, linefeed ended. A path
    holding a linefeed cannot be written in the list format, so it is reported instead.
    """
    lines: list[bytes] = []
    for mp3 in (mp3 for album in run.albums for mp3 in album.not_in_music):
        raw = os.fsencode(mp3.path)
        if b"\n" in raw:
            _notice(
                f"--missing-list: {mp3.path}: holds a linefeed, so it is not written"
            )
            continue
        lines.append(raw + b"\n")
    return b"".join(lines)


def _write_missing_list(target: Path, run: refresh_run.AlbumsRun, code: int) -> int:
    """Write the missing list to *target*; return *code*, raised to 1 when it failed.

    The target is asked again whether it may be written, at the moment of writing:
    the answer given at start may no longer hold (a repository made around its
    folder mid-run, say). A refusal then is reported as a failed write.
    """
    failed = code if code != refresh_report.EXIT_OK else refresh_report.EXIT_PARTIAL
    reason = report_file.refusal(target)
    if reason is not None:
        _notice(f"--missing-list: {reason}")
        return failed
    try:
        report_file.write_atomically(target, _missing_list_bytes(run))
    except OSError as error:
        _notice(
            f"--missing-list: cannot write the missing list {target}: {error.strerror or error}"
        )
        return failed
    return code


def _explicit(args: argparse.Namespace, wiring: Wiring) -> int:
    """Refresh the named MP3s by album folder, print the report; return its exit code."""
    collected = _collect(args, wiring)
    _require_music(wiring)
    groups = refresh_core.group_albums(collected.mp3s, tag_reader=wiring.tag_reader)
    dry_run = bool(args.dry_run)
    run = refresh_run.refresh_albums(groups, _seams(wiring), dry_run=dry_run)
    hint = NO_MUTAGEN_HINT if wiring.tag_reader is None else None
    print(refresh_report.format_albums(run, dry_run=dry_run, hint=hint), end="")
    code = refresh_report.albums_exit_code(run, problems=_counted(collected.problems))
    if args.missing_list is None:
        return code
    return _write_missing_list(args.missing_list, run, code)


def main(argv: Sequence[str] | None = None, *, wiring: Wiring | None = None) -> int:
    """Parse the options and run the chosen mode; return the exit code.

    *wiring* is the real one unless a test passes its own.
    """
    stdio_utf8.force_utf8_streams(sys.stdout, sys.stderr)
    parser = build_parser()
    args = parser.parse_args(argv)
    refuse_bad_modes(parser, args)
    refuse_bad_missing_list(parser, args)
    wiring = wiring or real_wiring()
    # Before any file is read or any call made: there is no Music.app to ask elsewhere.
    if wiring.platform != _DARWIN:
        _notice(
            f"{parser.prog}: needs macOS, where Music.app runs; this is {wiring.platform}"
        )
        return refresh_report.EXIT_USAGE
    try:
        return (_whole_library if args.whole_library else _explicit)(args, wiring)
    except _CannotStart as refusal:
        _notice(f"{parser.prog}: {refusal}")
        return refresh_report.EXIT_USAGE
    # Ctrl-C anywhere in a run is caught by the run, which reports what finished. Only
    # one before it (collecting, reading a list, the probe, reading album tags) ends
    # here, before the run's first call, so there is nothing to report.
    except KeyboardInterrupt:
        _notice(f"{parser.prog}: interrupted before any refresh")
        return refresh_report.EXIT_INTERRUPTED


if __name__ == "__main__":  # pragma: no cover - the CLI entry point; main() is tested
    sys.exit(main())
