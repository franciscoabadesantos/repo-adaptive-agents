# Shared team knowledge for coding agents

Write a reusable Codex Skill once in a team-owned Git repository, then let each engineering
repository install only the Skills a model judges likely to be relevant. The source stays
canonical: `team-knowledge sync` distributes central improvements and revocations without
manual copying.

This first vertical is deliberately narrow: one team, native Agent Skills, Codex selection,
Git-backed review, and local generated copies. It has no hosted service, semantic ranking
engine, capability ontology, or management dashboard.

## Install

Python 3.11+, Git, and an installed and authenticated Codex CLI are required. From a clone of
this project:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
team-knowledge --help
```

## Canonical team repository

The team maintains ordinary Agent Skills in a separate Git repository:

```text
team-knowledge.json
skills/
  dns/
    SKILL.md
    team-knowledge.json
    references/
      review.md
```

The root descriptor identifies the source and its team:

```json
{
  "schema_version": 1,
  "source_id": "platform-team-knowledge",
  "organization": "example-company",
  "team": "platform"
}
```

Each Skill uses the standard `name` and `description` frontmatter in `SKILL.md`. Its small
sidecar contains only stable identity and lifecycle:

```json
{
  "schema_version": 1,
  "id": "dns-operations",
  "state": "active"
}
```

Review changes to this repository through normal Git pull requests. Skills must be safe,
UTF-8 text packages: `SKILL.md` plus optional text references. Symlinks, executable files,
`scripts/`, and binary bundles are rejected.

## Five-minute consumer workflow

In an existing engineering repository, run:

```sh
team-knowledge bootstrap \
  --source https://github.example/platform/team-knowledge.git \
  --ref main
```

Bootstrap profiles factual repository evidence, gives that evidence and admitted Skill
`id/name/description` metadata to Codex, and presents a plan. After reviewing it, answer `y`
(or use `--yes` in automation). Then commit only the distribution state:

```sh
git add .team-knowledge/config.json .team-knowledge/lock.json .team-knowledge/.gitignore
git commit -m "Bootstrap shared team knowledge"
```

Validated Skills are materialized locally at `.agents/skills/<name>/`, where Codex discovers
them natively. Generated copies and the Git source cache remain local. Bootstrap adds only
the exact managed Skill paths to `.git/info/exclude`; it does not hide other Agent Skills.

When the canonical team repository changes:

```sh
team-knowledge sync
git add .team-knowledge/lock.json
git commit -m "Sync shared team knowledge"
```

The plan automatically updates already-selected Skills and removes explicitly revoked ones.
New Skills or changed repository evidence trigger a fresh Codex selection. A previously
selected Skill that Codex no longer selects is reported but retained for human review.

If Codex is unavailable during sync, safe deterministic updates and revocations can still be
applied while semantic additions are deferred. If the Git source is unavailable, existing
local Skills and the lock remain untouched. `team-knowledge sync --offline` verifies the
locked local state without claiming freshness.

See [Cross-repository team knowledge](docs/CROSS_REPOSITORY_TEAM_KNOWLEDGE.md) for the exact
formats, safety rules, and sync behavior.

## Repository-local knowledge

The earlier one-repository workflow remains available for teams that are not yet distributing
canonical Skills:

```sh
team-knowledge init --codex
team-knowledge add \
  --title "Settlement retry contract" \
  --summary "Use when changing settlement retry behavior." \
  --body "Preserve the original idempotency key across every retry."
team-knowledge check
```

Its repository-local Codex Skill uses `index --json` and `use --exposure ... --json` to expose
metadata, request native-validated bodies, and disclose successful use as:

```text
Used team knowledge: Settlement retry contract
```

Feedback remains lightweight and local:

```sh
team-knowledge feedback tk-<id> useful
team-knowledge feedback tk-<id> outdated
team-knowledge feedback tk-<id> incorrect
team-knowledge revoke tk-<id>
```

See [Writing useful team knowledge](docs/TEAM_KNOWLEDGE_GUIDE.md) and the
[pilot operator checklist](docs/PILOT_OPERATOR.md).

## Architecture boundary

Codex owns semantic relevance. The product supplies bounded factual repository evidence and
Skill routing metadata; it contains no keyword fallback or deterministic semantic selector.
The existing native admission layer independently enforces exposure and final exact-resource
validation before any canonical Skill is materialized.

The older profiler, provider, role, and adapter commands remain legacy and are not part of
the shared-knowledge product path. Public-safe research history is under
[`docs/research/`](docs/research/README.md).
