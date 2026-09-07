---
name: dify-structured-output-gates
description: Use when a Dify LLM or Agent produces data that drives routing, validation, or an external action.
---

# Dify structured output and deterministic gates

Treat model output as an untrusted candidate payload whenever it controls routing or can lead
to an external effect. The model may interpret language, extract fields, classify ambiguity, or
draft text; deterministic workflow logic owns validation and the decision to proceed.

## Define a versioned contract first

Before configuring the LLM or Agent, define the smallest output contract that downstream nodes
need:

- required fields and their types;
- enumerated states or decisions;
- nullable versus absent values;
- list/object shape and whether additional properties are allowed;
- invariants that relate fields to each other;
- safe response when parsing or validation fails.

Use the target workspace's supported structured-output/schema feature only after verifying its
current node configuration and a representative run. If the feature or its exact schema support
is uncertain, retain a deterministic parser/validator and label the remaining assumption rather
than claiming the payload is guaranteed structured.

## Separate interpretation from authority

Use this sequence for any meaningful effect:

```text
LLM or Agent interpretation
        ↓
deterministic parse and type normalization
        ↓
invariant validation and explicit readiness result
        ↓
conditional gate
        ↓
bounded external action
```

The parser/validator must handle malformed, empty, missing, or contradictory output without
inventing values. Preserve genuinely unknown fields as the contract permits; do not convert an
unknown value into approval, completion, a default decision, or a fabricated fact.

## Make the gate explicit

Define a boolean or enumerated readiness result from validated data, rather than branching
straight from model prose. The gate must reject at least:

- invalid or unparseable payloads;
- missing required fields;
- unsupported enum values or wrong types;
- contradictory state combinations;
- missing required human approval;
- any condition that leaves the proposed external effect ambiguous.

Connect the false branch to a safe result: request the smallest useful clarification, return a
validation error, or escalate to an authorized human. Do not silently retry an authorization,
validation, or approval failure.

## Bound and verify external effects

Before enabling a production write:

1. test the gate with valid, incomplete, contradictory, malformed, and empty model outputs;
2. prove that the false branch never reaches the tool;
3. use a controlled external resource for the first allowed write;
4. verify the external effect independently, then record the run trace;
5. if the action changes state, re-fetch or otherwise verify the postcondition before a final
   success message.

An LLM's claim that an action succeeded is not evidence of the external effect.

## Confidence and correction

Keep model/schema behavior, plugin/tool behavior, and workspace permissions marked as
workspace-dependent until observed in the target environment. If a contract or gate behaves
differently, stop the external path and capture the sanitized payload, parser result, gate
result, trace, exact error, and expected postcondition. Use that evidence to update the
canonical Skill through review.
