"""Bounded factual profiler projection for repository-level Skill selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from repo_adaptive_agents.profiler import profile_repository


@dataclass(frozen=True)
class RepositoryKnowledgeEvidence:
    data: dict[str, Any]
    sha256: str


def _strings(values: Iterable[str], limit: int = 80) -> list[str]:
    return sorted(dict.fromkeys(value for value in values if value))[:limit]


def _evidence(values: Iterable[Any], limit: int = 80) -> list[dict[str, object]]:
    projected = [
        {
            "signal": item.signal,
            "paths": _strings(item.paths, 20),
            "detail": item.detail[:300],
        }
        for item in values
    ]
    return sorted(projected, key=lambda item: (str(item["signal"]), tuple(item["paths"])))[:limit]


def collect_skill_bootstrap_evidence(
    root: Path,
    repository_id: str,
    *,
    excluded_paths: tuple[str, ...] = (".team-knowledge",),
) -> RepositoryKnowledgeEvidence:
    profile = profile_repository(root, evidence_path_limit=20, excluded_paths=excluded_paths)
    components = [
        {
            "path": component.path or ".",
            "languages": _strings(component.languages),
            "frameworks": _strings(component.frameworks),
            "runtimes": _strings(component.runtimes),
            "manifests": _strings(component.manifests),
            "entrypoints": _strings(component.entrypoints),
            "deployment_targets": _strings(component.deployment_targets),
            "evidence": _evidence(component.evidence, 30),
        }
        for component in sorted(profile.components, key=lambda item: (item.path, item.name))
    ]
    integrations = [
        {
            "name": integration.name,
            "evidence": _evidence(integration.evidence, 20),
        }
        for integration in sorted(profile.integrations, key=lambda item: item.name)
        if integration.detected
    ]
    data: dict[str, Any] = {
        "schema_version": 1,
        "repository": repository_id,
        "languages": _strings(profile.languages),
        "frameworks": _strings(profile.frameworks),
        "manifests": _strings(profile.manifests),
        "components": components,
        "contracts": {
            "package_managers": dict(sorted(profile.workflow.package_managers.items())),
            "development_commands": _strings(profile.workflow.development_commands),
            "build_commands": _strings(profile.workflow.build_commands),
            "validation_commands": _strings(profile.workflow.validation_commands),
            "test_frameworks": _strings(profile.tests.frameworks),
            "test_commands": _strings(profile.tests.commands),
        },
        "architecture": {
            "entrypoints": _strings(profile.architecture.entrypoints),
            "evidence": _evidence(profile.architecture.evidence),
        },
        "deployment": {
            "tools": _strings(profile.deployment.tools),
            "targets": _strings(profile.deployment.targets),
            "evidence": _evidence(profile.deployment.evidence),
        },
        "integrations": integrations,
    }
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return RepositoryKnowledgeEvidence(data, hashlib.sha256(encoded).hexdigest())
