"""run_install's uninstall: the grant agent unloaded, the bundle removed, the logs kept.

Every tool and launchd are fakes from `_run_fixtures`, under a temporary home.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _run_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import launchd_agent  # noqa: E402 - on sys.path once _run_fixtures is imported
import run_install  # noqa: E402 - on sys.path once _run_fixtures is imported

if sys.platform == "win32":
    # POSIX only, as the runner is.
    raise unittest.SkipTest("the runner runs on macOS only")  # pragma: only-on win32


class UninstallTest(unittest.TestCase):
    """uninstall unloads the grant agent, removes the bundle, and says what breaks."""

    def setUp(self) -> None:
        self.kit = fx.make_kit(self)

    def uninstall(self) -> int:
        """Run uninstall against the kit."""
        return run_install.uninstall(self.kit.host, self.kit.layout)

    def test_the_bundle_and_a_loaded_grant_agent_are_removed(self) -> None:
        self.kit.install_app()
        self.kit.paths.grant_plist.parent.mkdir(parents=True)
        self.kit.paths.grant_plist.write_bytes(b"invented plist")
        self.kit.launchd.loaded.add(self.kit.layout.grant_label)
        (self.kit.paths.logs_dir).mkdir()
        self.assertEqual(self.uninstall(), 0)
        self.assertFalse(self.kit.paths.app_bundle.exists())
        self.assertFalse(self.kit.paths.grant_plist.exists())
        self.assertEqual(self.kit.launchd.loaded, set())
        self.assertTrue(self.kit.paths.logs_dir.is_dir())
        out = self.kit.out.getvalue()
        # The whole line: it names no job, since which jobs start through the runner
        # is theirs to know.
        self.assertEqual(
            out,
            f"removed {self.kit.paths.app_bundle}. A scheduled job that starts through "
            "the runner fails from now on: reinstall that job, or install the runner "
            "again.\n",
        )

    def test_nothing_installed_is_exit_0_and_says_so(self) -> None:
        self.assertEqual(self.uninstall(), 0)
        self.assertEqual(
            self.kit.out.getvalue(),
            "Apple Music Toolbox Runner is not installed; nothing was removed\n",
        )

    def test_an_agent_launchd_answers_oddly_about_keeps_the_bundle(self) -> None:
        self.kit.install_app()
        self.kit.launchd.unknown.add(self.kit.layout.grant_label)
        with self.assertRaises(launchd_agent.LaunchdError):
            self.uninstall()
        self.assertTrue(self.kit.paths.app_bundle.exists())


if __name__ == "__main__":
    unittest.main()
