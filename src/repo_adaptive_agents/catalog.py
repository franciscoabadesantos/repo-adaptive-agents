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
    "application_review": CapabilityDefinition(
        "application_review", "Application review", "Review executable entrypoints, lifecycle, interaction loops, and failure handling.", ("application",)
    ),
    "computer_vision_review": CapabilityDefinition(
        "computer_vision_review", "Computer vision review", "Review detection pipelines, geometry, thresholds, and frame processing.", ("computer_vision",)
    ),
    "image_processing_review": CapabilityDefinition(
        "image_processing_review", "Image processing review", "Review image transformations, numerical behavior, and visual artifacts.", ("image_processing",)
    ),
    "ml_inference_review": CapabilityDefinition(
        "ml_inference_review", "ML inference review", "Review model loading, preprocessing, inference, and post-processing.", ("ml_inference",)
    ),
    "model_evaluation": CapabilityDefinition(
        "model_evaluation", "Model evaluation", "Review representative data, metrics, thresholds, and failure modes.", ("ml_inference", "ml")
    ),
    "shell_review": CapabilityDefinition(
        "shell_review", "Shell review", "Review shell safety, portability, quoting, and error handling.", ("shell",)
    ),
    "acme_protocol_review": CapabilityDefinition(
        "acme_protocol_review", "ACME protocol review", "Review ACME account, challenge, order, finalize, and revoke flows.", ("certificate",)
    ),
    "certificate_lifecycle_review": CapabilityDefinition(
        "certificate_lifecycle_review", "Certificate lifecycle review", "Review key, CSR, issuance, renewal, install, revoke, and reload handling.", ("certificate",)
    ),
    "integration_review": CapabilityDefinition(
        "integration_review", "Integration review", "Review external-system contracts, side effects, retries, and authorization boundaries.", ("integration",)
    ),
    "mcp_protocol_review": CapabilityDefinition(
        "mcp_protocol_review", "MCP protocol review", "Review MCP transport, server lifecycle, errors, and protocol behavior.", ("mcp",)
    ),
    "tool_contract_review": CapabilityDefinition(
        "tool_contract_review", "Tool contract review", "Review tool inputs, outputs, schemas, and compatibility.", ("mcp", "developer_tool")
    ),
    "photographic_domain_review": CapabilityDefinition(
        "photographic_domain_review", "Photographic domain review", "Review photographic controls, metadata, profiles, and processing semantics.", ("photography",)
    ),
    "visual_evaluation": CapabilityDefinition(
        "visual_evaluation", "Visual evaluation", "Review before/after evaluation and image-quality evidence.", ("image_processing", "photography")
    ),
    "container_review": CapabilityDefinition(
        "container_review", "Container review", "Review container packaging and runtime support without treating it as repository identity.", ("container",)
    ),
    "dns_configuration_review": CapabilityDefinition(
        "dns_configuration_review", "DNS configuration review", "Review declarative DNS providers, zones, plans, and apply safety.", ("dns",)
    ),
    "java_spring_review": CapabilityDefinition(
        "java_spring_review", "Java and Spring review", "Review Spring Boot lifecycle, HTTP boundaries, configuration, and module structure.", ("java", "spring")
    ),
    "messaging_architecture_review": CapabilityDefinition(
        "messaging_architecture_review", "Messaging architecture review", "Review producer/consumer boundaries, message flow, retries, and failure handling.", ("messaging", "integration")
    ),
    "rabbitmq_review": CapabilityDefinition(
        "rabbitmq_review", "RabbitMQ review", "Review queues, exchanges, routing, acknowledgements, dead letters, and broker configuration.", ("messaging", "rabbitmq")
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
