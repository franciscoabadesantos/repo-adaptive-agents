"""Codex agent renderer (`.codex/agents/<id>.toml`).

Codex resolves an agent from a TOML file. There is no native reference to a SKILL.md, so
this wrapper is self-contained and preserves the critical constraints inline. Runtime knobs
with no canonical equivalent (notably ``model``) are intentionally left unset so the Codex
config can supply them.
"""

from __future__ import annotations

import json

from ..models import CanonicalRole, InvocationScope, RenderedTarget
from .common import (
    ADVISORY_SCOPE_WARNINGS,
    CODEX_WORKSPACE_WARNING,
    SCOPE_WORKING_RULES,
    scope_metadata,
)

VERSION = "1.1"
TARGET = "codex"
PORTABILITY = "target_specific"

# Codex enforces a workspace-write sandbox; it bounds the workspace, not allowed_paths.
_WORKSPACE_SANDBOX = {"mode": "workspace-write", "scope": "workspace", "path_scope_enforced": False}


def output_path(role: CanonicalRole) -> str:
    return f"codex/.codex/agents/{role.id}.toml"


def registration_path(role: CanonicalRole) -> str:
    return f"codex/.codex/config.fragments/{role.id}.toml"


def _toml_string(value: str) -> str:
    """A double-quoted TOML basic string via JSON encoding (identical grammar subset)."""
    return json.dumps(value, ensure_ascii=False)


def _scope_lines(scope: InvocationScope) -> list[str]:
    lines = [
        "Invocation scope (advisory; not technically enforced by this file):",
        f"- Scope: {scope.description}",
        f"- Allowed paths: {', '.join(scope.allowed_paths)}",
        f"- Blocked paths: {', '.join(scope.blocked_paths) if scope.blocked_paths else 'none'}",
    ]
    lines.extend(f"- {rule}" for rule in SCOPE_WORKING_RULES)
    lines.append("")
    return lines


def _developer_instructions(role: CanonicalRole, scope: InvocationScope | None) -> str:
    lines = [role.purpose, ""]
    if scope:
        lines.extend(_scope_lines(scope))
    lines.append("Capabilities:")
    lines.extend(f"- {capability}" for capability in role.capabilities)
    lines.extend(["", "Procedure:"])
    lines.extend(f"- {step}" for step in role.procedure)
    lines.extend(["", "Response format:"])
    lines.extend(f"- {item}" for item in role.response_format)
    lines.extend(["", "Constraints:"])
    lines.extend(f"- {rule}" for rule in role.critical_constraints())
    lines.extend(["", "Evidence requirements:"])
    lines.extend(f"- {item}" for item in role.evidence_requirements)
    return "\n".join(lines)


def _registration_fragment(role: CanonicalRole) -> str:
    return "\n".join(
        [
            f"[agents.{role.id}]",
            f"description = {_toml_string(role.description)}",
            f"config_file = {_toml_string(f'.codex/agents/{role.id}.toml')}",
            "",
        ]
    )


def render(role: CanonicalRole, scope: InvocationScope | None = None) -> RenderedTarget:
    sandbox = "read-only" if role.constraints.read_only else "workspace-write"
    lines = [
        f"name = {_toml_string(role.id)}",
        f"description = {_toml_string(role.description)}",
        f"model_reasoning_effort = {_toml_string(role.runtime_preferences.reasoning_intensity)}",
        f"sandbox_mode = {_toml_string(sandbox)}",
        'nickname_candidates = ["Auditor"]',
        f"developer_instructions = {_toml_string(_developer_instructions(role, scope))}",
        "",
    ]
    wrapper = output_path(role)
    fragment = registration_path(role)
    scope_warnings = (ADVISORY_SCOPE_WARNINGS + (CODEX_WORKSPACE_WARNING,)) if scope else ()
    return RenderedTarget(
        target=TARGET,
        renderer_version=VERSION,
        portability=PORTABILITY,
        files={
            wrapper: "\n".join(lines),
            fragment: _registration_fragment(role),
        },
        enforcement={
            "mode": "sandboxed",
            "runtime_controls_generated": True,
            "controls": ["sandbox_mode"],
        },
        semantic_mapping={
            "id": "name",
            "description": "description",
            "runtime_preferences.reasoning_intensity": "model_reasoning_effort",
            "constraints.read_only": "sandbox_mode",
            "purpose+capabilities+procedure+constraints+evidence_requirements": "developer_instructions",
            "registration": "config.fragments TOML fragment",
            **({"invocation_scope": "developer_instructions scope block"} if scope else {}),
        },
        unsupported_fields=(
            "model (left unset; inherited from .codex/config.toml, not chosen by canonical)",
            "delegation.parallelizable (orchestrator concern; not a per-agent TOML field)",
            "runtime_preferences.context_isolation_preferred (no confirmed TOML field)",
        ),
        warnings=(
            "The registration fragment is generated for manual merge only; it is not applied to .codex/config.toml.",
        )
        + scope_warnings,
        artifacts={"agent_wrapper": wrapper, "registration_fragment": fragment},
        scope_metadata=scope_metadata(role, scope, _WORKSPACE_SANDBOX) if scope else {},
    )
