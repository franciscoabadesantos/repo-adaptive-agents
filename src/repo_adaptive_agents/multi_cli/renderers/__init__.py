"""Target renderers for the multi-CLI pilot.

Each renderer is isolated in its own module and exposes ``TARGET``, ``VERSION``, and a
``render(role) -> RenderedTarget`` function. The registry order defines the deterministic,
canonical target order used throughout the pilot.
"""

from __future__ import annotations

from ..models import CanonicalRole, RenderedTarget
from . import claude, codex, copilot, skill

# Deterministic canonical order of supported targets.
RENDERERS = {
    skill.TARGET: skill,
    codex.TARGET: codex,
    claude.TARGET: claude,
    copilot.TARGET: copilot,
}

TARGETS: list[str] = list(RENDERERS)


def render_target(target: str, role: CanonicalRole) -> RenderedTarget:
    """Render one target for a role. Raises ``KeyError`` for an unknown target."""
    return RENDERERS[target].render(role)


def renderer_versions() -> dict[str, str]:
    """Deterministic mapping of target -> renderer version."""
    return {name: module.VERSION for name, module in RENDERERS.items()}
