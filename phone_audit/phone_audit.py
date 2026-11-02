"""phone_audit: find the iPhone's synced tracks that have no file on the phone. Read-only.

The entry point of the tool folder, and the only module here that writes output: the
report goes to stdout (or to ``--report``), progress and every refusal to stderr.
Importing it puts the folder's private modules, under ``src/``, on ``sys.path``, then
tag_refresh's ``src/``, whose report-file helper this tool shares,
then the shared libraries, each at one fixed place directly under the project root. The HTML page frame, ``html_page``, is one of those shared
libraries, and owns the escape every line this tool prints is shown through.

`main` finds ``afcclient`` on PATH, checks its version against the one this tool was
proven on (a mismatch only warns), copies the phone's music database twice and
compares the copies (`phone_db`), lists the ``Fnn`` sync folders (`phone_listing`),
compares the rows with the files (`phone_compare`) and prints the report
(`phone_report`; the HTML page, which goes to ``--report`` only, is `phone_html`'s).
It reads the phone over USB through afcclient alone, never Music.app, and every
afcclient call goes through `afc_calls`, whose allowlist holds reads only. The real
runner, the PATH lookup and the clock are bound by `real_wiring`; a test passes its
own `Wiring` instead.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: The private modules' folder, beside this file.
SRC_DIR = Path(__file__).resolve().parent / "src"
#: tag_refresh's private modules, whose report-file helper this tool shares: the
#: sibling tool folder's ``src/``, one fixed place under the project root.
SHARED_DIR = Path(__file__).resolve().parents[1] / "tag_refresh" / "src"
sys.path[:0] = [str(SRC_DIR), str(SHARED_DIR)]
# The shared libraries, each at one fixed place: directly under the project root, which
# is this file's grandparent. Deliberately not a search up the ancestors: that would
# also put any same-named folder above the checkout on sys.path, and whatever it holds
# would be imported in place of the real module. See stdio_utf8/stdio_utf8.md, "How this
# project's tools import it".
sys.path += [
    str(Path(__file__).resolve().parents[1] / name)
    for name in ("stdio_utf8", "help_formatter", "bounded_run", "html_page")
]

import afc_calls  # noqa: E402 - import follows the sys.path bootstrap above
import help_formatter  # noqa: E402 - import follows the sys.path bootstrap above
import html_page  # noqa: E402 - import follows the sys.path bootstrap above
import phone_compare  # noqa: E402 - import follows the sys.path bootstrap above
import phone_db  # noqa: E402 - import follows the sys.path bootstrap above
import phone_html  # noqa: E402 - import follows the sys.path bootstrap above
import phone_listing  # noqa: E402 - import follows the sys.path bootstrap above
import phone_report  # noqa: E402 - import follows the sys.path bootstrap above
import report_file  # noqa: E402 - import follows the sys.path bootstrap above
import stdio_utf8  # noqa: E402 - import follows the sys.path bootstrap above

#: The three report formats. HTML goes to a file only (``--report``), and no format is
#: ever inferred from the report's name.
FORMAT_TEXT, FORMAT_JSON, FORMAT_HTML = "text", "json", "html"
#: The refusal of ``--format html`` with no ``--report``.
HTML_NEEDS_REPORT = "--format html needs --report: the page is written to a file only"
#: The binary this tool runs, looked up on PATH.
AFCCLIENT = "afcclient"
#: The folder holding the phone's ``Fnn`` sync folders, relative to the AFC root (the
#: device's ``/var/mobile/Media``), as every afcclient path is.
MUSIC_FOLDER = "/iTunes_Control/Music"
#: What every could-not-reach line ends with.
_CONNECT = "connect the iPhone by USB, unlock it, and run this again"


# --- Wiring --------------------------------------------------------------------------


def local_now() -> datetime:
    """Now, in this Mac's local time zone: when the HTML page says the phone was read."""
    return datetime.now().astimezone()


@dataclass(frozen=True)
class Wiring:
    """What a run reaches outside the process through: the runner, PATH, the clock."""

    run: afc_calls.Runner
    which: Callable[[str], str | None]
    clock: Callable[[], datetime] = local_now


def real_wiring() -> Wiring:
    """The real seams: `bounded_run`, ``shutil.which`` and the local clock."""
    return Wiring(afc_calls.real_run, shutil.which, local_now)


# --- The options ---------------------------------------------------------------------


