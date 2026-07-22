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
from .providers import (
    build_decomposed_provider_research_brief,
    build_provider_research_brief,
    capabilities_requiring_research,
    decomposed_capabilities,
    load_provider_catalog,
    load_provider_research,
    load_provider_resolution,
    resolve_providers,
)
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
        help=(
            "Write a portable profile, infrastructure plan, and provider-discovery gate "
            "without choosing a harness"
        ),
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
            "Use the repository-aware adapter-options command to obtain selectable roles "
            "and targets. Provider research is optional; when supplied, its complete "
            "research/decision chain is preserved separately."
        ),
    )
    adapters.add_argument("repo", help="Local repository path to profile")
    adapters.add_argument(
        "--targets",
        required=True,
        help="Required comma-separated subset exposed by adapter-options output",
    )
    adapters.add_argument(
        "--role",
        action="append",
        required=True,
        metavar="ROLE",
        help="Repeat for each explicit read-only role exposed by adapter-options output",
    )
    adapters.add_argument("--output", required=True, help="Proposal directory (must not exist and be outside this repo)")
    adapters.add_argument("--compare-to", default=None, help="Destination repo to compare against, strictly read-only")
    adapters.add_argument(
        "--provider-catalog",
        default=None,
        help="Optional reviewed local provider catalog used by select_provider proposals",
    )
    adapters.add_argument(
        "--provider-research",
        default=None,
        metavar="FILE",
        help=(
            "Validated provider-search evidence for one or more selected capability gaps; "
            "research alone never authorizes a provider outcome"
        ),
    )
    adapters.add_argument(
        "--provider-resolution",
        default=None,
        metavar="FILE",
        help=(
            "Provider decisions recorded after the user reviewed --provider-research; "
            "both artifacts are required before an adapter bundle can be generated"
        ),
    )
    adapters.add_argument(
        "--decomposed-provider-research",
        default=None,
        metavar="FILE",
        help="Provider research for one or more subcapabilities declared by decompose_capability",
    )
    adapters.add_argument(
        "--decomposed-provider-resolution",
        default=None,
        metavar="FILE",
        help="User decisions for --decomposed-provider-research; nested decomposition is rejected",
    )

    adapter_options = subparsers.add_parser(
        "adapter-options",
        help=(
            "Repository-aware adapter selection query; always exposes deterministic base "
            "adapter options while keeping provider discovery advisory and separate"
        ),
    )
    adapter_options.add_argument("repo", help="Local repository path to profile")
    adapter_options.add_argument("--request", default="", help="Optional user request to shape recommendations")
    adapter_options.add_argument("--evidence-path-limit", type=int, default=25, help="Maximum paths shown per evidence item")
    adapter_options.add_argument(
        "--provider-catalog",
        default=None,
        help="Optional reviewed local provider catalog used by select_provider proposals",
    )
    adapter_options.add_argument(
        "--provider-research",
        default=None,
        metavar="FILE",
        help="Validated provider-search evidence for one or more selected capability gaps",
    )
    adapter_options.add_argument(
        "--provider-resolution",
        default=None,
        metavar="FILE",
        help="Decisions recorded after the user reviewed --provider-research",
    )
    adapter_options.add_argument(
        "--decomposed-provider-research",
        default=None,
        metavar="FILE",
        help="Provider research for one or more subcapabilities declared by decompose_capability",
    )
    adapter_options.add_argument(
        "--decomposed-provider-resolution",
        default=None,
        metavar="FILE",
        help="User decisions for --decomposed-provider-research; nested decomposition is rejected",
    )

    provider_options = subparsers.add_parser(
        "provider-options",
        help="Resolve capability gaps against local provider metadata without network access or writes",
    )
    provider_options.add_argument("repo", help="Local repository path to profile")
    provider_options.add_argument(
        "--catalog",
        default=None,
        help="Optional local JSON provider catalog; omitted uses the empty built-in catalog",
    )
    provider_options.add_argument("--request", default="", help="Optional user request to shape recommendations")
    provider_options.add_argument("--evidence-path-limit", type=int, default=25, help="Maximum paths shown per evidence item")

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
    profile = profile_repository(args.repo)
    infrastructure = recommend_infrastructure(profile)
    gaps = _provider_gap_capabilities(infrastructure)
    providers = ()
    research = None
    resolution = None
    proposals = ()
    decomposed_research = None
    decomposed_resolution = None
    decomposed_proposals = ()
    decomposed_researched_ids = ()
    provider_chain_requested = any((
        args.provider_research,
        args.provider_resolution,
        args.decomposed_provider_research,
        args.decomposed_provider_resolution,
        args.provider_catalog,
    ))
    if provider_chain_requested and not args.provider_research:
        raise ValueError(
            "provider artifacts or catalog require --provider-research; omit all provider "
            "arguments to generate a base adapter bundle"
        )
    if args.provider_research:
        research = load_provider_research(
            args.provider_research,
            (item.capability_id for item in gaps),
            require_all=False,
        )
    researched_ids = tuple(
        item["capability_id"] for item in (research or {}).get("capabilities", [])
    )
    if research is not None and not args.provider_resolution:
        raise ValueError(
            "provider resolution required to embed provider research in a bundle; "
            "complete the provider branch or omit all provider arguments"
        )
    if args.provider_resolution:
        if research is None:
            raise ValueError("--provider-resolution requires --provider-research")
        preliminary_resolution, _ = load_provider_resolution(
            args.provider_resolution,
            researched_ids,
            research,
            require_catalog_for_selection=False,
        )
        preliminary_decomposition = decomposed_capabilities(
            preliminary_resolution
        )
        providers = load_provider_catalog(
            args.provider_catalog,
            (item["capability_id"] for item in preliminary_decomposition),
        )
        resolution, proposals = load_provider_resolution(
            args.provider_resolution,
            researched_ids,
            research,
            providers,
        )
    elif not provider_chain_requested:
        providers = ()
    decomposed = decomposed_capabilities(resolution or {})
    decomposed_ids = tuple(item["capability_id"] for item in decomposed)
    if decomposed:
        if not args.decomposed_provider_research:
            raise ValueError(
                "decomposed provider research required for: "
                + ", ".join(decomposed_ids)
            )
        decomposed_research = load_provider_research(
            args.decomposed_provider_research,
            decomposed_ids,
            require_all=False,
        )
        decomposed_researched_ids = tuple(
            item["capability_id"]
            for item in decomposed_research["capabilities"]
        )
        if not args.decomposed_provider_resolution:
            raise ValueError(
                "decomposed provider resolution required after the user reviews "
                "decomposed provider research"
            )
        decomposed_resolution, decomposed_proposals = load_provider_resolution(
            args.decomposed_provider_resolution,
            decomposed_researched_ids,
            decomposed_research,
            providers,
            allow_decomposition=False,
        )
    elif args.decomposed_provider_research or args.decomposed_provider_resolution:
        raise ValueError(
            "decomposed provider artifacts require a decompose_capability decision"
        )
    written, plan, _ = write_adapter_bundle(
        args.repo,
        targets,
        args.role,
        args.output,
        compare_to=args.compare_to,
        protected_root=Path.cwd(),
        provider_research=research,
        provider_resolution=resolution,
        provider_gap_proposals=to_jsonable(proposals),
        decomposed_provider_research=decomposed_research,
        decomposed_provider_resolution=decomposed_resolution,
        decomposed_provider_gap_proposals=to_jsonable(decomposed_proposals),
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


def _provider_gap_capabilities(infrastructure) -> tuple:
    """Return recommended capabilities not covered by canonical adapters."""
    matched, _optional, _unmapped = list_adapter_options(infrastructure)
    covered_capability_ids = {
        capability
        for adapter in matched
        for capability in adapter.matched_capabilities
    }
    return tuple(
        capability
        for capability in infrastructure.capabilities
        if capability.capability_id not in covered_capability_ids
    )


def _provider_discovery_packet(infrastructure) -> dict[str, object]:
    """Build the portable provider-research gate for a repository plan."""
    matched, _optional, _unmapped = list_adapter_options(infrastructure)
    covered_capability_ids = {
        capability
        for adapter in matched
        for capability in adapter.matched_capabilities
    }
    gaps = _provider_gap_capabilities(infrastructure)
    brief = build_provider_research_brief(gaps)
    requires_research = bool(gaps)
    return {
        "schema_version": 1,
        "kind": "provider_discovery",
        "status": (
            "provider_research_optional" if requires_research else "no_provider_gaps"
        ),
        "catalog": {
            "source": "builtin-empty",
            "provider_count": 0,
            "network_access": False,
        },
        "covered_by_canonical_adapters": sorted(covered_capability_ids),
        "unresolved_capabilities": to_jsonable(gaps),
        "provider_discovery": to_jsonable(brief),
        "next_action": (
            "Present the provider gaps alongside the deterministic adapter options. The "
            "user may proceed with base adapters or request read-only public provider "
            "research for selected gaps. Research remains advisory and must be completed "
            "with separate user decisions before any provider outcome is embedded. Do not "
            "download, execute, install, or silently catalog a provider."
            if requires_research
            else "No provider research is required before adapter selection."
        ),
    }


def _run_adapter_options(args) -> int:
    profile = profile_repository(args.repo, evidence_path_limit=args.evidence_path_limit)
    infrastructure = recommend_infrastructure(profile, args.request)
    matched, optional, unmapped = list_adapter_options(infrastructure)
    unmapped_names = set(unmapped)
    unmapped_roles = [
        role for role in infrastructure.available_roles if role.name in unmapped_names
    ]
    matched_capability_ids = {
        capability
        for adapter in matched
        for capability in adapter.matched_capabilities
    }
    unmapped_capability_ids = {
        capability.capability_id
        for capability in infrastructure.capabilities
        if capability.capability_id not in matched_capability_ids
    }
    unmapped_capabilities = [
        capability
        for capability in infrastructure.capabilities
        if capability.capability_id in unmapped_capability_ids
    ]
    providers = ()
    research = None
    resolution = None
    proposals = ()
    decomposition = ()
    decomposed_research = None
    decomposed_resolution = None
    decomposed_proposals = ()
    decomposed_researched_ids = ()
    if (
        args.decomposed_provider_research
        or args.decomposed_provider_resolution
    ) and not args.provider_resolution:
        raise ValueError(
            "decomposed provider artifacts require --provider-resolution"
        )
    if args.provider_research:
        research = load_provider_research(
            args.provider_research,
            (item.capability_id for item in unmapped_capabilities),
            require_all=False,
        )
    researched_ids = tuple(
        item["capability_id"] for item in (research or {}).get("capabilities", [])
    )
    if args.provider_resolution:
        if research is None:
            raise ValueError("--provider-resolution requires --provider-research")
        preliminary_resolution, _ = load_provider_resolution(
            args.provider_resolution,
            researched_ids,
            research,
            require_catalog_for_selection=False,
        )
        preliminary_decomposition = decomposed_capabilities(
            preliminary_resolution
        )
        providers = load_provider_catalog(
            args.provider_catalog,
            (item["capability_id"] for item in preliminary_decomposition),
        )
        resolution, proposals = load_provider_resolution(
            args.provider_resolution,
            researched_ids,
            research,
            providers,
        )
        decomposition = decomposed_capabilities(resolution)
        if decomposition:
            decomposed_ids = tuple(
                item["capability_id"] for item in decomposition
            )
            if args.decomposed_provider_research:
                decomposed_research = load_provider_research(
                    args.decomposed_provider_research,
                    decomposed_ids,
                    require_all=False,
                )
                decomposed_researched_ids = tuple(
                    item["capability_id"]
                    for item in decomposed_research["capabilities"]
                )
            if args.decomposed_provider_resolution:
                if decomposed_research is None:
                    raise ValueError(
                        "--decomposed-provider-resolution requires "
                        "--decomposed-provider-research"
                    )
                decomposed_resolution, decomposed_proposals = load_provider_resolution(
                    args.decomposed_provider_resolution,
                    (
                        item["capability_id"]
                        for item in decomposed_research["capabilities"]
                    ),
                    decomposed_research,
                    providers,
                    allow_decomposition=False,
                )
        else:
            if args.decomposed_provider_research or args.decomposed_provider_resolution:
                raise ValueError(
                    "decomposed provider artifacts require a decompose_capability decision"
                )
    elif unmapped_capabilities:
        providers = load_provider_catalog(args.provider_catalog)
    elif args.decomposed_provider_research or args.decomposed_provider_resolution:
        raise ValueError(
            "decomposed provider artifacts require a decompose_capability decision"
        )
    else:
        providers = load_provider_catalog(args.provider_catalog)

    if not unmapped_capabilities:
        provider_status = "not_required"
    elif research is None:
        provider_status = "research_optional"
    elif resolution is None:
        provider_status = "decision_optional"
    elif decomposition and decomposed_research is None:
        provider_status = "decomposed_research_optional"
    elif decomposition and decomposed_resolution is None:
        provider_status = "decomposed_decision_optional"
    else:
        parent_unresearched = unmapped_capability_ids.difference(researched_ids)
        decomposed_unresearched = {
            item["capability_id"] for item in decomposition
        }.difference(decomposed_researched_ids)
        provider_status = (
            "selected_capabilities_resolved"
            if parent_unresearched or decomposed_unresearched
            else "resolved"
        )
    status = "requires_adapter_selection"

    active_decision_research = (
        decomposed_research
        if provider_status == "decomposed_decision_optional"
        else research
        if provider_status == "decision_optional"
        else None
    )
    decision_options = [
        "select_provider",
        "select_partial_provider",
        "leave_unresolved",
        "create_local_knowledge",
    ]
    if provider_status == "decision_optional":
        decision_options.append("decompose_capability")
    adapter_questions = [
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
    ]
    payload = {
        "status": status,
        "provider_status": provider_status,
        "provider_scope": {
            "researched_capability_ids": list(researched_ids),
            "unresearched_capability_ids": sorted(
                unmapped_capability_ids.difference(researched_ids)
            ),
            "decomposed_researched_capability_ids": list(
                decomposed_researched_ids
            ),
            "decomposed_unresearched_capability_ids": sorted(
                {item["capability_id"] for item in decomposition}.difference(
                    decomposed_researched_ids
                )
            ),
        },
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
        "unmapped_capabilities": to_jsonable(unmapped_capabilities),
        "provider_discovery": to_jsonable(
            build_decomposed_provider_research_brief(resolution)
            if decomposition
            else build_provider_research_brief(unmapped_capabilities)
        ),
        "capability_provider_policy": {
            "unmapped_meaning": (
                "No canonical adapter or bundled knowledge provider covers this "
                "recommended capability."
            ),
            "generic_reviewer_boundary": (
                "Generic read-only review isolation does not by itself supply missing "
                "domain expertise."
            ),
            "partial_provider_boundary": (
                "select_partial_provider records an explicit user choice but does not claim "
                "that the remaining capability gap is resolved."
            ),
        },
        "questions": adapter_questions,
        "provider_decision_questions": (
            [
                {
                    "capability_id": item["capability_id"],
                    "decision_scope": (
                        "decomposed_capability"
                        if provider_status == "decomposed_decision_optional"
                        else "repository_capability"
                    ),
                    "question": "Which outcome should be recorded after reviewing this provider research?",
                    "options": decision_options,
                    "research_recommendation": item["recommended_outcome"],
                    "recommended_provider_id": item["recommended_provider_id"],
                    "candidate_options": [
                        {
                            "provider_id": candidate["provider_id"],
                            "title": candidate["title"],
                            "recommendation": candidate["recommendation"],
                            "primary_source": candidate["primary_source"],
                            "compatible_targets": candidate["compatible_targets"],
                            "exact_coverage": candidate["exact_coverage"],
                            "coverage_gaps": candidate["coverage_gaps"],
                        }
                        for candidate in item["candidates"]
                    ],
                }
                for item in (active_decision_research or {}).get("capabilities", [])
            ]
            if active_decision_research is not None
            else []
        ),
        "deferred_questions": [],
        "provider_research": research,
        "provider_resolution": resolution,
        "provider_gap_proposals": to_jsonable(proposals),
        "decomposed_capabilities": to_jsonable(decomposition),
        "decomposed_provider_research": decomposed_research,
        "decomposed_provider_resolution": decomposed_resolution,
        "decomposed_provider_gap_proposals": to_jsonable(decomposed_proposals),
        "next_action": (
            (
                "Present the deterministic adapter roles and targets together with the "
                "unresolved provider gaps. Ask which base adapters the user wants. Offer "
                "read-only provider research only for capabilities the user wants to "
                "investigate; it is optional and must not block base setup."
            )
            if provider_status == "research_optional"
            else (
                "Present the adapter choices and the optional provider research. The user "
                "may proceed with base adapters without resolving it. Embed this research "
                "only after separate provider decisions complete the provider branch."
            )
            if provider_status == "decision_optional"
            else (
                "Present the adapter choices and the concrete decomposed capabilities. "
                "Researching those subcapabilities is optional and does not block a base "
                "adapter bundle. If requested, record the research separately."
            )
            if provider_status == "decomposed_research_optional"
            else (
                "Present the adapter choices and the optional decomposed-provider research. "
                "The user may proceed with base adapters or finish separate decisions for "
                "each subcapability. Nested decomposition remains unsupported."
            )
            if provider_status == "decomposed_decision_optional"
            else (
                "Present the repository facts, adapter coverage, available targets, and any "
                "recorded provider outcomes. Ask which roles and targets to include before "
                "generating an installation preview."
            )
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _run_provider_options(args) -> int:
    profile = profile_repository(args.repo, evidence_path_limit=args.evidence_path_limit)
    infrastructure = recommend_infrastructure(profile, args.request)
    matched, _optional, _unmapped = list_adapter_options(infrastructure)
    covered_capabilities = {
        capability
        for adapter in matched
        for capability in adapter.matched_capabilities
    }
    providers = load_provider_catalog(args.catalog)
    resolution = resolve_providers(infrastructure, covered_capabilities, providers)
    research_capabilities = capabilities_requiring_research(resolution)
    payload = {
        "status": "provider_options",
        "repository": profile.name,
        "catalog": {
            "source": str(Path(args.catalog).expanduser()) if args.catalog else "builtin-empty",
            "provider_count": len(providers),
            "network_access": False,
        },
        "capability_gaps": to_jsonable(resolution.capability_gaps),
        "provider_candidates": to_jsonable(resolution.candidates),
        "unresolved_capabilities": to_jsonable(resolution.unresolved_capabilities),
        "provider_discovery": to_jsonable(
            build_provider_research_brief(research_capabilities)
        ),
        "policy": {
            "metadata_only": "Provider sources were not accessed, downloaded, or executed.",
            "approval": (
                "A catalog entry is evidence of a candidate or prior catalog review, not "
                "approval to install it in this repository."
            ),
            "generic_reviewer_boundary": (
                "independent_reviewer can provide read-only isolation but does not itself "
                "supply unresolved domain knowledge."
            ),
        },
        "next_action": (
            "Present matching candidates with source, revision, license, review status, and "
            "compatible targets. For unmatched capabilities, follow the provider_discovery "
            "brief when public network research is permitted and present the resulting "
            "coverage limits in a provider_research artifact, present it, and stop for the "
            "user's separate provider_resolution decisions before adapter selection. "
            "No provider installation command exists in this MVP."
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _adapter_proposal_lines(bundle_dir: str | Path) -> list[str]:
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
    provider_proposals = manifest.get("provider_gap_proposals", [])
    if provider_proposals:
        lines.append("  Evidence-backed provider gap proposals recorded in this tool proposal:")
        research_items = {
            item.get("capability_id"): item
            for item in (manifest.get("provider_research") or {}).get("capabilities", [])
        }
        for proposal in provider_proposals:
            provider = (
                f" ({proposal['provider_id']})"
                if proposal.get("provider_id")
                else ""
            )
            research = research_items.get(proposal["capability_id"], {})
            lines.append(
                f"    - {proposal['capability_id']}: {proposal['outcome']}{provider}; "
                f"research={research.get('research_status', 'unknown')}; "
                f"candidates={len(research.get('candidates', []))}; "
                f"rationale={research.get('rationale', 'not recorded')}"
            )
            if proposal["outcome"] == "select_partial_provider":
                lines.append(
                    "      Partial selection does not resolve the remaining capability gap."
                )
    decomposed_proposals = manifest.get("decomposed_provider_gap_proposals", [])
    if decomposed_proposals:
        lines.append("  Decomposed provider gap proposals:")
        decomposed_research_items = {
            item.get("capability_id"): item
            for item in (manifest.get("decomposed_provider_research") or {}).get(
                "capabilities", []
            )
        }
        for proposal in decomposed_proposals:
            provider = (
                f" ({proposal['provider_id']})"
                if proposal.get("provider_id")
                else ""
            )
            research = decomposed_research_items.get(
                proposal["capability_id"], {}
            )
            lines.append(
                f"    - {proposal['capability_id']}: {proposal['outcome']}{provider}; "
                f"research={research.get('research_status', 'unknown')}; "
                f"candidates={len(research.get('candidates', []))}; "
                f"rationale={research.get('rationale', 'not recorded')}"
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
    print("\n".join(_adapter_proposal_lines(args.bundle)))
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
        if args.command == "render-role":
            return _run_render_role(args)
        if args.command == "propose-adapters":
            return _run_propose_adapters(args)
        if args.command == "adapter-options":
            return _run_adapter_options(args)
        if args.command == "provider-options":
            return _run_provider_options(args)
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
        provider_discovery = _provider_discovery_packet(plan)
        files = write_proposal(
            profile,
            plan,
            args.output,
            provider_discovery=provider_discovery,
        )
        print(f"Wrote {len(files)} proposal files to {args.output}")
        print("No harness adapter was selected or generated.")
        if provider_discovery["status"] == "provider_research_optional":
            print(
                "Provider gaps remain visible in provider-discovery.json. Base adapter "
                "selection may proceed independently; public provider research is optional "
                "and requires separate user decisions before its outcomes are embedded."
            )
        return 0
    except (OSError, ProposalError, AdapterInstallError, AdapterSelectionError, MultiCliError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
