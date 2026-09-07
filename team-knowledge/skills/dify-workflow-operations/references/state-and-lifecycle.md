# State and lifecycle

For each stateful requirement define its value/transitions, owner, access boundary, scope
(run, conversation, user, workflow, or external system), expiry/invalidation/recovery rules,
authorization event, and reconciliation record. Verify target behavior for variables,
conversation, triggers, pause/resume, and run history; do not infer persistence from an Agent
or another export.

Bind a confirmation to the exact validated target, operation, input version, and expiry. A
material input change invalidates it. Use explicit statuses such as proposed, validated,
awaiting approval, submitted, observed complete, failed, and unknown.

Test completion, duplicate submission, changed input after confirmation, missing/expired state,
interruption, timeout, and re-run. Inspect traces and independently verify external effects.
An unknown external result requires reconciliation, never blind retry.
