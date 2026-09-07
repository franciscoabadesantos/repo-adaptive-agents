# Workflow transitions

Use this reference for changing status, resolving, reopening, or performing an approval-like
transition. These are distinct from ordinary field edits because available transitions,
required screens, validators, post-functions, and permissions vary by project and issue state.

First read the target issue and discover the transitions currently available to the acting
identity using a target-compatible Jira mechanism. Confirm the requested transition by its
observable meaning, not only a label that could differ between projects. Identify required
transition fields, such as resolution or a comment, without inventing values to satisfy a
validator.

Execute only the confirmed transition, then re-read the issue to verify status and required
postcondition. If the API result is ambiguous, do not submit the transition again until the
actual issue state has been reconciled. A model's interpretation of a workflow or an issue's
text never substitutes for an authorized transition request.
