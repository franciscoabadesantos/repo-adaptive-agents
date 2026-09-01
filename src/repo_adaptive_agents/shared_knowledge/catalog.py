"""Repository-local storage and thin translation to the native catalog."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlparse

import repo_adaptive_agents.admission_control as native

from .content import KnowledgeContentError, KnowledgeItem, parse_item, render_item
from .events import EventLog


KNOWLEDGE_DIR = ".team-knowledge"
CONFIG_FILE = "config.json"
ITEMS_DIR = "items"
EVENTS_FILE = "events.jsonl"
RUNTIME_DIR = "runtime"
ITEM_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


class SharedKnowledgeError(ValueError):
    """Actionable user-facing error for the shared-knowledge workflow."""


@dataclass(frozen=True)
class KnowledgeConfig:
    organization: str
    team: str
    repository: str
    default_owner: str
    schema_version: int = 1

    def to_data(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "organization": self.organization,
            "team": self.team,
            "repository": self.repository,
            "default_owner": self.default_owner,
        }


def _git(root: Path, *arguments: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def find_repository(path: str | Path = ".") -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_dir():
        raise SharedKnowledgeError(f"repository path is not a directory: {candidate}")
    root = _git(candidate, "rev-parse", "--show-toplevel")
    if root is None:
        raise SharedKnowledgeError(f"not inside a Git repository: {candidate}")
    return Path(root).resolve()


def _remote_repository(root: Path) -> str:
    remote = _git(root, "remote", "get-url", "origin")
    if not remote:
        return root.name
    candidate = remote
    if "://" not in candidate and ":" in candidate:
        candidate = candidate.split(":", 1)[1]
    else:
        candidate = urlparse(candidate).path
    parts = [part for part in candidate.strip("/").split("/") if part]
    if parts:
        parts[-1] = parts[-1].removesuffix(".git")
    return "/".join(parts[-2:]) if len(parts) >= 2 else (parts[0] if parts else root.name)


def _default_owner(root: Path) -> str:
    return (
        _git(root, "config", "user.email")
        or _git(root, "config", "user.name")
        or getpass.getuser()
    )


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SharedKnowledgeError(f"config {field} must be a non-empty string")
    return value.strip()


def load_config(root: Path) -> KnowledgeConfig:
    path = root / KNOWLEDGE_DIR / CONFIG_FILE
    if not path.is_file():
        raise SharedKnowledgeError(f"team knowledge is not initialized; run 'team-knowledge init' in {root}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SharedKnowledgeError(f"cannot read {path.relative_to(root)}: {error}") from error
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise SharedKnowledgeError("config schema_version must be 1")
    allowed = {"schema_version", "organization", "team", "repository", "default_owner"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise SharedKnowledgeError(f"unsupported config field(s): {', '.join(unknown)}")
    return KnowledgeConfig(
        organization=_required_text(data.get("organization"), "organization"),
        team=_required_text(data.get("team"), "team"),
        repository=_required_text(data.get("repository"), "repository"),
        default_owner=_required_text(data.get("default_owner"), "default_owner"),
    )


def _ensure_local_ignores(target: Path) -> None:
    path = target / ".gitignore"
    if path.is_symlink():
        raise SharedKnowledgeError(f"team knowledge ignore file must not be a symlink: {path}")
    existing = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    required = (f"/{EVENTS_FILE}", f"/{RUNTIME_DIR}/")
    missing = [entry for entry in required if entry not in existing]
    if missing:
        content = "\n".join((*existing, *missing)).strip() + "\n"
        path.write_text(content, encoding="utf-8")


def initialize_repository(
    path: str | Path = ".",
    *,
    organization: str | None = None,
    team: str | None = None,
    repository: str | None = None,
    owner: str | None = None,
) -> Path:
    root = find_repository(path)
    target = root / KNOWLEDGE_DIR
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_dir():
            raise SharedKnowledgeError(f"cannot initialize because {target} already exists")
        existing = load_config(root)
        requested = {
            "organization": organization,
            "team": team,
            "repository": repository,
            "default_owner": owner,
        }
        conflicts = [
            field
            for field, value in requested.items()
            if value is not None
            and _required_text(value, field) != getattr(existing, field)
        ]
        if conflicts:
            raise SharedKnowledgeError(
                "team knowledge is already initialized with different " + ", ".join(conflicts)
            )
        _ensure_local_ignores(target)
        return target
    repository_id = _required_text(
        _remote_repository(root) if repository is None else repository,
        "repository",
    )
    default_team = repository_id.rsplit("/", 1)[-1]
    config = KnowledgeConfig(
        organization=_required_text("local" if organization is None else organization, "organization"),
        team=_required_text(default_team if team is None else team, "team"),
        repository=repository_id,
        default_owner=_required_text(_default_owner(root) if owner is None else owner, "default_owner"),
    )
    target.mkdir()
    items = target / ITEMS_DIR
    items.mkdir()
    (target / CONFIG_FILE).write_text(json.dumps(config.to_data(), indent=2) + "\n", encoding="utf-8")
    _ensure_local_ignores(target)
    (items / ".gitkeep").write_text("", encoding="utf-8")
    return target


class KnowledgeStore:
    def __init__(self, root: Path, config: KnowledgeConfig) -> None:
        self.root = root
        self.directory = root / KNOWLEDGE_DIR
        self.items_directory = self.directory / ITEMS_DIR
        self.config = config
        self.events = EventLog(self.directory / EVENTS_FILE, config.repository)

    def current_identity(self) -> str:
        """Use this checkout's Git identity, falling back to initialized configuration."""

        return (
            _git(self.root, "config", "user.email")
            or _git(self.root, "config", "user.name")
            or self.config.default_owner
        )

    def runtime_directory(self) -> Path:
        """Keep ephemeral exposure receipts writable but excluded from Git history."""

        ignore_path = self.directory / ".gitignore"
        try:
            ignored = ignore_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as error:
            raise SharedKnowledgeError(f"cannot verify local runtime ignore rule: {error}") from error
        if f"/{RUNTIME_DIR}/" not in ignored:
            raise SharedKnowledgeError(
                "team knowledge runtime is not ignored; run 'team-knowledge init' to update local safeguards"
            )
        return self.directory / RUNTIME_DIR

    @classmethod
    def open(cls, path: str | Path = ".") -> "KnowledgeStore":
        root = find_repository(path)
        config = load_config(root)
        items = root / KNOWLEDGE_DIR / ITEMS_DIR
        if not items.is_dir() or items.is_symlink():
            raise SharedKnowledgeError(f"knowledge items directory is missing: {items.relative_to(root)}")
        return cls(root, config)

    def item_files(self) -> tuple[Path, ...]:
        return tuple(sorted(self.items_directory.glob("*.md")))

    def load_items(self) -> tuple[KnowledgeItem, ...]:
        items: list[KnowledgeItem] = []
        errors: list[str] = []
        for path in self.item_files():
            try:
                if path.is_symlink() or not path.is_file():
                    raise KnowledgeContentError("item must be a regular Markdown file, not a symlink")
                item = parse_item(path, relative_to=self.root)
                if not ITEM_ID.fullmatch(item.id):
                    raise KnowledgeContentError(f"invalid item ID: {item.id}")
                if path.name != f"{item.id}.md":
                    raise KnowledgeContentError(f"filename must be {item.id}.md")
                items.append(item)
            except (OSError, KnowledgeContentError) as error:
                errors.append(f"{path.relative_to(self.root)}: {error}")
        ids: dict[str, Path] = {}
        for item in items:
            previous = ids.get(item.id)
            if previous is not None:
                errors.append(f"duplicate item ID {item.id}: {previous} and {item.path}")
            ids[item.id] = item.path
        if errors:
            raise SharedKnowledgeError("invalid team knowledge:\n- " + "\n- ".join(errors))
        return tuple(sorted(items, key=lambda item: item.id))

    def get(self, item_id: str) -> KnowledgeItem:
        if not ITEM_ID.fullmatch(item_id):
            raise SharedKnowledgeError(f"invalid knowledge item ID: {item_id}")
        path = self.items_directory / f"{item_id}.md"
        if not path.is_file() or path.is_symlink():
            raise SharedKnowledgeError(f"knowledge item not found: {item_id}")
        try:
            item = parse_item(path, relative_to=self.root)
        except KnowledgeContentError as error:
            raise SharedKnowledgeError(f"invalid team knowledge:\n- {path.relative_to(self.root)}: {error}") from error
        if item.id != item_id:
            raise SharedKnowledgeError(f"item ID {item.id} does not match filename {path.name}")
        return item

    def add(
        self,
        title: str,
        summary: str,
        body: str,
        *,
        owner: str | None = None,
        restricted: bool = False,
    ) -> KnowledgeItem:
        for _attempt in range(10):
            item_id = f"tk-{uuid.uuid4().hex[:12]}"
            path = self.items_directory / f"{item_id}.md"
            if not path.exists():
                break
        else:
            raise SharedKnowledgeError("could not generate a unique knowledge ID")
        item = KnowledgeItem(
            item_id,
            title,
            summary,
            owner or self.current_identity(),
            "active",
            "restricted" if restricted else "normal",
            1,
            body,
            path.relative_to(self.root),
        )
        rendered = render_item(item)
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
        self.events.append(
            "contribution_created",
            item.id,
            revision=str(item.revision),
            actor=item.owner,
        )
        return item

    def revoke(self, item_id: str, *, actor: str | None = None) -> KnowledgeItem:
        item = self.get(item_id)
        if item.state == "revoked":
            raise SharedKnowledgeError(f"knowledge item is already revoked: {item_id}")
        updated = replace(item, state="revoked", revision=item.revision + 1)
        destination = self.root / item.path
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(render_item(updated))
            os.replace(temporary_name, destination)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return updated

    def native_catalog(self) -> tuple[native.ResourceCatalog, tuple[KnowledgeItem, ...]]:
        items = self.load_items()
        records: list[native.ResourceRecord] = []
        for item in items:
            lifecycle = native.LifecycleState.APPROVED if item.state == "active" else native.LifecycleState.REVOKED
            payload = native.SharedKnowledgePayload(item.path.as_posix())
            content = native.build_content(
                item.id,
                str(item.revision),
                native.ResourceKind.SHARED_KNOWLEDGE,
                item.title,
                item.summary,
                item.body,
                payload,
            )
            records.append(
                native.ResourceRecord(
                    content,
                    native.AdmissionEnvelope(
                        lifecycle=native.Lifecycle(lifecycle),
                        scope=native.Scope(
                            organization=self.config.organization,
                            team=self.config.team,
                            repository=self.config.repository,
                        ),
                        compatibility=(),
                        dependencies=(),
                        exposure_policy=(
                            native.ExposurePolicy.REQUIRE_ADMISSIBLE
                            if item.exposure == "restricted"
                            else native.ExposurePolicy.ALLOW_WHEN_INADMISSIBLE
                        ),
                        selectable=True,
                    ),
                )
            )
        revision_input = "\n".join(
            f"{record.content.id}:{record.content.revision}:{record.content.payload_sha256}"
            for record in records
        )
        revision = "team-knowledge-" + hashlib.sha256(revision_input.encode("utf-8")).hexdigest()[:16]
        try:
            catalog = native.ResourceCatalog(revision, tuple(records)).validated()
        except native.CatalogError as error:
            raise SharedKnowledgeError(f"invalid team knowledge: {error}") from error
        return catalog, items
