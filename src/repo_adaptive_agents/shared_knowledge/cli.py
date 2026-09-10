"""CLI for repository-local shared team knowledge."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from textwrap import wrap

from .repository import SharedKnowledgeError, find_repository
from .canonical import CanonicalSkill
from .onboarding import install_onboarding_skills, onboarding_readiness
from .preferences import load_selector_preference, preferences_path, save_selector_preference
from .proposals import prepare_new, prepare_update, proposal_root
from .distribution import DistributionPlan, TeamKnowledgeDistributionService
from .consumer import default_consumer_source, external_consumer_source
from .selector import (
    SelectionConversationTurn,
    SkillSelection,
    resolve_selector_name,
    selector_for,
)
from .skill_quality import assess_candidate
from .skill_validation import consumer_validation_targets, load_candidate, local_canonical_skills, validate_skill
from .storage import user_cache_root
from .source import removable_legacy_cache, remove_legacy_cache


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
    bootstrap.add_argument(
        "--source",
        help="Override the default repo-adaptive-agents team knowledge Git source",
    )
    bootstrap.add_argument(
        "--catalog-path",
        help="Relative canonical catalog path inside --source (default: .)",
    )
    bootstrap.add_argument("--ref", default="main", help="Canonical Git ref (default: main)")
    bootstrap.add_argument(
        "--selector",
        metavar="NAME",
        help="Semantic selector: codex, claude, or copilot (default: TEAM_KNOWLEDGE_SELECTOR or codex)",
    )
    bootstrap.add_argument(
        "--task",
        metavar="TEXT",
        help="Select Skills for this declared implementation task without recording the task text",
    )
    bootstrap.add_argument("--yes", action="store_true", help="Apply the complete safe plan without prompting")

    sync = commands.add_parser("sync", help="Safely synchronize bootstrapped canonical team Skills")
    _repo_argument(sync)
    sync.add_argument("--offline", action="store_true", help="Verify locked local state without fetching or claiming freshness")
    sync.add_argument(
        "--selector",
        metavar="NAME",
        help="Semantic selector: codex, claude, or copilot (default: TEAM_KNOWLEDGE_SELECTOR or codex)",
    )
    sync.add_argument("--yes", action="store_true", help="Apply the complete safe plan without prompting")

    onboarding = commands.add_parser(
        "install-onboarding",
        help="Install the portable team-knowledge preparation Skill for coding agents",
    )
    onboarding.add_argument(
        "--consumer",
        choices=("all", "codex", "claude", "copilot"),
        default="all",
        help="User-level coding agent to configure (default: all)",
    )
    onboarding.add_argument("--dry-run", action="store_true", help="Show destinations without writing files")

    validate_skill_command = commands.add_parser(
        "validate", help="Validate local canonical Skills, installed copies, or private proposals"
    )
    _repo_argument(validate_skill_command)
    validate_skill_command.add_argument("skill_ids", nargs="*", metavar="SKILL_ID")
    validate_skill_command.add_argument("--selector", choices=("codex", "claude", "copilot"))

    propose = commands.add_parser("propose", help="Prepare a local proposal for a new or improved canonical Skill")
    _repo_argument(propose)
    propose.add_argument("--new", action="store_true", help="Create a new portable Skill proposal")
    propose.add_argument("--name", help="New Skill name (with --new)")
    propose.add_argument("--description", help="New Skill discovery description (with --new)")
    propose.add_argument("--selector", choices=("codex", "claude", "copilot"))

    setup = commands.add_parser(
        "setup",
        help="Prepare and diagnose user-level onboarding for Codex, Claude, and Copilot",
    )
    setup.add_argument(
        "--only",
        action="store_true",
        help="Install onboarding only for --selector instead of every supported agent",
    )
    setup.add_argument("--dry-run", action="store_true", help="Show readiness and destinations without writing files")
    setup.add_argument(
        "--selector",
        choices=("codex", "claude", "copilot"),
        help="Save this user-level default selector for future bootstrap and sync commands",
    )

    listing = commands.add_parser("list", help="List local canonical or installed team Skills")
    _repo_argument(listing)
    show = commands.add_parser("show", help="Show one local canonical or installed Skill")
    _repo_argument(show)
    show.add_argument("skill_id", metavar="ID")
    return parser


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
    for action in plan.actions:
        if action.bridge_action != "keep":
            print(
                f"  {action.bridge_action.upper():7} {action.id} -> "
                f".claude/skills/{action.name} (bridge)"
            )
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
        print("Semantic reassessment is pending because the configured selector was unavailable.")
    if plan.offline:
        print("Offline verification only; canonical source freshness was not checked.")


def _approval_recommendation(plan: DistributionPlan) -> tuple[str, str]:
    planned = [action for action in plan.actions if action.action != "keep"]
    if plan.semantic_pending:
        return "CANCEL", "the AI selector was unavailable, so no fresh semantic assessment exists"
    if plan.rejected_ids:
        return "CANCEL", "native validation rejected one or more proposed Skills"
    if not planned:
        return "CANCEL", "the reviewed plan does not materialize any Skill changes"
    return "APPLY", "the proposed local changes passed native validation"


def _print_approval_form(plan: DistributionPlan) -> None:
    planned = [action for action in plan.actions if action.action != "keep"]
    recommendation, reason = _approval_recommendation(plan)
    skill_count = len({action.id for action in planned})
    print()
    print("╭─ Team knowledge decision ──────────────────────────────────────────────╮")
    print(f"│ Recommended action: {recommendation:<49}│")
    print(f"│ Why: {reason[:62]:<62}│")
    print("├───────────────────────────────────────────────────────────────────────┤")
    print(f"│ Planned Skill changes: {skill_count:<48}│")
    print(
        "│ Writes: .team-knowledge config, lock, and local ignore rules          │"
        if planned
        else "│ Writes: none                                                           │"
    )
    print("│ Never: commits, pushes, deploys, or edits application source files     │")
    print("╰───────────────────────────────────────────────────────────────────────╯")
    if not planned:
        print("  No action is available — no files will be changed.")
        return
    if recommendation == "APPLY":
        print("  [1] Apply the recommended local plan")
        print("  [2] Cancel — make no changes (default)")
    else:
        print("  [1] Apply anyway")
        print("  [2] Cancel as recommended — make no changes (default)")


def _choose_bootstrap_skills(plan: DistributionPlan) -> tuple[str, ...] | None:
    """Let a person retain only some validated recommendations before final approval."""
    recommended_ids = {resource_id for resource_id, _reason in plan.selection_reasons}
    candidates = tuple(skill for skill in plan.desired_skills if skill.id in recommended_ids)
    if len(candidates) < 2:
        return tuple(skill.id for skill in candidates)
    reasons = dict(plan.selection_reasons)
    print()
    print("Recommended Skills — choose the ones you want in this repository:")
    for index, skill in enumerate(candidates, start=1):
        print(f"  [{index}] {skill.name}: {skill.description}")
        if reason := reasons.get(skill.id):
            print(f"      Why recommended: {reason}")
    print("  [all] Keep every recommendation (default)")
    print("  [cancel] Stop without changing the repository")
    while True:
        try:
            raw = input("Choose Skill numbers, separated by commas: ").strip().casefold()
        except EOFError:
            return None
        if raw in {"", "all"}:
            return tuple(skill.id for skill in candidates)
        if raw in {"cancel", "c", "none", "n"}:
            return None
        selected: list[str] = []
        valid = True
        for value in (part.strip() for part in raw.split(",")):
            if not value.isdecimal() or not 1 <= int(value) <= len(candidates):
                valid = False
                break
            skill_id = candidates[int(value) - 1].id
            if skill_id not in selected:
                selected.append(skill_id)
        if valid and selected:
            return tuple(selected)
        print(f"Enter numbers from 1 to {len(candidates)}, for example: 1,2. No files were changed.")


def _choose_bootstrap_intent() -> str | None:
    print()
    print("╭─ Prepare team knowledge ─────────────────────────────────────────────╮")
    print("│ Choose how the AI selector should evaluate this repository.          │")
    print("╰─────────────────────────────────────────────────────────────────────╯")
    print("  [1] Recommend Skills for this repository (default)")
    print("  [2] Tell me what you want to do")
    print("  [3] Cancel")
    while True:
        try:
            choice = input("Choose [1/2/3] (default 1): ").strip()
        except EOFError:
            return "repository"
        if choice in {"", "1"}:
            return "repository"
        if choice == "2":
            return "conversation"
        if choice == "3":
            return None
        print("Choose 1, 2, or 3. No files were changed.")


def _read_conversation_message(prompt: str) -> str | None:
    while True:
        try:
            message = input(prompt).strip()
        except EOFError:
            return None
        if message:
            return message
        print("Describe the work you want to do, or press Ctrl-D to cancel.")


def _conversation_action(selection: SkillSelection, skills) -> str:
    descriptions = {skill.id: skill for skill in skills}
    print()
    print("╭─ Current Skill recommendations ──────────────────────────────────────╮")
    if selection.selected:
        for entry in selection.selected:
            skill = descriptions.get(entry.id)
            label = skill.name if skill is not None else entry.id
            for line in wrap(label, width=67) or [""]:
                print(f"│ {line:<67}│")
            if entry.reason:
                for line in wrap(entry.reason, width=65):
                    print(f"│   {line:<65}│")
    else:
        print("│ No matching team Skills were found.                                  │")
    print("╰─────────────────────────────────────────────────────────────────────╯")
    if selection.selected:
        print("  [1] Review these recommendations (default)")
    else:
        print("  [1] Finish without Skill changes (default)")
    print("  [2] Add context or describe another task")
    print("  [3] Cancel")
    while True:
        try:
            choice = input("Choose [1/2/3] (default 1): ").strip()
        except EOFError:
            return "accept"
        if choice in {"", "1"}:
            return "accept"
        if choice == "2":
            return "continue"
        if choice == "3":
            return "cancel"
        print("Choose 1, 2, or 3. No files were changed.")


def _print_skill_list(targets) -> None:
    count = len(targets)
    noun = "Skill" if count == 1 else "Skills"
    print()
    print("╭─ Available team Skills ──────────────────────────────────────────────╮")
    summary = f"{count} local {noun}"
    print(f"│ {summary:<68} │")
    print("╰──────────────────────────────────────────────────────────────────────╯")
    if not targets:
        print("  No canonical, installed, or proposed Skills are available.")
        return
    for index, (skill, path) in enumerate(targets, start=1):
        print()
        print(f"  [{index}] {skill.name}")
        for line in wrap(skill.description, width=82):
            print(f"      {line}")
        for line in wrap(
            f"Location: {path}",
            width=82,
            initial_indent="      ",
            subsequent_indent="                ",
        ):
            print(line)


class _ConversationalSelector:
    """Keep one bootstrap conversation in memory while reusing one evidence snapshot."""

    def __init__(self, delegate, initial_message: str, selector_name: str) -> None:
        self.delegate = delegate
        self.initial_message = initial_message
        self.selector_name = selector_name
        self.cancelled = False

    def select(
        self,
        evidence,
        skills,
        *,
        task=None,
        organization_default_skill_ids=(),
    ) -> SkillSelection:
        del task
        message = self.initial_message
        history: list[SelectionConversationTurn] = []
        while True:
            selection = self.delegate.select(
                evidence,
                skills,
                task=message,
                organization_default_skill_ids=organization_default_skill_ids,
                conversation=tuple(history),
            )
            action = _conversation_action(selection, skills)
            if action == "accept":
                return selection
            if action == "cancel":
                self.cancelled = True
                return SkillSelection(())
            next_message = _read_conversation_message(
                "Add context, correct the request, or describe another task: "
            )
            if next_message is None:
                self.cancelled = True
                return SkillSelection(())
            history.append(SelectionConversationTurn(message, selection))
            message = next_message
            print(
                f"[team-knowledge] Continuing {self.selector_name} AI selection with the same "
                "repository evidence...",
                flush=True,
            )


def _choose_skills_to_validate(skills, *, proposal: bool = False) -> tuple[str, ...] | None:
    print()
    print("╭─ Prepare a Skill improvement ────────────────────────────────────────╮" if proposal else "╭─ Canonical Skill validation ─────────────────────────────────────────╮")
    print("│ Select one installed Skill to revalidate and prepare.                │" if proposal else "│ Select only the Skills you want to assess.                           │")
    print("│ No source checkout is changed until it has a READY assessment.       │" if proposal else "│ Each selected package is validated independently.                    │")
    print("├─────────────────────────────────────────────────────────────────────┤")
    print("│ Writes: none before the READY gate                                  │" if proposal else "│ Writes: none                                                         │")
    print("│ Never: publishes, changes Skills, or combines their contents         │")
    print("╰─────────────────────────────────────────────────────────────────────╯")
    for index, (skill, _path) in enumerate(skills, start=1):
        print(f"  [{index}] {skill.name}")
        print(f"      {skill.description}")
    print("  [all] Validate every listed Skill" if not proposal else "  [cancel] Exit without preparing a proposal (default)")
    if not proposal:
        print("  [cancel] Exit without validating (default)")
    while True:
        try:
            raw = input("Choose Skills [1, 3 / all / cancel] (default cancel): ").strip().casefold()
        except EOFError:
            return None
        if raw in {"cancel", "c", "none", "n", ""}:
            return None
        if raw == "all" and not proposal:
            return tuple(skill.id for skill, _path in skills)
        values = [part.strip() for part in raw.split(",")]
        if values and all(value.isdecimal() and 1 <= int(value) <= len(skills) for value in values):
            return tuple(dict.fromkeys(skills[int(value) - 1][0].id for value in values))
        print(f"Enter numbers from 1 to {len(skills)}, for example: 1, 3. No files were changed.")


def _choose_proposal_kind(*, can_update: bool) -> str | None:
    print()
    print("╭─ Prepare a shared Skill proposal ────────────────────────────────────╮")
    print("│ Choose what you want to contribute. Nothing will be published.       │")
    print("╰─────────────────────────────────────────────────────────────────────╯")
    if can_update:
        print("  [1] Improve an installed Skill")
    print("  [2] Draft a new Skill")
    print("  [3] Cancel (default)")
    try:
        choice = input("Choose [1/2/3] (default 3): ").strip()
    except EOFError:
        return None
    return ({"1": "update", "2": "new"} if can_update else {"2": "new"}).get(choice)


def _choose_prepared_proposal_action() -> str:
    print()
    print("╭─ Prepared Skill proposal ────────────────────────────────────────────╮")
    print("│ The diff is local. Choose the next explicit Git action.              │")
    print("╰─────────────────────────────────────────────────────────────────────╯")
    print("  [1] Keep the checkout local — no Git write (default)")
    print("  [2] Commit the prepared branch locally")
    print("  [3] Commit and push the prepared branch")
    print("  [4] Commit, push, and create a draft pull request")
    try:
        return {"2": "commit", "3": "push", "4": "pr"}.get(input("Choose [1/2/3/4] (default 1): ").strip(), "keep")
    except EOFError:
        return "keep"


def _run_git_action(checkout: Path, *arguments: str) -> None:
    result = subprocess.run(["git", *arguments], cwd=checkout, check=False, text=True, capture_output=True)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "Git failed without an error message"
        raise SharedKnowledgeError(f"requested Git action did not complete successfully: {detail}")


def _run_gh_action(checkout: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(["gh", *arguments], cwd=checkout, check=False, text=True, capture_output=True)
    except FileNotFoundError as error:
        raise SharedKnowledgeError("creating a pull request requires the GitHub CLI (gh) to be installed and signed in") from error
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "GitHub CLI failed without an error message"
        raise SharedKnowledgeError(f"draft pull request was not created: {detail}")
    return result.stdout.strip()


def _apply_prepared_proposal_action(prepared) -> None:
    """Perform only the Git action explicitly selected after the local diff was shown."""
    action = _choose_prepared_proposal_action()
    if action == "keep":
        print(f"Kept local checkout: {prepared.checkout}")
        print("No commit, push, pull request, or remote source change was made.")
        return
    _run_git_action(prepared.checkout, "add", "--", prepared.source_path)
    _run_git_action(prepared.checkout, "commit", "-m", f"Propose update to {prepared.skill_id}")
    print(f"Committed local proposal branch: {prepared.branch}")
    if action == "commit":
        print("No push, pull request, or remote source change was made.")
        return
    _run_git_action(prepared.checkout, "push", "--set-upstream", "origin", prepared.branch)
    print(f"Pushed proposal branch: {prepared.branch}")
    if action == "push":
        print("No pull request was created.")
        return
    url = _run_gh_action(
        prepared.checkout,
        "pr",
        "create",
        "--draft",
        "--base",
        prepared.base_ref,
        "--head",
        prepared.branch,
        "--title",
        f"Propose update to {prepared.skill_id}",
        "--body",
        "Prepared and independently validated with team-knowledge.",
    )
    print("Created draft pull request" + (f": {url}" if url else "."))


def _validation_targets(root: Path):
    """Installed locked packages plus local proposals; each proposal remains isolated."""
    try:
        targets = list(consumer_validation_targets(root))
    except SharedKnowledgeError:
        targets = []
    local_catalog = root / "team-knowledge"
    if (local_catalog / "team-knowledge.json").is_file():
        for skill in local_canonical_skills(local_catalog):
            targets.append((skill, local_catalog / skill.source_path))
    installed = {skill.id: skill for skill, _path in targets}
    drafts = proposal_root(root)
    if drafts.is_dir() and not drafts.is_symlink():
        for path in sorted(item for item in drafts.iterdir() if item.is_dir() and not item.is_symlink()):
            metadata_path = path / "proposal.json"
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            candidate = load_candidate(path)
            if metadata.get("kind") == "update" and isinstance(metadata.get("skill_id"), str):
                baseline = installed.get(metadata["skill_id"])
                if baseline is not None:
                    targets.append((CanonicalSkill(
                        f"proposal-{candidate.name}", baseline.name, baseline.description, baseline.state,
                        baseline.source_path, baseline.revision, baseline.digest_sha256, baseline.files,
                        baseline.skill_text,
                    ), path))
            elif metadata.get("kind") == "new":
                targets.append((CanonicalSkill(
                    f"proposal-{candidate.name}", candidate.name, candidate.description, "active",
                    f"proposals/{candidate.name}", "proposal", "", (), dict(candidate.files)["SKILL.md"].decode("utf-8"),
                ), path))
    if not targets:
        raise SharedKnowledgeError("no installed Skills or local proposals are available to validate")
    return tuple(targets)


def _confirm(yes: bool, plan: DistributionPlan) -> bool:
    planned = [action for action in plan.actions if action.action != "keep"]
    if not planned:
        _print_approval_form(plan)
        return False
    if yes:
        return True
    _print_approval_form(plan)
    try:
        choice = input("Choose [1/2] (default 2): ").strip().casefold()
        return choice in {"1", "y", "yes"}
    except EOFError:
        return False


def _offer_legacy_cache_cleanup(plan: DistributionPlan, *, noninteractive: bool) -> None:
    legacy = removable_legacy_cache(
        plan.root,
        plan.config.source.url,
        plan.config.source.catalog_path,
    )
    if legacy is None:
        return
    print()
    print("╭─ Obsolete repository cache ─────────────────────────────────────────╮")
    print("│ The shared cache is ready; this clone and its ignore rule are old.  │")
    print(f"│ Path: {str(legacy)[:62]:<62}│")
    print("╰─────────────────────────────────────────────────────────────────────╯")
    if noninteractive:
        print("  Kept obsolete local cache because --yes never authorizes cleanup.")
        return
    print("  [1] Remove the obsolete local cache")
    print("  [2] Keep it for now (default)")
    try:
        remove = input("Choose [1/2] (default 2): ").strip().casefold() in {"1", "y", "yes"}
    except EOFError:
        remove = False
    if not remove:
        print("Kept obsolete local cache.")
        return
    if not remove_legacy_cache(
        plan.root,
        plan.config.source.url,
        plan.config.source.catalog_path,
    ):
        raise SharedKnowledgeError("legacy cache changed before cleanup; nothing was removed")
    print("Removed obsolete repository-local source cache.")


def _print_skill_validation_report(report) -> None:
    status = "PASSED" if report.passed else "NEEDS REVISION"
    print()
    print("╭─ Skill validation result ────────────────────────────────────────────╮")
    print(f"│ Skill: {report.skill_id:<61}│")
    print(f"│ Package checks: {status:<53}│")
    print("├─────────────────────────────────────────────────────────────────────┤")
    print("│ This report is local and read-only; it does not approve publication. │")
    print("╰─────────────────────────────────────────────────────────────────────╯")
    if report.changed_paths:
        print("  Candidate changes: " + ", ".join(report.changed_paths))
    else:
        print("  Candidate changes: none (same package as the canonical baseline)")
    for finding in report.findings:
        print(f"  - {finding}")


def _print_skill_assessment(assessment) -> None:
    next_step = (
        "You can prepare a proposal."
        if assessment.decision == "ready"
        else "Fix the required changes, then run validate again."
        if assessment.decision == "needs_revision"
        else "Gather the missing evidence, then run validate again."
    )
    print()
    print("╭─ Skill decision ─────────────────────────────────────────────────────╮")
    print(f"│ Status: {assessment.decision.upper():<57}│")
    print(f"│ Next: {next_step:<59}│")
    print(f"│ Required changes: {len(assessment.required_changes):<46}│")
    print("│ It cannot publish, change files, use tools, or inspect other Skills. │")
    print("╰─────────────────────────────────────────────────────────────────────╯")
    if assessment.required_changes:
        print("\nWhat to fix:")
        for index, change in enumerate(assessment.required_changes, start=1):
            print(f"  {index}. {change}")
    print("\nWhy:")
    print(f"  {assessment.summary}")
    print("\nBoundary exercises:")
    print(f"  In-scope exercise: {assessment.in_scope_exercise}")
    print(f"  Out-of-scope exercise: {assessment.out_of_scope_exercise}")
    print("\nAdditional observations:")
    for finding in assessment.findings:
        print(f"  - {finding}")


def _run(args: argparse.Namespace) -> int:
    if args.command == "validate":
        root = find_repository(args.repo)
        targets = _validation_targets(root)
        skills = tuple((skill, path) for skill, path in targets)
        ids = tuple(args.skill_ids) or _choose_skills_to_validate(skills)
        if not ids:
            print("No Skills were validated.")
            return 0
        available = {skill.id: (skill, path) for skill, path in targets}
        if any(skill_id not in available for skill_id in ids):
            raise SharedKnowledgeError("selected Skill is not installed in this repository")
        preference = load_selector_preference() if args.selector is None and not os.environ.get("TEAM_KNOWLEDGE_SELECTOR") else None
        evaluator = resolve_selector_name(args.selector, preference=preference)
        for skill_id in dict.fromkeys(ids):
            skill, candidate_path = available[skill_id]
            report = validate_skill(skill, candidate_path)
            _print_skill_validation_report(report)
            if report.passed:
                print(f"[team-knowledge] Starting isolated {evaluator} assessment for this candidate only...", flush=True)
                _print_skill_assessment(assess_candidate(evaluator, load_candidate(candidate_path)))
        print("No Skill files were changed or published.")
        return 0
    if args.command == "propose":
        root = find_repository(args.repo)
        try:
            installed_targets = consumer_validation_targets(root)
        except SharedKnowledgeError:
            installed_targets = ()
        kind = "new" if args.new else _choose_proposal_kind(can_update=bool(installed_targets))
        if kind is None:
            print("No Skill proposal was created.")
            return 0
        if kind == "new":
            if args.name is None or args.description is None:
                try:
                    name = input("New Skill name (lowercase words with hyphens): ").strip()
                    description = input("When should an agent use it?: ").strip()
                except EOFError:
                    print("No Skill proposal was created.")
                    return 0
            else:
                name, description = args.name, args.description
            proposal = prepare_new(root, name, description)
            print(f"Created new Skill proposal: {proposal}")
        else:
            selected = _choose_skills_to_validate(installed_targets, proposal=True)
            if not selected:
                print("No Skill proposal was created.")
                return 0
            if len(selected) != 1:
                raise SharedKnowledgeError("choose exactly one installed Skill to prepare an update proposal")
            skill, candidate_path = {skill.id: (skill, path) for skill, path in installed_targets}[selected[0]]
            report = validate_skill(skill, candidate_path)
            _print_skill_validation_report(report)
            if not report.passed:
                raise SharedKnowledgeError("proposal stopped: package checks need revision")
            preference = load_selector_preference() if args.selector is None and not os.environ.get("TEAM_KNOWLEDGE_SELECTOR") else None
            evaluator = resolve_selector_name(args.selector, preference=preference)
            print(f"[team-knowledge] Revalidating with isolated {evaluator} assessment...", flush=True)
            assessment = assess_candidate(evaluator, load_candidate(candidate_path))
            _print_skill_assessment(assessment)
            if assessment.decision != "ready":
                raise SharedKnowledgeError("proposal stopped: independent assessment is not READY")
            prepared = prepare_update(root, selected[0], load_candidate(candidate_path))
            print(f"Prepared source checkout: {prepared.checkout}")
            print(f"Prepared branch: {prepared.branch}")
            print("\nProposed diff:\n" + prepared.diff)
            _apply_prepared_proposal_action(prepared)
            return 0
        print("No commit, push, pull request, or remote source change was made.")
        return 0
    if args.command == "setup":
        if args.only and args.selector is None:
            raise SharedKnowledgeError("--only requires --selector")
        consumers = (args.selector,) if args.only else ("codex", "claude", "copilot")
        readiness = dict(onboarding_readiness(consumers))
        preference_path = None
        if args.selector is not None:
            if args.dry_run:
                print(f"Would save default selector: {args.selector}")
            else:
                preference_path = save_selector_preference(args.selector)
        installed = install_onboarding_skills(consumers, dry_run=args.dry_run)
        print("Team knowledge machine setup")
        print("Agent CLI availability:")
        for consumer in consumers:
            status = "available" if readiness[consumer] else "not found on PATH"
            print(f"  {consumer}: {status}")
        print("Onboarding Skills:")
        for consumer, path, created in installed:
            action = "Would install" if args.dry_run and created else "Installed" if created else "Already current at"
            print(f"  {action} {consumer}: {path}")
        print("Machine storage:")
        print(f"  user configuration: {preferences_path()}")
        print(f"  shared source cache: {user_cache_root()}")
        print("  repository cache: not used")
        if args.dry_run:
            print("No files were written.")
            return 0
        if preference_path is not None:
            print(f"Saved default selector: {args.selector} ({preference_path})")
        missing = [consumer for consumer in consumers if not readiness[consumer]]
        if missing:
            print(
                "Note: onboarding was installed, but these agent CLIs are not currently on PATH: "
                + ", ".join(missing)
                + ". Install or sign in to them before using them as a selector."
            )
        print(
            "Ready. In any Git repository, ask your coding agent to prepare team knowledge for the work you want to do."
        )
        return 0
    if args.command == "install-onboarding":
        installed = install_onboarding_skills(
            ("codex", "claude", "copilot") if args.consumer == "all" else (args.consumer,),
            dry_run=args.dry_run,
        )
        for consumer, path, created in installed:
            action = "Would install" if created else "Already current at"
            print(f"{action} {consumer} onboarding Skill: {path}")
        if args.dry_run:
            print("No files were written.")
        return 0
    if args.command in {"bootstrap", "sync"}:
        if args.command == "bootstrap" and args.catalog_path is not None and args.source is None:
            raise SharedKnowledgeError("--catalog-path requires --source")
        preference = None
        if args.selector is None and not os.environ.get("TEAM_KNOWLEDGE_SELECTOR"):
            preference = load_selector_preference()
        selector_name = resolve_selector_name(args.selector, preference=preference)
        active_selector = selector_for(selector_name)
        conversational_selector = None
        bootstrap_task = args.task if args.command == "bootstrap" else None
        if (
            args.command == "bootstrap"
            and not args.yes
            and args.task is None
            and sys.stdin.isatty()
        ):
            intent = _choose_bootstrap_intent()
            if intent is None:
                print("No committed or materialized team knowledge changes were applied.")
                return 0
            if intent == "conversation":
                initial_message = _read_conversation_message(
                    "What are you planning to build, change, or investigate? "
                )
                if initial_message is None:
                    print("No committed or materialized team knowledge changes were applied.")
                    return 0
                conversational_selector = _ConversationalSelector(
                    active_selector,
                    initial_message,
                    selector_name,
                )
                active_selector = conversational_selector
                bootstrap_task = initial_message
        service = TeamKnowledgeDistributionService(active_selector)

        def progress(message: str) -> None:
            if message.startswith("Calling the configured AI selector"):
                message = f"Starting {selector_name} AI selection with read-only factual evidence"
            print(f"[team-knowledge] {message}...", flush=True)

        plan = (
            service.bootstrap_plan(
                args.repo,
                source=(
                    external_consumer_source(
                        args.source,
                        args.ref,
                        args.catalog_path or ".",
                    )
                    if args.source is not None
                    else default_consumer_source(args.ref)
                ),
                task=bootstrap_task,
                progress=progress,
            )
            if args.command == "bootstrap"
            else service.sync_plan(args.repo, offline=args.offline)
        )
        if conversational_selector is not None and conversational_selector.cancelled:
            print("No committed or materialized team knowledge changes were applied.")
            return 0
        if args.command == "bootstrap" and not args.yes:
            selected = _choose_bootstrap_skills(plan)
            if selected is None:
                print("No committed or materialized team knowledge changes were applied.")
                return 0
            plan = service.retain_bootstrap_skills(plan, selected)
        _print_distribution_plan(plan)
        _offer_legacy_cache_cleanup(plan, noninteractive=args.yes)
        if plan.offline:
            service.apply(plan)
            print("Locked team Skills are present and match their recorded digests.")
            return 0
        if not _confirm(args.yes, plan):
            print("No committed or materialized team knowledge changes were applied.")
            return 0
        service.apply(plan)
        past = {"add": "Added", "update": "Updated", "restore": "Restored", "remove": "Removed"}
        for action in plan.actions:
            if action.action != "keep":
                print(f"{past[action.action]} {action.id}: {action.materialized_path}")
            if action.bridge_action != "keep":
                print(
                    f"{past[action.bridge_action]} {action.id}: "
                    f".claude/skills/{action.name} (Claude bridge)"
                )
        print("Recorded canonical selection in .team-knowledge/lock.json")
        print("Commit .team-knowledge/config.json, .team-knowledge/lock.json, and .team-knowledge/.gitignore")
        print("Generated Agent Skills and Claude bridges remain local and Git-excluded.")
        return 0
    if args.command in {"list", "show"}:
        root = find_repository(args.repo)
        targets = _validation_targets(root)
        available = {skill.id: (skill, path) for skill, path in targets}
        if args.command == "list":
            _print_skill_list(tuple(available.values()))
            return 0
        if args.skill_id not in available:
            raise SharedKnowledgeError("Skill is not available in this repository")
        _skill, path = available[args.skill_id]
        sys.stdout.write((path / "SKILL.md").read_text(encoding="utf-8"))
        return 0
    raise SharedKnowledgeError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except (SharedKnowledgeError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
