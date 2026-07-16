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
