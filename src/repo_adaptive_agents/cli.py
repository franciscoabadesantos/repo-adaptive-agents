"""Command-line entry point for the MVP."""

from __future__ import annotations

import argparse
import json
import sys

from .generator import ProposalError, proposal_diff, write_proposal
from .models import to_jsonable
from .profiler import profile_repository
from .recommender import recommend_team


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Profile a repository and propose a tailored Codex team.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("profile", "plan"):
        sub = subparsers.add_parser(command)
        sub.add_argument("repo", help="Local repository path")
        sub.add_argument("--request", default="", help="Optional user request to shape recommendations")
    propose = subparsers.add_parser("propose")
    propose.add_argument("repo", help="Local repository path")
    propose.add_argument("--output", default=".codex-proposal", help="Proposal directory; defaults away from existing .codex")
    propose.add_argument("--request", default="", help="Optional user request to shape recommendations")
    propose.add_argument("--existing", default=None, help="Existing .codex directory to diff against")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        profile = profile_repository(args.repo)
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
    except (OSError, ProposalError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
