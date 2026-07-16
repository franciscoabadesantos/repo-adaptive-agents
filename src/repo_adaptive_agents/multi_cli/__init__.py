"""Experimental multi-CLI role rendering (pilot).

Renders canonical roles into portable and target-specific wrappers for the Agent Skill
format, Codex, Claude Code, and GitHub Copilot. This is a proposal generator only: it
never applies changes, never writes to HOME, and never touches an existing Codex config.
"""

from __future__ import annotations

from .generator import (
    GENERATOR_VERSION,
    SCHEMA_VERSION,
    CompareReport,
    MultiCliError,
    compare_proposal,
    render_role,
    resolve_targets,
    write_proposal,
)
from .models import (
    CanonicalRole,
    DelegationPolicy,
    RenderedTarget,
    RoleConstraints,
    RuntimePreferences,
)
from .renderers import TARGETS
from .roles import ROLES, get_role, role_ids
from .validator import validate_proposal

__all__ = [
    "CanonicalRole",
    "CompareReport",
    "DelegationPolicy",
    "GENERATOR_VERSION",
    "MultiCliError",
    "ROLES",
    "RenderedTarget",
    "RoleConstraints",
    "RuntimePreferences",
    "SCHEMA_VERSION",
    "TARGETS",
    "compare_proposal",
    "get_role",
    "render_role",
    "resolve_targets",
    "role_ids",
    "validate_proposal",
    "write_proposal",
]
