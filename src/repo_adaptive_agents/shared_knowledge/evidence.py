"""Bounded, literal repository facts for model-owned Skill selection."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_EXCLUDED_DIRECTORIES = frozenset({".git", ".agents", ".claude", ".codex", ".venv", "node_modules", "__pycache__"})
_MANIFEST_NAMES = frozenset({
    "pyproject.toml", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "requirements.txt", "Pipfile", "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "wrangler.toml", "terraform.tf",
})


@dataclass(frozen=True)
class RepositoryKnowledgeEvidence:
    data: dict[str, Any]
    sha256: str


def _relative_files(root: Path, excluded_paths: tuple[str, ...]) -> tuple[str, ...]:
    excluded = {Path(path).as_posix().strip("/") for path in excluded_paths}
    found: list[str] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        parts = Path(relative).parts
        if any(part in _EXCLUDED_DIRECTORIES for part in parts) or any(
            relative == item or relative.startswith(item + "/") for item in excluded
        ):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        found.append(relative)
        if len(found) >= 400:
            break
    return tuple(sorted(found))


def collect_skill_bootstrap_evidence(
    root: Path,
    repository_id: str,
    *,
    excluded_paths: tuple[str, ...] = (".team-knowledge",),
) -> RepositoryKnowledgeEvidence:
    """Expose literal paths and file-name facts; semantic relevance remains model-owned."""
    files = _relative_files(root, excluded_paths)
    suffixes = Counter(Path(path).suffix.lower() or "[no extension]" for path in files)
    manifests = tuple(path for path in files if Path(path).name in _MANIFEST_NAMES)
    data: dict[str, Any] = {
        "schema_version": 2,
        "repository": repository_id,
        "files": files,
        "file_extensions": dict(sorted(suffixes.items())),
        "manifests": manifests,
    }
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return RepositoryKnowledgeEvidence(data, hashlib.sha256(encoded).hexdigest())
