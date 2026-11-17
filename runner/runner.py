"""runner: build, install and inspect Apple Music Toolbox Runner, the Python half.

A scheduled Python job that reads Music.app is charged, by macOS, to whatever program
launchd started. Started directly, that is the Python interpreter, an identity that
changes with every upgrade and that any script shares. Apple Music Toolbox Runner is a
small signed app launchd starts instead: it starts the job's interpreter and script as
its child, so macOS charges the job's Apple events to the app, under one stable name.

The Swift package under ``app/`` is the app; this file is the command line that manages
it. The commands are ``build``, ``install``, ``uninstall``, ``status`` and ``locate``,
and each is held by a module under ``src/``: `run_install` (build, install and
uninstall), `run_grant` (install's check that macOS lets the app control Music),
`run_status` (status and locate), `run_signer` (the signer install records and status
and locate demand), `run_allowlist` (the scripts the app may start) and `run_layout`
(the names and paths). The generic build, sign and install steps they call
are signed_app's, beside this tool's folder. A refusal starts with ``ERROR:`` and exits
2; a build, sign or launchd step that fails, or any other ``OSError``, starts with
``ERROR:`` and exits 1, never a traceback. Each is one line, with one exception: a
codesign step that fails prints ``ERROR: codesign sign failed (exit N):`` (or ``codesign
verify``) and then what codesign wrote, on as many lines as it took, with the signing
identity redacted.

Importing this module puts the private modules, under ``src/``, on ``sys.path``, then
the shared libraries, each at one fixed place directly under the project root, beside
this tool's folder. signed_app, this project's own library of the generic build, sign
and install steps, is one of them.

Entry point assumptions: run as a script, or imported for `main`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final, TypeAlias

#: The private modules' folder, beside this file.
SRC_DIR: Final = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC_DIR))
# The grant probe's folder, beside src/: run_grant imports the probe by name, for the
# outcome names its result file holds.
sys.path.append(str(SRC_DIR.parent / "grant_probe"))
# The shared libraries, each at one fixed place: directly under the project root, which
# is this file's grandparent. Deliberately not a search up the ancestors: that would
# also put any same-named folder above the checkout on sys.path, and whatever it holds
# would be imported in place of the real module. See stdio_utf8/stdio_utf8.md, "How this
# project's tools import it". swift_gate's signing reader lives in that tool's private
# src/; signed_app's front module, which puts its own src/ on sys.path, and the rest
# at the top of their own folders.
sys.path += [
    str(Path(__file__).resolve().parents[1] / folder)
    for folder in (
        "stdio_utf8",
        "help_formatter",
        "bounded_run",
        "launchd_agent",
        "atomic_write",
        "swift_gate/src",
        "signed_app",
    )
]

import help_formatter  # noqa: E402 - import follows the sys.path bootstrap above
import launchd_agent  # noqa: E402 - import follows the sys.path bootstrap above

# Ahead of the run_ modules, which import the steps it puts on sys.path.
import signed_app  # noqa: E402, F401 - puts signed_app's src/ on sys.path
import app_bundle  # noqa: E402 - on sys.path once signed_app is imported
import app_host  # noqa: E402 - on sys.path once signed_app is imported
import run_install  # noqa: E402 - import follows the sys.path bootstrap above
import run_layout  # noqa: E402 - import follows the sys.path bootstrap above
import run_status  # noqa: E402 - import follows the sys.path bootstrap above
import stdio_utf8  # noqa: E402 - import follows the sys.path bootstrap above

#: The layout file every command reads; a test points it elsewhere.
LAYOUT_FILE: Path = run_layout.LAYOUT_FILE
#: A step that failed: a build, a signature, launchd, or the grant check.
EXIT_FAILED: Final = 1
#: A command that could not run, as argparse's usage errors also exit.
EXIT_CANNOT: Final = 2
#: Every parser's epilog: what the tool needs.
_EPILOG: Final = (
    "Prerequisites: the Python release requires-python names in the project's "
    "pyproject.toml, macOS 14 or later, and a git checkout holding this tool. build "
    "and install need the Swift toolchain and codesign; build --sign and install need "
    "a signing identity in the signing setting file layout.json names, outside every "
    "checkout. Run install from the repository's main checkout, never a linked "
    "worktree, with the interpreter the scheduled jobs use, with Music open, and stay "
    "to answer the permission prompt macOS shows. Run install before installing a job "
    "that starts through the runner."
)
#: The failures that end a command with exit 1, and the refusals that end it with 2.
#: OSError is a failure too: any the commands do not turn into one of their own (a
#: bundle that cannot be removed, say) is still an ERROR report, not a traceback. Every
#: report is one line but a failed codesign step's, whose message carries codesign's own
#: redacted output on the lines after the first.
_FAILURES: Final = (app_bundle.BuildFailed, launchd_agent.LaunchdError, OSError)
_REFUSALS: Final = (app_bundle.Refused, run_layout.LayoutError)
#: How a command gets its host: built only when the command needs one.
HostSource = Callable[[], app_host.Host]
#: A command's handler: the parsed arguments and the host source in, the exit code out.
Handler = Callable[[argparse.Namespace, HostSource], int]


def real_host() -> app_host.Host:  # pragma: no cover - the real host seam
    """This process's host, with this file as the entry script."""
    return app_host.real_host(Path(__file__).resolve())


