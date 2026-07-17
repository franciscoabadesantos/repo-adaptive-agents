"""Lexical construction and validation of an :class:`InvocationScope`.

Validation here is purely lexical: paths are normalized to repo-relative POSIX strings and
rejected on unsafe forms. This phase deliberately does not touch the filesystem — no
symlink resolution, no working-tree inspection, no submodule detection. Non-existent paths
are allowed. The manifest declares these limitations explicitly.
"""

from __future__ import annotations

from .models import InvocationScope


class ScopeError(ValueError):
    """Raised when a scope path is lexically unsafe or a required scope field is missing."""


def normalize_path(raw: str) -> str:
    """Return a repo-relative POSIX path, or raise :class:`ScopeError`.

    Rejects absolute paths, ``..`` components, empty paths, ``.``, NUL bytes, backslashes
    (ambiguous separators), and anything under ``.git``. Collapses duplicate slashes,
    drops ``.`` components, and strips trailing slashes.
    """
    if raw is None:
        raise ScopeError("path must not be None")
    if "\x00" in raw:
        raise ScopeError("path must not contain a NUL byte")
    if "\\" in raw:
        raise ScopeError(f"ambiguous backslash in path: {raw!r}")
    stripped = raw.strip()
    if not stripped:
        raise ScopeError("path must not be empty")
    if stripped.startswith("/"):
        raise ScopeError(f"absolute paths are not allowed: {raw!r}")

    cleaned: list[str] = []
    for part in stripped.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ScopeError(f"parent traversal '..' is not allowed: {raw!r}")
        cleaned.append(part)

    if not cleaned:
        raise ScopeError(f"path resolves to the repository root: {raw!r}")
    if cleaned[0] == ".git":
        raise ScopeError(f"paths under .git are not allowed: {raw!r}")
    return "/".join(cleaned)


def _normalize_all(paths: list[str]) -> tuple[str, ...]:
    """Normalize, de-duplicate, and deterministically sort a list of paths."""
    return tuple(sorted({normalize_path(path) for path in paths}))


def build_scope(
    description: str,
    allow_paths: list[str],
    block_paths: list[str] | None = None,
) -> InvocationScope:
    """Build a validated, deterministic :class:`InvocationScope`.

    ``allowed_paths`` and ``blocked_paths`` are normalized, de-duplicated, and sorted, so
    the order the user supplied them in never affects the output. ``blocked_paths`` always
    override ``allowed_paths`` semantically; both lists are preserved in full.
    """
    if not description or not description.strip():
        raise ScopeError("scope description must not be empty")
    if not allow_paths:
        raise ScopeError("scope requires at least one allowed path")
    return InvocationScope(
        description=description.strip(),
        allowed_paths=_normalize_all(allow_paths),
        blocked_paths=_normalize_all(block_paths or []),
    )
