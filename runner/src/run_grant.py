"""install's grant check: start the probe once through the installed app, and report.

macOS decides whether an app may control Music the first time the app asks, by showing
its permission prompt, and remembers the answer for that app. So install asks once, on
the spot, while a person is there to answer: it loads a one-shot launchd agent whose
program is the installed runner app, running ``grant_probe.py`` (the question is charged
to the app, exactly as a scheduled job's will be), waits for the result file the probe
writes, and unloads the agent again whatever happened.

The wait is `GRANT_DEADLINE_S`, longer than the probe's own bound, so the probe always
reports first and a missing result means the probe never ran or never finished. The
result file is polled with escalating waits. Before the agent is loaded, an agent a
stopped earlier install left is unloaded and then the result it left is removed, in that
order, so neither it nor its last write can pass for this check's.

`report` turns the outcome into install's last line and its exit code: 0 only when the
app may control Music.

Entry point assumptions: imported by the runner's modules, with `src/`, the grant
probe's folder (for `grant_probe`), signed_app's ``src/`` and the shared libraries
on `sys.path`.
"""

from __future__ import annotations

import json
import plistlib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import grant_probe
import launchd_agent
from app_bundle import bundle_executable
from app_host import Host
from app_install import make_private
from run_layout import RunLayout, RunPaths

#: How long install waits for the probe's result: past the probe's own bound.
GRANT_DEADLINE_S: Final = 180.0
#: The waits between reads of the result file; the last repeats until the deadline.
GRANT_WAITS_S: Final = (0.5, 1.0, 2.0, 4.0)
#: The most bytes a result file may hold: one outcome and a one-line detail are far less,
#: and a file past this is never read whole.
MAX_RESULT_BYTES: Final = 65_536
#: Where a person allows the app, in System Settings' own words.
_SETTINGS_PATH: Final = "System Settings > Privacy & Security > Automation"
#: What both a prompt nobody answered and a probe that never reported come to.
_NOT_ANSWERED: Final = "the permission prompt was not answered; run install again"


@dataclass(frozen=True)
class GrantResult:
    """What the probe reported: one of `grant_probe`'s outcomes, and its detail."""

    outcome: str
    detail: str


def grant_plist(
    layout: RunLayout, paths: RunPaths, *, python: str, probe: Path
) -> bytes:
    """The one-shot agent's plist: the installed app, running the probe once at load.

    No ``KeepAlive``: the probe must run once, never again after it exits. Only stderr
    is kept, since the runner app's own refusals go there and the probe's answer goes to
    the result file.
    """
    return plistlib.dumps(
        {
            "Label": layout.grant_label,
            "ProgramArguments": [
                str(bundle_executable(paths.app_bundle, layout)),
                "--python",
                python,
                "--script",
                str(probe),
                "--",
                "--result",
                str(paths.grant_result),
            ],
            "RunAtLoad": True,
            "StandardErrorPath": str(paths.grant_err_log),
        }
    )


def read_result(path: Path) -> GrantResult | None:
    """The result in `path`; None while there is no file, an error result for a bad one.

    The probe replaces the file in one step, so a file that is there is whole. At most
    `MAX_RESULT_BYTES` are read, and a file past that is an error, as is a document
    nested too deeply for json to parse: never an exception.
    """
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_RESULT_BYTES + 1)
        if len(raw) > MAX_RESULT_BYTES:
            return GrantResult(grant_probe.ERROR, "the result file is too large")
        document = json.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, RecursionError) as error:
        # ValueError covers text that is not UTF-8 and text that is not JSON;
        # RecursionError, nesting deeper than json's recursion limit.
        return GrantResult(
            grant_probe.ERROR,
            f"the result file cannot be read ({type(error).__name__})",
        )
    if isinstance(document, dict):
        outcome, detail = document.get("outcome"), document.get("detail")
        if isinstance(outcome, str) and isinstance(detail, str):
            return GrantResult(outcome, detail)
    return GrantResult(grant_probe.ERROR, "the result file has an unexpected shape")


def await_result(host: Host, paths: RunPaths) -> GrantResult | None:
    """Poll for the probe's result until it is there, or the deadline; None when never."""
    deadline = host.clock() + GRANT_DEADLINE_S
    attempt = 0
    while True:
        result = read_result(paths.grant_result)
        remaining = deadline - host.clock()
        if result is not None or remaining <= 0:
            return result
        wait = GRANT_WAITS_S[min(attempt, len(GRANT_WAITS_S) - 1)]
        host.sleep(min(wait, remaining))
        attempt += 1


def run_check(
    host: Host, layout: RunLayout, paths: RunPaths, *, python: str, probe: Path
) -> GrantResult | None:
    """Run the probe once through the installed app; its result, or None when it gave none.

    An agent an earlier install left loaded is unloaded first, and only then is the old
    result removed, so that agent's probe cannot write one this check would read. The
    new agent is unloaded and its plist removed whatever happens, a launchd failure on
    the way included.
    """
    for folder in (paths.logs_dir, paths.grant_dir):
        make_private(folder)
    _remove_agent(host, layout, paths, only_if_present=True)
    # An earlier install's answer must never be read as this one's: removed only now,
    # when no earlier agent is left to write another.
    paths.grant_result.unlink(missing_ok=True)
    try:
        launchd_agent.install_agent(
            host.launchctl,
            label=layout.grant_label,
            plist_path=paths.grant_plist,
            plist=grant_plist(layout, paths, python=python, probe=probe),
        )
        return await_result(host, paths)
    finally:
        _remove_agent(host, layout, paths)


def _remove_agent(
    host: Host, layout: RunLayout, paths: RunPaths, *, only_if_present: bool = False
) -> None:
    """Unload the grant agent and remove its plist, once launchd confirms it gone.

    With `only_if_present`, an agent launchd reports absent is left alone; one it cannot
    answer for is still unloaded, so the failure is launchd_agent's own LaunchdError.
    """
    if only_if_present:
        state = launchd_agent.agent_state(host.launchctl, layout.grant_label)
        if state is launchd_agent.AgentState.ABSENT:
            return
    launchd_agent.uninstall_agent(
        host.launchctl, label=layout.grant_label, plist_path=paths.grant_plist
    )


def _failure(layout: RunLayout, paths: RunPaths, result: GrantResult | None) -> str:
    """Why the app may not control Music yet, and what to do, as one line."""
    if result is None:
        return (
            f"{_NOT_ANSWERED} (the check reported nothing in {GRANT_DEADLINE_S:g} s; "
            f"what it wrote instead is in {paths.grant_err_log})"
        )
    if result.outcome == grant_probe.NOT_RUNNING:
        return (
            "Music is not running, so macOS was not asked: "
            "open Music and run install again"
        )
    if result.outcome == grant_probe.DENIED:
        return (
            f"macOS refused: allow Music under {_SETTINGS_PATH} > "
            f"{layout.display_name}, then run install again"
        )
    if result.outcome == grant_probe.TIMED_OUT:
        return _NOT_ANSWERED
    detail = (result.detail.splitlines() or ["no detail"])[0]
    if result.outcome != grant_probe.ERROR:
        detail = f"{result.outcome}: {detail}"
    return f"the grant check failed: {detail}"


def report(
    host: Host, layout: RunLayout, paths: RunPaths, result: GrantResult | None
) -> int:
    """Print the check's verdict; 0 when the app may control Music, 1 otherwise."""
    if result is not None and result.outcome == grant_probe.GRANTED:
        print(f"{layout.display_name} may control Music.", file=host.out)
        return 0
    print(f"ERROR: {_failure(layout, paths, result)}", file=host.err)
    return 1
