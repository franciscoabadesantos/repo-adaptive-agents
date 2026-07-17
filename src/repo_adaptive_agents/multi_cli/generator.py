"""Render a canonical role into a deterministic, multi-target proposal.

The generator renders each requested target with its isolated renderer, assembles a
deterministic ``manifest.json`` (no variable timestamps), and writes everything atomically
to a fresh output directory outside any protected repository. It never writes to HOME,
never touches an existing ``.codex/config.toml``, and never makes network calls.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import CanonicalRole, InvocationScope, RenderedTarget
from .renderers import RENDERERS, TARGETS, renderer_versions
from .renderers.common import bullet_list
from .roles import ROLES
from repo_adaptive_agents import __version__

GENERATOR_VERSION = __version__
SCHEMA_VERSION = 2
MANIFEST_NAME = "manifest.json"

# Buckets are the first path segment of every generated file; used to map a proposal file
# back onto a real repository layout when comparing.
_TARGET_BUCKETS = {"skill": "portable", "codex": "codex", "claude": "claude", "copilot": "copilot"}
_SHARED_BUCKET = "shared"


class MultiCliError(ValueError):
    """Raised when a role proposal cannot be produced safely."""


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def resolve_targets(targets: list[str] | None) -> list[str]:
    """Validate and order requested targets deterministically.

    ``None`` means "all targets". Unknown or duplicate targets are rejected.
    """
    if targets is None:
        return list(TARGETS)
    seen: set[str] = set()
    for target in targets:
        if target not in RENDERERS:
            allowed = ", ".join(TARGETS)
            raise MultiCliError(f"Unknown target: {target!r}. Allowed targets: {allowed}")
        if target in seen:
            raise MultiCliError(f"Duplicate target: {target!r}")
        seen.add(target)
    # Preserve canonical order regardless of request order for determinism.
    return [target for target in TARGETS if target in seen]


def get_role_or_error(role_id: str) -> CanonicalRole:
    try:
        return ROLES[role_id]
    except KeyError:
        allowed = ", ".join(sorted(ROLES))
        raise MultiCliError(f"Unknown role: {role_id!r}. Allowed roles: {allowed}") from None


def _shared_fragment(role: CanonicalRole) -> str:
    return "\n".join(
        [
            f"<!-- Generated fragment for role: {role.id}. Guidance, not enforcement. -->",
            f"## {role.title}",
            "",
            role.purpose,
            "",
            "Constraints:",
            "",
            bullet_list(role.critical_constraints()),
            "",
        ]
    )


def _validate_scope_for_role(role: CanonicalRole, scope: InvocationScope | None) -> None:
    """Enforce the scope contract before any file is produced."""
    if role.constraints.require_explicit_scope and scope is None:
        raise MultiCliError(
            f"{role.id} requires an explicit invocation scope (at least one allowed path and a description)"
        )
    if scope is not None and role.constraints.read_only:
        raise MultiCliError(f"read-only role {role.id!r} does not accept an invocation scope")
    if scope is not None and not scope.allowed_paths:
        raise MultiCliError(f"{role.id} requires at least one allowed path in its scope")
    if scope is not None and not scope.description.strip():
        raise MultiCliError(f"{role.id} requires a non-empty scope description")


def render_role(
    role_id: str,
    targets: list[str] | None = None,
    scope: InvocationScope | None = None,
) -> tuple[dict[str, str], dict]:
    """Render a role for the requested targets.

    Returns ``(files, manifest)`` where ``files`` maps proposal-relative POSIX paths to
    content (including ``manifest.json``) and ``manifest`` is the manifest as a dict. A
    write role requires an explicit ``scope``; a read-only role must not be given one.
    """
    role = get_role_or_error(role_id)
    _validate_scope_for_role(role, scope)
    resolved = resolve_targets(targets)

    files: dict[str, str] = {}
    rendered: dict[str, RenderedTarget] = {}
    for target in resolved:
        result = RENDERERS[target].render(role, scope)
        rendered[target] = result
        files.update(result.files)

    shared_path = f"{_SHARED_BUCKET}/AGENTS.fragment.md"
    files[shared_path] = _shared_fragment(role)

    manifest = _build_manifest(role, resolved, rendered, files, shared_path)
    files[MANIFEST_NAME] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    return files, manifest


def _build_manifest(
    role: CanonicalRole,
    resolved: list[str],
    rendered: dict[str, RenderedTarget],
    files: dict[str, str],
    shared_path: str,
) -> dict:
    targets_section: dict[str, dict] = {}
    warnings: list[str] = []
    for target in resolved:
        result = rendered[target]
        targets_section[target] = {
            "status": "generated",
            "portability": result.portability,
            "renderer_version": result.renderer_version,
            "enforcement": result.enforcement,
            "files": [
                {"path": path, "sha256": _sha256(files[path])}
                for path in sorted(result.files)
            ],
            "semantic_mapping": result.semantic_mapping,
            "unsupported_fields": list(result.unsupported_fields),
            "warnings": list(result.warnings),
        }
        if result.artifacts:
            targets_section[target]["artifacts"] = {
                name: {"path": path, "sha256": _sha256(files[path])}
                for name, path in sorted(result.artifacts.items())
            }
        if result.scope_metadata:
            # Merge scope blocks (sandbox, write_scope, destructive_actions, …) as siblings.
            targets_section[target].update(result.scope_metadata)
        warnings.extend(result.warnings)

    return {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "canonical_role_id": role.id,
        "source": {"role_hash": role.source_hash()},
        "renderer_versions": renderer_versions(),
        "targets_requested": list(resolved),
        "targets": targets_section,
        "shared": {
            "files": [{"path": shared_path, "sha256": _sha256(files[shared_path])}],
        },
        "warnings": sorted(set(warnings)),
    }


def _assert_no_absolute_paths(files: dict[str, str]) -> None:
    for path in files:
        if Path(path).is_absolute() or path.startswith("/"):
            raise MultiCliError(f"Refusing to emit an absolute path: {path!r}")


def write_proposal(
    role_id: str,
    targets: list[str] | None,
    output_dir: str | Path,
    *,
    protected_root: str | Path | None = None,
    scope: InvocationScope | None = None,
) -> list[Path]:
    """Render a role and write an atomic proposal directory.

    ``protected_root`` (when given) must not contain ``output``; this preserves the
    "never write inside the analyzed repository" guarantee. The output must not already
    exist and is written atomically via a temporary sibling and ``os.replace``. A write
    role requires an explicit ``scope``; the scope is validated before anything is written.
    """
    files, _ = render_role(role_id, targets, scope)
    return write_files_atomically(output_dir, files, protected_root=protected_root)


def write_files_atomically(
    output_dir: str | Path,
    files: dict[str, str],
    *,
    protected_root: str | Path | None = None,
) -> list[Path]:
    """Write ``files`` (proposal-relative POSIX paths) atomically to a fresh output dir.

    Enforces the shared safety invariants: the output must be outside ``protected_root``,
    must not already exist, and must contain no absolute paths. Writes to a temporary
    sibling and renames into place, cleaning up on any failure.
    """
    output = Path(output_dir).expanduser().resolve()
    if protected_root is not None:
        root = Path(protected_root).expanduser().resolve()
        if output == root or output.is_relative_to(root):
            raise MultiCliError("Proposal output cannot be inside the protected repository")
    if output.exists() or output.is_symlink():
        raise MultiCliError(f"Proposal output already exists; refusing to overwrite: {output}")

    _assert_no_absolute_paths(files)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        for relative in sorted(files):
            path = temporary / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(files[relative], encoding="utf-8")
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return [output / relative for relative in sorted(files)]


@dataclass
class CompareReport:
    """Read-only comparison of a proposal against a destination repository."""

    additions: list[str]
    changes: list[str]
    unchanged: list[str]
    diff: str

    @property
    def conflicts(self) -> list[str]:
        """Changed files are potential conflicts; kept as a distinct accessor."""
        return list(self.changes)


def _repo_relative(proposal_relative: str) -> str | None:
    """Map a proposal file to its destination path by dropping the bucket segment.

    Returns ``None`` for files that do not correspond to a repository location
    (``manifest.json`` and the ``shared/`` fragment).
    """
    parts = Path(proposal_relative).parts
    if len(parts) < 2 or parts[0] in {_SHARED_BUCKET}:
        return None
    if parts[0] not in _TARGET_BUCKETS.values():
        return None
    return Path(*parts[1:]).as_posix()


def compare_proposal(proposal_dir: str | Path, compare_to: str | Path) -> CompareReport:
    """Compare a written proposal against a destination directory, strictly read-only."""
    proposal = Path(proposal_dir).expanduser().resolve()
    destination = Path(compare_to).expanduser().resolve()

    additions: list[str] = []
    changes: list[str] = []
    unchanged: list[str] = []
    diff_chunks: list[str] = []

    proposal_files = sorted(path for path in proposal.rglob("*") if path.is_file())
    for path in proposal_files:
        relative = path.relative_to(proposal).as_posix()
        repo_relative = _repo_relative(relative)
        if repo_relative is None:
            continue
        target_file = destination / repo_relative
        new_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        if target_file.is_file():
            old_lines = target_file.read_text(encoding="utf-8").splitlines(keepends=True)
            if old_lines == new_lines:
                unchanged.append(repo_relative)
                continue
            changes.append(repo_relative)
            fromfile, tofile = f"a/{repo_relative}", f"b/{repo_relative}"
        else:
            additions.append(repo_relative)
            old_lines, fromfile, tofile = [], "/dev/null", f"b/{repo_relative}"
        kind = "add" if not target_file.is_file() else "change/conflict"
        diff_chunks.append(f"# {kind}: {repo_relative}\n")
        diff_chunks.extend(difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile))

    return CompareReport(
        additions=sorted(additions),
        changes=sorted(changes),
        unchanged=sorted(unchanged),
        diff="".join(diff_chunks),
    )
