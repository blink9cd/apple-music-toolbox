"""baseline_calls: the play-count read, sent through tag_refresh's call primitive.

Every runner is a `FakeMusic`, so no test can reach ``osascript`` or Music.app.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import baseline_calls  # noqa: E402 - import follows the sys.path bootstrap above
import baseline_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import baseline_rows  # noqa: E402 - import follows the sys.path bootstrap above
import music_calls  # noqa: E402 - baseline_calls put tag_refresh's src/ on sys.path

#: The script's per-track properties, each read once for the whole range.
_RANGE_PROPERTIES = (
    "class",
    "persistent ID",
    "name",
    "artist",
    "album",
    "album artist",
    "disc number",
    "duration",
    "played count",
    "played date",
    "genre",
    "year",
    "location",
)

#: The lists the row line reads, in the row format's field order, then the path local.
_ROW_ORDER = [
    "trackIDs",
    "trackNames",
    "trackArtists",
    "trackAlbums",
    "albumArtists",
    "discNumbers",
    "trackDurations",
    "playedCounts",
    "playedDates",
    "trackGenres",
    "trackYears",
    "trackPath",
]
#: One field the row line reads: a list's ``item i``, or the path local.
_ROW_FIELD = re.compile(r"item i of (\w+)|\b(trackPath)$")

#: The script's one block that talks to Music.app.
_TELL_BLOCK = re.compile(r'tell application "Music"(.*?)end tell', re.DOTALL)
#: A ``set`` that assigns a script local: ``set <identifier> to``.
_SET_LOCAL = re.compile(r"set\s+([A-Za-z_]\w*)\s+to\b")
#: A ``set`` that appends to a list: ``set end of <identifier> to``.
_SET_APPEND = re.compile(r"set\s+end\s+of\s+([A-Za-z_]\w*)\s+to\b")
#: AppleScript and Music.app commands that change, start, or stop something.
_WRITING_COMMANDS = re.compile(
    r"\b(make|move|add|delete|duplicate|refresh|play|pause|stop|reveal|convert"
    r"|activate|launch|quit)\b"
)


def _row_line(script: str) -> str:
    """The script's one ``set rowText to`` line, stripped."""
    (line,) = [text.strip() for text in script.splitlines() if "set rowText to" in text]
    return line


def _row_fields(line: str) -> list[str]:
    """The names *line* joins into a row, in order."""
    return [a or b for a, b in _ROW_FIELD.findall(line)]


def _write_findings(script: str) -> list[str]:
    """What, inside *script*'s ``tell application "Music"`` block, could write to Music.

    Every ``set`` there must assign a local (``set <identifier> to``) or append to a
    list a ``set`` before it made (``set end of <identifier> to``); any other ``set``,
    such as ``set genre of ...``, writes a property. Every writing command is a finding.
    """
    block = _TELL_BLOCK.search(script)
    if block is None:
        return ["no tell block"]
    body = block.group(1)
    findings: list[str] = []
    locals_made: set[str] = set()
    for found in re.finditer(r"\bset\b", body):
        rest = body[found.start() :]
        local, append = _SET_LOCAL.match(rest), _SET_APPEND.match(rest)
        if local is not None:
            locals_made.add(local.group(1))
        elif append is None or append.group(1) not in locals_made:
            findings.append(rest.splitlines()[0])
    findings += [found.group(0) for found in _WRITING_COMMANDS.finditer(body)]
    return findings


class ListPlayCountsTest(unittest.TestCase):
    """`list_play_counts` sends the one read script with its range as argv."""

    def test_passes_the_range_after_a_double_dash(self) -> None:
        fake = fx.FakeMusic(tracks=[fx.INVENTED_TRACK])
        baseline_calls.list_play_counts(1, 1, run=fake)
        self.assertEqual(fake.calls[-1][3:], ["--", "1", "1"])

    def test_sends_the_play_counts_script(self) -> None:
        fake = fx.FakeMusic(tracks=[fx.INVENTED_TRACK])
        baseline_calls.list_play_counts(1, 1, run=fake)
        self.assertEqual(
            fake.calls[-1][:3], ["osascript", "-e", baseline_calls.PLAY_COUNTS_SCRIPT]
        )

    def test_returns_the_reply_unparsed(self) -> None:
        fake = fx.FakeMusic(tracks=[fx.INVENTED_TRACK])
        reply = baseline_calls.list_play_counts(1, 1, run=fake)
        self.assertEqual(reply, fx.row_of(fx.INVENTED_TRACK) + "\n")

    def test_the_reply_parses_back_to_the_tracks(self) -> None:
        fake = fx.FakeMusic(tracks=[fx.INVENTED_TRACK])
        reply = baseline_calls.list_play_counts(1, 1, run=fake)
        parsed = baseline_rows.parse_play_rows(reply)
        self.assertEqual(parsed, baseline_rows.ParsedRows((fx.INVENTED_TRACK,), 0))

    def test_refuses_a_range_that_cannot_exist_before_calling(self) -> None:
        fake = fx.FakeMusic(tracks=[])
        for first, last in ((0, 1), (2, 1)):
            with self.assertRaises(ValueError):
                baseline_calls.list_play_counts(first, last, run=fake)
        self.assertEqual(fake.calls, [])

    def test_a_failed_call_raises_call_failed(self) -> None:
        failed = fx.completed(returncode=1, stderr="execution error: invented (-1728)")
        fake = fx.FakeMusic(tracks=[fx.INVENTED_TRACK], answers={(fx.LIST, 1): failed})
        with self.assertRaises(music_calls.CallFailed):
            baseline_calls.list_play_counts(1, 1, run=fake)


