"""Shared selectors for detecting an active browser generation.

Keep stream completion and pre-send idle guards on the same selector set. A
locale-specific Stop control must never be visible to one lifecycle guard but
invisible to the other, otherwise a completed-looking DOM reply can be released
while the same Web generation is still active.
"""

from __future__ import annotations


GENERATION_INDICATOR_CSS_SELECTORS = (
    'button[aria-label*="Stop"]',
    'button[aria-label*="stop"]',
    'button[aria-label*="停止"]',
    'button[data-testid="stop-button"]',
    '[data-testid="stop-button"]',
    '[data-state="streaming"]',
    '.stop-generating',
)


__all__ = ["GENERATION_INDICATOR_CSS_SELECTORS"]
