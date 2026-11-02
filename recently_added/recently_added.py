"""The newest album per Apple Music's own "date added", via its AppleScript API.

Apple Music's own "date added" is the primary source for "most recently added"; the
library folder's filesystem birth time is only a fallback, because on a real library
it mis-ranks albums. Against three albums added in a known order, Music's "date
added" reproduces that order exactly, while the folder scan misses the middle one
entirely: its folder's birth time and its mtime read months apart, and
Music.app agrees with the mtime. The birth time was a re-materialization timestamp,
not the date the album was added. The contributing
cause is verifiable on any machine with the same arrangement: `~/Music/Albums` was the
same directory, by inode and device, as its iCloud Drive counterpart, and an
evicted-then-re-materialized item does not preserve its original birth time. See
`album_scan/album_scan.md` in the separate media_feeds project, "Why the folder
scan's date is a heuristic".

Every artist and album name in this tool's tests is an invented stand-in, so none of
them is anyone's actual listening history.

Music.app's AppleScript dictionary is the supported, testable API for "date added".
`Library.musicdb` is a large, undocumented binary format: building on it would
mean depending on a guessed wire contract with no way to exercise it under test, so
it is ruled out.

This is a library with no CLI, in its own folder with its own tests and doc, because
more than one tool imports it: `album_stats.py` (`Runner` and `_real_run`), and
media_feeds' `album_scan.py` (the date source and the `Runner` seam), only under
`--source music` or `auto`.
`album_stats.py`, a sibling in this project, finds it at one fixed place on
`sys.path`: a folder directly under the project root.
`album_scan.py` locates this whole project at run time (`--toolbox`, the
`APPLE_MUSIC_TOOLBOX` variable, or a bounded upward search), as its own
`album_scan.md` documents under "Finding the toolbox".

`AlbumRef` is defined here, beside the query that produces it. media_feeds'
`album_scan` and `cover_art` keep their own copy of it, so neither published project
needs the other.

`_rank_albums` collapses the AppleScript's per-track rows to per-album ones before
ranking, keeping each album's newest track time as its added date. A single running
maximum over tracks is no substitute: it looks right only at a result of size one,
where a duplicate cannot appear, and at `--count` above 1 a freshly-added twelve-track
album fills every slot with copies of itself.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

# The shared bounded-subprocess-runner library, at one fixed place: directly under the
# project root, which is this file's grandparent. See bounded_run/bounded_run.md,
# "Importing it", and stdio_utf8/stdio_utf8.md for why this is not a search upward.
sys.path.append(str(Path(__file__).resolve().parents[1] / "bounded_run"))

import bounded_run


class AlbumRef(NamedTuple):
    """One album, identified by artist, album, and the date it was added."""

    artist: str
    album: str
    added: dt.date


# (argv, timeout_seconds) -> completed process. Injected, like cover_art.py's
# `Fetcher`, so both the found and not-found branches stay reachable with no real
# `osascript` process, and no unit test can reach Music.app or the host.
Runner = Callable[[list[str], float], "subprocess.CompletedProcess[str]"]

# AppleScript's `whose date added > cutoff` filter visits every track in the library,
# not just those within the window, so the query's cost scales with library size, not
# lookback width: measured live, a large library takes many seconds. 60s leaves
# headroom for a larger library or a slower run; this is a hand-run tool, not a
# page-load path, so a generous timeout costs nothing a caller would notice.
_MUSIC_TIMEOUT_SECONDS = 60.0

# How far back Music.app is asked to look for a "date added". Wide enough that a
# refresh after a normal gap still sees the newest addition. Nothing added within the
# window is an empty result, not an error: `newest_albums_from_music` returns `[]`, and
# album_scan.py's `--source auto` then falls back to the folder scan.
_MUSIC_LOOKBACK_DAYS = 200

# How far past "today" a row's "date added" may sit and still count. Music.app's
# `«class isot»` date is local time with no offset, so a track added late in the
# evening reads as tomorrow to a run whose own clock sits in a different zone, or
# that runs just past midnight. One day keeps every such row; a row any further
# ahead cannot have been added yet, and `_rank_albums` says why that matters.
_FUTURE_SLACK = dt.timedelta(days=1)

# The AppleScript ends each row with `linefeed` and nothing else, so this is the
# only character that may end one. Not `str.splitlines`: that also breaks at a
# vertical tab, a form feed, the ASCII separator controls, the C1 NEL and
# U+2028/U+2029, all of which a legitimate name may hold. Split that way, the name was
# cut there and its remainder read as a malformed row.
_ROW_TERMINATOR = "\n"

# The one date shape `«class isot» as string` emits, full-matched before a row is
# parsed. `datetime.fromisoformat` reads far more than that (the basic form
# `20000101T000000`, week dates `2000-W20-1T00:00:00`, and any single character where
# the `T` separator goes), so bounding the parsed value while ranking the raw string
# let another shape pass the bound and then sort wherever its characters landed: `'0'`
# and `'W'` both sort above `'-'`, so either outranked every hyphenated stamp of the
# same year. Refusing the shape here, and keying every comparison in `_rank_albums` on
# the parsed value, closes both halves; either alone leaves the other open. The digits
# are spelt `[0-9]` rather than `\d`, which in a `str` pattern matches any Unicode
# decimal digit. See docs/technical_notes/python-untrusted-input.md.
_ISOT_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}")

# Emits one line per recently-added track (not album: Music.app has no per-album
# "date added", and the newest track's stamp is what the whole tool means by "when the
# album was added"): an ISO-8601 "date added", a tab, the album artist, a tab, the
# album. That shape, and only that shape, is what `_ISOT_STAMP` full-matches: a row's
# date field is tag text like every other field, so `_rank_albums` refuses any other
# spelling of a date and ranks by the parsed value rather than by these characters.
# Tab is the field separator, not "|", which has appeared in band names,
# and AppleScript's own `tab`/`linefeed` keywords supply it. Only the integer lookback
# is interpolated into the script; track text never is, so it needs no escaping.
_MUSIC_SCRIPT = f"""tell application "Music"
    set cutoff to (current date) - ({_MUSIC_LOOKBACK_DAYS} * days)
    set recentTracks to (every track of library playlist 1 whose date added > cutoff)
    set output to ""
    repeat with t in recentTracks
        set output to output & ((date added of t) as «class isot» as string) & tab & (album artist of t) & tab & (album of t) & linefeed
    end repeat
    return output