class PlayCountsScriptTest(unittest.TestCase):
    """The script's text: what it reads, and what it never says to Music."""

    def test_the_script_reads_every_property_once_per_range(self) -> None:
        for prop in (
            "persistent ID",
            "played count",
            "played date",
            "duration",
            "album artist",
            "disc number",
            "genre",
            "year",
            "location",
        ):
            self.assertIn(
                f"{prop} of tracks lowIndex thru highIndex",
                baseline_calls.PLAY_COUNTS_SCRIPT,
            )

    def test_each_range_read_is_one_apple_event(self) -> None:
        for prop in _RANGE_PROPERTIES:
            read = f" to {prop} of tracks lowIndex thru highIndex of library playlist 1"
            self.assertEqual(baseline_calls.PLAY_COUNTS_SCRIPT.count(read), 1, prop)

    def test_the_in_script_bound_is_the_shared_one(self) -> None:
        self.assertIn(
            f"with timeout of {music_calls.IN_SCRIPT_TIMEOUT_SECONDS} seconds",
            baseline_calls.PLAY_COUNTS_SCRIPT,
        )

    def test_a_timeout_on_one_location_is_re_raised(self) -> None:
        self.assertIn(
            "if errorNumber is -1712 then error errorText number errorNumber",
            baseline_calls.PLAY_COUNTS_SCRIPT,
        )

    def test_every_list_is_checked_against_the_persistent_ids(self) -> None:
        lists = (
            "trackClasses",
            "trackNames",
            "trackArtists",
            "trackAlbums",
            "albumArtists",
            "discNumbers",
            "trackDurations",
            "playedCounts",
            "playedDates",
            "trackGenres",
            "trackYears",
            "trackFiles",
        )
        for name in lists:
            self.assertIn(
                f"if (count of {name}) is not expectedLength then error",
                baseline_calls.PLAY_COUNTS_SCRIPT,
                name,
            )

    def test_every_text_field_is_flattened(self) -> None:
        for name in (
            "trackNames",
            "trackArtists",
            "trackAlbums",
            "albumArtists",
            "trackGenres",
        ):
            self.assertIn(
                f"my flatText(item i of {name})", baseline_calls.PLAY_COUNTS_SCRIPT
            )

    def test_date_and_duration_use_the_scrobbler_s_handlers(self) -> None:
        script = baseline_calls.PLAY_COUNTS_SCRIPT
        self.assertIn("my dateParts(item i of playedDates)", script)
        self.assertIn("my milliseconds(item i of trackDurations)", script)
        self.assertIn('if s is greater than or equal to 536870 then return ""', script)

    def test_the_row_joins_the_fields_in_the_row_format_s_order(self) -> None:
        line = _row_line(baseline_calls.PLAY_COUNTS_SCRIPT)
        self.assertEqual(_row_fields(line), _ROW_ORDER)
        self.assertEqual(line.count(" & tab & "), baseline_rows.FIELD_COUNT - 1)

    def test_the_album_artist_has_no_fall_back_to_the_artist(self) -> None:
        self.assertNotIn("artistName", baseline_calls.PLAY_COUNTS_SCRIPT)

    def test_it_never_writes_to_music(self) -> None:
        self.assertEqual(_write_findings(baseline_calls.PLAY_COUNTS_SCRIPT), [])


class WriteGuardTest(unittest.TestCase):
    """`_write_findings` itself catches each way a copy of the script could write."""

    def _planted(self, line: str) -> str:
        """The real script with *line* planted inside its ``tell`` block."""
        anchor = "            set trackYears to"
        script = baseline_calls.PLAY_COUNTS_SCRIPT
        self.assertIn(anchor, script)
        return script.replace(anchor, f"            {line}\n{anchor}", 1)

    def test_a_property_set_is_a_finding(self) -> None:
        planted = self._planted('set genre of track 1 of library playlist 1 to "x"')
        self.assertEqual(
            _write_findings(planted),
            ['set genre of track 1 of library playlist 1 to "x"'],
        )

    def test_an_append_to_a_list_no_set_made_is_a_finding(self) -> None:
        planted = self._planted("set end of tracks to missing value")
        self.assertEqual(
            _write_findings(planted), ["set end of tracks to missing value"]
        )

    def test_each_writing_command_is_a_finding(self) -> None:
        for command in ("play track 1", "delete track 1", "quit", "launch"):
            with self.subTest(command=command):
                self.assertEqual(
                    _write_findings(self._planted(command)), [command.split()[0]]
                )

    def test_a_script_with_no_tell_block_is_a_finding(self) -> None:
        self.assertEqual(_write_findings("return 1"), ["no tell block"])


if __name__ == "__main__":
    unittest.main()
