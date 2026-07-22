"""Deterministic, read-only resolution of knowledge providers for capability gaps."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .catalog import CAPABILITIES
from .models import CapabilityRecommendation, InfrastructurePlan


PROVIDER_CATALOG_SCHEMA_VERSION = 1
PROVIDER_KINDS = ("skill", "plugin", "manual")
PROVIDER_REVIEW_STATUSES = ("candidate", "approved")
PROVIDER_TARGETS = ("skill", "codex", "claude", "copilot")
BUILTIN_PROVIDERS: tuple["ProviderDefinition", ...] = ()
_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9_-]*$")
_MAX_CATALOG_BYTES = 1_000_000


class ProviderCatalogError(ValueError):
    """Raised when local provider metadata is malformed or ambiguous."""


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    title: str
    capabilities: tuple[str, ...]
    kind: str
    source: str
    revision: str
    compatible_targets: tuple[str, ...]
    license: str
    review_status: str


@dataclass(frozen=True)
class ProviderCandidate:
    provider: ProviderDefinition
    matched_capabilities: tuple[str, ...]


@dataclass(frozen=True)
class ProviderResolution:
    capability_gaps: tuple[CapabilityRecommendation, ...]
    candidates: tuple[ProviderCandidate, ...]
    unresolved_capabilities: tuple[CapabilityRecommendation, ...]


def capabilities_requiring_research(
    resolution: ProviderResolution,
) -> tuple[CapabilityRecommendation, ...]:
    """Return unmatched gaps plus gaps covered only by unapproved candidates."""
    unresolved_ids = {
        capability.capability_id for capability in resolution.unresolved_capabilities
    }
    candidate_only_ids = {
        capability_id
        for candidate in resolution.candidates
        if candidate.provider.review_status == "candidate"
        for capability_id in candidate.matched_capabilities
    }
    research_ids = unresolved_ids | candidate_only_ids
    return tuple(
        capability
        for capability in resolution.capability_gaps
        if capability.capability_id in research_ids
    )


def build_provider_research_brief(
    capabilities: Iterable[CapabilityRecommendation],
) -> dict[str, object]:
    """Build a deterministic brief for optional, agent-assisted provider research.

    The brief contains repository evidence and a review contract, but it never performs
    network access, selects a provider, or grants installation permission.
    """
    research_items: list[dict[str, object]] = []
    for recommendation in capabilities:
        definition = CAPABILITIES[recommendation.capability_id]
        research_items.append(
            {
                "capability_id": recommendation.capability_id,
                "title": definition.title,
                "objective": definition.description,
                "repository_reason": recommendation.reason,
                "evidence": recommendation.evidence,
            }
        )

    return {
        "status": "research_recommended" if research_items else "not_required",
        "actor": (
            "The Main agent may perform this research; a separate research agent is optional, "
            "not required."
        ),
        "network_access": "not_performed_by_cli",
        "capabilities": research_items,
        "result_contract": {
            "status": "provider_research_result",
            "max_candidates_per_capability": 3,
            "no_match_allowed": True,
            "required_candidate_fields": [
                "provider_id",
                "title",
                "primary_source",
                "revision",
                "kind",
                "compatible_targets",
                "license",
                "trust_signals",
                "exact_coverage",
                "coverage_gaps",
                "permissions",
                "external_requirements",
                "platform_coupling",
                "recommendation",
            ],
            "recommendation_values": ["suitable", "partial_only", "reject"],
        },
        "research_rules": [
            "Use public primary sources and version-specific evidence where possible.",
            "Search by capability and public technology names; do not disclose repository source, secrets, or proprietary context.",
            "Classify partial coverage honestly; never map a narrower provider to a broader capability merely because it is the closest result.",
            "Do not download, execute, install, or add a provider to a catalog during research.",
            "If a capability is too broad for honest matching, propose a smaller capability decomposition instead of inventing expertise.",
        ],
        "decision_options": [
            {
                "id": "select_provider",
                "description": "Review and later propose a selected provider.",
            },
            {
                "id": "leave_unresolved",
                "description": "Leave the capability unresolved.",
            },
            {
                "id": "create_local_knowledge",
                "description": "Create repository-local knowledge manually.",
            },
            {
                "id": "decompose_capability",
                "description": "Decompose the capability and research narrower providers.",
            },
        ],
    }


def _required_string(item: dict, field: str, provider_id: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ProviderCatalogError(
            f"provider {provider_id!r}: {field} must be a non-empty string"
        )
    return value.strip()


def _string_tuple(item: dict, field: str, provider_id: str) -> tuple[str, ...]:
    value = item.get(field)
    if not isinstance(value, list) or not value:
        raise ProviderCatalogError(
            f"provider {provider_id!r}: {field} must be a non-empty array"
        )
    if not all(isinstance(entry, str) and entry.strip() for entry in value):
        raise ProviderCatalogError(
            f"provider {provider_id!r}: {field} entries must be non-empty strings"
        )
    normalized = tuple(entry.strip() for entry in value)
    if len(set(normalized)) != len(normalized):
        raise ProviderCatalogError(
            f"provider {provider_id!r}: {field} entries must be unique"
        )
    return normalized


def _parse_provider(item: object) -> ProviderDefinition:
    if not isinstance(item, dict):
        raise ProviderCatalogError("each provider must be an object")
    expected = {
        "id",
        "title",
        "capabilities",
        "kind",
        "source",
        "revision",
        "compatible_targets",
        "license",
        "review_status",
    }
    unknown = sorted(set(item).difference(expected))
    missing = sorted(expected.difference(item))
    if unknown:
        raise ProviderCatalogError(
            "provider contains unknown field(s): " + ", ".join(unknown)
        )
    if missing:
        raise ProviderCatalogError(
            "provider is missing field(s): " + ", ".join(missing)
        )

    provider_id = _required_string(item, "id", "unknown")
    if not _PROVIDER_ID.fullmatch(provider_id):
        raise ProviderCatalogError(
            f"provider {provider_id!r}: id must match {_PROVIDER_ID.pattern}"
        )
    capabilities = _string_tuple(item, "capabilities", provider_id)
    unknown_capabilities = sorted(set(capabilities).difference(CAPABILITIES))
    if unknown_capabilities:
        raise ProviderCatalogError(
            f"provider {provider_id!r}: unknown capabilities: "
            + ", ".join(unknown_capabilities)
        )
    kind = _required_string(item, "kind", provider_id)
    if kind not in PROVIDER_KINDS:
        raise ProviderCatalogError(
            f"provider {provider_id!r}: kind must be one of {', '.join(PROVIDER_KINDS)}"
        )
    compatible_targets = _string_tuple(item, "compatible_targets", provider_id)
    unknown_targets = sorted(set(compatible_targets).difference(PROVIDER_TARGETS))
    if unknown_targets:
        raise ProviderCatalogError(
            f"provider {provider_id!r}: unknown compatible targets: "
            + ", ".join(unknown_targets)
        )
    review_status = _required_string(item, "review_status", provider_id)
    if review_status not in PROVIDER_REVIEW_STATUSES:
        raise ProviderCatalogError(
            f"provider {provider_id!r}: review_status must be one of "
            + ", ".join(PROVIDER_REVIEW_STATUSES)
        )
    return ProviderDefinition(
        id=provider_id,
        title=_required_string(item, "title", provider_id),
        capabilities=capabilities,
        kind=kind,
        source=_required_string(item, "source", provider_id),
        revision=_required_string(item, "revision", provider_id),
        compatible_targets=compatible_targets,
        license=_required_string(item, "license", provider_id),
        review_status=review_status,
    )


def load_provider_catalog(path: str | Path | None = None) -> tuple[ProviderDefinition, ...]:
    """Load a local metadata catalog without accessing provider sources or the network."""
    if path is None:
        return BUILTIN_PROVIDERS
    catalog_path = Path(path).expanduser()
    if not catalog_path.is_file():
        raise ProviderCatalogError(f"provider catalog is not a file: {catalog_path}")
    if catalog_path.stat().st_size > _MAX_CATALOG_BYTES:
        raise ProviderCatalogError(
            f"provider catalog exceeds {_MAX_CATALOG_BYTES} bytes: {catalog_path}"
        )
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProviderCatalogError(f"invalid provider catalog: {error}") from error
    if not isinstance(payload, dict):
        raise ProviderCatalogError("provider catalog root must be an object")
    unknown = sorted(set(payload).difference({"schema_version", "providers"}))
    if unknown:
        raise ProviderCatalogError(
            "provider catalog contains unknown field(s): " + ", ".join(unknown)
        )
    schema_version = payload.get("schema_version")
    if type(schema_version) is not int or schema_version != PROVIDER_CATALOG_SCHEMA_VERSION:
        raise ProviderCatalogError(
            f"provider catalog schema_version must be {PROVIDER_CATALOG_SCHEMA_VERSION}"
        )
    raw_providers = payload.get("providers")
    if not isinstance(raw_providers, list):
        raise ProviderCatalogError("provider catalog providers must be an array")
    providers = tuple(sorted((_parse_provider(item) for item in raw_providers), key=lambda item: item.id))
    ids = [provider.id for provider in providers]
    if len(set(ids)) != len(ids):
        raise ProviderCatalogError("provider ids must be unique")
    return providers


def resolve_providers(
    plan: InfrastructurePlan,
    covered_capabilities: Iterable[str],
    providers: Iterable[ProviderDefinition],
) -> ProviderResolution:
    """Match provider metadata to recommended capabilities not covered by adapters."""
    covered = set(covered_capabilities)
    gaps_by_id: dict[str, CapabilityRecommendation] = {}
    for capability in plan.capabilities:
        if capability.capability_id not in covered:
            gaps_by_id.setdefault(capability.capability_id, capability)
    gap_ids = set(gaps_by_id)
    candidates: list[ProviderCandidate] = []
    resolved: set[str] = set()
    for provider in sorted(providers, key=lambda item: item.id):
        matched = tuple(
            capability
            for capability in provider.capabilities
            if capability in gap_ids
        )
        if matched:
            candidates.append(ProviderCandidate(provider, matched))
            resolved.update(matched)
    gaps = tuple(gaps_by_id.values())
    unresolved = tuple(
        capability
        for capability in gaps
        if capability.capability_id not in resolved
    )
    return ProviderResolution(gaps, tuple(candidates), unresolved)
