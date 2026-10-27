"""The one live smoke test: the real afcclient against the connected, unlocked phone.

Skipped unless ``PHONE_AUDIT_LIVE`` is ``1``: it needs the operator at an unlocked,
trusted iPhone on USB, and it reads that phone for real (reads only, through the same
seam as every run). It skips as well whenever ``APPLE_MUSIC_TOOLBOX_OFFLINE`` is set,
the project's one switch for every live boundary, and off macOS, the only platform the
tool was proven on. The report goes to a temporary file, never into a repository, and
is checked only for its shape: no name or count from it is printed or kept.
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
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import phone_fixtures as pf  # noqa: E402 - import follows the sys.path bootstrap above

#: The switch that runs this test, and the value that turns it on.
_SWITCH = "PHONE_AUDIT_LIVE"
_ON = "1"
#: The project's "no live boundary" switch, which skips this test whatever _SWITCH says.
_OFFLINE = "APPLE_MUSIC_TOOLBOX_OFFLINE"
#: The keys a JSON report always has.
_KEYS = {"schema", "no_file", "size_differs", "files_no_row", "summary"}


@unittest.skipUnless(sys.platform == "darwin", "proven on macOS only")
@unittest.skipIf(_OFFLINE in os.environ, f"{_OFFLINE} is set - live phone test skipped")
@unittest.skipUnless(
    os.environ.get(_SWITCH) == _ON, f"set {_SWITCH}=1 at an unlocked phone"
)
class LiveTest(unittest.TestCase):  # pragma: no cover - runs only at a real phone
    """One real run, its report parsed."""

    def test_a_real_run_reports_in_shape(self) -> None:
        with TemporaryDirectory() as scratch:
            target = Path(scratch) / "phone.json"
            result = pf.run_main(["--format", "json", "--report", str(target)], None)
            self.assertIn(result.code, (pf.OK, pf.FINDINGS), result.stderr)
            report = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(set(report), _KEYS)
        self.assertEqual(report["schema"], 1)


def _live_class_under(environ: dict[str, str], platform: str) -> type:
    """`LiveTest` as this file decorates it under *environ* on *platform*.

    The file is loaded afresh under its own module name with the environment and the
    platform patched, so the decorators are evaluated again. Only the class's skip
    markers are read: no test of it is run, so nothing here reaches a phone.
    """
    location = importlib.util.spec_from_file_location(
        "_phone_live_reloaded", Path(__file__)
    )
    assert location is not None and location.loader is not None
    module = importlib.util.module_from_spec(location)
    with (
        mock.patch.dict(os.environ, environ, clear=True),
        mock.patch.object(sys, "platform", platform),
    ):
        location.loader.exec_module(module)
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

    def test_the_offline_switch_skips_it_even_with_its_own_switch_on(self) -> None:
        self.assert_skipped({_SWITCH: _ON, _OFFLINE: "1"}, "darwin")

    def test_it_skips_off_macos(self) -> None:
        self.assert_skipped({_SWITCH: _ON}, "linux")


if __name__ == "__main__":
    unittest.main()
