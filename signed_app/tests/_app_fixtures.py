"""Fake host seams for a signed app's suites: swift, codesign, git, launchd and the clocks.

`make_host_kit` builds an `app_host.Host` whose home is a fresh temporary folder, whose
clock is a `FakeClock` that only moves when something sleeps, whose `launchctl` is a
scripted `FakeLaunchd` and whose `run` is a scripted `FakeTools`, so no test reaches the
real HOME, `~/Library`, launchd, a real repository, swift or codesign. The checkout and
entry script it names are invented folders under the same temporary root. An app's own
fixtures build their kit on this one and add what only that app has.

`FAKE_IDENTITY` is an obvious fake signing identity whose name and team ID a test asserts
appear nowhere in any output. `InventedSpec` is an invented bundle's names.

Entry point assumptions: imported only, by the suites in this folder and by an app's own
fixtures; importing it imports `signed_app`, the front module beside this folder, which
puts this library's ``src/`` and the shared libraries it imports on `sys.path`.
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

#: The library's own folder, which holds signed_app.py, the front module.
_LIBRARY_ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_LIBRARY_ROOT))

import signed_app  # noqa: E402, F401 - puts src/ and the shared libraries on sys.path
import app_host  # noqa: E402 - on sys.path once signed_app is imported
import launchd_agent  # noqa: E402 - on sys.path once signed_app is imported

#: An invented uid; launchctl is never really asked.
UID = 4242
#: An invented pid, naming a staging folder.
PID = 31337
#: A pid no process can hold: one past Linux's largest `pid_max`, and far past macOS's
#: own limit, so `kill(pid, 0)` answers "no such process" on either. It names a work
#: folder a dead install left.
DEAD_PID = 4_194_305
#: The fake wall clock's start, in Unix seconds.
START = 1_793_000_000.0
#: An obvious fake signing identity: an invented name and team ID.
FAKE_NAME = "Invented Example Person"
FAKE_TEAM = "FAKETEAM00"
FAKE_IDENTITY = f"Apple Development: {FAKE_NAME} ({FAKE_TEAM})"
#: The designated requirement a bundle signed with `FAKE_IDENTITY` would carry: it names
#: the certificate, so a test asserts it appears nowhere in any output either.
FAKE_REQUIREMENT = (
    'identifier "local.invented.example" and anchor apple generic and '
    f'certificate leaf[subject.CN] = "{FAKE_IDENTITY}"'
)
#: launchctl print's answer for a label it does not hold.
ABSENT_RC = launchd_agent.PRINT_ABSENT_RC
#: git's exit and message for a folder outside every repository.
NOT_A_REPO_RC = 128
NOT_A_REPO_ERR = (
    "fatal: not a git repository (or any of the parent directories): .git\n"
)
#: What the fake swift writes as the built executable.
BUILT_BYTES = b"invented executable\n"
#: Why a case-only rename test is skipped on a volume that tells the spellings apart.
CASE_SENSITIVE_REASON = "the temporary folder's volume is case-sensitive"


def temporary_volume_ignores_case() -> bool:
    """Whether the volume temporary folders live on treats two spellings as one name.

    Default APFS does, so a case-only rename meets the old entry there; the suites that
    reproduce that ask this once, at import, rather than assume either answer.
    """
    with tempfile.TemporaryDirectory() as folder:
        (Path(folder) / "probe").mkdir()
        return (Path(folder) / "PROBE").exists()


#: Measured once: whether the volume under the kits' temporary homes ignores case.
CASE_INSENSITIVE_TMP: Final = temporary_volume_ignores_case()


@dataclass(frozen=True)
class InventedSpec:
    """An invented bundle's names, as a `app_bundle.BundleSpec` reads them."""

    bundle_id: str = "local.invented.example"
    display_name: str = "Invented Example"
    executable: str = "invented"
    version: str = "1.2.3"
    app_name: str = "Invented Example.app"


def done(
    argv: Sequence[str], code: int, out: str = "", err: str = ""
) -> subprocess.CompletedProcess[str]:
    """A finished process answering `argv` with `code`, `out` and `err`."""
    return subprocess.CompletedProcess(list(argv), code, out, err)


@dataclass
class FakeClock:
    """Wall and monotonic time that advance together, and only when slept."""

    wall: float = START
    mono: float = 0.0
    slept: list[float] = field(default_factory=list)

    def now(self) -> float:
        """The fake wall clock."""
        return self.wall

    def clock(self) -> float:
        """The fake monotonic clock."""
        return self.mono

    def sleep(self, seconds: float) -> None:
        """Advance both clocks instead of waiting."""
        self.slept.append(seconds)
        self.wall += seconds
        self.mono += seconds


