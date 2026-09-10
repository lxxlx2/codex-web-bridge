"""
app/core/page_capture - page-side runtime helpers.

The standalone Codex/ChatGPT build intentionally carries no provider-specific
Kimi fetch capture or DeepSeek request transport implementations.  The generic
registries remain available for the shared browser/workflow runtime.
"""

from .base import PageFetchCapture
from .registry import (
    create_page_fetch_capture,
    register_page_fetch_capture,
)
from .request_transport import (
    execute_page_request_transport,
    get_page_request_transport_profile,
    get_page_request_transport_profiles,
    register_page_request_transport,
)

__all__ = [
    "PageFetchCapture",
    "create_page_fetch_capture",
    "execute_page_request_transport",
    "get_page_request_transport_profile",
    "get_page_request_transport_profiles",
    "register_page_fetch_capture",
    "register_page_request_transport",
]
