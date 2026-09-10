# Shared team knowledge for coding agents

Write a reusable Agent Skill once in a team-owned Git catalog, then let each engineering
repository install only the Skills a model judges likely to be relevant. Choose Codex,
Claude, or Copilot for that semantic selection step. The source stays
canonical: `team-knowledge sync` distributes central improvements and revocations without
manual copying.

This first vertical is deliberately narrow: one team, native Agent Skills, one explicitly
selected model CLI, Git-backed review, and local generated copies. It has no hosted service, semantic ranking
engine, capability ontology, or management dashboard.

## Install

Python 3.11+, Git, and one installed and authenticated selector CLI (`codex`, `claude`, or
`copilot`) are required. Codex is the default. From a clone of this project:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
team-knowledge --help
```

## Canonical team catalog

For the first team trial, the canonical catalog lives alongside this product's code in the
`team-knowledge/` subtree:

```text
team-knowledge/
  team-knowledge.json
  skills/
```

The root descriptor identifies the source and its team:

```json
{
  "schema_version": 1,
  "source_id": "repo-adaptive-agents-team-knowledge",
  "organization": "repo-adaptive-agents",
  "team": "engineering"
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
team-knowledge bootstrap
```

By default, the tool fetches the `main` branch of `repo-adaptive-agents` and reads only its
`team-knowledge/` catalog. Product code and team knowledge share Git hosting for this trial,
but remain separate logical assets with independent source paths, revisions, and lifecycle.

To use a different dedicated canonical Git repository whose catalog is at the repository root,
override the source:

```sh
team-knowledge bootstrap --source <git-repository>
```

For a catalog in a subdirectory, provide that path explicitly:

```sh
team-knowledge bootstrap \
  --source <git-repository> \
  --catalog-path team-knowledge
```

An explicit source defaults to the external-root behavior (`.`). The chosen URL, ref, and
catalog path are recorded so later syncs never silently migrate to a different default.

Bootstrap profiles factual repository evidence, gives that evidence and admitted Skill
`id/name/description` metadata to the chosen model selector, and presents a plan. Selectors
are explicit; there is no auto-detection or semantic fallback:

```sh
team-knowledge bootstrap --selector claude
TEAM_KNOWLEDGE_SELECTOR=copilot team-knowledge bootstrap
```

The CLI prints each phase, including when it starts and finishes the isolated AI selection.
Before an interactive approval it repeats the exact local write boundary; approval never commits,
pushes, deploys, or changes application source files.

When more than one validated Skill is recommended during an interactive bootstrap, the CLI first
offers numbered choices. Keep all recommendations or select a subset (for example, only Dify and
not Jira); only that subset is then written to the lock and shown in the final approval form.
`--yes` is explicit automation consent for the complete validated recommendation set.

A canonical source may opt into schema version 2 and declare
`organization_default_skill_ids`. During a normal bootstrap, those active Skill IDs are presented
and enforced as auditable defaults only when the repository's Git remote owner exactly matches the
descriptor's `organization`. They are never cross-organization defaults and are not injected for an
explicit `--task`, which remains a separate semantic request.

The command-line flag takes precedence over `TEAM_KNOWLEDGE_SELECTOR`; otherwise Codex is
used. The selector is an invocation choice, not repository state, and is not written to the
config or lock. After reviewing the plan, answer `y`
(or use `--yes` in automation). Then commit only the distribution state:

```sh
git add .team-knowledge/config.json .team-knowledge/lock.json .team-knowledge/.gitignore
git commit -m "Bootstrap shared team knowledge"
```

Declining the bootstrap plan leaves no `.team-knowledge/` state or generated Skill package in
the consumer repository.

To prepare a repository for work it does not yet contain, provide the concrete goal as transient
model input. It is never written to the config, lock, or generated Skill package:

```sh
team-knowledge bootstrap --task "Implement Jira issue automation for this service"
```

For natural-language onboarding in every supported coding agent, install the same portable
preparation Skill once at the user-level locations for Codex, Claude, and Copilot:

```sh
team-knowledge setup --dry-run
team-knowledge setup
```

After that, in any repository, a request such as “prepare this repository to implement Jira
automation; ask if a material detail is missing” invokes the local onboarding Skill. It shows a
plan and never applies, commits, or pushes without confirmation.

### New-machine setup

The CLI is the shared foundation: it is independent of Codex, Claude, and Copilot. Install Python
3.11+, Git, and the coding agents a person will use, then install the organization’s canonical
distribution once. With access to a private organization source, a typical isolated install is:

```sh
pipx install "git+https://github.com/<organization>/<team-knowledge-repository>.git@main"
team-knowledge setup
```

`setup` installs the same portable onboarding Skill for all three agents and reports whether their
CLIs are currently available on `PATH`; it does not install, authenticate, configure, or silently
substitute any coding agent. A person needs Git access to the private source and must sign in to the
agent they choose. By default it prepares all three agents, including ones installed later. Use
`team-knowledge setup --selector claude --only` to limit onboarding to one agent. A Codex plugin can later package the same conversational onboarding, but it is optional:
the CLI remains the cross-agent installation path.

Set the user-level default semantic selector during setup; it is stored in the person's local
configuration, never in a repository or lock:

```sh
team-knowledge setup --selector claude
```

For one command only, `--selector` wins; `TEAM_KNOWLEDGE_SELECTOR` wins next, then the saved user
preference, with Codex as the final fallback.

Validated Skills are materialized once at `.agents/skills/<name>/`, the vendor-neutral Agent
Skills location used directly by Codex and Copilot. Claude receives a relative directory
symlink at `.claude/skills/<name>` pointing to that same package. Generated packages, Claude
bridges, and the Git source cache remain local. Bootstrap adds only the exact managed paths
to `.git/info/exclude`; it does not hide other Agent Skills.

When the canonical team repository changes:

```sh
team-knowledge sync
git add .team-knowledge/lock.json
git commit -m "Sync shared team knowledge"
```

The plan automatically updates already-selected Skills and removes explicitly revoked ones.
New Skills or changed repository evidence trigger a fresh selection using the selector chosen
for that invocation. A previously selected Skill the model no longer selects is reported but
retained for human review. Changing only `--selector` does not itself trigger reassessment.

If the configured selector is unavailable during sync, safe deterministic updates and revocations can still be
applied while semantic additions are deferred. If the Git source is unavailable, existing
local Skills and the lock remain untouched. `team-knowledge sync --offline` verifies the
locked local state without claiming freshness.

Unrelated product-code commits do not advance the effective team-knowledge revision or churn
consumer locks. Commits under `team-knowledge/` do. See
[Cross-repository team knowledge](docs/CROSS_REPOSITORY_TEAM_KNOWLEDGE.md) for the exact
formats, safety rules, and sync behavior.

## Architecture boundary

The explicitly chosen model owns semantic relevance. The product supplies bounded factual repository evidence and
Skill routing metadata; it contains no keyword fallback or deterministic semantic selector.
The existing native admission layer independently enforces exposure and final exact-resource
validation before any canonical Skill is materialized.
