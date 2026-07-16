# repo-adaptive-agents

Deterministic bootstrapper that analyzes a local repository and proposes a tailored
Codex multi-agent team. The MVP is Python 3.11+ and uses only the standard library at
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
