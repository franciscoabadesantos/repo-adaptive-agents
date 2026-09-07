---
name: dify-iteration-and-batch-safety
description: Use when a Dify workflow processes a collection, pagination, schedule, or repeated external action.
---

# Dify iteration and batch safety

Use this Skill when a Workflow processes more than one item. A successful run for one item
does not establish that pagination, ordering, duplication, partial failure, or re-runs are
safe for a batch.

## Define per-item and batch contracts

Before building the graph, specify the source query, stable item identity, input ordering,
maximum batch size, allowed side effect, and final aggregate result. State how the workflow
reports processed, skipped, failed, and unknown items. Do not let an aggregate success hide a
per-item error.

If parallelism, iteration limits, pagination behavior, or error propagation matter, verify
their current Dify semantics in official documentation and with an exported baseline. Do not
assume a schedule trigger supplies deduplication or that an iteration node preserves a
particular order.

## Design for bounded processing

- Fetch a bounded page and retain its source cursor or selection evidence where permitted.
- Normalize each item into a stable internal contract before an LLM, branch, or tool call.
- Validate each item independently before a write.
- Preserve an item-level result with identity, decision, error category, and observed
  postcondition.
- Make the final summary explicit: completed, partially completed, failed, or requires review.

Use a deterministic gate for each external effect. A model may classify or extract data, but
must not decide that unrelated items are safe because one item passed.

## Test before broadening scope

Start with one controlled item. Then run a small mixed fixture containing a valid item, an
invalid item, a duplicate, an item that causes a target-side failure, and an empty collection.
For each case inspect Dify's trace and independently inspect the target system when a write is
involved. Verify that a failed item follows its specified path and that other permitted items
have the intended result.

## Re-runs and ambiguous failures

Treat re-run behavior, crash recovery, retry semantics, and target idempotency as
workspace- and integration-dependent until tested. A timeout after submitting a write is an
unknown state, not permission to repeat it. Return the item identity and enough sanitized
evidence for an authorized operator to reconcile the target before retrying.
