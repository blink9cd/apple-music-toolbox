"""run_grant: the one-shot grant agent, the wait for its result, and what install says.

launchd is the kit's scripted fake, time is its fake clock, and the probe never runs: a
test writes the result file the probe would, when the fake launchd bootstraps the agent.
"""

from __future__ import annotations

import dataclasses
import plistlib
import stat
import subprocess
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _run_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import grant_probe  # noqa: E402 - on sys.path once _run_fixtures is imported
import launchd_agent  # noqa: E402 - on sys.path once _run_fixtures is imported
import run_grant  # noqa: E402 - on sys.path once _run_fixtures is imported

if sys.platform == "win32":
    # POSIX only, as the runner is; also lets a win32 type-check skip the mode checks.
    raise unittest.SkipTest("the runner runs on macOS only")  # pragma: only-on win32

#: The grant plist with every machine path as a placeholder, for reading by hand.
_SAMPLE = fx.TOOL_ROOT / "samples" / "grant.plist"


class GrantCase(unittest.TestCase):
    """A fresh kit per test."""

    def setUp(self) -> None:
        self.kit = fx.make_kit(self)

    def plist(self) -> bytes:
        """The grant agent's plist for the kit."""
        return run_grant.grant_plist(
            self.kit.layout,
            self.kit.paths,
            python=sys.executable,
            probe=self.kit.probe,
        )

    def check(self) -> run_grant.GrantResult | None:
        """Run the grant check against the kit."""
        return run_grant.run_check(
            self.kit.host,
            self.kit.layout,
            self.kit.paths,
            python=sys.executable,
            probe=self.kit.probe,
        )

    def report(self, result: run_grant.GrantResult | None) -> int:
        """Report `result` on the kit's streams."""
        return run_grant.report(self.kit.host, self.kit.layout, self.kit.paths, result)

    def error_line(self) -> str:
        """The one ERROR line on the kit's stderr, with nothing on its stdout."""
        self.assertEqual(self.kit.out.getvalue(), "")
        (line,) = self.kit.err.getvalue().splitlines()
        self.assertTrue(line.startswith("ERROR: "), line)
        return line


class GrantPlistTest(GrantCase):
    """The agent runs the probe once, through the installed app, and is never restarted."""

    def test_it_holds_exactly_its_keys(self) -> None:
        paths = self.kit.paths
        self.assertEqual(
            plistlib.loads(self.plist()),
            {
                "Label": "local.apple-music-toolbox.runner.grant",
                "ProgramArguments": [
                    str(self.kit.executable),
                    "--python",
                    sys.executable,
                    "--script",
                    str(self.kit.probe),
                    "--",
                    "--result",
                    str(paths.data_dir / "grant" / "result.json"),
                ],
                "RunAtLoad": True,
                "StandardErrorPath": str(paths.data_dir / "logs" / "grant.err.log"),
            },
        )

    def test_launchd_never_restarts_it(self) -> None:
        self.assertNotIn("KeepAlive", plistlib.loads(self.plist()))

    def test_the_sample_is_this_plist_with_placeholders(self) -> None:
        self.assertEqual(self.kit.with_placeholders(self.plist()), _SAMPLE.read_bytes())


class ReadResultTest(GrantCase):
    """A result file is absent, a result, or an error saying why it is neither."""

    def read(self) -> run_grant.GrantResult | None:
        """Read the kit's result file."""
        return run_grant.read_result(self.kit.paths.grant_result)

    def write(self, text: str) -> None:
        """Write `text` as the result file."""
        self.kit.paths.grant_result.parent.mkdir(parents=True)
        self.kit.paths.grant_result.write_text(text, encoding="utf-8", newline="\n")

    def test_no_file_is_no_result_yet(self) -> None:
        self.assertIsNone(self.read())

    def test_a_result_is_its_outcome_and_detail(self) -> None:
        self.kit.write_result("granted", "playing")
        self.assertEqual(self.read(), run_grant.GrantResult("granted", "playing"))

    def test_a_file_that_is_not_json_is_an_error(self) -> None:
        self.write("{not json")
        self.assertEqual(
            self.read(),
            run_grant.GrantResult(
                "error", "the result file cannot be read (JSONDecodeError)"
            ),
        )

    def test_a_folder_at_the_path_is_an_error(self) -> None:
        self.kit.paths.grant_result.mkdir(parents=True)
        result = self.read()
        assert result is not None
        self.assertEqual(result.outcome, "error")
        self.assertIn("IsADirectoryError", result.detail)

    def test_a_deeply_nested_document_is_an_error_not_a_crash(self) -> None:
        # The regression: json's recursion limit raised RecursionError, which the
        # handler did not catch, so a planted file crashed the check. Where the limit
        # falls differs by Python (3.12 stops near 1,000 levels, 3.14 far deeper), so
        # this real file is an error either way, and the next test pins the message.
        depth = run_grant.MAX_RESULT_BYTES // 2
        self.write("[" * depth + "]" * depth)
        result = self.read()
        assert result is not None
        self.assertEqual(result.outcome, "error")

    def test_a_recursion_error_is_one_line_saying_so(self) -> None:
        self.write("[]")
        too_deep = RecursionError("maximum recursion depth exceeded")
        with mock.patch.object(run_grant.json, "loads", side_effect=too_deep):
            self.assertEqual(
                self.read(),
                run_grant.GrantResult(
                    "error", "the result file cannot be read (RecursionError)"
                ),
            )

    def test_an_oversized_file_is_an_error_and_never_read_whole(self) -> None:
        self.write(" " * run_grant.MAX_RESULT_BYTES + "{}")
        self.assertEqual(
            self.read(),
            run_grant.GrantResult("error", "the result file is too large"),
        )

    def test_a_file_at_the_bound_is_read(self) -> None:
        document = '{"outcome": "granted", "detail": "playing"}'
        self.write(document.ljust(run_grant.MAX_RESULT_BYTES))
        self.assertEqual(self.read(), run_grant.GrantResult("granted", "playing"))

    def test_any_other_shape_is_an_error(self) -> None:
        for text in (
            '["granted"]',
            '{"outcome": "granted"}',
            '{"outcome": 1, "detail": ""}',
        ):
            with self.subTest(text=text):
                self.kit.paths.grant_result.unlink(missing_ok=True)
                self.kit.paths.grant_result.parent.mkdir(parents=True, exist_ok=True)
                self.kit.paths.grant_result.write_text(
                    text, encoding="utf-8", newline="\n"
                )
                self.assertEqual(
                    self.read(),
                    run_grant.GrantResult(
                        "error", "the result file has an unexpected shape"
                    ),
                )


