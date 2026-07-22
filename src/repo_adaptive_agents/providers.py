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
PROVIDER_RESEARCH_SCHEMA_VERSION = 1
PROVIDER_RESOLUTION_SCHEMA_VERSION = 1
PROVIDER_RESEARCH_STATUSES = ("completed", "unavailable")
PROVIDER_CANDIDATE_RECOMMENDATIONS = ("suitable", "partial_only", "reject")
PROVIDER_SEARCH_KINDS = (
    "marketplace",
    "provider_repository",
    "code_search",
    "web_search",
)
PROVIDER_GAP_OUTCOMES = (
    "leave_unresolved",
    "create_local_knowledge",
    "decompose_capability",
)
BUILTIN_PROVIDERS: tuple["ProviderDefinition", ...] = ()
_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9_-]*$")
_MAX_CATALOG_BYTES = 1_000_000


class ProviderCatalogError(ValueError):
    """Raised when local provider metadata is malformed or ambiguous."""


class ProviderResolutionError(ValueError):
    """Raised when provider research or a subsequent user decision is incomplete."""


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
class ProviderGapProposal:
    capability_id: str
    outcome: str
    provider_id: str | None = None


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
            "schema_version": PROVIDER_RESEARCH_SCHEMA_VERSION,
            "kind": "provider_research",
            "max_candidates_per_capability": 3,
            "no_match_allowed": True,
            "required_capability_fields": [
                "capability_id",
                "research_status",
                "searches",
                "candidates",
                "evidence",
                "limitation",
                "recommended_outcome",
                "recommended_provider_id",
                "rationale",
            ],
            "required_search_fields": [
                "source",
                "source_kind",
                "query",
                "result",
            ],
            "search_kind_values": list(PROVIDER_SEARCH_KINDS),
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
        "decision_contract": {
            "schema_version": PROVIDER_RESOLUTION_SCHEMA_VERSION,
            "kind": "provider_resolution",
            "required_decision_fields": [
                "capability_id",
                "outcome",
                "provider_id",
                "rationale",
            ],
        },
        "research_rules": [
            "Use public primary sources and version-specific evidence where possible.",
            "Search provider marketplaces, skill/plugin repositories, code indexes, or the public web for installable knowledge providers; product documentation alone is coverage evidence, not provider discovery.",
            "Record each provider search separately from candidate coverage evidence.",
            "Classify partial coverage honestly; never map a narrower provider to a broader capability merely because it is the closest result.",
            "Do not download, execute, install, or add a provider to a catalog during research.",
            "If a capability is too broad for honest matching, propose a smaller capability decomposition instead of inventing expertise.",
            "Research produces recommendations only. Present the provider_research artifact and stop for the user's decisions before creating provider_resolution.",
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


def _resolution_string(value: object, field: str, capability_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderResolutionError(
            f"provider resolution {capability_id!r}: {field} must be a non-empty string"
        )
    return value.strip()


def _resolution_strings(
    value: object,
    field: str,
    capability_id: str,
    *,
    allow_empty: bool = True,
) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "non-empty " if not allow_empty else ""
        raise ProviderResolutionError(
            f"provider resolution {capability_id!r}: {field} must be a {qualifier}array"
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ProviderResolutionError(
            f"provider resolution {capability_id!r}: {field} entries must be non-empty strings"
        )
    normalized = [item.strip() for item in value]
    if len(set(normalized)) != len(normalized):
        raise ProviderResolutionError(
            f"provider resolution {capability_id!r}: {field} entries must be unique"
        )
    return normalized


def _parse_research_candidate(item: object, capability_id: str) -> dict[str, object]:
    if not isinstance(item, dict):
        raise ProviderResolutionError(
            f"provider resolution {capability_id!r}: each candidate must be an object"
        )
    expected = {
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
    }
    if set(item) != expected:
        raise ProviderResolutionError(
            f"provider resolution {capability_id!r}: candidate fields must be exactly "
            + ", ".join(sorted(expected))
        )
    provider_id = _resolution_string(item["provider_id"], "provider_id", capability_id)
    if not _PROVIDER_ID.fullmatch(provider_id):
        raise ProviderResolutionError(
            f"provider resolution {capability_id!r}: invalid provider_id {provider_id!r}"
        )
    kind = _resolution_string(item["kind"], "kind", capability_id)
    if kind not in PROVIDER_KINDS:
        raise ProviderResolutionError(
            f"provider resolution {capability_id!r}: unsupported candidate kind {kind!r}"
        )
    targets = _resolution_strings(
        item["compatible_targets"],
        "compatible_targets",
        capability_id,
        allow_empty=False,
    )
    unknown_targets = sorted(set(targets).difference(PROVIDER_TARGETS))
    if unknown_targets:
        raise ProviderResolutionError(
            f"provider resolution {capability_id!r}: unknown candidate targets: "
            + ", ".join(unknown_targets)
        )
    recommendation = _resolution_string(
        item["recommendation"], "recommendation", capability_id
    )
    if recommendation not in PROVIDER_CANDIDATE_RECOMMENDATIONS:
        raise ProviderResolutionError(
            f"provider resolution {capability_id!r}: invalid candidate recommendation"
        )
    return {
        "provider_id": provider_id,
        "title": _resolution_string(item["title"], "title", capability_id),
        "primary_source": _resolution_string(
            item["primary_source"], "primary_source", capability_id
        ),
        "revision": _resolution_string(item["revision"], "revision", capability_id),
        "kind": kind,
        "compatible_targets": targets,
        "license": _resolution_string(item["license"], "license", capability_id),
        "trust_signals": _resolution_strings(
            item["trust_signals"], "trust_signals", capability_id, allow_empty=False
        ),
        "exact_coverage": _resolution_strings(
            item["exact_coverage"], "exact_coverage", capability_id
        ),
        "coverage_gaps": _resolution_strings(
            item["coverage_gaps"], "coverage_gaps", capability_id
        ),
        "permissions": _resolution_strings(
            item["permissions"], "permissions", capability_id
        ),
        "external_requirements": _resolution_strings(
            item["external_requirements"], "external_requirements", capability_id
        ),
        "platform_coupling": _resolution_string(
            item["platform_coupling"], "platform_coupling", capability_id
        ),
        "recommendation": recommendation,
    }


def _parse_provider_search(item: object, capability_id: str) -> dict[str, str]:
    if not isinstance(item, dict) or set(item) != {
        "source",
        "source_kind",
        "query",
        "result",
    }:
        raise ProviderResolutionError(
            f"provider research {capability_id!r}: search fields must be exactly "
            "query, result, source, source_kind"
        )
    source_kind = _resolution_string(item["source_kind"], "source_kind", capability_id)
    if source_kind not in PROVIDER_SEARCH_KINDS:
        raise ProviderResolutionError(
            f"provider research {capability_id!r}: invalid source_kind {source_kind!r}"
        )
    return {
        "source": _resolution_string(item["source"], "source", capability_id),
        "source_kind": source_kind,
        "query": _resolution_string(item["query"], "query", capability_id),
        "result": _resolution_string(item["result"], "result", capability_id),
    }


def parse_provider_research(
    payload: object,
    capability_ids: Iterable[str],
) -> dict[str, object]:
    """Validate evidence-backed research recommendations for every capability gap."""
    ordered_capabilities = tuple(dict.fromkeys(capability_ids))
    expected = set(ordered_capabilities)
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "kind",
        "capabilities",
    }:
        raise ProviderResolutionError(
            "provider research root fields must be exactly capabilities, kind, schema_version"
        )
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != PROVIDER_RESEARCH_SCHEMA_VERSION
    ):
        raise ProviderResolutionError(
            f"provider research schema_version must be {PROVIDER_RESEARCH_SCHEMA_VERSION}"
        )
    if payload["kind"] != "provider_research":
        raise ProviderResolutionError("provider research kind must be 'provider_research'")
    if not isinstance(payload["capabilities"], list):
        raise ProviderResolutionError("provider research capabilities must be an array")

    normalized_by_id: dict[str, dict[str, object]] = {}
    expected_fields = {
        "capability_id",
        "research_status",
        "searches",
        "candidates",
        "evidence",
        "limitation",
        "recommended_outcome",
        "recommended_provider_id",
        "rationale",
    }
    for raw in payload["capabilities"]:
        if not isinstance(raw, dict) or set(raw) != expected_fields:
            raise ProviderResolutionError(
                "provider research capability fields must be exactly "
                + ", ".join(sorted(expected_fields))
            )
        capability_id = _resolution_string(
            raw["capability_id"], "capability_id", "unknown"
        )
        if capability_id not in expected:
            raise ProviderResolutionError(
                f"provider research references non-gap capability: {capability_id}"
            )
        if capability_id in normalized_by_id:
            raise ProviderResolutionError(
                f"duplicate provider research for capability: {capability_id}"
            )
        research_status = _resolution_string(
            raw["research_status"], "research_status", capability_id
        )
        if research_status not in PROVIDER_RESEARCH_STATUSES:
            raise ProviderResolutionError(
                f"provider research {capability_id!r}: invalid research_status"
            )
        searches_raw = raw["searches"]
        if not isinstance(searches_raw, list):
            raise ProviderResolutionError(
                f"provider research {capability_id!r}: searches must be an array"
            )
        searches = [_parse_provider_search(item, capability_id) for item in searches_raw]
        candidates_raw = raw["candidates"]
        if not isinstance(candidates_raw, list) or len(candidates_raw) > 3:
            raise ProviderResolutionError(
                f"provider research {capability_id!r}: candidates must be an array of at most 3"
            )
        candidates = [
            _parse_research_candidate(candidate, capability_id)
            for candidate in candidates_raw
        ]
        candidate_ids = [candidate["provider_id"] for candidate in candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ProviderResolutionError(
                f"provider research {capability_id!r}: candidate ids must be unique"
            )
        evidence = _resolution_strings(
            raw["evidence"],
            "evidence",
            capability_id,
            allow_empty=False,
        )
        limitation = raw["limitation"]
        if research_status == "unavailable":
            if candidates or searches:
                raise ProviderResolutionError(
                    f"provider research {capability_id!r}: unavailable research cannot contain searches or candidates"
                )
            limitation = _resolution_string(limitation, "limitation", capability_id)
        else:
            if not searches:
                raise ProviderResolutionError(
                    f"provider research {capability_id!r}: completed research requires at least one provider search"
                )
            if limitation is not None:
                raise ProviderResolutionError(
                    f"provider research {capability_id!r}: completed research must use null limitation"
                )
        outcome = _resolution_string(raw["recommended_outcome"], "recommended_outcome", capability_id)
        if outcome not in (*PROVIDER_GAP_OUTCOMES, "select_provider"):
            raise ProviderResolutionError(
                f"provider research {capability_id!r}: invalid recommended_outcome"
            )
        provider_id = raw["recommended_provider_id"]
        if outcome == "select_provider":
            provider_id = _resolution_string(
                provider_id, "recommended_provider_id", capability_id
            )
            candidate = next(
                (item for item in candidates if item["provider_id"] == provider_id),
                None,
            )
            if candidate is None or candidate["recommendation"] != "suitable":
                raise ProviderResolutionError(
                    f"provider research {capability_id!r}: recommended provider must be a suitable candidate"
                )
        elif provider_id is not None:
            raise ProviderResolutionError(
                f"provider research {capability_id!r}: recommended_provider_id requires select_provider"
            )
        normalized_by_id[capability_id] = {
            "capability_id": capability_id,
            "research_status": research_status,
            "searches": searches,
            "candidates": candidates,
            "evidence": evidence,
            "limitation": limitation,
            "recommended_outcome": outcome,
            "recommended_provider_id": provider_id,
            "rationale": _resolution_string(raw["rationale"], "rationale", capability_id),
        }

    missing = [item for item in ordered_capabilities if item not in normalized_by_id]
    if missing:
        raise ProviderResolutionError(
            "missing provider research for capability gaps: " + ", ".join(missing)
        )
    return {
        "schema_version": PROVIDER_RESEARCH_SCHEMA_VERSION,
        "kind": "provider_research",
        "capabilities": [normalized_by_id[item] for item in ordered_capabilities],
    }


def parse_provider_resolution(
    payload: object,
    capability_ids: Iterable[str],
    research: dict[str, object],
    providers: Iterable[ProviderDefinition] = (),
    *,
    require_catalog_for_selection: bool = True,
) -> tuple[dict[str, object], tuple[ProviderGapProposal, ...]]:
    """Validate decisions made after the user reviewed provider research."""
    ordered_capabilities = tuple(dict.fromkeys(capability_ids))
    expected = set(ordered_capabilities)
    canonical_research = parse_provider_research(research, ordered_capabilities)
    research_by_id = {
        item["capability_id"]: item for item in canonical_research["capabilities"]
    }
    provider_by_id = {provider.id: provider for provider in providers}
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "kind",
        "decisions",
    }:
        raise ProviderResolutionError(
            "provider resolution root fields must be exactly decisions, kind, schema_version"
        )
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != PROVIDER_RESOLUTION_SCHEMA_VERSION
    ):
        raise ProviderResolutionError(
            f"provider resolution schema_version must be {PROVIDER_RESOLUTION_SCHEMA_VERSION}"
        )
    if payload["kind"] != "provider_resolution":
        raise ProviderResolutionError("provider resolution kind must be 'provider_resolution'")
    if not isinstance(payload["decisions"], list):
        raise ProviderResolutionError("provider resolution decisions must be an array")

    normalized_by_id: dict[str, dict[str, object]] = {}
    proposals: dict[str, ProviderGapProposal] = {}
    expected_fields = {"capability_id", "outcome", "provider_id", "rationale"}
    for raw in payload["decisions"]:
        if not isinstance(raw, dict) or set(raw) != expected_fields:
            raise ProviderResolutionError(
                "provider resolution decision fields must be exactly "
                + ", ".join(sorted(expected_fields))
            )
        capability_id = _resolution_string(raw["capability_id"], "capability_id", "unknown")
        if capability_id not in expected:
            raise ProviderResolutionError(
                f"provider resolution references non-gap capability: {capability_id}"
            )
        if capability_id in normalized_by_id:
            raise ProviderResolutionError(
                f"duplicate provider resolution for capability: {capability_id}"
            )
        outcome = _resolution_string(raw["outcome"], "outcome", capability_id)
        if outcome not in (*PROVIDER_GAP_OUTCOMES, "select_provider"):
            raise ProviderResolutionError(
                f"provider resolution {capability_id!r}: invalid outcome"
            )
        provider_id = raw["provider_id"]
        if outcome == "select_provider":
            provider_id = _resolution_string(provider_id, "provider_id", capability_id)
            candidate = next(
                (
                    item
                    for item in research_by_id[capability_id]["candidates"]
                    if item["provider_id"] == provider_id
                ),
                None,
            )
            if candidate is None or candidate["recommendation"] != "suitable":
                raise ProviderResolutionError(
                    f"provider resolution {capability_id!r}: selected provider must be a suitable research candidate"
                )
            provider = provider_by_id.get(provider_id)
            if provider is None and require_catalog_for_selection:
                raise ProviderResolutionError(
                    f"selected provider is not present in the supplied catalog: {provider_id}"
                )
            if provider is not None and capability_id not in provider.capabilities:
                raise ProviderResolutionError(
                    f"provider {provider_id!r} does not claim capability {capability_id!r}"
                )
            if provider is not None and (
                candidate["title"] != provider.title
                or candidate["primary_source"] != provider.source
                or candidate["revision"] != provider.revision
                or candidate["kind"] != provider.kind
                or set(candidate["compatible_targets"]) != set(provider.compatible_targets)
                or candidate["license"] != provider.license
            ):
                raise ProviderResolutionError(
                    f"selected provider metadata does not match the supplied catalog: {provider_id}"
                )
        elif provider_id is not None:
            raise ProviderResolutionError(
                f"provider resolution {capability_id!r}: provider_id requires select_provider"
            )
        normalized_by_id[capability_id] = {
            "capability_id": capability_id,
            "outcome": outcome,
            "provider_id": provider_id,
            "rationale": _resolution_string(raw["rationale"], "rationale", capability_id),
        }
        proposals[capability_id] = ProviderGapProposal(capability_id, outcome, provider_id)

    missing = [item for item in ordered_capabilities if item not in normalized_by_id]
    if missing:
        raise ProviderResolutionError(
            "missing user decisions for provider gaps: " + ", ".join(missing)
        )
    normalized = {
        "schema_version": PROVIDER_RESOLUTION_SCHEMA_VERSION,
        "kind": "provider_resolution",
        "decisions": [normalized_by_id[item] for item in ordered_capabilities],
    }
    return normalized, tuple(proposals[item] for item in ordered_capabilities)


