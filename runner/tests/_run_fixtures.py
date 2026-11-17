"""The runner's kit for the build, install, grant and status suites, on signed_app's fakes.

`make_kit` builds signed_app's fake host (`_app_fixtures.make_host_kit`: a temporary
home, a `FakeClock`, a scripted `FakeLaunchd` and `FakeTools`, so no test reaches the
real HOME, `~/Library`, launchd, a real repository, swift, codesign or osascript) for the
runner's entry script, and adds what only the runner has: its layout, its paths, an
invented checkout holding every allowlisted script as an empty file, and helpers that
write its signing setting, a grant result and an installed app.

The entry script's place in the invented checkout is read from the committed allowlist
(the folder that holds its grant probe's own folder), so no folder name is restated here.

The fakes and constants the suites use are re-exported from `_app_fixtures` under their
own names, so a suite reads them all from this module.

Entry point assumptions: imported only, by the suites in this folder; importing it puts
the runner's modules and its shared libraries on `sys.path` through `runner.py`, and
signed_app's fixtures, beside this tool's folder, through their own folder.
"""

from __future__ import annotations

import dataclasses
import json
import plistlib
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

_TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_TOOL_ROOT))
# signed_app's fixtures, in the folder beside this tool's in the project root.
sys.path.insert(0, str(_TOOL_ROOT.parent / "signed_app" / "tests"))

import runner  # noqa: E402, F401 - puts src/ and the shared libraries on sys.path
from _app_fixtures import (  # noqa: E402 - import follows the sys.path bootstrap above
    ABSENT_RC,
    BUILT_BYTES,
    DEAD_PID,
    FAKE_IDENTITY,
    FAKE_NAME,
    FAKE_REQUIREMENT,
    FAKE_TEAM,
    PID,
    FakeClock,
    FakeLaunchd,
    FakeTools,
    HostKit,
    done,
    make_host_kit,
)
import app_host  # noqa: E402 - on sys.path once runner is imported
import run_allowlist  # noqa: E402 - on sys.path once runner is imported
import run_layout  # noqa: E402 - on sys.path once runner is imported

__all__ = [
    "ABSENT_RC",
    "BUILT_BYTES",
    "DEAD_PID",
    "FAKE_IDENTITY",
    "FAKE_NAME",
    "FAKE_REQUIREMENT",
    "FAKE_TEAM",
    "PID",
    "PROBE_FILE",
    "PROBE_NAME",
    "TOOL_ROOT",
    "FakeClock",
    "FakeLaunchd",
    "FakeTools",
    "Kit",
    "OTHER_PYTHON",
    "app_host",
    "done",
    "make_kit",
    "repo_scripts",
]

#: The runner's own folder in the real tree, for the files a test reads from it.
TOOL_ROOT = _TOOL_ROOT
#: The grant probe in the real tree, in its own folder beside the entry script.
PROBE_FILE = _TOOL_ROOT / "grant_probe" / "grant_probe.py"
PROBE_NAME = PROBE_FILE.name
#: An invented interpreter another tool might name; never run.
OTHER_PYTHON = "/opt/example/venv/bin/python"


def repo_scripts() -> list[str]:
    """The committed allowlist's scripts, as written: relative to the repository root."""
    document = json.loads(run_allowlist.ALLOWLIST_FILE.read_text(encoding="utf-8"))
    scripts: list[str] = document["scripts"]
    return scripts


def _entry_script() -> str:
    """The entry script's path below a checkout: beside the grant probe's folder."""
    (probe,) = [entry for entry in repo_scripts() if Path(entry).name == PROBE_NAME]
    return str(Path(probe).parent.parent / _TOOL_ROOT.name) + ".py"


