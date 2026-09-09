"""Local, non-publishing proposal workspaces for canonical Agent Skills."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .canonical import SKILL_NAME
from .catalog import SharedKnowledgeError
from .consumer import load_consumer_lock


def proposal_root(repository: Path) -> Path:
    return repository / ".team-knowledge" / "proposals"


def prepare_update(repository: Path, skill_id: str) -> Path:
    lock = load_consumer_lock(repository)
    resource = next((item for item in lock.resources if item.id == skill_id), None)
    if resource is None:
        raise SharedKnowledgeError("selected Skill is not installed in this repository")
    source = repository / resource.materialized_path
    target = proposal_root(repository) / resource.name
    if target.exists():
        raise SharedKnowledgeError(f"proposal already exists: {target}; edit it or remove it deliberately")
    if not source.is_dir() or source.is_symlink():
        raise SharedKnowledgeError(f"installed Skill is missing or unsafe: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=True)
    (target / "proposal.json").write_text(json.dumps({
        "schema_version": 1, "kind": "update", "skill_id": resource.id,
        "canonical_source_url": resource.source_url, "canonical_revision": resource.revision,
    }, indent=2) + "\n", encoding="utf-8")
    return target


def prepare_new(repository: Path, name: str, description: str) -> Path:
    if not name or not description:
        raise SharedKnowledgeError("new Skill name and description are required")
    if not SKILL_NAME.fullmatch(name):
        raise SharedKnowledgeError("new Skill name must use lowercase words separated by hyphens")
    target = proposal_root(repository) / name
    if target.exists():
        raise SharedKnowledgeError(f"proposal already exists: {target}; edit it or remove it deliberately")
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\nDescribe the shared procedure and its boundaries.\n",
        encoding="utf-8",
    )
    (target / "proposal.json").write_text(json.dumps({"schema_version": 1, "kind": "new"}, indent=2) + "\n", encoding="utf-8")
    return target
