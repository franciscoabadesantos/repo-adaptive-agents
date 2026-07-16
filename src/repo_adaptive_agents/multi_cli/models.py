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
