"""The wrapper's launch-agent start word is the one the Swift app's parser accepts.

``launch_argument/start-word.txt`` holds the single argument the installed agent passes
to the app. The Swift package's command-line tests read the same file and require the
real parser to turn it into the run command, so renaming the word on either side fails a
test on that side instead of leaving the agent to exit 2 and restart in a loop.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _scrob_fixtures  # noqa: E402,F401 - puts the wrapper's src folder on sys.path
import scrob_agent  # noqa: E402 - on sys.path once _scrob_fixtures is imported

#: The file the Swift command-line test reads too.
START_WORD_FILE = (
    Path(__file__).resolve().parents[1] / "launch_argument" / "start-word.txt"
)


class LaunchArgumentTest(unittest.TestCase):
    """The start word the plist carries is the one the shared file names."""

    def test_the_run_argument_is_the_shared_start_word(self) -> None:
        shared = START_WORD_FILE.read_text(encoding="utf-8")
        self.assertEqual(shared, scrob_agent.RUN_ARGUMENT + "\n")


if __name__ == "__main__":
    unittest.main()