@dataclass
class Kit(HostKit):
    """A fake host and the fakes behind it, with the runner's layout and paths."""

    layout: run_layout.RunLayout
    paths: run_layout.RunPaths

    @property
    def probe(self) -> Path:
        """The grant probe in the invented checkout."""
        return self.host.script.parent / PROBE_FILE.parent.name / PROBE_NAME

    @property
    def executable(self) -> Path:
        """The installed app's executable."""
        return self.paths.app_bundle / "Contents" / "MacOS" / self.layout.executable

    def allowlist(self) -> run_allowlist.Allowlist:
        """What a build from the invented checkout writes into the bundle."""
        scripts = [str(self.checkout / entry) for entry in repo_scripts()]
        return {"python": sys.executable, "scripts": scripts}

    def write_identity(self, identity: str = FAKE_IDENTITY) -> None:
        """Write the signing setting under the fake home."""
        self.paths.signing_config.parent.mkdir(parents=True, exist_ok=True)
        self.paths.signing_config.write_text(
            f'identity = "{identity}"\n', encoding="utf-8", newline="\n"
        )

    def write_result(self, outcome: str, detail: str = "") -> None:
        """Write the grant result, as the probe would under launchd."""
        self.paths.grant_result.parent.mkdir(parents=True, exist_ok=True)
        self.paths.grant_result.write_text(
            json.dumps({"outcome": outcome, "detail": detail}),
            encoding="utf-8",
            newline="\n",
        )

    def probe_reports(self, outcome: str, detail: str = "") -> None:
        """Make the fake launchd run the probe, which writes `outcome` at bootstrap."""
        self.launchd.on_bootstrap = lambda: self.write_result(outcome, detail)

    def _shown(self, value: object) -> object:
        """`value` with each machine path in its text swapped for its placeholder."""
        if isinstance(value, dict):
            return {key: self._shown(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._shown(item) for item in value]
        if not isinstance(value, str):
            return value
        shown = value.replace(sys.executable, "<venv>/bin/python")
        shown = shown.replace(str(self.checkout), "<checkout>")
        return shown.replace(str(self.home), "<home>")

    def with_placeholders(self, plist: bytes) -> bytes:
        """The property list `plist` with each machine path shown as the samples show it.

        The invented checkout is ``<checkout>``, this interpreter ``<venv>/bin/python``
        and the fake home ``<home>``, in every string the list holds.
        """
        loaded: dict[str, object] = plistlib.loads(plist)
        return plistlib.dumps({key: self._shown(item) for key, item in loaded.items()})

    def write_record(self, text: str = FAKE_REQUIREMENT) -> None:
        """Write the signer record as install would: `text` on one line, mode 0600."""
        self.paths.signer_record.parent.mkdir(parents=True, exist_ok=True)
        self.paths.signer_record.write_text(f"{text}\n", encoding="utf-8", newline="\n")
        self.paths.signer_record.chmod(0o600)

    def install_app(self, info: dict[str, object] | None = None) -> None:
        """Put an installed bundle in place, its Info.plist holding `info`.

        With no `info`, the Info.plist holds the allowlist a build would write. The
        signer install records is written beside it.
        """
        self.write_record()
        self.executable.parent.mkdir(parents=True, exist_ok=True)
        self.executable.write_bytes(BUILT_BYTES)
        if info is None:
            info = {run_allowlist.INFO_KEY: dict(self.allowlist())}
        plist = self.paths.app_bundle / "Contents" / "Info.plist"
        plist.write_bytes(plistlib.dumps(info))


def make_kit(test: unittest.TestCase) -> Kit:
    """A host on a temporary home, removed when `test` ends, with fresh fakes.

    The checkout is a repository's main checkout by default (one fake repository whose
    git folder and common folder are the same), and holds every allowlisted script.
    """
    layout = run_layout.load_layout()
    base = make_host_kit(test, script=_entry_script(), product=layout.executable)
    for entry in repo_scripts():
        script = base.checkout / entry
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_bytes(b"")
    shared = {
        field.name: getattr(base, field.name) for field in dataclasses.fields(base)
    }
    return Kit(**shared, layout=layout, paths=layout.paths(base.home))
