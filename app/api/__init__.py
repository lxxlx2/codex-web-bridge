"""API package for the standalone Codex Web Bridge.

Standalone imports submodules directly and deliberately exposes no generic UWA
aggregate router. Keeping this package side-effect free prevents legacy admin,
provider, configuration, and command routes from remaining in the dependency
closure solely for compatibility with the integrated repository.
"""

from __future__ import annotations

__all__: list[str] = []
