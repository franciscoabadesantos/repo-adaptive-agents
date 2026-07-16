"""Codex agent renderer (`.codex/agents/<id>.toml`).

Codex resolves an agent from a TOML file. There is no native reference to a SKILL.md, so
this wrapper is self-contained: it preserves the critical constraints inline and points to
the skill path only as complementary context. Runtime knobs with no canonical equivalent
(notably ``model``) are intentionally left unset so the Codex config can supply them.
"""

from __future__ import annotations

import json

from ..models import CanonicalRole, RenderedTarget

VERSION = "1.0"
TARGET = "codex"
PORTABILITY = "target_specific"


def output_path(role: CanonicalRole) -> str:
    return f"codex/.codex/agents/{role.id}.toml"


def registration_path(role: CanonicalRole) -> str:
    return f"codex/.codex/config.fragments/{role.id}.toml"


def _toml_string(value: str) -> str:
    """A double-quoted TOML basic string via JSON encoding (identical grammar subset)."""
    return json.dumps(value, ensure_ascii=False)


def _developer_instructions(role: CanonicalRole) -> str:
    lines = [role.purpose, "", "Capabilities:"]
    lines.extend(f"- {capability}" for capability in role.capabilities)
    lines.extend(["", "Procedure:"])
    lines.extend(f"- {step}" for step in role.procedure)
    lines.extend(["", "Response format:"])
    lines.extend(f"- {item}" for item in role.response_format)
    lines.extend(["", "Constraints:"])
    lines.extend(f"- {rule}" for rule in role.critical_constraints())
    lines.extend(["", "Evidence requirements:"])
    lines.extend(f"- {item}" for item in role.evidence_requirements)
    lines.extend(
        [
            "",
            f"Complementary context (read-only): .agents/skills/{role.slug}/SKILL.md",
        ]
    )
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


def render(role: CanonicalRole) -> RenderedTarget:
    sandbox = "read-only" if role.constraints.read_only else "workspace-write"
    lines = [
        f"name = {_toml_string(role.id)}",
        f"description = {_toml_string(role.description)}",
        f"model_reasoning_effort = {_toml_string(role.runtime_preferences.reasoning_intensity)}",
        f"sandbox_mode = {_toml_string(sandbox)}",
        'nickname_candidates = ["Auditor"]',
        f"developer_instructions = {_toml_string(_developer_instructions(role))}",
        "",
    ]
    wrapper = output_path(role)
    fragment = registration_path(role)
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
            "slug": "developer_instructions skill path reference",
            "registration": "config.fragments TOML fragment",
        },
        unsupported_fields=(
            "model (left unset; inherited from .codex/config.toml, not chosen by canonical)",
            "delegation.parallelizable (orchestrator concern; not a per-agent TOML field)",
            "runtime_preferences.context_isolation_preferred (no confirmed TOML field)",
        ),
        warnings=(
            "The registration fragment is generated for manual merge only; it is not applied to .codex/config.toml.",
        ),
        artifacts={"agent_wrapper": wrapper, "registration_fragment": fragment},
    )
