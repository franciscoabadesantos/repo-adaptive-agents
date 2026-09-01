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

