"""One live, read-only listing against the real Music.app, for the audit's two scripts.

Every other suite reads `COUNT_TRACKS_SCRIPT` and `LIST_TRACKS_SCRIPT` as text and
plays a fake ``osascript``, which proves what the audit sends and nothing about what
Music answers. This file makes the two real calls the audit makes first: the count,
then one listing of at most the first `_MAX_TRACKS` tracks, parsed by the audit's own
row parser, `audit_rows`.

**Read-only by construction.** Both scripts only read track properties, and the only
other call is `is_running`, which never launches Music.

**Shape only.** It asserts that the count is a non-negative integer, that every row
has the listing's field count and parses, and that the rows number the range asked
for. No track, album or artist name and no count from the library is asserted,
printed or kept: a failure names row positions and counts of bad rows, never a row's
text.

It runs only when every one of these holds, and skips otherwise:

- ``LIBRARY_AUDIT_LIVE`` is ``1``: whoever runs it chose to read their library;
- ``APPLE_MUSIC_TOOLBOX_OFFLINE`` is unset: the project's one switch for every live
  boundary, which the export sets on every run of its suite;
- the platform is macOS, where Music.app and ``osascript`` exist;
- Music.app is running, asked through `is_running` itself.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE.parent), str(_HERE.parent / "src")]

import library_audit as la  # noqa: E402 - import follows the sys.path bootstrap above
import audit_rows  # noqa: E402 - import follows the sys.path bootstrap above
import music_calls  # noqa: E402 - import follows the sys.path bootstrap above

#: The switch that runs this test, and the value that turns it on.
_SWITCH = "LIBRARY_AUDIT_LIVE"
_ON = "1"
#: The project's "no live boundary" switch, which skips this test whatever _SWITCH says.
_OFFLINE = "APPLE_MUSIC_TOOLBOX_OFFLINE"
#: The most tracks the live listing asks for: enough to meet several row shapes, few
#: enough to be one quick call.
_MAX_TRACKS = 50
#: The listing's fields a row, one per `TrackRow` field.
_FIELDS = len(dataclasses.fields(audit_rows.TrackRow))
#: The row terminator and field separator the listing writes.
_TERMINATOR, _SEPARATOR = "\n", "\t"
#: The error number ending an osascript failure, the one part of it a report may show.
_ERROR_NUMBER = re.compile(r"\((-?[0-9]+)\)\s*$")


def shape_problems(reply: str, asked: int) -> list[str]:
    """What is wrong with *reply* as the listing of *asked* tracks; empty when nothing.

    Each problem names a row's position or a count, never a row's text, so a failure
    can be shown without showing the library.
    """
    *terminated, _tail = reply.split(_TERMINATOR)
    segments = [segment for segment in terminated if segment]
    problems = [
        f"row {position} has {count} field(s), not {_FIELDS}"
        for position, count in enumerate(
            (segment.count(_SEPARATOR) + 1 for segment in segments), start=1
        )
        if count != _FIELDS
    ]
    parsed = audit_rows.parse_track_rows(reply)
    if parsed.unparsed:
        problems.append(f"{parsed.unparsed} row(s) audit_rows could not parse")
    if len(parsed.rows) != asked:
        problems.append(
            f"audit_rows parsed {len(parsed.rows)} row(s) for {asked} asked"
        )
    return problems


def error_number_of(reason: str) -> str:
    """The error number ending *reason*, or "none", for a failure that hides the rest."""
    found = _ERROR_NUMBER.search(reason)
    return found.group(1) if found else "none"


@unittest.skipUnless(sys.platform == "darwin", "Music.app is macOS-only")
@unittest.skipIf(_OFFLINE in os.environ, f"{_OFFLINE} is set - live listing skipped")
@unittest.skipUnless(
    os.environ.get(_SWITCH) == _ON, f"set {_SWITCH}=1 to read the real library"
)
class LiveTest(unittest.TestCase):  # pragma: no cover - runs only against Music.app
    """The real count and one real listing, checked for their shape alone."""

    def setUp(self) -> None:
        """Skip unless Music.app is running; the probe never launches it."""
        try:
            running = music_calls.is_running(run=music_calls.real_run)
        except music_calls.MusicCallError as exc:
            # Its error number alone, as _read reports a failure: the reason is
            # osascript's message, which this module never prints.
            number = error_number_of(exc.reason)
            self.skipTest(f"cannot ask whether Music.app is running: error {number}")
        if not running:
            self.skipTest("Music.app is not running")

    def _read(self) -> tuple[int, str, int]:
        """The count, the listing of the first tracks, and how many were asked.

        A failed call fails the test naming only its kind and error number: its
        reason is osascript's message, which could quote the library.
        """
        try:
            total = music_calls.count_tracks(run=music_calls.real_run)
            asked = min(_MAX_TRACKS, total)
            if not asked:
                return total, "", 0
            reply = music_calls.list_tracks(1, asked, run=music_calls.real_run)
        except music_calls.MusicCallError as exc:
            self.fail(f"{type(exc).__name__}, error {error_number_of(exc.reason)}")
        return total, reply, asked

    def test_the_count_and_first_tracks_answer_in_the_audit_s_shape(self) -> None:
        total, reply, asked = self._read()
        self.assertIsInstance(total, int)
        self.assertGreaterEqual(total, 0, "the count is negative")
        if not asked:
            self.skipTest("the library holds no tracks to list")
        problems = shape_problems(reply, asked)
        self.assertFalse(problems, "; ".join(problems))


class ShapeProblemsTest(unittest.TestCase):
    """The live test's checker, against invented replies: it names faults, not text."""

    _NAME = "Invented Name"

    def _row(self, *, fields: int = _FIELDS) -> str:
        """One invented, well-formed row, cut or padded to *fields* fields."""
        values = [
            "0123456789ABCDEF",
            "matched",
            "1",
            "2",
            "/invented/path.mp3",
            self._NAME,
            self._NAME,
            "false",
            audit_rows.FILE_TRACK,
            "true",
            "1234",
        ]
        values = (values + ["extra"] * fields)[:fields]
        return _SEPARATOR.join(values) + _TERMINATOR

    def test_the_invented_row_is_one_audit_rows_parses(self) -> None:
        parsed = audit_rows.parse_track_rows(self._row())
        self.assertEqual((len(parsed.rows), parsed.unparsed), (1, 0))

    def test_a_listing_of_every_track_asked_has_no_problem(self) -> None:
        self.assertEqual(shape_problems(self._row() * 3 + _TERMINATOR, 3), [])

    def test_a_row_short_of_a_field_is_named_by_position_and_counted(self) -> None:
        reply = self._row() + self._row(fields=_FIELDS - 1)
        self.assertEqual(
            shape_problems(reply, 2),
            [
                f"row 2 has {_FIELDS - 1} field(s), not {_FIELDS}",
                "1 row(s) audit_rows could not parse",
                "audit_rows parsed 1 row(s) for 2 asked",
            ],
        )

    def test_a_listing_short_of_the_range_is_counted(self) -> None:
        self.assertEqual(
            shape_problems(self._row(), 2), ["audit_rows parsed 1 row(s) for 2 asked"]
        )

    def test_no_problem_quotes_a_row(self) -> None:
        reply = self._row(fields=_FIELDS + 1) + "cut short"
        problems = shape_problems(reply, 3)
        self.assertTrue(problems)
        self.assertFalse([text for text in problems if self._NAME in text])

    def test_the_live_range_is_one_audit_batch(self) -> None:
        self.assertLessEqual(_MAX_TRACKS, la.BATCH_TRACKS)