class _HelpFormatter(
    help_formatter.ReqAwareDefaultsFormatter, argparse.RawDescriptionHelpFormatter
):
    """Every real default shown, the epilog's breaks kept.

    A default of None is no value a person could type, so it is not shown: each such
    option's help says instead what leaving it out means.
    """

    def _get_help_string(self, action: argparse.Action) -> str | None:
        """*action*'s help, with its default appended unless that default is None."""
        if action.default is None:
            return action.help
        return super()._get_help_string(action)


_EPILOG = f"""\
Prerequisites:
  Homebrew's libimobiledevice installed (brew install libimobiledevice), which
  provides afcclient; this tool was proven on macOS, against afcclient
  {afc_calls.PROVEN_VERSION}, and another version only warns. The iPhone connected by
  USB, trusted by this Mac (the pairing a Finder sync already uses), and unlocked.
  Music.app is not used. Close Music on the phone, so its database holds still while
  it is copied.

Formats:
  text (the default) and json print to stdout or --report; html writes one
  self-contained page of tables, so --format html needs --report. The format is
  never inferred from the report's name: --report phone.html alone writes text.

What it compares:
  every row of the phone's music database whose base location is a sync folder
  (F00, F01, ...) against the files those folders hold, by folder and file name. A
  row with no file, or whose file's size differs from the database's, is a finding;
  a file with no row is listed only. It never writes to the phone: afcclient is only
  ever asked to list or copy from it. See the companion doc.

Exit codes:
  0    nothing found
  1    findings
  2    could not run: afcclient not on PATH, the phone not connected, unlocked or
       trusted, or unplugged mid-run, a call timed out, a local file (the private
       temporary folder or a copy) that could not be used, a phone with no music
       database, a database that changed while it was copied, failed its integrity
       check or lacks the expected tables, a listing failed, bad options (--format
       html without --report among them), a --report inside a git working tree or
       in a folder that does not exist, or the report could not be written
  130  interrupted (Ctrl-C): before the report, nothing is printed or written and
       the copies are removed; while it is delivered, a --report file is left as it
       was and printed text may stop part way"""


def _udid(text: str) -> str:
    """A ``--udid`` value: refused when empty, as afcclient refuses it."""
    if not text:
        raise argparse.ArgumentTypeError("must not be empty")
    return text


