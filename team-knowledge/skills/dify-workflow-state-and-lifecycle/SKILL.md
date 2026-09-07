---
name: dify-workflow-state-and-lifecycle
description: Use when a Dify app needs conversational state, confirmations, resumable work, scheduled runs, or safe re-execution.
---

# Dify workflow state and lifecycle

Use this Skill when a workflow depends on information surviving a single node execution or
when an effect could be repeated. State must have an explicit owner, scope, lifetime, and
validation rule; it must not be inferred from an Agent, prompt history, or a node name.

## Model the state before choosing a mechanism

For every stateful requirement, write down:

- state value and allowed transitions;
- owner and access boundary;
- scope: one run, conversation, user, workflow, or external system;
- expiry, invalidation, and recovery rule;
- event that authorizes an irreversible effect;
- observable record used to reconcile ambiguous outcomes.

Verify the current Dify edition's actual variable, conversation, trigger, pause/resume, and
run-history behavior before relying on any of it. Their presence in another exported app is
not proof of availability or persistence in the target workspace.

## Make confirmation meaningful

Bind a confirmation to the exact validated proposal: target, operation, relevant input
version, and expiry. If any material input changes, invalidate the confirmation and return to
review. A free-text acknowledgement, model assertion, or prior conversation message is not a
durable authorization boundary unless the target design explicitly verifies it.

## Treat execution states distinctly

Use explicit statuses such as proposed, validated, awaiting approval, submitted, observed
complete, failed, and unknown. In particular, a tool timeout or an interrupted scheduled run
after submission leaves the external result unknown until it is reconciled. Do not convert
unknown into success or retry blindly.

## Test lifecycle behavior

Run controlled tests for normal completion, duplicate submission, changed input after
confirmation, missing state, expired state, interruption, timeout, and re-run. Inspect the
Dify trace and independently verify any external postcondition. Record the sanitized trace
and observed behavior before treating a lifecycle rule as reusable knowledge.

Keep private identifiers, user history, credentials, and target-resource details out of the
canonical Skill bank.
