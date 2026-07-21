"""Command-line entry point for the MVP."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .generator import ProposalError, write_proposal
from .models import to_jsonable
from .multi_cli import (
    AdapterInstallError,
    AdapterSelectionError,
    ROLES,
    MultiCliError,
    TARGETS,
    apply_adapter_install,
    build_scope,
    compare_proposal,
    list_adapter_options,
    plan_adapter_install,
    role_ids,
    validate_adapter_bundle,
    validate_proposal,
    write_adapter_bundle,
)
from .multi_cli import write_proposal as write_role_proposal
from .profiler import profile_repository
from .recommender import recommend_infrastructure


def _parse_targets(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    targets = [item.strip() for item in raw.split(",") if item.strip()]
    if not targets:
        raise MultiCliError("No targets given")
    return targets


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Profile a repository and propose tailored, repository-local agentic infrastructure."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("profile", "plan"):
        sub = subparsers.add_parser(command)
        sub.add_argument("repo", help="Local repository path")
        sub.add_argument("--request", default="", help="Optional user request to shape recommendations")
        sub.add_argument("--evidence-path-limit", type=int, default=25, help="Maximum paths shown per evidence item")
    propose = subparsers.add_parser(
        "propose",
        help="Write a portable profile and infrastructure plan without choosing a harness",
    )
    propose.add_argument("repo", help="Local repository path")
    propose.add_argument(
        "--output",
        required=True,
        help="Portable proposal directory; must be outside the analyzed repository",
    )
    propose.add_argument("--request", default="", help="Optional user request to shape recommendations")
    propose.add_argument("--evidence-path-limit", type=int, default=25, help="Maximum paths shown per evidence item")

    render = subparsers.add_parser(
        "render-role",
        help="[experimental] Render a canonical role to multi-CLI wrappers (proposal only)",
        description=(
            "[EXPERIMENTAL] Render one canonical role into portable and target-specific "
            "wrappers (skill, codex, claude, copilot). Writes a proposal directory; never "
            "applies changes, writes to HOME, or touches an existing Codex config. "
            f"Roles: {', '.join(role_ids())}. Targets: {', '.join(TARGETS)}."
        ),
    )
    render.add_argument("role", help=f"Canonical role id (one of: {', '.join(role_ids())})")
    render.add_argument("--targets", default=None, help=f"Comma-separated subset of: {', '.join(TARGETS)} (default: all)")
    render.add_argument("--output", required=True, help="Proposal directory (must not exist and be outside this repo)")
    render.add_argument("--compare-to", default=None, help="Destination repo to compare against, strictly read-only")
    render.add_argument(
        "--allow-path",
        action="append",
        default=[],
        metavar="PATH",
        help="[write roles] Repeatable repo-relative path the agent may edit (advisory scope)",
    )
    render.add_argument(
        "--block-path",
        action="append",
        default=[],
        metavar="PATH",
        help="[write roles] Repeatable repo-relative path to exclude; blocked overrides allowed",
    )
    render.add_argument(
        "--scope-description",
        default=None,
        help="[write roles] Non-empty description of the approved brief/scope",
    )

    adapters = subparsers.add_parser(
        "propose-adapters",
        help="[experimental] Render explicitly selected role adapters for a repository",
        description=(
            "[EXPERIMENTAL] Profile a repository and render only the canonical read-only "
            "roles and adapter targets supplied by the caller as a tool proposal. Capability matches "
            "are recorded as evidence, but no execution order, concurrency, consolidator, "
            "or mandatory team is generated. The command never applies or runs adapters. "
            f"Read-only roles: {', '.join(r for r in role_ids() if r != 'implementation_agent')}. "
            f"Targets: {', '.join(TARGETS)}."
        ),
    )
    adapters.add_argument("repo", help="Local repository path to profile")
    adapters.add_argument(
        "--targets",
        required=True,
        help=f"Required comma-separated subset of: {', '.join(TARGETS)}",
    )
    adapters.add_argument(
        "--role",
        action="append",
        required=True,
        metavar="ROLE",
        help="Repeat for each explicit read-only adapter role",
    )
    adapters.add_argument("--output", required=True, help="Proposal directory (must not exist and be outside this repo)")
    adapters.add_argument("--compare-to", default=None, help="Destination repo to compare against, strictly read-only")

    adapter_options = subparsers.add_parser(
        "adapter-options",
        help="Report matched adapters, preference-based options, and adapter targets without writing",
    )
    adapter_options.add_argument("repo", help="Local repository path to profile")
    adapter_options.add_argument("--request", default="", help="Optional user request to shape recommendations")
    adapter_options.add_argument("--evidence-path-limit", type=int, default=25, help="Maximum paths shown per evidence item")

    install = subparsers.add_parser(
        "install-adapters",
        help="Preview or explicitly install a validated adapter bundle into a local repository",
        description=(
            "Plan installation of a generated adapter bundle into a local repository. "
            "Preview is the default and writes nothing. --apply together with "
            "--confirm-install creates additions only; "
            "any differing file, symlink, or invalid parent blocks the entire operation."
        ),
    )
    install.add_argument("bundle", help="Validated adapter bundle directory")
    install.add_argument("repo", help="Destination local repository directory")
    install.add_argument(
        "--apply",
        action="store_true",
        help="Explicitly create planned additions; existing files are never overwritten",
    )
    install.add_argument(
        "--confirm-install",
        action="store_true",
        help=(
            "Attest that the user reviewed the install preview and separately approved "
            "applying that exact plan"
        ),
    )

    subparsers.add_parser("roles", help="[experimental] List available canonical roles")
    subparsers.add_parser("targets", help="[experimental] List supported render targets")
    return parser


def _build_render_scope(args):
    """Build an InvocationScope from CLI flags, enforcing the per-role scope contract."""
    role = ROLES.get(args.role)
    scope_flags = bool(args.allow_path or args.block_path or args.scope_description)
    if role is not None and role.constraints.require_explicit_scope:
        if not args.allow_path or not (args.scope_description or "").strip():
            raise MultiCliError(
                f"{role.id} requires at least one --allow-path and a non-empty --scope-description"
            )
        return build_scope(args.scope_description, args.allow_path, args.block_path)
    if role is not None and scope_flags:
        raise MultiCliError(
            f"role {args.role!r} is read-only and does not accept --allow-path, --block-path, or --scope-description"
        )
    return None


def _run_render_role(args) -> int:
    targets = _parse_targets(args.targets)
    scope = _build_render_scope(args)
    files = write_role_proposal(args.role, targets, args.output, protected_root=Path.cwd(), scope=scope)
    issues = validate_proposal(args.output)
    if issues:
        raise MultiCliError("Generated proposal failed validation: " + "; ".join(issues))
    print(f"Wrote {len(files)} proposal files to {args.output}")
    if args.compare_to:
        report = compare_proposal(args.output, args.compare_to)
        print(f"\nComparison against {args.compare_to} (read-only):")
        print(f"  additions: {len(report.additions)}  changes/conflicts: {len(report.changes)}  unchanged: {len(report.unchanged)}")
        if report.diff:
            print(report.diff)
    return 0


def _run_propose_adapters(args) -> int:
    targets = _parse_targets(args.targets)
    written, plan, _ = write_adapter_bundle(
        args.repo,
        targets,
        args.role,
        args.output,
        compare_to=args.compare_to,
        protected_root=Path.cwd(),
    )
    issues = validate_adapter_bundle(args.output)
    if issues:
        raise MultiCliError("Generated adapter bundle failed validation: " + "; ".join(issues))
    print(f"Wrote {len(written)} adapter bundle files to {args.output}")
    print("Proposed adapters: " + ", ".join(plan.selected_ids))
    print(
        "Selection status: tool proposal. Roles and targets remain recommendations until "
        "the user approves the exact installation preview."
    )
    print("No execution order or agent invocation was generated.")
    if args.compare_to:
        print(f"Compared (read-only) against {args.compare_to}; see manifest.json 'compare'.")
    return 0


def _run_adapter_options(args) -> int:
    profile = profile_repository(args.repo, evidence_path_limit=args.evidence_path_limit)
    infrastructure = recommend_infrastructure(profile, args.request)
    matched, optional, unmapped = list_adapter_options(infrastructure)
    unmapped_names = set(unmapped)
    unmapped_roles = [
        role for role in infrastructure.available_roles if role.name in unmapped_names
    ]
    unmapped_capability_ids = {
        capability
        for role in unmapped_roles
        for capability in role.capabilities
    }
    payload = {
        "status": "requires_install_decision",
        "repository_summary": {
            "name": profile.name,
            "primary_project_types": list(profile.primary_project_types),
            "secondary_project_types": list(profile.secondary_project_types),
            "languages": list(profile.languages),
            "frameworks": list(profile.frameworks),
            "technology_findings": to_jsonable(profile.technology_findings),
            "warnings": list(profile.warnings),
        },
        "repository_contracts": to_jsonable(infrastructure.repository_contracts),
        "recommended_capabilities": to_jsonable(infrastructure.capabilities),
        "available_targets": list(TARGETS),
        "target_details": {
            "skill": {
                "kind": "portable_artifact",
                "path": ".agents/skills/<role>/SKILL.md",
                "note": "Optional portable role procedure; not a harness and not required by other targets.",
            },
            "codex": {"kind": "harness_adapter"},
            "claude": {"kind": "harness_adapter"},
            "copilot": {"kind": "harness_adapter"},
        },
        "matched_adapters": [to_jsonable(item) for item in matched],
        "optional_adapters": [to_jsonable(item) for item in optional],
        "unmapped_available_roles": list(unmapped),
        "unmapped_roles": to_jsonable(unmapped_roles),
        "unmapped_capabilities": [
            to_jsonable(capability)
            for capability in infrastructure.capabilities
            if capability.capability_id in unmapped_capability_ids
        ],
        "questions": [
            {
                "id": "adapter_targets",
                "question": "Which adapter targets should be installed? The skill target is an optional portable artifact, not a harness.",
                "options": list(TARGETS),
            },
            {
                "id": "adapter_roles",
                "question": "Which matched and optional adapter roles should be installed?",
                "options": [item.role_id for item in matched + optional],
            },
        ],
        "next_action": (
            "Present the repository summary, recommended capabilities, matched adapters, "
            "and unmapped capabilities. The user may choose roles and targets before a "
            "proposal, or review them in the exact installation preview."
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _adapter_decision_lines(bundle_dir: str | Path) -> list[str]:
    """Build a concise, evidence-backed decision packet from a validated bundle."""
    bundle = Path(bundle_dir).expanduser().resolve()
    try:
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        infrastructure = json.loads(
            (bundle / "infrastructure-plan.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise AdapterInstallError(f"Invalid adapter decision metadata: {error}") from error

    profile = manifest.get("profile", {})
    selected = manifest.get("selected_adapters", [])
    selected_ids = {item.get("role_id") for item in selected}
    eligible_ids = set(manifest.get("eligible_role_ids", []))
    read_only_roles = [role for role in ROLES.values() if role.constraints.read_only]
    available_roles = {
        item.get("name"): item for item in infrastructure.get("available_roles", [])
    }
    capabilities = {
        item.get("capability_id"): item
        for item in infrastructure.get("capabilities", [])
    }

    def joined(items) -> str:
        values = [str(item) for item in items if item]
        return ", ".join(values) if values else "none"

    lines = ["Decision summary:"]
    lines.append(
        "  Repository facts: "
        f"types={joined(profile.get('primary_project_types', []))}; "
        f"languages={joined(profile.get('languages', []))}; "
        f"frameworks={joined(profile.get('frameworks', []))}"
    )
    selected_targets = manifest.get("requested_targets", [])
    other_targets = [target for target in TARGETS if target not in selected_targets]
    lines.append(f"  Selected targets: {joined(selected_targets)}")
    lines.append(f"  Other available targets: {joined(other_targets)}")
    lines.append(
        "  Selection status: tool proposal; roles and targets are recommendations until "
        "this exact install plan is approved"
    )
    lines.append("  Selected adapters:")
    for item in selected:
        role_id = item.get("role_id", "unknown")
        role = ROLES.get(role_id)
        title = role.title if role else "Unknown role"
        purpose = role.purpose if role else "No canonical purpose available."
        matched_roles = item.get("matched_available_roles", [])
        matched_capabilities = item.get("matched_capabilities", [])
        detail = f"{role_id} ({title}): {purpose}"
        if matched_capabilities:
            evidence_parts: list[str] = []
            for capability_id in matched_capabilities:
                capability = capabilities.get(capability_id, {})
                paths: list[str] = []
                for evidence in capability.get("evidence", []):
                    paths.extend(evidence.get("paths", []))
                paths = list(dict.fromkeys(paths))
                reason = capability.get("reason", "matched repository capability")
                evidence_parts.append(
                    f"{capability_id}: {reason} [{joined(paths[:3])}]"
                )
            detail += (
                f" Match: capabilities={joined(matched_capabilities)}; "
                f"repository roles={joined(matched_roles)}. Evidence: "
                + "; ".join(evidence_parts)
            )
        else:
            detail += " Match: preference-based; no deterministic repository capability match."
        lines.append(f"    - {detail}")

    other_matched = [
        role for role in read_only_roles
        if role.id in eligible_ids and role.id not in selected_ids
    ]
    lines.append(
        "  Other matched adapters: "
        + joined(f"{role.id} ({role.title})" for role in other_matched)
    )
    optional = [
        role for role in read_only_roles
        if role.id not in eligible_ids and role.id not in selected_ids
    ]
    lines.append(
        "  Optional adapters without a deterministic match: "
        + joined(f"{role.id} ({role.title})" for role in optional)
    )
    unmapped = []
    for role_id in manifest.get("unmapped_available_roles", []):
        available = available_roles.get(role_id, {})
        title = available.get("title", role_id)
        purpose = available.get("purpose", "No canonical adapter is available.")
        unmapped.append(f"{role_id} ({title}): {purpose}")
    lines.append(
        "  Repository roles without a canonical adapter: "
        + ("; ".join(unmapped) if unmapped else "none")
    )
    lines.append(
        "  Functional effect: add repository-local, read-only role definitions for the "
        "selected adapter targets. No agent is invoked, no application command changes, no CLI "
        "is installed, and registration fragments are not merged automatically."
    )
    return lines


def _run_install_adapters(args) -> int:
    if args.confirm_install and not args.apply:
        raise AdapterInstallError("--confirm-install is valid only together with --apply")
    if args.apply and not args.confirm_install:
        raise AdapterInstallError(
            "--apply requires --confirm-install after the user reviewed the exact preview "
            "and separately approved installation"
        )
    plan = plan_adapter_install(args.bundle, args.repo)
    print("\n".join(_adapter_decision_lines(args.bundle)))
    print(
        f"Install plan: {len(plan.additions)} addition(s), "
        f"{len(plan.unchanged)} unchanged, {len(plan.conflicts)} conflict(s)"
    )
    for entry in plan.entries:
        detail = f" — {entry.reason}" if entry.reason else ""
        print(f"{entry.status}: {entry.destination_path}{detail}")
    if not args.apply:
        print("Preview only; no files were written.")
        print(
            "STOP: present the Decision summary and exact install plan above, including "
            "proposed roles and targets, and request installation approval. Approval of "
            "this preview accepts both the selection and the exact additions."
        )
        return 0
    result = apply_adapter_install(args.bundle, args.repo)
    print(f"Installed {len(result.created)} file(s); {len(result.unchanged)} already unchanged.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "roles":
            print("\n".join(role_ids()))
            return 0
        if args.command == "targets":
            print("\n".join(TARGETS))
            return 0
        if args.command == "render-role":
            return _run_render_role(args)
        if args.command == "propose-adapters":
            return _run_propose_adapters(args)
        if args.command == "adapter-options":
            return _run_adapter_options(args)
        if args.command == "install-adapters":
            return _run_install_adapters(args)

        profile = profile_repository(args.repo, evidence_path_limit=args.evidence_path_limit)
        if args.command == "profile":
            print(json.dumps(to_jsonable(profile), indent=2, sort_keys=True))
            return 0
        plan = recommend_infrastructure(profile, args.request)
        if args.command == "plan":
            print(json.dumps(to_jsonable(plan), indent=2, sort_keys=True))
            return 0
        files = write_proposal(profile, plan, args.output)
        print(f"Wrote {len(files)} proposal files to {args.output}")
        print("No harness adapter was selected or generated.")
        return 0
    except (OSError, ProposalError, AdapterInstallError, AdapterSelectionError, MultiCliError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