def build_parser() -> argparse.ArgumentParser:
    """The CLI: every argument a named option, every real default shown."""
    parser = argparse.ArgumentParser(
        description="Find the iPhone's synced tracks that have no file on the phone, "
        "or a file of the wrong size. Read-only.",
        formatter_class=_HelpFormatter,
        epilog=_EPILOG,
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
        "--udid",
        type=_udid,
        metavar="UDID",
        help="The phone to read, when more than one is connected. Left out, afcclient "
        "reads the only one.",
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


class _CannotRun(Exception):
    """A run that cannot start or cannot get what it compares: its one-line reason."""


def _find_afcclient(wiring: Wiring) -> str:
    """The path of afcclient found on PATH; the run cannot go on without it."""
    found = wiring.which(AFCCLIENT)
    if found is None:
        raise _CannotRun(
            f"{AFCCLIENT} is not on PATH: install it with `brew install libimobiledevice`"
        )
    return found


def _check_version(afc: afc_calls.Afc) -> None:
    """Warn, and go on, when afcclient is not the version this tool was proven on."""
    version = afc.version()
    if version == afc_calls.PROVEN_VERSION:
        return
    shown = "an unreadable version" if version is None else f"version {version}"
    _notice(
        f"warning: {AFCCLIENT} reports {shown}; this tool was proven against"
        f" {AFCCLIENT} {afc_calls.PROVEN_VERSION}, so its output may differ"
    )


@dataclass(frozen=True)
class _Files:
    """The files the sync folders hold, and what else their listings held."""

    files: tuple[phone_compare.PhoneFile, ...]
    unparsed: int
    other_entries: int


def _list(afc: afc_calls.Afc, path: str) -> phone_listing.Listing:
    """*path*'s listing; its unparsed lines are said on stderr."""
    listing = phone_listing.parse_listing(afc.list_dir(path))
    if listing.unparsed:
        _notice(f"{len(listing.unparsed)} listing line(s) unparsed in {path}")
    return listing


def _list_files(afc: afc_calls.Afc) -> _Files:
    """Every file in every ``Fnn`` folder of the music folder."""
    _notice(f"listing {MUSIC_FOLDER}")
    music = _list(afc, MUSIC_FOLDER)
    folders = sorted(
        e.name
        for e in music.entries
        if e.kind == phone_listing.DIR_KIND and phone_db.SYNC_FOLDER.fullmatch(e.name)
    )
    files: list[phone_compare.PhoneFile] = []
    unparsed, other = len(music.unparsed), 0
    for number, folder in enumerate(folders, start=1):
        _notice(f"listing {folder} ({number} of {len(folders)})")
        listing = _list(afc, f"{MUSIC_FOLDER}/{folder}")
        unparsed += len(listing.unparsed)
        for entry in listing.entries:
            if entry.kind != phone_listing.FILE_KIND:
                other += 1
                continue
            files.append(phone_compare.PhoneFile(folder, entry.name, entry.size))
    return _Files(tuple(files), unparsed, other)


def _audit(args: argparse.Namespace, wiring: Wiring) -> phone_report.Audit:
    """Read the phone and compare; return what was found."""
    afc = afc_calls.Afc(_find_afcclient(wiring), args.udid, wiring.run)
    _check_version(afc)
    try:
        rows = phone_db.load_rows(afc.copy_file, progress=_notice)
        listed = _list_files(afc)
    except afc_calls.Unreachable as error:
        raise _CannotRun(
            f"cannot reach the iPhone ({error.reason}); {_CONNECT}"
        ) from None
    except afc_calls.CommandFailed as error:
        raise _CannotRun(f"a read of the iPhone failed: {error.reason}") from None
    except phone_db.DatabaseRefused as error:
        raise _CannotRun(str(error)) from None
    # A local failure: the private temporary folder, a copy read for its hash, or the
    # copy opened. Each seam's own OSError is turned into its own error first.
    except OSError as error:
        raise _CannotRun(
            f"a local file could not be used: {error.strerror or error}"
        ) from None
    return phone_report.Audit(
        phone_compare.compare(rows.rows, listed.files),
        rows_in_sync=len(rows.rows),
        files=len(listed.files),
        outside_sync=rows.outside_sync,
        unparsed_lines=listed.unparsed,
        other_entries=listed.other_entries,
    )


def _render(
    args: argparse.Namespace, audit: phone_report.Audit, read_at: datetime
) -> str:
    """The report in its format; the HTML page says the phone was read at *read_at*."""
    if args.format == FORMAT_JSON:
        return phone_report.format_json(audit)
    if args.format == FORMAT_HTML:
        return phone_html.format_html(phone_report.report_dict(audit), read_at=read_at)
    return phone_report.format_text(audit)


def _deliver(
    args: argparse.Namespace, audit: phone_report.Audit, read_at: datetime, prog: str
) -> int:
    """Print or write the report in its format; return the run's exit code."""
    text = _render(args, audit, read_at)
    if args.report is None:
        print(text, end="")
        return phone_report.exit_code(audit)
    # Asked again at the moment of writing: the answer given at start may no longer
    # hold (a repository made around the folder while the run went on, say).
    reason = report_file.refusal(args.report)
    if reason is not None:
        _notice(f"{prog}: --report: {reason}")
        return phone_report.EXIT_USAGE
    try:
        report_file.write_atomically(args.report, text.encode("utf-8"))
    except OSError as error:
        _notice(
            f"{prog}: cannot write the report {args.report}: {error.strerror or error}"
        )
        return phone_report.EXIT_USAGE
    return phone_report.exit_code(audit)


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
        return phone_report.EXIT_USAGE
    wiring = wiring or real_wiring()
    try:
        audit = _audit(args, wiring)
    except _CannotRun as cannot:
        _notice(f"{parser.prog}: {cannot}")
        return phone_report.EXIT_USAGE
    # Nothing is printed until everything is read: Ctrl-C before the report leaves
    # nothing half-written, and the database copies are removed on the way out.
    except KeyboardInterrupt:
        _notice(f"{parser.prog}: interrupted; no report")
        return phone_report.EXIT_INTERRUPTED
    try:
        # The phone was read when the audit returned: the page's "when".
        return _deliver(args, audit, wiring.clock(), parser.prog)
    # A --report file is left as it was (the write is atomic); printed text may stop
    # part way, which the notice says.
    except KeyboardInterrupt:
        _notice(f"{parser.prog}: interrupted; the report is incomplete or not written")
        return phone_report.EXIT_INTERRUPTED


if __name__ == "__main__":  # pragma: no cover - the CLI entry point; main() is tested
    sys.exit(main())
