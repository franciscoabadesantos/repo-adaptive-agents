"""Deterministic team recommendation on top of the existing repository profile.

This module maps a :class:`RepoProfile` (produced by the deterministic profiler) onto a
canonical, read-only multi-CLI team using explicit rules. It never uses an LLM, never runs
agents, and never recommends the write role ``implementation_agent`` automatically. Design
tooling signals are the only supplemental detection here (Storybook, a CSS framework
config, or design-token files); language and framework detection are reused from the
profiler and never duplicated.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..models import RepoProfile
from ..profiler import IGNORED_DIRS
from .roles import ROLES

# Canonical role ids.
REPO_EXPLORER = "repo_explorer"
API_CONTRACT_AGENT = "api_contract_agent"
BROWSER_QA = "browser_qa"
ACCESSIBILITY_PERFORMANCE_REVIEWER = "accessibility_performance_reviewer"
DESIGN_DIRECTOR = "design_director"
INDEPENDENT_REVIEWER = "independent_reviewer"
IMPLEMENTATION_AGENT = "implementation_agent"

# Fixed selection/serialization order for every specialized role plus the consolidator.
CANONICAL_TEAM_ORDER = (
    REPO_EXPLORER,
    API_CONTRACT_AGENT,
    BROWSER_QA,
    ACCESSIBILITY_PERFORMANCE_REVIEWER,
    DESIGN_DIRECTOR,
    INDEPENDENT_REVIEWER,
)
# Specialized roles whose count decides whether a consolidator is added.
SPECIALIZED_ROLES = (API_CONTRACT_AGENT, BROWSER_QA, ACCESSIBILITY_PERFORMANCE_REVIEWER, DESIGN_DIRECTOR)


class TeamError(ValueError):
    """Raised on an invalid team request (unknown/ineligible role, bad options)."""


@dataclass(frozen=True)
class RoleRecommendation:
    role_id: str
    reasons: tuple[str, ...]
    evidence: tuple[str, ...]
    confidence: str


@dataclass(frozen=True)
class TeamPlan:
    selected_roles: tuple[RoleRecommendation, ...]
    excluded_roles: tuple[RoleRecommendation, ...]
    parallel_groups: tuple[tuple[str, ...], ...]
    consolidator: str | None
    warnings: tuple[str, ...]

    @property
    def selected_ids(self) -> tuple[str, ...]:
        return tuple(item.role_id for item in self.selected_roles)


# --- Supplemental design-tooling detection (filenames only, deterministic) --------------


def _iter_repo(repo_root: Path):
    """Yield (relative_dir_posix, dirnames, filenames), pruning ignored directories."""
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        rel = Path(dirpath).relative_to(repo_root).as_posix()
        yield ("" if rel == "." else rel), dirnames, sorted(filenames)


def _is_tailwind_config(name: str) -> bool:
    return name in {f"tailwind.config.{ext}" for ext in ("js", "cjs", "mjs", "ts")}


def _is_design_token_file(name: str) -> bool:
    return name.endswith(".tokens.json") or name in {"design-tokens.json", "tokens.css", "tokens.scss"}


def detect_design_signals(repo_root: str | Path) -> list[tuple[str, str]]:
    """Return sorted ``(label, repo-relative-path)`` design markers found lexically.

    Markers are intentionally strong and unambiguous: a ``.storybook`` directory, a
    ``tailwind.config.*`` file, a ``design-tokens`` directory, or a design-token file.
    """
    root = Path(repo_root)
    found: list[tuple[str, str]] = []
    for rel, dirnames, filenames in _iter_repo(root):
        for dirname in dirnames:
            marker_path = f"{rel}/{dirname}" if rel else dirname
            if dirname == ".storybook":
                found.append(("storybook", marker_path))
            elif dirname == "design-tokens":
                found.append(("design_tokens", marker_path))
        for name in filenames:
            marker_path = f"{rel}/{name}" if rel else name
            if _is_tailwind_config(name):
                found.append(("css_framework", marker_path))
            elif _is_design_token_file(name):
                found.append(("design_tokens", marker_path))
    return sorted(set(found), key=lambda item: (item[1], item[0]))


# --- Recommendation rules ---------------------------------------------------------------


def _profile_has_signal(profile: RepoProfile) -> bool:
    """Whether the profile carries any structural signal (i.e. the repo is not empty)."""
    return bool(
        profile.manifests
        or profile.frameworks
        or profile.architecture.entrypoints
        or (profile.project_types and profile.project_types != ["unknown"])
    )


def _evidence_for(profile: RepoProfile, project_type: str) -> tuple[str, ...]:
    """Deterministic, repo-relative evidence for a project-type-driven rule."""
    paths = list(profile.manifests) + list(profile.architecture.entrypoints)
    return tuple(sorted(set(paths))) or (f"project_type:{project_type}",)


def recommend_team(
    profile: RepoProfile,
    repo_root: str | Path,
    *,
    include_roles: list[str] | None = None,
    exclude_roles: list[str] | None = None,
) -> TeamPlan:
    """Produce a deterministic :class:`TeamPlan` from a repository profile.

    ``include_roles`` may force read-only roles that lack a signal; ``exclude_roles`` drops
    roles from the selection. Order of includes/excludes never affects the output.
    """
    include = _validate_option_roles(include_roles, allow_forcing=True)
    exclude = _validate_option_roles(exclude_roles, allow_forcing=False)

    project_types = set(profile.project_types)
    selected: dict[str, RoleRecommendation] = {}
    warnings: list[str] = []

    has_signal = _profile_has_signal(profile)
    if not has_signal:
        warnings.append("insufficient information to recommend specialized roles")

    if has_signal:
        selected[REPO_EXPLORER] = RoleRecommendation(
            REPO_EXPLORER,
            ("Repository is non-empty and its architecture is not yet mapped.",),
            tuple(sorted(set(profile.manifests))) or ("project_type:" + ",".join(profile.project_types),),
            "high",
        )

    if "api" in project_types:
        selected[API_CONTRACT_AGENT] = RoleRecommendation(
            API_CONTRACT_AGENT,
            ("Profiler detected an API surface (HTTP/RPC/schema handlers, routes, or contracts).",),
            _evidence_for(profile, "api"),
            "high",
        )

    if "frontend" in project_types:
        selected[BROWSER_QA] = RoleRecommendation(
            BROWSER_QA,
            ("Profiler detected a frontend web project with UI surfaces to review.",),
            _evidence_for(profile, "frontend"),
            "high",
        )
        selected[ACCESSIBILITY_PERFORMANCE_REVIEWER] = RoleRecommendation(
            ACCESSIBILITY_PERFORMANCE_REVIEWER,
            (
                "Frontend web project benefits from a static accessibility and performance review.",
                "No browser, Lighthouse, or performance tooling is executed; runtime checks remain required.",
            ),
            _evidence_for(profile, "frontend"),
            "high",
        )

    design_markers = detect_design_signals(repo_root)
    if design_markers:
        labels = sorted({label for label, _ in design_markers})
        selected[DESIGN_DIRECTOR] = RoleRecommendation(
            DESIGN_DIRECTOR,
            tuple(f"Detected design-tooling signal: {label}." for label in labels),
            tuple(path for _, path in design_markers),
            "high",
        )

    # Explicit includes (read-only roles only; forcing without a signal is allowed).
    for role_id in include:
        if role_id not in selected:
            selected[role_id] = RoleRecommendation(
                role_id, ("Explicitly requested with --include-role.",), (), "medium"
            )

    # Explicit excludes win over any selection above.
    for role_id in exclude:
        selected.pop(role_id, None)

    # Consolidator: add independent_reviewer when more than one specialized role is present.
    specialized_selected = [rid for rid in SPECIALIZED_ROLES if rid in selected]
    consolidator: str | None = None
    if INDEPENDENT_REVIEWER in include and INDEPENDENT_REVIEWER not in exclude:
        consolidator = INDEPENDENT_REVIEWER
    elif len(specialized_selected) >= 2 and INDEPENDENT_REVIEWER not in exclude:
        selected[INDEPENDENT_REVIEWER] = RoleRecommendation(
            INDEPENDENT_REVIEWER,
            (f"{len(specialized_selected)} specialized roles selected; consolidates their findings.",),
            (),
            "high",
        )
        consolidator = INDEPENDENT_REVIEWER
    if INDEPENDENT_REVIEWER in selected:
        consolidator = INDEPENDENT_REVIEWER

    ordered = [selected[rid] for rid in CANONICAL_TEAM_ORDER if rid in selected]
    excluded = _build_excluded(set(selected), exclude)
    parallel_groups = _execution_plan(selected, consolidator)

    return TeamPlan(
        selected_roles=tuple(ordered),
        excluded_roles=excluded,
        parallel_groups=parallel_groups,
        consolidator=consolidator,
        warnings=tuple(warnings),
    )


def _execution_plan(selected: dict[str, RoleRecommendation], consolidator: str | None) -> tuple[tuple[str, ...], ...]:
    """repo_explorer first, specialized read-only roles in parallel, consolidator last."""
    groups: list[tuple[str, ...]] = []
    if REPO_EXPLORER in selected:
        groups.append((REPO_EXPLORER,))
    parallel = tuple(rid for rid in SPECIALIZED_ROLES if rid in selected)
    if parallel:
        groups.append(parallel)
    return tuple(groups)


def _build_excluded(selected_ids: set[str], exclude: set[str]) -> tuple[RoleRecommendation, ...]:
    """Every registry role not selected, with a deterministic reason. Order is fixed."""
    excluded: list[RoleRecommendation] = []
    for role_id in ROLES:
        if role_id in selected_ids:
            continue
        if role_id == IMPLEMENTATION_AGENT:
            reason = "Requires an explicit brief and write scope; never recommended automatically."
        elif role_id in exclude:
            reason = "Explicitly excluded with --exclude-role."
        else:
            reason = "No matching structural signal was detected."
        excluded.append(RoleRecommendation(role_id, (reason,), (), "excluded"))
    return tuple(excluded)


def _validate_option_roles(role_ids: list[str] | None, *, allow_forcing: bool) -> set[str]:
    """Validate --include-role/--exclude-role values against the registry and eligibility."""
    result: set[str] = set()
    for role_id in role_ids or []:
        if role_id not in ROLES:
            allowed = ", ".join(r for r in ROLES if r != IMPLEMENTATION_AGENT)
            raise TeamError(f"Unknown role: {role_id!r}. Allowed roles: {allowed}")
        if role_id == IMPLEMENTATION_AGENT:
            raise TeamError("implementation_agent cannot be part of an automatic team; it requires an explicit scope")
        if allow_forcing and ROLES[role_id].constraints.require_explicit_scope:
            raise TeamError(f"role {role_id!r} requires an explicit scope and cannot be included in a team")
        result.add(role_id)
    return result
