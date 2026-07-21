"""Experimental multi-CLI role rendering (pilot).

Renders canonical roles into portable and target-specific wrappers for the Agent Skill
format, Codex, Claude Code, and GitHub Copilot. Rendering is proposal-only; the separate
installer requires explicit application and never overwrites existing files or writes HOME.
"""

from __future__ import annotations

from .adapter_generator import render_adapter_bundle, write_adapter_bundle
from .adapters import (
    AdapterOption,
    AdapterPlan,
    AdapterSelection,
    AdapterSelectionError,
    list_adapter_options,
    select_adapters,
)
from .deployment import (
    AdapterInstallError,
    InstallEntry,
    InstallPlan,
    InstallResult,
    apply_adapter_install,
    plan_adapter_install,
)
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
from .validator import validate_adapter_bundle, validate_proposal

__all__ = [
    "AdapterOption",
    "AdapterPlan",
    "AdapterSelection",
    "AdapterSelectionError",
    "AdapterInstallError",
    "CanonicalRole",
    "CompareReport",
    "DelegationPolicy",
    "GENERATOR_VERSION",
    "InvocationScope",
    "InstallEntry",
    "InstallPlan",
    "InstallResult",
    "MultiCliError",
    "ROLES",
    "RenderedTarget",
    "RoleConstraints",
    "RuntimePreferences",
    "SCHEMA_VERSION",
    "ScopeError",
    "TARGETS",
    "apply_adapter_install",
    "build_scope",
    "compare_proposal",
    "get_role",
    "list_adapter_options",
    "normalize_path",
    "plan_adapter_install",
    "render_adapter_bundle",
    "render_role",
    "resolve_targets",
    "role_ids",
    "select_adapters",
    "validate_adapter_bundle",
    "validate_proposal",
    "write_adapter_bundle",
    "write_proposal",
]