class RunCheckTest(GrantCase):
    """The check loads the agent, waits for the result, and always unloads the agent."""

    def test_a_result_is_returned_and_the_agent_removed(self) -> None:
        seen: list[bytes] = []

        def started() -> None:
            seen.append(self.kit.paths.grant_plist.read_bytes())
            self.kit.write_result("granted", "paused")

        self.kit.launchd.on_bootstrap = started
        self.assertEqual(self.check(), run_grant.GrantResult("granted", "paused"))
        self.assertEqual(seen, [self.plist()])
        self.assertEqual(self.kit.log, ["bootout", "bootstrap", "bootout"])
        self.assertFalse(self.kit.paths.grant_plist.exists())
        self.assertEqual(self.kit.launchd.loaded, set())

    def test_the_result_and_log_folders_are_private(self) -> None:
        self.kit.probe_reports("granted")
        self.check()
        for folder in (self.kit.paths.grant_dir, self.kit.paths.logs_dir):
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700, folder)

    def test_an_earlier_result_is_never_taken_for_this_check_s(self) -> None:
        self.kit.write_result("granted", "left by an earlier install")
        self.assertIsNone(self.check())

    def test_no_result_waits_out_the_deadline_with_escalating_waits(self) -> None:
        before = self.kit.clock.mono
        self.assertIsNone(self.check())
        waits = self.kit.clock.slept
        self.assertEqual(waits[:6], [0.5, 1.0, 2.0, 4.0, 4.0, 4.0])
        self.assertEqual(sum(waits), run_grant.GRANT_DEADLINE_S)
        self.assertEqual(self.kit.clock.mono - before, 180.0)
        self.assertFalse(self.kit.paths.grant_plist.exists())
        self.assertEqual(self.kit.launchd.loaded, set())

    def test_the_deadline_is_past_the_probe_s_own_bound(self) -> None:
        self.assertEqual(run_grant.GRANT_DEADLINE_S, 180.0)
        self.assertGreater(
            run_grant.GRANT_DEADLINE_S, grant_probe.GRANT_PROBE_TIMEOUT_S
        )

    def test_a_result_that_arrives_late_is_still_read(self) -> None:
        clock = self.kit.clock

        def sleep(seconds: float) -> None:
            clock.sleep(seconds)
            if clock.mono >= 60:
                self.kit.write_result("denied", "invented (-1743)")

        self.kit.host = dataclasses.replace(self.kit.host, sleep=sleep)
        self.assertEqual(
            self.check(), run_grant.GrantResult("denied", "invented (-1743)")
        )
        self.assertLess(clock.mono, 70)

    def test_a_launchd_that_answers_unknown_fails_before_a_plist_is_written(
        self,
    ) -> None:
        self.kit.launchd.unknown.add(self.kit.layout.grant_label)
        with self.assertRaises(launchd_agent.LaunchdError):
            self.check()
        self.assertFalse(self.kit.paths.grant_plist.exists())
        self.assertNotIn("bootstrap", self.kit.log)

    def test_an_agent_that_never_loads_is_booted_out_and_its_plist_kept(self) -> None:
        # launchd answers unknown from the bootstrap on, so the removal cannot be
        # confirmed: launchd_agent keeps the plist then, for a retry.
        label = self.kit.layout.grant_label
        self.kit.launchd.on_bootstrap = lambda: self.kit.launchd.unknown.add(label)
        with self.assertRaises(launchd_agent.LaunchdError):
            self.check()
        self.assertEqual(self.kit.log, ["bootout", "bootstrap", "bootout"])
        self.assertEqual(self.kit.launchd.loaded, set())
        self.assertTrue(self.kit.paths.grant_plist.exists())

    def test_the_agent_is_removed_when_the_wait_is_cut_short(self) -> None:
        label = self.kit.layout.grant_label
        for error in (KeyboardInterrupt(), OSError("invented failure")):
            with self.subTest(error=type(error).__name__):
                kit = self.kit = fx.make_kit(self)
                loaded_at_wait: list[bool] = []

                def sleep(
                    seconds: float,
                    kit: fx.Kit = kit,
                    error: BaseException = error,
                    loaded_at_wait: list[bool] = loaded_at_wait,
                ) -> None:
                    loaded_at_wait.append(
                        label in kit.launchd.loaded and kit.paths.grant_plist.exists()
                    )
                    raise error

                kit.host = dataclasses.replace(kit.host, sleep=sleep)
                with self.assertRaises(type(error)) as raised:
                    self.check()
                self.assertIs(raised.exception, error)
                self.assertEqual(loaded_at_wait, [True])
                self.assertFalse(kit.paths.grant_plist.exists())
                self.assertEqual(kit.launchd.loaded, set())
                self.assertEqual(kit.log, ["bootout", "bootstrap", "bootout"])

    def test_a_result_a_leftover_agent_writes_as_it_stops_is_not_this_check_s(
        self,
    ) -> None:
        # A hard-killed install left its agent loaded; that old probe's last write
        # lands as launchd boots it out. This run's own probe answers later.
        kit, clock = self.kit, self.kit.clock
        label = kit.layout.grant_label
        kit.launchd.loaded.add(label)
        fake_run = kit.launchd.run

        def run(
            argv: Sequence[str], timeout: float
        ) -> subprocess.CompletedProcess[str]:
            if argv[1] == "bootout" and label in kit.launchd.loaded:
                kit.write_result("granted", "left by the earlier install's probe")
            return fake_run(argv, timeout)

        def sleep(seconds: float) -> None:
            clock.sleep(seconds)
            if clock.mono >= 60:
                kit.write_result("denied", "invented (-1743)")

        launchctl = dataclasses.replace(kit.host.launchctl, run=run)
        kit.host = dataclasses.replace(kit.host, launchctl=launchctl, sleep=sleep)
        self.assertEqual(
            self.check(), run_grant.GrantResult("denied", "invented (-1743)")
        )
        self.assertEqual(kit.launchd.loaded, set())
        self.assertFalse(kit.paths.grant_plist.exists())


