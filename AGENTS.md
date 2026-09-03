# AGENTS.md

## Scope

Work only inside this repository unless the user explicitly authorizes another path.

## Product direction

This repository provides shared team knowledge for coding agents. Its current architecture is:

```text
canonical Git-backed team knowledge
        ↓
portable standard Agent Skills
        ↓
factual repository evidence
        ↓
model-owned semantic Skill relevance
        ↓
native deterministic admission / exposure / validation
        ↓
vendor-independent repository knowledge selection
        ↓
derived local Agent Skills
```

`team-knowledge/` is the canonical, team-owned Skill bank for the current trial. Canonical
knowledge is stored as portable standard Agent Skills, not as vendor-specific copies. See
`README.md` and `docs/CROSS_REPOSITORY_TEAM_KNOWLEDGE.md` for the current user workflow and
detailed behavior.

## Architectural contract

- Keep source acquisition, catalog parsing, factual evidence collection, semantic selection,
  native validation, and local materialization as separate responsibilities.
- Semantic repository-to-Skill relevance belongs to the explicitly chosen model selector.
  Codex, Claude, or Copilot may perform selection. Do not add deterministic keyword matching,
  capability ontologies, requirement inference, or another fuzzy-relevance fallback.
- Selector and consumer are independent concepts. Changing the coding agent that later
  consumes a materialized Skill does not itself trigger semantic reselection. Selector
  identity is a developer-local invocation choice, not committed repository semantic state.
- Native deterministic code owns lifecycle, scope, revocation, exposure and admission,
  integrity, exact resource identity, and post-model validation. Do not duplicate or weaken
  those rules in selectors, distribution code, integrations, or documentation.
- `.agents/skills/<name>/` contains generated physical Skill packages used by supported
  consumers. `.claude/skills/<name>` is a generated discovery bridge to the same package.
  Generated packages, bridges, caches, events, and runtime state are derived and disposable.
- `.team-knowledge/config.json` and `.team-knowledge/lock.json` are the durable committed
  consumer state. Local materialization must remain safely reconstructible from their
  committed provenance and the canonical source.
- Central Skill changes and explicit revocations propagate through sync. Preserve integrity,
  collision protection, locally modified-copy protection, and deterministic revocation.

The repository still contains profiler, recommender, provider-resolution, role, and adapter
code from the earlier product direction. Treat it as legacy: do not extend it, revive it as
the product architecture, or route new shared-knowledge behavior through it unless the user
explicitly requests that work.

## Maintenance workflow

- Inspect relevant code, contracts, documentation, and tests before editing.
- Keep changes narrowly scoped and preserve native repository conventions.
- Do not overwrite, revert, or otherwise disturb unrelated local work.
- Keep generated changes auditable, reversible, and reviewable.
- Do not weaken validation or architectural boundaries to make tests pass.
- Prefer one implementation owner per overlapping file area.
- Distinguish committed repository or team state from developer-local preferences and runtime
  state.
- Never store credentials, tokens, secrets, or personal or local provider preferences in the
  repository.
- Do not commit, push, deploy, install integrations, or mutate external systems unless the
  user explicitly authorizes that action.
- Report uncertainty, unverified provider behavior, unsupported assumptions, and unavailable
  validation honestly.

## Delegation

Use delegation only when it materially helps. Read-only exploration can be delegated for
unfamiliar areas; implementation ownership should be explicit and non-overlapping;
independent review is useful for risky or boundary-sensitive changes. Keep delegated tasks
narrow. Do not require an Explorer → Builder → Reviewer pipeline, and do not treat any
vendor-specific helper-agent configuration as the repository architecture.

## Validation

Run focused validation for changed behavior. Run broader regression checks when a change
touches architecture boundaries, shared contracts, packaging, generated state, or multiple
subsystems. Use fixtures representing materially different repositories where relevant.
