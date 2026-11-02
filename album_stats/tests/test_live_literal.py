"""One live pass through the real AppleScript compiler, for the literal escape.

`album_stats/test_album_stats.py` proves the escape by reading the generated
source: `assertIn('album is "The \\"Blue\\" Album"', script)` and its siblings. That
pins the characters this side of the boundary and nothing beyond it: whether the
compiler on the other side reads those characters back as the name they came from is
an assumption those tests cannot fail on. Escaping that crosses a quoting layer has
to be proven by behavior rather than by reading the characters it produced, and this
is that layer: a name that escaped its literal would stop being data and become
AppleScript source, in a language where `do shell script` exists.

So each name below is escaped, spliced into a script, compiled and evaluated for real,
and the value that comes back must equal the name that went in. With the `translate`
pass removed, `x" & "INJECTED" & "y` comes back as `xINJECTEDy`: the middle stopped
being text and became a concatenation the compiler performed.

Nothing here reaches Music.app, the network, or any library. The script is a bare
`return "<literal>"` (no `tell` block, no application, no property read), so it
compiles and answers inside `osascript` itself. That is why it is not gated on
`APPLE_MUSIC_TOOLBOX_OFFLINE`, which means "no Music.app and no network": this makes neither
kind of call, and gating it there would leave the one test that actually crosses the
boundary skipped in exactly the runs that gate the code.

The interpreter is named by its absolute path on purpose. A session working offline
puts a fake `osascript` first on `PATH` so nothing can reach the library by accident,
and a fake answering this script would leave every assertion below passing while
proving nothing whatever: a test whose subject can be shadowed by something earlier on
`PATH` is a test of that something. Resolving it absolutely is what keeps a pass
meaningful, and the path is a standard macOS location rather than this machine's.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import album_stats  # noqa: E402 - import follows the sys.path bootstrap above
from recently_added import (  # noqa: E402 - import follows the sys.path bootstrap above
    _real_run,
)

#: macOS ships the AppleScript interpreter here, and only here.
_OSASCRIPT = Path("/usr/bin/osascript")

#: Compiling and evaluating a string literal is immediate work with no I/O of any
#: kind, so this bounds a hung process rather than a slow one. The bound is on the
#: call itself, through the same `run_bounded` seam the tool uses.
_COMPILE_TIMEOUT_SECONDS = 20.0

#: `osascript` terminates its printed result with one newline of its own. Removing
#: exactly one, not `.strip()`, is what lets a name that legitimately ends in
#: whitespace, or spans two lines, still be compared for equality.
_RESULT_TERMINATOR = "\n"


@unittest.skipUnless(sys.platform == "darwin", "AppleScript is macOS-only")
@unittest.skipUnless(_OSASCRIPT.is_file(), f"{_OSASCRIPT} is not installed")
class LiveLiteralRoundTripTest(unittest.TestCase):
    """Every escaped name comes back out of the real compiler unchanged."""

    def _evaluate(self, literal: str) -> subprocess.CompletedProcess[str]:
        """Compile and evaluate `return <literal>`, bounded, and hand back the result."""
        return _real_run(
            [str(_OSASCRIPT), "-e", f"return {literal}"], _COMPILE_TIMEOUT_SECONDS
        )

    def test_every_escaped_name_survives_the_real_compiler(self) -> None:
        for label, name in (
            ("a double quote", 'a"b'),
            ("a lone backslash", "a\\b"),
            ("a backslash before a quote", 'a\\"b'),
            # The injection itself: unescaped, the quotes close the literal and what
            # sits between them is read as an AppleScript concatenation.
            ("an attempted concatenation", 'x" & "INJECTED" & "y'),
            ("two lines", "two\nlines"),
            ("curly quotes", "“curly”"),
            # AppleScript's own line-continuation character.
            ("a continuation mark", "not¬x"),
        ):
            with self.subTest(label):
                literal = album_stats._applescript_literal(name)
                result = self._evaluate(literal)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.stdout.removesuffix(_RESULT_TERMINATOR),
                    name,
                    f"{literal!r} did not compile back to the name it came from",
                )


if __name__ == "__main__":
    unittest.main()