class ReportTest(GrantCase):
    """Each outcome is one line and an exit code."""

    def test_granted_is_exit_0(self) -> None:
        self.assertEqual(self.report(run_grant.GrantResult("granted", "playing")), 0)
        self.assertEqual(
            self.kit.out.getvalue(), "Apple Music Toolbox Runner may control Music.\n"
        )
        self.assertEqual(self.kit.err.getvalue(), "")

    def test_music_not_running_is_exit_1(self) -> None:
        self.assertEqual(self.report(run_grant.GrantResult("not-running", "")), 1)
        self.assertIn("open Music and run install again", self.error_line())

    def test_denied_names_where_to_allow_it(self) -> None:
        result = run_grant.GrantResult("denied", "invented (-1743)")
        self.assertEqual(self.report(result), 1)
        self.assertIn(
            "System Settings > Privacy & Security > Automation > "
            "Apple Music Toolbox Runner",
            self.error_line(),
        )

    def test_timed_out_says_the_prompt_was_not_answered(self) -> None:
        result = run_grant.GrantResult("timed-out", "invented (-1712)")
        self.assertEqual(self.report(result), 1)
        self.assertIn(
            "the permission prompt was not answered; run install again",
            self.error_line(),
        )

    def test_no_result_says_the_same_and_names_the_log(self) -> None:
        self.assertEqual(self.report(None), 1)
        line = self.error_line()
        self.assertIn("the permission prompt was not answered; run install again", line)
        self.assertIn(str(self.kit.paths.grant_err_log), line)

    def test_an_error_shows_the_first_line_of_its_detail(self) -> None:
        result = run_grant.GrantResult("error", "invented failure\nsecond line")
        self.assertEqual(self.report(result), 1)
        self.assertEqual(
            self.error_line(), "ERROR: the grant check failed: invented failure"
        )

    def test_an_error_with_no_detail_still_reads(self) -> None:
        self.assertEqual(self.report(run_grant.GrantResult("error", "")), 1)
        self.assertEqual(self.error_line(), "ERROR: the grant check failed: no detail")

    def test_an_outcome_it_does_not_know_is_a_failure_naming_it(self) -> None:
        self.assertEqual(self.report(run_grant.GrantResult("invented", "x")), 1)
        self.assertEqual(
            self.error_line(), "ERROR: the grant check failed: invented: x"
        )


if __name__ == "__main__":
    unittest.main()
