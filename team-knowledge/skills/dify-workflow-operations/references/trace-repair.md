# Trace repair

Re-run a small reproducible fixture and locate the first divergence in the trace: start at the
input node, compare received input to the preceding expected output, then stop at the first
wrong input, output, or branch. Classify it as DSL/reference, model, deterministic code,
plugin/tool, credential/permission, knowledge retrieval, or external integration before
changing downstream nodes.

For the affected path inventory actual node IDs, edge source/target values, selectors and
templates, declared outputs/types, and branch conditions. References must resolve to real
producing nodes and outputs. Do not infer semantic rules from opaque edge-ID formatting.

Make the smallest correction, then repeat the same fixture. Stop when an import rejects the
DSL, a dependency is unavailable, a template remains literal, a selector is absent, a path is
disconnected, or the trace cannot establish the first divergence. Keep production effects
disconnected until a controlled test verifies success and safe failure paths.
