---
name: team-knowledge
description: Use repository-local shared team knowledge when a coding task may depend on team conventions, contracts, checklists, operational context, or known pitfalls. Do not invoke it for unrelated general questions.
---

# Team knowledge

Use the `team-knowledge` CLI as the only knowledge boundary. Do not open files under
`.team-knowledge/items/` directly and do not reproduce catalog, exposure, selection, or
validation logic.

For a repository coding task where team context may help:

1. Run `team-knowledge index --json` from the repository.
2. Read only the returned IDs, revisions, titles, and summaries. Decide semantic relevance
   yourself; do not treat every indexed item as relevant.
3. If one or more items are relevant, run
   `team-knowledge use --exposure <exposure_id> --json <id> [<id> ...]` using the exposure
   ID from that index response.
4. Use only bodies in the `knowledge` array. Never use or cite entries in `rejected`.
5. When returned knowledge materially informs the work or answer, end the final response
   with exactly one short line using only returned citation titles:
   `Used team knowledge: <title>; <title>`

If no indexed item is relevant, do not call `use` and do not add a disclosure. If `use`
returns no validated knowledge, continue without team knowledge and do not cite it.
