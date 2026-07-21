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
            "roles and harness targets selected explicitly by the user. Capability matches "
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

    install = subparsers.add_parser(
        "install-adapters",
        help="Preview or explicitly install a validated adapter bundle into a local repository",
        description=(
            "Plan installation of a generated adapter bundle into a local repository. "
            "Preview is the default and writes nothing. --apply creates additions only; "
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
    print("Selected adapters: " + ", ".join(plan.selected_ids))
    print("No execution order or agent invocation was generated.")
    if args.compare_to:
        print(f"Compared (read-only) against {args.compare_to}; see manifest.json 'compare'.")
    return 0


def _run_install_adapters(args) -> int:
    plan = plan_adapter_install(args.bundle, args.repo)
    print(
        f"Install plan: {len(plan.additions)} addition(s), "
        f"{len(plan.unchanged)} unchanged, {len(plan.conflicts)} conflict(s)"
    )
    for entry in plan.entries:
        detail = f" — {entry.reason}" if entry.reason else ""
        print(f"{entry.status}: {entry.destination_path}{detail}")
    if not args.apply:
        print("Preview only; no files were written. Use --apply to install additions.")
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
