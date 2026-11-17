"""grant_probe: ask Music.app one read-only question, and record whether macOS allowed it.

`runner.py install` starts this script once through the installed runner app, so the
question is charged to the app and the answer says whether the app holds the Automation
permission for Music. It asks for the player state, and only when Music is already
running: AppleScript's ``is running`` test sends no Apple event, so this never opens
Music. It never asks for Music's version, which AppleScript answers from the app's bundle
with no event at all, and so would report a grant that was never given.

The first time, macOS shows its permission prompt and holds the event until a person
answers. The script therefore has no ``with timeout`` clause (a short one withdraws the
prompt before it can be read; AppleScript's default is 120 s), and the subprocess bound,
`GRANT_PROBE_TIMEOUT_S`, is longer than that default.

The result is one JSON document, ``{"outcome": ..., "detail": ...}``, written to
``--result`` in one step so a reader never sees half of it. The outcome is `GRANTED` (a
state came back), `NOT_RUNNING` (Music is closed, so nothing was asked), `DENIED`
(-1743 or -1744), `TIMED_OUT` (-1712, or the bound expired) or `ERROR` (anything else,
with the first line osascript wrote). It exits 0 once the result is written and 1 when it
cannot be, with one ``ERROR:`` line.

Importing this module puts the shared libraries on ``sys.path``, each at one fixed place
directly under the project root.

Entry point assumptions: run as a script by the runner app under launchd, or imported
for `main` and the outcome names.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

# The shared libraries, each at one fixed place: directly under the project root, two
# folders above this file's own. Deliberately not a search up the ancestors, as in
# runner.py: that would also put any same-named folder above the checkout on sys.path.
_LIBRARIES: Final = ("stdio_utf8", "help_formatter", "bounded_run", "atomic_write")
sys.path += [str(Path(__file__).resolve().parents[2] / name) for name in _LIBRARIES]

import atomic_write  # noqa: E402 - import follows the sys.path bootstrap above
import help_formatter  # noqa: E402 - import follows the sys.path bootstrap above
import stdio_utf8  # noqa: E402 - import follows the sys.path bootstrap above
from bounded_run import run_bounded  # noqa: E402 - import follows the bootstrap above

#: macOS's own osascript, by its full path: launchd's PATH is not the login shell's.
OSASCRIPT: Final = "/usr/bin/osascript"
#: The one question. No `with timeout` clause, and never `get version`: see the module
#: docstring for why each would give a wrong answer.
SCRIPT: Final = (
    'if application "Music" is running then tell application "Music" to get '
    "player state as text"
)
#: The bound on the osascript process: past AppleScript's own 120 s wait for an answer,
#: so a prompt nobody answers ends as osascript's -1712, not as this bound.
GRANT_PROBE_TIMEOUT_S: Final = 150.0
#: The outcomes a result file can hold.
GRANTED: Final = "granted"
NOT_RUNNING: Final = "not-running"
DENIED: Final = "denied"
TIMED_OUT: Final = "timed-out"
ERROR: Final = "error"
#: How osascript's last line ends when macOS refused the event, or never answered it.
_DENIED_ENDINGS: Final = ("(-1743)", "(-1744)")
_NO_ANSWER_ENDING: Final = "(-1712)"
#: The result file's mode: its user's alone.
_RESULT_MODE: Final = 0o600
#: The command line's epilog: what the probe needs.
_EPILOG: Final = (
    "Prerequisites: macOS, and the folder that will hold --result. Started by the "
    "runner app during its install; it reads Music's player state when Music is "
    "running, and changes nothing."
)

#: Runs osascript: the argv and its bound in, the finished process out.
RunFn = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


def _run_real(
    argv: Sequence[str], timeout: float
) -> subprocess.CompletedProcess[str]:  # pragma: no cover - the real osascript seam
    """Run osascript on this machine, bounded; it may raise macOS's permission prompt."""
    return run_bounded(argv, timeout=timeout)


def _result(outcome: str, detail: str) -> dict[str, str]:
    """One result document."""
    return {"outcome": outcome, "detail": detail}


def classify(done: subprocess.CompletedProcess[str]) -> dict[str, str]:
    """The result for a finished osascript: its exit, its answer and its last words."""
    state = done.stdout.strip()
    if done.returncode == 0:
        return _result(GRANTED if state else NOT_RUNNING, state)
    said = done.stderr.strip()
    first = said.splitlines()[0] if said else f"osascript exited {done.returncode}"
    if said.endswith(_DENIED_ENDINGS):
        return _result(DENIED, first)
    if said.endswith(_NO_ANSWER_ENDING):
        return _result(TIMED_OUT, first)
    return _result(ERROR, first)


def probe(run: RunFn) -> dict[str, str]:
    """Ask the question through `run` and return the result document."""
    try:
        done = run([OSASCRIPT, "-e", SCRIPT], GRANT_PROBE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return _result(
            TIMED_OUT, f"osascript did not finish in {GRANT_PROBE_TIMEOUT_S:g} s"
        )
    except OSError as error:
        return _result(ERROR, f"could not run osascript ({type(error).__name__})")
    return classify(done)


def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    """The command line, named `prog` (argv[0]'s file name when None)."""
    parser = stdio_utf8.EscapingArgumentParser(
        prog=prog,
        description=(
            "Check whether the app that started this may read Music's player state."
        ),
        epilog=_EPILOG,
        formatter_class=help_formatter.UnsetHidingFormatter,
    )
    parser.add_argument(
        "--result",
        type=Path,
        required=True,
        metavar="FILE",
        help="file to write the outcome to, as one JSON document",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    prog: str | None = None,
    run: RunFn = _run_real,
) -> int:
    """Ask, write the result, and return 0; 1 when the result cannot be written."""
    stdio_utf8.force_utf8_streams(sys.stdout, sys.stderr)
    args = build_parser(prog).parse_args(argv)
    document = probe(run)
    try:
        atomic_write.replace_text(
            args.result, json.dumps(document) + "\n", mode=_RESULT_MODE
        )
    except OSError as error:
        # The error's own text names the path, which sits under the home folder.
        print(
            f"ERROR: could not write the result ({type(error).__name__})",
            file=sys.stderr,
        )
        return 1
    print(f"{document['outcome']}: {document['detail']}")
    return 0


if __name__ == "__main__":  # pragma: no cover - the CLI entry point; main() is tested
    sys.exit(main())
