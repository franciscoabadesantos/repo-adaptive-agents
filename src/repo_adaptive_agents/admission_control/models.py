"""Native domain model for deterministic resource admission and lifecycle control."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias


class ResourceKind(str, Enum):
    AGENT_SKILL = "agent_skill"
    SHARED_KNOWLEDGE = "shared_knowledge"
    REPOSITORY_INSTRUCTION = "repository_instruction"
    MCP_TOOL = "mcp_tool"
    MCP_RESOURCE = "mcp_resource"
    ORGANIZATIONAL_POLICY = "organizational_policy"
    ENVIRONMENT_CONTRACT = "environment_contract"


class LifecycleState(str, Enum):
    APPROVED = "approved"
    DRAFT = "draft"
    DENIED = "denied"
    REVOKED = "revoked"


class ExposurePolicy(str, Enum):
    """Whether content may be shown when final-selection admission fails."""

    ALLOW_WHEN_INADMISSIBLE = "allow_when_inadmissible"
    REQUIRE_ADMISSIBLE = "require_admissible"


class PredicateOperator(str, Enum):
    EQUALS = "equals"
    ONE_OF = "one_of"
    CONTAINS_ALL = "contains_all"
    INTERSECTS = "intersects"
    VERSION_AT_LEAST = "version_at_least"


class ControlEffect(str, Enum):
    MANDATORY = "mandatory"
    FORBIDDEN = "forbidden"


class ReasonCode(str, Enum):
    NOT_APPROVED = "not_approved"
    REVOKED = "revoked"
    NOT_EFFECTIVE = "not_effective"
    EXPIRED = "expired"
    SCOPE_ORGANIZATION = "scope_organization"
    SCOPE_TEAM = "scope_team"
    SCOPE_REPOSITORY = "scope_repository"
    SCOPE_PATH = "scope_path"
    COMPATIBILITY_UNKNOWN = "compatibility_unknown"
    COMPATIBILITY_MISMATCH = "compatibility_mismatch"
    DEPENDENCY_UNSATISFIED = "dependency_unsatisfied"
    FORBIDDEN_CONTROL = "forbidden_control"
    SUPERSEDED = "superseded"
    NOT_SELECTABLE = "not_selectable"
    UNKNOWN_RESOURCE = "unknown_resource"
    NOT_EXPOSED = "not_exposed"
    RESOURCE_CHANGED = "resource_changed"
    DUPLICATE_SELECTION = "duplicate_selection"
    PRECEDENCE_LOST = "precedence_lost"
    UNRESOLVED_CONFLICT = "unresolved_conflict"
    MANDATORY_RESOURCE_INADMISSIBLE = "mandatory_resource_inadmissible"


def normalize_repository_path(value: str) -> str:
    """Normalize a repository-relative POSIX path without allowing root escape."""

    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value or "\x00" in value:
        raise ValueError("path must be a non-empty repository-relative POSIX path")
    parts: list[str] = []
    for part in value.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise ValueError("path must not escape the repository root")
            parts.pop()
        else:
            parts.append(part)
    if not parts or parts[0] == ".git":
        raise ValueError("path must identify content outside .git")
    return "/".join(parts)


def require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def normalize_facts(value: Mapping[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    for key, entries in value.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(entries, tuple):
            raise ValueError("facts must map non-empty strings to tuples of strings")
        cleaned = tuple(item.strip() for item in entries if isinstance(item, str) and item.strip())
        if len(cleaned) != len(entries) or len(cleaned) != len(set(cleaned)):
            raise ValueError(f"fact values for {key} must be non-empty unique strings")
        normalized[key.strip()] = cleaned
    return normalized


@dataclass(frozen=True)
class AdmissionContext:
    organization: str
    team: str
    repository: str
    affected_paths: tuple[str, ...]
    effective_at: datetime
    facts: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("organization", "team", "repository"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        object.__setattr__(self, "effective_at", require_aware(self.effective_at, "effective_at"))
        object.__setattr__(self, "affected_paths", tuple(normalize_repository_path(path) for path in self.affected_paths))
        object.__setattr__(self, "facts", MappingProxyType(normalize_facts(self.facts)))

    def model_facing_data(self) -> dict[str, Any]:
        """Return the exact deterministic context that callers may show to a model."""

        return {
            "organization": self.organization,
            "team": self.team,
            "repository": self.repository,
            "affected_paths": list(self.affected_paths),
            "effective_at": self.effective_at.isoformat().replace("+00:00", "Z"),
            "facts": {key: list(values) for key, values in sorted(self.facts.items())},
        }


@dataclass(frozen=True)
class Scope:
    organization: str | None = None
    team: str | None = None
    repository: str | None = None
    path: str | None = None

    def __post_init__(self) -> None:
        for name in ("organization", "team", "repository"):
            value = getattr(self, name)
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"scope {name} must be a non-empty string when present")
                object.__setattr__(self, name, value.strip())
        if self.path is not None:
            object.__setattr__(self, "path", normalize_repository_path(self.path))


@dataclass(frozen=True)
class Lifecycle:
    state: LifecycleState
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, LifecycleState):
            raise ValueError("lifecycle state must be a LifecycleState")
        for name in ("effective_at", "expires_at", "revoked_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_aware(value, name))


@dataclass(frozen=True)
class FactPredicate:
    key: str
    operator: PredicateOperator
    values: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.key, str)
            or not self.key.strip()
            or not isinstance(self.operator, PredicateOperator)
            or not isinstance(self.values, tuple)
            or not self.values
            or any(not isinstance(value, str) or not value.strip() for value in self.values)
        ):
            raise ValueError("predicate key and values must be non-empty")
        if len(self.values) != len(set(self.values)):
            raise ValueError("predicate values must be unique")
        if self.operator in {PredicateOperator.EQUALS, PredicateOperator.VERSION_AT_LEAST} and len(self.values) != 1:
            raise ValueError(f"{self.operator.value} requires exactly one value")


@dataclass(frozen=True)
class Dependency:
    name: str
    predicate: FactPredicate

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("dependency name must be non-empty")


@dataclass(frozen=True)
class ControlRef:
    resource_id: str
    rule_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.resource_id, str) or not self.resource_id.strip() or not isinstance(self.rule_id, str) or not self.rule_id.strip():
            raise ValueError("control references require resource_id and rule_id")


@dataclass(frozen=True)
class ControlRule:
    id: str
    effect: ControlEffect
    when: tuple[FactPredicate, ...]
    authority: int
    conflicts_with: tuple[ControlRef, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, str)
            or not self.id.strip()
            or not isinstance(self.effect, ControlEffect)
            or not isinstance(self.when, tuple)
            or not isinstance(self.authority, int)
            or isinstance(self.authority, bool)
            or self.authority < 0
            or not isinstance(self.conflicts_with, tuple)
        ):
            raise ValueError("control rule id must be non-empty and authority non-negative")


@dataclass(frozen=True)
class SkillPayload:
    harnesses: tuple[str, ...]
    entrypoint: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.harnesses, tuple)
            or not self.harnesses
            or any(not isinstance(value, str) or not value.strip() for value in self.harnesses)
            or len(self.harnesses) != len(set(self.harnesses))
        ):
            raise ValueError("skill harnesses must be non-empty unique strings")
        object.__setattr__(self, "entrypoint", normalize_repository_path(self.entrypoint))


@dataclass(frozen=True)
class RepositoryInstructionPayload:
    instruction_path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "instruction_path", normalize_repository_path(self.instruction_path))


@dataclass(frozen=True)
class SharedKnowledgePayload:
    content_path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_path", normalize_repository_path(self.content_path))


@dataclass(frozen=True)
class MCPPayload:
    server: str
    capability: str
    permissions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.server, str) or not self.server.strip() or not isinstance(self.capability, str) or not self.capability.strip():
            raise ValueError("MCP server and capability must be non-empty")
        if not isinstance(self.permissions, tuple) or any(not isinstance(value, str) or not value.strip() for value in self.permissions):
            raise ValueError("MCP permissions must be strings")
        if len(self.permissions) != len(set(self.permissions)):
            raise ValueError("MCP permissions must be unique")


@dataclass(frozen=True)
class PolicyPayload:
    policy_class: str

    def __post_init__(self) -> None:
        if not isinstance(self.policy_class, str) or not self.policy_class.strip():
            raise ValueError("policy_class must be non-empty")


@dataclass(frozen=True)
class EnvironmentContractPayload:
    contract_class: str

    def __post_init__(self) -> None:
        if not isinstance(self.contract_class, str) or not self.contract_class.strip():
            raise ValueError("contract_class must be non-empty")


ResourcePayload: TypeAlias = SkillPayload | SharedKnowledgePayload | RepositoryInstructionPayload | MCPPayload | PolicyPayload | EnvironmentContractPayload


@dataclass(frozen=True)
class ResourceIdentity:
    resource_id: str
    revision: str
    payload_sha256: str


@dataclass(frozen=True)
class ResourceContent:
    id: str
    revision: str
    payload_sha256: str
    kind: ResourceKind
    title: str
    summary: str
    body: str
    payload: ResourcePayload

    @property
    def identity(self) -> ResourceIdentity:
        return ResourceIdentity(self.id, self.revision, self.payload_sha256)


@dataclass(frozen=True)
class AdmissionEnvelope:
    lifecycle: Lifecycle
    scope: Scope
    compatibility: tuple[FactPredicate, ...]
    dependencies: tuple[Dependency, ...]
    exposure_policy: ExposurePolicy
    selectable: bool
    supersedes: tuple[str, ...] = ()
    control_rules: tuple[ControlRule, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.exposure_policy, ExposurePolicy):
            raise ValueError("exposure_policy must be an ExposurePolicy")
        if not isinstance(self.selectable, bool):
            raise ValueError("selectable must be a boolean")
        for name in ("compatibility", "dependencies", "supersedes", "control_rules"):
            if not isinstance(getattr(self, name), tuple):
                raise ValueError(f"{name} must be a tuple")
        if any(not isinstance(value, str) or not value.strip() for value in self.supersedes):
            raise ValueError("supersedes values must be non-empty strings")


@dataclass(frozen=True)
class ResourceRecord:
    content: ResourceContent
    admission: AdmissionEnvelope


@dataclass(frozen=True)
class DeterministicReason:
    code: ReasonCode
    related_resource_id: str | None = None
    related_rule_id: str | None = None
    fact_key: str | None = None
    expected: tuple[str, ...] = ()
    actual: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleDecision:
    resource_id: str
    rule_id: str
    effect: ControlEffect
    authority: int
    active: bool
    suppressed_by: ControlRef | None = None
    unresolved_conflict_with: tuple[ControlRef, ...] = ()


@dataclass(frozen=True)
class ResourceDecision:
    identity: ResourceIdentity
    final_eligible: bool
    exposure_allowed: bool
    selectable: bool
    reasons: tuple[DeterministicReason, ...]


class ExposureError(ValueError):
    pass


@dataclass(frozen=True)
class ExposureReceipt:
    context: AdmissionContext
    catalog_revision: str
    catalog_sha256: str
    resources: tuple[ResourceIdentity, ...]

    @property
    def resource_ids(self) -> tuple[str, ...]:
        return tuple(resource.resource_id for resource in self.resources)


@dataclass(frozen=True)
class AdmissionSnapshot:
    context: AdmissionContext
    catalog_revision: str
    catalog_sha256: str
    decisions: tuple[ResourceDecision, ...]
    rule_decisions: tuple[RuleDecision, ...]
    exposable_resources: tuple[ResourceContent, ...]
    mandatory_resource_ids: tuple[str, ...]
    reasons: tuple[DeterministicReason, ...]
    blocked: bool

    def record_exposure(self, resources: tuple[ResourceContent, ...]) -> ExposureReceipt:
        """Bind the exact content objects actually presented to the semantic layer."""

        resource_ids = tuple(resource.id for resource in resources)
        if len(resource_ids) != len(set(resource_ids)):
            raise ExposureError("actual model exposure resources must be unique")
        available = {resource.id: resource for resource in self.exposable_resources}
        unknown = tuple(resource_id for resource_id in resource_ids if resource_id not in available)
        if unknown:
            raise ExposureError(f"resources were outside the exposable universe: {unknown}")
        changed = tuple(
            resource.id
            for resource in resources
            if available[resource.id] != resource
        )
        if changed:
            raise ExposureError(f"resources differed from the admitted model-visible content: {changed}")
        return ExposureReceipt(
            self.context,
            self.catalog_revision,
            self.catalog_sha256,
            tuple(resource.identity for resource in resources),
        )


@dataclass(frozen=True)
class CandidateSelection:
    resource_id: str
    rationale: str = ""
    confidence: float | None = None


@dataclass(frozen=True)
class SelectionDecision:
    selection_index: int
    resource_id: str
    admitted: bool
    reasons: tuple[DeterministicReason, ...]


@dataclass(frozen=True)
class ValidationResult:
    exposure: ExposureReceipt
    context: AdmissionContext
    current_catalog_revision: str
    current_catalog_sha256: str
    raw_selections: tuple[CandidateSelection, ...]
    selection_decisions: tuple[SelectionDecision, ...]
    rule_decisions: tuple[RuleDecision, ...]
    added_mandatory_ids: tuple[str, ...]
    final_resources: tuple[ResourceIdentity, ...]
    reasons: tuple[DeterministicReason, ...]
    blocked: bool

    @property
    def final_resource_ids(self) -> tuple[str, ...]:
        return tuple(resource.resource_id for resource in self.final_resources)


def to_data(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: to_data(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): to_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_data(item) for item in value]
    return value
