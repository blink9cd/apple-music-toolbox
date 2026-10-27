"""afcclient's ``ls -l`` output, parsed strictly. Pure.

afcclient 1.4.0 prints one line per entry, ``.`` and ``..`` left out, as this printf
sequence: the type and permissions (``drwxr-xr-x`` a folder, ``lrwxrwxrwx`` a link,
else one of ``f b c s -`` then ``rw-r--r--``), a space, the link count as ``%4d``, a
space, ``mobile mobile``, a space, the size as ``%10lld``, a space, the modification
time as ``%d %h %Y %H:%M:%S``, a space, the base name, a linefeed. With colors on, the
name is wrapped in color escapes; the seam turns them off, and they are removed here
as well.

When one entry's stat fails, afcclient still prints its line, every field zeroed: a
link count of 0, a size of 0 and the epoch in the local zone. No real entry has a link
count of 0, so such a line is unparsed rather than a 0-byte file.

A line in any other shape is never dropped: it comes back in `Listing.unparsed`, so
the caller counts it as a finding. A file name holding a linefeed would split its line
in two, and both halves land there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The type character of a regular file, and of a folder.
FILE_KIND = "-"
DIR_KIND = "d"
#: One entry's line. The month is the C library's abbreviated name, so any non-space run.
_LINE = re.compile(
    r"(?P<mode>drwxr-xr-x|lrwxrwxrwx|[-fbcs]rw-r--r--)"
    r" +(?P<links>\d+) mobile mobile +(?P<size>\d+)"
    r" \d{2} \S+ \d{4} \d{2}:\d{2}:\d{2} (?P<name>.+)",
    re.ASCII,
)
#: The link count of a line whose stat failed: afcclient prints it zeroed.
_FAILED_STAT_LINKS = 0
#: A color escape: CSI, parameters, ``m``.
_COLOR = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True)
class Entry:
    """One listed entry: its type character, size in bytes, and base name."""

    kind: str
    size: int
    name: str


@dataclass(frozen=True)
class Listing:
    """A listing's entries in order, and every line that was not in the expected shape."""

    entries: tuple[Entry, ...]
    unparsed: tuple[str, ...]


def _lines(text: str) -> list[str]:
    """*text*'s lines, split on linefeeds only; the empty tail after the last is dropped."""
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


# fuzz-target
def parse_listing(text: str) -> Listing:
    """Every line of *text* as an `Entry`, or as an unparsed line when it is not one."""
    entries: list[Entry] = []
    unparsed: list[str] = []
    for line in _lines(text):
        found = _LINE.fullmatch(_COLOR.sub("", line))
        if found is None or int(found["links"]) == _FAILED_STAT_LINKS:
            unparsed.append(line)
            continue
        entries.append(Entry(found["mode"][0], int(found["size"]), found["name"]))
    return Listing(tuple(entries), tuple(unparsed))
