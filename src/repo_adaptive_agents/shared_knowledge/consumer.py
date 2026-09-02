"""Committed consumer config/lock state and exact local Git exclusions."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from repo_adaptive_agents.shared_knowledge.catalog import SharedKnowledgeError, _git


STATE_DIR = ".team-knowledge"
CONFIG_FILE = "config.json"
LOCK_FILE = "lock.json"
IGNORE_CONTENT = "/events.jsonl\n/runtime/\n/cache/\n"
EXCLUDE_BEGIN = "# BEGIN team-knowledge managed Skills"
EXCLUDE_END = "# END team-knowledge managed Skills"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DEFAULT_SOURCE_URL = "git@github.com:franciscoabadesantos/repo-adaptive-agents.git"
DEFAULT_SOURCE_REF = "main"
DEFAULT_CATALOG_PATH = "team-knowledge"


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SharedKnowledgeError(f"{field} must be a non-empty string")
    return value.strip()


def _object(value: object, field: str, allowed: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SharedKnowledgeError(f"{field} must be an object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise SharedKnowledgeError(f"unsupported {field} field(s): {', '.join(unknown)}")
    return value


def validate_source_url(value: str) -> str:
    source = _text(value, "source URL")
    parsed = urlparse(source)
    if parsed.scheme == "file" or (not parsed.scheme and not (":" in source and not source.startswith("./")) and Path(source).is_absolute()):
        raise SharedKnowledgeError(
            "absolute local source paths are not stored; use a Git URL or a relative repository path"
        )
    return source


def validate_catalog_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SharedKnowledgeError("catalog path must be a non-empty relative POSIX path")
    raw = value.strip()
    if raw == ".":
        return raw
    path = PurePosixPath(raw)
    if "\\" in raw or path.is_absolute() or ".." in path.parts or path.as_posix() != raw:
        raise SharedKnowledgeError("catalog path must be '.' or a normalized relative POSIX path")
    return raw


@dataclass(frozen=True)
class ConsumerSource:
    url: str
    ref: str
    catalog_path: str = "."
    type: str = "git"

    def to_data(self) -> dict[str, str]:
        return {
            "type": self.type,
            "url": self.url,
            "ref": self.ref,
            "catalog_path": self.catalog_path,
        }


def default_consumer_source(ref: str = DEFAULT_SOURCE_REF) -> ConsumerSource:
    return ConsumerSource(DEFAULT_SOURCE_URL, _text(ref, "source ref"), DEFAULT_CATALOG_PATH)


def external_consumer_source(url: str, ref: str = DEFAULT_SOURCE_REF) -> ConsumerSource:
    return ConsumerSource(validate_source_url(url), _text(ref, "source ref"), ".")


@dataclass(frozen=True)
class ConsumerConfig:
    repository: str
    source: ConsumerSource
    schema_version: int = 2
    mode: str = "consumer"
    target: str = "codex"

    def to_data(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "repository": self.repository,
            "target": self.target,
            "source": self.source.to_data(),
        }


@dataclass(frozen=True)
class LockedResource:
    source_id: str
    source_url: str
    source_ref: str
    resolved_source_commit: str
    id: str
    name: str
    source_path: str
    revision: str
    digest_sha256: str
    materialized_path: str
    repository_evidence_sha256: str
    source_catalog_path: str = "."

    def to_data(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "source_url": self.source_url,
            "source_ref": self.source_ref,
            "source_catalog_path": self.source_catalog_path,
            "resolved_source_commit": self.resolved_source_commit,
            "id": self.id,
            "name": self.name,
            "source_path": self.source_path,
            "revision": self.revision,
            "digest_sha256": self.digest_sha256,
            "materialized_path": self.materialized_path,
            "repository_evidence_sha256": self.repository_evidence_sha256,
        }


@dataclass(frozen=True)
class ConsumerLock:
    source_id: str
    source_url: str
    source_ref: str
    resolved_commit: str
    repository_id: str
    evidence_sha256: str
    evaluated_source_commit: str
    evaluated_evidence_sha256: str
    resources: tuple[LockedResource, ...]
    catalog_path: str = "."
    schema_version: int = 1

    def to_data(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source": {
                "source_id": self.source_id,
                "url": self.source_url,
                "ref": self.source_ref,
                "catalog_path": self.catalog_path,
                "resolved_commit": self.resolved_commit,
            },
            "repository": {"id": self.repository_id, "evidence_sha256": self.evidence_sha256},
            "selection": {
                "evaluated_source_commit": self.evaluated_source_commit,
                "evidence_sha256": self.evaluated_evidence_sha256,
            },
            "resources": [resource.to_data() for resource in self.resources],
        }


def ensure_consumer_layout(root: Path) -> Path:
    state = root / STATE_DIR
    if state.is_symlink():
        raise SharedKnowledgeError(".team-knowledge must not be a symlink")
    state.mkdir(exist_ok=True)
    ignore = state / ".gitignore"
    if ignore.is_symlink() or (ignore.exists() and not ignore.is_file()):
        raise SharedKnowledgeError(".team-knowledge/.gitignore must be a regular file")
    existing = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
    required = IGNORE_CONTENT.splitlines()
    missing = [line for line in required if line not in existing]
    if missing:
        _atomic_text(ignore, "\n".join((*existing, *missing)).strip() + "\n")
    return state


def assert_bootstrap_available(root: Path) -> None:
    config = root / STATE_DIR / CONFIG_FILE
    lock = root / STATE_DIR / LOCK_FILE
    if config.exists() or lock.exists():
        if config.is_file():
            try:
                data = json.loads(config.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                data = None
            if isinstance(data, dict) and data.get("schema_version") == 2 and data.get("mode") == "consumer":
                raise SharedKnowledgeError(
                    "team knowledge is already bootstrapped; run 'team-knowledge sync' instead"
                )
        raise SharedKnowledgeError(
            "existing .team-knowledge state is not a cross-repository consumer; refusing to overwrite it"
        )
    items = root / STATE_DIR / "items"
    if items.exists():
        raise SharedKnowledgeError(
            "existing repo-local team knowledge is present; cross-repository bootstrap will not replace it"
        )


def load_consumer_config(root: Path) -> ConsumerConfig:
    data = _load_json(root / STATE_DIR / CONFIG_FILE, "consumer config")
    data = _object(data, "consumer config", frozenset({"schema_version", "mode", "repository", "target", "source"}))
    if data.get("schema_version") != 2 or data.get("mode") != "consumer" or data.get("target") != "codex":
        raise SharedKnowledgeError("consumer config must be schema version 2, consumer mode, Codex target")
    source = _object(
        data.get("source"),
        "consumer source",
        frozenset({"type", "url", "ref", "catalog_path"}),
    )
    if source.get("type") != "git":
        raise SharedKnowledgeError("consumer source type must be git")
    return ConsumerConfig(
        _text(data.get("repository"), "consumer repository"),
        ConsumerSource(
            validate_source_url(_text(source.get("url"), "source URL")),
            _text(source.get("ref"), "source ref"),
            validate_catalog_path(source.get("catalog_path", ".")),
        ),
    )


def load_consumer_lock(root: Path) -> ConsumerLock:
    data = _load_json(root / STATE_DIR / LOCK_FILE, "consumer lock")
    data = _object(data, "consumer lock", frozenset({"schema_version", "source", "repository", "selection", "resources"}))
    if data.get("schema_version") != 1:
        raise SharedKnowledgeError("consumer lock schema_version must be 1")
    source = _object(
        data.get("source"),
        "lock source",
        frozenset({"source_id", "url", "ref", "catalog_path", "resolved_commit"}),
    )
    repository = _object(data.get("repository"), "lock repository", frozenset({"id", "evidence_sha256"}))
    selection = _object(data.get("selection"), "lock selection", frozenset({"evaluated_source_commit", "evidence_sha256"}))
    raw_resources = data.get("resources")
    if not isinstance(raw_resources, list):
        raise SharedKnowledgeError("lock resources must be an array")
    resources: list[LockedResource] = []
    allowed = frozenset({
        "source_id", "source_url", "source_ref", "source_catalog_path", "resolved_source_commit", "id", "name",
        "source_path", "revision", "digest_sha256", "materialized_path", "repository_evidence_sha256",
    })
    for raw in raw_resources:
        item = _object(raw, "locked resource", allowed)
        resource = LockedResource(
            source_id=_text(item.get("source_id"), "locked resource source_id"),
            source_url=_text(item.get("source_url"), "locked resource source_url"),
            source_ref=_text(item.get("source_ref"), "locked resource source_ref"),
            resolved_source_commit=_text(
                item.get("resolved_source_commit"), "locked resource resolved_source_commit"
            ),
            id=_text(item.get("id"), "locked resource id"),
            name=_text(item.get("name"), "locked resource name"),
            source_path=_text(item.get("source_path"), "locked resource source_path"),
            revision=_text(item.get("revision"), "locked resource revision"),
            digest_sha256=_text(item.get("digest_sha256"), "locked resource digest_sha256"),
            materialized_path=_text(item.get("materialized_path"), "locked resource materialized_path"),
            repository_evidence_sha256=_text(
                item.get("repository_evidence_sha256"),
                "locked resource repository_evidence_sha256",
            ),
            source_catalog_path=validate_catalog_path(item.get("source_catalog_path", ".")),
        )
        validate_source_url(resource.source_url)
        if not _SKILL_NAME.fullmatch(resource.name):
            raise SharedKnowledgeError(f"locked resource has invalid Skill name: {resource.name}")
        if resource.source_path.count("/") != 1 or not resource.source_path.startswith("skills/"):
            raise SharedKnowledgeError(f"locked resource has unsafe source path: {resource.source_path}")
        if resource.materialized_path != f".agents/skills/{resource.name}":
            raise SharedKnowledgeError(f"locked resource has unsafe materialized path: {resource.materialized_path}")
        if not _GIT_REVISION.fullmatch(resource.revision):
            raise SharedKnowledgeError(f"locked resource has invalid Git revision: {resource.id}")
        if not _GIT_REVISION.fullmatch(resource.resolved_source_commit):
            raise SharedKnowledgeError(f"locked resource has invalid source commit: {resource.id}")
        if not _SHA256.fullmatch(resource.digest_sha256) or not _SHA256.fullmatch(resource.repository_evidence_sha256):
            raise SharedKnowledgeError(f"locked resource has invalid digest: {resource.id}")
        resources.append(resource)
    ids = [item.id for item in resources]
    paths = [item.materialized_path for item in resources]
    if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
        raise SharedKnowledgeError("locked resource IDs and materialized paths must be unique")
    lock = ConsumerLock(
        _text(source.get("source_id"), "lock source_id"),
        validate_source_url(_text(source.get("url"), "lock source URL")),
        _text(source.get("ref"), "lock source ref"),
        _text(source.get("resolved_commit"), "lock resolved commit"),
        _text(repository.get("id"), "lock repository id"),
        _text(repository.get("evidence_sha256"), "lock repository evidence digest"),
        _text(selection.get("evaluated_source_commit"), "lock evaluated source commit"),
        _text(selection.get("evidence_sha256"), "lock selection evidence digest"),
        tuple(resources),
        validate_catalog_path(source.get("catalog_path", ".")),
    )
    if not _GIT_REVISION.fullmatch(lock.resolved_commit) or not _GIT_REVISION.fullmatch(lock.evaluated_source_commit):
        raise SharedKnowledgeError("consumer lock contains an invalid Git commit")
    if not _SHA256.fullmatch(lock.evidence_sha256) or not _SHA256.fullmatch(lock.evaluated_evidence_sha256):
        raise SharedKnowledgeError("consumer lock contains an invalid evidence digest")
    if any(resource.repository_evidence_sha256 != lock.evidence_sha256 for resource in lock.resources):
        raise SharedKnowledgeError("locked resource evidence digest does not match repository lock")
    if any(
        (
            resource.source_id,
            resource.source_url,
            resource.source_ref,
            resource.source_catalog_path,
            resource.resolved_source_commit,
        )
        != (
            lock.source_id,
            lock.source_url,
            lock.source_ref,
            lock.catalog_path,
            lock.resolved_commit,
        )
        for resource in lock.resources
    ):
        raise SharedKnowledgeError("locked resource source provenance does not match repository lock")
    return lock


def _load_json(path: Path, label: str) -> object:
    if path.is_symlink() or not path.is_file():
        raise SharedKnowledgeError(f"{label} is missing or unsafe: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SharedKnowledgeError(f"cannot read {label}: {error}") from error


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            Path(temporary).unlink()
        except FileNotFoundError:
            pass
        raise


def write_json_atomic(path: Path, value: dict[str, object]) -> None:
    _atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def git_exclude_path(root: Path) -> Path:
    raw = _git(root, "rev-parse", "--git-path", "info/exclude")
    if raw is None:
        raise SharedKnowledgeError("cannot locate local Git exclude file")
    path = Path(raw)
    resolved = path if path.is_absolute() else root / path
    if resolved.is_symlink() or (resolved.exists() and not resolved.is_file()):
        raise SharedKnowledgeError("local Git exclude path must be a regular file")
    return resolved


def managed_exclude_content(existing: str, materialized_paths: tuple[str, ...]) -> str:
    lines = existing.splitlines()
    begin = [index for index, line in enumerate(lines) if line == EXCLUDE_BEGIN]
    end = [index for index, line in enumerate(lines) if line == EXCLUDE_END]
    if len(begin) != len(end) or len(begin) > 1 or (begin and begin[0] >= end[0]):
        raise SharedKnowledgeError("local Git exclude has a malformed team-knowledge managed block")
    block = [EXCLUDE_BEGIN, *(f"/{path.strip('/')}/" for path in sorted(materialized_paths)), EXCLUDE_END]
    if begin:
        lines[begin[0] : end[0] + 1] = block
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(block)
    return "\n".join(lines).rstrip() + "\n"
