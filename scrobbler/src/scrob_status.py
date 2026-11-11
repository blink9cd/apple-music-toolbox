"""`status`: the scrobbler's health as rows and reasons, and the session-start lines.

`gather_status` checks, in order: the agent's plist (absent is "not installed", exit 2,
and nothing else is asked), the agent's state in launchd, the installed app and its
signature, and the app's own `status.json`. Each check adds rows and, when something is
wrong, a reason: "needs attention" (exit 1) for something a person should act on, or
"cannot judge" (exit 2, which outranks it) when a check could not get an answer.

`status.json` is the app's report of itself, rewritten every heartbeat: Unix seconds for
every time, null when unknown. A file that is missing, not a regular file, larger
than `STATUS_MAX_BYTES`, not JSON (a number JSON cannot hold, such as Infinity or NaN,
and nesting too deep to parse, included), not an object, of another format, or holding
a field of the wrong type or a time that is not finite needs attention and is not read
further. The file is opened without blocking, so a FIFO planted in its place is refused
rather than waited on. Every string it holds is shown only as `shown_text`: cut to
`SHOWN_TEXT_MAX` characters, with every character that does not print replaced, so the
app's text can neither forge a second line nor reach the terminal as a control. Of a readable one, attention goes to: a heartbeat older than 90 s, denied
Automation, any refused play, a last send error a retry cannot cure (the token refused or
unreadable, the config refused, the queue folder unreadable or unwritable), and a queued play older than an hour.

`session_lines` is the session-start hook's view: nothing when the plist is absent, one
line per reason otherwise with the home folder written as `$HOME`, and one line naming
only the exception's type, never a traceback, when the check itself fails. Every
launchctl and codesign call is clamped to what remains of `SESSION_BUDGET_S`.

Entry point assumptions: imported by the scrobbler's modules, with `src/` and the shared
libraries on `sys.path`.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import stat
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import launchd_agent
import scrob_bundle
from scrob_host import Host
from scrob_layout import Layout, ScrobPaths
from swgate_model import RunFn

if sys.platform == "win32":
    # The status file is read without blocking, a POSIX open flag; this arm also lets a
    # win32 type-check pass treat the POSIX names below as unreachable.
    raise ImportError("the scrobbler needs macOS")  # pragma: only-on win32

EXIT_HEALTHY, EXIT_ATTENTION, EXIT_CANNOT_JUDGE = 0, 1, 2
SESSION_BUDGET_S: Final = 20.0
#: The bound on the status check's one codesign call.
VERIFY_TIMEOUT_S: Final = 10.0
#: The oldest heartbeat that is still healthy.
HEARTBEAT_LIMIT_S: Final = 90.0
#: The oldest queued play that is still healthy.
QUEUE_LIMIT_S: Final = 3600.0
#: The status.json format this reader understands.
STATUS_FORMAT: Final = 1
#: The largest status.json read: the app's report is a few hundred bytes.
STATUS_MAX_BYTES: Final = 64 * 1024
#: The most characters of any status.json string shown, the cut marked with an ellipsis.
SHOWN_TEXT_MAX: Final = 120
#: What stands in for a character that does not print.
_UNPRINTABLE: Final = "?"
_ELLIPSIS: Final = "…"
NEEDS_ATTENTION: Final = "needs attention"
CANNOT_JUDGE: Final = "cannot judge"
HOME_TOKEN: Final = "$HOME"
#: The command a session line points the reader at.
DETAILS: Final = "scrobbler.py status"
#: The prefix of every line the scrobbler prints about itself.
STEM: Final = "listensmith scrobbler"
#: The last send errors a retry cannot cure: a person has to fix the token, the config or
#: the queue folder itself.
_STUCK_ERRORS: Final = ("token refused", "queue unreadable", "queue unwritable")
_STUCK_PREFIXES: Final = ("token unreadable: ", "config refused: ")
_SECONDS_PER_MINUTE: Final = 60
_NONE: Final = "none"
_VERDICTS: Final = {
    EXIT_HEALTHY: "HEALTHY",
    EXIT_ATTENTION: "NEEDS ATTENTION",
    EXIT_CANNOT_JUDGE: "CANNOT JUDGE",
}

Row = tuple[str, str]


@dataclass(frozen=True)
class Reason:
    """One thing wrong: its kind ("needs attention" or "cannot judge") and its text."""

    kind: str
    text: str


@dataclass(frozen=True)
class StatusReport:
    """What status shows: the rows, then the reasons."""

    rows: tuple[Row, ...]
    reasons: tuple[Reason, ...]

    @property
    def exit_code(self) -> int:
        """2 when any reason cannot judge, else 1 when any needs attention, else 0."""
        kinds = {reason.kind for reason in self.reasons}
        if CANNOT_JUDGE in kinds:
            return EXIT_CANNOT_JUDGE
        return EXIT_ATTENTION if kinds else EXIT_HEALTHY


@dataclass(frozen=True)
class AppStatus:
    """The fields of `status.json` this module reads."""

    version: str | None
    started_at: float | None
    heartbeat_at: float | None
    queue_backlog: int
    oldest_queued_at: float | None
    refused_count: int
    last_queued_at: float | None
    last_sent_at: float | None
    last_send_error: str | None
    automation_denied: bool


class StatusFileError(ValueError):
    """status.json is missing, unreadable, or not the format this module reads."""


class Budget:
    """What remains of a time budget, read from a monotonic `clock`; None is unbounded."""

    def __init__(self, clock: Callable[[], float], budget_s: float | None) -> None:
        """Fix the deadline now, `budget_s` from the clock's reading."""
        self.clock = clock
        self.deadline = None if budget_s is None else clock() + budget_s

    def timeout(self, limit: float) -> float:
        """`limit`, clamped to what remains; zero or less once the budget is spent."""
        if self.deadline is None:
            return limit
        return min(limit, self.deadline - self.clock())

    def clamp_launchctl(self, run: launchd_agent.RunCmd) -> launchd_agent.RunCmd:
        """The launchctl runner with each call's timeout clamped."""

        def clamped(
            argv: Sequence[str], timeout: float
        ) -> subprocess.CompletedProcess[str]:
            return run(argv, self._remaining(argv, timeout))

        return clamped

    def clamp(self, run: RunFn) -> RunFn:
        """The tool runner with each call's timeout clamped."""

        def clamped(
            argv: Sequence[str], *, cwd: Path, timeout: float
        ) -> subprocess.CompletedProcess[str]:
            return run(argv, cwd=cwd, timeout=self._remaining(argv, timeout))

        return clamped

    def _remaining(self, argv: Sequence[str], timeout: float) -> float:
        """What a call may take; TimeoutExpired, the call not started, when nothing is left."""
        remaining = self.timeout(timeout)
        if remaining <= 0:
            raise subprocess.TimeoutExpired(list(argv), 0)
        return remaining


