"""Validated catalog snapshots and exact model-visible payload digests."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .models import (
    EnvironmentContractPayload,
    MCPPayload,
    PolicyPayload,
    RepositoryInstructionPayload,
    ResourceContent,
    ResourceKind,
    ResourcePayload,
    ResourceRecord,
    SkillPayload,
    to_data,
)


_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CatalogError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(to_data(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_sha256(
    kind: ResourceKind,
    title: str,
    summary: str,
    body: str,
    payload: ResourcePayload,
) -> str:
    model_payload = {
        "kind": kind,
        "title": title,
        "summary": summary,
        "body": body,
        "payload": payload,
    }
    return hashlib.sha256(canonical_json(model_payload).encode("utf-8")).hexdigest()


def build_content(
    resource_id: str,
    revision: str,
    kind: ResourceKind,
    title: str,
    summary: str,
    body: str,
    payload: ResourcePayload,
) -> ResourceContent:
    return ResourceContent(
        resource_id,
        revision,
        payload_sha256(kind, title, summary, body, payload),
        kind,
        title,
        summary,
        body,
        payload,
    )


def _validate_content(content: ResourceContent) -> None:
    if not _ID.fullmatch(content.id):
        raise CatalogError(f"invalid resource id: {content.id}")
    for name in ("revision", "title", "summary", "body"):
        value = getattr(content, name)
        if not isinstance(value, str) or not value.strip():
            raise CatalogError(f"resource {content.id} {name} must be non-empty")
    if not isinstance(content.kind, ResourceKind):
        raise CatalogError(f"resource {content.id} kind must be a ResourceKind")
    expected_payload = {
        ResourceKind.AGENT_SKILL: SkillPayload,
        ResourceKind.REPOSITORY_INSTRUCTION: RepositoryInstructionPayload,
        ResourceKind.MCP_TOOL: MCPPayload,
        ResourceKind.MCP_RESOURCE: MCPPayload,
        ResourceKind.ORGANIZATIONAL_POLICY: PolicyPayload,
        ResourceKind.ENVIRONMENT_CONTRACT: EnvironmentContractPayload,
    }[content.kind]
    if not isinstance(content.payload, expected_payload):
        raise CatalogError(f"resource {content.id} payload does not match kind {content.kind.value}")
    actual = payload_sha256(content.kind, content.title, content.summary, content.body, content.payload)
    if not _SHA256.fullmatch(content.payload_sha256) or content.payload_sha256 != actual:
        raise CatalogError(f"resource {content.id} payload_sha256 does not match model-visible content")


@dataclass(frozen=True)
class ResourceCatalog:
    revision: str
    resources: tuple[ResourceRecord, ...]
    schema_version: int = 2

    def validated(self) -> ResourceCatalog:
        if self.schema_version != 2:
            raise CatalogError("catalog schema_version must be 2")
        if not isinstance(self.revision, str) or not self.revision.strip():
            raise CatalogError("catalog revision must be a non-empty string")
        identifiers = [resource.content.id for resource in self.resources]
        if len(identifiers) != len(set(identifiers)):
            raise CatalogError("resource IDs must be unique")
        known = set(identifiers)
        rule_refs: set[tuple[str, str]] = set()
        for resource in self.resources:
            _validate_content(resource.content)
            lifecycle = resource.admission.lifecycle
            if lifecycle.effective_at and lifecycle.expires_at and lifecycle.effective_at >= lifecycle.expires_at:
                raise CatalogError(f"resource {resource.content.id} effective_at must precede expires_at")
            rule_ids = [rule.id for rule in resource.admission.control_rules]
            if len(rule_ids) != len(set(rule_ids)):
                raise CatalogError(f"resource {resource.content.id} control rule IDs must be unique")
            rule_refs.update((resource.content.id, rule_id) for rule_id in rule_ids)
            unknown = set(resource.admission.supersedes) - known
            if unknown:
                raise CatalogError(f"resource {resource.content.id} supersedes unknown resources: {sorted(unknown)}")
            if resource.content.id in resource.admission.supersedes:
                raise CatalogError(f"resource {resource.content.id} cannot supersede itself")

        for resource in self.resources:
            for rule in resource.admission.control_rules:
                for reference in rule.conflicts_with:
                    target = (reference.resource_id, reference.rule_id)
                    if target not in rule_refs:
                        raise CatalogError(
                            f"control {resource.content.id}#{rule.id} conflicts with unknown control "
                            f"{reference.resource_id}#{reference.rule_id}"
                        )
                    if target == (resource.content.id, rule.id):
                        raise CatalogError(f"control {resource.content.id}#{rule.id} cannot conflict with itself")

        supersedes = {resource.content.id: resource.admission.supersedes for resource in self.resources}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(resource_id: str) -> None:
            if resource_id in visiting:
                raise CatalogError(f"supersession cycle includes resource {resource_id}")
            if resource_id in visited:
                return
            visiting.add(resource_id)
            for older_id in supersedes[resource_id]:
                visit(older_id)
            visiting.remove(resource_id)
            visited.add(resource_id)

        for resource_id in sorted(supersedes):
            visit(resource_id)
        return ResourceCatalog(self.revision.strip(), tuple(sorted(self.resources, key=lambda item: item.content.id)), 2)

    def by_id(self) -> dict[str, ResourceRecord]:
        return {resource.content.id: resource for resource in self.resources}

    def canonical_data(self) -> dict[str, Any]:
        validated = self.validated()
        return {
            "schema_version": validated.schema_version,
            "revision": validated.revision,
            "resources": to_data(validated.resources),
        }

    def canonical_json(self) -> str:
        return canonical_json(self.canonical_data())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
