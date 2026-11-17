"""The process-level facts the scrobbler's commands read: signed_app's injectable `Host`.

The `Host`, its pure `tool_environment` helper and `real_host` live in signed_app's
`app_host`, shared with every signed app this project builds; this module names them
for the scrobbler's modules, so each still reads its host from here.

Entry point assumptions: imported by the scrobbler's modules, with `src/`, signed_app's
``src/`` and the shared libraries on `sys.path`, as `scrobbler.py` arranges.
"""

from __future__ import annotations

from app_host import Host, real_host, tool_environment

__all__ = ["Host", "real_host", "tool_environment"]
