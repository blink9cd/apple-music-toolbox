#!/usr/bin/env python3
"""Gate a SwiftPM package: strict build, tests, and 100% region coverage at the floor.

Point ``--path`` at a directory: every
``Package.swift`` under it is one package, gated in turn through the stage pipeline in
``src/swgate_stages.py``: the manifest dump (the macOS floor and language mode 6), the
coverage markers, ``swift build --build-tests --enable-code-coverage -Xswiftc
-warnings-as-errors``, ``swift test``, and region coverage parsed from the llvm-cov export;
then, only with ``--sign``, ``codesign`` signs and verifies a copy of each executable
product with the identity read from ``--signing-config``, a file outside every checkout.
Builds go to a scratch dir under the system temp dir, never into the checkout.

Findings are reported as ``CODE path:line: message``:

======  ==============================================================
SWG001  the macOS platform is missing or is not ``macos_floor`` exactly
SWG002  tools version below 6.0, or a language mode other than 6
SWG003  a ``// coverage: ignore`` marker with no reason
SWG004  a marker that excludes no coverage region (dead)
SWG005  no code region measured: the result verifies nothing
======  ==============================================================

Exit 0 clean, or nothing to gate; 1 findings, a build or test failure, a timeout, or
coverage below ``--min-percent``; 2 could not run (no Swift toolchain or not macOS, Swift
outside any SwiftPM package, a missing ``macos_floor``, an untrusted dump or export, or,
with ``--sign``, a malformed signing setting or one inside a checkout).
Needs Python 3.11+ (stdlib ``tomllib``).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

# Sibling shared libraries, resolved from this file's own location, never the working
# directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bounded_run"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "help_formatter"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stdio_utf8"))

import bounded_run  # noqa: E402 - import follows the sys.path bootstrap above
import help_formatter  # noqa: E402 - import follows the sys.path bootstrap above
import stdio_utf8  # noqa: E402 - import follows the sys.path bootstrap above

# This tool's own private modules, one level down. `_run_swift` stays HERE, and `main`
# reads it at call time, so `patch.object(swift_gate, "_run_swift")` reaches every stage.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from swgate_config import read_config, require_floor  # noqa: E402 - same bootstrap
from swgate_model import (  # noqa: E402 - same bootstrap
    PREREQ_GROUP,
    SUBJECT_NOT_SWIFTPM,
    SUBJECT_NOTHING,
    ConfigError,
    Discovery,
    GateOptions,
    GateResult,
    ParseError,
    RunFn,
    SigningSetting,
    Subject,
)
from swgate_report import format_results  # noqa: E402 - same bootstrap
from swgate_signing import (  # noqa: E402 - same bootstrap
    checkout_roots,
    enclosing_checkout,
    read_signing_identity,
)
from swgate_stages import default_scratch_base, run_stages  # noqa: E402 - same bootstrap
from swgate_subject import discover  # noqa: E402 - same bootstrap

DEFAULT_MIN_PERCENT = 100.0
# Generous per-call bound: a cold SwiftPM build is legitimately slow. The point is that a
# wedged toolchain cannot hang the gate, since an outer deadline fires only between calls.
DEFAULT_TIMEOUT_SECONDS = 1200.0
# A git top-level or worktree query answers at once; a bound that long means git is wedged.
GIT_TIMEOUT_SECONDS = 60.0
# Kept symbolic so --help never prints the running user's home; expanded when parsed.
DEFAULT_SIGNING_CONFIG = "~/.config/swift_gate/signing.toml"
# The environment variables that redirect or bound git's repository discovery.
_GIT_DISCOVERY = frozenset(
    {"GIT_DIR", "GIT_WORK_TREE", "GIT_CEILING_DIRECTORIES", "GIT_COMMON_DIR"}
)
# git's untranslated messages, which the "not a git repository" match depends on.
_GIT_LOCALE = "C"
_HOST_PLATFORM = "darwin"


def _run_swift(  # pragma: no cover - real subprocess seam, faked in tests
    argv: Sequence[str], *, cwd: Path, timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run one ``swift`` command in *cwd*, capturing its output, bounded by *timeout*."""
    return bounded_run.run_bounded(list(argv), cwd=cwd, timeout=timeout)


