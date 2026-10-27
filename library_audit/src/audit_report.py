"""The audit's record, its text and JSON forms, and the exit code it ends with.

Pure: `Audit` is what a finished run found, and each function turns it into text,
JSON or a code; the entry point writes the result. The text report's wording is the
companion doc's, and the suites pin it whole. Every text line is shown through
`html_page.shown`, the shared escape, since a file, folder, album or artist name is text this tool
did not write: a control character in one would break a line in two, or drive the
terminal. JSON escapes such characters itself. The HTML page is `audit_html`'s, from
`report_dict`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from audit_checks import CountDiffers, Gap, missing_ranges
from audit_groups import Group, group_label
from audit_rows import TrackRow
from audit_splits import Split
from audit_sync import SizeDiffers, SyncResult
from audit_walk import Unreadable
from html_page import shown

#: Exit codes: clean, findings, could not start (or run), Ctrl-C.
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130
#: The JSON report's schema number, raised whenever a key changes meaning or goes.
#: 2: gaps and count differences are per album group, not per folder, and
#: ``no_track_number`` is its own list. 3: ``split_albums`` names each album split by a
#: spelling difference, and its halves leave ``track_gaps``. 4: the sync checks'
#: keys, and ``unreadable_paths`` also holds the files the access check refuses.
SCHEMA = 4
#: The line standing in for every tag check when mutagen cannot be imported.
TAGS_SKIPPED = "tag checks skipped: mutagen not installed"
#: The line standing in for the decode section when ``--decode`` was not given.
DECODE_NOT_RUN = "decode check not run (--decode)"
#: What the sync checks cannot see, said once after their sections.
MAC_ONLY = (
    "the sync checks see this Mac only: Music.app cannot see an iPhone, so a track"
    " the phone lists but cannot play is not found here"
)
#: Each sync section's note, shown under it when it lists anything.
_PLACEHOLDER_NOTE = (
    "a placeholder's audio is not on this Mac, so a Finder sync cannot copy it"
)
_SIZE_NOTE = "Music.app's record is stale; tag_refresh makes it reread the file"
_UNCHECKED_NOTE = (
    "an unchecked track is skipped only when the phone syncs only checked songs"
)
_DECODE_NOTE = (
    "afconvert tolerates some damage, so a file that decodes is not proven sound"
)
#: The location shown for a gone track that has no file at all.
_NO_LOCATION = "no location"


@dataclass(frozen=True)
class Audit:
    """What one audit found, every list already in report order.

    ``gaps``, ``splits``, ``no_track_number`` and ``unreadable_tags`` are None when
    the tag checks were skipped. A split album's spellings are in ``splits`` only, and
    never in ``gaps``: the numbers it still lacks are its own.
    ``music_tracks`` is the count Music.app gave; ``unparsed_rows`` the listing lines
    in no row's shape, each a track the audit could not place. ``sync`` is what the
    sync checks found; its refused files are shown among ``unreadable_paths``.
    """

    library: Path
    audio_files: int
    music_tracks: int
    no_track: tuple[Path, ...]
    file_gone: tuple[TrackRow, ...]
    gaps: tuple[Gap, ...] | None
    splits: tuple[Split, ...] | None
    no_track_number: tuple[Path, ...] | None
    count_differs: tuple[CountDiffers, ...]
    unreadable_tags: tuple[Path, ...] | None
    unreadable_paths: tuple[Unreadable, ...]
    unparsed_rows: int
    cloud_only: int
    outside_library: int
    sync: SyncResult


def unreadable_of(audit: Audit) -> tuple[Unreadable, ...]:
    """Every folder and file that could not be read, the refused ones too, by path."""
    return tuple(
        sorted((*audit.unreadable_paths, *audit.sync.refused), key=lambda u: u.path)
    )


def finding_count(audit: Audit) -> int:
    """How many findings *audit* holds: each listed item, and each unparsed row."""
    listed = (
        audit.no_track,
        audit.file_gone,
        audit.gaps or (),
        audit.splits or (),
        audit.no_track_number or (),
        audit.count_differs,
        audit.unreadable_tags or (),
        unreadable_of(audit),
        audit.sync.placeholders,
        audit.sync.size_differs,
        audit.sync.unchecked,
        audit.sync.decoded.failed if audit.sync.decoded else (),
    )
    return sum(len(items) for items in listed) + audit.unparsed_rows


def exit_code(audit: Audit) -> int:
    """1 when *audit* found anything, else 0."""
    return EXIT_FINDINGS if finding_count(audit) else EXIT_OK


# --- Text ----------------------------------------------------------------------------


def _section(header: str, items: Iterable[str]) -> list[str]:
    """A header with its count, then each item indented."""
    lines = [f"  {item}" for item in items]
    return [f"{header}: {len(lines)}", *lines]


def _noted(header: str, items: Iterable[str], note: str) -> list[str]:
    """A section with its note under it, when it lists anything."""
    lines = _section(header, items)
    return [*lines, f"  note: {note}"] if len(lines) > 1 else lines


def _track_label(row: TrackRow) -> str:
    """Who, which album, and which disc and track a listed track is."""
    return f"{row.artist} / {row.album}, disc {row.disc} track {row.track}"


def _gone_line(row: TrackRow) -> str:
    """One gone track: who, which album, which disc and track, its status and its path."""
    return f"{_track_label(row)} [{row.cloud_status}]: {row.path or _NO_LOCATION}"


def _gap_line(gap: Gap) -> str:
    """One group's holes, and the counts that found them."""
    tag = (
        "no track-count tag"
        if gap.track_count is None
        else f"track-count tag {gap.track_count}"
    )
    return f"{group_label(gap.group)}: missing {missing_ranges(gap.missing)} (files {gap.files}, {tag})"


