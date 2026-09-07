# Bulk operations and reconciliation

Use this reference for scheduled processing, pagination, import-like work, or mutations across
multiple issues. Treat every item as an independent operation with a stable issue key,
validated intended change, outcome, and error category. A batch-level success message must not
hide partial failures.

Define selection criteria, maximum scope, ordering or pagination rule, duplicate/re-run rule,
allowed mutation, and stop condition before processing. Verify the target Jira version and API
pagination behavior rather than assuming a default page size or ordering is stable.

Begin with one controlled issue, then use a small mixed fixture where feasible. Stop on
authorization, schema, workflow, or unknown-outcome errors that could make subsequent writes
unsafe. For a timeout after a write, reconcile the individual issue by read before any retry.

Report completed, skipped, failed, and unknown issue keys separately. Do not claim that a
schedule, retry mechanism, or repeated API call is idempotent unless it has been verified for
the exact target operation.