class _Found:
    """The rows and reasons gathered so far."""

    def __init__(self) -> None:
        self.rows: list[Row] = []
        self.reasons: list[Reason] = []

    def row(self, label: str, value: str, attention: str | None = None) -> None:
        """Add a row, and a needs-attention reason when `attention` is given."""
        self.rows.append((label, value))
        if attention is not None:
            self.reasons.append(Reason(NEEDS_ATTENTION, attention))

    def cannot(self, label: str, value: str, why: str) -> None:
        """Add a row and a cannot-judge reason."""
        self.rows.append((label, value))
        self.reasons.append(Reason(CANNOT_JUDGE, why))

    def report(self) -> StatusReport:
        """Everything found."""
        return StatusReport(tuple(self.rows), tuple(self.reasons))


def _optional_number(document: dict[str, object], key: str) -> float | None:
    """`key`'s value as seconds, or None; StatusFileError for any other type."""
    value = document.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise StatusFileError(f"{key} is not a number")
    if not math.isfinite(value):
        raise StatusFileError(f"{key} is not a finite number")
    return float(value)


def _count(document: dict[str, object], key: str) -> int:
    """`key`'s value as a whole count; StatusFileError when it is anything else."""
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise StatusFileError(f"{key} is not a whole number")
    return value


def _optional_text(document: dict[str, object], key: str) -> str | None:
    """`key`'s value as text, or None; StatusFileError for any other type."""
    value = document.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise StatusFileError(f"{key} is not text")
    return shown_text(value)


def parse_app_status(document: object) -> AppStatus:
    """The fields of one status.json document; StatusFileError when it is not format 1."""
    if not isinstance(document, dict):
        raise StatusFileError("it cannot be read: it is not a JSON object")
    if document.get("format") != STATUS_FORMAT:
        raise StatusFileError(f"its format is not {STATUS_FORMAT}")
    denied = document.get("automation_denied")
    if not isinstance(denied, bool):
        raise StatusFileError("automation_denied is not true or false")
    return AppStatus(
        version=_optional_text(document, "version"),
        started_at=_optional_number(document, "started_at"),
        heartbeat_at=_optional_number(document, "heartbeat_at"),
        queue_backlog=_count(document, "queue_backlog"),
        oldest_queued_at=_optional_number(document, "oldest_queued_at"),
        refused_count=_count(document, "refused_count"),
        last_queued_at=_optional_number(document, "last_queued_at"),
        last_sent_at=_optional_number(document, "last_sent_at"),
        last_send_error=_optional_text(document, "last_send_error"),
        automation_denied=denied,
    )