def _numbered(numbers: Sequence[int]) -> str:
    """*numbers* as ``track 4`` or ``tracks 1-3, 5``."""
    noun = "track" if len(numbers) == 1 else "tracks"
    return f"{noun} {missing_ranges(numbers)}"


def _split_lines(split: Split) -> list[str]:
    """One split album: a header naming it, each spelling, then how the spellings differ.

    Spellings are numbered from 1, and each difference names its two by number; the
    header ends with the numbers the joined album still lacks, when it lacks any.
    """
    lacking = (
        f", still missing {missing_ranges(split.missing)}" if split.missing else ""
    )
    header = (
        f"{group_label(split.spellings[0].group)}:"
        f" {len(split.spellings)} spellings{lacking}"
    )
    spellings = [
        f"  {n}. {s.group.artist} / {s.group.album}: {_numbered(s.tracks)}"
        for n, s in enumerate(split.spellings, 1)
    ]
    differences = [
        f"  {d.first + 1} and {d.second + 1} differ in the {name}: {note}"
        for d in split.differences
        for name, note in (("artist", d.artist), ("album", d.album))
        if note is not None
    ]
    return [header, *spellings, *differences]


def _split_section(splits: Sequence[Split]) -> list[str]:
    """The split albums' section: its count of albums, then each album's lines."""
    lines = [f"  {line}" for split in splits for line in _split_lines(split)]
    return [f"albums split by spelling: {len(splits)}", *lines]


def _tag_sections(audit: Audit) -> list[str]:
    """The gap, split and no-track-number sections, or one line saying they were skipped."""
    if audit.gaps is None or audit.splits is None or audit.no_track_number is None:
        return [TAGS_SKIPPED]
    return [
        *_section("track-number gaps", map(_gap_line, audit.gaps)),
        *_split_section(audit.splits),
        *_section("files with no track number", map(str, audit.no_track_number)),
    ]


def _size_line(found: SizeDiffers) -> str:
    """One size out of step: the file, and the two sizes."""
    return f"{found.path}: Music.app {found.music_size}, file {found.file_size}"


def _decode_sections(audit: Audit) -> list[str]:
    """The decode's section and its skipped count, or one line saying it did not run."""
    decoded = audit.sync.decoded
    if decoded is None:
        return [DECODE_NOT_RUN]
    failed = (f"{f.path}: {f.reason}" for f in decoded.failed)
    return [
        *_noted("files that do not decode", failed, _DECODE_NOTE),
        f"decode skipped: {decoded.skipped}"
        " (iCloud placeholders and files that cannot be read)",
    ]


def _sync_sections(audit: Audit) -> list[str]:
    """The sync checks' sections, then the line saying what they cannot see."""
    sync = audit.sync
    unchecked = (f"{_track_label(r)}: {r.path or _NO_LOCATION}" for r in sync.unchecked)
    return [
        *_noted("iCloud placeholders", map(str, sync.placeholders), _PLACEHOLDER_NOTE),
        *_noted(
            "Music.app size differs from the file",
            map(_size_line, sync.size_differs),
            _SIZE_NOTE,
        ),
        *_noted("unchecked tracks", unchecked, _UNCHECKED_NOTE),
        *_decode_sections(audit),
        MAC_ONLY,
    ]


def _summary(audit: Audit) -> str:
    """The closing line: findings, what was compared, and the tallies."""
    return (
        f"summary: findings {finding_count(audit)}; audio files {audit.audio_files},"
        f" Music.app tracks {audit.music_tracks}; cloud-only {audit.cloud_only},"
        f" outside --library {audit.outside_library}, unparsed rows {audit.unparsed_rows},"
        f" sizes unknown {audit.sync.sizes_unknown}"
    )


