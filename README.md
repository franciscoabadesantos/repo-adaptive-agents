# repo-adaptive-agents

This branch contains the first vertical slice of **shared team knowledge for coding
agents**. An engineer can contribute ordinary Markdown in a Git repository, inspect the
catalog, and load it through the validated native control boundary.

Live model calls and the Codex integration are not implemented yet. Increment one proves
the repository workflow and native enforcement before an agent is connected.

## Try the shared-knowledge workflow

Python 3.11 or newer is required.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

cd /path/to/an/existing/git/repository
team-knowledge init --team payments
team-knowledge add \
  --title "Settlement retry contract" \
  --summary "Use when changing settlement retry behavior." \
  --body "Preserve the original idempotency key across every retry."
team-knowledge list
team-knowledge check
```

Initialization creates this Git-friendly layout:

```text
.team-knowledge/
  config.json
  .gitignore
  items/
    .gitkeep
    tk-<generated-id>.md
```

Each item is readable Markdown with minimal frontmatter: generated ID, title, usefulness
summary, owner, state, and revision. The body remains ordinary Markdown. Commit and review
these files through the team's normal pull-request workflow.

Useful commands:

```sh
team-knowledge add --help
team-knowledge list
team-knowledge show tk-<generated-id>
team-knowledge check
team-knowledge revoke tk-<generated-id>
```

`revoke` preserves the file and Git history while making the item unavailable. `check`
rejects malformed content and verifies the real native catalog mapping. Local pilot events
are written to the ignored `.team-knowledge/events.jsonl`; they contain identifiers and
outcomes, never prompts, source code, model responses, or knowledge bodies.

## Runtime boundary in increment one

`repo_adaptive_agents.shared_knowledge` translates the simple Markdown contract into the
existing `repo_adaptive_agents.admission_control` domain model. It uses the existing
repository-instruction payload; no new resource ontology was added.

The service can expose an admitted ID/title/summary index, pass externally chosen IDs to
native validation, and return bodies and canonical citation labels only for validated
items. It performs no keyword matching, semantic ranking, capability inference, or other
deterministic relevance selection.

## Development

```sh
python -m pytest
```

The complete increment-one behavior and deferred work are defined in
[`V0_1_PRODUCT_SPEC.md`](V0_1_PRODUCT_SPEC.md).

## Research and legacy tooling

The public-safe research decision record is in [`docs/research/`](docs/research/README.md).
Private gold, raw model outputs, and complete evaluation trees remain outside normal Git
history.

The older repository profiler, capability recommender, provider flow, role renderer, and
adapter installer remain temporarily available through commands marked `legacy`. They are
not the shared-knowledge product path and will be considered for removal separately.
