"""Install helpers for a signed app: private folders, the bundle swap, the worktree check.

`make_private` makes every folder an app keeps to itself: mode 0700, refusing a symbolic
link planted where the folder should be, before the call or swapped in after the folder
is made, a folder of another user, and a folder that cannot be read. Every parent it has
to make is held to the same rules: each level is made and opened relative to the level
above it without following a link, and checked and chmodded through its own descriptor,
so the folder checked is the folder changed and a chmod never lands on a link's target.
A parent that already exists is used as found, so a caller that needs one judged makes
each level private in turn.

`swap_in` replaces an installed bundle with a staged one in one atomic step: macOS's
`renamex_np` with `RENAME_SWAP` exchanges the two paths, so a bundle is at the installed
path at every moment, and the old one ends at the staged path for the caller to remove
with its staging folder. A first install is one plain rename. `same_entry` tells two
paths apart by the entry they name, never by their spelling, so a case-insensitive
volume cannot make one bundle look like two. `sweep_stale_work` removes
the staging folders (and the `.old-<pid>-` folders the earlier two-step swap left) of
installs whose process is gone, which no later install would otherwise remove, since each
removes only its own. `refuse_linked_worktree` refuses an entry script in a linked git
worktree: such a checkout is often removed once its work is done, and an agent should run
from the repository's main checkout, which stays.

A refusal is `app_bundle.Refused` (exit 2), with a message that is safe to print.

Entry point assumptions: imported by an app's modules, with this library's ``src/`` and
the shared libraries on `sys.path`.
"""

from __future__ import annotations

import contextlib
import ctypes
import errno
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final, TextIO

from app_bundle import GIT_TIMEOUT_S, Refused
from app_host import Host

if sys.platform == "win32":
    # A private folder is opened with POSIX flags and checked against the POSIX user id;
    # this arm also lets a win32 type-check pass treat those names as unreachable.
    raise ImportError("a signed app needs macOS")  # pragma: only-on win32

#: The mode of every folder an app keeps to itself: its user's alone.
PRIVATE_MODE: Final = 0o700
#: The errors a no-follow folder open fails with when a symbolic link is at the path.
_LINK_OPEN_ERRORS: Final = frozenset({errno.ELOOP, errno.ENOTDIR})
#: What `rev-parse` is asked, one answer line each, in this order.
_DIR_QUESTIONS: Final = ("--git-dir", "--git-common-dir")
#: git's own words for a folder outside every repository.
_NOT_A_REPOSITORY: Final = (
    "not a git repository (or any of the parent directories)",
    "not a git repository (or any parent up to mount point",
)
#: `renamex_np`'s flag that exchanges its two paths in one step (macOS's <stdio.h>).
RENAME_SWAP: Final = 0x00000002
#: An install's work folder named by its pid: `.staging-<pid>`, or `.old-<pid>-<app>`,
#: which the two-rename swap before `RENAME_SWAP` left. ASCII digits only.
_WORK_FOLDER: Final = re.compile(r"\.(?:staging-([0-9]+)|old-([0-9]+)-.+)", re.ASCII)


def make_private(folder: Path) -> None:
    """Create `folder` and every missing parent, each level it makes and `folder` mode 0700.

    The levels that already exist above the first missing one are the user's own (the
    home folder, `Library`) and are used as found, a link among them included: only the
    user can write there, so such a link is the user's own. From the deepest of them
    down, each level is made and opened relative to the descriptor of the one above it,
    without following a link, so no level is reached through a link and a link swapped in
    at any level made here, or at `folder` itself, is refused, never followed.

    Each such level is refused when it belongs to another user, or cannot be read (one of
    ours left at mode 000 or 0300, say): the open needs read permission, so such a folder
    is named and refused rather than chmodded back. Every check and the chmod go through
    the level's own descriptor. Any other file-system failure (a file at the path) is the
    OSError itself.
    """
    base, names = _missing_levels(folder)
    descriptor = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
    for name in names:
        base = base / name
        # Each step closes the descriptor it is handed, whether it succeeds or raises.
        descriptor = _private_level(descriptor, base)
    os.close(descriptor)