def run_build(args: argparse.Namespace, host: HostSource) -> int:
    """Build the bundle into --out, signed and verified with --sign."""
    layout = run_layout.load_layout(LAYOUT_FILE)
    return run_install.run_build(host(), layout, args.out, sign=args.sign)


def run_install_command(_args: argparse.Namespace, host: HostSource) -> int:
    """Build, sign and install the app, then check that it may control Music."""
    layout = run_layout.load_layout(LAYOUT_FILE)
    return run_install.install(host(), layout)


def run_uninstall(_args: argparse.Namespace, host: HostSource) -> int:
    """Remove the app, and a grant agent a stopped install left."""
    layout = run_layout.load_layout(LAYOUT_FILE)
    return run_install.uninstall(host(), layout)


def run_status_command(_args: argparse.Namespace, host: HostSource) -> int:
    """Print whether the app is installed and intact, and what it may start."""
    layout = run_layout.load_layout(LAYOUT_FILE)
    return run_status.status(host(), layout)


def run_locate(args: argparse.Namespace, host: HostSource) -> int:
    """Print the installed executable's path for one interpreter and script."""
    layout = run_layout.load_layout(LAYOUT_FILE)
    return run_status.locate(host(), layout, python=args.python, script=args.script)


#: The subcommand table the helper below adds to.
_Commands: TypeAlias = "argparse._SubParsersAction[stdio_utf8.EscapingArgumentParser]"


def _subparser(
    commands: _Commands,
    name: str,
    summary: str,
    handler: Handler,
) -> argparse.ArgumentParser:
    """One subcommand and its handler."""
    parser: argparse.ArgumentParser = commands.add_parser(
        name,
        help=summary,
        description=summary,
        epilog=_EPILOG,
        formatter_class=help_formatter.UnsetHidingFormatter,
    )
    parser.set_defaults(handler=handler)
    return parser


def _add_build(commands: _Commands) -> None:
    """`build` and its options."""
    build = _subparser(
        commands, "build", "build the app bundle, and with --sign sign it", run_build
    )
    build.add_argument(
        "--out",
        type=Path,
        required=True,
        metavar="DIR",
        help="folder to assemble the bundle in; it must not already hold one",
    )
    build.add_argument(
        "--sign",
        action="store_true",
        help="sign the bundle with the configured identity, then verify it",
    )


def _add_locate(commands: _Commands) -> None:
    """`locate` and its options."""
    locate = _subparser(
        commands,
        "locate",
        "print the installed app's executable, for a job its allowlist holds",
        run_locate,
    )
    locate.add_argument(
        "--python",
        required=True,
        metavar="PATH",
        help="the interpreter the job runs under, exactly as the job will pass it",
    )
    locate.add_argument(
        "--script",
        required=True,
        metavar="PATH",
        help="the script the job runs, exactly as the job will pass it",
    )


def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    """The command line, named `prog` (argv[0]'s file name when None)."""
    parser = stdio_utf8.EscapingArgumentParser(
        prog=prog,
        description=(
            "Manage Apple Music Toolbox Runner, the signed app scheduled Apple Music "
            "tools start through."
        ),
        epilog=_EPILOG,
        formatter_class=help_formatter.UnsetHidingFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    _add_build(commands)
    _subparser(
        commands,
        "install",
        "build, sign and install the app, then check it may control Music",
        run_install_command,
    )
    _subparser(
        commands,
        "uninstall",
        "remove the app; jobs that start through it then fail",
        run_uninstall,
    )
    _subparser(
        commands,
        "status",
        "report whether the app is installed and its signature verifies",
        run_status_command,
    )
    _add_locate(commands)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    prog: str | None = None,
    host: app_host.Host | None = None,
) -> int:
    """Run one command and return its exit code; `host` replaces this process's."""
    stdio_utf8.force_utf8_streams(sys.stdout, sys.stderr)
    args = build_parser(prog).parse_args(argv)
    built: list[app_host.Host] = []

    def source() -> app_host.Host:
        # Each command asks once; the host is kept so a failure prints on its stream.
        built.append(host if host is not None else real_host())
        return built[-1]

    try:
        code: int = args.handler(args, source)
    except _REFUSALS as error:
        return _report(error, host, built, EXIT_CANNOT)
    except _FAILURES as error:
        return _report(error, host, built, EXIT_FAILED)
    return code


def _report(
    error: Exception,
    given: app_host.Host | None,
    built: list[app_host.Host],
    code: int,
) -> int:
    """Print `error` after ``ERROR:`` on the host's stderr, and return `code`.

    The message is printed whole: one line for every error but a failed codesign step,
    whose message holds codesign's redacted output on further lines.

    A host given to `main`, or one already built, owns the stream; a command that failed
    before building the real host writes to this process's stderr, as that host would.
    """
    hosts = [*built, *([given] if given is not None else [])]
    print(f"ERROR: {error}", file=hosts[0].err if hosts else sys.stderr)
    return code


if __name__ == "__main__":  # pragma: no cover - the CLI entry point; main() is tested
    sys.exit(main())
