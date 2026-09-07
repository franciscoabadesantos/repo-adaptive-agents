# Issue creation and simple updates

Use this reference for a single requested issue creation or a bounded field/comment/assignee
change. It is based on a tested local pattern of authenticating first and then submitting a
REST issue creation request, but exact resources, authentication headers, field names, and
required values must be verified against the target Jira version and project.

Before writing, confirm the requested project, issue type, summary or target issue key,
intended fields, and acting identity. Discover required and allowed fields through current
target-compatible Jira metadata or an authorized UI/API observation. Do not infer that a field
or assignee representation which works in one project works in another.

For a creation request, search or otherwise inspect the stated duplicate rule first when one
exists. If no duplicate rule is available, tell the requester that creation is not known to be
idempotent. Submit one bounded request only after the user has authorized the concrete data.

After the response, retain the returned issue key/ID and verify the intended fields by an
authorized read. If the request times out or connection fails after submission, stop: search
for the expected issue before considering another creation or update. Never retry an ambiguous
write blindly.
