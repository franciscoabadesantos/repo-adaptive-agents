# Admission-control research

## First experiment

The first frozen implementation mixed an experimental semantic pipeline with
deterministic controls. Its public benchmark was not mechanically compatible
with the frozen package and required a substantive external adapter. That
evaluation is preserved as research, not native product validation.

## Native experiment

The replacement package owns only explicit admission and validation semantics.
External code may translate representations and orchestrate retrieval/model
calls, but it must not reproduce lifecycle, scope, exposure, controls,
conflicts, identity changes, or post-model validation.

The native public evaluation verified callable origins and frozen source
hashes, used 125 shared A/V calls plus 125 PV calls, and froze 375 condition
records. Public diagnostics found no prohibited PV exposure or withheld-content
leakage. Hidden success criteria were not scored in the public run.

## Product consequence

Only the final native package is extracted into the clean baseline. Benchmark
runners, adapters, raw outputs, and deterministic knowledge-resolution code
remain research-only.

