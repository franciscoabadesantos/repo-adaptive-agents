"""Small, explainable recommendation rules."""

from __future__ import annotations

from .catalog import CAPABILITIES
from .models import (
    Availability,
    AgentPlan,
    CapabilityRecommendation,
    Evidence,
    IntegrationRecommendation,
    RecommendationStatus,
    RepoProfile,
    TeamPlan,
    UserQuestion,
)


def _relevant_evidence(profile: RepoProfile, signals: set[str]) -> list[Evidence]:
    groups = profile.evidence + profile.architecture.evidence + profile.tests.evidence + profile.deployment.evidence
    groups += [item for component in profile.components for item in component.evidence]
    return _unique_evidence(item for item in groups if item.signal in signals)


def _component_evidence(profile: RepoProfile, project_types: set[str], signals: set[str] | None = None) -> list[Evidence]:
    return _unique_evidence(
        item
        for item in (
            item
            for component in profile.components
            if project_types.intersection(component.project_types)
            for item in component.evidence
        )
        if signals is None or item.signal in signals
    )


def _unique_evidence(items) -> list[Evidence]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    unique: list[Evidence] = []
    for item in items:
        key = (item.signal, item.paths)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _add(
    items: list[CapabilityRecommendation],
    capability_id: str,
    reason: str,
    evidence: list[Evidence],
    status: RecommendationStatus = RecommendationStatus.RECOMMENDED,
) -> None:
    definition = CAPABILITIES[capability_id]
    items.append(CapabilityRecommendation(capability_id, status, definition.availability, reason, _unique_evidence(evidence)[:4]))


