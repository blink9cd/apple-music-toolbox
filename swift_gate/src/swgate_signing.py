"""The ``--sign`` stage's inputs: the signing setting, where it may live, and its rendering.

Private to ``swift_gate``. The signing identity is a local setting read from a file outside
every checkout and never committed; an absent file is "not configured" and the stage
passes. The file holds one key::

    identity = "<the codesign identity>"

Three rules live here:

* **Where the file may live.** :func:`checkout_roots` asks ``git`` for the target's top
  level and every worktree it lists, and :func:`enclosing_checkout` asks ``git`` for the
  repository holding the setting path itself, whatever repository that is.
  :func:`read_signing_identity` refuses a setting path at or under any of them, absent or
  not, since a file created there later would be one ``git add`` away from a commit. A
  root is matched lexically and by file identity, so a case variant of a checkout path on
  a case-insensitive volume is the same directory. Only "not a git repository" means no
  checkout: any other ``git`` failure is exit 2, never a skipped check.
* **What it must hold.** A non-empty string ``identity``; anything else is exit 2.
* **How it is shown.** Never in full: :func:`render_identity` gives the first word plus an
  ellipsis, or a fixed placeholder for a one-word identity (a SHA-1, a team ID), and
  :func:`redact` scrubs every certificate common name and parenthesized team ID from
  ``codesign``'s own output, which echoes every matching certificate when an identity is
  ambiguous. :func:`render_path` shows a path under the home as ``~/…`` in every message.

Entry point assumptions
-----------------------
Reads one file through an injectable seam, and runs ``git`` only through the injected
:class:`~swgate_model.RunFn`. Signing itself is the stage's (``swgate_stages``).
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

from swgate_model import (
    Configured,
    NotConfigured,
    RunFn,
    SigningConfigError,
    SigningSetting,
)

__all__ = [
    "Configured",
    "NotConfigured",
    "SigningConfigError",
    "SigningSetting",
    "checkout_roots",
    "enclosing_checkout",
    "read_signing_identity",
    "redact",
    "render_identity",
    "render_path",
]

IDENTITY_KEY = "identity"
_ELLIPSIS = "…"
_PLACEHOLDER = "<identity>"  # shown for a one-word identity, which has no safe prefix
_HOME = "~"
_WORKTREE_PREFIX = "worktree "  # a `git worktree list --porcelain` record's first line
_NOT_A_REPO = "not a git repository"  # git's stderr when there is no repository at all
# An Apple team ID: ten upper-case letters or digits, parenthesized after a common name.
_TEAM_ID = r"[A-Z0-9]{10}"
_ANY_TEAM_ID = re.compile(rf"\({_TEAM_ID}\)")
# The configured identity's own team ID: the whole identity, or its trailing "(ID)".
_OWN_TEAM_ID = re.compile(rf"^({_TEAM_ID})$|\(({_TEAM_ID})\)\s*$")
# A certificate common name, "<Type>: <Name> (<ID>)", as codesign echoes it. The name is
# free text (a parenthesized company, a colon, a quote), so it runs lazily to the nearest
# parenthesized team ID on the line rather than stopping at the first such character.
_COMMON_NAME = re.compile(
    rf"(?P<kind>[0-9A-Za-z][0-9A-Za-z ]*): [^\n]+? \({_TEAM_ID}\)"
)
_REFUSAL = "the signing identity must live outside every checkout"

ReadTextFn = Callable[[Path], str]
FileId = tuple[int, int]


def _read_text(path: Path) -> str:
    """Read *path* as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def render_identity(identity: str) -> str:
    """The identity as shown anywhere: its first word, or a placeholder, plus an ellipsis."""
    words = identity.split()
    return f"{words[0] if len(words) > 1 else _PLACEHOLDER}{_ELLIPSIS}"


def render_path(path: Path, home: Path) -> str:
    """*path* as shown in a message: under *home* as ``~/…``, otherwise as given."""
    if path == home:
        return _HOME
    if path.is_relative_to(home):
        return f"{_HOME}/{path.relative_to(home).as_posix()}"
    return str(path)


def _tilde_text(text: str, home: Path) -> str:
    """*text* with every path under *home* shown from ``~``, as :func:`render_path` does."""
    return text.replace(f"{home}{os.sep}", f"{_HOME}/")


def redact(text: str, identity: str, *, home: Path | None = None) -> str:
    """*text* with every common name, team ID and the identity scrubbed.

    A common name keeps only its type (``Apple Development: …``) and any parenthesized team
    ID becomes ``(…)``, whatever the identity, because codesign echoes every certificate an
    ambiguous identity matched. The identity itself is replaced by its rendering only when
    that shortens it, so the ad-hoc ``-`` leaves codesign's own flags intact. With *home*,
    paths under it are shown from ``~``.
    """
    scrubbed = _COMMON_NAME.sub(lambda match: f"{match['kind']}: {_ELLIPSIS}", text)
    scrubbed = _ANY_TEAM_ID.sub(f"({_ELLIPSIS})", scrubbed)
    shown = render_identity(identity)
    if len(shown) < len(identity):
        scrubbed = scrubbed.replace(identity, shown)
    own = _OWN_TEAM_ID.search(identity)
    if own is not None:
        scrubbed = scrubbed.replace(own.group(1) or own.group(2), _ELLIPSIS)
    return scrubbed if home is None else _tilde_text(scrubbed, home)


