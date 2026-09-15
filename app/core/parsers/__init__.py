"""Response-parser package for the standalone Codex Web Bridge.

The standalone runtime supports the ChatGPT parser used by the controlled
Codex-Web execution path. Provider-specific parser exports from the integrated
UWA application are intentionally outside the standalone surface.
"""

from __future__ import annotations

from .base import ResponseParser
from .registry import ParserRegistry
from .chatgpt_parser import ChatGPTParser


ParserRegistry.register_class(ChatGPTParser)

__all__ = [
    "ResponseParser",
    "ParserRegistry",
    "ChatGPTParser",
]
