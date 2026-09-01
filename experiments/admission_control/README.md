# Admission-control experiment

This is a parallel, non-product experiment derived from the independently
scored knowledge-resolution holdout. The earlier cases are now known and are
used only as labelled development/regression tests. Results here are not blind
evidence for the architecture.

The implemented boundary is:

```text
catalog -> deterministic prefilter -> semantic selector
        -> deterministic post-validation -> final exposure set
```

The deterministic layer evaluates only represented metadata: approval,
revocation, effective/expiry dates, organization/team/repository/path scope,
exact compatibility values, Skill harness support, MCP network availability,
supersession, forbidden disposition, mandatory controls, and explicit conflict
authority. It contains no task phrase rules, requirements, capabilities,
deterministic coverage, or residual-gap logic.

The semantic selector receives admitted selectable resources and admitted
mandatory controls. Rejected resource bodies are not passed to it. The selector
is a protocol/callback; `semantic.py` supplies a deliberately ordinary lexical
reference implementation, not a new semantic thesis.

Post-validation recomputes admission against a current catalog snapshot. This
allows a resource selected from the prefilter snapshot to be rejected if it is
revoked or otherwise invalidated before final exposure. A changed mandatory
control set or an unresolved equal-authority conflict blocks the run.

The audit writer persists catalog snapshots/digests, context, prefilter
decisions, actual model-visible resources, raw selections, post-validation,
mandatory controls, final exposure, and a hash manifest. It refuses overwrite.
