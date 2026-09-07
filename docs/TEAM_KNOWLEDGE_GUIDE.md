# Writing useful team knowledge

Canonical team knowledge is authored as a portable Agent Skill under
`team-knowledge/skills/<skill-name>/`. It is reviewed and versioned in Git, then selected and
materialized by `team-knowledge bootstrap`; do not use `team-knowledge add` for canonical
team Skills.

Each canonical Skill contains only safe UTF-8 text:

```text
team-knowledge/skills/<skill-name>/
  SKILL.md
  team-knowledge.json
  references/              # optional .md, .txt, .json, .yaml, or .yml files
```

`SKILL.md` has exactly the portable `name` and `description` frontmatter fields. Its directory
must equal the lowercase hyphenated `name`. The sidecar holds only the stable ID and lifecycle:

```json
{
  "schema_version": 1,
  "id": "stable-skill-id",
  "state": "active"
}
```

Canonical Skills cannot contain scripts, binaries, symlinks, credentials, private keys,
personal paths, or provider-specific frontmatter. They may explain how to decide whether an
operator has the required access, where to stop, and which maintained automation is the source
of truth.

Add knowledge that another engineer's coding agent would genuinely benefit from and that the
repository itself does not make obvious.

Good candidates include:

- conventions repeatedly explained in reviews;
- internal API or data contracts;
- operational gotchas and safe recovery steps;
- debugging procedures with reliable signals;
- required testing practices;
- architectural constraints and repository-specific pitfalls.

Keep each item focused, concise, and actionable. The title should name the concept, the
summary should say when it is useful, and the body should state what the engineer or agent
needs to do. Prefer one durable rule or procedure over a broad project overview.

Avoid copying source code, temporary incident detail, secrets, personal preferences, or
information already clear in maintained repository documentation. Do not add speculative
advice as an established team contract. For privileged operations, make authorization and
missing-access stop conditions explicit; a Skill informs an operator but never grants access.

## Repository-local legacy knowledge

The commands below create the earlier repository-local knowledge format. Use them only for
that legacy workflow, not to add to the canonical `team-knowledge/` catalog.

Example:

```sh
team-knowledge add \
  --title "Settlement retry contract" \
  --summary "Use when changing settlement retry behavior." \
  --body "Preserve the original idempotency key across every retry."
```

Review the generated Markdown in a normal pull request. Edit an item and increment its
`revision` when the guidance changes. Use `team-knowledge revoke ID` when it must no longer
survive validation. `useful`, `outdated`, and `incorrect` feedback are signals for human
review; they never change an item automatically.