def shown_text(text: str) -> str:
    """`text` safe to print on one line: unprintable characters replaced, and cut short."""
    printable = "".join(c if c.isprintable() else _UNPRINTABLE for c in text)
    if len(printable) <= SHOWN_TEXT_MAX:
        return printable
    return printable[: SHOWN_TEXT_MAX - len(_ELLIPSIS)] + _ELLIPSIS


def _read_bounded(path: Path) -> bytes:
    """The bytes of the regular file at `path`, refused when it is anything else or too big.

    Opened without blocking and checked through the open descriptor, so a FIFO or a
    device is refused rather than read, and the file checked is the file read.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        raise StatusFileError("it is missing") from None
    except OSError as error:
        raise StatusFileError(f"it cannot be read ({type(error).__name__})") from None
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise StatusFileError("it is not a regular file")
        if status.st_size > STATUS_MAX_BYTES:
            raise StatusFileError(f"it is too large ({status.st_size} bytes)")
        return os.read(descriptor, STATUS_MAX_BYTES)
    except OSError as error:
        raise StatusFileError(f"it cannot be read ({type(error).__name__})") from None
    finally:
        os.close(descriptor)


def _refuse_constant(name: str) -> object:
    """The JSON parser's hook for Infinity, -Infinity and NaN, which no status.json holds."""
    raise ValueError(f"{name} is not a JSON number")


def read_app_status(path: Path) -> AppStatus:
    """The app's status file at `path`; StatusFileError when missing or unreadable."""
    raw = _read_bounded(path)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise StatusFileError("it cannot be read (UnicodeDecodeError)") from None
    try:
        document = json.loads(text, parse_constant=_refuse_constant)
    # RecursionError is how the parser reports nesting too deep to follow.
    except (ValueError, RecursionError):
        raise StatusFileError("it cannot be read: it is not JSON") from None
    return parse_app_status(document)


def age_text(at: float | None, now: float) -> str:
    """How long ago `at` was, in whole seconds; "none" when unknown."""
    if at is None:
        return _NONE
    return f"{max(0, int(now - at))} s ago"


def check_agent(found: _Found, host: Host, layout: Layout) -> None:
    """The agent's row; absent needs attention, an unexpected answer cannot judge."""
    state = launchd_agent.agent_state(host.launchctl, layout.launchd_label)
    if state is launchd_agent.AgentState.UNKNOWN:
        found.cannot("agent", state.value, "launchctl gave an unexpected answer")
        return
    loaded = state is launchd_agent.AgentState.LOADED
    problem = None if loaded else f"the agent is {state.value}, not loaded"
    found.row("agent", state.value, problem)


