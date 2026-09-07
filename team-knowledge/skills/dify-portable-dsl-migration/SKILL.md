---
name: dify-portable-dsl-migration
description: Use when exporting, importing, adapting, or moving a Dify DSL/YAML app between environments or workspaces.
---

# Dify portable DSL migration

Use this Skill to move the portable workflow definition without treating it as a portable copy
of its runtime environment. Importing a DSL does not establish that credentials, models,
plugins, knowledge bindings, permissions, schedules, or publishing state transferred.

## Preserve evidence before editing

Keep a sanitized source export, its app type, DSL version, and the intended target purpose.
Diff the graph structure, node types, variable selectors, branch conditions, and declared
dependencies after every migration edit. Preserve opaque node and provider identifiers only
when a source export or current official documentation establishes their meaning; otherwise
obtain a minimal exported target baseline for that feature.

Remove secrets, private endpoints, credential bindings, private corpus content, and
workspace-specific identifiers from anything committed to canonical team knowledge. Never
replace them with plausible values.

## Separate portable and target-bound work

Portable work can include graph topology, prompts with safe placeholders, explicit contracts,
deterministic parsing, and test fixtures. Target-bound work includes installing plugins,
selecting models, binding credentials and knowledge, setting authorization, configuring
triggers, and publishing. List the latter as post-import steps rather than claiming the YAML
does them automatically.

## Import safely

1. Verify current Dify Cloud import and DSL compatibility guidance for the source and target.
2. Import into a disposable or controlled target copy where the workspace permits it.
3. Resolve each reported schema or dependency issue using an exact error, target export, or
   official source.
4. Run a fixture through the imported graph and trace the first divergence, if any.
5. Configure target-bound dependencies without exposing values, then publish only after the
   defined acceptance cases pass.

Do not promise automatic rollback, trigger migration, credential transfer, or version
compatibility unless verified for the exact editions and workspace.

## Handoff record

Provide the sanitized source and target DSLs, dependency and placeholder checklist, imports
attempted, Dify edition/version when observable, fixture results, trace evidence, and the
remaining target-bound steps. This allows a future operator to repair a failed migration
without rediscovering an unrecorded assumption.
