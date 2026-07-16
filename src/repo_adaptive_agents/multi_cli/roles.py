"""Canonical role definitions for the multi-CLI pilot.

The pilot ships exactly one role: ``independent_reviewer``. The canonical source is
versioned Python for determinism and easy validation; it can be moved to YAML/JSON later
without changing the renderer contract.
"""

from __future__ import annotations

from .models import (
    CanonicalRole,
    DelegationPolicy,
    RoleConstraints,
    RuntimePreferences,
)

INDEPENDENT_REVIEWER = CanonicalRole(
    id="independent_reviewer",
    slug="independent-review",
    title="Independent Reviewer",
    description=(
        "Read-only independent reviewer that inspects a scoped change and reports "
        "findings ordered by severity with per-path evidence."
    ),
    purpose=(
        "Provide an independent, safe validation pass that surfaces correctness, "
        "regression, and out-of-scope risks without modifying the repository or "
        "delegating further work."
    ),
    capabilities=(
        "Independent inspection of a scoped diff and its acceptance criteria.",
        "Read-only validation of correctness, regressions, and missing checks.",
        "Severity-ranked findings with per-path evidence.",
        "A concise accept or revise recommendation.",
    ),
    when_to_use=(
        "An orchestrator needs an independent review of a scoped change before it is accepted.",
        "A change must be validated without granting write, network, or deployment access.",
        "Several reviews can run in parallel and be consolidated by the orchestrator.",
    ),
    procedure=(
        "Read the accepted scope, acceptance criteria, and the diff before any adjacent code.",
        "Inspect adjacent code only when needed to establish a regression or correctness risk.",
        "Identify correctness defects, regressions, missing validation, and out-of-scope changes.",
        "Rank findings by severity, most severe first.",
        "Attach file-path evidence to every finding.",
        "Conclude with a single accept or revise recommendation.",
    ),
    response_format=(
        "Findings first, ordered by severity (highest first).",
        "Each finding states severity, a one-line summary, affected path(s), and a concrete failure scenario.",
        "A final line with an explicit accept or revise recommendation.",
    ),
    constraints=RoleConstraints(
        read_only=True,
        allow_network=False,
        allow_commit=False,
        allow_push=False,
        allow_deploy=False,
        allowed_paths=(),
        blocked_paths=(),
    ),
    evidence_requirements=(
        "Every finding must cite at least one repository-relative file path.",
        "Cite line ranges when they materially help locate the issue.",
        "Do not assert a defect without evidence a reader can independently verify.",
    ),
    delegation=DelegationPolicy(
        parallelizable=True,
        recursive_delegation=False,
        consolidation_required=True,
        recommended_concurrency=1,
    ),
    runtime_preferences=RuntimePreferences(
        reasoning_intensity="medium",
        context_isolation_preferred=True,
        sandbox_preferred=True,
    ),
    source_evidence=(
        ".codex/agents/independent_reviewer.toml",
        "AGENTS.md",
    ),
)

ROLES: dict[str, CanonicalRole] = {INDEPENDENT_REVIEWER.id: INDEPENDENT_REVIEWER}


def get_role(role_id: str) -> CanonicalRole:
    """Return a canonical role by id, or raise ``KeyError`` for an unknown role."""
    return ROLES[role_id]


def role_ids() -> list[str]:
    """Deterministic, sorted list of available role ids."""
    return sorted(ROLES)
