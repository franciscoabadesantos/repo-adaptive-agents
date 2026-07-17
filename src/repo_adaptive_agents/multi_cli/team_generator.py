"""Render a recommended team into an aggregated, deterministic multi-CLI proposal.

Reuses the deterministic profiler, the team recommender, and the per-role renderers. It
produces one proposal per selected role under ``roles/<role-id>/`` plus a team fragment and
an aggregated manifest. It only proposes: it never applies files, never runs agents, never
writes to HOME, and never touches the analyzed repository.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..profiler import profile_repository
from .generator import (
    GENERATOR_VERSION,
    SCHEMA_VERSION,
    MultiCliError,
    _repo_relative,
    _sha256,
    render_role,
    resolve_targets,
    write_files_atomically,
)
from ..models import RepoProfile
from .renderers.common import bullet_list
from .roles import ROLES
from .team import TeamPlan, recommend_team


def _team_fragment(plan: TeamPlan, profile: RepoProfile) -> str:
    lines = [
        "<!-- Generated team fragment. Guidance, not enforcement. No agent is executed. -->",
        "# Recommended review team",
        "",
        f"Repository project types: {', '.join(profile.project_types) or 'unknown'}.",
        "",
        "## Selected roles",
        "",
    ]
    if plan.selected_roles:
        lines.append(bullet_list(tuple(f"{rec.role_id} — {ROLES[rec.role_id].title}" for rec in plan.selected_roles)))
    else:
        lines.append("- (none: insufficient signal)")
    lines += ["", "## Execution plan", ""]
    for index, group in enumerate(plan.parallel_groups, start=1):
        joined = ", ".join(group)
        lines.append(f"{index}. {'run in parallel: ' if len(group) > 1 else ''}{joined}")
    if plan.consolidator:
        lines.append(f"{len(plan.parallel_groups) + 1}. consolidate: {plan.consolidator}")
    lines += [
        "",
        "No write role is included; implementation_agent is excluded because it requires an explicit brief and scope.",
        "",
    ]
    if plan.warnings:
        lines += ["## Warnings", "", bullet_list(plan.warnings), ""]
    return "\n".join(lines)


def _profile_summary(profile: RepoProfile) -> dict:
    return {
        "name": profile.name,
        "project_types": list(profile.project_types),
        "primary_project_types": list(profile.primary_project_types),
        "languages": list(profile.languages),
        "frameworks": list(profile.frameworks),
        "manifests": list(profile.manifests),
        "warnings": list(profile.warnings),
    }


def _recommendation_dict(rec) -> dict:
    return {
        "role_id": rec.role_id,
        "reasons": list(rec.reasons),
        "evidence": list(rec.evidence),
        "confidence": rec.confidence,
    }


def render_team(
    repo_path: str | Path,
    targets: list[str] | None = None,
    *,
    include_roles: list[str] | None = None,
    exclude_roles: list[str] | None = None,
    compare_to: str | Path | None = None,
) -> tuple[dict[str, str], dict, TeamPlan]:
    """Profile a repo, recommend a team, and render every selected role.

    Returns ``(files, manifest, plan)`` where ``files`` maps OUTPUT-relative POSIX paths to
    content (including ``manifest.json``). No filesystem writes happen here.
    """
    profile = profile_repository(repo_path)
    plan = recommend_team(profile, repo_path, include_roles=include_roles, exclude_roles=exclude_roles)
    resolved = resolve_targets(targets)

    files: dict[str, str] = {}
    roles_section: dict[str, dict] = {}
    for rec in plan.selected_roles:
        role_files, role_manifest = render_role(rec.role_id, resolved)
        prefix = f"roles/{rec.role_id}/"
        for relative, content in role_files.items():
            files[prefix + relative] = content
        roles_section[rec.role_id] = _role_section(rec, prefix, role_files, role_manifest, files)

    files["team/AGENTS.fragment.md"] = _team_fragment(plan, profile)

    compare_result = _compare_to_destination(files, compare_to) if compare_to is not None else None
    manifest = _aggregated_manifest(profile, plan, resolved, files, roles_section, compare_result)
    files["manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    return files, manifest, plan


def _role_section(rec, prefix: str, role_files: dict, role_manifest: dict, files: dict) -> dict:
    section = {
        "recommendation": _recommendation_dict(rec),
        "manifest": {"path": prefix + "manifest.json", "sha256": _sha256(files[prefix + "manifest.json"])},
        "files": [
            {"path": path, "sha256": _sha256(files[path])}
            for path in sorted(p for p in files if p.startswith(prefix))
        ],
    }
    codex = role_manifest.get("targets", {}).get("codex", {})
    if "artifacts" in codex:
        section["artifacts"] = {
            name: {"path": prefix + entry["path"], "sha256": _sha256(files[prefix + entry["path"]])}
            for name, entry in sorted(codex["artifacts"].items())
        }
    return section


def _aggregated_manifest(profile, plan, resolved, files, roles_section, compare_result) -> dict:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "kind": "team",
        "profile": _profile_summary(profile),
        "requested_targets": list(resolved),
        "selected_roles": [_recommendation_dict(rec) for rec in plan.selected_roles],
        "excluded_roles": [_recommendation_dict(rec) for rec in plan.excluded_roles],
        "execution_plan": {
            "parallel_groups": [list(group) for group in plan.parallel_groups],
            "consolidator": plan.consolidator,
        },
        "roles": roles_section,
        "team": {
            "files": [
                {"path": "team/AGENTS.fragment.md", "sha256": _sha256(files["team/AGENTS.fragment.md"])}
            ]
        },
        "warnings": list(plan.warnings),
    }
    if compare_result is not None:
        manifest["compare"] = compare_result
    return manifest


def _compare_to_destination(files: dict[str, str], compare_to: str | Path) -> dict:
    """Read-only comparison of the rendered roles against a destination repository.

    Maps each role wrapper onto its real repository location and reports additions,
    changes, and unchanged counts. Never writes; only the destination is read. Recorded
    paths are repository-relative (never absolute).
    """
    destination = Path(compare_to).expanduser().resolve()
    additions: set[str] = set()
    changes: set[str] = set()
    unchanged: set[str] = set()
    for proposal_relative in sorted(files):
        if not proposal_relative.startswith("roles/"):
            continue
        inner = "/".join(proposal_relative.split("/")[2:])  # drop "roles/<role-id>/"
        repo_relative = _repo_relative(inner)
        if repo_relative is None:
            continue
        target_file = destination / repo_relative
        if target_file.is_file():
            if target_file.read_text(encoding="utf-8") == files[proposal_relative]:
                unchanged.add(repo_relative)
            else:
                changes.add(repo_relative)
        else:
            additions.add(repo_relative)
    return {
        "additions": sorted(additions),
        "changes": sorted(changes),
        "unchanged": sorted(unchanged),
    }


def write_team_proposal(
    repo_path: str | Path,
    targets: list[str] | None,
    output_dir: str | Path,
    *,
    include_roles: list[str] | None = None,
    exclude_roles: list[str] | None = None,
    compare_to: str | Path | None = None,
    protected_root: str | Path | None = None,
) -> tuple[list[Path], TeamPlan, dict]:
    """Render a team and write an atomic aggregated proposal directory."""
    repo = Path(repo_path).expanduser()
    if not repo.is_dir():
        raise MultiCliError(f"Repository path is not a directory: {repo_path}")
    files, manifest, plan = render_team(
        repo_path,
        targets,
        include_roles=include_roles,
        exclude_roles=exclude_roles,
        compare_to=compare_to,
    )
    written = write_files_atomically(output_dir, files, protected_root=protected_root)
    return written, plan, manifest
