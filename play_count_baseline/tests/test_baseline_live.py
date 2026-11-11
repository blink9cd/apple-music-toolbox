"""One live, read-only run of the whole tool against the real Music.app, opt-in only.

Every other suite fakes Music.app at the `music_calls` runner seam, which proves what the
tool sends and nothing about what Music answers. This file runs `main` itself, with the
real runner, into a fresh temporary folder outside every checkout, and asserts only that
it exits 0 and that the file it wrote validates against the contract copy.

**Read-only by construction.** The tool sends only the ``is running`` probe, the count,
and the play-count listing, each a read; it never writes to Music.app and never launches
it.

**Validity only.** No title, artist, album, path, or count from the library is asserted,
printed or kept: the run's own stderr carries aggregates alone, a failure names the exit
code and the number of schema findings, and the file is deleted with its folder.

It runs only when every one of these holds, and skips otherwise:

- ``PLAY_COUNT_BASELINE_LIVE`` is ``1``: whoever runs it chose to read their library;
- ``APPLE_MUSIC_TOOLBOX_OFFLINE`` is unset: the project's one switch for every live
  boundary, which the export sets on every run of its suite;
- the platform is macOS, where Music.app and ``osascript`` exist;
- Music.app is running, asked through `is_running` itself.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE.parent), str(_HERE.parent / "src")]

import play_count_baseline as pcb  # noqa: E402 - import follows the sys.path bootstrap above
import baseline_schema  # noqa: E402 - import follows the sys.path bootstrap above
import music_calls  # noqa: E402 - import follows the sys.path bootstrap above

#: The switch that runs this test, and the value that turns it on.
_SWITCH = "PLAY_COUNT_BASELINE_LIVE"
_ON = "1"
#: The project's "no live boundary" switch, which skips this test whatever _SWITCH says.
_OFFLINE = "APPLE_MUSIC_TOOLBOX_OFFLINE"


@unittest.skipUnless(sys.platform == "darwin", "Music.app is macOS-only")
@unittest.skipIf(_OFFLINE in os.environ, f"{_OFFLINE} is set - live run skipped")
@unittest.skipUnless(
    os.environ.get(_SWITCH) == _ON, f"set {_SWITCH}=1 to read the real library"
)
class LiveTest(unittest.TestCase):  # pragma: no cover - runs only against Music.app
    """The real run, checked for its exit code and the validity of its file alone."""

    def setUp(self) -> None:
        """Skip unless Music.app is running; the probe never launches it."""
        try:
            running = music_calls.is_running(run=music_calls.real_run)
        except music_calls.MusicCallError as exc:
            # Its class alone: the reason is osascript's message, never printed here.
            self.skipTest(
                f"cannot ask whether Music.app is running: {type(exc).__name__}"
            )
        if not running:
            self.skipTest("Music.app is not running")

    def test_the_real_library_writes_a_valid_baseline(self) -> None:
        with TemporaryDirectory() as folder:
            target = Path(folder).resolve() / "baseline.json"
            code = pcb.main(["--output", str(target)], wiring=pcb.real_wiring())
            self.assertEqual(code, pcb.EXIT_WRITTEN, "the run did not write a baseline")
            findings = baseline_schema.located_findings(json.loads(target.read_bytes()))
            self.assertEqual(
                len(findings), 0, f"{len(findings)} schema finding(s) in the file"
            )


def _live_class_under(environ: dict[str, str], platform: str) -> type:
    """`LiveTest` as this file decorates it under *environ* on *platform*.

    The file is loaded afresh under its own module name with the environment and the
    platform patched, so the decorators are evaluated again. Only the class's skip
    markers are read: no test of it is run, so nothing here reaches Music.app.
    """
    location = importlib.util.spec_from_file_location(
        "_baseline_live_reloaded", Path(__file__)
    )
    assert location is not None and location.loader is not None
    module = importlib.util.module_from_spec(location)
    # Registered under its own name for the re-evaluation only, as a dataclass or a
    # decorator reading sys.modules[cls.__module__] would need; the skip markers it
    # decides are the same either way.
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
