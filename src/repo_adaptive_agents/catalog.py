"""Initial capability catalog. External integrations are intentionally not adapters."""

from .models import Availability, CapabilityDefinition


CAPABILITIES: dict[str, CapabilityDefinition] = {
    "repo_analysis": CapabilityDefinition(
        "repo_analysis", "Repository analysis", "Map repository structure and detected signals.", ("all",)
    ),
    "test_strategy": CapabilityDefinition(
        "test_strategy", "Test strategy", "Run or improve the repository's existing test strategy.", ("all",)
    ),
    "dependency_audit": CapabilityDefinition(
        "dependency_audit", "Dependency audit", "Review dependency manifests and supply-chain risk.", ("all",)
    ),
    "pipeline_review": CapabilityDefinition(
        "pipeline_review", "Pipeline review", "Review operational pipeline stages, ordering, retries, and data movement.", ("pipeline", "automation")
    ),
    "ci_cd_review": CapabilityDefinition(
        "ci_cd_review", "CI/CD review", "Review workflows, triggers, runners, permissions, and operational commands.", ("ci_cd",)
    ),
    "operations_review": CapabilityDefinition(
        "operations_review", "Operations review", "Review runtime integrations, operational side effects, and runbook safety.", ("operations", "automation")
    ),
    "browser_qa": CapabilityDefinition(
        "browser_qa", "Browser QA", "Validate user-facing browser flows and responsive behavior.", ("frontend",)
    ),
    "api_contract_review": CapabilityDefinition(
        "api_contract_review", "API contract review", "Review HTTP/API boundaries, schemas, and compatibility.", ("api",)
    ),
    "proxy_service_review": CapabilityDefinition(
        "proxy_service_review", "Proxy service review", "Review the separate Node proxy service and its boundary with the edge component.", ("proxy_service",)
    ),
    "worker_runtime_review": CapabilityDefinition(
        "worker_runtime_review", "Worker runtime review", "Review edge-runtime bindings, limits, and deployment config.", ("worker",)
    ),
    "ml_reproducibility": CapabilityDefinition(
        "ml_reproducibility", "ML reproducibility", "Review datasets, experiments, environments, and model evaluation.", ("ml",)
    ),
    "infrastructure_safety": CapabilityDefinition(
        "infrastructure_safety", "Infrastructure safety", "Review declarative infrastructure and change risk.", ("infrastructure",)
    ),
    "deployment_review": CapabilityDefinition(
        "deployment_review", "Deployment review", "Review deployment targets, packaging, and release paths.", ("deployment",)
    ),
    "security_review": CapabilityDefinition(
        "security_review", "Security review", "Inspect secrets handling, trust boundaries, and exposed services.", ("api", "worker", "infrastructure")
    ),
    "jira_issue_context": CapabilityDefinition(
        "jira_issue_context", "Jira issue context", "Load issue context from Jira for planning and traceability.", ("all",), Availability.UNAVAILABLE, True
    ),
    "confluence_context": CapabilityDefinition(
        "confluence_context", "Confluence context", "Load team documentation from Confluence.", ("all",), Availability.UNAVAILABLE, True
    ),
    "dify_workflow": CapabilityDefinition(
        "dify_workflow", "Dify workflow", "Use an approved Dify workflow for assisted recommendations.", ("all",), Availability.UNAVAILABLE, True
    ),
}
