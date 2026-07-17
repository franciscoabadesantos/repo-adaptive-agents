"""Deterministic formatting helpers shared by the target renderers.

Helpers here must be pure and produce stable, byte-for-byte identical output for the same
input. They never emit absolute paths and never depend on the environment.
"""

from __future__ import annotations

# Shared, deterministic note that makes the guidance-vs-enforcement boundary explicit.
# Rendered verbatim above the constraints list in every Markdown wrapper.
ENFORCEMENT_NOTE = (
    "These constraints are behavioral guidance, not technical enforcement.",
    "Enforce them through the host tool's permissions, approvals, sandbox, and repository policy.",
)

# Lexical-only path validation flags, shared by every target's scope metadata.
PATH_VALIDATION = {"lexical": True, "filesystem_resolved": False, "symlink_escape_checked": False}

# Warnings every target must carry when a write role is rendered with an explicit scope.
ADVISORY_SCOPE_WARNINGS = (
    "path scope is advisory and not technically enforced",
    "symlink/filesystem validation was not performed",
)
# Additional warning specific to the Codex workspace-write sandbox.
CODEX_WORKSPACE_WARNING = "Codex workspace-write limits the workspace, not allowed_paths"

# The scope working-rules block, injected verbatim into every wrapper's prose.
SCOPE_WORKING_RULES = (
    "Stop before editing anything outside the allowed paths.",
    "Blocked paths override allowed paths.",
    "Preserve pre-existing local changes; do not revert unrelated work.",
    "Do not perform destructive deletes or renames.",
    "Do not commit, push, deploy, or access the network.",
    "Run only safe local validations and report the result.",
)


def scope_section(scope) -> list[str]:
    """Markdown lines for the advisory invocation-scope block. Deterministic."""
    lines = [
        "## Invocation scope",
        "",
        "This scope is advisory. Path scoping is not technically enforced by these files;",
        "the host tool's sandbox and permissions are the actual boundary.",
        "",
        f"Scope: {scope.description}",
        "",
        "Allowed paths:",
        "",
        bullet_list(scope.allowed_paths),
        "",
    ]
    if scope.blocked_paths:
        lines += ["Blocked paths (blocked overrides allowed):", "", bullet_list(scope.blocked_paths), ""]
    else:
        lines += ["Blocked paths: none. Blocked paths always override allowed paths.", ""]
    lines += ["Working rules:", "", bullet_list(SCOPE_WORKING_RULES), ""]
    return lines


def scope_metadata(role, scope, sandbox: dict) -> dict:
    """Per-target manifest metadata for an explicit invocation scope.

    ``sandbox`` is the target-specific sandbox block; the remaining blocks derive from the
    canonical role constraints and the (already normalized) scope.
    """
    return {
        "sandbox": sandbox,
        "write_scope": {
            "mode": "explicit-advisory",
            "enforced": False,
            "description": scope.description,
            "allowed_paths": list(scope.allowed_paths),
            "blocked_paths": list(scope.blocked_paths),
        },
        "destructive_actions": {
            "delete": role.constraints.allow_delete,
            "commit": role.constraints.allow_commit,
            "push": role.constraints.allow_push,
            "deploy": role.constraints.allow_deploy,
            "network": role.constraints.allow_network,
        },
        "validation_required": role.constraints.require_validation,
        "path_validation": dict(PATH_VALIDATION),
    }


def yaml_scalar(value: str) -> str:
    """Return a YAML double-quoted scalar. Inputs are single-line by contract."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def frontmatter(fields: list[tuple[str, str]]) -> str:
    """Render an ordered YAML frontmatter block with double-quoted scalar values."""
    body = "\n".join(f"{key}: {yaml_scalar(value)}" for key, value in fields)
    return f"---\n{body}\n---\n"


def bullet_list(items: tuple[str, ...] | list[str]) -> str:
    """Render a Markdown bullet list, one item per line."""
    return "\n".join(f"- {item}" for item in items)


def numbered_list(items: tuple[str, ...] | list[str]) -> str:
    """Render a Markdown ordered list, one item per line."""
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))
