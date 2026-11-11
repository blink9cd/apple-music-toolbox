"""scrobbler: listensmith's Music.app adapter, the Python half of its command line.

The adapter has two halves. The Swift package under ``app/`` is the app that watches
Music.app and submits each listen to the store; this file is the command line that
manages it. Both read one layout file, ``layout.json`` beside this file, through
`scrob_layout` here and through constants a Swift test holds equal to it there.

The commands are ``version``, ``build``, ``install``, ``uninstall`` and ``status``; what
each does is in ``scrobbler.md`` and in the modules under ``src/`` that hold it:
`scrob_bundle` (build and sign), `scrob_agent` (install and uninstall), `scrob_status`
(status and the session check), `scrob_host` (the process facts every command reads)
and `scrob_layout` (the names and paths). A refusal is one ``ERROR:`` line and exit 2; a
build, sign or launchd step that fails is one ``ERROR:`` line and exit 1.

Importing this module puts the private modules, under ``src/``, on ``sys.path``, then
the shared libraries, each at one fixed place directly under the project root, beside
this tool's folder.

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
# The shared libraries, each at one fixed place: directly under the project root, which
# is this file's grandparent. Deliberately not a search up the ancestors: that would
# also put any same-named folder above the checkout on sys.path, and whatever it holds
# would be imported in place of the real module. See stdio_utf8/stdio_utf8.md, "How this
# project's tools import it". swift_gate's signing reader lives in that tool's private
# src/, the rest at the top of their own folders.
sys.path += [
    str(Path(__file__).resolve().parents[1] / folder)
    for folder in (
        "stdio_utf8",
        "help_formatter",
        "bounded_run",
        "launchd_agent",
        "swift_gate/src",
    )
]

import help_formatter  # noqa: E402 - import follows the sys.path bootstrap above
import launchd_agent  # noqa: E402 - import follows the sys.path bootstrap above
import scrob_agent  # noqa: E402 - import follows the sys.path bootstrap above
import scrob_bundle  # noqa: E402 - import follows the sys.path bootstrap above
import scrob_host  # noqa: E402 - import follows the sys.path bootstrap above
import scrob_layout  # noqa: E402 - import follows the sys.path bootstrap above
import scrob_status  # noqa: E402 - import follows the sys.path bootstrap above
import stdio_utf8  # noqa: E402 - import follows the sys.path bootstrap above

#: The layout file every command reads; a test points it elsewhere.
LAYOUT_FILE: Path = scrob_layout.LAYOUT_FILE
#: A step that failed: a build, a signature, or launchd.
EXIT_FAILED: Final = 1
#: A command that could not run, as argparse's usage errors also exit.
EXIT_CANNOT: Final = 2
#: Every parser's epilog: what the tool needs.
_EPILOG: Final = (
    "Prerequisites: the Python release requires-python names in the project's "
    "pyproject.toml, and macOS 14 or later. build and install need the Swift toolchain "
    "and codesign; build --sign and install need a signing identity in the signing "
    "setting file layout.json names, outside every checkout. Run install from the "
    "repository's main checkout, never a linked worktree; see scrobbler.md."
)
#: The failures that end a command with exit 1, and the refusals that end it with 2.
_FAILURES: Final = (scrob_bundle.BuildFailed, launchd_agent.LaunchdError)
_REFUSALS: Final = (scrob_bundle.Refused, scrob_layout.LayoutError)
#: How a command gets its host: built only when the command needs one.
HostSource = Callable[[], scrob_host.Host]
#: A command's handler: the parsed arguments and the host source in, the exit code out.
Handler = Callable[[argparse.Namespace, HostSource], int]


def real_host() -> scrob_host.Host:  # pragma: no cover - the real host seam
    """This process's host, with this file as the entry script."""
    return scrob_host.real_host(Path(__file__).resolve())


def run_version(_args: argparse.Namespace, _host: HostSource) -> int:
    """Print the layout's version."""
    print(scrob_layout.load_layout(LAYOUT_FILE).version)
    return 0


def run_build(args: argparse.Namespace, host: HostSource) -> int:
    """Build the bundle into --out, signed and verified with --sign."""
    layout = scrob_layout.load_layout(LAYOUT_FILE)
    return scrob_bundle.run_build(host(), layout, args.out, sign=args.sign)


def run_install(_args: argparse.Namespace, host: HostSource) -> int:
    """Build, sign and install the app and its agent, confirmed started."""
    return scrob_agent.install(host(), scrob_layout.load_layout(LAYOUT_FILE))


def run_uninstall(_args: argparse.Namespace, host: HostSource) -> int:
    """Unload the agent; keep the app and its data."""
    scrob_agent.uninstall(host(), scrob_layout.load_layout(LAYOUT_FILE))
    return 0


def run_status(args: argparse.Namespace, host: HostSource) -> int:
    """Print the health report, or with --session-check the session lines, exit 0."""
    built = host()
    if args.session_check:
        for line in _session_lines(built):
            print(line, file=built.out)
        return 0
    layout = scrob_layout.load_layout(LAYOUT_FILE)
    report = scrob_status.gather_status(built, layout)
    for line in scrob_status.format_lines(report):
        print(line, file=built.out)
    return report.exit_code


def _session_lines(host: scrob_host.Host) -> list[str]:
    """The session lines; a layout the tool cannot trust is one line, never an exit 2.

    The line names no path, since the layout error's text may hold one under the home.
    """
    try:
        layout = scrob_layout.load_layout(LAYOUT_FILE)
    except scrob_layout.LayoutError:
        return [
            f"{scrob_status.STEM}: session check failed -- the layout file cannot be "
            f"trusted; details: {scrob_status.DETAILS}"
        ]
    return scrob_status.session_lines(host, layout)


#: The subcommand table the helpers below add to.
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


def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    """The command line, named `prog` (argv[0]'s file name when None)."""
    parser = stdio_utf8.EscapingArgumentParser(
        prog=prog,
        description="listensmith's Music.app adapter: manage the scrobbler app.",
        epilog=_EPILOG,
        formatter_class=help_formatter.UnsetHidingFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    _subparser(commands, "version", "print the scrobbler's version", run_version)
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
    _subparser(
        commands,
        "install",
        "build, sign and install the app and its LaunchAgent",
        run_install,
    )
    _subparser(
        commands,
        "uninstall",
        "unload the LaunchAgent; keep the app, queue, state and config",
        run_uninstall,
    )
    status = _subparser(commands, "status", "report the scrobbler's health", run_status)
    status.add_argument(
        "--session-check",
        action="store_true",
        help="print one line per problem and nothing when healthy; always exit 0",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    prog: str | None = None,
    host: scrob_host.Host | None = None,
) -> int:
    """Run one command and return its exit code; `host` replaces this process's."""
    stdio_utf8.force_utf8_streams(sys.stdout, sys.stderr)
    args = build_parser(prog).parse_args(argv)
    built: list[scrob_host.Host] = []

    def source() -> scrob_host.Host:
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
    given: scrob_host.Host | None,
    built: list[scrob_host.Host],
    code: int,
) -> int:
    """Print `error` as one ERROR line on the host's stderr, and return `code`.

    A host given to `main`, or one already built, owns the stream; a command that failed
    before building the real host writes to this process's stderr, as that host would.
    """
    hosts = [*built, *([given] if given is not None else [])]
    print(f"ERROR: {error}", file=hosts[0].err if hosts else sys.stderr)
    return code


if __name__ == "__main__":  # pragma: no cover - the CLI entry point; main() is tested
    sys.exit(main())
