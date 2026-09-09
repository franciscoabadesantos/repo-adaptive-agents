"""Isolated, non-mutating validation of explicit canonical Skill candidates."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

from .canonical import (
    MAX_FILE_BYTES,
    MAX_SKILL_BYTES,
    REFERENCE_SUFFIXES,
    CanonicalSkill,
    load_canonical_catalog,
    package_digest,
)
from .catalog import SharedKnowledgeError
from .consumer import load_consumer_lock
from .source import GitKnowledgeSource


@dataclass(frozen=True)
class SkillCandidate:
    """One proposed portable package, detached from every other Skill."""

    path: Path
    name: str
    description: str
    files: tuple[tuple[str, bytes], ...]
    digest_sha256: str


@dataclass(frozen=True)
class SkillValidationReport:
    skill_id: str
    name: str
    candidate_path: Path
    candidate_digest_sha256: str
    changed_paths: tuple[str, ...]
    passed: bool
    findings: tuple[str, ...]


def local_canonical_skills(catalog_root: Path) -> tuple[CanonicalSkill, ...]:
    catalog = load_canonical_catalog(catalog_root, "working-tree", lambda _path: "working-tree")
    return tuple(skill for skill in catalog.skills if skill.state == "active")


def _frontmatter(text: str) -> tuple[str, str]:
    """Read portable fields required for a materialized candidate package."""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise SharedKnowledgeError("candidate SKILL.md must start with a --- frontmatter delimiter")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise SharedKnowledgeError("candidate SKILL.md frontmatter must end with a --- delimiter") from error
    values: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line.strip():
            continue
        if line[:1].isspace() or ":" not in line:
            raise SharedKnowledgeError("candidate SKILL.md frontmatter must use top-level key: value fields")
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if key not in {"name", "description"} or not value or key in values:
            raise SharedKnowledgeError("candidate SKILL.md has unsupported, empty, or duplicate frontmatter")
        values[key] = " ".join(value.split())
    if set(values) != {"name", "description"}:
        raise SharedKnowledgeError("candidate SKILL.md must contain only name and description frontmatter")
    if not "\n".join(lines[closing + 1 :]).strip():
        raise SharedKnowledgeError("candidate SKILL.md body must be non-empty")
    return values["name"], values["description"]


def load_candidate(path: Path) -> SkillCandidate:
    """Load one materializable package, allowing a derived .agents copy without its sidecar."""
    if path.is_symlink() or not path.is_dir():
        raise SharedKnowledgeError(f"candidate Skill path is missing or unsafe: {path}")
    files: list[tuple[str, bytes]] = []
    total = 0
    for entry in sorted(path.rglob("*")):
        relative = entry.relative_to(path)
        label = relative.as_posix()
        if entry.is_symlink():
            raise SharedKnowledgeError(f"candidate Skill contains symlink: {label}")
        mode = entry.stat(follow_symlinks=False).st_mode
        if entry.is_dir():
            if "scripts" in relative.parts:
                raise SharedKnowledgeError("candidate Skill may not contain scripts/")
            continue
        if not stat.S_ISREG(mode) or mode & 0o111:
            raise SharedKnowledgeError(f"candidate Skill contains unsafe file: {label}")
        allowed = label in {"SKILL.md", "team-knowledge.json", "proposal.json"} or (
            relative.parts[0] == "references" and entry.suffix.lower() in REFERENCE_SUFFIXES
        )
        if not allowed:
            raise SharedKnowledgeError(f"unsupported candidate Skill file: {label}")
        data = entry.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            raise SharedKnowledgeError(f"candidate Skill file is too large: {label}")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SharedKnowledgeError(f"candidate Skill file must be UTF-8 text: {label}") from error
        total += len(data)
        if total > MAX_SKILL_BYTES:
            raise SharedKnowledgeError(f"candidate Skill package is too large: {path.name}")
        if label not in {"team-knowledge.json", "proposal.json"}:
            files.append((label, data))
    values = dict(files)
    if "SKILL.md" not in values:
        raise SharedKnowledgeError(f"candidate Skill is missing SKILL.md: {path}")
    name, description = _frontmatter(values["SKILL.md"].decode("utf-8"))
    normalized = tuple(files)
    return SkillCandidate(path, name, description, normalized, package_digest(normalized))


def _changed_paths(baseline: CanonicalSkill, candidate: SkillCandidate) -> tuple[str, ...]:
    before, after = dict(baseline.files), dict(candidate.files)
    return tuple(path for path in sorted(set(before) | set(after)) if before.get(path) != after.get(path))


def validate_skill(skill: CanonicalSkill, candidate_path: Path | None = None) -> SkillValidationReport:
    """Validate one candidate against its own predecessor, never another Skill."""
    candidate = load_candidate(candidate_path) if candidate_path is not None else SkillCandidate(
        Path(skill.source_path), skill.name, skill.description, skill.files, skill.digest_sha256
    )
    findings: list[str] = ["Candidate package structure and portable identity are valid."]
    if candidate.name != skill.name:
        findings.append(f"Candidate name {candidate.name!r} does not match canonical name {skill.name!r}.")
    text = "\n".join(data.decode("utf-8") for _path, data in candidate.files)
    for marker in ("BEGIN PRIVATE KEY", "CLOUDFLARE_TOKEN=", "Authorization: Bearer "):
        if marker in text:
            findings.append(f"Unsafe credential-like marker found: {marker!r}")
    for marker in ("/home/user/", "C:\\Users\\"):
        if marker in text:
            findings.append(f"Local-machine path found: {marker!r}")
    changed_paths = _changed_paths(skill, candidate)
    findings.append(
        "Candidate differs from the canonical package: " + ", ".join(changed_paths)
        if changed_paths
        else "Candidate exactly matches the current canonical package."
    )
    blocking = any(
        finding.startswith(("Candidate name", "Unsafe credential", "Local-machine path"))
        for finding in findings
    )
    return SkillValidationReport(
        skill.id,
        skill.name,
        candidate.path,
        candidate.digest_sha256,
        changed_paths,
        not blocking,
        tuple(findings),
    )


def selected_skills(catalog_root: Path, ids: tuple[str, ...]) -> tuple[CanonicalSkill, ...]:
    available = {skill.id: skill for skill in local_canonical_skills(catalog_root)}
    unknown = [skill_id for skill_id in ids if skill_id not in available]
    if unknown:
        raise SharedKnowledgeError(f"unknown active canonical Skill: {unknown[0]}")
    return tuple(available[skill_id] for skill_id in dict.fromkeys(ids))


def consumer_validation_targets(root: Path) -> tuple[tuple[CanonicalSkill, Path], ...]:
    """Return only installed packages and their exact locked canonical predecessors."""
    lock = load_consumer_lock(root)
    import tempfile

    with tempfile.TemporaryDirectory(prefix="team-knowledge-validation-") as temporary:
        source = GitKnowledgeSource(root, state=Path(temporary) / "state")
        source.acquire(
            lock.source_url, lock.source_ref, catalog_path=lock.catalog_path,
        )
        commit = source.acquire(
            lock.source_url, lock.source_ref, catalog_path=lock.catalog_path,
            offline=True, commit=lock.resolved_commit,
        )
        with source.snapshot(commit, catalog_path=lock.catalog_path) as snapshot:
            canonical = load_canonical_catalog(snapshot, commit, lambda _path: commit)
    by_id = canonical.by_id()
    targets: list[tuple[CanonicalSkill, Path]] = []
    for resource in lock.resources:
        skill = by_id.get(resource.id)
        if skill is None or skill.digest_sha256 != resource.digest_sha256:
            raise SharedKnowledgeError(f"locked canonical Skill cannot be reproduced: {resource.id}")
        targets.append((skill, root / resource.materialized_path))
    return tuple(targets)
