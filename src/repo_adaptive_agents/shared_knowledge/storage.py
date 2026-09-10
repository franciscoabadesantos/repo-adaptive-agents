"""User-scoped storage locations for disposable team-knowledge data."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Mapping


def user_cache_root(
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> Path:
    """Return the shared cache root without creating it."""
    environment = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    if override := environment.get("TEAM_KNOWLEDGE_HOME"):
        return Path(override).expanduser() / "cache"
    if (os.name if platform_name is None else platform_name) == "nt":
        base = Path(environment.get("LOCALAPPDATA", str(user_home / "AppData" / "Local")))
        return base.expanduser() / "team-knowledge" / "cache"
    base = Path(environment.get("XDG_CACHE_HOME", str(user_home / ".cache")))
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
