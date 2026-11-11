"""The vocabulary every layer of ``swift_gate`` speaks: its records and its exit classes.

Private to ``swift_gate`` -- the ``src/`` dir ``tool_subdirs`` defines, so nothing outside
this tool folder may import it. The name carries the tool's prefix because a bare
``model`` in a ``src/`` dir collides with the next tool to want that obvious name.

Everything here is here because more than one layer speaks it:

* the exception classes, the tool's **exit-2 vocabulary**: each means "this could not be
  evaluated", as distinct from a finding, which means "it was evaluated and it failed";
* the frozen records the layers hand to each other (the signing setting among them, which
  the CLI reads and the sign stage acts on), and the ``SUBJECT_*`` states that tell
  "nothing to gate" apart from a pass and from "could not run";
* the literals two layers must agree on: the coverage marker the scan and the report both
  name, and the prerequisite group every exit-2 message points at;
* the injected process seam's type.

Entry point assumptions
-----------------------
Pure: no filesystem, no subprocess, no stream, and no ``sys.path`` bootstrap.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# The prerequisite group that provides the toolchain; every exit-2 message about a
# missing or unusable toolchain names it, so the fix is one lookup away.
PREREQ_GROUP = "swift"

# The coverage marker. Spoken by the marker scan and by the documentation.
MARKER_TEXT = "coverage: ignore"

# Subject states. Absence of Swift is "not applicable" (exit 0); Swift this gate cannot
# evaluate, because no SwiftPM manifest owns it, is a hard error (exit 2).
SUBJECT_NOTHING = "nothing"
SUBJECT_NOT_SWIFTPM = "not-swiftpm"
SUBJECT_READY = "ready"


class ConfigError(Exception):
    """Exit-2-class failure: the ``[tool.swift_gate]`` config is missing or untrusted."""


class ParseError(Exception):
    """Exit-2-class failure: a manifest dump or coverage export could not be trusted."""


class SigningConfigError(ConfigError):
    """Exit-2-class failure: the signing setting is malformed or lives inside a checkout."""


class RunFn(Protocol):
    """The injected process seam: run *argv* in *cwd*, bounded by *timeout*."""

    def __call__(
        self, argv: Sequence[str], *, cwd: Path, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        """Run one command; raise ``subprocess.TimeoutExpired`` past *timeout*."""
        ...  # pragma: no cover - a Protocol body is never executed


@dataclass(frozen=True)
class Finding:
    """One gate finding: its code, where it is, and what is wrong."""

    code: str
    path: str
    line: int  # 0 for a file-level or package-level finding
    message: str


@dataclass(frozen=True)
class Config:
    """Resolved ``[tool.swift_gate]`` settings from the nearest pyproject declaring it."""

    excludes: tuple[Path, ...] = ()
    macos_floor: str | None = None


@dataclass(frozen=True)
class Discovery:
    """What ``--path`` holds: its SwiftPM packages, and any Swift no package owns."""

    status: str
    root: Path
    packages: tuple[Path, ...] = ()
    strays: tuple[Path, ...] = ()


@dataclass(frozen=True)
class Subject:
    """One SwiftPM package to gate: the directory holding its ``Package.swift``."""

    root: Path
    excludes: tuple[Path, ...] = ()


@dataclass(frozen=True)
class Configured:
    """The signing setting names an identity. Never rendered in full (it holds a team ID)."""

    identity: str


@dataclass(frozen=True)
class NotConfigured:
    """No signing setting exists at *path*: the sign stage reports it and passes."""

    path: Path


# What the setting read gives the sign stage; None on GateOptions means --sign is off.
SigningSetting = Configured | NotConfigured


@dataclass(frozen=True)
class GateOptions:
    """The inputs that hold for every package one run gates."""

    swift: str
    macos_floor: str
    scratch_base: Path
    min_percent: float = 100.0
    timeout: float = 1200.0
    signing: SigningSetting | None = None


@dataclass(frozen=True)
class GateResult:
    """Outcome of gating one package."""

    returncode: int
    detail: str = ""
    findings: tuple[Finding, ...] = ()
    percent: float | None = None
    misses: tuple[str, ...] = ()
