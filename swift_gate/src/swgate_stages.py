"""The ordered stage pipeline for one package: manifest, markers, build, test, coverage, sign.

Private to ``swift_gate``. The ORDER is the design, and :data:`STAGES` is where it is
written down: each stage is one named function taking the shared :class:`StageContext`
and the run's :class:`Progress`, returning a terminal :class:`~swgate_model.GateResult`
to stop the pipeline or None to go on. The coverage verdict always follows them, and the
opt-in sign stage (:data:`FINISH`) takes that verdict and returns the package's result:
it signs only a package that passed, and only when ``--sign`` put a setting on the
options.

A stage that cannot even ask its question raises (``ParseError``, ``FileNotFoundError``:
exit 2 at the caller); a stage that got an answer it did not like either returns a
terminal result (a failed build or test run) or records a finding and lets the pipeline
continue, so one run reports a manifest finding and the coverage shortfall together.

Entry point assumptions
-----------------------
Runs no subprocess itself: every command goes through an injected
:class:`~swgate_model.RunFn` carried on :class:`StageContext`, ``swift`` through one and
``codesign`` through the other. Reads the package's sources, reads and deletes coverage
reports under the scratch dir, which is never inside the package, and signs only copies
of the built products, made in a temp dir of their own.
"""

from __future__ import annotations

import dataclasses
import hashlib
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from swgate_coverage import measure, parse_export
from swgate_manifest import check_manifest, parse_dump_package
from swgate_markers import Marker, apply_markers, scan_markers
from swgate_model import (
    Configured,
    Finding,
    GateOptions,
    GateResult,
    NotConfigured,
    RunFn,
    Subject,
)
from swgate_signing import redact, render_identity, render_path
from swgate_subject import MANIFEST, package_sources

_SCRATCH_DIRNAME = "swift_gate"
_SCRATCH_HASH_CHARS = 16
_WARN_FLAGS = ("-Xswiftc", "-warnings-as-errors")
_CODECOV_GLOB = "codecov/*.json"
# LLVM's profile counters are plain, non-atomic increments, and swift-testing runs a
# package's tests in parallel in one process unless told otherwise (SwiftPM's own
# "default: --no-parallel" is XCTest's). Two tests bumping one function's entry counter
# at once can lose an increment, and a region counted by subtracting from it (a
# ternary's last arm) then reads 0: a miss the tests did cover. Serial runs count
# exactly. Measured: 8 parallel tests of a million calls each recorded 3.9M to 4.7M
# entries; serially, 8,000,000 every run.
_SERIAL_FLAG = "--no-parallel"
_CODESIGN = "codesign"
_SIGN_STAGE = "sign"


def default_scratch_base() -> Path:
    """``<tempdir>/swift_gate``: the base every package's scratch dir sits under."""
    return Path(tempfile.gettempdir()) / _SCRATCH_DIRNAME


def scratch_for(package: Path, base: Path) -> Path:
    """The package's own scratch dir: *base* / the first 16 hex of its path's sha256.

    Keyed on the resolved path so two packages never share build state, and rooted
    outside the checkout so a gate run never writes into the tree it gates.
    """
    digest = hashlib.sha256(str(package.resolve()).encode("utf-8")).hexdigest()
    return base / digest[:_SCRATCH_HASH_CHARS]


class StageTimeout(Exception):
    """A stage's command outlived its per-call bound; carries the stage's name."""

    def __init__(self, stage: str) -> None:
        """Record which stage timed out."""
        super().__init__(stage)
        self.stage = stage


