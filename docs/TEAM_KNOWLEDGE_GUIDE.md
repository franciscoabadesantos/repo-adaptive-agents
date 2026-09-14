# Writing useful team knowledge

Canonical team knowledge is authored as a portable Agent Skill under
`team-knowledge/skills/<skill-name>/`. It is reviewed and versioned in Git, then selected and
materialized by `team-knowledge bootstrap`.

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

The menu lists installed Skills, local canonical packages, and new local proposals available in
that repository. An installed Skill is compared only with its exact canonical URL, commit, and
path from locked provenance. A new candidate is validated independently against an empty
baseline. Both paths check the portable package boundary and common secret/personal-path markers,
then run the isolated semantic assessment with the person's saved selector. Validation never
publishes, replaces, or commits a Skill.

The evaluator receives only the selected package, not a repository or other Skills. Its
recommendation and two boundary exercises are evidence for improvement, never authorization to
publish. A candidate is not a new canonical version until its contents are deliberately copied
into the catalog, reviewed through the normal Git workflow, and committed.

For an installed Skill, use `team-knowledge propose` after editing its local materialized
copy. The command reruns the same independent assessment and, only when it is `READY`, creates
a separate local checkout pinned to the Skill's locked canonical commit. It shows the exact
diff and then offers a form: keep that checkout only (the default), commit the local branch,
commit and push it, or commit, push, and create a draft GitHub pull request. No source
repository is changed before the selected action; creating a draft PR requires the `gh` CLI to
be installed and signed in.

The same `propose` menu combines adding existing work and starting a new draft. "Add or create a
new Skill" first lists new proposals under `.team-knowledge/proposals/` and unmanaged portable
packages under `.agents/skills/`; it can also accept another folder inside the current repository.
Selecting existing work validates it and, only when it is `READY`, creates the sidecar and Skill
directory in a pinned checkout of the configured canonical catalog. `proposal.json` remains local
and is never copied to the catalog. Choosing "Start a new Skill draft" creates only a local
workspace to edit with a coding agent; rerun `propose` to select it when it is ready.

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
