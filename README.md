# repo-adaptive-agents

Deterministic bootstrapper that analyzes a local repository and proposes tailored,
repository-local agentic infrastructure plus portable role adapters. The MVP is Python
3.11+ and uses only the standard library at runtime.

## Architecture

The implementation is intentionally split into small, inspectable layers:

1. `profiler.py` walks a repository while ignoring generated/dependency directories,
   parses root and nested manifests/workflows, and emits a `RepoProfile` with scoped
   evidence paths, `ComponentProfile` entries, repository-native commands, browser-QA
   lifecycle facts, deployment signals, and semantic technology findings.
2. `catalog.py` defines capabilities independently from agents. Built-in capabilities
   are available; Jira, Confluence, and Dify entries are catalogued as optional but have
   no adapters in this MVP.
3. `recommender.py` applies explainable rules from project types and signals to produce
   an `InfrastructurePlan`, including repository contracts, capabilities, available roles,
   assumptions, and questions. Available roles are not a mandatory execution pipeline.
4. `providers.py` optionally resolves uncovered capabilities against a strict local metadata
   catalog. Resolution is read-only: provider sources are never fetched, executed, or installed.
5. `generator.py` writes the portable profile and infrastructure plan only. It does not
   choose a harness, model, concurrency, sandbox, role execution order, or agent topology.
6. `cli.py` exposes the profiling, proposal, adapter, and provider-resolution commands.

The data contract is represented by dataclasses in `models.py`; portable JSON Schema
documents are exported from `schemas.py` for downstream validation.

## Quickstart

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
repo-adaptive-agents --help
```

The runtime has no third-party dependencies. `pytest` is only installed through the
optional `dev` extra. The `.venv/` directory is ignored by Git.

## Usage

Run the focused test suite with the standard-library runner:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

After the editable development install, the same suite can be run with:

```sh
python -m pytest
```

Inspect a profile or infrastructure plan without writing files:

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli profile /path/to/repository
PYTHONPATH=src python3 -m repo_adaptive_agents.cli plan /path/to/repository
```

Generate a portable proposal:

```sh
proposal_parent=$(mktemp -d /tmp/repo-adaptive.XXXXXX)
PYTHONPATH=src python3 -m repo_adaptive_agents.cli propose /path/to/repository \
  --output "$proposal_parent/proposal"
```

`--output` is required. Proposal output must be outside the analyzed repository and must
not already exist. For temporary output, create a private parent directory and use a new
child path as above; do not use `mktemp -u`. The generated directory contains:

- `profile.json` — detected facts and evidence;
- `infrastructure-plan.json` — repository contracts, capabilities, available roles,
  integrations, questions, and assumptions;
- `provider-discovery.json` — capabilities not covered by canonical adapters plus the
  read-only research contract that must be resolved or explicitly deferred before adapter
  roles and targets are recommended.

This core command intentionally generates no Codex, Claude, Copilot, model, concurrency,
sandbox, or execution-plan configuration. Harness adapters remain available through the
explicit experimental `render-role` and `propose-adapters` commands described below.

Version 0.3 changes the core proposal contract: `propose` now requires an explicit output,
writes `infrastructure-plan.json` instead of `team-plan.json`, and no longer generates Codex
TOML. The former experimental `propose-team` command is replaced by the explicit
`propose-adapters` flow.

Version 0.4 removes the unverifiable `--confirm-selection` attestation. Adapter bundles are
always labelled `tool_proposal`; regenerate older bundles before
installation. The exact installation preview is the single decision packet approved by the
user.

Version 0.4.1 makes every harness wrapper self-contained. The backward-compatible `skill`
target is now described explicitly as an optional portable artifact rather than a harness;
Codex, Claude, and Copilot targets never depend on it being installed.

Version 0.4.2 makes destination comparisons symlink-safe, cross-validates adapter decision
metadata against rendered role manifests, and uses adapter-target terminology consistently.

Version 0.4.3 stops turning the `ml_reproducibility` capability into a synthetic
`ml_reviewer` role. Domain knowledge without a canonical provider remains an explicit
capability gap; the generic `independent_reviewer` is still available for read-only review
isolation, but is not presented as ML expertise.

Version 0.5 adds read-only provider resolution. `provider-options` can match explicit
capability gaps against a local, versioned metadata catalog without network access,
downloading provider content, or installing anything.