end tell"""


def _real_run(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, bounded by a per-call timeout that actually holds.

    The timeout is on the call itself, not on an enclosing loop, as with
    `cover_art._real_fetch` for HTTP: an outer deadline can only fire between
    calls, never interrupt one already in flight. Delegates to
    `bounded_run.run_bounded` rather than calling `subprocess.run` directly: a plain
    `subprocess.run(capture_output=True, timeout=...)` reads as bounded and is not
    (`reliability_lint` RL005): on expiry CPython kills only the direct `osascript`
    child, then blocks re-reading the captured pipes if it ever spawned a grandchild
    that inherited them. `run_bounded` kills the whole process tree first
    (`bounded_run.md` has the mechanism), and decodes the capture as UTF-8 rather than
    by locale, so this module needs no `stdio_utf8` import of its own.

    Underscore-prefixed although `album_scan.py` and `album_stats.py` import it:
    it is the real-process seam, not a name any caller should reach for directly;
    inject a fake `run` instead, as every unit test here does. Excluded from coverage
    as a real-process IO seam every unit test replaces with a fake `run`; exercised end
    to end by `album_scan/tests/test_live_music.py`, in the separate media_feeds
    project.
    """
    return bounded_run.run_bounded(  # pragma: no cover - real-process IO seam, see docstring
        args, timeout=timeout
    )


