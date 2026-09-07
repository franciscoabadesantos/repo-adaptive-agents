---
name: dify-workflow-operations
description: Use when designing, importing, repairing, testing, or operating a Dify Workflow or Chatflow with workspace-dependent dependencies or external effects.
---

# Dify workflow operations

Use this Skill for Dify workflow work without treating a plausible DSL, successful import, or
model response as proof that the automation is ready. Choose Workflow or Chatflow from the
required interaction and state model, not from an assumed universal recipe.

Classify every important claim as **Confirmed** (current official documentation, sanitized
export, or observed trace), **Workspace-dependent** (models, plugins, credentials, knowledge,
permissions, resources, and publish settings), or **Not established**. Do not convert the last
two categories into a promise or an import-ready DSL.

## Read only the relevant reference

- For architecture, app type, baseline DSL, and preflight, read
  [references/build-and-dsl.md](references/build-and-dsl.md).
- For literal templates, broken selectors, routing, or unexpected output, read
  [references/trace-repair.md](references/trace-repair.md).
- For LLM/Agent outputs that control routing or effects, read
  [references/structured-output-and-effects.md](references/structured-output-and-effects.md).
- For APIs, plugins, tools, MCP servers, or webhooks, read
  [references/integrations.md](references/integrations.md).
- For iteration, pagination, scheduled processing, or repeated effects, read
  [references/iteration-and-batches.md](references/iteration-and-batches.md).
- For knowledge-base grounding, read
  [references/knowledge-retrieval.md](references/knowledge-retrieval.md).
- For exporting, importing, or moving DSL between workspaces, read
  [references/migration.md](references/migration.md).
- For state, confirmations, resumable work, or safe re-execution, read
  [references/state-and-lifecycle.md](references/state-and-lifecycle.md).

Do not load unrelated references merely because they are available. A read-only knowledge
question does not need batch rules; a DSL repair does not authorize an external write.

## Common safeguards

Use explicit nodes for deterministic transformations, validation, routing, and effects. Use an
Agent only where dynamic tool choice or multi-step reasoning is necessary. Never commit or
expose secrets, credential bindings, private keys, private endpoints, workspace IDs, or private
corpus content.

Before enabling an external effect, verify the target workspace dependency and use a controlled
resource. After a write, independently verify its postcondition. A timeout or loss of
connection after submission is an **unknown outcome**, not a reason to retry blindly.

When behavior differs, capture sanitized evidence: Dify edition/version when observable, app
and node type, relevant export fragment, fixture input, first divergent input/output, exact
error, expected result, and smallest correction. A single workspace workaround is not a
canonical rule until reviewed.
