---
name: dify-dsl-trace-repair
description: Use when an imported Dify workflow has literal templates, empty or wrong node inputs, invalid selectors, disconnected routing, or unexpected runtime output.
---

# Repair Dify DSL and diagnose with run traces

Use a sanitized export and a reproducible fixture. YAML syntax and a successful import do not
prove that selectors, templates, edges, or node contracts work at runtime.

## Find the first divergence

1. Re-run the same small fixture and open the run trace.
2. Start at the input node and compare each node's received input with the preceding node's
   expected output.
3. Stop at the first node whose received input, output, or branch differs from expectation.
4. Classify that first fault before changing anything downstream: DSL/reference, model,
   deterministic code, plugin/tool, credential/permission, knowledge retrieval, or external
   integration.
5. Make the smallest change in that layer, re-import if required, and rerun the same fixture.

Do not diagnose solely from the final output, and do not change prompts, code, graph, and
credentials together without a new baseline.

## Check graph and reference integrity

For the affected path, inventory:

- actual node IDs;
- edge `source` and `target` values;
- every input selector and template reference;
- declared outputs and their value types;
- branch conditions and their referenced values.

Each selector and template reference must resolve to the actual producing node and output.
Changing a node ID, replacing a node, renaming a variable, or changing an edge requires
checking all consumers on that path.

Do not infer semantic rules from the formatting of opaque edge IDs. The meaningful contract is
that the graph's source/target links and selectors resolve correctly in the target Dify DSL
version and are confirmed by a trace.

## Treat these as stop conditions

Stop the repair and gather an evidence packet when:

- the import rejects the DSL or a dependency is unavailable;
- an input arrives as a literal template rather than its value;
- a selector points to a missing node/output;
- a node or branch is disconnected from its intended path;
- a tool requires a missing credential, plugin, permission, or external resource;
- the trace cannot establish the first divergence.

For any external write, keep the repaired path disconnected from production effects until a
controlled test confirms both the successful path and a safe failure path.

## Handoff evidence

Record the sanitized before/after DSL fragment, fixture, relevant trace input/output, exact
error, cause classification, and retest result. If the correction is reusable, update the
canonical Skill through review; do not turn an unverified workspace-specific workaround into a
general Dify rule.
