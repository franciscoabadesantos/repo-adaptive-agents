"""Deterministic prefiltering based only on represented lifecycle metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath

from .catalog import ResourceCatalog
from .models import AdmissionDecision, MCPSemantics, ResolutionContext, ResourceRecord, SkillSemantics


@dataclass(frozen=True)
class AdmissionEvaluation:
    decisions: tuple[AdmissionDecision, ...]
    selectable: tuple[ResourceRecord, ...]
    mandatory: tuple[ResourceRecord, ...]
    violations: tuple[str, ...]
    blocked: bool


def _path_applies(prefix: str, paths: tuple[str, ...]) -> bool:
    normalized = prefix.rstrip("/")
    return any(path == normalized or path.startswith(normalized + "/") for path in paths)


def _validate_context(context: ResolutionContext) -> None:
    try:
        date.fromisoformat(context.as_of)
    except (TypeError, ValueError) as error:
        raise ValueError("context as_of must use YYYY-MM-DD") from error
    for name in ("task", "organization", "team", "repository"):
        value = getattr(context, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"context {name} must be a non-empty string")
    for path in context.affected_paths:
        parts = PurePosixPath(path).parts
        if not path or path.startswith("/") or "\\" in path or "\x00" in path or ".." in parts or parts[0] == ".git":
            raise ValueError("context affected_paths must contain safe repository-relative POSIX paths")
    for dimension, value in context.compatibility.items():
        if not isinstance(dimension, str) or not dimension.strip() or not isinstance(value, str) or not value.strip():
            raise ValueError("context compatibility must contain non-empty string keys and values")


def _base_reasons(resource: ResourceRecord, context: ResolutionContext) -> list[str]:
    reasons: list[str] = []
    current = date.fromisoformat(context.as_of)
    lifecycle = resource.lifecycle
    if lifecycle.approval != "approved":
        reasons.append(f"approval:{lifecycle.approval}")
    if lifecycle.revoked_at and date.fromisoformat(lifecycle.revoked_at) <= current:
        reasons.append(f"revoked_at:{lifecycle.revoked_at}")
    if lifecycle.effective_from and current < date.fromisoformat(lifecycle.effective_from):
        reasons.append(f"not_effective_until:{lifecycle.effective_from}")
    if lifecycle.expires_at and current > date.fromisoformat(lifecycle.expires_at):
        reasons.append(f"expired_at:{lifecycle.expires_at}")
    scope = resource.scope
    if scope.organization and scope.organization != context.organization:
        reasons.append("scope:organization")
    if scope.team and scope.team != context.team:
        reasons.append("scope:team")
    if scope.repository and scope.repository != context.repository:
        reasons.append("scope:repository")
    if scope.path and not _path_applies(scope.path, context.affected_paths):
        reasons.append("scope:path")
    for constraint in resource.compatibility:
        actual = context.compatibility.get(constraint.dimension)
        if actual is None:
            reasons.append(f"compatibility_unknown:{constraint.dimension}")
        elif actual not in constraint.allowed_values:
            reasons.append(f"compatibility_mismatch:{constraint.dimension}:{actual}")
    if isinstance(resource.semantics, SkillSemantics):
        harness = context.compatibility.get("harness")
        if harness is None:
            reasons.append("compatibility_unknown:harness")
        elif harness not in resource.semantics.harnesses:
            reasons.append(f"compatibility_mismatch:harness:{harness}")
    if isinstance(resource.semantics, MCPSemantics) and resource.semantics.requires_network:
        network = context.compatibility.get("network")
        if network is None:
            reasons.append("compatibility_unknown:network")
        elif network != "allowed":
            reasons.append(f"compatibility_mismatch:network:{network}")
    if resource.governance.disposition == "forbidden":
        reasons.append("governance:forbidden")
    return reasons


def evaluate_admission(catalog: ResourceCatalog, context: ResolutionContext, *, stage: str = "prefilter") -> AdmissionEvaluation:
    if stage not in {"prefilter", "post_validation"}:
        raise ValueError(f"unsupported admission stage: {stage}")
    _validate_context(context)
    catalog = catalog.validated()
    base = {resource.id: _base_reasons(resource, context) for resource in catalog.resources}
    records = catalog.by_id()

    # Supersession is active only when the superseding resource itself passes the hard gates.
    for resource in catalog.resources:
        if base[resource.id]:
            continue
        for superseded_id in resource.governance.supersedes:
            if not base[superseded_id]:
                base[superseded_id].append(f"superseded_by:{resource.id}")

    conflict_pairs: set[tuple[str, str]] = set()
    for resource in catalog.resources:
        for other_id in resource.governance.conflicts_with:
            conflict_pairs.add(tuple(sorted((resource.id, other_id))))
    violations: list[str] = []
    for left_id, right_id in sorted(conflict_pairs):
        if base[left_id] or base[right_id]:
            continue
        left = records[left_id]
        right = records[right_id]
        if left.governance.authority > right.governance.authority:
            base[right_id].append(f"precedence_lost_to:{left_id}")
        elif right.governance.authority > left.governance.authority:
            base[left_id].append(f"precedence_lost_to:{right_id}")
        else:
            base[left_id].append(f"unresolved_equal_authority_conflict:{right_id}")
            base[right_id].append(f"unresolved_equal_authority_conflict:{left_id}")
            violations.append(f"unresolved_conflict:{left_id}:{right_id}")

    decisions = tuple(
        AdmissionDecision(resource.id, stage, not base[resource.id], tuple(base[resource.id] or ["admitted"]))  # type: ignore[arg-type]
        for resource in catalog.resources
    )
    admitted_ids = {decision.resource_id for decision in decisions if decision.admitted}
    selectable = tuple(resource for resource in catalog.resources if resource.id in admitted_ids and resource.governance.disposition == "selectable")
    mandatory = tuple(resource for resource in catalog.resources if resource.id in admitted_ids and resource.governance.disposition == "mandatory")
    return AdmissionEvaluation(decisions, selectable, mandatory, tuple(violations), bool(violations))
