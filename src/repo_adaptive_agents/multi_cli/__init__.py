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
    InvocationScope,
    RenderedTarget,
    RoleConstraints,
    RuntimePreferences,
)
from .renderers import TARGETS
from .roles import ROLES, get_role, role_ids
from .scope import ScopeError, build_scope, normalize_path
from .validator import validate_proposal

__all__ = [
    "CanonicalRole",
    "CompareReport",
    "DelegationPolicy",
    "GENERATOR_VERSION",
    "InvocationScope",
    "MultiCliError",
    "ROLES",
    "RenderedTarget",
    "RoleConstraints",
    "RuntimePreferences",
    "SCHEMA_VERSION",
    "ScopeError",
    "TARGETS",
    "build_scope",
    "compare_proposal",
    "get_role",
    "normalize_path",
    "render_role",
    "resolve_targets",
    "role_ids",
    "validate_proposal",
    "write_proposal",
]