class ErrorNumberTest(unittest.TestCase):
    """A failed call is reported by its error number alone."""

    def test_the_trailing_number_is_kept(self) -> None:
        self.assertEqual(
            error_number_of("Music got an error: invented. (-1728)"), "-1728"
        )

    def test_a_reason_with_no_number_says_none(self) -> None:
        self.assertEqual(error_number_of("osascript exited 1"), "none")


def _live_class_under(environ: dict[str, str], platform: str) -> type:
    """`LiveTest` as this file decorates it under *environ* on *platform*.

    The file is loaded afresh under its own module name with the environment and the
    platform patched, so the decorators are evaluated again. Only the class's skip
    markers are read: no test of it is run, so nothing here reaches Music.app.
    """
    location = importlib.util.spec_from_file_location(
        "_audit_live_reloaded", Path(__file__)
    )
    assert location is not None and location.loader is not None
    module = importlib.util.module_from_spec(location)
    # Registered under its own name for the re-evaluation only: a dataclass in the file
    # reads sys.modules[cls.__module__] while its body runs. The skip markers it decides
    # are the same either way, so registering changes nothing this test proves.
    sys.modules[location.name] = module
    try:
        with (
            mock.patch.dict(os.environ, environ, clear=True),
            mock.patch.object(sys, "platform", platform),
        ):
            location.loader.exec_module(module)
    finally:
        del sys.modules[location.name]
    return module.LiveTest


class SkipTest(unittest.TestCase):
    """The live test runs only on macOS, with its switch on and the offline one unset."""

    def assert_skipped(self, environ: dict[str, str], platform: str) -> None:
        live = _live_class_under(environ, platform)
        self.assertTrue(getattr(live, "__unittest_skip__", False))

    def test_it_runs_with_its_switch_on_macos(self) -> None:
        live = _live_class_under({_SWITCH: _ON}, "darwin")
        self.assertFalse(getattr(live, "__unittest_skip__", False))

    def test_it_skips_without_its_switch(self) -> None:
        self.assert_skipped({}, "darwin")

    def test_it_skips_with_its_switch_set_to_anything_but_on(self) -> None:
        self.assert_skipped({_SWITCH: "0"}, "darwin")

    def test_the_offline_switch_skips_it_even_with_its_own_switch_on(self) -> None:
        self.assert_skipped({_SWITCH: _ON, _OFFLINE: "1"}, "darwin")

    def test_it_skips_off_macos(self) -> None:
        self.assert_skipped({_SWITCH: _ON}, "linux")


if __name__ == "__main__":
    unittest.main()