Version 0.6 adds the missing handoff from deterministic gap detection to optional
agent-assisted provider discovery. `adapter-options` and `provider-options` now emit a
`provider_discovery` brief for capabilities that remain unresolved. The CLI still performs
no network access: the brief tells a Main agent how to compare public candidates, disclose
partial coverage and platform coupling, and return the decision to the user without
downloading, executing, installing, or silently cataloguing a provider.

Version 0.7 makes that handoff enforceable in the canonical adapter flow. When provider gaps
exist, `adapter-options` hides roles and targets and reports only repository facts, gaps, and
the research brief. `propose-adapters` refuses to generate a bundle until every gap has an
explicit decision: select a reviewed catalog provider, leave it unresolved, create local
knowledge, or decompose it. The resulting adapter bundle records those decisions in schema
version 4 so the installation preview remains auditable.

Version 0.7.1 removes the global `roles` and `targets` catalog commands from the adoption
CLI. Repository setup must use `adapter-options <repo>`; it reveals selectable roles and
targets only after the provider-resolution gate is complete. The canonical registries remain
available to the renderer implementation and its tests.

Version 0.8 removes raw provider-outcome flags. Unlocking adapter selection now requires a
schema-versioned `provider_resolution` JSON artifact covering every gap with research status,
evidence or an explicit runtime limitation, up to three fully described candidates, rationale,
and a proposed outcome. These are tool proposals, not claims of user approval. Adapter bundle
schema version 5 embeds the resolution and previews it before installation.

Version 0.9 separates provider research from provider decisions. `provider_research` records
actual provider searches, candidates, coverage limits, and recommendations but cannot unlock
roles or targets. After that evidence is presented, a separate `provider_resolution` records
the user's outcomes. Adapter bundle schema version 6 embeds both artifacts.

Version 0.10 makes discovered providers selectable rather than leaving them only in search
prose. Each search links named results to structured candidates. Users may explicitly select
a `partial_only` candidate without converting that choice into a false claim of full
capability coverage. Adapter bundle schema version 7 preserves this distinction.

Version 0.11 makes `decompose_capability` operational. The parent resolution declares two to
six narrower capabilities with repository evidence. Those subcapabilities receive a separate
research and user-decision phase, and roles/targets remain hidden until it is complete.
Nested decomposition is rejected. Adapter bundle schema version 8 preserves the complete
parent and decomposed decision chain.

Version 0.12 removes the global provider gate. `adapter-options` always exposes deterministic
base roles and targets while reporting provider work through a separate `provider_status`.
Provider research remains available per capability, but it is opt-in and never blocks a base
bundle. If provider artifacts are supplied to `propose-adapters`, their complete validated
research/decision chain is still required and preserved.

## Knowledge provider resolution

Inspect capability gaps using the empty built-in catalog:

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli provider-options /path/to/repository
```

Supply an explicitly chosen local catalog when the team has reviewed provider metadata:

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli provider-options /path/to/repository \
  --catalog /path/to/providers.json
```

Catalog schema version 1 is deliberately small and strict:

```json
{
  "schema_version": 1,
  "providers": [
    {
      "id": "example_ml_review",
      "title": "Example ML review knowledge",
      "capabilities": ["ml_reproducibility"],
      "kind": "skill",
      "source": "https://example.invalid/providers/ml-review",
      "revision": "0123456789abcdef0123456789abcdef01234567",
      "compatible_targets": ["codex"],
      "license": "MIT",
      "review_status": "candidate"
    }
  ]
}
```

`kind` is `skill`, `plugin`, or `manual`; `review_status` is `candidate` or `approved`.
The catalog records provenance and compatibility, not permission to install. The command
does not access `source`, and this MVP intentionally has no provider download or install
command. Unmatched capabilities remain explicit rather than causing a new domain agent to
be invented.

For every unmatched capability, `provider_discovery` supplies:

- the capability objective, repository reason, and local evidence;
- the candidate fields that research must report, including coverage gaps, permissions,
  external requirements, license, revision, trust signals, and platform coupling;
- at most three materially different candidates per capability, with an explicit
  `suitable`, `partial_only`, or `reject` recommendation; reporting no match is valid;
- explicit links from every named provider search result to its structured candidate;
- rules to use primary sources, protect private repository context, and reject inflated
  capability matches;
- available resolution outcomes: select a suitable reviewed candidate, select a partial
  candidate while preserving its remaining gap, leave the gap unresolved, create local
  knowledge, or decompose an over-broad capability and research narrower providers.

