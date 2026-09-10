"""Small Git-repository primitives used by the current Skill workflow."""

from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import urlparse


class SharedKnowledgeError(ValueError):
    """Actionable user-facing error for the current shared-Skill workflow."""


def git_output(root: Path, *arguments: str) -> str | None:
    """Return Git stdout when a read-only query succeeds and has output."""
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
    root = git_output(candidate, "rev-parse", "--show-toplevel")
    if root is None:
        raise SharedKnowledgeError(f"not inside a Git repository: {candidate}")
    return Path(root).resolve()


def repository_identity(root: Path) -> str:
    """Return the stable owner/repository identity derived from `origin`, if present."""
    remote = git_output(root, "remote", "get-url", "origin")
    if not remote:
        return root.name
    candidate = remote.split(":", 1)[1] if "://" not in remote and ":" in remote else urlparse(remote).path
    parts = [part for part in candidate.strip("/").split("/") if part]
    if parts:
        parts[-1] = parts[-1].removesuffix(".git")
    return "/".join(parts[-2:]) if len(parts) >= 2 else (parts[0] if parts else root.name)
