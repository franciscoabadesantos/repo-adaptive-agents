"""Domain model for repository profiling and infrastructure proposals."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class Availability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    REQUIRES_AUTHORIZATION = "requires_authorization"


class RecommendationStatus(StrEnum):
    RECOMMENDED = "recommended"
    MISSING = "missing"
    OPTIONAL = "optional"
    UNAVAILABLE = "unavailable"
    REQUIRES_AUTHORIZATION = "requires_authorization"


@dataclass(frozen=True)
class Evidence:
    signal: str
    paths: tuple[str, ...]
    detail: str
    total_count: int = 0
    omitted_count: int = 0


@dataclass
class TestProfile:
    present: bool = False
    frameworks: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class WorkflowProfile:
    """Repository-native commands discovered from package manifests and lockfiles."""

    package_managers: dict[str, str] = field(default_factory=dict)
    scripts: dict[str, dict[str, str]] = field(default_factory=dict)
    development_commands: list[str] = field(default_factory=list)
    build_commands: list[str] = field(default_factory=list)
    validation_commands: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class BrowserQAProfile:
    """Browser-test tooling and server lifecycle facts; no browser is executed."""

    present: bool = False
    frameworks: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    manages_server: bool = False
    server_commands: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class DeploymentProfile:
    tools: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class ArchitectureProfile:
    styles: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class IntegrationProfile:
    name: str
    detected: bool
    authorization: Availability
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class TechnologyFinding:
    """Technology whose repository role needs semantic classification."""

    technology: str
    category: str
    status: str
    inferred_behaviors: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class ComponentProfile:
    """A root or nested runnable/package unit discovered from a local manifest."""

    name: str
    path: str
    manifests: list[str]
    role: str
    project_types: list[str]
    languages: list[str]
    frameworks: list[str]
    runtimes: list[str]
    entrypoints: list[str]
    deployment_targets: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def manifest(self) -> str | None:
        """Backward-compatible access to the first manifest, if any."""
        return self.manifests[0] if self.manifests else None


@dataclass
class RepoProfile:
    path: str
    name: str
    project_types: list[str]
    primary_project_types: list[str]
    secondary_project_types: list[str]
    languages: list[str]
    frameworks: list[str]
    manifests: list[str]
    components: list[ComponentProfile]
    architecture: ArchitectureProfile
    workflow: WorkflowProfile
    tests: TestProfile
    browser_qa: BrowserQAProfile
    deployment: DeploymentProfile
    integrations: list[IntegrationProfile]
    risks: list[str]
    evidence: list[Evidence]
    warnings: list[str] = field(default_factory=list)
    technology_findings: list[TechnologyFinding] = field(default_factory=list)


@dataclass(frozen=True)
class CapabilityDefinition:
    id: str
    title: str
    description: str
    domains: tuple[str, ...]
    availability: Availability = Availability.AVAILABLE
    requires_authorization: bool = False


@dataclass
class CapabilityRecommendation:
    capability_id: str
    status: RecommendationStatus
    availability: Availability
    reason: str
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class AgentPlan:
    name: str
    title: str
    purpose: str
    capabilities: list[str]
    rationale: str


@dataclass
class UserQuestion:
    id: str
    question: str
    reason: str
    options: list[str]


@dataclass
class IntegrationRecommendation:
    name: str
    status: RecommendationStatus
    reason: str


@dataclass
class RepositoryContracts:
    package_managers: dict[str, str]
    development_commands: list[str]
    build_commands: list[str]
    validation_commands: list[str]
    test_commands: list[str]
    browser_qa_commands: list[str]
    browser_qa_manages_server: bool
    browser_qa_server_commands: list[str]
    deployment_tools: list[str]
    deployment_targets: list[str]


@dataclass
class InfrastructurePlan:
    repository_contracts: RepositoryContracts
    capabilities: list[CapabilityRecommendation]
    available_roles: list[AgentPlan]
    integrations: list[IntegrationRecommendation]
    questions: list[UserQuestion]
    assumptions: list[str]

    @property
    def agents(self) -> list[AgentPlan]:
        """Backward-compatible Python accessor; serialized plans use available_roles."""
        return self.available_roles


# Backward-compatible import for callers of the original MVP API.
TeamPlan = InfrastructurePlan


def to_jsonable(value: Any) -> Any:
    """Convert domain objects to stable JSON-compatible data."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value
