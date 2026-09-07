---
name: jira-data-center-operations
description: Use when reading, searching, creating, updating, transitioning, or reconciling Jira Data Center issues through an authorized API or automation.
---

# Jira Data Center operations

Use this Skill for authorized operations against Jira Data Center. Treat an on-premises Jira
deployment as version- and workspace-dependent until its edition, version, base URL,
authentication method, project permissions, and required fields have been verified. Do not
apply Jira Cloud assumptions to it.

## Choose the smallest operation

- For retrieval, JQL, or inspection without a mutation, read
  [references/read-and-search.md](references/read-and-search.md).
- For creating an issue or making a simple field/comment/assignee update, read
  [references/issue-create-update.md](references/issue-create-update.md).
- For a workflow state change, approval-like step, resolution, or reopen action, read
  [references/workflow-transitions.md](references/workflow-transitions.md).
- For pagination, schedules, repeated mutations, or more than one issue, read
  [references/bulk-and-reconciliation.md](references/bulk-and-reconciliation.md).

Use only the reference required by the task. A simple issue update must not inherit batch
complexity, and a read-only request must not gain permission to write.

## Common boundary

Before an API mutation, establish the requested operation, exact target or target-selection
rule, acting identity, and authorization. Verify the current Jira REST documentation and the
target instance's available fields and permissions; project configuration and workflows are
not portable facts.

Never put a personal access token, password, session cookie, private Jira URL, account name,
or customer issue content into canonical team knowledge, source control, command history, or
logs. Keep credentials outside the repository and avoid printing them. A successful
authentication check does not prove authorization for a project-specific mutation.

After a write, verify the returned issue identity and the intended changed state using an
authorized read. A timeout, connection loss, or malformed response after submission is an
**unknown outcome**, not evidence that the operation failed or permission to repeat it.

## Evidence and correction

When behavior differs, retain only sanitized evidence: Jira edition/version, relevant REST
resource, operation type, expected versus observed status/result, required field or
permission category, and a reproducible error. Do not turn a single project's custom field,
workflow, or username convention into a universal rule.
