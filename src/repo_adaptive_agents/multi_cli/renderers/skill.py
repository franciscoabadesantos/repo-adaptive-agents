"""Portable Agent Skill renderer (`.agents/skills/<slug>/SKILL.md`).

This is the portable materialization of the canonical role: no CLI-specific prose, no
absolute paths, and no promises of enforcement the file cannot make.
"""

from __future__ import annotations

from ..models import CanonicalRole, RenderedTarget
from .common import ENFORCEMENT_NOTE, bullet_list, frontmatter, numbered_list

VERSION = "1.0"
TARGET = "skill"
PORTABILITY = "portable"


def output_path(role: CanonicalRole) -> str:
    return f"portable/.agents/skills/{role.slug}/SKILL.md"


def render(role: CanonicalRole) -> RenderedTarget:
    meta = frontmatter([("name", role.slug), ("description", role.description)])
    body = "\n".join(
        [
            meta,
            f"# {role.title}",
            "",
            role.purpose,
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
    return RenderedTarget(
        target=TARGET,
        renderer_version=VERSION,
        portability=PORTABILITY,
        files={output_path(role): body},
        semantic_mapping={
            "title": "# heading",
            "description": "frontmatter.description",
            "purpose": "intro paragraph",
            "when_to_use": "## When to use",
            "procedure": "## Procedure",
            "response_format": "## Response format",
            "constraints": "## Constraints",
            "evidence_requirements": "## Evidence requirements",
        },
        unsupported_fields=(
            "runtime_preferences (advisory; no runtime knobs in a portable skill)",
            "delegation (informational; not expressible in SKILL.md)",
        ),
    )