@dataclass
class FakeLaunchd:
    """launchd as a set of loaded labels: print, bootout and bootstrap act on it.

    `on_bootstrap`, when set, runs at each bootstrap, as the app starting would.
    """

    clock: FakeClock
    log: list[str]
    loaded: set[str] = field(default_factory=set)
    #: Labels whose print answers an unexpected exit.
    unknown: set[str] = field(default_factory=set)
    on_bootstrap: Callable[[], None] | None = None

    def run(
        self, argv: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        """Answer one launchctl call as launchd would, logging bootout and bootstrap."""
        args = list(argv)
        verb = args[1]
        if verb == "bootstrap":
            self.log.append("bootstrap")
            self.loaded.add(Path(args[3]).stem)
            if self.on_bootstrap is not None:
                self.on_bootstrap()
            return done(args, 0)
        label = args[2].rsplit("/", 1)[1]
        if verb == "bootout":
            self.log.append("bootout")
            self.loaded.discard(label)
            return done(args, 0)
        if label in self.unknown:
            return done(args, 1, err="invented unexpected answer\n")
        return done(args, 0 if label in self.loaded else ABSENT_RC)

    def launchctl(self) -> launchd_agent.Launchctl:
        """The Launchctl a host hands launchd_agent."""
        return launchd_agent.Launchctl(
            run=self.run, uid=UID, clock=self.clock.clock, sleep=self.clock.sleep
        )


@dataclass
class FakeTools:
    """swift, codesign and git, scripted and logged; no real tool runs.

    git answers from `repos`, a list of invented repository roots: a folder at or under
    one is inside it, any other folder is outside every repository. swift writes
    `BUILT_BYTES` as the executable named `product` on a build that succeeds.
    """

    log: list[str]
    product: str = InventedSpec.executable
    repos: list[Path] = field(default_factory=list)
    git_dir: str = ".git"
    common_dir: str = ".git"
    build_rc: int = 0
    bin_rc: int = 0
    sign_rc: int = 0
    verify_rc: int = 0
    sign_output: str = ""
    verify_output: str = ""
    #: What ``codesign -d -r-`` answers: its exit, and the designated line on stdout.
    display_rc: int = 0
    display_output: str = f"designated => {FAKE_REQUIREMENT}\n"
    #: Tools that cannot be run at all.
    missing: set[str] = field(default_factory=set)
    calls: list[list[str]] = field(default_factory=list)

    def run(
        self, argv: Sequence[str], *, cwd: Path, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        """Answer one call, logging it."""
        args = list(argv)
        self.calls.append(args)
        if args[0] in self.missing:
            raise FileNotFoundError(args[0])
        if args[0] == "git":
            return self._git(args, cwd)
        if args[0] == "swift":
            return self._swift(args)
        return self._codesign(args)

    def _repo_of(self, folder: Path) -> Path | None:
        """The fake repository holding `folder`, if any."""
        for repo in self.repos:
            if folder == repo or repo in folder.parents:
                return repo
        return None

    def _git(self, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        """rev-parse and worktree list, answered from `repos`."""
        folder = Path(args[2]) if args[1] == "-C" else cwd
        repo = self._repo_of(folder.resolve())
        if repo is None:
            return done(args, NOT_A_REPO_RC, err=NOT_A_REPO_ERR)
        if "--show-toplevel" in args:
            return done(args, 0, f"{repo}\n")
        if "worktree" in args:
            return done(args, 0, f"worktree {repo}\nHEAD invented\n")
        self.log.append("git")
        return done(args, 0, f"{self.git_dir}\n{self.common_dir}\n")

    def _swift(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """A build that writes the product, or names its folder."""
        # SwiftPM names the product folder after the configuration -c chose.
        config = args[args.index("-c") + 1]
        bin_dir = Path(args[args.index("--scratch-path") + 1]) / config
        if "--show-bin-path" in args:
            return done(args, self.bin_rc, f"{bin_dir}\n" if not self.bin_rc else "")
        self.log.append("build")
        if self.build_rc:
            return done(args, self.build_rc, err="error: invented compile failure\n")
        bin_dir.mkdir(parents=True, exist_ok=True)
        product = bin_dir / self.product
        product.write_bytes(BUILT_BYTES)
        product.chmod(0o755)
        return done(args, 0)

    def _codesign(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Sign, display or verify, answering the scripted exit and output."""
        if "-d" in args:
            # codesign prints the designated requirement on stdout, the rest on stderr.
            self.log.append("display")
            return done(args, self.display_rc, out=self.display_output)
        if "--sign" in args:
            self.log.append("sign")
            return done(args, self.sign_rc, err=self.sign_output)
        self.log.append("verify")
        return done(args, self.verify_rc, err=self.verify_output)


@dataclass
class HostKit:
    """A fake host and the fakes, folders and streams behind it."""

    host: app_host.Host
    home: Path
    checkout: Path
    clock: FakeClock
    launchd: FakeLaunchd
    tools: FakeTools
    log: list[str]
    out: io.StringIO
    err: io.StringIO

    def output(self) -> str:
        """Everything written to both streams."""
        return self.out.getvalue() + self.err.getvalue()


def make_host_kit(test: unittest.TestCase, *, script: str, product: str) -> HostKit:
    """A host on a temporary home, removed when `test` ends, with fresh fakes.

    `script` is the entry script's path below the invented checkout, and `product` the
    executable the fake swift builds. The checkout is a repository's main checkout by
    default: one fake repository whose git folder and common folder are the same.
    """
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    root = Path(folder.name).resolve()
    home, checkout = root / "home", root / "checkout"
    for made in (home, checkout):
        made.mkdir()
    log: list[str] = []
    clock = FakeClock()
    launchd = FakeLaunchd(clock=clock, log=log)
    tools = FakeTools(log=log, product=product, repos=[checkout])
    out, err = io.StringIO(), io.StringIO()
    host = app_host.Host(
        home=home,
        uid=UID,
        pid=PID,
        script=checkout / script,
        now=clock.now,
        clock=clock.clock,
        sleep=clock.sleep,
        launchctl=launchd.launchctl(),
        run=tools.run,
        out=out,
        err=err,
    )
    return HostKit(host, home, checkout, clock, launchd, tools, log, out, err)