The Main agent may perform this read-only research when public network access is permitted;
a dedicated research agent is optional. Research results and recommended outcomes are
advisory: present them and stop for the user's separate resolution before adapter selection.
Catalog entries marked `candidate` remain in this research brief until their coverage has
been reviewed; only an `approved` provider suppresses repeat discovery for the capabilities
it matches.

## Domain model

`RepoProfile` separates `primary_project_types` from secondary characteristics and keeps
`project_types` as their stable combined view. The taxonomy covers web/API/Worker repos,
pipelines and DNS-as-code, executable/desktop applications, local ML inference and
computer vision, shell certificate automation, MCP servers, image-processing tools,
libraries, and unknown repositories. It also records languages, frameworks, manifests,
components, architecture, tests, deployment, integration hints, risks, warnings, and
evidence. `technology_findings` is a focused semantic inventory rather than a copy of every
dependency: it records technologies whose role affects the infrastructure recommendation,
their inferred behavior, local evidence, and whether the versioned catalog recognizes them.
An unclassified workflow tool can therefore still yield `pipeline` and `operations`
capabilities from deployments, entrypoints, schedules, workers/queues, and retries; the plan
then asks the user to confirm the tool's role instead of silently guessing. Each component
records its
path, all manifests declared in that component, project types, frameworks, runtime,
entrypoints, deployment targets, and
evidence. Nested manifests such as `server/proxy/package.json` therefore do not leak
their Express dependency into the root Worker component.

`workflow` records package managers only when an explicit `packageManager` field or
repository lockfile proves them, preserves package scripts by manifest, and classifies
executable development, build, and validation commands without inventing a package manager.
`browser_qa` separately records browser-test tooling, its repository-native commands, and
whether Playwright `webServer` owns server startup and shutdown. Detection is static: the
profiler never launches a server or browser.

Evidence paths are sorted and capped deterministically. Every evidence item includes
`total_count` and `omitted_count`, and `profile_repository(..., evidence_path_limit=N)`
or the CLI option `--evidence-path-limit N` can select a different reporting limit
without changing the underlying detection.

`InfrastructurePlan` carries the repository-native contracts needed by installed tooling and
contains capability recommendations first. Each recommendation has a
selection status (`recommended`, `optional`, `unavailable`, or
`requires_authorization`) and an availability (`available`, `unavailable`, or
`requires_authorization`). Available roles reference capability IDs and carry a rationale,
so a reviewer can trace why a role is useful without implying it must run on every task.
`UserQuestion` records decisions that
cannot be inferred safely.

ML classification requires strong signals: recognized ML frameworks, notebooks,
training/experiment layouts, or model artifact files. Product AI calls,
analytics, generic `model` names, and ordinary frontend/API dependencies are not enough.
Capability evidence is scoped to the rule that selected it. Integration references in
README/docs and agent templates are documentary only; authorization recommendations
require runtime code/configuration, manifests, or declared environment variable names.

Operational repositories are classified with pipeline, automation, CI/CD, and operations
signals from `bin/*.sh`, workflow schedules/manual dispatch, self-hosted runners, API
calls, and side-effecting scripts. Python `requirements.txt` alone is not a library
signal; libraries require packaging metadata or an importable package. Files such as
`scripts/test_*.py` are not tests unless a real test directory, runner configuration,
test command, or test-framework signal is present.

The profiler never reads sensitive-looking files such as `.env`, credentials, secrets,
private keys, or private certificates. It reports their paths as risks only. Symlinks are
ignored by default and links escaping the repository are reported as incomplete-scan
warnings. Invalid JSON/TOML manifests are also reported explicitly instead of being
treated as empty manifests.

Virtual environments and installed dependencies are excluded, including custom names
such as `.venv-certbot`, directories with `pyvenv.cfg`, and `site-packages` or
`dist-packages` trees. Test fixtures and test data remain visible to test detection but
cannot create runtime components or project identities.

Proposal output must be outside the analyzed repository and must not already exist. The
generator validates generated JSON in a temporary sibling directory and then renames it
atomically; it never writes harness configuration into the analyzed repository.

## Fixtures and observed differentiation

The tests use the original stack fixtures plus operational/component regressions:

- `frontend-next`: Next.js/React, npm workflow commands, Playwright-owned server lifecycle,
  Vercel deployment, browser QA, dependency review, and test engineer;
