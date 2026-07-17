# repo-adaptive-agents

Deterministic bootstrapper that analyzes a local repository and proposes tailored Codex
and multi-CLI agent teams. The MVP is Python 3.11+ and uses only the standard library at
runtime.

## Architecture

The implementation is intentionally split into small, inspectable layers:

1. `profiler.py` walks a repository while ignoring generated/dependency directories,
   parses root and nested manifests/workflows, and emits a `RepoProfile` with scoped
   evidence paths and `ComponentProfile` entries.
2. `catalog.py` defines capabilities independently from agents. Built-in capabilities
   are available; Jira, Confluence, and Dify entries are catalogued as optional but have
   no adapters in this MVP.
3. `recommender.py` applies explainable rules from project types and signals to produce
   a `TeamPlan`, including capability status, minimal agents, assumptions, and questions.
4. `generator.py` renders `config.toml`, agent TOMLs, and JSON reports. It writes to a
   proposal directory and computes a diff against an existing `.codex/` without changing
   that existing configuration.
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

Inspect a profile or team plan without writing files:

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli profile /path/to/repository
PYTHONPATH=src python3 -m repo_adaptive_agents.cli plan /path/to/repository
```

Generate a proposal and show its TOML diff against `/path/to/repository/.codex/`:

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli propose /path/to/repository \
  --output /tmp/repo-adaptive-proposal
```

The default output directory is `.codex-proposal`, deliberately separate from an
existing `.codex/`. `--existing` can point at another baseline. The generated directory
contains:

- `config.toml` and `agents/*.toml` — the proposed Codex configuration;
- `profile.json` — detected facts and evidence;
- `team-plan.json` — capabilities, agents, integrations, questions, and assumptions.

## Domain model

`RepoProfile` separates `primary_project_types` from secondary characteristics and keeps
`project_types` as their stable combined view. The taxonomy covers web/API/Worker repos,
pipelines and DNS-as-code, executable/desktop applications, local ML inference and
computer vision, shell certificate automation, MCP servers, image-processing tools,
libraries, and unknown repositories. It also records languages, frameworks, manifests,
components, architecture, tests, deployment, integration hints, risks, warnings, and
evidence. Each component records its
path, all manifests declared in that component, project types, frameworks, runtime,
entrypoints, deployment targets, and
evidence. Nested manifests such as `server/proxy/package.json` therefore do not leak
their Express dependency into the root Worker component.

Evidence paths are sorted and capped deterministically. Every evidence item includes
`total_count` and `omitted_count`, and `profile_repository(..., evidence_path_limit=N)`
or the CLI option `--evidence-path-limit N` can select a different reporting limit
without changing the underlying detection.

`TeamPlan` contains capability recommendations first. Each recommendation has a
selection status (`recommended`, `optional`, `unavailable`, or
`requires_authorization`) and an availability (`available`, `unavailable`, or
`requires_authorization`). Agents reference capability IDs and carry a rationale, so a
reviewer can trace why an agent was selected. `UserQuestion` records decisions that
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
generator validates all generated TOML/JSON in a temporary sibling directory and then
renames it atomically; it never merges or overwrites an existing `.codex/` tree.

## Fixtures and observed differentiation

The tests use the original stack fixtures plus operational/component regressions:

- `frontend-next`: Next.js/React, browser QA, dependency review, and test engineer;
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

The tests assert both the detected project type and that the recommended agent sets
actually differ between fixtures. They also parse every generated TOML file and verify
JSON serialization.

## Experimental multi-CLI role rendering

> **Experimental pilot.** This subsystem is separate from the deterministic profiler above
> and covers seven roles in three groups:
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

What this pilot deliberately does **not** do: apply changes, write
into a target repo, sync with HOME, install or detect CLIs, alter `.codex/config.toml`,
generate `CLAUDE.md` or `.github/copilot-instructions.md`, or make any network call. The
Copilot output is a **custom agent**, not inline-autocomplete configuration and not a
replacement for `copilot-instructions`; the manifest states this explicitly.

### End-to-end team proposal: `propose-team`

`propose-team` profiles a repository, recommends a **read-only** team with explicit
deterministic rules, and renders every selected role to the requested targets — one
sub-proposal per role plus an aggregated manifest.

```sh
PYTHONPATH=src python3 -m repo_adaptive_agents.cli propose-team ./my-repo \
  --targets skill,codex,claude,copilot \
  --output /tmp/my-team
```

Roles are chosen by **explicit, deterministic rules** over the existing profiler's signals
(no LLM, no scoring, no learning):

- `repo_explorer` — any non-empty repository;
- `api_contract_agent` — an API surface detected by the profiler (HTTP/RPC/event/schema);
- `browser_qa` and `accessibility_performance_reviewer` — a detected frontend web project
  (the accessibility role never claims that a browser, Lighthouse, or performance tool was
  run — those remain runtime checks it flags as required);
- `design_director` — strong structural design signals only (a `.storybook` directory, a
  `tailwind.config.*`, a `design-tokens` directory, or a design-token file), never vague
  README wording;
- `independent_reviewer` — added as the **consolidator** when more than one specialized
  role is selected;
- `implementation_agent` — **never** selected automatically; it is always listed under
  `excluded_roles` because it requires an explicit brief and write scope. `propose-team`
  rejects it in `--include-role`.

`--include-role` (read-only roles only) forces a role in; `--exclude-role` drops one; their
order never changes the output. `--compare-to DIR` performs a strictly read-only comparison
of the rendered roles against a destination repo and records additions/changes/unchanged in
the manifest. The output layout:

```
OUTPUT/
  manifest.json            # aggregated: profile summary, selected/excluded roles with
  team/AGENTS.fragment.md   # reasons+evidence+confidence, execution plan, per-role hashes
  roles/<role-id>/          # a full per-role proposal (manifest.json + portable/codex/…)
```

The **execution plan** is data only — no agent is run: `repo_explorer` first, specialized
read-only roles in a parallel group, and `independent_reviewer` consolidating last when
selected. Enforcement differs by target exactly as for `render-role` (Codex sandbox vs.
advisory Skill/Claude/Copilot), and browser/design tooling is never executed. Generation is
atomic, byte-for-byte deterministic (no timestamps), writes only under `--output`, and never
touches the analyzed repository, `.codex/config.toml`, or HOME.

### Security note

Agent instruction files are **not enforcement**. The constraints rendered into each wrapper
(read-only, no commit/push/deploy, no network, no recursive delegation) are guidance for the
agent; they must continue to be enforced by CI, sandboxing, and repository/organization
policies. Do not import third-party skills automatically, and review every generated proposal
before copying any file into a real repository.

## Explicit MVP limits

This version does not call Jira, Confluence, Dify, MCP servers, browsers, LLMs, or remote
deployment systems. It does not read credential values, install integrations, mutate an
existing `.codex/`, commit, push, deploy, create a PR, or provide a UI. Manifest parsing
and framework detection are intentionally conservative; unusual build systems and
custom conventions may be reported as `unknown` and should be reviewed before use.

## Next steps

1. Add a versioned profile/plan schema validator and fixture cases for more languages.
2. Add a safe merge planner that preserves existing `.codex` files and reports conflicts.
3. Add explicit organization/team policy input with precedence over local preferences.
4. Add opt-in adapters behind authorization boundaries, starting with read-only context.
5. Add a reviewable interactive workflow after the deterministic CLI contract stabilizes.
