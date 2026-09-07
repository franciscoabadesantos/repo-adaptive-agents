# Iteration and batches

Define source query, stable item identity, ordering, maximum batch size, allowed side effect,
and aggregate result. Keep per-item completed, skipped, failed, and unknown results; never
hide partial failure behind aggregate success. Verify parallelism, iteration limits,
pagination, ordering, and error propagation in the target version rather than assuming them.

Fetch bounded pages, normalize each item before model/branch/tool use, validate each effect
independently, and make the final summary explicit. Start with one controlled item, then test a
mixed fixture: valid, invalid, duplicate, target-side failure, and empty collection.

A schedule does not establish deduplication. Re-runs, recovery, retry, and target idempotency
remain workspace- and integration-dependent; reconcile an unknown item before retrying it.
