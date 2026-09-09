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

## Validate a proposed canonical change

Inside a bootstrapped consumer repository, validate a changed local materialization without
typing a path, source URL, or a second semantic-validation command:

```sh
team-knowledge validate
```

The menu lists only Skills installed in that repository. For each chosen Skill it discovers the
local `.agents/skills/...` package and its exact canonical URL, commit, and path from the locked
provenance. It compares only that pair, checks the portable package boundary and common
secret/personal-path markers, then runs the isolated semantic assessment with the person's saved
selector. It never publishes, replaces, or commits a Skill.

The evaluator receives only the selected package, not a repository or other Skills. Its
recommendation and two boundary exercises are evidence for improvement, never authorization to
publish. A candidate is not a new canonical version until its contents are deliberately copied
into the catalog, reviewed through the normal Git workflow, and committed.

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
