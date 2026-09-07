---
name: canonical-team-skill-authoring
description: Use when proposing, creating, restructuring, validating, or retiring canonical shared team Skills in a Git-backed team-knowledge catalog.
---

# Canonical team Skill authoring

Use this Skill for the shared catalog, not for a one-off prompt, private helper, or generated
local Agent Skill. The goal is durable knowledge that materially changes another engineer's
decisions without accumulating a vague operational manual.

## Start with the catalog boundary

Confirm the target is canonical Git-backed team knowledge and inspect its catalog rules,
existing Skill descriptions, lifecycle model, and tests before editing. Preserve required
portable structure and safety constraints. Do not add credentials, personal paths, private
endpoints, source archives, binaries, or executable helpers to canonical packages.

## Choose the right shape

For a proposed capability family or a catalogue restructuring, read
[references/catalog-design.md](references/catalog-design.md). For evidence quality, change
discipline, lifecycle/revocation, and validation, read
[references/evidence-and-lifecycle.md](references/evidence-and-lifecycle.md).
For a new, changing, or version-sensitive technology, read
[references/research-and-refresh.md](references/research-and-refresh.md).

Prefer one coherent Skill with progressive references over many near-duplicate Skills. Split a
reference into an independent Skill only when it has a distinct discovery trigger, materially
different authority or failure semantics, and its own evidence/test lifecycle.

## Author and validate

Keep `name` and `description` narrow enough for reliable discovery. Put shared purpose,
boundaries, and reference routing in `SKILL.md`; place conditional procedures in references.
State what is confirmed, workspace-dependent, or not established when that distinction affects
an operation. A Skill can explain how to verify access and when to stop, but it never grants
permission.

Validate the canonical format, relevant repository tests, safety scans, and diff before
proposing a commit. Report the difference between authored, validated, committed, published,
materialized, and observed-in-use states accurately.