def _run_codesign(  # pragma: no cover - real subprocess seam, faked in tests
    argv: Sequence[str], *, cwd: Path, timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run one ``codesign`` command in *cwd*, capturing its output, bounded by *timeout*."""
    return bounded_run.run_bounded(list(argv), cwd=cwd, timeout=timeout)


def _run_git(  # pragma: no cover - real subprocess seam, faked in tests
    argv: Sequence[str], *, cwd: Path, timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run one ``git`` query in *cwd*, capturing its output, bounded by *timeout*."""
    env = git_environment(os.environ)
    return bounded_run.run_bounded(list(argv), cwd=cwd, timeout=timeout, env=env)


def git_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """*environ* without the variables that steer git's repository discovery, in locale C.

    A gate launched from a git hook inherits ``GIT_DIR``, and a ceiling or work-tree
    variable can make git answer "not a git repository" for a checkout: either would let
    the outside-every-checkout check answer about the wrong repository, or none. ``LC_ALL=C`` keeps git's
    stderr in English, because that phrase is matched verbatim and a translated session
    would turn "no checkout" into an exit 2.
    """
    env = {key: value for key, value in environ.items() if key not in _GIT_DISCOVERY}
    env["LC_ALL"] = _GIT_LOCALE
    return env


def _expanded_path(text: str) -> Path:
    """*text* as a path with a leading ``~`` expanded, for a symbolic --help default."""
    return Path(text).expanduser()


def _signing_setting(args: argparse.Namespace) -> SigningSetting | None:
    """The signing setting when ``--sign`` is on, else None and nothing is read."""
    if not args.sign:
        return None
    roots = (
        *checkout_roots(args.path.resolve(), _run_git, timeout=GIT_TIMEOUT_SECONDS),
        *enclosing_checkout(args.signing_config, _run_git, timeout=GIT_TIMEOUT_SECONDS),
    )
    return read_signing_identity(args.signing_config, checkout_roots=roots)


def locate_swift(explicit: str | None, platform_name: str) -> str | None:
    """The ``swift`` driver to use, or None when there is none or the host is not macOS.

    An explicit value with no directory part (``--swift swift``) names a command and is
    looked up on ``PATH``; one with a directory part is a path and must be a file.
    """
    if platform_name != _HOST_PLATFORM:
        return None
    if explicit is None:
        return shutil.which("swift")
    if Path(explicit).name == explicit:
        return shutil.which(explicit)
    return explicit if Path(explicit).is_file() else None


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (named options only; defaults shown in --help)."""
    parser = argparse.ArgumentParser(
        prog=os.path.basename(sys.argv[0]),
        description="Gate SwiftPM packages: strict build, tests, 100% region coverage.",
        formatter_class=help_formatter.ReqAwareDefaultsFormatter,
        epilog=(
            f"Prerequisites: macOS with the Swift toolchain (prerequisite group "
            f"{PREREQ_GROUP!r}: Xcode or the Command Line Tools), and [tool.swift_gate] "
            "macos_floor in the nearest pyproject.toml. Order per package: swift package "
            "dump-package (SWG001 floor, SWG002 tools version and language mode 6), the "
            "// coverage: ignore: <reason> marker scan (SWG003), swift build --build-tests "
            "--enable-code-coverage -Xswiftc -warnings-as-errors, swift test --skip-build "
            "--enable-code-coverage --no-parallel (serial, so no counter loses a count), "
            "then region coverage from the llvm-cov export "
            "(SWG004 dead marker, SWG005 nothing measured), then, with --sign only, "
            "codesign --force --sign and codesign --verify --strict on a copy of each "
            "executable product (the identity is read from --signing-config, which must "
            "live outside every checkout; absent, signing reports not configured and "
            "passes). Exit codes: 0 clean or nothing "
            "to gate; 1 findings, a build or test failure, a timeout, or coverage below "
            "--min-percent; 2 could not run (no toolchain, not macOS, Swift outside any "
            "SwiftPM package, no macos_floor, or an untrusted dump or export)."
        ),
    )
    parser.add_argument(
        "--path", required=True, type=Path, help="A directory holding SwiftPM packages."
    )
    parser.add_argument(
        "--exclude",
        type=Path,
        action="append",
        default=[],
        metavar="PATH",
        help="Prune a path from discovery and coverage; repeatable. Unioned with "
        "[tool.swift_gate] exclude from the nearest pyproject.toml.",
    )
    parser.add_argument(
        "--min-percent",
        type=float,
        default=DEFAULT_MIN_PERCENT,
        help="Minimum region-coverage percentage required.",
    )
    parser.add_argument(
        "--swift",
        default=None,
        help="The swift driver: a name on PATH or a path; when omitted, swift on PATH.",
    )
    parser.add_argument(
        "--scratch-path",
        type=Path,
        default=None,
        help="Base dir for build scratch, one hashed subdir per package; when omitted, "
        "swift_gate under the system temp dir.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-call timeout in seconds; a timeout fails the gate rather than hanging it.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit the result as JSON instead of text."
    )
    parser.add_argument(
        "--sign",
        action="store_true",
        help="After a passing verdict, codesign and verify a copy of each executable "
        "product with the identity in --signing-config. Off: the setting is not read.",
    )
    parser.add_argument(
        "--signing-config",
        type=_expanded_path,
        default=DEFAULT_SIGNING_CONFIG,
        metavar="FILE",
        help='TOML holding identity = "<name>"; must live outside every checkout. '
        "Absent: signing reports not configured and passes.",
    )
    return parser


def _gate_one(subject: Subject, opts: GateOptions, run: RunFn) -> GateResult:
    """Gate one package; an untrusted dump or export, or a missing tool, is exit 2."""
    try:
        return run_stages(subject, opts, run, codesign=_run_codesign)
    except (ParseError, ConfigError) as exc:
        return GateResult(2, f"ERROR: {exc}")
    except OSError as exc:
        # Missing, not executable, or otherwise unlaunchable: the class and the OS's
        # reason only, since the exception's own text carries the absolute driver path.
        reason = exc.strerror or "no reason given"
        return GateResult(
            2, f"ERROR: could not run swift: {type(exc).__name__}: {reason}"
        )


def _refusal(discovery: Discovery) -> str | None:
    """The exit-2 message for Swift outside SwiftPM, or None when there is none."""
    if discovery.status != SUBJECT_NOT_SWIFTPM:
        return None
    shown = ", ".join(os.path.relpath(p, discovery.root) for p in discovery.strays)
    return (
        f"ERROR: swift_gate gates SwiftPM packages only: no Package.swift owns "
        f"{shown} under {discovery.root}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns 0 (clean or skipped), 1 (findings), 2 (could not run)."""
    stdio_utf8.force_utf8_streams(sys.stdout, sys.stderr)
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.path.is_dir():
        parser.error(f"--path {args.path} is not a directory")
    try:
        config = read_config(args.path)
        excludes = (*config.excludes, *(item.resolve() for item in args.exclude))
        discovery = discover(args.path, excludes)
        if discovery.status == SUBJECT_NOTHING:
            print(f"{discovery.root}: no Swift found; nothing to gate (skipped).")
            return 0
        refusal = _refusal(discovery)
        if refusal is not None:
            print(refusal, file=sys.stderr)
            return 2
        floor = require_floor(config)
        signing = _signing_setting(args)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return _gate_all(args, discovery, excludes, floor, signing)


def _gate_all(
    args: argparse.Namespace,
    discovery: Discovery,
    excludes: tuple[Path, ...],
    floor: str,
    signing: SigningSetting | None,
) -> int:
    """Locate the toolchain, gate every package in turn, and report."""
    swift = locate_swift(args.swift, sys.platform)
    if swift is None:
        print(
            f"ERROR: no Swift toolchain on this host (needs macOS and prerequisite group "
            f"{PREREQ_GROUP!r}; host {sys.platform}, --swift {args.swift})",
            file=sys.stderr,
        )
        return 2
    opts = GateOptions(
        swift=swift,
        macos_floor=floor,
        scratch_base=(args.scratch_path or default_scratch_base()).resolve(),
        min_percent=args.min_percent,
        timeout=args.timeout_seconds,
        signing=signing,
    )
    results = [
        (subject, _gate_one(subject, opts, _run_swift))
        for subject in (Subject(p, excludes) for p in discovery.packages)
    ]
    print(format_results(results, args.min_percent, as_json=args.json))
    return max(result.returncode for _, result in results)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