- `cloudflare-worker`: Wrangler/Hono, worker runtime review, security review, and no
  browser QA agent;
- `backend-api`: FastAPI, API contract review, security review, and Jira authorization
  question because the fixture references Jira without a connector;
- `python-ml`: pandas/scikit-learn, an explicit unmapped ML reproducibility capability,
  and no synthetic ML or browser QA agent;
- `pipeline-operational`: Python operational pipeline, scheduled self-hosted CI, Cloudflare
  API, Oracle side effects, and no real test suite;
- `python-library`: packaging metadata plus importable package and tests;
- `hybrid-worker-proxy`: root Worker and nested Express proxy with two deployment targets;
- `worker-with-actions`: Wrangler plus GitHub Actions but one deployment target;
- `operational-test-script`: `scripts/test_ports.py` without a test runner or suite.

The tests assert both the detected project type and that the available role sets
actually differ between fixtures. They verify the portable JSON contracts and parse every
TOML emitted by the opt-in adapter tests.

## Experimental multi-CLI role rendering

> **Experimental, opt-in adapter layer.** This subsystem is separate from the portable
> `profile`/`plan`/`propose` core and covers seven roles in three groups:
>
> - **General read-only review/exploration:** `independent_reviewer`, `repo_explorer`,
>   `api_contract_agent`, `accessibility_performance_reviewer`.
> - **Browser/design roles with optional, host-provided tooling:** `browser_qa`,
>   `design_director`.
> - **Write role (scope required):** `implementation_agent` — the only role with
>   `read_only=False`; it renders only when given an explicit, advisory write scope.

A canonical role is the single source of truth for a role's identity, description, purpose,
capabilities, procedure, constraints, delegation intent, and advisory runtime preferences.
The canonical model in `multi_cli/models.py` contains **no** Codex-, Claude-, or
Copilot-specific fields; the role itself lives in versioned Python in `multi_cli/roles.py`.
Renderers translate that shared description into each tool's format, and the manifest records
exactly what was mapped, omitted, or is tool-specific.

Each output is classified by portability:

- **portable** — the Agent Skill (`SKILL.md`) is the portable materialization of the role;
- **generated** — the Claude Code and GitHub Copilot Markdown agents are thin wrappers
  derived from the canonical content;
- **target_specific** — the Codex TOML embeds runtime semantics (e.g. `sandbox_mode`,
  `model_reasoning_effort`) that do not carry across tools.

Supported targets in the pilot are `skill`, `codex`, `claude`, and `copilot`. The stable CLI
target name `skill` means an optional portable Agent Skill artifact under `.agents/skills/`;
it is not an IDE or harness. Codex, Claude, and Copilot wrappers are self-contained and do
not depend on that artifact, so select `skill` only when the destination intentionally
consumes or versions portable skills. Each target has an isolated renderer, so the three
CLIs are never treated as having identical semantics. During repository adoption, roles and
targets are exposed by `adapter-options <repo>` alongside unresolved provider gaps; the
renderer API keeps deterministic internal registries for development and testing.

Render a proposal (this generates files; it never applies them):

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli render-role \
  repo_explorer \
  --targets skill,codex,claude,copilot \
  --output /tmp/repo-explorer-pilot
