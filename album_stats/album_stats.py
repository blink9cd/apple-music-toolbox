"""Report one album's track count, favorited-track count and year, via Apple Music.

Answers a single question -- "of this album's N tracks, how many have I favorited?" --
for a caller that already knows which album it means. `album_scan.py` is that caller;
this tool has no idea how an album was chosen, and deliberately no ability to choose one.

NOTHING HERE READS OR REPORTS A TRACK TITLE. Music.app is asked for three integers and
returns three integers; there is no path by which a title, a filename or any other piece
of library content reaches stdout, stderr or a caller. See `album_stats.md`, "What
leaves Music.app", for why that boundary is drawn at the query rather than at the output.

Two rules this tool encodes, pinned by `test_album_stats.py` and, for the opt-in
star-rating half, by `tests/test_star_rating.py`:

- **`favorited`, not `rating`, by default.** On a real library, `rating kind is user
  and rating > 0` matched almost none of the tracks; `favorited is true` matched a
  large share. Recent Music.app draws a STAR for "Favorite", so the control a listener
  presses when they "star a song" writes `favorited` -- while the property literally
  named for rating stays almost empty. A count keyed on `rating` would read 0 of N on
  essentially every album. A caller whose library DOES carry star ratings asks for
  them explicitly with `min_stars`, and then only a USER rating counts.
- **Both artist and album, never album alone.** Two albums can share a title across
  different artists, and compilations make it worse.

The real-process seam is `recently_added._real_run`, REUSED rather than
reimplemented: it already carries the bounded-subprocess discipline (a plain
`subprocess.run(capture_output=True, timeout=...)` reads as bounded and is not -- see
that function's own docstring), and a second copy would be a second thing to get right.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

# The shared UTF-8 stdio policy and --help formatter libraries, and the sibling
# recently_added TOOL folder: all three sit directly under the project root, which
# is this file's grandparent, so each is ONE fixed candidate rather than a search up the
# ancestors. See stdio_utf8/stdio_utf8.md, "How this project's tools import it", for why
# the search was bounded and what an unbounded one lets a stranger's folder do.
sys.path += [
    str(Path(__file__).resolve().parents[1] / name)
    for name in ("stdio_utf8", "help_formatter", "recently_added")
]

import help_formatter
import stdio_utf8
from recently_added import (
    _MUSIC_TIMEOUT_SECONDS,
    Runner,
    _real_run,
)

__all__ = ["AlbumFacts", "Runner", "album_facts", "build_parser", "main"]


class AlbumFacts(NamedTuple):
    """What Music.app reports about one album: two counts and a year.

    Named for facts rather than counts because it carries a year too.

    `tracks` is at least 1, and `favorited` is always between 0 and `tracks`
    inclusive; a payload that violates that is rejected by `_parse_facts` rather than
    handed on, because a count shown as "N of M" has no sensible way to show
    "12 of 10".

    `year` is the latest year tag among the tracks the query matched, or None when
    none of them is tagged. It is the FILE'S TAG, not a release date: an album
    ripped from a remaster reports the reissue year, and nothing here can tell a
    wrong tag from a right one. album_scan uses it as the album's year anyway,
    filling only an absent one from the store's release date -- see album_scan.md,
    in the media_feeds project.
    """

    tracks: int
    favorited: int
    year: int | None


# The query's time bound is `recently_added._MUSIC_TIMEOUT_SECONDS`, imported above
# rather than restated: album_stats' and recently_added's `whose` clauses visit the
# whole library, and the rationale for the number lives beside it there.

# One single-pass mapping rather than chained `.replace()` calls, which carry an
# ordering trap: escaping quotes before backslashes re-escapes the escapes just added,
# and the resulting literal quietly means something other than the name it came from.
# `str.translate` visits each character exactly once and never revisits its own output,
# so that ordering bug is not merely untested here -- it cannot be written.
# Newline and carriage return map to the `\n` and `\r` escapes, which denote the same
# characters: a raw line break inside an AppleScript literal also compiles, to the
# same string (measured with osascript), so these two only keep the generated script
# one statement per line.
_APPLESCRIPT_ESCAPES = str.maketrans(
    {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r"}
)

_FIELD_SEPARATOR = "\t"
_EXPECTED_FIELDS = 3

#: Music.app stores a track rating as 0-100, twenty per star, so N stars is N * 20.
_RATING_PER_STAR = 20
#: The star thresholds `min_stars` accepts: Music.app's one-to-five-star scale.
_STAR_RANGE = range(1, 6)


def _applescript_literal(value: str) -> str:
    """`value` as an AppleScript string literal, quotes included.

    Every caller interpolates the result straight into script source, so the quoting
    is this function's responsibility and not the caller's -- returning the bare
    escaped text would invite exactly the un-quoted interpolation this exists to stop.
    """
    return '"' + value.translate(_APPLESCRIPT_ESCAPES) + '"'


def _qualifier_clause(min_stars: int | None) -> str:
    """The `whose` condition a track must meet to count toward `favorited`.

    `None` is Music.app's `favorited` flag. A star count is a USER rating at or above
    that many stars: `rating kind is user` is not optional, because Music can derive a
    track rating from an album rating, and counting those would credit tracks the
    listener never rated (album_stats.md, "Why `favorited`, and not `rating`").
    """
    if min_stars is None:
        return "favorited is true"
    return f"rating kind is user and rating >= {min_stars * _RATING_PER_STAR}"


def _validate_min_stars(min_stars: int | None) -> None:
    """Raise ValueError unless `min_stars` is None or an int star count from 1 to 5.

    `type(...) is int` rather than isinstance: a bool IS an int to Python, and `True`
    would otherwise slip through as one star.
    """
    if min_stars is None:
        return
    if type(min_stars) is not int or min_stars not in _STAR_RANGE:
        raise ValueError(f"min_stars must be None or 1 to 5, not {min_stars!r}")


def _facts_script(artist: str, album: str, min_stars: int | None) -> str:
    """The AppleScript that answers both counts and the year in one round trip.

    Two `whose` clauses select and count the tracks: a `whose` clause is evaluated
    inside Music.app and answers immediately, while iterating tracks and reading a
    property per track makes each access its own Apple Event -- a probe reading two
    properties per track timed out on a few thousand tracks.

    The match predicate is built ONCE and used in both clauses, so the two counts
    cannot drift apart by an edit to one of them. `min_stars` changes only the second
    clause's qualifier (`_qualifier_clause`); every other line, and every variable
    name, is the same in both modes, so the rating script keeps the structure the
    live test proved for the favorited one.

    The year is the one per-track read, and it loops only over the tracks the first
    clause already matched: one Apple Event per track on THIS album, never one per
    track in the library.
    """
    match = (
        f"album artist is {_applescript_literal(artist)} "
        f"and album is {_applescript_literal(album)}"
    )
    qualifier = _qualifier_clause(min_stars)
    # The track set is bound once and reused for the count and the year, so the year
    # is read from tracks certainly part of THIS album rather than from a second,
    # independently-evaluated query that could drift from it.
    #
    # The year kept is the LATEST tag among those tracks. An untagged track reports 0,
    # which never beats a real year, so one untagged track cannot blank the album's
    # year; 0 survives only when no track is tagged. Latest rather than earliest
    # because a compilation's tracks can carry their original years, while the year a
    # store lists for a compilation is its own release, on or after all of them --
    # and a store year is what `cover_art` weighs this one against.
    #
    # `albTracks`, not `matched`: `matched` is a term in Music's own dictionary and
    # binding it fails at RUNTIME with "Access not allowed. (-10003)" -- which reads
    # exactly like a denied automation permission and is not one. `computed` collides
    # the same way (see album_stats.md); the defense is to invent variable names
    # (`albTrk`, `trkYr`) rather than to reach for a natural-sounding word.
    return (
        'tell application "Music"\n'
        "    set lp to library playlist 1\n"
        f"    set albTracks to (every track of lp whose {match})\n"
        "    set nAll to count of albTracks\n"
        f"    set nFav to count of (every track of lp whose {match} and {qualifier})\n"
        "    set yr to 0\n"
        "    repeat with albTrk in albTracks\n"
        "        set trkYr to year of albTrk\n"
        "        if trkYr > yr then set yr to trkYr\n"
        "    end repeat\n"
        "    return (nAll as string) & tab & (nFav as string) & tab & (yr as string)\n"
        "end tell"
    )


def _parse_facts(text: str) -> AlbumFacts | None:
    """Music.app's `tracks<TAB>favorited<TAB>year` reply, or `None` if it is not usable.

    Never raises. A zero track count means the artist/album pair matched nothing, which
    is reported as `None` rather than as zero counts: the album is absent, a different
    fact from "present, with nothing favorited yet", and a consumer must be able to tell
    the two apart.
    """
    fields = text.strip().split(_FIELD_SEPARATOR)
    if len(fields) != _EXPECTED_FIELDS:
        return None
    try:
        tracks, favorited, year = (int(field) for field in fields)
    except ValueError:
        return None
    if tracks <= 0 or favorited < 0 or favorited > tracks or year < 0:
        return None
    # Music.app returns 0 for a track with no year tag. 0 is not a year, so it becomes
    # None and a consumer can omit the year rather than print a zero. Statement form,
    # not a conditional expression: coverage.py emits no branch arcs for
    # `x if cond else y`, so the untagged arm would satisfy the 100% gate while never
    # running.
    if year == 0:
        reported_year = None
    else:
        reported_year = year
    return AlbumFacts(tracks=tracks, favorited=favorited, year=reported_year)


def album_facts(
    artist: str,
    album: str,
    *,
    run: Runner = _real_run,
    timeout: float = _MUSIC_TIMEOUT_SECONDS,
    min_stars: int | None = None,
) -> AlbumFacts | None:
    """This album's two counts and year, or `None` if they cannot be had.

    `min_stars=None` counts tracks Music.app has `favorited`; `min_stars=N` (1 to 5)
    instead counts tracks the listener rated at least N stars, reported in the same
    `favorited` field. Either way 0 means "asked, none qualified" and `None` means no
    answer, so the two never collapse.

    Raises ValueError for a `min_stars` outside 1 to 5 -- a caller's programming
    error, refused before any query. Otherwise never raises, mirroring
    `recently_added.newest_albums_from_music`'s contract for the same reason:
    Music.app absent, not running, not scriptable, automation permission denied, a
    timeout, a non-zero exit, an unparseable reply and an album that simply is not in
    the library all come back as `None`, and the CALLER decides what no answer means
    rather than this function deciding for it via an exception.
    """
    # ValueError alongside the two obvious classes: `subprocess.Popen` raises it, not
    # OSError, for an argv element holding a NUL -- and the artist and album are
    # interpolated into the script that becomes one. A NUL in either would otherwise
    # escape this never-raises contract as a traceback out of the caller's refresh.
    _validate_min_stars(min_stars)
    try:
        script = _facts_script(artist, album, min_stars)
        result = run(["osascript", "-e", script], timeout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if result.returncode != 0:
        return None
    return _parse_facts(result.stdout)


_EXIT_OK = 0
_EXIT_NO_COUNTS = 1


def positive_float(text: str) -> float:
    """A --timeout value: a finite number of seconds greater than zero.

    Raised as an ArgumentTypeError rather than checked in main, so argparse renders
    the usage message and exits 2 -- the same treatment a non-numeric value already
    gets, rather than a second spelling of "bad argument" -- and the rejection lands
    before any Music.app query. The floor exists because `bounded_run` expires a zero
    or negative timeout instantly, which surfaced as "no counts ... Music.app could
    not answer" on exit 1: a usage error disguised as a data answer. `nan` and `inf`
    are refused too, since neither bounds anything. Defined locally rather than
    shared with `album_scan.positive_int`, for the reason that function's own
    docstring records: a shared module for a handful of branchless lines would need
    its own gate-checked folder, a companion doc, and its own tests.
    """
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(
            f"must be a positive number of seconds, not {text}"
        )
    return value


def star_count(text: str) -> int:
    """A --favorite-min-stars value: a whole number of stars from 1 to 5.

    An ArgumentTypeError for the same reason `positive_float` raises one: argparse
    then exits 2 with its usage message before any Music.app query, rather than the
    ValueError `album_facts` would raise surfacing as a traceback.
    """
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value not in _STAR_RANGE:
        raise argparse.ArgumentTypeError(
            f"must be a whole number of stars from 1 to 5, not {text}"
        )
    return value


class _HelpFormatter(
    help_formatter.ReqAwareDefaultsFormatter, argparse.RawDescriptionHelpFormatter
):
    """Show every default AND keep the epilog's own line breaks.

    Neither stock formatter does both, and using the defaults formatter alone silently
    re-wraps the epilog into one unbroken block: its paragraph breaks vanish and even a
    short heading like "Exit codes:" can be split across a line.

    The two bases override different methods -- `_get_help_string` for the defaults,
    `_fill_text` for the wrapping -- so they compose with no conflict to resolve.
    Because `_fill_text` no longer wraps, the epilog below is hard-wrapped by hand.

    The defaults half is the SHARED `help_formatter.ReqAwareDefaultsFormatter`, not
    argparse's stock one, and here it changes what an operator actually reads: below
    CPython 3.13 the stock formatter stamps a misleading "(default: None)" onto a
    REQUIRED option, and BOTH `--artist` and `--album` are required. This project's
    floor is 3.12 (`pyproject.toml`'s `[project].requires-python`), below that fix.
    """


def build_parser() -> argparse.ArgumentParser:
    """The CLI, fully configured. Every argument is a named option, defaults shown."""
    parser = argparse.ArgumentParser(
        description=(
            "Report one album's track count, favorited-track count (or count of "
            "tracks rated at least N stars) and year, via Apple Music."
        ),
        formatter_class=_HelpFormatter,
        epilog=(
            "Prerequisites:\n"
            "  Music.app installed, running, and scriptable (macOS only; System\n"
            "  Settings > Privacy & Security > Automation must allow it). Makes NO\n"
            "  network call -- the Music.app query is a local subprocess. Run by\n"
            "  hand, or call album_facts() directly; never as a build step and\n"
            "  never at page-view time.\n"
            "\n"
            "Matching:\n"
            "  --artist must match the album ARTIST, which is not always the track\n"
            "  artist: on a compilation they differ. Matching on the album title\n"
            "  alone is not enough, because two albums can share a title.\n"
            "\n"
            "Favorites signal:\n"
            "  By default a track counts when Music.app has it favorited. With\n"
            "  --favorite-min-stars N it counts instead when the listener's OWN\n"
            "  rating is at least N stars (Music.app rating >= N*20); a rating\n"
            "  Music derived from an album rating never counts.\n"
            "\n"
            "Output:\n"
            '  Prints {"tracks": N, "favorited": M, "year": Y} to stdout. Every\n'
            "  human-readable message goes to stderr, so stdout piped or redirected\n"
            "  to a file gets nothing but the JSON record. No track title ever\n"
            "  leaves Music.app.\n"
            "\n"
            "Exit codes:\n"
            "  0  wrote the counts\n"
            "  1  no counts -- the album is not in the library, or Music.app could\n"
            "     not answer (absent, not running, not scriptable, or automation\n"
            "     permission denied)"
        ),
    )
    _add_arguments(parser)
    return parser


def _add_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach this tool's options. Split from `build_parser` only for length."""
    parser.add_argument(
        "--artist", required=True, help="The album artist to match, exactly."
    )
    parser.add_argument(
        "--album", required=True, help="The album title to match, exactly."
    )
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=_MUSIC_TIMEOUT_SECONDS,
        help="Seconds to allow the Music.app query before abandoning it.",
    )
    parser.add_argument(
        "--favorite-min-stars",
        type=star_count,
        default=None,
        metavar="N",
        help=(
            "Count tracks the listener rated at least N stars (1-5) instead of "
            "favorited tracks; unset means favorited."
        ),
    )


