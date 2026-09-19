"""Service package for the standalone Codex Web Bridge.

Runtime code imports the required service modules directly. Keep package import
side effects empty so importing a focused Codex service cannot instantiate the
legacy generic configuration engine or other integrated UWA services.
"""

from __future__ import annotations

__all__: list[str] = []