```

The command produces:

```
manifest.json
portable/.agents/skills/repo-explorer/SKILL.md
codex/.codex/agents/repo_explorer.toml
codex/.codex/config.fragments/repo_explorer.toml
claude/.claude/agents/repo-explorer.md
copilot/.github/agents/repo-explorer.agent.md
shared/AGENTS.fragment.md
```

The Codex target emits both the agent wrapper and a relative
`codex/.codex/config.fragments/<role>.toml` registration fragment. The fragment contains
only the role description and the wrapper's `config_file`; it has no model or concurrency
settings. It is classified as `target_specific`, included in the manifest, and provided for
manual merge only. Generation never applies it or modifies `.codex/config.toml`.

The output must not already exist and must be outside this repository; generation is atomic
(a temporary sibling is renamed into place) and byte-for-byte deterministic across runs
(`manifest.json` omits any timestamp). `--compare-to ../some-repo` performs a strictly
read-only comparison of the proposal against a destination repo, mapping each wrapper onto
its real location (`codex/.codex/...` → `.codex/...`) and reporting additions, changes/
conflicts, and unchanged files without writing anything.

All six roles are read-only and keep purpose, procedure, response contract, capabilities,
evidence requirements, and critical constraints in the canonical role model.
`repo_explorer` separates confirmed facts from inferences and reports evidence paths;
`api_contract_agent` distinguishes HTTP, RPC/event, schema, client, and documentation
surfaces; `accessibility_performance_reviewer` separates static evidence from runtime
validation and unavailable tooling.

The two browser/design roles treat their extra tooling as **optional and host-provided**,
represented only in the canonical prose. `browser_qa` inspects UI code first and separates
*browser validation performed* (only for interactions actually executed) from *browser
validation required* and *unavailable tooling*; it never claims screenshots, metrics, or
interactions that did not occur, and it does not assume a browser, network, or authentication
is available. `design_director` reviews visual hierarchy, spacing, typography, tokens, and
component consistency, separating evidence from source, visual inference, and runtime
validation still required, without editing assets or inventing design requirements. The
wrappers do **not** guarantee or perform browser execution — no browser was run to produce
them, and none is launched at generation time.

### Manual-validation policy

Manual validation is deliberately sparse and does not repeat per role and per CLI:

- one pilot role (`independent_reviewer`) was validated manually in **all three** CLIs
  (Codex, Claude Code, GitHub Copilot);
- a second role (`repo_explorer`) was validated manually in **two** CLIs (Codex, Claude);
- the remaining roles are covered by the automated suite (TOML, frontmatter, JSON, hashes,
  determinism, and per-role semantics);
- manual re-validation is warranted only when a **renderer, permission model, or tooling
  assumption** changes — not for each new read-only role.

Generation never executes an external CLI, browser, Lighthouse, screen reader, or API
runtime, so no output should be read as evidence that such a tool was run.

### The write role: `implementation_agent`

`implementation_agent` is the only role with `read_only=False`. It renders **only** when
given an explicit write scope, and the scope is **advisory**: nothing here technically
enforces per-path boundaries.

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli render-role implementation_agent \
  --allow-path src/ \
  --allow-path tests/ \
  --block-path src/generated/ \
  --scope-description "Implement the approved parser change" \
  --output /tmp/implementation-agent-pilot
```

- **Scope is mandatory.** Without at least one `--allow-path` and a non-empty
  `--scope-description`, the command fails before writing anything. Read-only roles
  *reject* these flags rather than silently ignoring them.
- **Per-path scoping is advisory, not enforced.** Paths are only lexically validated
  (absolute paths, `..`, `.`, empty, `.git`, NUL bytes, and ambiguous backslashes are
  rejected; non-existent paths are allowed) and then de-duplicated and sorted, so flag
  order never changes the output. No filesystem, symlink, submodule, or working-tree
  checks are performed; the manifest declares these limitations.
- **Codex uses `sandbox_mode = "workspace-write"`**, which limits the *workspace*, not the
  `allowed_paths` — a warning states this explicitly. No `model` is imposed and no
  unconfirmed fields (e.g. `writable_roots`) are emitted. The registration fragment is
  still manual and never applied.
- **Skill, Claude, and Copilot are guidance only** — advisory scope, no technical sandbox,
  and the same guidance-not-enforcement note as every other role.
- **Destructive actions are off:** deletes/renames, commit, push, deploy, and network are
  all disabled in the canonical constraints, and local changes must be preserved.
- Generation still only produces a proposal. **It never runs the implementation agent** and
  applies nothing to any repository. `manifest.json` is now `schema_version: 2` to carry the
  per-target `sandbox`, `write_scope`, `destructive_actions`, `validation_required`, and
  `path_validation` metadata.

The rendering commands deliberately do not apply changes, sync with HOME, install or detect
CLIs, alter `.codex/config.toml`, generate `CLAUDE.md` or
`.github/copilot-instructions.md`, or make network calls. The separate local installer
described below can create reviewed adapter files only after explicit `--apply` and a
separate installation confirmation.

### Explicit adapter bundle: `propose-adapters`