def main(argv: list[str] | None = None, *, run: Runner = _real_run) -> int:
    """Resolve the facts for --artist/--album and print them. Returns the exit code.

    `run` is the same injection seam `album_facts` exposes, threaded through so a test
    can drive any outcome without spawning a real `osascript` process.
    """
    # First statement, before anything is printed: this tool's output is captured by a
    # pipe as often as it is read in a terminal, and a locale-derived encoding would
    # fail on any non-ASCII artist or album name reaching the stderr messages below.
    stdio_utf8.force_utf8_streams(sys.stdout, sys.stderr)
    args = build_parser().parse_args(argv)

    facts = album_facts(
        args.artist,
        args.album,
        run=run,
        timeout=args.timeout,
        min_stars=args.favorite_min_stars,
    )
    if facts is None:
        # album_facts' `None` does not say WHICH failure happened, so the message
        # offers both explanations.
        print(
            f"album_stats: no counts for {args.artist} - {args.album} "
            "(not in the library, or Music.app could not answer)",
            file=sys.stderr,
        )
        return _EXIT_NO_COUNTS

    # No stdout newline pinning, unlike album_scan's `emit_records`: that tool
    # writes the same record to EITHER a file or stdout and keeps the two
    # byte-identical, while this one has a single output path.
    sys.stdout.write(
        json.dumps(
            {"tracks": facts.tracks, "favorited": facts.favorited, "year": facts.year},
            indent=2,
        )
        + "\n"
    )
    print(
        f"album_stats: {facts.favorited} of {facts.tracks} "
        f"{_signal_phrase(args.favorite_min_stars)}",
        file=sys.stderr,
    )
    return _EXIT_OK


def _signal_phrase(min_stars: int | None) -> str:
    """How the stderr confirmation names the favorites signal it counted."""
    if min_stars is None:
        return "favorited"
    if min_stars == 1:
        return "rated at least 1 star"
    return f"rated at least {min_stars} stars"


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
