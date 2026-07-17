"""Portable Agent Skill renderer (`.agents/skills/<slug>/SKILL.md`).

This is the portable materialization of the canonical role: no CLI-specific prose, no
absolute paths, and no promises of enforcement the file cannot make.
"""

from __future__ import annotations

from ..models import CanonicalRole, InvocationScope, RenderedTarget
from .common import (
    ADVISORY_SCOPE_WARNINGS,
    ENFORCEMENT_NOTE,
    bullet_list,
    frontmatter,
    numbered_list,
    scope_metadata,
    scope_section,
)

VERSION = "1.0"
TARGET = "skill"
PORTABILITY = "portable"

# Markdown wrappers have no technical sandbox; scope is advisory only.
_ADVISORY_SANDBOX = {"mode": "none", "scope": "advisory", "path_scope_enforced": False}


def output_path(role: CanonicalRole) -> str:
    return f"portable/.agents/skills/{role.slug}/SKILL.md"


def render(role: CanonicalRole, scope: InvocationScope | None = None) -> RenderedTarget:
    meta = frontmatter([("name", role.slug), ("description", role.description)])
    body = "\n".join(
        [
            meta,
            f"# {role.title}",
            "",
            role.purpose,
            "",
            *(scope_section(scope) if scope else []),
            "## Capabilities",
            "",
            bullet_list(role.capabilities),
            "",
            "## When to use",
            "",
            bullet_list(role.when_to_use),
            "",
            "## Procedure",
            "",
            numbered_list(role.procedure),
            "",
            "## Response format",
            "",
            bullet_list(role.response_format),
            "",
            "## Constraints",
            "",
            *ENFORCEMENT_NOTE,
            "",
            bullet_list(role.critical_constraints()),
            "",
            "## Evidence requirements",
            "",
            bullet_list(role.evidence_requirements),
            "",
        ]
    )
    mapping = {
        "title": "# heading",
        "description": "frontmatter.description",
        "purpose": "intro paragraph",
        "capabilities": "## Capabilities",
        "when_to_use": "## When to use",
        "procedure": "## Procedure",
        "response_format": "## Response format",
        "constraints": "## Constraints",
        "evidence_requirements": "## Evidence requirements",
    }
    if scope:
        mapping["invocation_scope"] = "## Invocation scope"
    return RenderedTarget(
        target=TARGET,
        renderer_version=VERSION,
        portability=PORTABILITY,
        files={output_path(role): body},
        semantic_mapping=mapping,
        unsupported_fields=(
            "runtime_preferences (advisory; no runtime knobs in a portable skill)",
            "delegation (informational; not expressible in SKILL.md)",
        ),
        warnings=ADVISORY_SCOPE_WARNINGS if scope else (),
        scope_metadata=scope_metadata(role, scope, _ADVISORY_SANDBOX) if scope else {},
    )