@dataclass(frozen=True)
class StageContext:
    """What every stage needs: the package, the options, the seams, and its scratch dir."""

    subject: Subject
    opts: GateOptions
    run: RunFn
    scratch: Path
    codesign_run: RunFn

    def swift(self, stage: str, *args: str) -> subprocess.CompletedProcess[str]:
        """Run ``swift <args>`` in the package, naming *stage* if it times out."""
        try:
            return self.run(
                [self.opts.swift, *args],
                cwd=self.subject.root,
                timeout=self.opts.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise StageTimeout(stage) from exc

    def codesign(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        """Run ``codesign <args>`` in *cwd*, naming the sign stage if it times out."""
        try:
            return self.codesign_run(
                [_CODESIGN, *args], cwd=cwd, timeout=self.opts.timeout
            )
        except subprocess.TimeoutExpired as exc:
            raise StageTimeout(_SIGN_STAGE) from exc


@dataclass
class Progress:
    """What the stages accumulate: findings, markers, the report path, the executables."""

    findings: list[Finding] = field(default_factory=list)
    markers: tuple[Marker, ...] = ()
    report: Path | None = None
    executables: tuple[str, ...] = ()


def _output(completed: subprocess.CompletedProcess[str]) -> str:
    """A command's combined output, stripped, for a failure detail."""
    return (completed.stdout + completed.stderr).strip()


def manifest_stage(ctx: StageContext, progress: Progress) -> GateResult | None:
    """Dump the manifest and check the floor (SWG001) and the language mode (SWG002)."""
    done = ctx.swift(
        "manifest", "package", "--scratch-path", str(ctx.scratch), "dump-package"
    )
    if done.returncode != 0:
        return GateResult(1, f"swift package dump-package failed:\n{_output(done)}")
    facts = parse_dump_package(done.stdout)
    progress.executables = facts.executables
    progress.findings.extend(check_manifest(facts, ctx.opts.macos_floor, MANIFEST))
    return None


def marker_stage(ctx: StageContext, progress: Progress) -> GateResult | None:
    """Scan the package's own sources for markers; SWG003 for a reasonless one."""
    sources = package_sources(ctx.subject.root, ctx.subject.excludes)
    progress.markers, findings = scan_markers(sources, ctx.subject.root)
    progress.findings.extend(findings)
    return None


def build_stage(ctx: StageContext, progress: Progress) -> GateResult | None:
    """Build the package and its tests, instrumented, with warnings as errors."""
    done = ctx.swift(
        "build",
        "build",
        "--build-tests",
        "--enable-code-coverage",
        "--scratch-path",
        str(ctx.scratch),
        *_WARN_FLAGS,
    )
    if done.returncode == 0:
        return None
    return GateResult(
        1,
        f"swift build failed (-warnings-as-errors):\n{_output(done)}",
        tuple(progress.findings),
    )


def swift_test_stage(ctx: StageContext, progress: Progress) -> GateResult | None:
    """Run the tests on the built products, then ask SwiftPM where the report went.

    Every earlier report under the scratch dir is deleted first, so a run whose tests
    write no fresh report can never be measured against a stale one. The tests run
    serially (:data:`_SERIAL_FLAG`), because the counts they record are the verdict.
    """
    for stale in ctx.scratch.rglob(_CODECOV_GLOB):
        stale.unlink()
    done = ctx.swift(
        "test",
        "test",
        "--skip-build",
        "--enable-code-coverage",
        _SERIAL_FLAG,
        "--scratch-path",
        str(ctx.scratch),
    )
    if done.returncode != 0:
        return GateResult(
            1,
            f"swift test failed (rc {done.returncode}):\n{_output(done)}",
            tuple(progress.findings),
        )
    where = ctx.swift(
        "codecov-path",
        "test",
        "--show-codecov-path",
        "--scratch-path",
        str(ctx.scratch),
    )
    lines = where.stdout.strip().splitlines()
    report = Path(lines[-1].strip()) if where.returncode == 0 and lines else None
    if report is None or not report.is_file():
        return GateResult(
            1,
            f"swift test produced no coverage report:\n{_output(where)}",
            tuple(progress.findings),
        )
    progress.report = report
    return None


def coverage_stage(ctx: StageContext, progress: Progress) -> GateResult:
    """Measure region coverage after markers; SWG004 dead markers, SWG005 vacuous."""
    assert progress.report is not None  # swift_test_stage returns terminally otherwise
    text = progress.report.read_text(encoding="utf-8")
    functions = parse_export(text, ctx.subject.root, ctx.subject.excludes)
    excluded, dead = apply_markers(progress.markers, functions, ctx.subject.root)
    progress.findings.extend(dead)
    measured = measure(functions, excluded, ctx.subject.root)
    detail = ""
    if measured.percent is None:
        progress.findings.append(
            Finding(
                "SWG005",
                "Sources",
                0,
                "no code region measured: the result verifies nothing",
            )
        )
    elif measured.percent < ctx.opts.min_percent:
        detail = f"region coverage {measured.percent:.2f}% < {ctx.opts.min_percent:g}%"
    findings = tuple(progress.findings)
    failed = bool(detail or findings)
    return GateResult(int(failed), detail, findings, measured.percent, measured.misses)


def _noted(verdict: GateResult, line: str, returncode: int | None = None) -> GateResult:
    """*verdict* with *line* appended to its detail, and its exit code replaced if given."""
    detail = f"{verdict.detail}\n{line}" if verdict.detail else line
    code = verdict.returncode if returncode is None else returncode
    return dataclasses.replace(verdict, detail=detail, returncode=code)


def sign_stage(
    ctx: StageContext, progress: Progress, verdict: GateResult
) -> GateResult:
    """Sign and verify a copy of each executable product, when ``--sign`` asked for it.

    Off (no setting on the options): the verdict unchanged. A failed verdict is not
    signed, a missing setting is reported and passes, and a package with no
    executable product has nothing to sign.
    """
    setting = ctx.opts.signing
    if setting is None:
        return verdict
    if verdict.returncode != 0:
        return _noted(verdict, "signing: skipped, the gate already failed")
    if isinstance(setting, NotConfigured):
        shown = render_path(setting.path, Path.home())
        return _noted(verdict, f"signing: not configured ({shown} absent)")
    if not progress.executables:
        return _noted(verdict, "signing: nothing to sign")
    return _sign_products(ctx, progress.executables, setting, verdict)


def _bin_path(ctx: StageContext) -> Path | None:
    """Where SwiftPM put the built products, asked of SwiftPM; None when it would not say."""
    where = ctx.swift(
        "bin-path", "build", "--show-bin-path", "--scratch-path", str(ctx.scratch)
    )
    lines = where.stdout.strip().splitlines()
    return Path(lines[-1].strip()) if where.returncode == 0 and lines else None


def _sign_products(
    ctx: StageContext,
    executables: Sequence[str],
    setting: Configured,
    verdict: GateResult,
) -> GateResult:
    """Copy each built executable to a temp dir, then sign and verify the copy."""
    bin_dir = _bin_path(ctx)
    if bin_dir is None:
        return _noted(verdict, "signing: swift build --show-bin-path failed", 1)
    shown = render_identity(setting.identity)
    with tempfile.TemporaryDirectory(prefix="swift_gate_sign_") as tmp:
        for name in executables:
            built = bin_dir / name
            if not built.is_file():
                return _noted(
                    verdict, f"signing: no built product {name} in the bin path", 1
                )
            copy = Path(shutil.copy2(built, Path(tmp) / name))
            failure = _sign_one(ctx, copy, setting.identity)
            if failure is not None:
                return _noted(verdict, failure[1], failure[0])
    return _noted(
        verdict, f"signing: signed and verified {', '.join(executables)} with {shown}"
    )


def _sign_one(ctx: StageContext, copy: Path, identity: str) -> tuple[int, str] | None:
    """Sign then verify *copy*; the exit code and redacted detail of a failure, or None."""
    steps = (
        ("sign", ("--force", "--sign", identity, "--timestamp=none", str(copy))),
        ("verify", ("--verify", "--strict", "--verbose=2", str(copy))),
    )
    for step, args in steps:
        try:
            done = ctx.codesign(copy.parent, *args)
        except OSError as exc:
            return 2, f"ERROR: could not run codesign: {exc}"
        if done.returncode != 0:
            output = redact(_output(done), identity, home=Path.home())
            return 1, (
                f"signing: codesign {step} failed for {copy.name} "
                f"(rc {done.returncode}):\n{output}"
            )
    return None


Stage = Callable[[StageContext, Progress], "GateResult | None"]

# The pipeline, in order: each may stop the run with a terminal result. The verdict stage
# always follows them, and the finishing stage takes that verdict and returns the result.
STAGES: Sequence[Stage] = (
    manifest_stage,
    marker_stage,
    build_stage,
    swift_test_stage,
)
VERDICT: Callable[[StageContext, Progress], GateResult] = coverage_stage
FINISH: Callable[[StageContext, Progress, GateResult], GateResult] = sign_stage


def run_stages(
    subject: Subject,
    opts: GateOptions,
    run: RunFn,
    *,
    codesign: RunFn | None = None,
) -> GateResult:
    """Gate one package through :data:`STAGES`; a timeout is exit 1 naming the stage.

    *codesign* is the seam ``codesign`` runs through; when omitted, *run* serves both,
    since the two seams share one shape. The CLI passes its own.
    """
    ctx = StageContext(
        subject,
        opts,
        run,
        scratch_for(subject.root, opts.scratch_base),
        codesign if codesign is not None else run,
    )
    progress = Progress()
    try:
        for stage in STAGES:
            result = stage(ctx, progress)
            if result is not None:
                return result
        return FINISH(ctx, progress, VERDICT(ctx, progress))
    except StageTimeout as exc:
        return GateResult(
            1,
            f"{exc.stage} stage timed out after {opts.timeout:g}s",
            tuple(progress.findings),
        )