def format_text(audit: Audit) -> str:
    """The text report: a section per check, then the summary line."""
    lines = [f"library: {audit.library}"]
    lines += _section("files with no Music.app track", map(str, audit.no_track))
    lines += _section(
        "Music.app tracks whose file is gone", map(_gone_line, audit.file_gone)
    )
    lines += _tag_sections(audit)
    lines += _section(
        "files and Music.app tracks differ",
        (
            f"{group_label(d.group)}: files {d.files}, Music.app tracks {d.tracks}"
            for d in audit.count_differs
        ),
    )
    if audit.unreadable_tags is not None:
        lines += _section("unreadable tags", map(str, audit.unreadable_tags))
    lines += _section(
        "unreadable files and folders",
        (f"{u.path}: {u.reason}" for u in unreadable_of(audit)),
    )
    lines += _sync_sections(audit)
    lines.append(_summary(audit))
    return "".join(f"{shown(line)}\n" for line in lines)


# --- JSON ----------------------------------------------------------------------------


def _track_json(row: TrackRow) -> dict[str, object]:
    """One listed track as JSON: who, which album, disc and track, and where."""
    return {
        "persistent_id": row.persistent_id,
        "artist": row.artist,
        "album": row.album,
        "disc": row.disc,
        "track": row.track,
        "location": row.path,
    }


def _sync_json(sync: SyncResult) -> dict[str, object]:
    """The sync checks' keys; the decode's two are null when it did not run."""
    decoded = sync.decoded
    return {
        "icloud_placeholders": [str(p) for p in sync.placeholders],
        "size_differs": [
            {
                "path": str(d.path),
                "persistent_id": d.row.persistent_id,
                "music_size": d.music_size,
                "file_size": d.file_size,
            }
            for d in sync.size_differs
        ],
        "unchecked": [_track_json(r) for r in sync.unchecked],
        "sizes_unknown": sync.sizes_unknown,
        "decode_failed": None
        if decoded is None
        else [{"path": str(f.path), "reason": f.reason} for f in decoded.failed],
        "decode_skipped": None if decoded is None else decoded.skipped,
    }


def _gone_json(row: TrackRow) -> dict[str, object]:
    """One gone track as JSON: a listed track, with its cloud status."""
    return {**_track_json(row), "cloud_status": row.cloud_status}


def _group_json(group: Group) -> dict[str, object]:
    """Which group, as JSON: by tags (folder null) or by folder (the names null)."""
    if group.folder is not None:
        return {
            "grouped_by": "folder",
            "artist": None,
            "album": None,
            "disc": None,
            "folder": str(group.folder),
        }
    return {
        "grouped_by": "tags",
        "artist": group.artist,
        "album": group.album,
        "disc": group.disc,
        "folder": None,
    }


def _gap_json(gap: Gap) -> dict[str, object]:
    """One group's holes as JSON; a gap's group is always a tag group."""
    return {
        "artist": gap.group.artist,
        "album": gap.group.album,
        "disc": gap.group.disc,
        "missing": list(gap.missing),
        "files": gap.files,
        "track_count": gap.track_count,
    }


def _split_json(split: Split) -> dict[str, object]:
    """One split album as JSON; ``between`` indexes its ``spellings`` from 0."""
    return {
        "disc": split.disc,
        "spellings": [
            {"artist": s.group.artist, "album": s.group.album, "tracks": list(s.tracks)}
            for s in split.spellings
        ],
        "still_missing": list(split.missing),
        "differs": [
            {"between": [d.first, d.second], "artist": d.artist, "album": d.album}
            for d in split.differences
        ],
    }


def report_dict(audit: Audit) -> dict[str, object]:
    """The JSON report before it is serialized: the text report's content, keyed.

    The HTML page is rendered from this same object, so the two can never disagree.
    """
    return {
        "schema": SCHEMA,
        "library": str(audit.library),
        "audio_files": audit.audio_files,
        "music_tracks": audit.music_tracks,
        "findings": finding_count(audit),
        "no_track": [str(p) for p in audit.no_track],
        "file_gone": [_gone_json(r) for r in audit.file_gone],
        "track_gaps": None
        if audit.gaps is None
        else [_gap_json(g) for g in audit.gaps],
        "split_albums": None
        if audit.splits is None
        else [_split_json(s) for s in audit.splits],
        "no_track_number": (
            None
            if audit.no_track_number is None
            else [str(p) for p in audit.no_track_number]
        ),
        "count_differs": [
            {**_group_json(d.group), "files": d.files, "tracks": d.tracks}
            for d in audit.count_differs
        ],
        "unreadable_tags": (
            None
            if audit.unreadable_tags is None
            else [str(p) for p in audit.unreadable_tags]
        ),
        "unreadable_paths": [
            {"path": str(u.path), "reason": u.reason} for u in unreadable_of(audit)
        ],
        "unparsed_rows": audit.unparsed_rows,
        "cloud_only": audit.cloud_only,
        "outside_library": audit.outside_library,
        **_sync_json(audit.sync),
    }


def format_json(audit: Audit) -> str:
    """The JSON report: `report_dict`, keyed as the companion doc lists."""
    # ensure_ascii, the default, escapes every non-ASCII character and lone surrogate,
    # so the report is plain ASCII whatever names it holds.
    return json.dumps(report_dict(audit), indent=2) + "\n"
