"""Response-parser package for the standalone Codex Web Bridge.

The standalone runtime needs the ChatGPT parser eagerly. Historical UWA parser
classes remain available through lazy attribute imports for compatibility while
S2 is in progress, but importing this package no longer imports and registers
every unrelated provider parser.
"""

from __future__ import annotations

import importlib
from typing import Any

from .base import ResponseParser
from .registry import ParserRegistry
from .chatgpt_parser import ChatGPTParser


ParserRegistry.register_class(ChatGPTParser)

_LAZY_EXPORTS = {
    "GeminiParser": (".gemini_parser", "GeminiParser"),
    "DeepSeekParser": (".deepseek_parser", "DeepSeekParser"),
    "AIStudioParser": (".aistudio_parser", "AIStudioParser"),
    "DoubaoParser": (".doubao_parser", "DoubaoParser"),
    "ClaudeParser": (".claude_parser", "ClaudeParser"),
    "KimiParser": (".kimi_parser", "KimiParser"),
    "GLMParser": (".glm_parser", "GLMParser"),
    "QwenParser": (".qwen_parser", "QwenParser"),
    "MimoParser": (".mimo_parser", "MimoParser"),
    "LmarenaParser": (".lmarena_parser", "LmarenaParser"),
    "LmarenaSideLeftParser": (".lmarena_side_left_parser", "LmarenaSideLeftParser"),
    "LmarenaBattleWinnerParser": (".lmarena_battle_side_parser", "LmarenaBattleWinnerParser"),
    "LmarenaBattleSideLeftParser": (".lmarena_battle_side_parser", "LmarenaBattleSideLeftParser"),
    "LmarenaBattleSideRightParser": (".lmarena_battle_side_parser", "LmarenaBattleSideRightParser"),
    "LmarenaImageSideLeftParser": (".lmarena_image_side_left_parser", "LmarenaImageSideLeftParser"),
    "LmarenaImageSideRightParser": (".lmarena_image_side_right_parser", "LmarenaImageSideRightParser"),
    "GrokParser": (".grok_parser", "GrokParser"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, class_name = target
    parser_class = getattr(importlib.import_module(module_name, __name__), class_name)
    ParserRegistry.register_class(parser_class)
    globals()[name] = parser_class
    return parser_class


__all__ = [
    "ResponseParser",
    "ParserRegistry",
    "ChatGPTParser",
    *_LAZY_EXPORTS.keys(),
]