def _rank_albums(text: str, count: int, *, today: dt.date) -> list[AlbumRef]:
    """Collapse Music.app's per-track rows into per-album ones, then rank.

    Music.app has no per-album "date added" (the AppleScript emits one row per
    track), so rows are grouped by `(artist, album)` before ranking, keeping each
    group's newest track time as that album's added date. This grouping is the whole
    point of this function: without it, a freshly-added twelve-track album would
    supply every one of `count`'s slots with a copy of itself, since every track in
    it carries a timestamp newer than anything else in the library.

    Never raises: a line with the wrong field count, a date field that is not the one
    shape Music.app emits or that will not parse at all, or an empty artist/album is
    skipped rather than aborting the whole scan: one malformed or unset row must not
    hide every other genuine one.

    The date field is judged twice and ranked by neither spelling of the string. It is
    full-matched against `_ISOT_STAMP` before it is parsed, because `fromisoformat`
    reads shapes Music.app never emits, and a row in one of those passed a bound placed
    on the parsed value and then sorted by its own raw characters, so a basic-form or
    week-date stamp outranked every genuine row of the same year while parsing to a date
    months in the past. Both the per-album maximum and the final sort below key on the
    parsed datetime, so the two halves cannot disagree again. The shape check does not
    make the parser's own refusal dead: `2000-13-45T99:99:99` matches the shape and names
    a thirteenth month.

    Two more rows are refused, and the reason is the same for both: the AppleScript
    concatenates each tag's text unescaped, so a tag can carry anything, including
    the row terminator itself. A row holding a NUL cannot name a real track, and a
    name with one in it cannot be handed to a subprocess at all: the per-album
    counts query built from it would be refused before it ran. A row dated more
    than `_FUTURE_SLACK` past `today` cannot have been added yet: a tag holding a
    line break followed by `date<TAB>artist<TAB>album` reads as a row of its own,
    with a date its author chose, and dated far enough ahead it ranked newest
    forever, over every real addition. The residual is stated plainly: the
    text-mode capture turns CR and CRLF into LF before this function sees them, so
    a CR or LF inside a tag still ends a row. What the date check removes is the one
    power injection adds (a date the tag's author picks), while the text a forged
    row carries is text a crafted tag could already have carried on its own.

    `today` is a parameter rather than a clock read so this function stays pure:
    a row's distance from "today" is then a property of the test, not of the day
    it runs.

    The empty-field guard matters because the failure it prevents is silent:
    AppleScript reports an unset `album artist` or `album` (a compilation, a single
    with no album) as `""`, not an error. Without the guard, such a track would group
    and rank as `AlbumRef(artist="", album="...")`, a value returned successfully,
    so `--source auto` would never fall back to the folder scan (which cannot produce
    an empty name; it reads names straight off real directories) and the record would
    carry an empty artist or album. Skipping such a track lets an older but complete
    album win that slot instead; if every candidate is incomplete, this returns `[]`
    and the caller falls back to the folder scan.
    """
    newest_per_album: dict[tuple[str, str], tuple[dt.datetime, AlbumRef]] = {}
    latest_allowed = today + _FUTURE_SLACK
    for line in text.split(_ROW_TERMINATOR):
        if "\x00" in line:
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            continue
        added_isot, artist, album = fields
        if not artist.strip() or not album.strip():
            continue
        if not _ISOT_STAMP.fullmatch(added_isot):
            continue
        try:
            added_at = dt.datetime.fromisoformat(added_isot)
        except ValueError:
            continue
        added = added_at.date()
        if added > latest_allowed:
            continue
        key = (artist, album)
        seen = newest_per_album.get(key)
        if seen is None or added_at > seen[0]:
            newest_per_album[key] = (
                added_at,
                AlbumRef(artist=artist, album=album, added=added),
            )
    ranked = sorted(newest_per_album.values(), key=lambda pair: pair[0], reverse=True)
    return [ref for _, ref in ranked[:count]]


def newest_albums_from_music(
    count: int,
    *,
    run: Runner = _real_run,
    timeout: float = _MUSIC_TIMEOUT_SECONDS,
    today: dt.date | None = None,
) -> list[AlbumRef]:
    """The `count` most recently added albums per Apple Music's own "date added".

    Newest first. Never raises. Music.app absent, not running, not scriptable,
    automation permission denied, a timeout, a non-zero exit, empty output, and output
    with no parseable line all come back as `[]`. That mirrors
    `cover_art.artwork_url`'s never-raises contract, for the same reason: the
    caller decides what "no answer" means (fall back to the folder scan) rather than
    this function deciding for it via an exception. Returns fewer than `count` when
    Music.app reports fewer distinct albums than that: a short answer, not an error.

    `today` bounds how far ahead a row's "date added" may sit (see `_rank_albums`).
    `None`, the default, means the current date, read when this function runs
    rather than when the module loaded: a long-lived importer must not carry the
    day it started as "today" forever. A test injects a fixed date instead.
    """
    # Statement form, not a conditional expression: coverage.py emits no branch
    # arcs for `x if cond else y`, so the clock-reading arm would satisfy the 100%
    # gate while never running.
    if today is None:
        reference_day = dt.date.today()
    else:
        reference_day = today
    # ValueError alongside the two obvious classes: `subprocess.Popen` raises it, not
    # OSError, for an argv element holding a NUL. Nothing built here carries one, but
    # the contract is "never raises", and a seam that can be handed a name from
    # anywhere must hold it for the one refusal the seam itself makes.
    try:
        result = run(["osascript", "-e", _MUSIC_SCRIPT], timeout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    if result.returncode != 0:
        return []
    return _rank_albums(result.stdout, count, today=reference_day)
