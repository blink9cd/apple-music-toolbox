"""The field escape, run for real: each script's ``escapedText`` through ``/usr/bin/osascript``.

Every other suite reads the handler as text, and text cannot show how AppleScript
searches it. Its text item search works on whole characters (grapheme clusters), so a
tab or line break followed by a combining mark or a variation selector is one
character to it, and a delimiter search passes it by. Only running the handler shows
what it writes, so this suite is the ground truth for the escape: each handler is
taken from the script that ships it, run on every awkward value the other suites use
and on each delimiter fused with a following mark, and its output must hold no raw
tab, linefeed, carriage return or U+001F and must decode back to its input exactly.

Nothing here reaches Music.app, the network or any library. Each handler is cut out
of its script and run alone, with a ``run`` handler that only calls it, and the cut
text is checked for a ``tell`` and for Music before it runs. That is why it is not
gated on ``APPLE_MUSIC_TOOLBOX_OFFLINE``, which means "no Music.app and no network".
The interpreter is named by its absolute path, so a fake ``osascript`` first on
``PATH`` cannot stand in for it, and the output is read as bytes: a text-mode read
turns a carriage return into a linefeed and would hide the one case it must catch.
"""

from __future__ import annotations

import re
import sys
import unittest
from collections.abc import Callable
from pathlib import Path

_HERE = Path(__file__).resolve().parent
#: The project root: this tool's folder's parent.
_PROJECT = _HERE.parents[1]
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]
sys.path[:0] = [str(_PROJECT / "play_count_baseline" / "src")]
sys.path[:0] = [str(_PROJECT / "recently_added")]

import baseline_calls  # noqa: E402 - import follows the sys.path bootstrap above
import bounded_run  # noqa: E402 - baseline_calls' seam put it on sys.path
import music_calls  # noqa: E402 - import follows the sys.path bootstrap above
import music_calls_list  # noqa: E402 - import follows the sys.path bootstrap above
import recently_added  # noqa: E402 - import follows the sys.path bootstrap above
import script_text  # noqa: E402 - import follows the sys.path bootstrap above
from test_script_text import swift_escape_handler  # noqa: E402 - see the bootstrap

#: macOS ships the AppleScript interpreter here, and only here.
_OSASCRIPT = Path("/usr/bin/osascript")
#: Running a few lines of AppleScript on a few dozen short strings is immediate work
#: with no I/O, so this bounds a hung process rather than a slow one. The long value
#: below must finish inside it too, which a rebuild quadratic in its length did not.
_TIMEOUT_SECONDS = 20.0
#: A long field ending in a tab fused with a combining acute accent, so the whole of it
#: goes through the code-point rebuild. At this length a quadratic rebuild takes well
#: over the bound (about 18 s at half of it, measured under load), while the linear one
#: takes a few seconds even on a loaded machine, so the test is not timing-fragile.
_LONG_FUSED = "x" * 32_000 + "\t" + chr(0x0301)
#: Runs the handler on the one argument, and on nothing else.
_RUN_ONE = "\non run argv\n  return my escapedText(item 1 of argv)\nend run\n"
#: Runs the handler on every argument, one result a line: a correct result holds no
#: linefeed, so a raw one shows as a wrong line count.
_RUN_ALL = """
on run argv
  set escapedValues to {}
  repeat with argument in argv
    set end of escapedValues to my escapedText(contents of argument)
  end repeat
  set AppleScript's text item delimiters to linefeed
  return escapedValues as text
end run
"""
#: Sets the text item delimiters to a sentinel, runs the handler on the one argument
#: and on "", and returns both results, a join that shows the delimiters the handler
#: left, and how many it left, one a line.
_RUN_KEEPS_DELIMITERS = """
on run argv
  set AppleScript's text item delimiters to {"Q"}
  set fusedResult to my escapedText(item 1 of argv)
  set emptyResult to my escapedText("")
  set joined to {"a", "b"} as text
  set delimitersLeft to AppleScript's text item delimiters
  set AppleScript's text item delimiters to linefeed
  return {fusedResult, emptyResult, joined, count of delimitersLeft} as text
end run
"""
#: What a decoded result must never hold raw: each would split or end a row.
_RAW_DELIMITERS = (b"\t", b"\n", b"\r", b"\x1f")
#: The marks that fuse with the character before them into one AppleScript character:
#: a combining acute accent, a variation selector and a zero-width joiner.
_FUSING = (chr(0x0301), chr(0xFE0F), chr(0x200D))
#: An emoji outside the Basic Multilingual Plane, two UTF-16 units and one code point.
_EMOJI = chr(0x1F600)
#: Every awkward value the parsers' suites use, each inside invented text.
_AWKWARD = ("\t", "\n", "\r", "\r\n", "\x1f", "%", "%09", "%25", "%41", "100%")
#: Signs no escape begins, which the decoder keeps.
_LONE = ("%G0", "%0", "%1f", "%" + _FUSING[0] + "09")


def _values() -> list[str]:
    """Every value the handler is run on."""
    fused = [
        delimiter + mark
        for delimiter in ("\t", "\n", "\r", "\r\n", "\x1f")
        for mark in _FUSING
    ]
    plain = [f"Invented{value}Song" for value in (*_AWKWARD, *_LONE, *fused)]
    return [
        *plain,
        *(f"a{value}b" for value in fused),
        "",
        _EMOJI,
        f"a\t{_EMOJI}b",
        f"{_EMOJI}\n{_FUSING[0]}",
        "%" + _FUSING[0],
        "a%" + _FUSING[0] + "\t" + _FUSING[1],
    ]


