# Five-minute teammate tryout

The team owns canonical Agent Skills centrally. Bootstrap examines factual evidence from a
repository, asks the selected model which admitted Skills are likely to belong there, passes
the selected IDs through native validation, and makes only validated standard Skills
available to supported coding agents.

The selector provider and the coding agent used later are independent. Selecting Skills with
Claude does not require the teammate to consume them with Claude, for example.

## Prerequisites

- Install `team-knowledge` using the instructions in `README.md`.
- Use a real repository, or a disposable clone of one. Repository evidence drives selection,
  so an empty `git init` is not representative.
- Have at least one supported selector CLI installed and authenticated: Codex, Claude, or
  Copilot.
- Ensure Git can access the configured canonical source. The current default uses the
  `repo-adaptive-agents` Git repository over SSH.
- Ensure at least one reviewed real canonical Skill has been merged under
  `team-knowledge/skills/`.

The catalog currently contains no real Skills; it contains only its placeholder. This
walkthrough becomes end-to-end runnable when the first reviewed canonical Skill is merged.

## Bootstrap

From the repository you want to equip, run:

```sh
team-knowledge bootstrap --selector <codex|claude|copilot>
```

Replace the placeholder with the selector CLI you actually have available. The explicit flag
takes precedence over `TEAM_KNOWLEDGE_SELECTOR`. Bootstrap fetches the canonical source,
collects factual repository evidence, runs semantic selection, performs native validation,
and prints a proposed plan.

## Review the plan

Before applying it, ask:

- Does each proposed Skill make sense for this repository?
- Is an obviously useful canonical Skill missing?
- Is something obviously irrelevant proposed?

An empty selection can be correct for an unrelated repository. Record it as an observation;
do not repeatedly rerun selection until something appears.

Answer the interactive `Apply? [y/N]` prompt only after reviewing the plan. Declining leaves
committed and materialized team-knowledge state unchanged.

## Inspect durable and generated state

After applying the plan, these files are durable repository state and should be reviewed:

```text
.team-knowledge/config.json
.team-knowledge/lock.json
.team-knowledge/.gitignore
```

These paths are local, generated state:

```text
.agents/skills/<managed-name>/
.claude/skills/<managed-name>
.team-knowledge/cache/
.team-knowledge/runtime/
```

Each selected standard Skill exists physically once under `.agents/skills/`. The Claude path
is a generated discovery bridge to that same package. Do not commit generated Skill packages,
Claude bridges, caches, or runtime state.

## Commit repository knowledge state

```sh
git add .team-knowledge/config.json .team-knowledge/lock.json .team-knowledge/.gitignore
git commit -m "Bootstrap shared team knowledge"
```

## Use your normal coding agent

Open Codex, Claude Code, or Copilot and perform normal repository work for which a selected
Skill should be useful. The consuming coding agent may differ from the selector:

```text
bootstrap using Claude
        ↓
later work with Codex
```

Changing the consuming agent requires no additional bootstrap or semantic reselection.
Agent products may surface Skill discovery and use differently; this workflow does not
promise a provider-independent disclosure format.

## Optional sync check

When the pilot operator announces a canonical Skill change or revocation, run:

```sh
team-knowledge sync --selector <codex|claude|copilot>
```

Review the plan and choose whether to apply it. Content updates to selected Skills propagate
through sync, while explicit revocation removes managed exposure. New Skills, routing changes,
or changed repository evidence may require semantic reassessment. Changing only the selector
choice does not force reassessment.

See `docs/CROSS_REPOSITORY_TEAM_KNOWLEDGE.md` for detailed source, validation, state, and sync
semantics.
