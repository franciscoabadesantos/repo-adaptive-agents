# Native admission boundary

Validated source commit:
`b610f1b1232eeb2840e5cca2ddaf450ba64fa491`

Validated source tree:
`a0e784208ab3df5e8889cc96c2319448ffab4687`

The product extraction contains only:

- exact resource identity and model-visible payload digests;
- lifecycle and authoritative effective timestamps;
- organization, team, repository, and normalized path scope;
- explicit compatibility and dependency predicates;
- exposure policy distinct from final eligibility;
- supersession, mandatory/forbidden controls, authority, and conflicts;
- exact exposure receipts and validation against a current catalog.

It deliberately does not interpret task prose, infer requirements or
capabilities, rank resources, estimate coverage, repair model choices, or
derive authoritative facts.

The initial extraction is protected by source-hash and callable-origin tests.
Future product changes may evolve it, but must do so after this known baseline.

## Product evolution: generic shared knowledge

On 2026-09-02 the product added `SHARED_KNOWLEDGE` and `SharedKnowledgePayload` because
generic reusable Markdown is not a repository instruction. This is a content-category and
payload-only extension. The native admission and validation algorithms are unchanged.

The product translation also preserves the validated distinction between visibility and
final eligibility:

- ordinary knowledge uses `ALLOW_WHEN_INADMISSIBLE`;
- exposure-sensitive knowledge uses `REQUIRE_ADMISSIBLE`;
- both still require final native validation before their bodies are returned.