Before selecting anything, obtain the read-only assessment packet:

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli adapter-options ./my-repo
```

If capability-provider gaps exist, it emits repository identity and technologies,
repository-native contracts, recommended capabilities, the gaps, and the provider research
brief alongside deterministic adapter roles and targets. The user may proceed with base
adapters or investigate selected gaps. Optional research must be recorded in a local JSON
artifact outside the target repository. Research records actual provider searches and
recommendations for one or more selected gaps, but never user decisions. Gaps omitted from
that artifact remain explicitly unresearched. An unavailable example is:

```json
{
  "schema_version": 2,
  "kind": "provider_research",
  "capabilities": [
    {
      "capability_id": "ml_reproducibility",
      "research_status": "unavailable",
      "searches": [],
      "candidates": [],
      "evidence": ["Web research tool unavailable: <exact runtime error>"],
      "limitation": "Public network access is unavailable in this runtime.",
      "recommended_outcome": "leave_unresolved",
      "recommended_provider_id": null,
      "rationale": "Preserve the gap until provider research can be completed."
    }
  ]
}
```

Every status requires non-empty evidence. Completed research uses
`research_status: "completed"`, null `limitation`, at least one structured provider search,
and zero to three candidates using every field declared by
`provider_discovery.result_contract`. Search sources are marketplaces, provider repositories,
code search, or web search; product documentation may assess coverage but does not satisfy
provider discovery by itself. Each search includes `discovered_provider_ids`; every ID must
map to a structured candidate, and every candidate must be linked by a search. Unavailable
research must preserve the exact runtime blocker.

Pass only the research artifact first:

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli adapter-options ./my-repo \
  --provider-research /tmp/my-provider-research.json
```

The output continues to expose base adapter choices and also asks for one provider outcome per
researched capability. The user may ignore that optional branch or record decisions separately:

```json
{
  "schema_version": 3,
  "kind": "provider_resolution",
  "decisions": [
    {
      "capability_id": "ml_reproducibility",
      "outcome": "leave_unresolved",
      "provider_id": null,
      "decomposition": [],
      "rationale": "The user chose to keep this gap explicit for now."
    }
  ]
}
```

Then rerun `adapter-options` with both artifacts. A selected provider must be a `suitable`
research candidate and must also exist in the supplied reviewed catalog. Neither artifact
downloads or installs providers, and the command always writes nothing.
`select_partial_provider` may reference a `partial_only` research candidate without
claiming the full capability is resolved; its exact coverage and remaining gaps stay in the
decision packet.

When the user chooses `decompose_capability`, that decision must contain `decomposition` with
two to six objects containing `capability_id`, `title`, `objective`, `repository_reason`, and
non-empty repository `evidence`. Rerunning `adapter-options` reports
`provider_status: decomposed_research_optional` and a research brief for those narrower capabilities.
Pass the resulting artifacts through `--decomposed-provider-research` and, after the user
reviews that research, `--decomposed-provider-resolution`. The second resolution rejects
nested decomposition. Base adapter choices remain available throughout.
A reviewed provider catalog remains strict: only the exact subcapability IDs declared by the
validated parent resolution are accepted in addition to the global capability registry.

`propose-adapters` profiles a repository and renders only the read-only roles and adapter targets
supplied by the caller. The result is always a tool proposal: roles and targets remain
recommendations until the user approves the exact installation preview. Exact capability IDs connect the portable
`InfrastructurePlan` to compatible canonical roles; they explain eligibility but never
select, schedule, or invoke an agent.

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli propose-adapters ./my-repo \
  --targets skill,codex,claude,copilot \
  --role repo_explorer \
  --role browser_qa \
  --provider-research /tmp/my-provider-research.json \
  --provider-resolution /tmp/my-provider-resolution.json \
  --decomposed-provider-research /tmp/my-decomposed-provider-research.json \
  --decomposed-provider-resolution /tmp/my-decomposed-provider-resolution.json \
  --output /tmp/my-adapters