def handler_in(script: str) -> str:
    """The ``escapedText`` handler *script* holds, with its helper, as one text."""
    found = re.search(
        r"^on escapedText\(.*?^end escapedPoints\n|^on escapedText\(.*?^end escapedText\n",
        script + "\n",
        re.DOTALL | re.MULTILINE,
    )
    if found is None:
        raise AssertionError("the script holds no escapedText handler")
    return found.group(0)


#: Each place a handler ships, by name, and how to take it out.
_SOURCES: dict[str, Callable[[], str]] = {
    "the shared copy": lambda: script_text.ESCAPE_HANDLER,
    "the play-count listing": lambda: handler_in(baseline_calls.PLAY_COUNTS_SCRIPT),
    "the scrobbler's snapshot": swift_escape_handler,
    "the track listing": lambda: handler_in(music_calls_list.LIST_TRACKS_SCRIPT),
    "the album lookup": lambda: handler_in(music_calls.LOOKUP_SCRIPT),
    "the recently added query": lambda: handler_in(recently_added._MUSIC_SCRIPT),
}


def _run(script: str, values: list[str]) -> bytes:
    """What *script* prints for *values* as its argv, as raw bytes, its one linefeed cut."""
    result = bounded_run.run_bounded_bytes(
        [str(_OSASCRIPT), "-e", script, "--", *values], timeout=_TIMEOUT_SECONDS
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace")
        raise AssertionError(f"osascript exited {result.returncode}: {stderr}")
    return result.stdout.removesuffix(b"\n")


def _reads_back(written: bytes, value: str) -> bool:
    """Whether *written* holds no raw delimiter and decodes to *value*."""
    if any(raw in written for raw in _RAW_DELIMITERS):
        return False
    return script_text.unescape_field(written.decode("utf-8")) == value


def _misread_by(handler: str) -> list[str]:
    """Each value *handler* writes a raw delimiter for, or that does not read back.

    One run for every value; only when that run shows a fault is each value run on its
    own, to name the ones at fault.
    """
    values = _values()
    lines = _run(handler + _RUN_ALL, values).split(b"\n")
    if len(lines) == len(values) and all(map(_reads_back, lines, values)):
        return []
    misread = []
    for value in values:
        written = _run(handler + _RUN_ONE, [value])
        if not _reads_back(written, value):
            misread.append(f"{value!r} -> {written!r}")
    return misread


@unittest.skipUnless(sys.platform == "darwin", "AppleScript is macOS-only")
@unittest.skipUnless(_OSASCRIPT.is_file(), f"{_OSASCRIPT} is not installed")
class EscapeRunTest(unittest.TestCase):
    """Each shipped handler writes no raw delimiter and decodes back exactly."""

    maxDiff = None

    def test_no_handler_talks_to_an_application(self) -> None:
        for name, source in _SOURCES.items():
            with self.subTest(name=name):
                handler = source()
                self.assertNotIn("tell application", handler)
                self.assertNotIn("Music", handler)

    def test_every_value_is_escaped_and_reads_back(self) -> None:
        for name, source in _SOURCES.items():
            with self.subTest(name=name):
                self.assertEqual(_misread_by(source()), [])

    def test_a_long_fused_value_is_escaped_in_time(self) -> None:
        # The copies are held equal as text, so one run per distinct text covers each.
        texts = sorted({source() for source in _SOURCES.values()})
        for index, handler in enumerate(texts):
            with self.subTest(distinct_text=index):
                written = _run(handler + _RUN_ONE, [_LONG_FUSED])
                self.assertTrue(_reads_back(written, _LONG_FUSED))

    def test_the_delimiters_are_restored(self) -> None:
        fused = "a\t" + _FUSING[0] + "b"
        written = _run(script_text.ESCAPE_HANDLER + _RUN_KEEPS_DELIMITERS, [fused])
        expected = ["a%09" + _FUSING[0] + "b", "", "aQb", "1"]
        self.assertEqual(written.decode("utf-8").split("\n"), expected)

    def test_the_rebuild_takes_no_points_and_one(self) -> None:
        # `string id {}` crashes osascript (measured: exit 139), so the rebuild must
        # answer an empty list itself. The handler never passes one, but it is cheap.
        calls = '"[" & my escapedPoints({}) & "][" & my escapedPoints({65}) & "]"'
        script = (
            f"{script_text.ESCAPE_HANDLER}\nreturn {calls} & my escapedPoints({{9}})\n"
        )
        self.assertEqual(_run(script, []), b"[][A]%09")

    def test_missing_value_is_empty(self) -> None:
        script = script_text.ESCAPE_HANDLER + "\nreturn my escapedText(missing value)\n"
        result = bounded_run.run_bounded_bytes(
            [str(_OSASCRIPT), "-e", script], timeout=_TIMEOUT_SECONDS
        )
        self.assertEqual((result.returncode, result.stdout), (0, b"\n"))


if __name__ == "__main__":
    unittest.main()