def _git(
    run: RunFn, argv: Sequence[str], cwd: Path, timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run one git query; a git that cannot run or times out is a SigningConfigError.

    The exception's own text quotes the argv (``-C <dir>``) or the executable's path, so
    it is shown with the home as ``~``, so no message carries the home's layout.
    """
    try:
        return run(argv, cwd=cwd, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SigningConfigError(
            f"could not run git to locate the checkout for {_REFUSAL}: "
            f"{_tilde_text(str(exc), Path.home())}"
        ) from exc


def _toplevel(cwd: Path, run: RunFn, timeout: float) -> Path | None:
    """The top level of the repository holding *cwd*, or None when there is none.

    Only git's "not a git repository" is None. Any other failure (dubious ownership, a
    corrupt or unreadable ``.git``) raises, so the outside-every-checkout check cannot
    fail open.
    """
    argv = ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"]
    done = _git(run, argv, cwd, timeout)
    if done.returncode == 0:
        return Path(done.stdout.strip())
    if _NOT_A_REPO in done.stderr:
        return None
    home = Path.home()
    raise SigningConfigError(
        f"git rev-parse failed (rc {done.returncode}) in {render_path(cwd, home)}, so "
        f"{_REFUSAL} cannot be checked: {_tilde_text(done.stderr.strip(), home)}"
    )


def checkout_roots(target: Path, run: RunFn, *, timeout: float) -> tuple[Path, ...]:
    """The target's git top level and every worktree of that repository, resolved.

    Outside any git repository there is no checkout, so the answer is ``()``. A ``git``
    that cannot run, times out, fails otherwise, or cannot list the worktrees raises
    :class:`SigningConfigError`: the outside-every-checkout check cannot be skipped by a
    broken tool.
    """
    top = _toplevel(target, run, timeout)
    if top is None:
        return ()
    listed = _git(run, ["git", "worktree", "list", "--porcelain"], target, timeout)
    if listed.returncode != 0:
        raise SigningConfigError(
            f"git worktree list failed (rc {listed.returncode}), so {_REFUSAL} "
            f"cannot be checked: {_tilde_text(listed.stderr.strip(), Path.home())}"
        )
    roots = [top]
    roots.extend(
        Path(line[len(_WORKTREE_PREFIX) :])
        for line in listed.stdout.splitlines()
        if line.startswith(_WORKTREE_PREFIX)
    )
    return tuple(dict.fromkeys(root.resolve() for root in roots))


def enclosing_checkout(path: Path, run: RunFn, *, timeout: float) -> tuple[Path, ...]:
    """The top level of any repository holding the setting *path*, as ``()`` or one root.

    Asked from the path's nearest existing directory, since git needs one to start from,
    and git answers from the real path, case and links canonicalized, for any repository:
    the target's, a nested one, or an unrelated one such as a dotfiles checkout.
    """
    resolved = path.resolve()
    # The filesystem root always exists, so the search always ends on a directory.
    start = next(each for each in (resolved, *resolved.parents) if each.is_dir())
    top = _toplevel(start, run, timeout)
    return () if top is None else (top.resolve(),)


def _file_id(path: Path) -> FileId | None:
    """*path*'s device and inode, or None when it cannot be stat'd."""
    try:
        status = path.stat()
    except OSError:
        return None
    return status.st_dev, status.st_ino


def _refuse_inside(path: Path, roots: Sequence[Path]) -> Path:
    """*path* resolved, or :class:`SigningConfigError` when it is at or under any root.

    A root matches lexically, or by file identity against any existing ancestor, which is
    what catches a case variant on a case-insensitive volume: ``resolve`` keeps the given
    spelling, so ``Workspace`` and ``workspace`` differ lexically yet are one directory.
    """
    resolved = path.resolve()
    ancestors = {
        found
        for each in (resolved, *resolved.parents)
        if (found := _file_id(each)) is not None
    }
    for root in roots:
        root_id = _file_id(root)
        if resolved.is_relative_to(root.resolve()) or root_id in ancestors:
            home = Path.home()
            raise SigningConfigError(
                f"{_REFUSAL}: {render_path(path, home)} is inside "
                f"{render_path(root, home)}"
            )
    return resolved


def read_signing_identity(
    path: Path,
    *,
    checkout_roots: Sequence[Path],
    read_text: ReadTextFn = _read_text,
) -> SigningSetting:
    """The signing setting at *path*: :class:`Configured`, or :class:`NotConfigured`.

    Raises :class:`SigningConfigError` for a path inside any of *checkout_roots*, an
    unreadable or non-TOML file, or a missing, empty or non-string ``identity``. The file
    read is the resolved path the check accepted, not the one given. No message quotes
    the file's content, which is where the team ID is.
    """
    resolved = _refuse_inside(path, checkout_roots)
    shown = render_path(path, Path.home())
    try:
        text = read_text(resolved)
    except FileNotFoundError:
        return NotConfigured(path)
    except (OSError, UnicodeDecodeError) as exc:
        raise SigningConfigError(
            f"cannot read the signing setting {shown}: {type(exc).__name__}"
        ) from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SigningConfigError(
            f"the signing setting {shown} is not TOML: {exc}"
        ) from exc
    identity = data.get(IDENTITY_KEY)
    if not isinstance(identity, str) or not identity.strip():
        raise SigningConfigError(
            f'the signing setting {shown} needs {IDENTITY_KEY} = "<name>", '
            "a non-empty string"
        )
    return Configured(identity.strip())
