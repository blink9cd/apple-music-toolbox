"""Shared fixtures for the refresh_core suites: a temporary tree, invented MP3s, a fake stat.

Every file these suites touch is made under a fresh temporary directory by `TreeCase`,
so no test reads a real music library or any file of the machine it runs on. The MP3s
are a few invented bytes, never audio: refresh_core reads only names and inodes.

`fake_stat` stands in for ``os.stat`` where a test needs a path to report a device and
inode of its choosing, which is how a row in Music's resolved path form is shown to
match a named MP3 that is spelled differently.

Not discovered as a suite (no ``test_`` prefix). Suites import it by bare name with
this directory on ``sys.path``.
"""

from __future__ import annotations

import os
import stat
import unittest
from collections.abc import Callable, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

#: Invented bytes standing in for an MP3: the core never reads a file's content.
FAKE_MP3 = b"ID3 invented"
#: A regular file's mode, for a fake stat result.
_REGULAR_FILE_MODE = stat.S_IFREG | 0o644
#: How many fields ``os.stat_result`` takes when built from a sequence.
_STAT_FIELDS = 10


def make_stat(device: int, inode: int) -> os.stat_result:
    """Return a stat result for a regular file with this device and inode, the rest zero."""
    fields = [0] * _STAT_FIELDS
    fields[0] = _REGULAR_FILE_MODE
    fields[1] = inode
    fields[2] = device
    return os.stat_result(fields)


def fake_stat(table: Mapping[str, tuple[int, int]]) -> Callable[[str], os.stat_result]:
    """Return a stat seam answering from ``table`` (path -> (device, inode)).

    A path absent from the table raises ``FileNotFoundError``, as a vanished file does.
    """

    def _stat(path: str) -> os.stat_result:
        try:
            device, inode = table[path]
        except KeyError:
            raise FileNotFoundError(path) from None
        return make_stat(device, inode)

    return _stat


def list_bytes(*lines: str) -> bytes:
    """Return a list file's bytes: each line UTF-8 encoded and linefeed terminated."""
    return "".join(f"{line}\n" for line in lines).encode("utf-8")


class TreeCase(unittest.TestCase):
    """A test case owning a fresh temporary directory, removed when the test ends."""

    def setUp(self) -> None:
        """Make the temporary root; ``resolve`` so it compares equal to walked paths."""
        super().setUp()
        holder = TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name).resolve()

    def touch(self, relative: str, data: bytes = FAKE_MP3) -> Path:
        """Write ``data`` at ``relative`` under the root, making its folders; return it."""
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path
