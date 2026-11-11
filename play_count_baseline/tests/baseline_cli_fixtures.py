"""Shared fixtures for the entry point's suites: a temporary target and a captured run.

`CliCase` gives each test a fresh folder from `tempfile`, outside any checkout, so the
toolbox's working-tree refusal passes, and runs `main` against a
`baseline_fixtures.FakeMusic`, capturing stdout and stderr, so nothing reaches Music.app.

Not discovered as a suite (no ``test_`` prefix). Suites import it by bare name with
this directory on ``sys.path``.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import sys
import unittest
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import play_count_baseline as pcb  # noqa: E402 - import follows the sys.path bootstrap above
import baseline_fixtures as bf  # noqa: E402 - import follows the sys.path bootstrap above

#: The tool's exit codes: written, refused, and could not run.
WRITTEN, REFUSED, CANNOT = 0, 1, 2
#: An invented capture time, in Unix seconds, with a fraction `main` must drop.
NOW = 1793100000.75
#: A second invented track, unplayed, with no file and no album artist.
SECOND = dataclasses.replace(
    bf.INVENTED_TRACK,
    persistent_id="FEDCBA9876543210",
    name="Second Invented Song",
    album_artist="",
    played_count=0,
    played_date="",
    path="",
)


@dataclass(frozen=True)
class Outcome:
    """One run: its exit code, stdout, and stderr (argparse's and the tool's together)."""

    code: int
    stdout: str
    stderr: str


def tracks(count: int) -> list[bf.baseline_rows.RawTrack]:
    """*count* invented tracks, each its own persistent ID."""
    return [
        dataclasses.replace(bf.INVENTED_TRACK, persistent_id=f"{index:016X}")
        for index in range(count)
    ]


class CliCase(unittest.TestCase):
    """A fresh temporary folder outside any checkout, and a target in it."""

    def setUp(self) -> None:
        """Make the folder; ``target`` names a file in it that does not exist yet."""
        super().setUp()
        holder = TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name).resolve()
        self.target = self.root / "baseline.json"

    def run_main(
        self,
        music: bf.FakeMusic,
        argv: Sequence[str] | None = None,
        *,
        platform: str = "darwin",
    ) -> Outcome:
        """Run `main` against *music*; an argparse exit's code is returned like any other."""
        args = ["--output", str(self.target)] if argv is None else list(argv)
        out, err = io.StringIO(), io.StringIO()
        wiring = pcb.Wiring(run=music, now=lambda: NOW, stderr=err, platform=platform)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = pcb.main(args, wiring=wiring)
            except SystemExit as stop:
                code = int(stop.code or 0)
        return Outcome(code, out.getvalue(), err.getvalue())

    def written(self) -> dict[str, object]:
        """The target's document, parsed."""
        document = json.loads(self.target.read_text(encoding="utf-8"))
        assert isinstance(document, dict)
        return document
