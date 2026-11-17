#!/usr/bin/env python3
"""Unit tests for nested_checkout, bare-runnable (python test_nested_checkout.py).

The predicate is a fact about the filesystem, so these build real directory trees under
a temp dir rather than faking a stat seam: a faked stat would test the fake. Every
layout is a sandbox; no test walks or reads the real checkout. Every branch is
reachable that way, so 100% branch coverage needs no pragma.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# The library under test sits beside this file; import it by location so the test runs
# from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import nested_checkout  # noqa: E402 - import follows the sys.path bootstrap above

# What a linked worktree's or a submodule's .git FILE holds: a pointer to the real git dir.
_GITDIR_POINTER = "gitdir: ../.git/worktrees/x\n"


def _write(path: Path, text: str = "") -> Path:
    """Create *path* (and its parents) holding *text*, byte-identical on every host."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" keeps the fixture byte-identical on every host (RL004).
    path.write_text(text, encoding="utf-8", newline="")
    return path


class _Sandbox(unittest.TestCase):
    """A fresh temporary root per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def make_worktree(self, relative: str) -> Path:
        """A linked worktree at *relative*: a directory whose ``.git`` is a FILE."""
        top = self.root / relative
        _write(top / nested_checkout.MARKER, _GITDIR_POINTER)
        return top

    def make_clone(self, relative: str) -> Path:
        """A clone at *relative*: a directory whose ``.git`` is a DIRECTORY."""
        top = self.root / relative
        (top / nested_checkout.MARKER).mkdir(parents=True)
        return top


class MarkerTest(unittest.TestCase):
    """The marker is the one entry git itself uses to find a checkout's top."""

    def test_marker_is_dot_git(self) -> None:
        self.assertEqual(nested_checkout.MARKER, ".git")


class IsNestedCheckoutTest(_Sandbox):
    """One directory, judged by whether it holds a ``.git`` entry of either kind."""

    def test_a_git_file_marks_a_linked_worktree(self) -> None:
        worktree = self.make_worktree(".claude/worktrees/agent-x")
        self.assertTrue(nested_checkout.is_nested_checkout(worktree))

    def test_a_git_directory_marks_a_clone(self) -> None:
        clone = self.make_clone("vendor/other")
        self.assertTrue(nested_checkout.is_nested_checkout(clone))

    def test_a_plain_directory_is_not_a_checkout(self) -> None:
        plain = self.root / "utilities"
        plain.mkdir()
        self.assertFalse(nested_checkout.is_nested_checkout(plain))

    def test_a_missing_path_is_not_a_checkout(self) -> None:
        """A dir removed between listing and checking must read False, not raise."""
        self.assertFalse(nested_checkout.is_nested_checkout(self.root / "gone"))

    def test_a_subdirectory_of_a_checkout_is_not_itself_one(self) -> None:
        """The predicate answers about one directory; a walk prunes at the top."""
        inner = self.make_worktree("wt") / "utilities"
        inner.mkdir()
        self.assertFalse(nested_checkout.is_nested_checkout(inner))


class IsUnderNestedCheckoutTest(_Sandbox):
    """The ancestor form, for walkers that glob first and filter after."""

    def test_a_file_inside_a_nested_worktree(self) -> None:
        top = self.make_worktree(".claude/worktrees/agent-x")
        buried = _write(top / "utilities" / "tool" / "tool.py")
        self.assertTrue(nested_checkout.is_under_nested_checkout(buried, self.root))

    def test_a_file_directly_inside_a_nested_clone(self) -> None:
        shallow = _write(self.make_clone("vendor/other") / "x.py")
        self.assertTrue(nested_checkout.is_under_nested_checkout(shallow, self.root))

    def test_a_file_beside_a_nested_checkout(self) -> None:
        self.make_worktree(".claude/worktrees/agent-x")
        beside = _write(self.root / ".claude" / "settings.json")
        self.assertFalse(nested_checkout.is_under_nested_checkout(beside, self.root))

    def test_a_nested_checkout_two_levels_deep(self) -> None:
        """A checkout inside a checkout below root: the path is under one either way."""
        outer = self.make_worktree("outer")
        inner = self.make_clone("outer/vendor/inner")
        target = _write(inner / "src" / "x.py")
        self.assertTrue(nested_checkout.is_under_nested_checkout(target, self.root))
        self.assertTrue(nested_checkout.is_under_nested_checkout(target, outer))

    def test_the_root_itself_is_never_tested(self) -> None:
        """A tool pointed AT a worktree must walk it: root's own ``.git`` is ignored."""
        _write(self.root / nested_checkout.MARKER, _GITDIR_POINTER)
        target = _write(self.root / "utilities" / "tool" / "tool.py")
        self.assertFalse(nested_checkout.is_under_nested_checkout(target, self.root))

    def test_a_checkout_root_still_prunes_its_own_nested_checkouts(self) -> None:
        """Exempting root does not exempt what is below it."""
        (self.root / nested_checkout.MARKER).mkdir()
        top = self.make_worktree(".claude/worktrees/agent-x")
        buried = _write(top / "x.py")
        self.assertTrue(nested_checkout.is_under_nested_checkout(buried, self.root))

    def test_the_path_itself_is_not_tested(self) -> None:
        """Only directories at or above the path's parent count; a checkout's own top,
        passed as the path, is not "under" one. A glob-then-filter caller rejects such a
        directory hit with ``is_nested_checkout`` itself (see the companion doc)."""
        top = self.make_worktree("wt")
        self.assertFalse(nested_checkout.is_under_nested_checkout(top, self.root))


class OutsideRootTest(_Sandbox):
    """Nothing at or above *root* is examined, even when a ``.git`` sits up there.

    The sandbox itself holds a ``.git`` and the caller's root is a folder inside it, so
    a walk that strayed above root would find that marker and answer True.
    """

    def setUp(self) -> None:
        super().setUp()
        (self.root / nested_checkout.MARKER).mkdir()
        self.inner_root = self.root / "sub"
        self.inner_root.mkdir()

    def test_a_path_equal_to_root_is_not_under_a_checkout_above_root(self) -> None:
        self.assertFalse(
            nested_checkout.is_under_nested_checkout(self.inner_root, self.inner_root)
        )

    def test_a_path_outside_root_ignores_a_checkout_above_it(self) -> None:
        stray = _write(self.root / "other" / "x.py")
        self.assertFalse(
            nested_checkout.is_under_nested_checkout(stray, self.inner_root)
        )


if __name__ == "__main__":
    unittest.main()
