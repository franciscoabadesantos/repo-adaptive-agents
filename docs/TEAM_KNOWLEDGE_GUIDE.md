# Writing useful team knowledge

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
advice as an established team contract.

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
