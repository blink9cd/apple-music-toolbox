"""The process-level facts the scrobbler's commands read, gathered into one injectable `Host`.

Every fact a command takes from its process (the home folder, the uid, the pid, this
checkout's entry script, wall and monotonic time, sleeping, launchctl, the bounded subprocess runner for swift, codesign and git, and the two
output streams) arrives through a `Host`, so a test replaces each with a fake and nothing
under test reaches the machine. `real_host` builds this process's.

Entry point assumptions: imported by the scrobbler's modules, with `src/` and the shared
libraries on `sys.path`, as `scrobbler.py` arranges.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import launchd_agent
from bounded_run import run_bounded
from swgate_model import RunFn

if sys.platform == "win32":
    # The scrobbler runs under launchd only; this arm also lets a win32 type-check pass
    # treat the POSIX names below as unreachable rather than missing.
    raise ImportError("the scrobbler needs macOS")  # pragma: only-on win32


@dataclass(frozen=True)
class Host:
    """Every process-level fact a command reads.

    `script` is this checkout's `scrobbler.py`, resolved, so the app package beside it and
    the checkout holding it are derived rather than named; `now` is wall time in Unix
    seconds, the clock `status.json` is written in; `clock` is monotonic, for deadlines;
    `run` runs one argv in a folder under a timeout, as swift_gate's runner does.
    """

    home: Path
    uid: int
    pid: int
    script: Path
    now: Callable[[], float]
    clock: Callable[[], float]
    sleep: Callable[[float], None]
    launchctl: launchd_agent.Launchctl
    run: RunFn
    out: TextIO
    err: TextIO


#: git settings a caller's environment may carry that would point git at another repository
#: than the folder it is asked about, so the linked-worktree check would judge the wrong one.
_GIT_LOCATION_VARIABLES = frozenset(
    {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES"}
)


def tool_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """A copy of `environ` for swift, codesign and git: untranslated, with no git location.

    git's "not a git repository" is read as text, so a translated message would read as
    some other failure; `LC_ALL=C` outranks every other locale variable. The git location
    variables are dropped so git answers about the folder named with ``-C``.
    """
    kept = {
        name: value
        for name, value in environ.items()
        if name not in _GIT_LOCATION_VARIABLES
    }
    return {**kept, "LC_ALL": "C"}


def _run_real(
    argv: Sequence[str], *, cwd: Path, timeout: float
) -> subprocess.CompletedProcess[str]:  # pragma: no cover - the real host seam
    """Run `argv` in `cwd` on this machine, bounded, with an untranslated locale."""
    return run_bounded(argv, timeout=timeout, cwd=cwd, env=tool_environment(os.environ))


def real_host(script: Path) -> Host:  # pragma: no cover - the real host seam
    """The Host of this process, whose entry script is `script`."""
    return Host(
        home=Path.home(),
        uid=os.getuid(),
        pid=os.getpid(),
        script=script,
        now=time.time,
        clock=time.monotonic,
        sleep=time.sleep,
        launchctl=launchd_agent.real_launchctl(),
        run=_run_real,
        out=sys.stdout,
        err=sys.stderr,
    )
