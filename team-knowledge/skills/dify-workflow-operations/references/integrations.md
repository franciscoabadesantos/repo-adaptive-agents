# Integrations

For an API, plugin, tool, MCP server, webhook, or other external system, define operation,
target identity, inputs/allowed values, read versus write authority, credential scope, and
observable postcondition. Obtain tool identifiers, parameters, and schemas from current
official documentation or a sanitized target export; never copy opaque values across
workspaces.

Verify installation, selection, authorized credential, intended tool access, and controlled
test resource without exposing secrets. Exercise a harmless read or validation first, then one
bounded write only after deterministic validation and explicit authorization. Observe the
postcondition independently.

Retry, deduplication, rollback, and preservation of tool results are not established until
tested for the exact Dify, plugin, and target combination. Report timeouts as ambiguous and
retain sanitized trace plus target-side evidence for reconciliation.