def check_app(found: _Found, host: Host, layout: Layout, paths: ScrobPaths) -> None:
    """The app's row: missing, or failing its strict signature check, needs attention."""
    bundle = paths.app_bundle
    if not scrob_bundle.bundle_executable(bundle, layout).is_file():
        found.row("app", "missing", f"the app is missing: {bundle}")
        return
    try:
        done = host.run(
            scrob_bundle.verify_argv(bundle),
            cwd=paths.data_dir,
            timeout=VERIFY_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        found.cannot(
            "app", "unchecked", f"codesign could not run ({type(error).__name__})"
        )
        return
    # codesign's own output is not shown: it names the signing certificate.
    problem = None
    if done.returncode != 0:
        problem = f"the app fails codesign --verify --strict (exit {done.returncode})"
    found.row("app", "signed" if problem is None else "signature fails", problem)


def _send_error_problem(error: str | None) -> str | None:
    """The reason a last send error gives, when only a person can cure it."""
    if error is None:
        return None
    if error in _STUCK_ERRORS or error.startswith(_STUCK_PREFIXES):
        return f"the last send failed and will not cure itself: {error}"
    return None


def judge_app_status(
    found: _Found, status: AppStatus, paths: ScrobPaths, now: float
) -> None:
    """The app's rows, and a reason for each problem its status names."""
    found.row("backlog", str(status.queue_backlog))
    found.row("refused", str(status.refused_count))
    found.row("newest queued", age_text(status.last_queued_at, now))
    found.row("last sent", age_text(status.last_sent_at, now))
    found.row("version", status.version or _NONE)
    if status.heartbeat_at is None:
        found.reasons.append(
            Reason(NEEDS_ATTENTION, "the app has written no heartbeat")
        )
    elif now - status.heartbeat_at > HEARTBEAT_LIMIT_S:
        age = int(now - status.heartbeat_at)
        found.reasons.append(
            Reason(NEEDS_ATTENTION, f"the app's heartbeat is {age} s old")
        )
    if status.automation_denied:
        found.reasons.append(
            Reason(
                NEEDS_ATTENTION,
                "Automation of Music is denied: allow it in System Settings, Privacy & "
                "Security, Automation",
            )
        )
    _judge_queue(found, status, paths, now)


def _judge_queue(
    found: _Found, status: AppStatus, paths: ScrobPaths, now: float
) -> None:
    """Reasons for refused plays, a stuck send error, and an old queued play."""
    if status.refused_count > 0:
        noun = "play" if status.refused_count == 1 else "plays"
        found.reasons.append(
            Reason(
                NEEDS_ATTENTION,
                f"{status.refused_count} {noun} the store refused wait in "
                f"{paths.refused_dir}",
            )
        )
    stuck = _send_error_problem(status.last_send_error)
    if stuck is not None:
        found.reasons.append(Reason(NEEDS_ATTENTION, stuck))
    oldest = status.oldest_queued_at
    if oldest is not None and now - oldest > QUEUE_LIMIT_S:
        minutes = int(now - oldest) // _SECONDS_PER_MINUTE
        found.reasons.append(
            Reason(
                NEEDS_ATTENTION,
                f"the oldest queued play is {minutes} minutes old (last send error: "
                f"{status.last_send_error or _NONE})",
            )
        )


def check_app_status(found: _Found, host: Host, paths: ScrobPaths) -> None:
    """The status file's rows and reasons; one that cannot be read needs attention."""
    try:
        status = read_app_status(paths.status_file)
    except StatusFileError as error:
        found.row("status file", "unreadable", f"the app's status file: {error}")
        return
    judge_app_status(found, status, paths, host.now())


def budgeted(host: Host, budget: Budget) -> Host:
    """`host` with its launchctl and tool calls clamped to `budget`."""
    launchctl = dataclasses.replace(
        host.launchctl, run=budget.clamp_launchctl(host.launchctl.run)
    )
    return dataclasses.replace(host, launchctl=launchctl, run=budget.clamp(host.run))


def gather_status(
    host: Host, layout: Layout, *, budget_s: float | None = None
) -> StatusReport:
    """Every check, each adding rows and, when wrong, a reason."""
    paths = layout.paths(host.home)
    if not paths.launch_agent_plist.exists():
        return StatusReport(
            (("agent", "not installed"),), (Reason(CANNOT_JUDGE, "not installed"),)
        )
    found = _Found()
    host = budgeted(host, Budget(host.clock, budget_s))
    check_agent(found, host, layout)
    check_app(found, host, layout, paths)
    check_app_status(found, host, paths)
    return found.report()


def format_lines(report: StatusReport) -> list[str]:
    """What `status` prints: the verdict, each reason, then the rows as a table."""
    code = report.exit_code
    lines = [f"{STEM}: {_VERDICTS[code]} (exit {code})"]
    lines += [f"- {reason.kind}: {reason.text}" for reason in report.reasons]
    lines += ["", "| Item | State |", "| --- | --- |"]
    lines += [f"| {label} | {value} |" for label, value in report.rows]
    return lines


def redact_home(text: str, home: Path) -> str:
    """`text` with the home folder written as `$HOME`."""
    return text.replace(str(home), HOME_TOKEN)


def session_lines(host: Host, layout: Layout) -> list[str]:
    """One line per reason, home redacted; none when not installed; never raises."""
    try:
        if not layout.paths(host.home).launch_agent_plist.exists():
            return []
        report = gather_status(host, layout, budget_s=SESSION_BUDGET_S)
        return [
            redact_home(
                f"{STEM}: {reason.kind} -- {reason.text}; details: {DETAILS}", host.home
            )
            for reason in report.reasons
        ]
    # Broad on purpose: a hook's failure must be one line, never a traceback, and the
    # line names the type alone, so no value a message might hold is ever printed.
    except Exception as error:  # noqa: BLE001 - reported as the one failure line
        return [f"{STEM}: session check failed -- unexpected {type(error).__name__}"]