def load_provider_research(
    path: str | Path,
    capability_ids: Iterable[str],
) -> dict[str, object]:
    """Load and validate a local provider-research proposal."""
    research_path = Path(path).expanduser()
    if not research_path.is_file():
        raise ProviderResolutionError(f"provider research is not a file: {research_path}")
    if research_path.stat().st_size > _MAX_CATALOG_BYTES:
        raise ProviderResolutionError(
            f"provider research exceeds {_MAX_CATALOG_BYTES} bytes: {research_path}"
        )
    try:
        payload = json.loads(research_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProviderResolutionError(f"invalid provider research: {error}") from error
    return parse_provider_research(payload, capability_ids)


def load_provider_resolution(
    path: str | Path,
    capability_ids: Iterable[str],
    research: dict[str, object],
    providers: Iterable[ProviderDefinition] = (),
) -> tuple[dict[str, object], tuple[ProviderGapProposal, ...]]:
    """Load decisions made after a provider-research proposal was reviewed."""
    resolution_path = Path(path).expanduser()
    if not resolution_path.is_file():
        raise ProviderResolutionError(
            f"provider resolution is not a file: {resolution_path}"
        )
    if resolution_path.stat().st_size > _MAX_CATALOG_BYTES:
        raise ProviderResolutionError(
            f"provider resolution exceeds {_MAX_CATALOG_BYTES} bytes: {resolution_path}"
        )
    try:
        payload = json.loads(resolution_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProviderResolutionError(f"invalid provider resolution: {error}") from error
    return parse_provider_resolution(payload, capability_ids, research, providers)


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
