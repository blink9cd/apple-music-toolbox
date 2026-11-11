"""Parsed play-count rows mapped to the listensmith contract's baseline document.

Pure: no I/O, no clock, and no process. The mapping is applied field by field in
`track_entry`: a value the contract cannot hold is omitted, never invented, and
a track with no name or no artist is excluded and counted by `build_document`, never
given a placeholder. The run supplies ``captured_at``, the version, and, in tests, a
named time zone; with none, a played date is read through the machine's own rules.
"""

from __future__ import annotations

import enum
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from types import MappingProxyType

from baseline_rows import RawTrack

#: The ``submission_client`` every document names: this tool.
SUBMISSION_CLIENT = "play_count_baseline"
#: The contract's ``baseline_type`` for a play-count snapshot.
BASELINE_TYPE = "play_counts"
#: The date parts' shape, ``Y/M/D/seconds-after-midnight``, in ASCII digits only.
_DATE_PARTS = re.compile(r"([0-9]{1,4})/([0-9]{1,2})/([0-9]{1,2})/([0-9]{1,5})")
#: Seconds in a day: seconds after midnight must stay below it.
_DAY_SECONDS = 86400
_HOUR_SECONDS = 3600
_MINUTE_SECONDS = 60
#: The contract's ``listened_at`` range: ListenBrainz's earliest, to 9999-12-31 UTC.
_LISTENED_AT_MIN = 1033430400
_LISTENED_AT_MAX = 253402300799
#: The contract's ``duration_ms`` ceiling, 24 days in milliseconds.
_DURATION_MS_MAX = 2073600000
#: The contract's ``ls_disc_number`` and ``ls_year`` ranges, inclusive.
_DISC_RANGE = (1, 999)
_YEAR_RANGE = (1000, 9999)

#: The keys a track may lack, in the mapping table's order; the summary counts each.
OPTIONAL_KEYS: tuple[str, ...] = (
    "release_name",
    "ls_album_artist",
    "ls_disc_number",
    "duration_ms",
    "last_played_at",
    "ls_genre",
    "ls_year",
    "ls_file_path",
)


class Exclusion(enum.Enum):
    """Why a track was left out of the document: a required text value was empty."""

    NO_NAME = "no name"
    NO_ARTIST = "no artist"


@dataclass(frozen=True)
class Summary:
    """What a document holds against what was read.

    ``excluded`` counts every `Exclusion` (zero included); ``missing`` counts, for
    each of `OPTIONAL_KEYS`, how many written tracks lack it. Both are read-only.
    """

    read: int
    written: int
    excluded: Mapping[Exclusion, int]
    missing: Mapping[str, int]


def local_to_unix(parts: str, *, zone: tzinfo | None = None) -> int | None:
    """Unix seconds for wall-clock date parts, or None for ``""`` or malformed parts.

    With *zone* None the machine's own rules for that date apply (daylight saving
    included); otherwise *zone*'s. Seconds after midnight must be below a day's.

    A wall-clock time the zone skips (the spring-forward gap) and one it reads twice
    (the fall-back fold) both take the offset in force just before the transition,
    Python's ``fold=0``: 02:30 on New York's spring-forward day reads as standard time,
    and 01:30 on its fall-back day as the earlier, daylight-time reading.
    """
    found = _DATE_PARTS.fullmatch(parts)
    if found is None:
        return None
    year, month, day, seconds = (int(part) for part in found.groups())
    if seconds >= _DAY_SECONDS:
        return None
    hour, rest = divmod(seconds, _HOUR_SECONDS)
    minute, second = divmod(rest, _MINUTE_SECONDS)
    try:
        moment = datetime(year, month, day, hour, minute, second, tzinfo=zone)
        return int(moment.timestamp())
    except (ValueError, OverflowError, OSError):
        # ValueError: no such date (month 13, February 30, year 0). OverflowError and
        # OSError: the platform's mktime cannot place a naive date that far out.
        return None


def _within(value: int | None, low: int, high: int) -> bool:
    """Whether *value* is present and inside ``low..high`` inclusive."""
    return value is not None and low <= value <= high


def _ranged_values(raw: RawTrack, zone: tzinfo | None) -> dict[str, object]:
    """The track's numeric optional keys, each kept only inside the contract's range."""
    played_at = local_to_unix(raw.played_date, zone=zone)
    candidates: tuple[tuple[str, int | None, int, int], ...] = (
        ("ls_disc_number", raw.disc_number, *_DISC_RANGE),
        ("duration_ms", raw.duration_ms, 0, _DURATION_MS_MAX),
        ("last_played_at", played_at, _LISTENED_AT_MIN, _LISTENED_AT_MAX),
        ("ls_year", raw.year, *_YEAR_RANGE),
    )
    return {
        key: value for key, value, low, high in candidates if _within(value, low, high)
    }


def _text_values(raw: RawTrack) -> dict[str, object]:
    """The track's optional text keys, each kept only when non-empty."""
    album_artist = "" if raw.album_artist == raw.artist else raw.album_artist
    candidates = (
        ("release_name", raw.album),
        ("ls_album_artist", album_artist),
        ("ls_genre", raw.genre),
        ("ls_file_path", raw.path),
    )
    return {key: value for key, value in candidates if value}


# fuzz-target
def track_entry(
    raw: RawTrack, *, zone: tzinfo | None = None
) -> dict[str, object] | Exclusion:
    """One baseline track for *raw*, or the `Exclusion` that keeps it out.

    The required keys and the persistent ID are always written; every optional key
    only when the contract can hold its value.
    """
    if not raw.name:
        return Exclusion.NO_NAME
    if not raw.artist:
        return Exclusion.NO_ARTIST
    entry: dict[str, object] = {
        "track_name": raw.name,
        "artist_name": raw.artist,
        "play_count": raw.played_count,
        "ls_persistent_id": raw.persistent_id,
    }
    entry.update(_text_values(raw))
    entry.update(_ranged_values(raw, zone))
    return entry


def build_document(
    rows: Sequence[RawTrack],
    *,
    captured_at: int,
    version: str,
    zone: tzinfo | None = None,
) -> tuple[dict[str, object], Summary]:
    """The baseline document for *rows*, tracks sorted by persistent ID, and its summary.

    An empty ``tracks`` list is returned as is: refusing it is the run's decision.
    """
    tracks: list[dict[str, object]] = []
    excluded: Counter[Exclusion] = Counter(dict.fromkeys(Exclusion, 0))
    for raw in sorted(rows, key=lambda track: track.persistent_id):
        entry = track_entry(raw, zone=zone)
        if isinstance(entry, Exclusion):
            excluded[entry] += 1
        else:
            tracks.append(entry)
    missing = {key: sum(key not in track for track in tracks) for key in OPTIONAL_KEYS}
    document: dict[str, object] = {
        "baseline_type": BASELINE_TYPE,
        "captured_at": captured_at,
        "submission_client": SUBMISSION_CLIENT,
        "submission_client_version": version,
        "tracks": tracks,
    }
    summary = Summary(
        read=len(rows),
        written=len(tracks),
        excluded=MappingProxyType(dict(excluded)),
        missing=MappingProxyType(missing),
    )
    return document, summary
