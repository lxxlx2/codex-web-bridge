from tools import codex_remote_compaction_trigger_probe as remote_probe


def test_remote_probe_switches_delegated_scanner_to_v2_markers():
    # The wrapper and delegated trigger probe intentionally use top-level tool
    # imports when executed as scripts. Assert against those exact module
    # objects rather than importing the same file again through the `tools.`
    # namespace, which would create a distinct Python module instance.
    base = remote_probe.base
    trigger_probe = remote_probe.trigger_probe
    old_route = base.COMPACT_ROUTE_MARKER
    old_success = base.COMPACT_SUCCESS_MARKER
    try:
        remote_probe.configure_remote_v2_markers()
        assert base.COMPACT_ROUTE_MARKER == remote_probe.REMOTE_V2_ROUTE_MARKER
        assert base.COMPACT_SUCCESS_MARKER == remote_probe.REMOTE_V2_SUCCESS_MARKER
        assert "/v1/responses/compact" not in base.COMPACT_ROUTE_MARKER
        assert trigger_probe.base is base
    finally:
        base.COMPACT_ROUTE_MARKER = old_route
        base.COMPACT_SUCCESS_MARKER = old_success


def test_remote_success_marker_is_stricter_than_route_marker():
    assert remote_probe.REMOTE_V2_SUCCESS_MARKER.startswith(
        remote_probe.REMOTE_V2_ROUTE_MARKER
    )
    assert "completed remote compact" in remote_probe.REMOTE_V2_SUCCESS_MARKER
