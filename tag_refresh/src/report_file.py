"""The one way a tool here writes a file of library paths: never into a repository, atomically.

tag_refresh's ``--missing-list`` and each audit tool's ``--report`` write the names
and paths of a real library, which must never be committed. So `refusal` turns down
any target whose folder lies inside a git working tree, judged before the run does any
work, and `write_atomically` replaces the target whole, so a reader never sees half a
file and a failed write leaves the old one as it was; `write_new` publishes as whole a
file that must not replace one, refusing a target that exists by then.

A working tree is recognized structurally, by a ``.git`` entry in the target's folder
or any folder above it: a folder in a clone, a file in a linked worktree or a
submodule. No git command is run, so the answer holds where git is not installed.
The folder is resolved first, so a symbolic link into a repository is refused as the
repository it leads to.

The audits (library_audit and phone_audit) also share their report's delivery here:
the ``--format`` values (`FORMATS`), `refuse_bad_report` and `refuse_html_to_stdout`,
which turn down options that cannot run before any work, and `deliver_report`, which
writes the report to the caller's stdout or through `write_atomically`, asking
`refusal` again at the moment of writing. Each audit declares ``--format`` and ``--report`` in its
own parser, where its companion doc's consistency check reads them.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

#: The entry that marks a working tree's top folder: a folder, or a file in a worktree.
GIT_ENTRY = ".git"
#: The temporary file's suffix, beside the target until it is published.
_TEMP_SUFFIX = ".tmp"
#: The audits' three report formats. HTML goes to a file only (``--report``), and no
#: format is ever inferred from the report's name.
FORMAT_TEXT, FORMAT_JSON, FORMAT_HTML = "text", "json", "html"
#: Every report format, in the order ``--help`` lists them.
FORMATS = (FORMAT_TEXT, FORMAT_JSON, FORMAT_HTML)
#: The refusal of ``--format html`` with no ``--report``.
HTML_NEEDS_REPORT = "--format html needs --report: the page is written to a file only"


class InterruptedAfterPublish(KeyboardInterrupt):
    """Ctrl-C after `write_new` published the target: the file is there, whole.

    A KeyboardInterrupt still, so a caller that does not tell the two apart stops as
    on any interrupt.
    """


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


def _discard(name: str) -> None:
    """Remove the temporary file *name*, which may be gone already."""
    with contextlib.suppress(FileNotFoundError):
        os.unlink(name)


def _discard_quietly(name: str) -> None:
    """Remove the temporary file *name*, leaving it where removing it fails.

    Only while an error or interrupt is already on its way out of a write: that is
    the one to report, and a cleanup error raised in its place would hide it, so the
    leftover is not reported.
    """
    with contextlib.suppress(OSError):
        os.unlink(name)


def _staged(target: Path, data: bytes) -> str:
    """Write *data* to a new temporary file beside *target*, flushed to disk; its name.

    The file is created readable by the user running the tool only, as ``tempfile``
    makes it: it lists a private library. On any failure it is removed where it can
    be and the error raised.
    """
    # Not a `with` around the whole: the name must outlive the close for the publish.
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
    except BaseException:
        _discard_quietly(handle.name)
        raise
    return handle.name


def write_atomically(target: Path, data: bytes) -> None:
    """Replace *target* with *data* through a temporary file in the same folder.

    The temporary file is written, flushed to disk, then renamed over the target by
    ``os.replace``, which is atomic within one file system. On any failure the
    temporary file is removed where it can be and the error raised, never a cleanup
    error in its place; the target is left as it was. The file is created at mode
    0600, as `_staged` makes it.
    """
    staged = _staged(target, data)
    try:
        os.replace(staged, target)
    except BaseException:
        _discard_quietly(staged)
        raise


def _same_file(staged: str, target: Path) -> bool:
    """Whether *target* is a link to the file *staged*, so the publish was made."""
    try:
        return os.path.samestat(os.stat(staged), os.lstat(target))
    except OSError:
        return False


def _leftover(staged: str) -> str | None:
    """Remove the published file's staging name; that name if it stays, else None."""
    try:
        _discard(staged)
    except OSError:
        return staged
    return None


def write_new(target: Path, data: bytes) -> str | None:
    """Publish *data* as the new file *target*; raise FileExistsError if it exists.

    For a target that must never be replaced, a snapshot say, where a check that it
    is absent followed by `write_atomically` would replace a file made in between. The
    temporary file is written and flushed beside the target, then hard-linked to it:
    ``os.link`` refuses any existing entry, a dangling symbolic link too, without
    following it, and like a rename it makes the name appear with the whole file
    behind it, so a reader never sees half of one. A file system without hard links
    fails the link with its own error.

    The link's outcome is the write's. A failed link raises its own error, the target
    left as it was, and the temporary file is removed where it can be. Once the link
    is made, the write has succeeded: the temporary name is removed, and if that
    fails it is returned, for the caller to name; None means nothing was left.
    Ctrl-C once the link is made raises `InterruptedAfterPublish`, since the target
    is then whole.
    """
    staged = _staged(target, data)
    try:
        os.link(staged, target)
    except BaseException as error:
        # An interrupt delivered as the link returns arrives here with the link made;
        # the file system, not the exception, says whether it was. Accepted residual:
        # a second Ctrl-C during the same-file check or the quiet unlink below
        # escapes as a plain interrupt, even with the link made.
        published = isinstance(error, KeyboardInterrupt) and _same_file(staged, target)
        _discard_quietly(staged)
        if published:
            raise InterruptedAfterPublish from None
        raise
    try:
        return _leftover(staged)
    except KeyboardInterrupt:
        raise InterruptedAfterPublish from None


# --- An audit's report, delivered ----------------------------------------------------


def refuse_bad_report(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    """Exit 2 through *parser* when ``--report`` cannot be written, before any work."""
    if args.report is None:
        return
    reason = refusal(args.report)
    if reason is not None:
        parser.error(f"--report: {reason}")


def refuse_html_to_stdout(args: argparse.Namespace) -> str | None:
    """Why the options cannot run, when ``--format html`` names no ``--report``."""
    if args.format == FORMAT_HTML and args.report is None:
        return HTML_NEEDS_REPORT
    return None


def deliver_report(
    text: str,
    report: Path | None,
    *,
    prog: str,
    out: TextIO,
    notice: Callable[[str], None],
) -> bool:
    """Write *text* to *out*, or whole to *report*; False when it could not be written.

    *out* is the calling CLI's stdout, passed in so this module never seizes it. A
    report that cannot be written is said through *notice*, prefixed with *prog*. An
    interrupt is the caller's to report: the atomic write leaves the file as it was.
    """
    if report is None:
        out.write(text)
        return True
    # Asked again at the moment of writing: the answer given at start may no longer
    # hold (a repository made around the folder while the run went on, say).
    reason = refusal(report)
    if reason is not None:
        notice(f"{prog}: --report: {reason}")
        return False
    try:
        write_atomically(report, text.encode("utf-8"))
    except OSError as error:
        notice(f"{prog}: cannot write the report {report}: {error.strerror or error}")
        return False
    return True
