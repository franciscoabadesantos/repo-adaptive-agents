# Structured output and effects

Treat LLM or Agent output as an untrusted candidate whenever it controls routing or an
external effect. Define a smallest versioned contract: required fields/types, enums,
nullable-versus-absent rules, object/list shape, cross-field invariants, and parse-failure
result. Verify target support for structured output/schema; retain a deterministic
parser/validator when that support is uncertain.

Use this sequence:

```text
model interpretation -> deterministic parse/normalization -> invariant validation
    -> explicit readiness result -> conditional gate -> bounded external action
```

Reject malformed, empty, missing, contradictory, unapproved, or ambiguous payloads through a
safe branch. Test valid, incomplete, contradictory, malformed, and empty output; prove the
false path cannot invoke the tool. Verify the first allowed write independently and re-fetch
state where applicable. A model's success claim is not evidence of the external effect.
