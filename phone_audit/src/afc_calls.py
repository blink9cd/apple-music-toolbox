"""The one seam to ``afcclient``: the only module here that builds its argv or starts it.

**Read-only by construction.** `ALLOWED_COMMANDS` names the two reads the tool
sends (``ls``, and ``get``, which copies phone to Mac); `command_argv` raises
`ForbiddenCommand` for any other command, and for ``get``'s overwrite and recursive
flags, before a process exists. A test pins the set's exact value, so widening it is a
reviewed decision, never an accident.

**How afcclient 1.4.0 reports failure** (read from its source): a command that fails
still exits 0 and prints one stdout line starting ``Error: ``, so the exit status alone
would call a failed listing an empty folder. A connection failure (no device, a
lockdown refusal) exits 1 with its reason on stderr, and a bad option exits 2. So a
call fails on any exit but 0 (`Unreachable`) or on any stdout line starting
``Error: `` (`CommandFailed`). A command's own flags go after ``--``, or afcclient's
``getopt`` reads them as its own. A phone unplugged while a command runs is reported
on stdout alone: a ``[disconnected]`` line, then exit 0; that line is `Unreachable`.

Every call goes through a `Runner` with its own named bound: `real_run` is
`bounded_run`, which kills the whole process tree at the bound. With no device
afcclient exits at once; with ``-u UDID`` and only a different device connected, it
waits for that one, so the first call runs out its whole bound (`GET_TIMEOUT_S`) before
the run exits 2. The bound is what turns a phone that never answers into an error
rather than a hang. The child runs with ``COLOR=0``, so no color escape wraps a listed
name.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import bounded_run

#: The only commands this tool may send: reads, never a write.
ALLOWED_COMMANDS: Final = frozenset({"ls", "get"})
#: ``get`` flags that are refused: ``-f`` overwrites a local file, ``-r`` recurses.
_FORBIDDEN_FLAGS: Final = frozenset({"-f", "-r", "-rf", "-fr"})
#: The afcclient release whose output formats this tool was proven against.
PROVEN_VERSION: Final = "1.4.0"
#: Bounds, in seconds. A listing is one round trip per entry; a copy moves the whole
#: database, which can run to many megabytes over USB; ``-v`` touches no device.
LS_TIMEOUT_S: Final = 60.0
GET_TIMEOUT_S: Final = 600.0
VERSION_TIMEOUT_S: Final = 15.0
#: How afcclient starts a failed command's one stdout line.
ERROR_PREFIX: Final = "Error: "
#: The line afcclient prints on stdout, and then exits 0, when the phone is unplugged.
DISCONNECTED_LINE: Final = "[disconnected]"
#: The end of the line for a path the phone does not have: AFC_E_OBJECT_NOT_FOUND.
#: Keyed on the code, not afc_strerror's words, which have read differently by release.
_NOT_FOUND_TAIL: Final = "(8)"
#: The ``-v`` line: the tool's name, its version, then perhaps a build note.
_VERSION_LINE = re.compile(r"afcclient (\S+)")

Runner = Callable[[list[str], float], subprocess.CompletedProcess[str]]


class ForbiddenCommand(ValueError):
    """A command, or a flag, outside the read-only allowlist."""


class AfcError(Exception):
    """A call that did not do what was asked: its one-line reason."""

    def __init__(self, reason: str) -> None:
        """Keep *reason*, the line a refusal quotes."""
        super().__init__(reason)
        self.reason = reason


class Unreachable(AfcError):
    """afcclient could not run, did not answer in time, or could not reach the phone."""


class CommandFailed(AfcError):
    """afcclient reached the phone, and the command failed: its ``Error:`` line."""


def command_argv(
    binary: str, command: str, args: Sequence[str], *, udid: str | None = None
) -> list[str]:
    """The argv running *command* with *args*; raises `ForbiddenCommand` for a write."""
    if command not in ALLOWED_COMMANDS:
        raise ForbiddenCommand(f"afcclient command {command!r} is not a read")
    if command == "get" and _FORBIDDEN_FLAGS.intersection(args):
        raise ForbiddenCommand("afcclient get may not overwrite or recurse")
    device = [] if udid is None else ["-u", udid]
    return [binary, *device, "--", command, *args]


def child_env(environ: Mapping[str, str]) -> dict[str, str]:
    """*environ* with afcclient's colors turned off."""
    return {**environ, "COLOR": "0"}


def real_run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """Run *argv* through `bounded_run`, which kills its whole tree at *timeout*."""
    return bounded_run.run_bounded(argv, timeout=timeout, env=child_env(os.environ))


def _error_line(stdout: str) -> str | None:
    """The first line of *stdout* starting ``Error: ``, or None.

    Split on carriage returns too: a large copy's progress redraws one line with them,
    and an error printed after it starts a line of its own.
    """
    for line in stdout.splitlines():
        if line.startswith(ERROR_PREFIX):
            return line
    return None


@dataclass(frozen=True)
class Afc:
    """afcclient at *binary*, aimed at the phone *udid* (or the only one), run by *run*."""

    binary: str
    udid: str | None
    run_process: Runner

    def run(self, command: str, args: Sequence[str], timeout: float) -> str:
        """Run one allowlisted *command*; return its stdout, or raise `AfcError`."""
        argv = command_argv(self.binary, command, args, udid=self.udid)
        try:
            result = self.run_process(argv, timeout)
        except subprocess.TimeoutExpired:
            raise Unreachable(
                f"afcclient {command} did not answer within {timeout:g} s"
            ) from None
        except OSError as error:
            raise Unreachable(
                f"cannot run {self.binary}: {error.strerror or error}"
            ) from None
        if result.returncode != 0:
            said = (result.stderr or "").strip().splitlines()
            detail = said[0] if said else "no message"
            raise Unreachable(
                f"afcclient {command}: exit {result.returncode}: {detail}"
            )
        if DISCONNECTED_LINE in result.stdout.splitlines():
            raise Unreachable(f"afcclient {command}: the phone was disconnected")
        line = _error_line(result.stdout)
        if line is not None:
            raise CommandFailed(line)
        return result.stdout

    def list_dir(self, path: str) -> str:
        """``ls -l`` of *path*: one line per entry."""
        return self.run("ls", ["-l", path], LS_TIMEOUT_S)

    def copy_file(self, remote: str, local: Path) -> bool:
        """Copy *remote* from the phone to *local*; False when the phone has no such file.

        *local* must not exist: afcclient refuses to overwrite without ``-f``, which is
        never passed. After the copy reports success the file is confirmed to be there.
        """
        if os.path.lexists(local):
            raise FileExistsError(f"{local} already exists")
        try:
            self.run("get", [remote, str(local)], GET_TIMEOUT_S)
        except CommandFailed as failed:
            if failed.reason.endswith(_NOT_FOUND_TAIL):
                return False
            raise
        if not local.is_file():
            raise CommandFailed(
                f"afcclient get {remote} reported a copy but left no file"
            )
        return True

    def version(self) -> str | None:
        """The version ``-v`` reports, or None when it cannot be read."""
        try:
            result = self.run_process([self.binary, "-v"], VERSION_TIMEOUT_S)
        except (subprocess.TimeoutExpired, OSError):
            return None
        found = _VERSION_LINE.match(result.stdout)
        if result.returncode != 0 or found is None:
            return None
        return found.group(1)
