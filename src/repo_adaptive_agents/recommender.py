"""Small, explainable recommendation rules."""

from __future__ import annotations

from .catalog import CAPABILITIES
from .models import (
    Availability,
    AgentPlan,
    CapabilityRecommendation,
    Evidence,
    InfrastructurePlan,
    IntegrationRecommendation,
    RecommendationStatus,
    RepoProfile,
    RepositoryContracts,
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


def _repository_contracts(profile: RepoProfile) -> RepositoryContracts:
    return RepositoryContracts(
        package_managers=dict(profile.workflow.package_managers),
        development_commands=list(profile.workflow.development_commands),
        build_commands=list(profile.workflow.build_commands),
        validation_commands=list(profile.workflow.validation_commands),
        test_commands=list(profile.tests.commands),
        browser_qa_commands=list(profile.browser_qa.commands),
        browser_qa_manages_server=profile.browser_qa.manages_server,
        browser_qa_server_commands=list(profile.browser_qa.server_commands),
        deployment_tools=list(profile.deployment.tools),
        deployment_targets=list(profile.deployment.targets),
    )


def recommend_infrastructure(profile: RepoProfile, request: str = "") -> InfrastructurePlan:
    request_lower = request.lower()
    capabilities: list[CapabilityRecommendation] = []
    _add(capabilities, "repo_analysis", "Useful for every repository to preserve an evidence-backed map.", profile.evidence[:3] + profile.architecture.evidence[:2])

    test_status = RecommendationStatus.RECOMMENDED if profile.tests.present else RecommendationStatus.MISSING
    test_reason = "Existing tests or a recognized test command can be exercised by a focused agent." if profile.tests.present else "No real test suite was detected; a focused agent is needed to establish a safe baseline."
    _add(capabilities, "test_strategy", test_reason, profile.tests.evidence, test_status)
    if profile.manifests:
        _add(capabilities, "dependency_audit", "Recognized dependency manifests are present.", _relevant_evidence(profile, {"manifest", "package_dependency", "python_dependency", "ml_dependency"}))
    if "pipeline" in profile.project_types:
        _add(capabilities, "pipeline_review", "Operational or delivery pipeline entrypoints and stages were detected.", _relevant_evidence(profile, {"operational_entrypoint", "oracle_operation", "cloudflare_api", "jenkins_pipeline", "maven_packaging"}))
    if "ci_cd" in profile.project_types:
        _add(capabilities, "ci_cd_review", "CI/CD workflows, triggers, runners, or delivery pipelines were detected.", _relevant_evidence(profile, {"ci_cd_workflow", "self_hosted_runner", "jenkins_pipeline", "tests_disabled_in_build"}))
    if "operations" in profile.project_types:
        _add(capabilities, "operations_review", "Operational side effects or external runtime integrations were detected.", _relevant_evidence(profile, {"operations_signal", "cloudflare_api", "oracle_operation", "self_hosted_runner", "operational_entrypoint", "java_service_wrapper", "rabbitmq_signal", "external_http_gateway"}))
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
    if "application" in profile.project_types:
        _add(capabilities, "application_review", "An executable application entrypoint or interactive lifecycle was detected.", _relevant_evidence(profile, {"application_entrypoint", "interactive_ui", "cli_entrypoint"}))
    if "computer_vision" in profile.project_types:
        _add(capabilities, "computer_vision_review", "Computer-vision inference or classical vision processing was detected.", _relevant_evidence(profile, {"ml_inference_signal", "image_processing_signal"}))
    if "image_processing" in profile.project_types:
        _add(capabilities, "image_processing_review", "Image-processing operations are part of the repository's runtime behavior.", _relevant_evidence(profile, {"image_processing_signal", "photographic_domain_signal"}))
    if "ml_inference" in profile.project_types:
        inference_evidence = _relevant_evidence(profile, {"ml_inference_signal", "external_model_artifact_missing"})
        _add(capabilities, "ml_inference_review", "A local model inference pipeline was detected.", inference_evidence)
        _add(capabilities, "ml_reproducibility", "Inference depends on reproducible model/configuration artifacts and preprocessing.", inference_evidence)
        _add(capabilities, "model_evaluation", "Inference thresholds and post-processing require representative evaluation.", inference_evidence)
    if "shell_tool" in profile.project_types and "messaging_application" not in profile.primary_project_types:
        _add(capabilities, "shell_review", "Executable shell tooling was detected.", _relevant_evidence(profile, {"shell_tool_signal", "shellcheck_config"}))
    if "certificate_automation" in profile.project_types:
        _add(capabilities, "acme_protocol_review", "ACME protocol operations were detected.", _relevant_evidence(profile, {"acme_protocol_signal"}))
        _add(capabilities, "certificate_lifecycle_review", "Certificate and key lifecycle operations were detected.", _relevant_evidence(profile, {"certificate_lifecycle_signal", "sensitive_operations"}))
    if {"integration_tool", "integration_service", "dns_iac"}.intersection(profile.project_types):
        _add(capabilities, "integration_review", "The repository coordinates external tools, providers, or services.", _relevant_evidence(profile, {"dns_provider_hooks", "mcp_server_signal", "dns_configuration", "sensitive_operations", "cloudflare_api", "oracle_operation", "rabbitmq_signal", "external_http_gateway"}))
    if "java_application" in profile.project_types:
        _add(capabilities, "java_spring_review", "Spring Boot services or executable Java components were detected.", _relevant_evidence(profile, {"java_spring_signal", "spring_web_signal", "spring_actuator_signal"}))
    if "messaging_application" in profile.project_types:
        _add(capabilities, "messaging_architecture_review", "Publishers, consumers, and runtime integration boundaries form a messaging application.", _relevant_evidence(profile, {"rabbitmq_signal", "external_http_gateway"}))
    rabbitmq = next((item for item in profile.integrations if item.name == "rabbitmq"), None)
    if rabbitmq and rabbitmq.detected:
        _add(capabilities, "rabbitmq_review", "RabbitMQ is a runtime integration with publisher, listener, or broker configuration signals.", rabbitmq.evidence)
    if "mcp_server" in profile.project_types:
        _add(capabilities, "mcp_protocol_review", "A FastMCP server and transport lifecycle were detected.", _relevant_evidence(profile, {"mcp_server_signal"}))
        _add(capabilities, "tool_contract_review", "Registered MCP tools require stable and reviewable contracts.", _relevant_evidence(profile, {"mcp_server_signal", "opaque_tool_contract"}))
    if "photographic_tool" in profile.project_types:
        photo_evidence = _relevant_evidence(profile, {"photographic_domain_signal", "image_processing_signal"})
        _add(capabilities, "photographic_domain_review", "Photographic processing and metadata semantics were detected.", photo_evidence)
        _add(capabilities, "visual_evaluation", "The tool produces or evaluates visual image-processing results.", photo_evidence)
    if "dns_iac" in profile.project_types:
        _add(capabilities, "dns_configuration_review", "Declarative DNS providers and deployment targets were detected.", _relevant_evidence(profile, {"dns_configuration", "cloudflare_dns_target", "rfc2136_dns_target"}))
    if "containerized" in profile.secondary_project_types:
        _add(capabilities, "container_review", "Container support is present as a secondary packaging/deployment concern.", _relevant_evidence(profile, {"container_support"}))
    if "infrastructure" in profile.project_types:
        _add(capabilities, "infrastructure_safety", "Declarative infrastructure or container deployment files were detected.", _component_evidence(profile, {"infrastructure"}))
    if profile.deployment.targets:
        _add(capabilities, "deployment_review", "One or more concrete deployment targets were detected.", profile.deployment.evidence)
    if {"api", "cloudflare_worker", "proxy_service", "infrastructure", "operations", "pipeline", "security_tooling", "certificate_automation", "dns_iac"}.intersection(profile.project_types):
        _add(capabilities, "security_review", "The repository exposes service, edge, infrastructure, certificate, DNS, or operational trust boundaries.", _relevant_evidence(profile, {"api_signal", "cloudflare_deployment", "cloudflare_api", "oracle_operation", "self_hosted_runner", "infrastructure_signal", "acme_protocol_signal", "certificate_lifecycle_signal", "sensitive_operations", "dns_configuration"}))

    available_roles: list[AgentPlan] = [AgentPlan("repo_mapper", "Repository mapper", "Maintain the evidence-backed repository profile.", ["repo_analysis"], "Available to ground future work in local facts when repository mapping adds value.")]
    available_roles.append(AgentPlan("test_engineer", "Test engineer", "Assess and run the safest available test strategy.", ["test_strategy"], "Available when test strategy or independent test evidence is needed."))
    capability_ids = {item.capability_id for item in capabilities}
    if "dependency_audit" in capability_ids:
        available_roles.append(AgentPlan("dependency_guardian", "Dependency guardian", "Review dependency and supply-chain changes.", ["dependency_audit"], "Available because the repository contains dependency manifests."))
    agent_by_capability = {
        "pipeline_review": AgentPlan("pipeline_reviewer", "Pipeline reviewer", "Review operational pipeline stages and side effects.", ["pipeline_review"], "Available for pipeline-shaped repositories."),
        "ci_cd_review": AgentPlan("ci_cd_reviewer", "CI/CD reviewer", "Review workflow triggers, runners, permissions, and commands.", ["ci_cd_review"], "Available when CI/CD workflows are detected."),
        "operations_review": AgentPlan("operations_reviewer", "Operations reviewer", "Review runtime integrations and operational safety.", ["operations_review"], "Available for automation with operational side effects."),
        "browser_qa": AgentPlan("browser_qa", "Browser QA", "Review user-facing browser flows.", ["browser_qa"], "Available for browser-facing projects when independent runtime evidence adds value."),
        "api_contract_review": AgentPlan("api_reviewer", "API reviewer", "Review API contracts and compatibility.", ["api_contract_review"], "Available for API-shaped components."),
        "proxy_service_review": AgentPlan("proxy_reviewer", "Proxy reviewer", "Review the separate Node proxy boundary.", ["proxy_service_review"], "Available for a nested proxy service component."),
        "worker_runtime_review": AgentPlan("worker_reviewer", "Worker reviewer", "Review edge runtime and Wrangler configuration.", ["worker_runtime_review"], "Available for Cloudflare Workers components."),
        "ml_reproducibility": AgentPlan("ml_reviewer", "ML reviewer", "Review experiment and model reproducibility.", ["ml_reproducibility"], "Available for strong data/ML signals."),
        "infrastructure_safety": AgentPlan("infrastructure_reviewer", "Infrastructure reviewer", "Review infrastructure change safety.", ["infrastructure_safety"], "Available when infrastructure is detected."),
        "deployment_review": AgentPlan("deployment_reviewer", "Deployment reviewer", "Review concrete deployment targets and release paths.", ["deployment_review"], "Available when the profiler identifies a deployment target."),
        "security_review": AgentPlan("security_reviewer", "Security reviewer", "Review trust boundaries and secret handling.", ["security_review"], "Available for service, edge, infrastructure, or operational boundaries."),
        "application_review": AgentPlan("application_reviewer", "Application reviewer", "Review executable lifecycle and interaction behavior.", ["application_review"], "Available for executable application repositories."),
        "computer_vision_review": AgentPlan("computer_vision_reviewer", "Computer vision reviewer", "Review detection and geometric vision pipelines.", ["computer_vision_review"], "Available for computer-vision runtime behavior."),
        "image_processing_review": AgentPlan("image_processing_reviewer", "Image processing reviewer", "Review image transformations and artifacts.", ["image_processing_review"], "Available for image-processing repositories."),
        "ml_inference_review": AgentPlan("ml_inference_reviewer", "ML inference reviewer", "Review model loading and inference behavior.", ["ml_inference_review", "ml_reproducibility", "model_evaluation"], "Available for local ML inference."),
        "shell_review": AgentPlan("shell_reviewer", "Shell reviewer", "Review shell safety and portability.", ["shell_review"], "Available for shell-based tools."),
        "acme_protocol_review": AgentPlan("certificate_reviewer", "Certificate reviewer", "Review ACME and certificate lifecycle safety.", ["acme_protocol_review", "certificate_lifecycle_review"], "Available for certificate automation."),
        "integration_review": AgentPlan("integration_reviewer", "Integration reviewer", "Review external provider and tool boundaries.", ["integration_review"], "Available for integration services and operational hooks."),
        "mcp_protocol_review": AgentPlan("mcp_reviewer", "MCP reviewer", "Review MCP lifecycle, transport, and protocol behavior.", ["mcp_protocol_review"], "Available for MCP servers."),
        "tool_contract_review": AgentPlan("tool_contract_reviewer", "Tool contract reviewer", "Review MCP tool schemas and compatibility.", ["tool_contract_review"], "Available for registered tool contracts."),
        "photographic_domain_review": AgentPlan("photographic_reviewer", "Photographic reviewer", "Review photographic processing semantics.", ["photographic_domain_review", "visual_evaluation"], "Available for photographic tools."),
        "container_review": AgentPlan("container_reviewer", "Container reviewer", "Review secondary container packaging.", ["container_review"], "Available when container support exists."),
        "dns_configuration_review": AgentPlan("dns_reviewer", "DNS configuration reviewer", "Review DNS plans, providers, and apply safety.", ["dns_configuration_review"], "Available for DNS-as-code repositories."),
        "java_spring_review": AgentPlan("java_spring_reviewer", "Java and Spring reviewer", "Review Spring Boot service structure and runtime behavior.", ["java_spring_review"], "Available for executable Spring Boot components."),
        "messaging_architecture_review": AgentPlan("messaging_reviewer", "Messaging architecture reviewer", "Review message flow, service boundaries, and failure handling.", ["messaging_architecture_review"], "Available for producer/consumer messaging applications."),
        "rabbitmq_review": AgentPlan("rabbitmq_reviewer", "RabbitMQ reviewer", "Review RabbitMQ topology, delivery semantics, and broker configuration.", ["rabbitmq_review"], "Available when RabbitMQ runtime integration is detected."),
    }
    for recommendation in capabilities:
        if recommendation.capability_id == "ml_reproducibility" and "data_ml" not in profile.project_types:
            continue
        agent = agent_by_capability.get(recommendation.capability_id)
        if agent:
            available_roles.append(agent)

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
        questions.append(UserQuestion("deployment_scope", "Which deployment target should receive priority in the infrastructure plan?", "More than one concrete deployment target was detected.", profile.deployment.targets))

    assumptions = [
        "Available roles are repository capabilities, not a mandatory execution pipeline; select them proportionally per task.",
        "Running a repository QA command does not require creating a corresponding QA agent.",
        "Generated review roles are read-only by default and cannot deploy, commit, push, or call external systems.",
        "Existing harness-specific customizations should be compared before applying a proposal.",
    ]
    return InfrastructurePlan(
        repository_contracts=_repository_contracts(profile),
        capabilities=capabilities,
        available_roles=available_roles,
        integrations=integrations,
        questions=questions,
        assumptions=assumptions,
    )


def recommend_team(profile: RepoProfile, request: str = "") -> InfrastructurePlan:
    """Compatibility alias for the original MVP API."""
    return recommend_infrastructure(profile, request)