def _missing_levels(folder: Path) -> tuple[Path, list[str]]:
    """The deepest existing parent of `folder`, and the names below it down to `folder`.

    `folder` itself is always among the names, so an existing one is still judged.
    """
    base = folder.parent
    names = [folder.name]
    while not os.path.lexists(base):
        names.insert(0, base.name)
        base = base.parent
    return base, names


def _private_level(parent: int, level: Path) -> int:
    """Make `level` in the open folder `parent`, judge it, and return it open.

    `parent` is closed either way: the walk holds one descriptor at a time.
    """
    try:
        # An existing entry is judged by the open below, never by its name.
        with contextlib.suppress(FileExistsError):
            os.mkdir(level.name, PRIVATE_MODE, dir_fd=parent)
        descriptor = _open_folder_unfollowed(level, parent)
    finally:
        os.close(parent)
    try:
        if os.fstat(descriptor).st_uid != os.getuid():
            raise Refused(f"{level} belongs to another user; refusing to use it")
        # The mode mkdir was given is masked by the umask; this sets it exactly.
        os.fchmod(descriptor, PRIVATE_MODE)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _open_folder_unfollowed(folder: Path, parent: int) -> int:
    """`folder` opened in `parent` without following a link.

    Refused for a link at its path or a folder it cannot read.
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
    try:
        return os.open(folder.name, flags, dir_fd=parent)
    except PermissionError:
        # O_RDONLY needs read permission on the folder itself; without it there is no
        # descriptor to check and chmod through, so it is refused, never chmodded by name.
        raise Refused(
            f"{folder} cannot be read; refusing to use it as a private folder"
        ) from None
    except OSError as error:
        # A link at the path fails the open: macOS reports ENOTDIR when O_DIRECTORY is
        # also set, Linux ELOOP. The lstat only names the refusal, as a file at the path
        # fails the same way; nothing is done to the entry, so a swap here changes nothing.
        if error.errno in _LINK_OPEN_ERRORS and folder.is_symlink():
            raise Refused(
                f"{folder} is a symbolic link; refusing to use it as a private folder"
            ) from None
        raise


def exchange_paths(first: Path, second: Path) -> None:
    """Exchange `first` and `second` in one atomic step, with `renamex_np(RENAME_SWAP)`.

    Both must exist on one volume. A failure is the OSError the C call's errno names,
    with nothing moved.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    call = libc.renamex_np
    # Declared, so ctypes checks each argument instead of guessing its C type.
    call.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    call.restype = ctypes.c_int
    status = call(os.fsencode(first), os.fsencode(second), RENAME_SWAP)
    if status != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(first), None, str(second))


def same_entry(first: Path, second: Path) -> bool:
    """Whether `first` and `second` name one directory entry, by device and inode.

    Neither is followed, so a link to an entry is not that entry. A volume that ignores
    case or Unicode normalization answers two spellings with one entry; comparing the
    paths' text would call them two. A path that cannot be examined is never the same.
    """
    try:
        one, other = first.lstat(), second.lstat()
    except OSError:
        return False
    return (one.st_dev, one.st_ino) == (other.st_dev, other.st_ino)


def _give_exact_name(
    final: Path, same: Callable[[Path, Path], bool] = same_entry
) -> None:
    """Rename the entry at `final` to `final`'s exact spelling, when it is spelled otherwise.

    An exchange keeps each entry's name, so on a volume that ignores case an upgrade to a
    name differing only in case leaves the new bundle under the OLD spelling. Each other
    entry beside `final` that `same` says is `final` takes its name; renaming an entry
    onto itself, differing only in spelling, is one atomic rename.
    """
    for entry in sorted(final.parent.iterdir()):
        if entry.name != final.name and same(entry, final):
            entry.rename(final)


