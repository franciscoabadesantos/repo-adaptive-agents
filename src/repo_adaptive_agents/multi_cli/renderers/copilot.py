"""GitHub Copilot custom agent renderer (`.github/agents/<slug>.agent.md`).

Markdown with YAML frontmatter for confirmed fields only. This file represents a Copilot
*custom agent*. It is not `.github/copilot-instructions.md` and is not read by inline
autocomplete; the manifest records that distinction. Copilot's discovery surface differs
across modes, so nothing here assumes a single one.
"""

from __future__ import annotations

from ..models import CanonicalRole, RenderedTarget
from .common import ENFORCEMENT_NOTE, bullet_list, frontmatter, numbered_list

VERSION = "1.0"
TARGET = "copilot"
PORTABILITY = "generated"


def output_path(role: CanonicalRole) -> str:
    return f"copilot/.github/agents/{role.slug}.agent.md"


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
            "slug": "frontmatter.name",
            "description": "frontmatter.description",
            "purpose": "intro paragraph",
            "procedure": "## Procedure",
            "constraints": "## Constraints",
            "evidence_requirements": "## Evidence requirements",
        },
        unsupported_fields=(
            "model (frontmatter compatibility not confirmed by this renderer; omitted)",
            "tools (frontmatter compatibility not confirmed by this renderer; omitted)",
            "runtime_preferences (no confirmed frontmatter equivalent; expressed as prose)",
            "delegation (orchestrator concern; not a custom-agent frontmatter field)",
        ),
        warnings=(
            "This is a Copilot custom agent, not .github/copilot-instructions.md and not inline autocomplete configuration.",
        ),
    )
