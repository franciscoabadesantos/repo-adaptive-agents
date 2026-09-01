# Architecture decision: model-owned relevance, native validation

Status: accepted product direction; v0.1 implementation pending.

## Decision

Use this separation:

```text
shared knowledge -> model/retrieval selects relevance -> native validation
```

Run native admission before retrieval only when an inadmissible resource must
not be exposed to the model. Keep the control layer mostly invisible to normal
users.

## Supported conclusions

- Capable models and retrieval should own interpretation of task prose and
  semantic relevance.
- Native deterministic validation is useful for exact identity, lifecycle,
  scope, revocation, changed resources, mandatory and forbidden controls,
  supersession, conflicts, and catalog transitions.
- Selective prefiltering is justified for exposure-sensitive resources.

## Rejected product responsibilities

The product should not build deterministic task interpretation, capability or
requirement ontologies, deterministic semantic ranking, coverage calculation,
generated agent teams/personas, or broad provider-resolution machinery.

## Validation boundary

The extracted native package is a validated starting primitive, not proof of
the v0.1 product hypothesis. It does not derive authoritative facts, discover
semantic conflicts, distribute or sign catalogs, or measure whether engineers
will contribute and reuse knowledge.

