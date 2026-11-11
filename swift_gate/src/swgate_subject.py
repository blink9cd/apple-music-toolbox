"""Resolve what ``--path`` holds: its SwiftPM packages, and any Swift no package owns.

Private to ``swift_gate``. Each ``Package.swift`` is one package, gated in turn. Swift the
gate cannot evaluate, because no SwiftPM manifest owns it (loose ``.swift`` files, or an
``.xcodeproj`` / ``.xcworkspace``), is a stray: this is a SwiftPM-only gate, so a stray
is exit 2 rather than a silent pass over code nobody built.

Entry point assumptions
-----------------------
Reads the filesystem (one tree walk) and nothing else. Needs the ``venv_prune`` sibling
library, resolved from this file's own location.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "venv_prune"))

import venv_prune  # noqa: E402 - import follows the sys.path bootstrap above

from swgate_model import (  # noqa: E402 - same
    SUBJECT_NOTHING,
    SUBJECT_NOT_SWIFTPM,
    SUBJECT_READY,
    Discovery,
)

MANIFEST = "Package.swift"
_SWIFT_SUFFIX = ".swift"
_XCODE_SUFFIXES = (".xcodeproj", ".xcworkspace")

# Dirs never walked: SwiftPM and Xcode build output, vcs noise, and the caches every gate
# prunes. ``.build`` holds checked-out dependencies, whose manifests are not subjects.
_PRUNED_DIRS: frozenset[str] = frozenset(
    {
        ".build",
        ".swiftpm",
        "DerivedData",
        ".git",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
    }
)


def is_excluded(path: Path, excludes: Sequence[Path]) -> bool:
    """True when *path* is, or lies under, one of *excludes*."""
    return any(path == ex or ex in path.parents for ex in excludes)


def _walk(root: Path, excludes: Sequence[Path]) -> tuple[list[Path], list[Path]]:
    """Every package dir, and every Swift file or Xcode project, under *root*."""
    packages: list[Path] = []
    swift: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        # An Xcode project is a stray unless excluded: the exclude filter must hold here
        # too, since the dirnames pruning below never reports an Xcode dir on its own.
        swift.extend(
            base / name
            for name in dirnames
            if name.endswith(_XCODE_SUFFIXES) and not is_excluded(base / name, excludes)
        )
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in _PRUNED_DIRS
            and not name.endswith(_XCODE_SUFFIXES)
            and not venv_prune.is_virtualenv(base / name)
            and not is_excluded(base / name, excludes)
        )
        if MANIFEST in filenames:
            packages.append(base)
        swift.extend(
            base / name
            for name in filenames
            if name.endswith(_SWIFT_SUFFIX) and not is_excluded(base / name, excludes)
        )
    return packages, swift


def discover(path: Path, excludes: Sequence[Path] = ()) -> Discovery:
    """Classify *path*: nothing to gate, Swift outside SwiftPM, or packages ready."""
    root = path.resolve()
    if is_excluded(root, excludes):
        return Discovery(SUBJECT_NOTHING, root)
    packages, swift = _walk(root, excludes)
    strays = tuple(
        sorted(
            f
            for f in swift
            if not any(p == f.parent or p in f.parents for p in packages)
        )
    )
    if strays:
        return Discovery(SUBJECT_NOT_SWIFTPM, root, tuple(sorted(packages)), strays)
    if not packages:
        return Discovery(SUBJECT_NOTHING, root)
    return Discovery(SUBJECT_READY, root, tuple(sorted(packages)))


def package_sources(package: Path, excludes: Sequence[Path]) -> tuple[Path, ...]:
    """The package's own non-test sources: every ``.swift`` under its ``Sources/``."""
    sources = package / "Sources"
    return tuple(
        sorted(
            file
            for file in sources.rglob(f"*{_SWIFT_SUFFIX}")
            if not is_excluded(file, excludes)
        )
    )
