---
name: dify-evidence-first-workflow-build
description: Use when designing, importing, changing, or reviewing a Dify workflow or Chatflow whose workspace dependencies or runtime behavior must be verified.
---

# Evidence-first Dify workflow building

Use this Skill to build Dify workflows without treating a plausible DSL, a successful import,
or a model response as proof that the automation is ready. It applies to Workflow and Chatflow
apps; choose the app type from the required interaction and state model, not from an assumed
universal recipe.

## Classify every claim

Keep these categories separate in the design, handoff, and change record:

- **Confirmed:** supported by a current official Dify source, a sanitized exported baseline,
  or an observed run trace/test.
- **Workspace-dependent:** model availability, plugin/tool installation, credentials,
  knowledge-base bindings, permissions, external resources, and publish settings. Verify them
  in the target workspace without exposing their values.
- **Not established:** behavior not yet observed or documented for the target Dify edition.
  Do not encode it as a requirement or promise.

When Dify version, node schema, plugin identifier, or API capability matters, verify current
official documentation and the target workspace before generating an import-ready DSL.

## Build from a minimal, inspectable baseline

1. State the objective, inputs, output contract, external effects, and success condition.
2. Choose explicit workflow nodes for deterministic transformation, validation, routing, and
   effects. Use an Agent only where dynamic tool choice or multi-step reasoning is necessary.
3. Export a sanitized baseline before changing it. Never commit secrets, credential bindings,
   private keys, workspace IDs, or private endpoints.
4. Change one capability at a time: graph shape, structured output, validation, then one
   external integration. Re-import into a safe copy when the workspace permits it.
5. Run a small fixture and retain the relevant trace as evidence for the changed behavior.

A workflow that imports successfully is not automatically semantically valid. Confirm that
the intended input reaches each consumer node and that each output has the expected type and
value before enabling an external effect.

## Preflight before publish or external effects

Verify, without printing secret values:

- the selected model can run in this workspace;
- each required plugin/tool is installed and selectable;
- required knowledge bases are bound and retrieval has a representative result;
- credentials are selectable and authorized for a controlled target;
- the operator can import, edit, publish, and inspect runs;
- each external action has an explicit authorization and a bounded test resource.

If a required dependency is absent or unclear, stop and report the missing capability. Do not
replace it with an invented plugin, identifier, credential, model, or manual workaround.

## Required evidence packet when behavior differs

Before proposing a correction to this Skill or another canonical Dify Skill, collect a
sanitized evidence packet containing:

- Dify edition and observed version when available;
- app type, affected node type, and sanitized DSL fragment or export;
- relevant node configuration, with all secrets and private IDs removed;
- fixture input, expected result, received input/output at the first divergent node, and exact
  error text;
- minimal reproduction steps and result after the smallest correction.

Classify the cause as DSL/reference, model output, deterministic code, plugin/tool,
credential/permission, knowledge retrieval, or external integration. A new observation is not
a canonical rule until it is reviewed with this evidence.
