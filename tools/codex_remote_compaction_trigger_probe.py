#!/usr/bin/env python3
"""Run the P1.2 small-step trigger probe with remote-V2-specific log evidence.

The generic large-context harness predates Codex 0.153.4 remote compaction V2 and
tracks the legacy `/v1/responses/compact` route. V2 travels through ordinary
`/v1/responses`, so a generic path counter would be polluted by every normal
turn. This thin wrapper switches the shared bounded log scanner to UWA's
metadata-only V2 markers and delegates all threshold/thread/tool safety checks to
the already-live small-step probe.
"""

from __future__ import annotations

import codex_auto_compact_trigger_probe as trigger_probe
import codex_large_context_acceptance as base


REMOTE_V2_ROUTE_MARKER = "[CODEX_REMOTE_COMPACTION_V2]"
REMOTE_V2_SUCCESS_MARKER = "[CODEX_REMOTE_COMPACTION_V2] completed remote compact:"


def configure_remote_v2_markers() -> None:
    base.COMPACT_ROUTE_MARKER = REMOTE_V2_ROUTE_MARKER
    base.COMPACT_SUCCESS_MARKER = REMOTE_V2_SUCCESS_MARKER


def main() -> int:
    configure_remote_v2_markers()
    return trigger_probe.main()


if __name__ == "__main__":
    raise SystemExit(main())
