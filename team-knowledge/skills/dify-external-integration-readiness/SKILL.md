---
name: dify-external-integration-readiness
description: Use when a Dify workflow calls an API, plugin, tool, MCP server, webhook, or other external system.
---

# Dify external integration readiness

Use this Skill before allowing a Dify workflow to read from or write to an external system.
An imported node, configured-looking tool, or model statement is not proof that the target
operation is authorized or completed.

## Establish the integration contract

Document the smallest contract at the boundary:

- operation and target resource identity;
- required input fields, allowed values, and expected result;
- read versus write authority and the accountable owner;
- credential scope, without recording a token or secret;
- observable postcondition and failure result.

Get plugin/provider identifiers, tool parameters, and node schemas from current official
documentation or a sanitized target-workspace export. Do not invent them from a similar
integration or copy opaque identifiers between workspaces.

## Preflight the target workspace

Verify without exposing credential values that the integration is installed, selectable, and
bound to an authorized credential. Confirm the model/node has only the tool access intended
for its role. For a write, identify a bounded test resource and the person authorized to use
it. Stop if the target, permission, or resource ownership is unclear.

## Introduce effects incrementally

1. Exercise a harmless read or validation operation against the controlled target.
2. Confirm the received request and response in the Dify trace and, when possible, at the
   external system.
3. Test one controlled write with an explicit expected postcondition.
4. Independently observe that postcondition; re-fetch state if the operation changes it.
5. Record the sanitized trace, target type, and result before widening scope.

Use deterministic validation and a conditional gate before the write. A failed validation,
authorization, or approval check must take a safe branch rather than silently retrying.

## Do not assume lifecycle behavior

Whether a given Dify edition, plugin, or target API retries, deduplicates, rolls back, or
preserves a tool result is **not established** until verified for that exact combination.
Design the target API call and the surrounding workflow so a timeout or ambiguous response is
reported for investigation. Do not label an uncertain write as successful merely because a
tool node returned control.

## Evidence needed to improve this Skill

Capture a sanitized export fragment, Dify edition, plugin/tool version, node inputs and
outputs, exact error, target-side observation, and expected versus observed postcondition.
Keep credential values, private endpoints, workspace IDs, and customer data out of canonical
team knowledge.
