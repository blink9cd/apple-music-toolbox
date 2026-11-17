"""signed_app: the generic steps behind a small signed macOS app, and the way in to them.

A signed app here is a Swift package built in release, assembled into an `.app` bundle,
signed and verified with a local codesign identity, and put in place for launchd. The
steps every such app shares live in the modules under ``src/``: `app_host` (the
injectable process facts), `app_bundle` (build, Info.plist, assemble, identity, sign)
and `app_install` (private folders, the bundle swap, the linked-worktree refusal). An
app's own CLI supplies its names, folders and messages, and calls them. See
``signed_app.md``.

Importing this module is how a caller reaches them: it puts ``src/`` on ``sys.path``,
then the shared libraries those modules import, each at one fixed place directly under
the project root, beside this library's folder. It has no command line of its own.

Entry point assumptions: imported only, with this folder on ``sys.path``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

#: The library's modules' folder, beside this file.
SRC_DIR: Final = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC_DIR))
# The shared libraries, each at one fixed place: directly under the project root, which
# is this file's grandparent. Deliberately not a search up the ancestors, as in
# scrobbler.py: that would also put any same-named folder above the checkout on
# sys.path. Each entry is a library folder's path below the root and the module that
# marks it: swift_gate's signing reader and run model live in that tool's private src/,
# the rest at the top of their own folders.
_LIBRARIES: Final = (
    ("bounded_run", "bounded_run"),
    ("launchd_agent", "launchd_agent"),
    ("swift_gate/src", "swgate_signing"),
)
sys.path += [
    str(Path(__file__).resolve().parents[1] / folder_name)
    for folder_name, _module in _LIBRARIES
]
