"""Render an explicit set of role adapters without defining an execution topology."""

from __future__ import annotations

import json
from pathlib import Path

from ..models import RepoProfile, to_jsonable
from ..profiler import profile_repository
from ..recommender import recommend_infrastructure
from .adapters import AdapterPlan, select_adapters
from .generator import (
    GENERATOR_VERSION,
    MultiCliError,
    _destination_path_conflict,
    _repo_relative,
    _sha256,
    render_role,
    resolve_targets,
    write_files_atomically,
)

ADAPTER_BUNDLE_SCHEMA_VERSION = 6


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


def _selection_dict(selection) -> dict:
    return {
        "role_id": selection.role_id,
        "selection_source": "tool_proposal",
        "matched_available_roles": list(selection.matched_available_roles),
        "matched_capabilities": list(selection.matched_capabilities),
    }


def _role_section(selection, prefix: str, role_files: dict, role_manifest: dict, files: dict) -> dict:
    section = {
        "selection": _selection_dict(selection),
        "manifest": {
            "path": prefix + "manifest.json",
            "sha256": _sha256(files[prefix + "manifest.json"]),
        },
        "files": [
            {"path": path, "sha256": _sha256(files[path])}
            for path in sorted(item for item in files if item.startswith(prefix))
        ],
    }
    codex = role_manifest.get("targets", {}).get("codex", {})
    if "artifacts" in codex:
        section["artifacts"] = {
            name: {
                "path": prefix + entry["path"],
                "sha256": _sha256(files[prefix + entry["path"]]),
            }
            for name, entry in sorted(codex["artifacts"].items())
        }
    return section


def _compare_to_destination(files: dict[str, str], compare_to: str | Path) -> dict:
    destination = Path(compare_to).expanduser().resolve()
    additions: set[str] = set()
    changes: set[str] = set()
    unchanged: set[str] = set()
    for proposal_relative in sorted(files):
        if not proposal_relative.startswith("roles/"):
            continue
        inner = "/".join(proposal_relative.split("/")[2:])
        repo_relative = _repo_relative(inner)
        if repo_relative is None:
            continue
        target_file = destination / repo_relative
        if _destination_path_conflict(destination, repo_relative):
            changes.add(repo_relative)
        elif target_file.is_file():
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


def render_adapter_bundle(
    repo_path: str | Path,
    targets: list[str],
    role_ids: list[str],
    *,
    compare_to: str | Path | None = None,
    provider_research: dict | None = None,
    provider_resolution: dict | None = None,
    provider_gap_proposals: list[dict] | None = None,
) -> tuple[dict[str, str], dict, AdapterPlan]:
    """Profile a repository and render only the adapters explicitly requested."""
    profile = profile_repository(repo_path)
    infrastructure = recommend_infrastructure(profile)
    adapter_plan = select_adapters(infrastructure, role_ids)
    resolved_targets = resolve_targets(targets)

    files: dict[str, str] = {
        "profile.json": json.dumps(to_jsonable(profile), indent=2, sort_keys=True) + "\n",
        "infrastructure-plan.json": json.dumps(
            to_jsonable(infrastructure), indent=2, sort_keys=True
        ) + "\n",
    }
    roles_section: dict[str, dict] = {}
    for selection in adapter_plan.selected_adapters:
        role_files, role_manifest = render_role(selection.role_id, resolved_targets)
        prefix = f"roles/{selection.role_id}/"
        for relative, content in role_files.items():
            files[prefix + relative] = content
        roles_section[selection.role_id] = _role_section(
            selection, prefix, role_files, role_manifest, files
        )

    compare_result = (
        _compare_to_destination(files, compare_to) if compare_to is not None else None
    )
    manifest = {
        "schema_version": ADAPTER_BUNDLE_SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "kind": "adapter_bundle",
        "profile": _profile_summary(profile),
        "requested_targets": list(resolved_targets),
        "selection_status": "tool_proposal",
        "provider_research": provider_research,
        "provider_resolution": provider_resolution,
        "provider_gap_proposals": provider_gap_proposals or [],
        "selected_adapters": [
            _selection_dict(item) for item in adapter_plan.selected_adapters
        ],
        "eligible_role_ids": list(adapter_plan.eligible_role_ids),
        "unmapped_available_roles": list(adapter_plan.unmapped_available_roles),
        "assumptions": list(adapter_plan.assumptions),
        "artifacts": [
            {"path": path, "sha256": _sha256(files[path])}
            for path in ("profile.json", "infrastructure-plan.json")
        ],
        "roles": roles_section,
    }
    if compare_result is not None:
        manifest["compare"] = compare_result
    files["manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    return files, manifest, adapter_plan


def write_adapter_bundle(
    repo_path: str | Path,
    targets: list[str],
    role_ids: list[str],
    output_dir: str | Path,
    *,
    compare_to: str | Path | None = None,
    protected_root: str | Path | None = None,
    provider_research: dict | None = None,
    provider_resolution: dict | None = None,
    provider_gap_proposals: list[dict] | None = None,
) -> tuple[list[Path], AdapterPlan, dict]:
    repo = Path(repo_path).expanduser().resolve()
    if not repo.is_dir():
        raise MultiCliError(f"Repository path is not a directory: {repo_path}")
    output = Path(output_dir).expanduser().resolve()
    if output == repo or output.is_relative_to(repo):
        raise MultiCliError("Proposal output cannot be inside the analyzed repository")
    files, manifest, plan = render_adapter_bundle(
        repo_path,
        targets,
        role_ids,
        compare_to=compare_to,
        provider_research=provider_research,
        provider_resolution=provider_resolution,
        provider_gap_proposals=provider_gap_proposals,
    )
    written = write_files_atomically(output_dir, files, protected_root=protected_root)
    return written, plan, manifest
