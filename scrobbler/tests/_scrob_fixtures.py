"""The scrobbler's kit for the build, agent and status suites, on signed_app's fake seams.

`make_kit` builds signed_app's fake host (`_app_fixtures.make_host_kit`: a temporary
home, a `FakeClock`, a scripted `FakeLaunchd` and `FakeTools`, so no test reaches the
real HOME, `~/Library`, launchd, a real repository, swift or codesign) for the
scrobbler's entry script, and adds what only the scrobbler has: its layout, its paths,
and helpers that write its signing setting, its status.json and an installed app.

The fakes and constants the suites use are re-exported from `_app_fixtures` under their
own names, so a suite reads them all from this module.

Entry point assumptions: imported only, by the suites in this folder; importing it puts
the scrobbler's modules and its shared libraries on `sys.path` through `scrobbler.py`,
and signed_app's fixtures, beside this tool's folder, through their own folder.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

_TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_TOOL_ROOT))
# signed_app's fixtures, in the folder beside this tool's in the project root.
sys.path.insert(0, str(_TOOL_ROOT.parent / "signed_app" / "tests"))

import scrobbler  # noqa: E402, F401 - puts src/ and the shared libraries on sys.path
from _app_fixtures import (  # noqa: E402 - import follows the sys.path bootstrap above
    ABSENT_RC,
    BUILT_BYTES,
    CASE_INSENSITIVE_TMP,
    CASE_SENSITIVE_REASON,
    DEAD_PID,
    FAKE_IDENTITY,
    FAKE_NAME,
    FAKE_TEAM,
    PID,
    FakeClock,
    FakeLaunchd,
    FakeTools,
    HostKit,
    done,
    make_host_kit,
)
import scrob_host  # noqa: E402 - on sys.path once scrobbler is imported
import scrob_layout  # noqa: E402 - on sys.path once scrobbler is imported

__all__ = [
    "ABSENT_RC",
    "BUILT_BYTES",
    "CASE_INSENSITIVE_TMP",
    "CASE_SENSITIVE_REASON",
    "DEAD_PID",
    "FAKE_IDENTITY",
    "FAKE_NAME",
    "FAKE_TEAM",
    "PID",
    "FakeClock",
    "FakeLaunchd",
    "FakeTools",
    "Kit",
    "done",
    "make_kit",
    "scrob_host",
    "subprocess",
]


@dataclass
class Kit(HostKit):
    """A fake host and the fakes behind it, with the scrobbler's layout and paths."""

    layout: scrob_layout.Layout
    paths: scrob_layout.ScrobPaths

    def write_identity(self, identity: str = FAKE_IDENTITY) -> None:
        """Write the signing setting under the fake home."""
        self.paths.signing_config.parent.mkdir(parents=True, exist_ok=True)
        self.paths.signing_config.write_text(
            f'identity = "{identity}"\n', encoding="utf-8", newline="\n"
        )

    def write_status(self, **fields: object) -> None:
        """Write a healthy status.json, as of the fake clock, with `fields` changed."""
        now = self.clock.wall
        document: dict[str, object] = {
            "format": 1,
            "version": self.layout.version,
            "pid": 4243,
            "started_at": now - 600,
            "heartbeat_at": now - 5,
            "music_running": True,
            "playing": True,
            "queue_backlog": 0,
            "oldest_queued_at": None,
            "refused_count": 0,
            "last_queued_at": None,
            "last_sent_at": None,
            "last_send_error": None,
            "unrecordable_count": 0,
            "automation_denied": False,
            "automation_asked_at": None,
            "now_playing": None,
            **fields,
        }
        self.paths.status_file.parent.mkdir(parents=True, exist_ok=True)
        self.paths.status_file.write_text(
            json.dumps(document), encoding="utf-8", newline="\n"
        )

    def install_app(self) -> None:
        """Put an installed app bundle and the agent's plist in place, agent loaded."""
        executable = self.paths.app_bundle / "Contents" / "MacOS" / "scrobbler"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_bytes(BUILT_BYTES)
        self.paths.launch_agent_plist.parent.mkdir(parents=True, exist_ok=True)
        self.paths.launch_agent_plist.write_bytes(b"invented plist")
        self.launchd.loaded.add(self.layout.launchd_label)


def make_kit(test: unittest.TestCase) -> Kit:
    """A host on a temporary home, removed when `test` ends, with fresh fakes.

    The checkout is a repository's main checkout by default: one fake repository whose
    git folder and common folder are the same.
    """
    layout = scrob_layout.load_layout()
    base = make_host_kit(
        test, script="scrobbler/scrobbler.py", product=layout.executable
    )
    shared = {
        field.name: getattr(base, field.name) for field in dataclasses.fields(base)
    }
    return Kit(**shared, layout=layout, paths=layout.paths(base.home))