```

`propose-adapters` needs no provider artifacts for a base bundle. When any provider artifact
or catalog is supplied, every researched capability in that optional branch needs a matching
decision. Decomposed research may likewise cover a selected subset of declared
subcapabilities; the rest remain visible as unresearched. Incomplete or malformed supplied
branches fail before output is created. Adapter bundle
`manifest.json` schema version 8 embeds the parent and decomposed artifacts and their derived
outcomes; installation previews display their research status, candidate count, and rationale
before roles and file additions. The decomposed flags are required only when the parent
resolution contains `decompose_capability`.

The agent-led adoption flow keeps base setup and provider discovery separate:

1. run `propose` or `adapter-options`; present repository facts, provider gaps, and the
   deterministic role/target options. The user may proceed directly with a base bundle;
2. only when requested, research selected provider gaps and present candidates, evidence,
   limitations, and recommendations for separate decisions;
3. if the user wants provider outcomes embedded, complete `provider_resolution` and any
   decomposed research/resolution branch. Otherwise omit all provider arguments;
4. render a proposal, preview installation, show any recorded provider outcomes, proposed
   roles/targets, and exact additions, then stop for approval. Approval of that exact preview
   accepts both the selection and the file plan;
5. only after that approval, run
   `install-adapters --apply --confirm-install`.

The CLI cannot prove whether a proposal came from a human when agent and user share the
same permissions, so it never claims prior user approval. Resolution outcomes,
recommendations, CLI arguments, capability matches, and repository facts must not be
described as user choices before the installation preview is approved. Both `--targets` and
at least one `--role` are required. A user may explicitly choose a read-only role without a
deterministic capability match (for example, design judgment);
the manifest records empty match evidence rather than pretending the profiler inferred it.
`implementation_agent` remains available only through `render-role` with an explicit write
scope. `--compare-to DIR` performs a strictly read-only comparison with a destination.

The output layout is:

```
OUTPUT/
  manifest.json            # explicit selections, matches, targets, hashes, and assumptions
  profile.json
  infrastructure-plan.json
  roles/<role-id>/          # a full per-role proposal (manifest.json + portable/codex/…)
```

The bundle contains no execution plan, parallel groups, consolidator, concurrency, or model
choice. No independent reviewer is added automatically. Enforcement differs by target
exactly as for `render-role` (Codex sandbox versus advisory Skill/Claude/Copilot), and no
adapter or browser is executed. Generation is atomic and byte-for-byte deterministic.

### Safe local installation: `install-adapters`

Installation is a separate step. Preview is the default and is strictly read-only:

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli install-adapters \
  /tmp/my-adapters /path/to/repository
```

The preview is a decision packet, not just a file list. It reports detected repository
facts, selected and alternative adapter targets, each selected adapter's purpose and match
evidence, other matched and preference-based adapters, repository roles without a canonical
adapter, the functional effect, and the exact additions/conflicts. This output is generated
from the validated bundle so approval does not depend on an agent supplying a complete
narrative. An agent must relay this decision summary with the exact install plan; a
file-only approval request is insufficient.

Every bundle is a tool proposal and may be previewed. The preview is the authoritative
decision packet for roles, targets, and exact file additions.

After reviewing the additions, installation requires an explicit flag:

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli install-adapters \
  /tmp/my-adapters /path/to/repository --apply --confirm-install
```

`--confirm-install` is a caller attestation that the user reviewed the exact preview and
approved its proposed roles, targets, and file additions in a later interaction. It is not
identity proof; a harness must enforce human approval if that guarantee is required. The
preview prints an explicit stop instruction so an agent does not apply in the same turn.

The installer validates the complete bundle, maps only target adapter files, and excludes
bundle manifests, profile reports, and shared fragments. Existing identical files are left
unchanged. A differing file, directory collision, destination symlink, unsafe parent, or
source symlink is a conflict and blocks the whole operation before writing. There is no
force or overwrite mode. If creation fails partway through, rollback is limited to files
and empty directories created by that invocation.

The command installs locally only. It does not merge Codex registration fragments into
`.codex/config.toml`, write to HOME, install a CLI, commit, push, deploy remotely, or run an
agent.

### Security note

Agent instruction files are **not enforcement**. The constraints rendered into each wrapper
(read-only, no commit/push/deploy, no network, no recursive delegation) are guidance for the
agent; they must continue to be enforced by CI, sandboxing, and repository/organization
policies. Do not import third-party skills automatically, and review every generated proposal
before copying any file into a real repository.

## Explicit MVP limits

This version does not call Jira, Confluence, Dify, MCP servers, browsers, LLMs, package
registries, documentation sites, or remote
deployment systems. It does not read credential values, install integrations, overwrite
existing repository files, commit, push, deploy remotely, create a PR, or provide a UI. Manifest parsing
and framework detection are intentionally conservative. Generic local behavior is detected
independently from brand names; unfamiliar orchestration technology is reported as
`unclassified` with a user question and is never researched or added to the catalog
automatically.

## Next steps

1. Add a versioned profile/plan schema validator and fixture cases for more behavioral patterns.
2. Add a machine-readable install-plan output if automation consumers require it.
3. Add explicit organization/team policy input with precedence over local preferences.
4. Expand canonical adapter coverage only where portable capability contracts exist.
5. Add a reviewable interactive workflow after the deterministic CLI contract stabilizes.
