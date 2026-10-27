"""The one way a tool here writes a file of library paths: never into a repository, atomically.

tag_refresh's ``--missing-list`` and each audit tool's ``--report`` write the names
and paths of a real library, which must never be committed. So `refusal` turns down
any target whose folder lies inside a git working tree, judged before the run does any
work, and `write_atomically` replaces the target whole, so a reader never sees half a
file and a failed write leaves the old one as it was.

A working tree is recognized structurally, by a ``.git`` entry in the target's folder
or any folder above it: a folder in a clone, a file in a linked worktree or a
submodule. No git command is run, so the answer holds where git is not installed.
The folder is resolved first, so a symbolic link into a repository is refused as the
repository it leads to.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

#: The entry that marks a working tree's top folder: a folder, or a file in a worktree.
GIT_ENTRY = ".git"
#: The temporary file's suffix, beside the target until it replaces it.
_TEMP_SUFFIX = ".tmp"


def _folder_of(target: Path) -> Path:
    """The folder *target* would be written in, made absolute from the working directory."""
    return Path(os.path.abspath(target)).parent


def working_tree_of(target: Path) -> Path | None:
    """The top folder of the working tree holding *target*'s folder, or None."""
    folder = _folder_of(target).resolve()
    for candidate in (folder, *folder.parents):
        if os.path.lexists(candidate / GIT_ENTRY):
            return candidate
    return None


def refusal(target: Path) -> str | None:
    """Why *target* may not be written, or None when it may.

    Refused: a folder that does not exist, a target that is itself a folder, and any
    target inside a git working tree.
    """
    folder = _folder_of(target)
    if not folder.is_dir():
        return f"{folder} is not a folder"
    if target.is_dir():
        return f"{target} is a folder"
    tree = working_tree_of(target)
    if tree is not None:
        return (
            f"{target} is inside the git working tree {tree}; it would hold library "
            "names and paths, so write it outside any repository"
        )
    return None


def write_atomically(target: Path, data: bytes) -> None:
    """Replace *target* with *data* through a temporary file in the same folder.

    The temporary file is written, flushed to disk, then renamed over the target by
    ``os.replace``, which is atomic within one file system. On any failure the
    temporary file is removed and the error raised; the target is left as it was. The
    file is created readable by the user running the tool only, as ``tempfile`` makes
    it: it lists a private library.
    """
    # Not a `with` around the whole: the name must outlive the close for the rename.
    handle = tempfile.NamedTemporaryFile(
        dir=_folder_of(target),
        prefix=f".{target.name}.",
        suffix=_TEMP_SUFFIX,
        delete=False,
    )
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(handle.name)
        raise
