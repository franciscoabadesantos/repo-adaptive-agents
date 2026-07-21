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
4. `generator.py` writes the portable profile and infrastructure plan only. It does not
   choose a harness, model, concurrency, sandbox, role execution order, or agent topology.
5. `cli.py` exposes profile, plan, and propose commands.

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
  integrations, questions, and assumptions.

This core command intentionally generates no Codex, Claude, Copilot, model, concurrency,
sandbox, or execution-plan configuration. Harness adapters remain available through the
explicit experimental `render-role` and `propose-adapters` commands described below.

Version 0.3 changes the core proposal contract: `propose` now requires an explicit output,
writes `infrastructure-plan.json` instead of `team-plan.json`, and no longer generates Codex
TOML. The former experimental `propose-team` command is replaced by the explicit
`propose-adapters` flow.

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
- `python-ml`: pandas/scikit-learn, ML reproducibility review, and no browser QA agent;
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

Supported targets in the pilot are `skill`, `codex`, `claude`, and `copilot` (also printed by
`repo-adaptive-agents targets`; roles by `repo-adaptive-agents roles`). Each has an isolated
renderer, so the three CLIs are never treated as having identical semantics. The roles are
listed deterministically by `repo-adaptive-agents roles`.

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

Before selecting anything, obtain the read-only decision packet:

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli adapter-options ./my-repo
```

It emits a self-contained decision packet: repository identity and technologies,
repository-native contracts, recommended capabilities, deterministically matched adapters,
preference-based options, capabilities and plan roles without canonical adapters, every
supported harness target, and two explicit user questions. Consumers should present these
facts and coverage gaps before asking for roles and targets. It writes nothing.

`propose-adapters` profiles a repository and renders only the read-only roles and harnesses
supplied by the caller. Without `--confirm-selection`, the result is explicitly an
unconfirmed proposal: it can be previewed but cannot be installed. Exact capability IDs connect the portable
`InfrastructurePlan` to compatible canonical roles; they explain eligibility but never
select, schedule, or invoke an agent.

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli propose-adapters ./my-repo \
  --targets skill,codex,claude,copilot \
  --role repo_explorer \
  --role browser_qa \
  --confirm-selection \
  --output /tmp/my-adapters
```

The agent-led adoption flow retains two separate gates:

1. run `profile`, `plan`, and `adapter-options`; present its two unresolved questions and
   ask the user to choose roles and targets;
2. an agent may render an unconfirmed proposal for review, but it must describe it as a
   recommendation rather than a user choice; after the user chooses, regenerate the bundle
   with `propose-adapters --confirm-selection`, preview installation,
   show the exact additions, and stop to request a second approval;
3. only after the user separately approves that exact preview, run
   `install-adapters --apply --confirm-install`.

The confirmation flag is a caller attestation, not identity proof. Unconfirmed proposals
are useful for audit and discussion but are mechanically non-installable. Recommendations, CLI
arguments, capability matches, and repository facts must never be described as user choices
before the user actually answers. Both `--targets` and at least one `--role` are required. A user may explicitly choose a
read-only role without a deterministic capability match (for example, design judgment);
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
facts, selected and alternative harness targets, each selected adapter's purpose and match
evidence, other matched and preference-based adapters, repository roles without a canonical
adapter, the functional effect, and the exact additions/conflicts. This output is generated
from the validated bundle so approval does not depend on an agent supplying a complete
narrative. An agent must relay this decision summary with the exact install plan; a
file-only approval request is insufficient.

Both confirmed and unconfirmed bundles may be previewed. An unconfirmed preview instructs
the caller to collect the user's role/target choice and regenerate the bundle. Apply remains
blocked until that confirmed bundle exists.

After reviewing the additions, installation requires an explicit flag:

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli install-adapters \
  /tmp/my-adapters /path/to/repository --apply --confirm-install
```

`--confirm-selection` covers only the earlier choice of roles and targets. It is not
installation approval. `--confirm-install` is a separate caller attestation that the user
reviewed the exact preview and approved applying it in a later interaction. The preview
prints an explicit stop instruction so an agent does not collapse both decisions into one.

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
