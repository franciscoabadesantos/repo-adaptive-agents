# Native admission-control development results

Status: development/regression evidence only. Both earlier benchmark gold sets
were known before this implementation. No new blind benchmark was created or
run, and these results are not evidence of comparative product value.

## Enforced natively

The focused suite covers approved/current, draft, expired, revoked, activation
and expiry boundaries; organization/team/repository/path scope; safe path
normalization and root-escape rejection; compatibility and dependency facts;
exposure-sensitive withholding; ordinary post-validation-only rejection;
exact exposure receipts; unknown, unexposed, duplicate, nonselectable, changed,
and post-model-revoked selections; unconditional and conditional mandatory and
forbidden controls; supersession; equal-authority conflict blocking;
higher-authority resolution; nonconflicting supplementation; post-model
mandatory injection; inadmissible mandatory blocking; distinct typed payloads;
catalog digests/cycles; and atomic no-overwrite audit output.

The thin-runner regression proves that invalid exposure-sensitive content is
absent from retrieval/model callbacks and that final decisions identify the
native `admit` and `validate` functions as their origin. The same normalized,
timezone-aware `AdmissionContext.effective_at` is serialized for model-facing
context and required again at validation.

## Verification before commit

- Focused native suite: 37 passed.
- Complete repository suite: 229 passed.
- Compile sanity: all Python under `src` plus the thin runner compiled.
- Patch whitespace validation: `git diff --check` passed.
- Source review found no case IDs, organization-specific vocabulary, task-tag
  predicates, scoring, retrieval implementation, or experiment-condition logic
  in the native package or thin runner.

## Remaining limitations

- Facts are authoritative inputs; the package does not derive or attest them.
- Authority and conflict resolution apply only to explicitly related binding
  clauses. There is no semantic conflict discovery.
- Resource payload digests provide exact identity and race detection, not a
  cryptographic trust/signature system.
- Exposure receipts bind the exact native content objects supplied by the
  orchestrator; they cannot independently observe an external model service.
- Catalog changes are supplied as an authoritative current snapshot. This
  experiment does not define catalog distribution, signing, or persistence.
