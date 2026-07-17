"""Canonical, tool-agnostic model for a multi-CLI role.

The canonical model deliberately contains no Codex-, Claude-, or Copilot-specific
fields. Renderers translate this shared description into each tool's format; runtime
semantics that have no cross-tool equivalent live in the renderers and manifest, never
here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class RoleConstraints:
    """Safety boundaries the role must respect. These are declarative, not enforcement."""

    read_only: bool
    allow_network: bool
    allow_commit: bool
    allow_push: bool
    allow_deploy: bool
    allowed_paths: tuple[str, ...] = ()
    blocked_paths: tuple[str, ...] = ()
    additional_rules: tuple[str, ...] = ()
    # Deliberately no allow_edit/allow_create: writing is governed by read_only plus an
    # explicit invocation scope, not by a boolean the wrapper cannot enforce.
    allow_delete: bool = False
    require_explicit_scope: bool = False
    require_validation: bool = False


@dataclass(frozen=True)
class InvocationScope:
    """An explicit, advisory write scope supplied at render time.

    The scope is not part of the canonical role definition and never changes the role's
    canonical hash. Paths are lexically normalized, repo-relative POSIX strings.
    """

    description: str
    allowed_paths: tuple[str, ...]
    blocked_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class DelegationPolicy:
    """How an orchestrator may schedule and compose this role."""

    parallelizable: bool
    recursive_delegation: bool
    consolidation_required: bool
    recommended_concurrency: int


@dataclass(frozen=True)
class RuntimePreferences:
    """Advisory preferences. Concrete runtime knobs are target-specific and not set here."""

    reasoning_intensity: str
    context_isolation_preferred: bool
    sandbox_preferred: bool


@dataclass(frozen=True)
class CanonicalRole:
    """A single, source-of-truth description of a role, independent of any CLI."""

    id: str
    slug: str
    title: str
    description: str
    purpose: str
    capabilities: tuple[str, ...]
    when_to_use: tuple[str, ...]
    procedure: tuple[str, ...]
    response_format: tuple[str, ...]
    constraints: RoleConstraints
    evidence_requirements: tuple[str, ...]
    delegation: DelegationPolicy
    runtime_preferences: RuntimePreferences
    source_evidence: tuple[str, ...] = ()

    def critical_constraints(self) -> tuple[str, ...]:
        """Human-readable constraints preserved verbatim in every wrapper."""
        rules: list[str] = []
        if self.constraints.read_only:
            rules.append("Do not edit, create, or delete files.")
        if not self.constraints.allow_commit:
            rules.append("Do not commit.")
        if not self.constraints.allow_push:
            rules.append("Do not push.")
        if not self.constraints.allow_deploy:
            rules.append("Do not deploy.")
        if not self.constraints.allow_network:
            rules.append("Do not access the network or external systems.")
        rules.extend(self.constraints.additional_rules)
        if not self.delegation.recursive_delegation:
            rules.append("Do not delegate recursively or spawn further agents.")
        return tuple(rules)

    def canonical_json(self) -> str:
        """Deterministic serialization used for source hashing."""
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)

    def source_hash(self) -> str:
        """Stable SHA-256 of the canonical content; changes only when the role changes."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RenderedTarget:
    """The output of a single renderer for a single target.

    ``files`` maps proposal-relative POSIX paths to file content. ``portability`` is one
    of ``portable``, ``generated``, or ``target_specific``.
    """

    target: str
    renderer_version: str
    portability: str
    files: dict[str, str]
    semantic_mapping: dict[str, str] = field(default_factory=dict)
    unsupported_fields: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    # Declares whether the wrapper generates real runtime controls or only advisory prose.
    # ``mode`` is ``advisory`` or ``sandboxed``; ``controls`` lists generated control fields.
    enforcement: dict = field(default_factory=lambda: {"mode": "advisory", "runtime_controls_generated": False})
    # Optional named artifacts for targets that emit more than one file, such as the
    # Codex agent wrapper and its manual registration fragment.
    artifacts: dict[str, str] = field(default_factory=dict)
    # Optional per-target invocation-scope metadata (sandbox, write_scope, destructive
    # actions, validation, path_validation). Merged into the manifest target section when
    # a write role is rendered with an explicit scope. Empty for read-only roles.
    scope_metadata: dict = field(default_factory=dict)
