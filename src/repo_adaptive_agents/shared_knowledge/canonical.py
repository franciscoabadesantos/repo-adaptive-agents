"""Canonical, text-only Agent Skills loaded from one pinned Git snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from repo_adaptive_agents.shared_knowledge.catalog import SharedKnowledgeError


SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESOURCE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
REFERENCE_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml"})
MAX_FILE_BYTES = 1_000_000
MAX_SKILL_BYTES = 4_000_000


@dataclass(frozen=True)
class SourceDescriptor:
    source_id: str
    organization: str
    team: str


@dataclass(frozen=True)
class CanonicalSkill:
    id: str
    name: str
    description: str
    state: str
    source_path: str
    revision: str
    digest_sha256: str
    files: tuple[tuple[str, bytes], ...]
    skill_text: str

    @property
    def materialized_path(self) -> str:
        return f".agents/skills/{self.name}"


@dataclass(frozen=True)
class CanonicalCatalog:
    descriptor: SourceDescriptor
    source_commit: str
    skills: tuple[CanonicalSkill, ...]

    def by_id(self) -> dict[str, CanonicalSkill]:
        return {skill.id: skill for skill in self.skills}


def _json_object(path: Path, *, allowed: frozenset[str]) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise SharedKnowledgeError(f"canonical descriptor is missing or unsafe: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SharedKnowledgeError(f"cannot read canonical descriptor {path}: {error}") from error
    if not isinstance(value, dict):
        raise SharedKnowledgeError(f"canonical descriptor must be a JSON object: {path}")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise SharedKnowledgeError(
            f"unsupported field(s) in {path.name}: {', '.join(unknown)}"
        )
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SharedKnowledgeError(f"canonical {field} must be a non-empty string")
    return value.strip()


def _parse_source(root: Path) -> SourceDescriptor:
    data = _json_object(
        root / "team-knowledge.json",
        allowed=frozenset({"schema_version", "source_id", "organization", "team"}),
    )
    if data.get("schema_version") != 1:
        raise SharedKnowledgeError("canonical source schema_version must be 1")
    return SourceDescriptor(
        _text(data.get("source_id"), "source_id"),
        _text(data.get("organization"), "organization"),
        _text(data.get("team"), "team"),
    )


def _frontmatter_values(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line[:1].isspace() or ":" not in line:
            raise SharedKnowledgeError("SKILL.md frontmatter must use top-level key: value fields")
        field, raw = line.split(":", 1)
        field = field.strip()
        raw = raw.strip()
        if not field or field in values:
            raise SharedKnowledgeError(f"SKILL.md has invalid or duplicate {field or '<empty>'} frontmatter")
        if raw in {">", ">-", ">+", "|", "|-", "|+"}:
            block: list[str] = []
            index += 1
            while index < len(lines) and (not lines[index].strip() or lines[index][:1].isspace()):
                block.append(lines[index].strip())
                index += 1
            values[field] = ("\n" if raw.startswith("|") else " ").join(block).strip()
            continue
        values[field] = raw.strip('"\'')
        index += 1
    return values


def _parse_skill_text(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise SharedKnowledgeError("SKILL.md must start with a --- frontmatter delimiter")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise SharedKnowledgeError("SKILL.md frontmatter must end with a --- delimiter") from error
    frontmatter = lines[1:closing]
    values = _frontmatter_values(frontmatter)
    name = values.get("name")
    description = values.get("description")
    if name is None or not SKILL_NAME.fullmatch(name):
        raise SharedKnowledgeError("SKILL.md name must be a lowercase hyphenated Skill name")
    if description is None or not description.strip():
        raise SharedKnowledgeError("SKILL.md description must be non-empty")
    if not "\n".join(lines[closing + 1 :]).strip():
        raise SharedKnowledgeError("SKILL.md body must be non-empty")
    return name, " ".join(description.split())


def package_digest(files: tuple[tuple[str, bytes], ...]) -> str:
    """Hash exact materializable paths and bytes in stable path order."""

    digest = hashlib.sha256()
    for relative, content in sorted(files):
        encoded_path = relative.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def directory_digest(path: Path) -> str:
    if path.is_symlink() or not path.is_dir():
        raise SharedKnowledgeError(f"managed Agent Skill path is not a safe directory: {path}")
    files: list[tuple[str, bytes]] = []
    for candidate in sorted(path.rglob("*")):
        relative = candidate.relative_to(path).as_posix()
        if candidate.is_symlink() or not (candidate.is_dir() or candidate.is_file()):
            raise SharedKnowledgeError(f"managed Agent Skill contains unsafe entry: {relative}")
        if candidate.is_file():
            files.append((relative, candidate.read_bytes()))
    return package_digest(tuple(files))


def _skill_files(directory: Path) -> tuple[tuple[str, bytes], ...]:
    materializable: list[tuple[str, bytes]] = []
    total = 0
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        label = relative.as_posix()
        if path.is_symlink():
            raise SharedKnowledgeError(f"canonical Skill contains symlink: {label}")
        mode = path.stat(follow_symlinks=False).st_mode
        if path.is_dir():
            if "scripts" in relative.parts:
                raise SharedKnowledgeError("canonical Skills may not contain scripts/")
            continue
        if not stat.S_ISREG(mode):
            raise SharedKnowledgeError(f"canonical Skill contains non-regular file: {label}")
        if mode & 0o111:
            raise SharedKnowledgeError(f"canonical Skill contains executable file: {label}")
        allowed = label in {"SKILL.md", "team-knowledge.json"} or (
            relative.parts[0] == "references" and path.suffix.lower() in REFERENCE_SUFFIXES
        )
        if not allowed:
            raise SharedKnowledgeError(f"unsupported canonical Skill file: {label}")
        data = path.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            raise SharedKnowledgeError(f"canonical Skill file is too large: {label}")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SharedKnowledgeError(f"canonical Skill file must be UTF-8 text: {label}") from error
        total += len(data)
        if total > MAX_SKILL_BYTES:
            raise SharedKnowledgeError(f"canonical Skill package is too large: {directory.name}")
        if label != "team-knowledge.json":
            materializable.append((label, data))
    names = {name for name, _data in materializable}
    if "SKILL.md" not in names:
        raise SharedKnowledgeError(f"canonical Skill is missing SKILL.md: {directory.name}")
    return tuple(materializable)


def load_canonical_catalog(
    root: Path,
    source_commit: str,
    revision_for: Callable[[str], str],
) -> CanonicalCatalog:
    descriptor = _parse_source(root)
    skills_root = root / "skills"
    if not skills_root.exists():
        return CanonicalCatalog(descriptor, source_commit, ())
    if skills_root.is_symlink() or not skills_root.is_dir():
        raise SharedKnowledgeError("canonical source must contain a safe skills/ directory")
    stray = [
        path.name
        for path in skills_root.iterdir()
        if path.name != ".gitkeep" and (path.is_symlink() or not path.is_dir())
    ]
    if stray:
        raise SharedKnowledgeError(f"canonical skills/ contains unsafe entry: {sorted(stray)[0]}")
    parsed: list[CanonicalSkill] = []
    for directory in sorted(
        (path for path in skills_root.iterdir() if path.name != ".gitkeep"),
        key=lambda item: item.name,
    ):
        sidecar = _json_object(
            directory / "team-knowledge.json",
            allowed=frozenset({"schema_version", "id", "state"}),
        )
        if sidecar.get("schema_version") != 1:
            raise SharedKnowledgeError(f"canonical Skill {directory.name} schema_version must be 1")
        resource_id = _text(sidecar.get("id"), f"Skill {directory.name} id")
        if not RESOURCE_ID.fullmatch(resource_id):
            raise SharedKnowledgeError(f"canonical Skill has invalid stable ID: {resource_id}")
        state = _text(sidecar.get("state"), f"Skill {resource_id} state")
        if state not in {"active", "revoked"}:
            raise SharedKnowledgeError(f"canonical Skill {resource_id} state must be active or revoked")
        files = _skill_files(directory)
        skill_bytes = dict(files)["SKILL.md"]
        skill_text = skill_bytes.decode("utf-8")
        name, description = _parse_skill_text(skill_text)
        source_path = PurePosixPath("skills", directory.name).as_posix()
        parsed.append(
            CanonicalSkill(
                resource_id,
                name,
                description,
                state,
                source_path,
                revision_for(source_path),
                package_digest(files),
                files,
                skill_text,
            )
        )
    ids = [skill.id for skill in parsed]
    names = [skill.name for skill in parsed]
    if len(ids) != len(set(ids)):
        raise SharedKnowledgeError("canonical Skill IDs must be unique")
    if len(names) != len(set(names)):
        raise SharedKnowledgeError("canonical Skill names must be unique")
    return CanonicalCatalog(descriptor, source_commit, tuple(parsed))
