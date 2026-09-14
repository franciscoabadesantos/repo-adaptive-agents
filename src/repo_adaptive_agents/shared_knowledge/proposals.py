"""Local, non-publishing proposal workspaces for canonical Agent Skills."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .canonical import SKILL_NAME, load_canonical_catalog
from .repository import SharedKnowledgeError
from .consumer import load_consumer_lock
from .skill_validation import SkillCandidate, load_candidate


def proposal_root(repository: Path) -> Path:
    return repository / ".team-knowledge" / "proposals"


@dataclass(frozen=True)
class PreparedProposal:
    checkout: Path
    branch: str
    diff: str
    base_ref: str
    skill_id: str
    source_path: str
    reused: bool = False


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", *arguments], cwd=root, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "Git failed"
        raise SharedKnowledgeError(detail)
    return result.stdout


def _replace_materialized(target: Path, candidate: SkillCandidate) -> None:
    sidecar = target / "team-knowledge.json"
    if sidecar.is_symlink() or not sidecar.is_file():
        raise SharedKnowledgeError("canonical Skill sidecar is missing or unsafe")
    for child in target.iterdir():
        if child.name == "team-knowledge.json":
            continue
        if child.is_symlink():
            raise SharedKnowledgeError("canonical Skill contains unsafe symlink")
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for relative, data in candidate.files:
        destination = target.joinpath(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def _repository_skill_path(catalog_path: str, skill_path: str) -> str:
    if catalog_path == ".":
        return skill_path
    return f"{catalog_path.rstrip('/')}/{skill_path}"


def _git_paths(root: Path, *arguments: str) -> tuple[str, ...]:
    return tuple(path for path in _git(root, *arguments).split("\0") if path)


def _proposal_diff(checkout: Path, repository_skill_path: str) -> str:
    untracked = _git_paths(
        checkout,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        repository_skill_path,
    )
    if untracked:
        _git(checkout, "add", "--intent-to-add", "--", *untracked)
    try:
        return _git(checkout, "diff", "--no-ext-diff", "--", repository_skill_path)
    finally:
        if untracked:
            _git(checkout, "reset", "--", *untracked)


def _path_is_within(path: str, parent: str) -> bool:
    return path == parent or path.startswith(parent + "/")


def _reuse_prepared_update(
    final: Path,
    branch: str,
    resource,
    candidate: SkillCandidate,
    repository_skill_path: str,
) -> PreparedProposal:
    unsafe = "existing prepared proposal is not reusable; keep it for inspection or remove it deliberately"
    if final.is_symlink() or not final.is_dir():
        raise SharedKnowledgeError(unsafe)
    if _git(final, "rev-parse", "HEAD").strip() != resource.resolved_source_commit:
        raise SharedKnowledgeError(unsafe)
    if _git(final, "branch", "--show-current").strip() != branch:
        raise SharedKnowledgeError(unsafe)
    if _git_paths(final, "diff", "--cached", "--name-only", "-z"):
        raise SharedKnowledgeError(unsafe)
    changed = set(_git_paths(final, "diff", "--name-only", "-z"))
    changed.update(_git_paths(final, "ls-files", "--others", "--exclude-standard", "-z"))
    if not changed or any(not _path_is_within(path, repository_skill_path) for path in changed):
        raise SharedKnowledgeError(unsafe)
    catalog = final if resource.source_catalog_path == "." else final / resource.source_catalog_path
    target = catalog / resource.source_path
    existing = load_candidate(target)
    if existing.digest_sha256 != candidate.digest_sha256 or existing.files != candidate.files:
        raise SharedKnowledgeError(unsafe)
    parsed = load_canonical_catalog(catalog, resource.resolved_source_commit, lambda _path: resource.revision)
    verified = parsed.by_id().get(resource.id)
    if verified is None or verified.digest_sha256 != candidate.digest_sha256:
        raise SharedKnowledgeError(unsafe)
    diff = _proposal_diff(final, repository_skill_path)
    if not diff:
        raise SharedKnowledgeError(unsafe)
    return PreparedProposal(
        checkout=final,
        branch=branch,
        diff=diff,
        base_ref=resource.source_ref,
        skill_id=resource.id,
        source_path=repository_skill_path,
        reused=True,
    )


def prepare_update(repository: Path, skill_id: str, candidate: SkillCandidate) -> PreparedProposal:
    """Prepare an uncommitted, pinned source checkout without touching the remote."""
    lock = load_consumer_lock(repository)
    resource = next((item for item in lock.resources if item.id == skill_id), None)
    if resource is None:
        raise SharedKnowledgeError("selected Skill is not installed in this repository")
    root = repository / ".team-knowledge" / "runtime" / "proposals"
    root.mkdir(parents=True, exist_ok=True)
    branch = f"team-knowledge/{resource.name}-{candidate.digest_sha256[:12]}"
    final = root / f"{resource.name}-{candidate.digest_sha256[:12]}"
    repository_skill_path = _repository_skill_path(resource.source_catalog_path, resource.source_path)
    if final.exists():
        return _reuse_prepared_update(final, branch, resource, candidate, repository_skill_path)
    with tempfile.TemporaryDirectory(prefix="proposal-", dir=root) as temporary:
        staging = Path(temporary) / "source"
        _git(repository, "clone", "--no-checkout", resource.source_url, str(staging))
        _git(staging, "checkout", "--detach", resource.resolved_source_commit)
        _git(staging, "switch", "-c", branch)
        catalog = staging if resource.source_catalog_path == "." else staging / resource.source_catalog_path
        target = catalog / resource.source_path
        _replace_materialized(target, candidate)
        parsed = load_canonical_catalog(catalog, resource.resolved_source_commit, lambda _path: resource.revision)
        verified = parsed.by_id().get(resource.id)
        if verified is None or verified.digest_sha256 != candidate.digest_sha256:
            raise SharedKnowledgeError("prepared canonical package does not match the validated candidate")
        diff = _proposal_diff(staging, repository_skill_path)
        if not diff:
            raise SharedKnowledgeError("candidate has no change relative to the locked canonical Skill")
        os.replace(staging, final)
    return PreparedProposal(
        checkout=final,
        branch=branch,
        diff=diff,
        base_ref=resource.source_ref,
        skill_id=resource.id,
        source_path=repository_skill_path,
    )


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
