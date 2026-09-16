"""Local, non-publishing proposal workspaces for canonical Agent Skills."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .canonical import SKILL_NAME, load_canonical_catalog
from .repository import SharedKnowledgeError
from .consumer import load_consumer_lock
from .skill_validation import SkillCandidate, load_candidate
from .source import GitKnowledgeSource


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
    kind: str = "update"


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


def _reusable_checkout_state(
    final: Path,
    branch: str,
    base_commit: str,
    catalog_path: str,
    skill_path: str,
    candidate: SkillCandidate,
    repository_skill_path: str,
) -> tuple[Path, str]:
    unsafe = "existing prepared proposal is not reusable; keep it for inspection or remove it deliberately"
    if final.is_symlink() or not final.is_dir():
        raise SharedKnowledgeError(unsafe)
    if _git(final, "rev-parse", "HEAD").strip() != base_commit:
        raise SharedKnowledgeError(unsafe)
    if _git(final, "branch", "--show-current").strip() != branch:
        raise SharedKnowledgeError(unsafe)
    if _git_paths(final, "diff", "--cached", "--name-only", "-z"):
        raise SharedKnowledgeError(unsafe)
    changed = set(_git_paths(final, "diff", "--name-only", "-z"))
    changed.update(_git_paths(final, "ls-files", "--others", "--exclude-standard", "-z"))
    if not changed or any(not _path_is_within(path, repository_skill_path) for path in changed):
        raise SharedKnowledgeError(unsafe)
    catalog = final if catalog_path == "." else final / catalog_path
    existing = load_candidate(catalog / skill_path)
    if existing.digest_sha256 != candidate.digest_sha256 or existing.files != candidate.files:
        raise SharedKnowledgeError(unsafe)
    diff = _proposal_diff(final, repository_skill_path)
    if not diff:
        raise SharedKnowledgeError(unsafe)
    return catalog, diff


def _reuse_prepared_update(
    final: Path,
    branch: str,
    resource,
    candidate: SkillCandidate,
    repository_skill_path: str,
    base_commit: str,
) -> PreparedProposal:
    unsafe = "existing prepared proposal is not reusable; keep it for inspection or remove it deliberately"
    catalog, diff = _reusable_checkout_state(
        final,
        branch,
        base_commit,
        resource.source_catalog_path,
        resource.source_path,
        candidate,
        repository_skill_path,
    )
    parsed = load_canonical_catalog(catalog, base_commit, lambda _path: base_commit)
    verified = parsed.by_id().get(resource.id)
    if verified is None or verified.digest_sha256 != candidate.digest_sha256:
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


def _reuse_prepared_addition(
    final: Path,
    branch: str,
    lock,
    candidate: SkillCandidate,
    repository_skill_path: str,
    base_commit: str,
) -> PreparedProposal:
    unsafe = "existing prepared proposal is not reusable; keep it for inspection or remove it deliberately"
    catalog, diff = _reusable_checkout_state(
        final,
        branch,
        base_commit,
        lock.catalog_path,
        f"skills/{candidate.name}",
        candidate,
        repository_skill_path,
    )
    parsed = load_canonical_catalog(catalog, base_commit, lambda _path: base_commit)
    verified = parsed.by_id().get(candidate.name)
    if (
        verified is None
        or verified.name != candidate.name
        or verified.state != "active"
        or verified.digest_sha256 != candidate.digest_sha256
    ):
        raise SharedKnowledgeError(unsafe)
    return PreparedProposal(
        checkout=final,
        branch=branch,
        diff=diff,
        base_ref=lock.source_ref,
        skill_id=candidate.name,
        source_path=repository_skill_path,
        reused=True,
        kind="addition",
    )


def _prepare_worktree(source: GitKnowledgeSource, branch: str, base_commit: str) -> Path:
    replica = source.repository
    if replica is None:
        raise SharedKnowledgeError("canonical source must be acquired before preparing a proposal")
    worktrees = replica.parent / "worktrees"
    worktrees.mkdir(exist_ok=True)
    final = worktrees / branch.replace("/", "-")
    if final.exists():
        return final
    _git(replica, "worktree", "prune")
    existing = _git(replica, "branch", "--list", branch).strip()
    if existing:
        raise SharedKnowledgeError(
            "a local proposal branch already exists without its prepared worktree; "
            "inspect or remove that branch deliberately"
        )
    _git(replica, "worktree", "add", "-b", branch, str(final), base_commit)
    return final


def _latest_catalog(source: GitKnowledgeSource, commit: str, catalog_path: str):
    with source.snapshot(commit, catalog_path=catalog_path) as snapshot:
        return load_canonical_catalog(
            snapshot,
            commit,
            lambda path: source.revision_for(commit, path, catalog_path=catalog_path),
        )


def prepare_update(
    repository: Path,
    skill_id: str,
    candidate: SkillCandidate,
    *,
    offline: bool = False,
) -> PreparedProposal:
    """Prepare an update from the latest local canonical baseline."""
    lock = load_consumer_lock(repository)
    resource = next((item for item in lock.resources if item.id == skill_id), None)
    if resource is None:
        raise SharedKnowledgeError("selected Skill is not installed in this repository")
    source = GitKnowledgeSource(repository)
    catalog_commit = source.acquire(
        resource.source_url,
        resource.source_ref,
        catalog_path=resource.source_catalog_path,
        offline=offline,
    )
    base_commit = source.resolved_ref_commit or catalog_commit
    replica = source.repository
    if replica is None:
        raise SharedKnowledgeError("canonical source must be acquired before preparing a proposal")
    latest = _latest_catalog(source, base_commit, resource.source_catalog_path)
    latest_skill = latest.by_id().get(resource.id)
    if latest_skill is None:
        raise SharedKnowledgeError("the installed Skill no longer exists in the latest canonical catalog")
    if latest_skill.digest_sha256 != resource.digest_sha256:
        raise SharedKnowledgeError(
            "the canonical Skill changed after it was installed; run team-knowledge sync, "
            "reapply the intended edit, and validate it again"
        )
    branch = (
        f"team-knowledge/{resource.name}-{candidate.digest_sha256[:12]}-{base_commit[:12]}"
    )
    final = replica.parent / "worktrees" / branch.replace("/", "-")
    repository_skill_path = _repository_skill_path(resource.source_catalog_path, resource.source_path)
    if final.exists():
        return _reuse_prepared_update(
            final, branch, resource, candidate, repository_skill_path, base_commit
        )
    staging = _prepare_worktree(source, branch, base_commit)
    catalog = staging if resource.source_catalog_path == "." else staging / resource.source_catalog_path
    target = catalog / resource.source_path
    _replace_materialized(target, candidate)
    parsed = load_canonical_catalog(catalog, base_commit, lambda _path: base_commit)
    verified = parsed.by_id().get(resource.id)
    if verified is None or verified.digest_sha256 != candidate.digest_sha256:
        raise SharedKnowledgeError("prepared canonical package does not match the validated candidate")
    diff = _proposal_diff(staging, repository_skill_path)
    if not diff:
        raise SharedKnowledgeError("candidate has no change relative to the latest canonical Skill")
    return PreparedProposal(
        checkout=staging,
        branch=branch,
        diff=diff,
        base_ref=resource.source_ref,
        skill_id=resource.id,
        source_path=repository_skill_path,
    )


def prepare_addition(
    repository: Path,
    candidate: SkillCandidate,
    *,
    offline: bool = False,
) -> PreparedProposal:
    """Prepare a validated new Skill from the latest local canonical baseline."""
    lock = load_consumer_lock(repository)
    source = GitKnowledgeSource(repository)
    catalog_commit = source.acquire(
        lock.source_url,
        lock.source_ref,
        catalog_path=lock.catalog_path,
        offline=offline,
    )
    base_commit = source.resolved_ref_commit or catalog_commit
    replica = source.repository
    if replica is None:
        raise SharedKnowledgeError("canonical source must be acquired before preparing a proposal")
    latest = _latest_catalog(source, base_commit, lock.catalog_path)
    if any(skill.id == candidate.name or skill.name == candidate.name for skill in latest.skills):
        raise SharedKnowledgeError(
            f"canonical catalog already contains Skill name or ID: {candidate.name}"
        )
    branch = (
        f"team-knowledge/add-{candidate.name}-{candidate.digest_sha256[:12]}-{base_commit[:12]}"
    )
    final = replica.parent / "worktrees" / branch.replace("/", "-")
    skill_path = f"skills/{candidate.name}"
    repository_skill_path = _repository_skill_path(lock.catalog_path, skill_path)
    if final.exists():
        return _reuse_prepared_addition(
            final, branch, lock, candidate, repository_skill_path, base_commit
        )
    staging = _prepare_worktree(source, branch, base_commit)
    catalog = staging if lock.catalog_path == "." else staging / lock.catalog_path
    target = catalog / skill_path
    if target.exists() or target.is_symlink():
        raise SharedKnowledgeError(f"canonical Skill destination already exists: {skill_path}")
    target.mkdir(parents=True)
    for relative, data in candidate.files:
        destination = target.joinpath(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    (target / "team-knowledge.json").write_text(
        json.dumps(
            {"schema_version": 1, "id": candidate.name, "state": "active"},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    parsed = load_canonical_catalog(catalog, base_commit, lambda _path: base_commit)
    verified = parsed.by_id().get(candidate.name)
    if (
        verified is None
        or verified.name != candidate.name
        or verified.state != "active"
        or verified.digest_sha256 != candidate.digest_sha256
    ):
        raise SharedKnowledgeError("prepared canonical addition does not match the validated candidate")
    diff = _proposal_diff(staging, repository_skill_path)
    if not diff:
        raise SharedKnowledgeError("new Skill did not produce a canonical catalog change")
    return PreparedProposal(
        checkout=staging,
        branch=branch,
        diff=diff,
        base_ref=lock.source_ref,
        skill_id=candidate.name,
        source_path=repository_skill_path,
        kind="addition",
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
