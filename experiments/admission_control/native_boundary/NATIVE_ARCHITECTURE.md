# Native admission-control architecture

This is a parallel experimental slice. It does not replace or integrate with
the repository's provider, role, renderer, installer, proposal, or earlier
knowledge-resolution systems.

## Native product primitives

The package owns only explicit, enforceable metadata and decisions:

- exact resource ID, revision, type, and model-visible payload digest;
- distinct type payloads for Skills, repository instructions, MCP tools and
  resources, organizational policies, and environment contracts;
- approved/draft/denied/revoked lifecycle state and precise activation,
  expiry, and revocation timestamps;
- organization, team, repository, and normalized repository-path scope;
- generic predicates over authoritative structured facts for compatibility,
  dependencies, and conditional binding controls;
- exposure policy, independently of final-selection eligibility;
- explicit supersession, mandatory/forbidden controls, clause authority, and
  explicit clause conflicts;
- catalog revision and digest, typed rejection reasons, admission snapshots,
  exact exposure receipts, and post-selection validation results.

The native operations are `admit(context, catalog)` and
`validate(selections, exposure, context, current_catalog)`. Validation requires
the exact context recorded by the exposure receipt. Catalog state may change,
but the effective timestamp cannot silently change during one resolution.

## Translation-only concepts

External protocols may rename fields, parse timestamps, convert lists to
tuples, construct type-specific payload objects, and serialize native results.
They may also orchestrate caller-owned retrieval/model callbacks. These are
representation and orchestration duties only; the thin runner demonstrates
that no admission decision is needed outside the package.

Benchmark condition names, case IDs, task tags, organization-specific
vocabulary, retrieval algorithms, prompts, structured-output repairs, and
scoring remain external. Catalog transition events are represented by passing
the authoritative current catalog to `validate`; there is no benchmark-shaped
transition language in the native model.

## Deliberately absent

The native layer does not interpret task prose, infer capabilities or
requirements, rank resources, estimate relevance or semantic coverage, compute
residual gaps, or repair model choices. Generic fact predicates are evaluated
only against explicit authoritative facts; producing those facts is outside
this package.

Ordinarily inadmissible content may still be exposed when its envelope uses
`ALLOW_WHEN_INADMISSIBLE`; post-validation prevents it from surviving the final
set. Exposure-sensitive content uses `REQUIRE_ADMISSIBLE` and is withheld when
inadmissible. All model selections are checked again, and a newly active
admissible mandatory control is injected from the current catalog. An
inadmissible mandatory control or unresolved equal-authority binding conflict
blocks the result.
