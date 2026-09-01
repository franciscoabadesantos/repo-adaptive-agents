"""CLI for repository-local shared team knowledge."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .catalog import KnowledgeStore, SharedKnowledgeError, initialize_repository
from .content import KnowledgeContentError
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

    init = commands.add_parser("init", help="Initialize shared team knowledge in a Git repository")
    _repo_argument(init)
    init.add_argument("--organization", help="Organization scope (default: local)")
    init.add_argument("--team", help="Team name (default: repository name)")
    init.add_argument("--repository", help="Repository identity (default: Git remote slug or directory name)")
    init.add_argument("--owner", help="Default contribution owner (default: Git user email/name)")

    add = commands.add_parser("add", help="Add a Markdown knowledge item")
    _repo_argument(add)
    add.add_argument("--title", required=True, help="Short human-readable title")
    add.add_argument("--summary", required=True, help="One line describing when the item is useful")
    body = add.add_mutually_exclusive_group(required=True)
    body.add_argument("--body", help="Markdown body text")
    body.add_argument("--body-file", metavar="PATH", help="Read the Markdown body from a UTF-8 file")
    add.add_argument("--owner", help="Override the configured default owner")

    list_items = commands.add_parser("list", help="List shared team knowledge")
    _repo_argument(list_items)

    show = commands.add_parser("show", help="Show one knowledge item as source Markdown")
    _repo_argument(show)
    show.add_argument("item_id", metavar="ID", help="Stable knowledge item ID")

    check = commands.add_parser("check", help="Validate all knowledge and its native catalog mapping")
    _repo_argument(check)

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


def _run(args: argparse.Namespace) -> int:
    if args.command == "init":
        target = initialize_repository(
            args.repo,
            organization=args.organization,
            team=args.team,
            repository=args.repository,
            owner=args.owner,
        )
        print(f"Team knowledge is ready in {target}")
        print("Add .team-knowledge to Git and use your normal pull-request review.")
        return 0

    store = KnowledgeStore.open(args.repo)
    if args.command == "add":
        item = store.add(args.title, args.summary, _read_body(args), owner=args.owner)
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
            f"{result.exposable} available to agents."
        )
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
