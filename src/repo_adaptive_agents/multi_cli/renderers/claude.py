"""Claude Code subagent renderer (`.claude/agents/<slug>.md`).

Markdown with YAML frontmatter. The frontmatter carries only fields whose compatibility is
confirmed for a Claude Code subagent (``name``, ``description``); anything unconfirmed is
omitted and recorded in the manifest as unsupported. No Agent Teams settings, no hooks.
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
TARGET = "claude"
PORTABILITY = "generated"

# Markdown wrappers have no technical sandbox; scope is advisory only.
_ADVISORY_SANDBOX = {"mode": "none", "scope": "advisory", "path_scope_enforced": False}


def output_path(role: CanonicalRole) -> str:
    return f"claude/.claude/agents/{role.slug}.md"


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
    return RenderedTarget(
        target=TARGET,
        renderer_version=VERSION,
        portability=PORTABILITY,
        files={output_path(role): body},
        semantic_mapping={
            "slug": "frontmatter.name",
            "description": "frontmatter.description",
            "purpose": "intro paragraph",
            "capabilities": "## Capabilities",
            "procedure": "## Procedure",
            "constraints": "## Constraints",
            "evidence_requirements": "## Evidence requirements",
            **({"invocation_scope": "## Invocation scope"} if scope else {}),
        },
        unsupported_fields=(
            "model (frontmatter compatibility not confirmed by this renderer; omitted)",
            "tools (frontmatter compatibility not confirmed by this renderer; omitted)",
            "runtime_preferences (no confirmed frontmatter equivalent; expressed as prose)",
            "delegation (orchestrator concern; not a subagent frontmatter field)",
        ),
        warnings=ADVISORY_SCOPE_WARNINGS if scope else (),
        scope_metadata=scope_metadata(role, scope, _ADVISORY_SANDBOX) if scope else {},
    )
