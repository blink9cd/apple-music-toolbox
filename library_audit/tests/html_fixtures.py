"""Shared fixtures for the HTML report suites: invented reports and a strict parser.

`report` builds a clean report in the JSON format's shape, `full_report` one with
something in every section, and `Page` is the shared HTML page library's strict parse
(`html_page.ParsedPage`), which fails on any misclosed element and leaves an unclosed
one on its stack. `NOTES` holds each section's note word for word, so a reworded note
fails a test.

Not discovered as a suite (no ``test_`` prefix). Suites import it by bare name with
this directory on ``sys.path``.
"""

from __future__ import annotations

import html_page

#: The invented library folder every report here names.
LIBRARY = "/invented/Library"
#: The notes, one per section, word for word.
NOTES = {
    "split-albums": "One album under two spellings of its artist or title, so"
    " Music.app shows two albums. Give both halves one spelling in your tagger, then"
    " run tag_refresh.",
    "track-gaps": "These albums are missing track numbers: a partial copy, a single"
    " filed with an album, or a split the spelling check could not pair.",
    "no-track": "On disk but never imported. Add them to Music.app, or remove"
    " leftovers.",
    "file-gone": "Music.app points at a file that no longer exists.",
    "no-track-number": "The tags hold no track number.",
    "count-differs": "This album has a different number of files than Music.app"
    " tracks.",
    "unreadable-tags": "The file's tags could not be read.",
    "unreadable-paths": "The tool could not read these.",
    "icloud-placeholders": "The audio is in iCloud only, so a Finder sync cannot"
    " copy it.",
    "size-differs": "Music.app's record is stale; tag_refresh makes it reread the"
    " file.",
    "unchecked": "Skipped only when the phone syncs only checked songs.",
    "decode-failed": "afconvert could not decode these; a pass is not proof a file"
    " is sound.",
    "unparsed-rows": "Listing rows the tool could not read; that part of the picture"
    " is incomplete.",
}


def track(**fields: object) -> dict[str, object]:
    """One listed track as the JSON report holds it."""
    return {
        "persistent_id": "00000000000000A1",
        "artist": "The Placeholder Band",
        "album": "Invented Album",
        "disc": 1,
        "track": 2,
        "location": f"{LIBRARY}/The Placeholder Band/Invented Album/02 b.mp3",
        **fields,
    }


def report(**keys: object) -> dict[str, object]:
    """A clean report, every check run but the decode, with *keys* replaced."""
    report: dict[str, object] = {
        "schema": 4,
        "library": LIBRARY,
        "audio_files": 7,
        "music_tracks": 9,
        "findings": 0,
        "no_track": [],
        "file_gone": [],
        "track_gaps": [],
        "split_albums": [],
        "no_track_number": [],
        "count_differs": [],
        "unreadable_tags": [],
        "unreadable_paths": [],
        "unparsed_rows": 0,
        "cloud_only": 1,
        "outside_library": 2,
        "icloud_placeholders": [],
        "size_differs": [],
        "unchecked": [],
        "sizes_unknown": 3,
        "decode_failed": None,
        "decode_skipped": None,
    }
    report.update(keys)
    return report


def full_report() -> dict[str, object]:
    """A report with something in every section."""
    folder = f"{LIBRARY}/The Placeholder Band/Invented Album"
    return report(
        findings=14,
        no_track=[f"{folder}/04 d.mp3"],
        file_gone=[{**track(), "cloud_status": "local only"}],
        track_gaps=[
            {
                "artist": "The Placeholder Band",
                "album": "Invented Album",
                "disc": 1,
                "missing": [2, 3, 4, 7],
                "files": 3,
                "track_count": 12,
            }
        ],
        split_albums=[
            {
                "disc": 1,
                "spellings": [
                    {"artist": "The Split-Level Duo", "album": "Twin", "tracks": [2]},
                    {
                        "artist": "The Split‐Level Duo",
                        "album": "Twin",
                        "tracks": [1, 3],
                    },
                ],
                "still_missing": [4],
                "differs": [
                    {
                        "between": [0, 1],
                        "artist": "U+002D HYPHEN-MINUS vs U+2010 HYPHEN",
                        "album": None,
                    }
                ],
            }
        ],
        no_track_number=[f"{folder}/Hidden.mp3"],
        count_differs=[
            {
                "grouped_by": "folder",
                "artist": None,
                "album": None,
                "disc": None,
                "folder": folder,
                "files": 1,
                "tracks": 0,
            }
        ],
        unreadable_tags=[f"{folder}/04 d.mp3"],
        unreadable_paths=[{"path": "/elsewhere/locked", "reason": "permission denied"}],
        unparsed_rows=1,
        icloud_placeholders=[f"{folder}/05 e.mp3"],
        size_differs=[
            {
                "path": f"{folder}/01 a.mp3",
                "persistent_id": "00000000000000A2",
                "music_size": 4096,
                "file_size": 10,
            }
        ],
        unchecked=[track(track=6, location="")],
        decode_failed=[{"path": f"{folder}/06 f.mp3", "reason": "decode error"}],
        decode_skipped=0,
    )


#: The strict parse the suites read a page by: one copy, in the shared library.
Page = html_page.ParsedPage
