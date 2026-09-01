"""Strict loading and canonical hashing for governed contextual assets."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

from .models import (
    CompatibilityConstraint,
    EnvironmentContractSemantics,
    Governance,
    Lifecycle,
    MCPSemantics,
    PolicySemantics,
    RepositoryInstructionSemantics,
    ResourceRecord,
    Scope,
    SkillSemantics,
    to_data,
)


KINDS = {
    "agent_skill",
    "repository_instruction",
    "mcp_tool",
    "mcp_resource",
    "organizational_policy",
    "environment_contract",
}
APPROVALS = {"approved", "draft", "unapproved", "denied"}
DISPOSITIONS = {"selectable", "mandatory", "forbidden"}
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_BYTES = 2_000_000


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class ResourceCatalog:
    schema_version: int
    resources: tuple[ResourceRecord, ...]

    def canonical_data(self) -> dict[str, Any]:
        resources: list[dict[str, Any]] = []
        for resource in self.resources:
            item = to_data(resource)
            item["compatibility"] = {
                constraint.dimension: list(constraint.allowed_values)
                for constraint in resource.compatibility
            }
            resources.append(item)
        return {"schema_version": self.schema_version, "resources": resources}

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_data(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def by_id(self) -> dict[str, ResourceRecord]:
        return {item.id: item for item in self.resources}

    def validated(self) -> ResourceCatalog:
        """Re-parse programmatically constructed catalogs through the strict contract."""
        return parse_catalog(self.canonical_data())


def content_sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _exact(value: object, fields: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise CatalogError(f"{context} fields must be exactly: {', '.join(sorted(fields))}")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{context} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, context: str) -> str | None:
    return None if value is None else _string(value, context)


def _strings(value: object, context: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise CatalogError(f"{context} must be an array")
    result = tuple(_string(item, f"{context} entry") for item in value)
    if len(result) != len(set(result)):
        raise CatalogError(f"{context} entries must be unique")
    return result


def _date(value: object, context: str) -> str | None:
    parsed = _optional_string(value, context)
    if parsed is not None:
        try:
            date.fromisoformat(parsed)
        except ValueError as error:
            raise CatalogError(f"{context} must use YYYY-MM-DD") from error
    return parsed


def _relative_path(value: object, context: str) -> str | None:
    path = _optional_string(value, context)
    if path is None:
        return None
    if "\\" in path or "\x00" in path or path.startswith("/"):
        raise CatalogError(f"{context} must be a safe repository-relative POSIX path")
    parts = tuple(part for part in PurePosixPath(path).parts if part not in {"", "."})
    if not parts or ".." in parts or parts[0] == ".git":
        raise CatalogError(f"{context} must be a safe repository-relative POSIX path")
    return "/".join(parts)


def _semantics(kind: str, value: object, resource_id: str):
    context = f"resource {resource_id} semantics"
    if kind == "agent_skill":
        item = _exact(value, {"harnesses", "entrypoint"}, context)
        return SkillSemantics(_strings(item["harnesses"], f"{context} harnesses", allow_empty=False), _string(item["entrypoint"], f"{context} entrypoint"))
    if kind == "repository_instruction":
        item = _exact(value, {"instruction_path"}, context)
        return RepositoryInstructionSemantics(_relative_path(item["instruction_path"], f"{context} instruction_path") or "")
    if kind in {"mcp_tool", "mcp_resource"}:
        item = _exact(value, {"server", "capability", "permissions", "requires_network"}, context)
        if type(item["requires_network"]) is not bool:
            raise CatalogError(f"{context} requires_network must be boolean")
        return MCPSemantics(
            _string(item["server"], f"{context} server"),
            _string(item["capability"], f"{context} capability"),
            _strings(item["permissions"], f"{context} permissions"),
            item["requires_network"],
        )
    if kind == "organizational_policy":
        item = _exact(value, {"policy_class"}, context)
        return PolicySemantics(_string(item["policy_class"], f"{context} policy_class"))
    item = _exact(value, {"contract_class"}, context)
    return EnvironmentContractSemantics(_string(item["contract_class"], f"{context} contract_class"))


def parse_catalog(payload: object) -> ResourceCatalog:
    root = _exact(payload, {"schema_version", "resources"}, "catalog")
    if root["schema_version"] != 1 or type(root["schema_version"]) is not int:
        raise CatalogError("catalog schema_version must be 1")
    if not isinstance(root["resources"], list):
        raise CatalogError("catalog resources must be an array")
    resources: list[ResourceRecord] = []
    for raw in root["resources"]:
        item = _exact(raw, {
            "id", "kind", "title", "summary", "body", "source", "revision",
            "content_sha256", "lifecycle", "scope", "compatibility", "governance", "semantics",
        }, "resource")
        resource_id = _string(item["id"], "resource id")
        if not _ID.fullmatch(resource_id):
            raise CatalogError(f"invalid resource id: {resource_id}")
        kind = _string(item["kind"], f"resource {resource_id} kind")
        if kind not in KINDS:
            raise CatalogError(f"resource {resource_id} has unsupported kind: {kind}")
        body = _string(item["body"], f"resource {resource_id} body")
        declared_digest = _string(item["content_sha256"], f"resource {resource_id} content_sha256")
        if not _SHA256.fullmatch(declared_digest) or declared_digest != content_sha256(body):
            raise CatalogError(f"resource {resource_id} content_sha256 does not match body")

        lifecycle_raw = _exact(item["lifecycle"], {"approval", "effective_from", "expires_at", "revoked_at"}, f"resource {resource_id} lifecycle")
        approval = _string(lifecycle_raw["approval"], f"resource {resource_id} approval")
        if approval not in APPROVALS:
            raise CatalogError(f"resource {resource_id} has unsupported approval: {approval}")
        lifecycle = Lifecycle(
            approval,
            _date(lifecycle_raw["effective_from"], f"resource {resource_id} effective_from"),
            _date(lifecycle_raw["expires_at"], f"resource {resource_id} expires_at"),
            _date(lifecycle_raw["revoked_at"], f"resource {resource_id} revoked_at"),
        )

        scope_raw = _exact(item["scope"], {"organization", "team", "repository", "path"}, f"resource {resource_id} scope")
        scope = Scope(
            _optional_string(scope_raw["organization"], f"resource {resource_id} scope organization"),
            _optional_string(scope_raw["team"], f"resource {resource_id} scope team"),
            _optional_string(scope_raw["repository"], f"resource {resource_id} scope repository"),
            _relative_path(scope_raw["path"], f"resource {resource_id} scope path"),
        )

        if not isinstance(item["compatibility"], dict):
            raise CatalogError(f"resource {resource_id} compatibility must be an object")
        compatibility = tuple(
            CompatibilityConstraint(_string(dimension, "compatibility dimension"), _strings(values, f"resource {resource_id} compatibility {dimension}", allow_empty=False))
            for dimension, values in sorted(item["compatibility"].items())
        )

        governance_raw = _exact(item["governance"], {"disposition", "authority", "supersedes", "conflicts_with"}, f"resource {resource_id} governance")
        disposition = _string(governance_raw["disposition"], f"resource {resource_id} disposition")
        if disposition not in DISPOSITIONS:
            raise CatalogError(f"resource {resource_id} has unsupported disposition: {disposition}")
        authority = governance_raw["authority"]
        if type(authority) is not int or authority < 0:
            raise CatalogError(f"resource {resource_id} authority must be a non-negative integer")
        governance = Governance(
            disposition,
            authority,
            _strings(governance_raw["supersedes"], f"resource {resource_id} supersedes"),
            _strings(governance_raw["conflicts_with"], f"resource {resource_id} conflicts_with"),
        )
        if kind in {"organizational_policy", "repository_instruction", "environment_contract"} and disposition == "selectable":
            raise CatalogError(f"resource {resource_id} type {kind} cannot be ranked as selectable")
        if kind in {"agent_skill", "mcp_tool", "mcp_resource"} and disposition == "mandatory":
            raise CatalogError(f"resource {resource_id} type {kind} cannot be a mandatory control")

        resources.append(ResourceRecord(
            resource_id,
            kind,  # type: ignore[arg-type]
            _string(item["title"], f"resource {resource_id} title"),
            _string(item["summary"], f"resource {resource_id} summary"),
            body,
            _string(item["source"], f"resource {resource_id} source"),
            _string(item["revision"], f"resource {resource_id} revision"),
            declared_digest,
            lifecycle,
            scope,
            compatibility,
            governance,
            _semantics(kind, item["semantics"], resource_id),
        ))

    identifiers = [item.id for item in resources]
    if len(identifiers) != len(set(identifiers)):
        raise CatalogError("resource ids must be unique")
    known = set(identifiers)
    for resource in resources:
        relations = set(resource.governance.supersedes) | set(resource.governance.conflicts_with)
        unknown = sorted(relations - known)
        if unknown:
            raise CatalogError(f"resource {resource.id} references unknown resources: {unknown}")
        if resource.id in relations:
            raise CatalogError(f"resource {resource.id} cannot relate to itself")

    supersedes = {resource.id: resource.governance.supersedes for resource in resources}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(resource_id: str) -> None:
        if resource_id in visiting:
            raise CatalogError(f"supersession cycle includes resource {resource_id}")
        if resource_id in visited:
            return
        visiting.add(resource_id)
        for superseded_id in supersedes[resource_id]:
            visit(superseded_id)
        visiting.remove(resource_id)
        visited.add(resource_id)

    for resource_id in sorted(supersedes):
        visit(resource_id)
    return ResourceCatalog(1, tuple(sorted(resources, key=lambda resource: resource.id)))


def load_catalog(path: str | Path) -> ResourceCatalog:
    catalog_path = Path(path).expanduser().resolve()
    if not catalog_path.is_file() or catalog_path.stat().st_size > _MAX_BYTES:
        raise CatalogError(f"catalog missing or exceeds {_MAX_BYTES} bytes: {catalog_path}")
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CatalogError(f"invalid catalog: {error}") from error
    return parse_catalog(payload)
