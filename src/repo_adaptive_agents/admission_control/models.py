"""Minimal domain model for the admission-control experiment."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, TypeAlias


ResourceKind: TypeAlias = Literal[
    "agent_skill",
    "repository_instruction",
    "mcp_tool",
    "mcp_resource",
    "organizational_policy",
    "environment_contract",
]
Disposition: TypeAlias = Literal["selectable", "mandatory", "forbidden"]


@dataclass(frozen=True)
class ResolutionContext:
    task: str
    organization: str
    team: str
    repository: str
    affected_paths: tuple[str, ...]
    as_of: str
    compatibility: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Scope:
    organization: str | None = None
    team: str | None = None
    repository: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class Lifecycle:
    approval: str
    effective_from: str | None = None
    expires_at: str | None = None
    revoked_at: str | None = None


@dataclass(frozen=True)
class CompatibilityConstraint:
    dimension: str
    allowed_values: tuple[str, ...]


@dataclass(frozen=True)
class Governance:
    disposition: Disposition
    authority: int
    supersedes: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillSemantics:
    harnesses: tuple[str, ...]
    entrypoint: str


@dataclass(frozen=True)
class RepositoryInstructionSemantics:
    instruction_path: str


@dataclass(frozen=True)
class MCPSemantics:
    server: str
    capability: str
    permissions: tuple[str, ...]
    requires_network: bool


@dataclass(frozen=True)
class PolicySemantics:
    policy_class: str


@dataclass(frozen=True)
class EnvironmentContractSemantics:
    contract_class: str


ResourceSemantics: TypeAlias = (
    SkillSemantics
    | RepositoryInstructionSemantics
    | MCPSemantics
    | PolicySemantics
    | EnvironmentContractSemantics
)


@dataclass(frozen=True)
class ResourceRecord:
    id: str
    kind: ResourceKind
    title: str
    summary: str
    body: str
    source: str
    revision: str
    content_sha256: str
    lifecycle: Lifecycle
    scope: Scope
    compatibility: tuple[CompatibilityConstraint, ...]
    governance: Governance
    semantics: ResourceSemantics


@dataclass(frozen=True)
class CandidateSelection:
    resource_id: str
    reason: str
    confidence: float


@dataclass(frozen=True)
class AdmissionDecision:
    resource_id: str
    stage: Literal["prefilter", "post_validation"]
    admitted: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class AdmissionRun:
    schema_version: int
    context: ResolutionContext
    pre_catalog_sha256: str
    post_catalog_sha256: str
    prefilter_decisions: tuple[AdmissionDecision, ...]
    exposed_selectable_resources: tuple[ResourceRecord, ...]
    exposed_mandatory_controls: tuple[ResourceRecord, ...]
    raw_model_selections: tuple[CandidateSelection, ...]
    post_validation_decisions: tuple[AdmissionDecision, ...]
    mandatory_control_ids: tuple[str, ...]
    final_selected_ids: tuple[str, ...]
    final_exposure_ids: tuple[str, ...]
    violations: tuple[str, ...]
    blocked: bool


def to_data(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_data(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_data(item) for item in value]
    return value
