"""CLI for repository-local shared team knowledge."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .catalog import KnowledgeStore, SharedKnowledgeError, initialize_repository
from .codex import install_codex_skill
from .content import KnowledgeContentError
from .distribution import DistributionPlan, TeamKnowledgeDistributionService
from .selector import CodexSkillSelector
from .service import SharedKnowledgeService


def _repo_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--repo",
        default=".",
        metavar="PATH",
        help="Git repository or a path inside it (default: current directory)",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="team-knowledge",
        description="Share repository knowledge with your team's coding agents.",
    )
    commands = parser.add_subparsers(dest="command", required=True, title="commands")

    bootstrap = commands.add_parser(
        "bootstrap",
        help="Select and install canonical team Skills from a Git repository",
    )
    _repo_argument(bootstrap)
    bootstrap.add_argument("--source", required=True, help="Canonical team knowledge Git URL or relative path")
    bootstrap.add_argument("--ref", default="main", help="Canonical Git ref (default: main)")
    bootstrap.add_argument("--yes", action="store_true", help="Apply the complete safe plan without prompting")

    sync = commands.add_parser("sync", help="Safely synchronize bootstrapped canonical team Skills")
    _repo_argument(sync)
    sync.add_argument("--offline", action="store_true", help="Verify locked local state without fetching or claiming freshness")
    sync.add_argument("--yes", action="store_true", help="Apply the complete safe plan without prompting")

    init = commands.add_parser("init", help="Initialize shared team knowledge in a Git repository")
    _repo_argument(init)
    init.add_argument("--organization", help="Organization scope (default: local)")
    init.add_argument("--team", help="Team name (default: repository name)")
    init.add_argument("--repository", help="Repository identity (default: Git remote slug or directory name)")
    init.add_argument("--owner", help="Default contribution owner (default: Git user email/name)")
    init.add_argument(
        "--codex",
        action="store_true",
        help="Install the repository-local team-knowledge Agent Skill for Codex",
    )

    add = commands.add_parser("add", help="Add a Markdown knowledge item")
    _repo_argument(add)
    add.add_argument("--title", required=True, help="Short human-readable title")
    add.add_argument("--summary", required=True, help="One line describing when the item is useful")
    body = add.add_mutually_exclusive_group(required=True)
    body.add_argument("--body", help="Markdown body text")
    body.add_argument("--body-file", metavar="PATH", help="Read the Markdown body from a UTF-8 file")
    add.add_argument("--owner", help="Override the configured default owner")
    add.add_argument(
        "--restricted",
        action="store_true",
        help="Withhold this item from agents whenever it is inadmissible",
    )

    list_items = commands.add_parser("list", help="List shared team knowledge")
    _repo_argument(list_items)

    show = commands.add_parser("show", help="Show one knowledge item as source Markdown")
    _repo_argument(show)
    show.add_argument("item_id", metavar="ID", help="Stable knowledge item ID")

    check = commands.add_parser("check", help="Validate all knowledge and its native catalog mapping")
    _repo_argument(check)

    index = commands.add_parser("index", help="Expose the model-visible knowledge index")
    _repo_argument(index)
    index.add_argument("--json", action="store_true", help="Emit the machine-readable agent contract")
    index.add_argument("--task-id", help="Optional local task correlation ID for pilot events")

    use = commands.add_parser("use", help="Validate selected IDs and return only approved knowledge bodies")
    _repo_argument(use)
    use.add_argument("item_ids", nargs="+", metavar="ID", help="Knowledge IDs selected from one index response")
    use.add_argument("--exposure", required=True, metavar="ID", help="Exposure ID returned by index")
    use.add_argument("--json", action="store_true", help="Emit the machine-readable agent contract")
    use.add_argument("--task-id", help="Optional local task correlation ID for pilot events")

    feedback = commands.add_parser("feedback", help="Record useful, outdated, or incorrect feedback")
    _repo_argument(feedback)
    feedback.add_argument("item_id", metavar="ID", help="Stable knowledge item ID")
    feedback.add_argument("feedback", choices=("useful", "outdated", "incorrect"))
    feedback.add_argument("--task-id", help="Optional local task correlation ID for pilot events")
    feedback.add_argument("--json", action="store_true", help="Emit a machine-readable confirmation")

    revoke = commands.add_parser("revoke", help="Revoke an item while preserving its file and Git history")
    _repo_argument(revoke)
    revoke.add_argument("item_id", metavar="ID", help="Stable knowledge item ID")
    return parser


def _read_body(args: argparse.Namespace) -> str:
    if args.body_file:
        try:
            return Path(args.body_file).expanduser().read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise SharedKnowledgeError(f"cannot read body file {args.body_file}: {error}") from error
    return args.body


def _print_distribution_plan(plan: DistributionPlan) -> None:
    print(f"Team knowledge source: {plan.source_id} @ {plan.source_commit[:12]}")
    print(f"Repository: {plan.repository_id}")
    print("Plan:")
    visible = [action for action in plan.actions if action.action != "keep"]
    if not visible:
        print("  no materialized Skill changes")
    for action in visible:
        revision = f" @ {action.revision[:12]}" if action.revision else ""
        print(f"  {action.action.upper():7} {action.id} -> {action.materialized_path}{revision}")
    if plan.possibly_no_longer_relevant:
        print("Possibly no longer relevant (kept installed):")
        for resource_id in plan.possibly_no_longer_relevant:
            print(f"  {resource_id}")
    if plan.rejected_ids:
        print("Rejected by native validation:")
        for resource_id in plan.rejected_ids:
            print(f"  {resource_id}")
    reasons = [(resource_id, reason) for resource_id, reason in plan.selection_reasons if reason]
    if reasons:
        print("Model selection rationale (not stored in the lock):")
        for resource_id, reason in reasons:
            print(f"  {resource_id}: {reason}")
    if plan.semantic_pending:
        print("Semantic reassessment is pending because Codex was unavailable.")
    if plan.offline:
        print("Offline verification only; canonical source freshness was not checked.")


def _confirm(yes: bool) -> bool:
    if yes:
        return True
    try:
        return input("Apply? [y/N] ").strip().casefold() in {"y", "yes"}
    except EOFError:
        return False


def _run(args: argparse.Namespace) -> int:
    if args.command in {"bootstrap", "sync"}:
        service = TeamKnowledgeDistributionService(CodexSkillSelector())
        plan = (
            service.bootstrap_plan(args.repo, source_url=args.source, ref=args.ref)
            if args.command == "bootstrap"
            else service.sync_plan(args.repo, offline=args.offline)
        )
        _print_distribution_plan(plan)
        if plan.offline:
            service.apply(plan)
            print("Locked team Skills are present and match their recorded digests.")
            return 0
        if not _confirm(args.yes):
            print("No committed or materialized team knowledge changes were applied.")
            return 0
        service.apply(plan)
        past = {"add": "Added", "update": "Updated", "restore": "Restored", "remove": "Removed"}
        for action in plan.actions:
            if action.action != "keep":
                print(f"{past[action.action]} {action.id}: {action.materialized_path}")
        print("Recorded canonical selection in .team-knowledge/lock.json")
        print("Commit .team-knowledge/config.json, .team-knowledge/lock.json, and .team-knowledge/.gitignore")
        print("Generated Agent Skill copies remain local and Git-excluded.")
        return 0
    if args.command == "init":
        target = initialize_repository(
            args.repo,
            organization=args.organization,
            team=args.team,
            repository=args.repository,
            owner=args.owner,
        )
        if args.codex:
            skill_path, created = install_codex_skill(target.parent)
            action = "Installed" if created else "Codex Skill already current at"
            print(f"{action} {skill_path}")
        print(f"Team knowledge is ready in {target}")
        print("Add .team-knowledge to Git and use your normal pull-request review.")
        return 0

    store = KnowledgeStore.open(args.repo)
    if args.command == "add":
        item = store.add(
            args.title,
            args.summary,
            _read_body(args),
            owner=args.owner,
            restricted=args.restricted,
        )
        print(f"Added {item.id}: {item.title}")
        print(f"Created {item.path}; review and commit it through the normal Git workflow.")
        return 0
    if args.command == "list":
        items = store.load_items()
        if not items:
            print("No team knowledge yet. Use 'team-knowledge add' to create the first item.")
            return 0
        for item in items:
            print(f"{item.id}\t{item.state}\t{item.title}\t{item.summary}")
        print(f"{len(items)} item{'s' if len(items) != 1 else ''}")
        return 0
    if args.command == "show":
        item = store.get(args.item_id)
        sys.stdout.write((store.root / item.path).read_text(encoding="utf-8"))
        return 0
    if args.command == "check":
        result = SharedKnowledgeService(store).check()
        print(
            "Team knowledge is valid: "
            f"{result.active} active, {result.revoked} revoked, "
            f"{result.exposable} visible in the agent index."
        )
        return 0
    if args.command == "index":
        exposure = SharedKnowledgeService(store).expose_index(task_id=args.task_id)
        payload = {
            "schema_version": 1,
            "exposure_id": exposure.id,
            "knowledge": [
                {
                    "id": item.id,
                    "revision": item.revision,
                    "title": item.title,
                    "summary": item.summary,
                }
                for item in exposure.index
            ],
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Exposure: {exposure.id}")
            for item in exposure.index:
                print(f"{item.id}@{item.revision}\t{item.title}\t{item.summary}")
        return 0
    if args.command == "use":
        service = SharedKnowledgeService(store)
        exposure = service.load_exposure(args.exposure)
        result = service.validate_ids(
            exposure,
            tuple(args.item_ids),
            task_id=args.task_id,
        )
        exposed_revisions = {
            identity.resource_id: identity.revision for identity in exposure.receipt.resources
        }
        selected = [
            {
                "id": decision.resource_id,
                "revision": exposed_revisions.get(decision.resource_id),
                "status": "accepted" if decision.admitted else "rejected",
            }
            for decision in result.validation.selection_decisions
        ]
        payload = {
            "schema_version": 1,
            "exposure_id": exposure.id,
            "selected": selected,
            "knowledge": [
                {
                    "id": item.id,
                    "revision": item.revision,
                    "title": item.title,
                    "body": item.body,
                }
                for item in result.items
            ],
            "citations": [
                {"id": item.id, "revision": item.revision, "title": item.title}
                for item in result.items
            ],
            "binding_additions": list(result.binding_additions),
            "rejected": [item for item in selected if item["status"] == "rejected"],
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for item in result.items:
                print(f"# {item.title} ({item.id}@{item.revision})\n\n{item.body}\n")
            if result.citations:
                print("Used team knowledge: " + "; ".join(result.citations))
            if payload["rejected"]:
                print("Rejected: " + ", ".join(item["id"] for item in payload["rejected"]))
        return 0
    if args.command == "feedback":
        SharedKnowledgeService(store).record_feedback(
            args.item_id,
            args.feedback,
            task_id=args.task_id,
        )
        payload = {"schema_version": 1, "id": args.item_id, "feedback": args.feedback, "recorded": True}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"Recorded {args.feedback} feedback for {args.item_id}; the knowledge item was not changed.")
        return 0
    if args.command == "revoke":
        item = store.revoke(args.item_id)
        print(f"Revoked {item.id}: {item.title}")
        print(f"Updated {item.path}; review and commit the change through the normal Git workflow.")
        return 0
    raise SharedKnowledgeError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except (KnowledgeContentError, SharedKnowledgeError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
