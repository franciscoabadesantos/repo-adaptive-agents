# Read and search

Use this reference for read-only issue, project, user, or search requests.

Establish the intended question and the smallest authorized query before searching. Keep JQL
or API filters bounded by project, status, time range, or result limit when appropriate; do
not fetch a broad issue corpus merely because a narrower lookup failed.

Verify the target Jira version and REST resource against current official documentation before
reusing an endpoint or response field. A response may be incomplete because of permissions,
field configuration, pagination, deleted content, or a query error. Report that distinction
instead of claiming there are no matching issues.

Return issue keys and a concise result suitable for the request. Do not disclose issue content
or private fields beyond the caller's authorization and stated need. No read request authorizes
a comment, edit, transition, or other follow-up mutation.
