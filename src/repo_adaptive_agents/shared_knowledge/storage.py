"""User-scoped storage for persistent canonical replicas and disposable runtime data."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from .repository import SharedKnowledgeError


def user_cache_root(
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> Path:
    """Return the previous cache root, used only for safe replica migration."""
    environment = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    if override := environment.get("TEAM_KNOWLEDGE_HOME"):
        return Path(override).expanduser() / "cache"
    if (os.name if platform_name is None else platform_name) == "nt":
        base = Path(environment.get("LOCALAPPDATA", str(user_home / "AppData" / "Local")))
        return base.expanduser() / "team-knowledge" / "cache"
    base = Path(environment.get("XDG_CACHE_HOME", str(user_home / ".cache")))
    return base.expanduser() / "team-knowledge"


def user_data_root(
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> Path:
    """Return the persistent machine data root without creating it."""
    environment = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    if override := environment.get("TEAM_KNOWLEDGE_HOME"):
        return Path(override).expanduser() / "data"
    if (os.name if platform_name is None else platform_name) == "nt":
        base = Path(environment.get("LOCALAPPDATA", str(user_home / "AppData" / "Local")))
        return base.expanduser() / "team-knowledge" / "data"
    base = Path(environment.get("XDG_DATA_HOME", str(user_home / ".local" / "share")))
    return base.expanduser() / "team-knowledge"


def source_identity(source_url: str, consumer_root: Path) -> str:
    """Build a stable local identity without exposing the source in directory names."""
    source = source_url.strip()
    is_scp_like = ":" in source and not source.startswith(("./", "../"))
    has_scheme = "://" in source
    if not has_scheme and not is_scp_like:
        resolved = (consumer_root / source).resolve(strict=False)
        return f"local:{resolved.as_posix()}"
    return f"git:{source}"


def clone_source(source_url: str, consumer_root: Path) -> str:
    """Resolve local sources for a cache that can be shared by differently nested consumers."""
    identity = source_identity(source_url, consumer_root)
    return identity.removeprefix("local:") if identity.startswith("local:") else source_url.strip()


def source_cache_directory(
    source_url: str,
    consumer_root: Path,
    *,
    root: Path | None = None,
) -> Path:
    identity = source_identity(source_url, consumer_root)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return (user_cache_root() if root is None else root) / "sources" / digest


def source_replica_directory(
    source_url: str,
    consumer_root: Path,
    *,
    root: Path | None = None,
) -> Path:
    """Return the durable local-replica directory for one canonical source."""
    identity = source_identity(source_url, consumer_root)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return (user_data_root() if root is None else root) / "sources" / digest


def source_registry_path(*, root: Path | None = None) -> Path:
    return (user_data_root() if root is None else root) / "sources.json"


def registered_source_checkout(
    source_url: str,
    consumer_root: Path,
    *,
    root: Path | None = None,
) -> Path | None:
    path = source_registry_path(root=root)
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise SharedKnowledgeError("canonical source registry must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SharedKnowledgeError("canonical source registry is invalid") from error
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("sources"), dict):
        raise SharedKnowledgeError("canonical source registry must be a schema version 1 object")
    key = source_replica_directory(source_url, consumer_root, root=Path(".")).name
    raw = value["sources"].get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or not Path(raw).is_absolute():
        raise SharedKnowledgeError("registered canonical checkout path is invalid")
    return Path(raw)


def register_source_checkout(
    source_url: str,
    consumer_root: Path,
    checkout: Path,
    *,
    root: Path | None = None,
) -> Path:
    """Register an existing canonical clone as machine-local persistent state."""
    resolved = checkout.resolve(strict=True)
    if not (resolved / ".git").is_dir():
        raise SharedKnowledgeError("registered canonical checkout must be a Git working repository")
    path = source_registry_path(root=root)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise SharedKnowledgeError("canonical source registry must be a regular file")
    sources: dict[str, str] = {}
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SharedKnowledgeError("canonical source registry is invalid") from error
        if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("sources"), dict):
            raise SharedKnowledgeError("canonical source registry must be a schema version 1 object")
        if any(not isinstance(key, str) or not isinstance(item, str) for key, item in value["sources"].items()):
            raise SharedKnowledgeError("canonical source registry entries are invalid")
        sources.update(value["sources"])
    key = source_replica_directory(source_url, consumer_root, root=Path(".")).name
    sources[key] = str(resolved)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps({"schema_version": 1, "sources": sources}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
