"""Command-line entry point for the MVP."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .generator import ProposalError, proposal_diff, write_proposal
from .models import to_jsonable
from .multi_cli import (
    MultiCliError,
    TARGETS,
    compare_proposal,
    role_ids,
    validate_proposal,
)
from .multi_cli import write_proposal as write_role_proposal
from .profiler import profile_repository
from .recommender import recommend_team


def _parse_targets(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    targets = [item.strip() for item in raw.split(",") if item.strip()]
    if not targets:
        raise MultiCliError("No targets given")
    return targets


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Profile a repository and propose a tailored Codex team.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("profile", "plan"):
        sub = subparsers.add_parser(command)
        sub.add_argument("repo", help="Local repository path")
        sub.add_argument("--request", default="", help="Optional user request to shape recommendations")
        sub.add_argument("--evidence-path-limit", type=int, default=25, help="Maximum paths shown per evidence item")
    propose = subparsers.add_parser("propose")
    propose.add_argument("repo", help="Local repository path")
    propose.add_argument("--output", default=".codex-proposal", help="Proposal directory; defaults away from existing .codex")
    propose.add_argument("--request", default="", help="Optional user request to shape recommendations")
    propose.add_argument("--existing", default=None, help="Existing .codex directory to diff against")
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

    subparsers.add_parser("roles", help="[experimental] List available canonical roles")
    subparsers.add_parser("targets", help="[experimental] List supported render targets")
    return parser


def _run_render_role(args) -> int:
    targets = _parse_targets(args.targets)
    files = write_role_proposal(args.role, targets, args.output, protected_root=Path.cwd())
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

        profile = profile_repository(args.repo, evidence_path_limit=args.evidence_path_limit)
        if args.command == "profile":
            print(json.dumps(to_jsonable(profile), indent=2, sort_keys=True))
            return 0
        plan = recommend_team(profile, args.request)
        if args.command == "plan":
            print(json.dumps(to_jsonable(plan), indent=2, sort_keys=True))
            return 0
        files = write_proposal(profile, plan, args.output)
        existing = args.existing or f"{args.repo.rstrip('/')}/.codex"
        print(f"Wrote {len(files)} proposal files to {args.output}")
        print("\nDiff against existing .codex:")
        print(proposal_diff(args.output, existing) or "(no generated changes)")
        return 0
    except (OSError, ProposalError, MultiCliError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
