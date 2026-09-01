# Shared team knowledge for coding agents

This repository contains a one-team v0.1 for contributing useful engineering knowledge
once and reusing it safely with Codex. Knowledge is ordinary Markdown reviewed through the
repository's normal Git workflow.

## Team quickstart

Python 3.11 or newer is required.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

cd /path/to/an/existing/git/repository
team-knowledge init --team payments --codex
team-knowledge add \
  --title "Settlement retry contract" \
  --summary "Use when changing settlement retry behavior." \
  --body "Preserve the original idempotency key across every retry."
```

Commit `.team-knowledge/` and `.agents/skills/team-knowledge/SKILL.md`, then use Codex in
that repository. For a relevant coding task, the Skill tells Codex to inspect the knowledge
index, choose relevant IDs, request their validated bodies, and disclose only knowledge it
actually used:

```text
Used team knowledge: Settlement retry contract
```

The integration is one inspectable Agent Skill. It contains no catalog, ranking, admission,
or validation implementation.

## Everyday commands

```sh
team-knowledge add --help
team-knowledge list
team-knowledge show tk-<generated-id>
team-knowledge check
team-knowledge revoke tk-<generated-id>
team-knowledge feedback tk-<generated-id> useful
team-knowledge feedback tk-<generated-id> outdated
team-knowledge feedback tk-<generated-id> incorrect
```

Feedback records a local event and never changes or revokes the item automatically.

Initialization creates readable, Git-backed product files:

```text
.team-knowledge/
  config.json
  .gitignore
  items/
    .gitkeep
    tk-<generated-id>.md
.agents/
  skills/
    team-knowledge/
      SKILL.md
```

Local events stay in ignored `.team-knowledge/events.jsonl`. Exact exposure receipts stay
in ignored `.team-knowledge/runtime/`, which remains writable in the Codex workspace
sandbox. Neither contains prompts, source code, model responses, or knowledge bodies.

## Agent CLI contract

The Skill uses two machine-readable commands:

```sh
team-knowledge index --json
team-knowledge use --exposure exp-... --json tk-...
```

`index` returns only an exposure ID and admitted ID/revision/title/summary entries. It never
returns bodies, owners, lifecycle details, or control traces. The model decides semantic
relevance.

`use` reloads that exact native exposure receipt, re-reads current Markdown, runs native
validation, and returns bodies and citation titles only for validated resources. Changed,
revoked, unknown, or unexposed selections appear as rejected without their bodies.

Ordinary knowledge may remain title/summary-visible when later inadmissible, but cannot
survive final validation. Add `--restricted` when creating content that must also be
withheld before selection.

## Architecture and development

The thin translation in `repo_adaptive_agents.shared_knowledge` maps Markdown to the native
`SHARED_KNOWLEDGE` resource type in `repo_adaptive_agents.admission_control`. It does not
perform keyword matching, semantic ranking, capability inference, or coverage scoring.

```sh
python -m pytest
```

The complete scope and limitations are in [`V0_1_PRODUCT_SPEC.md`](V0_1_PRODUCT_SPEC.md).
The public-safe research decision record is in [`docs/research/`](docs/research/README.md).

The older profiler, provider, role, and adapter commands remain marked `legacy`; they are
not part of the shared-knowledge product path.