def recommend_team(profile: RepoProfile, request: str = "") -> TeamPlan:
    request_lower = request.lower()
    capabilities: list[CapabilityRecommendation] = []
    _add(capabilities, "repo_analysis", "Useful for every repository to preserve an evidence-backed map.", profile.evidence[:3] + profile.architecture.evidence[:2])

    test_status = RecommendationStatus.RECOMMENDED if profile.tests.present else RecommendationStatus.MISSING
    test_reason = "Existing tests or a recognized test command can be exercised by a focused agent." if profile.tests.present else "No real test suite was detected; a focused agent is needed to establish a safe baseline."
    _add(capabilities, "test_strategy", test_reason, profile.tests.evidence, test_status)
    if profile.manifests:
        _add(capabilities, "dependency_audit", "Recognized dependency manifests are present.", _relevant_evidence(profile, {"manifest", "package_dependency", "python_dependency", "ml_dependency"}))
    if "pipeline" in profile.project_types:
        _add(capabilities, "pipeline_review", "Operational pipeline entrypoints and stages were detected.", _relevant_evidence(profile, {"operational_entrypoint", "oracle_operation", "cloudflare_api"}))
    if "ci_cd" in profile.project_types:
        _add(capabilities, "ci_cd_review", "CI/CD workflows, triggers, or runners were detected.", _relevant_evidence(profile, {"ci_cd_workflow", "self_hosted_runner"}))
    if "operations" in profile.project_types:
        _add(capabilities, "operations_review", "Operational side effects or external runtime integrations were detected.", _relevant_evidence(profile, {"operations_signal", "cloudflare_api", "oracle_operation", "self_hosted_runner", "operational_entrypoint"}))
    if "frontend" in profile.project_types:
        _add(capabilities, "browser_qa", "A browser-facing framework was detected.", _relevant_evidence(profile, {"frontend_framework"}))
    if "api" in profile.project_types:
        _add(capabilities, "api_contract_review", "An API framework, edge API, or API-shaped source layout was detected.", _relevant_evidence(profile, {"api_signal"}))
    if "proxy_service" in profile.project_types:
        _add(capabilities, "proxy_service_review", "A separate proxy service component was detected.", _component_evidence(profile, {"proxy_service", "node_service"}, {"package_dependency", "api_signal"}))
    if "cloudflare_worker" in profile.project_types:
        _add(capabilities, "worker_runtime_review", "Wrangler configuration identifies an edge-worker runtime.", _relevant_evidence(profile, {"cloudflare_deployment", "worker_manifest"}))
    if "data_ml" in profile.project_types:
        _add(capabilities, "ml_reproducibility", "Strong ML dependencies or repository artifacts/layout were detected.", _relevant_evidence(profile, {"ml_signal"}))
    if "infrastructure" in profile.project_types:
        _add(capabilities, "infrastructure_safety", "Declarative infrastructure or container deployment files were detected.", _component_evidence(profile, {"infrastructure"}))
    if profile.deployment.targets:
        _add(capabilities, "deployment_review", "One or more concrete deployment targets were detected.", profile.deployment.evidence)
    if {"api", "cloudflare_worker", "proxy_service", "infrastructure", "operations", "pipeline"}.intersection(profile.project_types):
        _add(capabilities, "security_review", "The repository exposes service, edge, infrastructure, or operational trust boundaries.", _relevant_evidence(profile, {"api_signal", "cloudflare_deployment", "cloudflare_api", "oracle_operation", "self_hosted_runner", "infrastructure_signal"}))

    agents: list[AgentPlan] = [AgentPlan("repo_mapper", "Repository mapper", "Maintain the evidence-backed repository profile.", ["repo_analysis"], "Always needed to ground the proposed team in local facts.")]
    agents.append(AgentPlan("test_engineer", "Test engineer", "Assess and run the safest available test strategy.", ["test_strategy"], "Testing is relevant even when the repository currently lacks a real suite."))
    capability_ids = {item.capability_id for item in capabilities}
    if "dependency_audit" in capability_ids:
        agents.append(AgentPlan("dependency_guardian", "Dependency guardian", "Review dependency and supply-chain changes.", ["dependency_audit"], "The repository contains dependency manifests."))
    agent_by_capability = {
        "pipeline_review": AgentPlan("pipeline_reviewer", "Pipeline reviewer", "Review operational pipeline stages and side effects.", ["pipeline_review"], "Selected only for pipeline-shaped repositories."),
        "ci_cd_review": AgentPlan("ci_cd_reviewer", "CI/CD reviewer", "Review workflow triggers, runners, permissions, and commands.", ["ci_cd_review"], "Selected when CI/CD workflows are detected."),
        "operations_review": AgentPlan("operations_reviewer", "Operations reviewer", "Review runtime integrations and operational safety.", ["operations_review"], "Selected for automation with operational side effects."),
        "browser_qa": AgentPlan("browser_qa", "Browser QA", "Review user-facing browser flows.", ["browser_qa"], "Only selected for browser-facing projects."),
        "api_contract_review": AgentPlan("api_reviewer", "API reviewer", "Review API contracts and compatibility.", ["api_contract_review"], "Selected for API-shaped components."),
        "proxy_service_review": AgentPlan("proxy_reviewer", "Proxy reviewer", "Review the separate Node proxy boundary.", ["proxy_service_review"], "Selected for a nested proxy service component."),
        "worker_runtime_review": AgentPlan("worker_reviewer", "Worker reviewer", "Review edge runtime and Wrangler configuration.", ["worker_runtime_review"], "Only selected for Cloudflare Workers components."),
        "ml_reproducibility": AgentPlan("ml_reviewer", "ML reviewer", "Review experiment and model reproducibility.", ["ml_reproducibility"], "Only selected for strong data/ML signals."),
        "infrastructure_safety": AgentPlan("infrastructure_reviewer", "Infrastructure reviewer", "Review infrastructure change safety.", ["infrastructure_safety"], "Only selected when infrastructure is detected."),
        "deployment_review": AgentPlan("deployment_reviewer", "Deployment reviewer", "Review concrete deployment targets and release paths.", ["deployment_review"], "Selected when the profiler identifies a deployment target."),
        "security_review": AgentPlan("security_reviewer", "Security reviewer", "Review trust boundaries and secret handling.", ["security_review"], "Selected for service, edge, infrastructure, or operational boundaries."),
    }
    for recommendation in capabilities:
        agent = agent_by_capability.get(recommendation.capability_id)
        if agent:
            agents.append(agent)

    integrations: list[IntegrationRecommendation] = []
    questions: list[UserQuestion] = []
    optional_external = {"jira", "confluence", "dify"}
    for integration in profile.integrations:
        if integration.name not in optional_external:
            continue
        capability_id = f"{integration.name}_{'issue_context' if integration.name == 'jira' else 'context' if integration.name == 'confluence' else 'workflow'}"
        if not integration.detected and integration.name not in request_lower:
            continue
        status = RecommendationStatus.REQUIRES_AUTHORIZATION if integration.detected else RecommendationStatus.UNAVAILABLE
        reason = "A repository runtime reference makes this useful, but the MVP has no connector and requires explicit authorization." if integration.detected else "The user mentioned this integration, but no connector is installed in the MVP."
        integrations.append(IntegrationRecommendation(integration.name, status, reason))
        if capability_id in CAPABILITIES:
            capabilities.append(CapabilityRecommendation(capability_id, status, Availability.REQUIRES_AUTHORIZATION if status == RecommendationStatus.REQUIRES_AUTHORIZATION else Availability.UNAVAILABLE, reason, integration.evidence))
        questions.append(UserQuestion(f"authorize_{integration.name}", f"Authorize read-only {integration.name} context for a future integration?", "External integrations are optional and never enabled automatically.", ["No", "Yes, after review"]))
    if not profile.tests.present:
        questions.append(UserQuestion("test_baseline", "Should the proposal include a test-baseline task for this repository?", "No real test suite or recognized test command was detected.", ["Yes, add baseline", "No, defer tests"]))
    if len(profile.deployment.targets) > 1:
        questions.append(UserQuestion("deployment_scope", "Which deployment target should receive priority in the team plan?", "More than one concrete deployment target was detected.", profile.deployment.targets))

    assumptions = ["All generated agents are read-only by default and cannot deploy, commit, push, or call external systems.", "Existing local .codex customizations should be compared before applying a proposal."]
    return TeamPlan(capabilities, agents, integrations, questions, assumptions)
