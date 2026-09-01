"""Development-only proof that orchestration can remain policy-free.

This module translates generic dictionaries into the native domain objects. It
does not decide lifecycle, scope, compatibility, dependencies, supersession,
controls, authority, conflicts, exposure, or post-selection admission.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping

import repo_adaptive_agents.admission_control as native


Retriever = Callable[[tuple[native.ResourceContent, ...]], tuple[native.ResourceContent, ...]]
Selector = Callable[[Mapping[str, Any], tuple[native.ResourceContent, ...]], tuple[native.CandidateSelection, ...]]


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _predicate(data: Mapping[str, Any]) -> native.FactPredicate:
    return native.FactPredicate(
        str(data["key"]),
        native.PredicateOperator(str(data["operator"])),
        tuple(str(value) for value in data["values"]),
    )


def translate_context(data: Mapping[str, Any]) -> native.AdmissionContext:
    return native.AdmissionContext(
        organization=str(data["organization"]),
        team=str(data["team"]),
        repository=str(data["repository"]),
        affected_paths=tuple(str(path) for path in data["affected_paths"]),
        effective_at=_timestamp(str(data["effective_at"])),  # type: ignore[arg-type]
        facts={str(key): tuple(str(value) for value in values) for key, values in data.get("facts", {}).items()},
    )


def _payload(kind: native.ResourceKind, data: Mapping[str, Any]) -> native.ResourcePayload:
    if kind == native.ResourceKind.AGENT_SKILL:
        return native.SkillPayload(tuple(str(value) for value in data["harnesses"]), str(data["entrypoint"]))
    if kind == native.ResourceKind.REPOSITORY_INSTRUCTION:
        return native.RepositoryInstructionPayload(str(data["instruction_path"]))
    if kind in {native.ResourceKind.MCP_TOOL, native.ResourceKind.MCP_RESOURCE}:
        return native.MCPPayload(
            str(data["server"]),
            str(data["capability"]),
            tuple(str(value) for value in data["permissions"]),
        )
    if kind == native.ResourceKind.ORGANIZATIONAL_POLICY:
        return native.PolicyPayload(str(data["policy_class"]))
    return native.EnvironmentContractPayload(str(data["contract_class"]))


def _resource(data: Mapping[str, Any]) -> native.ResourceRecord:
    content_data = data["content"]
    admission_data = data["admission"]
    lifecycle_data = admission_data["lifecycle"]
    scope_data = admission_data.get("scope", {})
    kind = native.ResourceKind(str(content_data["kind"]))
    payload = _payload(kind, content_data["payload"])
    content = native.ResourceContent(
        id=str(content_data["id"]),
        revision=str(content_data["revision"]),
        payload_sha256=str(content_data["payload_sha256"]),
        kind=kind,
        title=str(content_data["title"]),
        summary=str(content_data["summary"]),
        body=str(content_data["body"]),
        payload=payload,
    )
    rules = tuple(
        native.ControlRule(
            id=str(rule["id"]),
            effect=native.ControlEffect(str(rule["effect"])),
            when=tuple(_predicate(item) for item in rule.get("when", ())),
            authority=int(rule["authority"]),
            conflicts_with=tuple(
                native.ControlRef(str(reference["resource_id"]), str(reference["rule_id"]))
                for reference in rule.get("conflicts_with", ())
            ),
        )
        for rule in admission_data.get("control_rules", ())
    )
    return native.ResourceRecord(
        content,
        native.AdmissionEnvelope(
            lifecycle=native.Lifecycle(
                state=native.LifecycleState(str(lifecycle_data["state"])),
                effective_at=_timestamp(lifecycle_data.get("effective_at")),
                expires_at=_timestamp(lifecycle_data.get("expires_at")),
                revoked_at=_timestamp(lifecycle_data.get("revoked_at")),
            ),
            scope=native.Scope(
                organization=scope_data.get("organization"),
                team=scope_data.get("team"),
                repository=scope_data.get("repository"),
                path=scope_data.get("path"),
            ),
            compatibility=tuple(_predicate(item) for item in admission_data.get("compatibility", ())),
            dependencies=tuple(
                native.Dependency(str(item["name"]), _predicate(item["predicate"]))
                for item in admission_data.get("dependencies", ())
            ),
            exposure_policy=native.ExposurePolicy(str(admission_data["exposure_policy"])),
            selectable=admission_data["selectable"],
            supersedes=tuple(str(value) for value in admission_data.get("supersedes", ())),
            control_rules=rules,
        ),
    )


def translate_catalog(data: Mapping[str, Any]) -> native.ResourceCatalog:
    """Translate representation only; native validation owns its meaning."""

    return native.ResourceCatalog(
        revision=str(data["revision"]),
        resources=tuple(_resource(resource) for resource in data["resources"]),
        schema_version=int(data.get("schema_version", 2)),
    )


def run_case(
    context_data: Mapping[str, Any],
    catalog_data: Mapping[str, Any],
    retrieve: Retriever,
    select: Selector,
    *,
    current_catalog_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Translate, call native boundaries, and serialize an auditable trace."""

    context = translate_context(context_data)
    admission_catalog = translate_catalog(catalog_data)
    snapshot = native.admit(context, admission_catalog)
    shown = tuple(retrieve(snapshot.exposable_resources))
    exposure = snapshot.record_exposure(shown)
    raw = tuple(select(context.model_facing_data(), shown))
    current_catalog = translate_catalog(current_catalog_data or catalog_data)
    result = native.validate(raw, exposure, context, current_catalog)
    return {
        "decision_origin": {
            "admit": f"{native.admit.__module__}.{native.admit.__name__}",
            "validate": f"{native.validate.__module__}.{native.validate.__name__}",
        },
        "context": context.model_facing_data(),
        "admission_snapshot": native.to_data(snapshot),
        "actual_exposure": native.to_data(exposure),
        "raw_selections": native.to_data(raw),
        "validation": native.to_data(result),
    }
