"""The entry point never prints a library value: not in a summary, a refusal, or a failure.

A failed Music.app call's reason is osascript's last stderr line, and AppleScript's
runtime errors quote the value they failed on, so each failure here plants an invented
title and path in what the fake answers and asserts that neither reaches the tool's
stderr, while the call's stage and its error number do. Every refusal of a library's
answer is held to the same bar.
"""

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import baseline_fixtures as bf  # noqa: E402 - import follows the sys.path bootstrap above
import baseline_map  # noqa: E402 - import follows the sys.path bootstrap above
import music_calls  # noqa: E402 - import follows the sys.path bootstrap above
from baseline_cli_fixtures import CANNOT, REFUSED, SECOND, CliCase, Outcome  # noqa: E402 - bootstrap above

#: An invented title and path, planted where a real one could appear.
_TITLE = "Invented Secret Title"
_PATH = "/Invented/Secret/Folder/Invented Secret Title.m4a"
#: osascript's last stderr line for a coercion failure quoting both, with its number.
_QUOTING_ERROR = (
    f'execution error: Can\'t make "{_TITLE}" of "{_PATH}" into type text. (-1700)'
)
#: The stage each kind of call is named by.
_STAGES = {
    bf.IS_RUNNING: "the probe",
    bf.COUNT: "the count",
    bf.LIST: "the list of tracks 1-2",
}
#: Two invented tracks; the second's values are the planted ones.
_PLANTED = dataclasses.replace(
    SECOND, name=_TITLE, path=_PATH, persistent_id="AAAAAAAAAAAAAAAA"
)
_LIBRARY = (bf.INVENTED_TRACK, _PLANTED)


class _QuietCase(CliCase):
    """A run whose stderr must hold no planted or invented library value."""

    def assert_no_value(self, result: Outcome) -> None:
        """Neither the planted values nor any invented track's text reached stderr."""
        for track in _LIBRARY:
            for value in (track.name, track.artist, track.album, track.path):
                if value:
                    with self.subTest(value=value):
                        self.assertNotIn(value, result.stderr)
        self.assertNotIn("Secret", result.stderr)
        self.assertFalse(self.target.exists())


class FailedCallTest(_QuietCase):
    """A failed call names its stage, its class, and its error number; never its text."""

    def test_a_quoting_error_of_each_kind_prints_no_value(self) -> None:
        failed = bf.completed(returncode=1, stderr=f"noise\n{_QUOTING_ERROR}\n")
        for kind, stage in _STAGES.items():
            with self.subTest(kind=kind):
                music = bf.FakeMusic(tracks=_LIBRARY, answers={(kind, 1): failed})
                result = self.run_main(music)
                self.assertEqual(result.code, CANNOT)
                self.assertIn(stage, result.stderr)
                self.assertIn("failed", result.stderr)
                self.assertIn("-1700", result.stderr)
                self.assert_no_value(result)

    def test_the_recount_is_its_own_stage(self) -> None:
        failed = bf.completed(returncode=1, stderr=_QUOTING_ERROR)
        music = bf.FakeMusic(tracks=_LIBRARY, answers={(bf.COUNT, 2): failed})
        result = self.run_main(music)
        self.assertEqual(result.code, CANNOT)
        self.assertIn("the recount", result.stderr)
        self.assert_no_value(result)

    def test_an_unexpected_reply_s_excerpt_is_not_printed(self) -> None:
        music = bf.FakeMusic(
            tracks=_LIBRARY, answers={(bf.COUNT, 1): bf.completed(f"{_TITLE}\n")}
        )
        result = self.run_main(music)
        self.assertEqual(result.code, CANNOT)
        self.assertIn("the count", result.stderr)
        self.assertIn("no error number", result.stderr)
        self.assert_no_value(result)

    def test_a_timeout_is_named_as_one(self) -> None:
        music = bf.FakeMusic(
            tracks=_LIBRARY,
            answers={(bf.LIST, 1): music_calls.CallTimedOut(_QUOTING_ERROR)},
        )
        result = self.run_main(music)
        self.assertEqual(result.code, CANNOT)
        self.assertIn("timed out", result.stderr)
        self.assertIn("the list of tracks 1-2", result.stderr)
        self.assert_no_value(result)


class RefusalTest(_QuietCase):
    """Every refusal of the library's answer is counts and paths into the document only."""

    def test_a_changed_count_prints_no_value(self) -> None:
        music = bf.FakeMusic(
            tracks=_LIBRARY, answers={(bf.COUNT, 2): bf.completed("3\n")}
        )
        result = self.run_main(music)
        self.assertEqual(result.code, REFUSED)
        self.assert_no_value(result)

    def test_a_short_batch_prints_no_value(self) -> None:
        reply = bf.completed(bf.row_of(_PLANTED) + "\n")
        music = bf.FakeMusic(tracks=_LIBRARY, answers={(bf.LIST, 1): reply})
        result = self.run_main(music)
        self.assertEqual(result.code, REFUSED)
        self.assert_no_value(result)

    def test_an_unparsed_row_prints_no_value(self) -> None:
        reply = bf.completed(bf.row_of(bf.INVENTED_TRACK) + f"{_TITLE}\t{_PATH}\n\n")
        music = bf.FakeMusic(tracks=_LIBRARY, answers={(bf.LIST, 1): reply})
        result = self.run_main(music)
        self.assertEqual(result.code, REFUSED)
        self.assert_no_value(result)

    def test_schema_findings_print_no_value(self) -> None:
        real_build = baseline_map.build_document

        def build_invalid(
            *args: object, **kwargs: object
        ) -> tuple[dict[str, object], baseline_map.Summary]:
            # A pass-through wrapper: the arguments are build_document's own, forwarded
            # unchanged, so typing them object here loses nothing the call checks.
            document, summary = real_build(*args, **kwargs)  # type: ignore[arg-type]
            tracks = document["tracks"]
            assert isinstance(tracks, list)
            tracks[0]["ls_year"] = _PATH
            tracks[0]["unknown_key"] = _TITLE
            return document, summary

        with mock.patch.object(baseline_map, "build_document", build_invalid):
            result = self.run_main(bf.FakeMusic(tracks=_LIBRARY))
        self.assertEqual(result.code, REFUSED)
        self.assertIn("$.tracks[0]", result.stderr)
        self.assert_no_value(result)

    def test_an_empty_answer_prints_no_value(self) -> None:
        nameless = dataclasses.replace(_PLANTED, name="")
        result = self.run_main(bf.FakeMusic(tracks=[nameless]))
        self.assertEqual(result.code, REFUSED)
        self.assert_no_value(result)


if __name__ == "__main__":
    unittest.main()