def swap_in(
    staged: Path,
    final: Path,
    *,
    exchange: Callable[[Path, Path], None] = exchange_paths,
    same_entry: Callable[[Path, Path], bool] = same_entry,
) -> None:
    """Put the bundle at `staged` in as `final`, in one atomic step.

    With a bundle already at `final` the two are exchanged, so the OLD bundle is at
    `staged` afterward and the caller removes it with its staging folder; with none,
    `staged` is renamed in. `final` is never renamed away, so no moment, and no process
    killed at any moment, leaves the path empty. After an exchange the entry takes
    `final`'s exact spelling, in case the old one was spelled otherwise. A failure moves
    nothing, so it simply propagates. `exchange` and `same_entry` are the seams a test
    replaces.
    """
    if final.exists():
        exchange(staged, final)
        _give_exact_name(final, same_entry)
    else:
        staged.rename(final)


def pid_is_alive(pid: int) -> bool:
    """Whether a process with `pid` exists, by `kill(pid, 0)`, which sends nothing.

    Only "no such process" reads as dead. Another user's process (a permission error),
    a pid too large to ask about, and any other failure read as alive: a folder is kept
    unless the process that made it is certainly gone.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (OSError, OverflowError):
        return True
    return True


def _work_folder_pid(name: str) -> int | None:
    """The positive pid an install's work folder `name` carries, or None for any other."""
    match = _WORK_FOLDER.fullmatch(name)
    if match is None:
        return None
    pid = int(match.group(1) or match.group(2))
    return pid if pid > 0 else None


def sweep_stale_work(
    data_dir: Path,
    own_pid: int,
    err: TextIO,
    *,
    is_alive: Callable[[int], bool] = pid_is_alive,
) -> list[Path]:
    """Remove the work folders in `data_dir` of installs that are no longer running.

    Each install removes only the folders named by its own pid, so those of an install
    killed partway would stay for good. A direct child named `.staging-<pid>` or
    `.old-<pid>-<anything>` is removed when its pid is not `own_pid` and `is_alive` says
    no process holds it. Only a real folder is removed: a link is never followed and a
    file is kept. A folder that cannot be removed is a warning on `err`, and the sweep
    goes on: a leftover never fails an install. Returns the folders removed.
    """
    removed: list[Path] = []
    with os.scandir(data_dir) as entries:
        stale = sorted(
            Path(entry.path) for entry in entries if _is_stale(entry, own_pid, is_alive)
        )
    for folder in stale:
        try:
            shutil.rmtree(folder)
        except OSError as error:
            print(
                f"WARNING: could not remove {folder}, left by an install that is no "
                f"longer running ({type(error).__name__}); remove it by hand",
                file=err,
            )
            continue
        removed.append(folder)
    return removed


def _is_stale(
    entry: os.DirEntry[str], own_pid: int, is_alive: Callable[[int], bool]
) -> bool:
    """Whether `entry` is a real folder some other, dead install left."""
    pid = _work_folder_pid(entry.name)
    if pid is None or pid == own_pid:
        return False
    return entry.is_dir(follow_symlinks=False) and not is_alive(pid)


def refuse_linked_worktree(host: Host) -> None:
    """Refused when the entry script sits in a linked git worktree.

    A linked worktree's `--git-dir` differs from its `--git-common-dir`. A folder outside
    every repository, as git's own message says, passes this check; any other git
    failure, an answer short of two lines, or a git that cannot answer refuses. Passing
    it is not leave to install: an app that needs more of git refuses such a folder on
    its own, as the runner does, since its allowlist is relative to the checkout's root.
    """
    folder = host.script.parent
    argv = ["git", "-C", str(folder), "rev-parse", *_DIR_QUESTIONS]
    try:
        done = host.run(argv, cwd=folder, timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused(
            f"could not ask git whether {folder} is a linked worktree "
            f"({type(error).__name__})"
        ) from None
    if done.returncode != 0 and any(
        phrase in done.stderr for phrase in _NOT_A_REPOSITORY
    ):
        return
    lines = done.stdout.splitlines()
    if done.returncode != 0 or len(lines) < len(_DIR_QUESTIONS):
        raise Refused(
            f"git could not say whether {folder} is a linked worktree "
            f"(exit {done.returncode})"
        )
    git_dir, common_dir = ((folder / line).resolve() for line in lines[:2])
    if git_dir != common_dir:
        raise Refused(
            f"{folder} is in a linked git worktree, which is often removed once its "
            "work is done; install from the repository's main checkout"
        )
