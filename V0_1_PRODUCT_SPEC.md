# Shared Team Knowledge v0.1 Product Spec

## Purpose and boundary

The pilot tests one behavior: an engineer contributes useful repository knowledge once,
and another engineer's coding agent later uses and visibly cites it. The first release is
for one team, one repository, roughly 10–20 items, Git review, and one Codex integration.
It is CLI-first and requires no hosted service.

The normal product vocabulary is **team knowledge**. Native admission and validation are
internal enforcement mechanisms, not concepts contributors must learn.

## Installation and initialization

Install the Python package and run from an existing Git repository:

```sh
team-knowledge init
```

`init` finds the Git root and creates only:

```text
.team-knowledge/
  config.json
  .gitignore
  items/
    .gitkeep
```

`config.json` records schema version, organization, team, repository identity, and default
owner. Repository identity defaults to the Git remote slug when available, otherwise the
root directory name. Team defaults to the repository name; flags may override defaults.
The local event log is ignored through `.team-knowledge/.gitignore`.

Running `init` again is safe when the existing configuration is valid and fails rather than
overwriting conflicting state.

## Knowledge representation

Each contribution is an ordinary UTF-8 Markdown file in `.team-knowledge/items/`. The
required contract is intentionally small:

```markdown
---
id: tk-a1b2c3d4e5f6
title: Settlement retry contract
summary: Use when changing retry behavior for settlement jobs.
owner: engineer@example.com
state: active
revision: 1
---

Retries must preserve the original idempotency key...
```

`add` generates the stable ID and filename. Title, summary, and a non-empty body are the
only contributor-supplied requirements. Owner defaults from `config.json`; repository
scope, active lifecycle, normal non-sensitive exposure, and no expiry are implicit.
Advanced admission metadata is not part of the first increment.

The Markdown path is translated internally to the native
`REPOSITORY_INSTRUCTION` payload. No new native resource kind is needed: the payload only
identifies repository-local content, while title, summary, body, identity, lifecycle, and
scope retain their native meanings.

## Contribution workflow

Commands operate on the current Git repository unless `--repo PATH` is supplied:

- `team-knowledge add --title TITLE --summary SUMMARY (--body TEXT | --body-file FILE)`
  creates one item and records `contribution_created` locally.
- `team-knowledge list` shows ID, state, title, and summary without internal control data.
- `team-knowledge show ID` prints the source Markdown for direct inspection.
- `team-knowledge check` parses every item, validates uniqueness and configuration, builds
  the native catalog, and reports concise active/revoked/invalid counts. It exits non-zero
  for invalid content.
- Engineers update title, summary, or body by editing Markdown and incrementing `revision`.
- `team-knowledge revoke ID` changes state to `revoked`, increments revision, and preserves
  the file and Git history.

A normal pull request is the publication and approval mechanism. There is no approval
database. An item is available when its file is present in the checked-out, reviewed Git
state.

## Runtime knowledge flow

The shared-knowledge service performs this sequence:

```text
Markdown catalog
  -> thin native ResourceCatalog translation
  -> native admit()
  -> model-visible index of admitted ID/title/summary only
  -> model chooses IDs semantically
  -> exposure receipt + native validate()
  -> bodies for validated IDs
  -> visible citation labels
```

Selection is never based on keywords, capabilities, deterministic scoring, or a semantic
ontology. The model owns relevance. The service never returns a body until its ID survives
native validation. Revoked content is neither indexed nor returned.

## Visible citations

The agent integration must append a disclosure whenever validated knowledge affects an
answer, for example:

```text
Used team knowledge: Settlement retry contract, Ledger testing checklist
```

Citation labels come from validated resource identities, not model-authored titles.

## Feedback

The next increment will expose:

```sh
team-knowledge feedback ITEM_ID useful
team-knowledge feedback ITEM_ID outdated
team-knowledge feedback ITEM_ID incorrect
```

Feedback appends a local event; it does not silently alter or revoke content. Outdated or
incorrect knowledge is corrected or revoked through the normal Git workflow.

## Lightweight pilot events

Events are appended to ignored `.team-knowledge/events.jsonl` and stay local/private by
default. Allowed event types are `contribution_created`, `contribution_available`,
`item_exposed`, `item_selected`, `validation_accepted`, `validation_rejected`, `item_cited`,
and `feedback_recorded` with a `useful`, `outdated`, or `incorrect` value.

Events may contain timestamp, item ID, actor, repository identity, task/session correlation
ID, validation outcome, and reason category. They must not contain raw prompts, source code,
knowledge bodies, model responses, or private admission traces.

This supports later measurement of cross-author reuse, repeated reuse, negative feedback,
and requests to expand the pilot. The north-star event chain is: person A contributes an
item; person B's task later selects, validates, uses, and visibly cites it.

## Initial agent integration

The single target is Codex because this repository and pilot already use repository-local
Codex instructions. The next increment should install one repository-local Agent Skill that:

1. calls a machine-readable command to obtain the admitted ID/title/summary index;
2. asks Codex to choose relevant IDs and passes only those IDs to a resolve command;
3. receives validated bodies plus canonical citation labels;
4. instructs Codex to append the visible disclosure; and
5. records selected, accepted/rejected, and cited events without prompt or body telemetry.

The CLI/service remains the enforcement boundary, so the skill contains workflow guidance,
not a duplicate implementation of admission or validation.

## Native validator integration

The shared-knowledge package translates each item to one native `ResourceRecord`:

- active/revoked -> native lifecycle;
- configured repository -> native repository scope;
- Markdown path -> existing repository-instruction payload;
- title, summary, and body -> native model-visible content;
- normal knowledge -> selectable with exposure requiring admissibility.

It calls `admit()`, records the exact index exposure with `record_exposure()`, and calls
`validate()` against the current catalog. It does not reproduce lifecycle, scope, digest,
change detection, exposure, or post-selection rules.

## Increment-one acceptance criteria

1. A teammate can initialize an existing Git repository without touching unrelated files.
2. `add` creates readable Markdown with an automatic stable ID and owner default.
3. `list`, `show`, `check`, and `revoke` have useful help and actionable errors.
4. Manual Markdown editing remains supported and `check` rejects malformed or duplicate
   items without rewriting them.
5. Valid active items enter the native catalog and admitted title/summary index.
6. Revoked items are not exposed; an item revoked or changed after exposure is rejected by
   native validation.
7. Invalid items cannot enter a validated native catalog.
8. End-to-end tests exercise the installed CLI against a real temporary Git repository.
9. Normal output contains no admission receipts, hashes, catalog revisions, reason codes,
   benchmark terms, or research terminology.
10. The full existing repository test suite remains green.

Live model calls, the Codex skill, feedback commands, citation rendering in an agent answer,
and pilot analysis are explicitly deferred until increment one is reviewed.
