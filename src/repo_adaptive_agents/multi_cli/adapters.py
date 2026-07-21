"""Explicit adapter selection from a portable infrastructure plan."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import InfrastructurePlan
from .roles import IMPLEMENTATION_AGENT, ROLES


class AdapterSelectionError(ValueError):
    """Raised when an adapter selection is unknown, unsafe, or empty."""


@dataclass(frozen=True)
class AdapterSelection:
    role_id: str
    matched_available_roles: tuple[str, ...]
    matched_capabilities: tuple[str, ...]


@dataclass(frozen=True)
class AdapterPlan:
    """Adapters selected by the user; this is not an execution plan."""

    selected_adapters: tuple[AdapterSelection, ...]
    eligible_role_ids: tuple[str, ...]
    unmapped_available_roles: tuple[str, ...]
    assumptions: tuple[str, ...]

    @property
    def selected_ids(self) -> tuple[str, ...]:
        return tuple(item.role_id for item in self.selected_adapters)


def _matches(plan: InfrastructurePlan, role_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    canonical_capabilities = set(ROLES[role_id].capabilities)
    role_names: list[str] = []
    capabilities: set[str] = set()
    for available in plan.available_roles:
        overlap = canonical_capabilities.intersection(available.capabilities)
        if overlap:
            role_names.append(available.name)
            capabilities.update(overlap)
    return tuple(role_names), tuple(sorted(capabilities))


def select_adapters(
    plan: InfrastructurePlan,
    requested_role_ids: list[str] | tuple[str, ...],
) -> AdapterPlan:
    """Validate an explicit selection and explain its connection to the plan.

    A canonical read-only role may be selected even when no deterministic capability match
    exists. That records a human choice rather than pretending the profiler inferred it.
    """
    requested = set(requested_role_ids)
    if not requested:
        raise AdapterSelectionError("At least one explicit adapter role is required")
    unknown = sorted(requested.difference(ROLES))
    if unknown:
        raise AdapterSelectionError(f"Unknown adapter role(s): {', '.join(unknown)}")
    if IMPLEMENTATION_AGENT.id in requested:
        raise AdapterSelectionError(
            "implementation_agent requires an explicit write scope; use render-role directly"
        )

    matches = {role_id: _matches(plan, role_id) for role_id in ROLES if role_id != IMPLEMENTATION_AGENT.id}
    eligible = tuple(role_id for role_id in ROLES if matches.get(role_id, ((), ()))[0])
    selected = tuple(
        AdapterSelection(role_id, *matches[role_id])
        for role_id in ROLES
        if role_id in requested
    )
    mapped_available = {
        name
        for role_names, _capabilities in matches.values()
        for name in role_names
    }
    unmapped = tuple(
        role.name for role in plan.available_roles if role.name not in mapped_available
    )
    return AdapterPlan(
        selected_adapters=selected,
        eligible_role_ids=eligible,
        unmapped_available_roles=unmapped,
        assumptions=(
            "Adapters were selected explicitly; no role is mandatory or automatically invoked.",
            "Capability matches explain availability but do not define execution order or concurrency.",
            "A selected adapter without a capability match is an explicit human choice.",
        ),
    )
