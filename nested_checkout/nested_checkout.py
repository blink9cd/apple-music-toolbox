#!/usr/bin/env python3
"""Answer "is this directory the top of another checkout?" from git's own ``.git`` marker.

Why this exists
---------------
Some tools keep linked worktrees inside the checkout they belong to; one such layout is
the example throughout this module, where a session tool keeps them all in one folder.
Session worktrees live INSIDE the primary checkout (``.claude/worktrees/<name>/``), each
a full copy of the tree. A walker rooted at the primary checkout that descends into one
gates, counts, lints or (for a cleaner) deletes another session's files as if they were
its own. Most walkers were safe only by accident: ``.gitignore`` lists that one location
and git happened to answer, or the walker pruned every dot-directory. A name list or an
ignore rule is a proxy; the authoritative signal is the entry git itself uses to find a
checkout's top, a ``.git`` directory (a clone) or a ``.git`` FILE (a linked worktree or
a submodule). Keying on it holds wherever the checkout sits and whether or not git can
be asked: state is read from its authoritative source, not a cached or side-channel
proxy.

The root exemption
------------------
A walk's own root is never tested: it is normally a checkout too, and a tool pointed AT
a worktree must walk that worktree. ``os.walk``'s ``dirnames`` prune judges only
children, so it exempts the root for free; :func:`is_under_nested_checkout` excludes it
explicitly. ``nested_checkout.md`` records the failure that inverting this produces.

Entry point assumptions
-----------------------
A library with no CLI. Both functions are pure queries: they read paths and write
nothing. A missing path reads as NOT a checkout, because ``Path.exists`` collapses
"no such entry" to ``False``.
"""

from __future__ import annotations

from itertools import takewhile
from pathlib import Path

#: The entry marking a directory as the top of a checkout: a directory in a clone, a FILE
#: in a linked worktree or a submodule.
MARKER = ".git"


def is_nested_checkout(directory: Path) -> bool:
    """True when *directory* holds a ``.git`` entry, a file or a directory.

    Call it on a walk's CHILDREN only, never on the walk's root (see the module
    docstring). Returns ``False``, rather than raising, for a missing path.
    """
    return (directory / MARKER).exists()


def is_under_nested_checkout(path: Path, root: Path) -> bool:
    """True when a directory strictly below *root*, at or above *path*'s parent, is a checkout.

    The ancestor form of :func:`is_nested_checkout`, for walkers that glob first and
    filter after and so have no prune step. *root* itself is never tested, and a *path*
    not strictly below *root* is never in a nested checkout: nothing at or above *root*
    is ever examined, so the answer cannot depend on directories the caller never named.

    Membership is lexical: *path* and *root* must be spelled alike (both resolved, or
    both unresolved; both absolute, or both relative), otherwise the answer is False and
    the checkout is walked. A checkout's own top, passed as *path*, is not under one;
    a caller filtering directory hits rejects it with :func:`is_nested_checkout`.
    """
    if root not in path.parents:
        return False
    below_root = takewhile(lambda parent: parent != root, path.parents)
    return any(is_nested_checkout(parent) for parent in below_root)
