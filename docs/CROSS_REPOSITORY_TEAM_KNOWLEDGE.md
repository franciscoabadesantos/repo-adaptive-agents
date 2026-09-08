# Cross-repository team knowledge

This vertical proves one property: a team can author a portable Agent Skill once, select it
for multiple relevant repositories with Codex, Claude, or Copilot, and keep every managed
copy current from one Git source.

## Default source and source contract

The normal team-trial command is:

```sh
team-knowledge bootstrap
```

It uses the `repo-adaptive-agents` Git repository at ref `main`, with catalog path
`team-knowledge`. Product code and team knowledge share a repository for the trial but remain
separate logical assets: the effective knowledge revision is the latest commit that changed
the catalog subtree, not necessarily the product repository's HEAD.

`team-knowledge bootstrap --source <git-repository>` remains the override for a dedicated
canonical Git source and reads its catalog from `.` by default. Use
`--catalog-path <relative-path>` when the catalog is below the source root. Config and lock
provenance persist the chosen URL, ref, and catalog path; sync always uses those recorded
coordinates.

The canonical repository has a root `team-knowledge.json` with `schema_version`, `source_id`,
`organization`, and `team`. Schema version 2 may additionally contain
`organization_default_skill_ids`: active Skill IDs sent to the selected model and added as
auditable organization-default recommendations before native validation during a normal bootstrap
of a repository whose Git remote owner exactly matches `organization`. They are not injected for
other owners or for explicit task-scoped bootstrap. Each
`skills/<directory>/team-knowledge.json` has exactly `schema_version`, a stable `id`, and
`state` (`active` or `revoked`). Semantic routing comes only from the standard Agent Skill
`name` and `description` in `SKILL.md`.

The complete materializable package consists of `SKILL.md` and optional UTF-8 files below
`references/` with `.md`, `.txt`, `.json`, `.yaml`, or `.yml` suffixes. The sidecar governs
the package but is not materialized. A deterministic SHA-256 covers every materialized path
and byte; the resource revision is the latest Git commit touching its Skill directory.
For cross-agent portability, the Skill directory must exactly match its standard lowercase
hyphenated `name`; names are limited to 64 characters and descriptions to 1,024 characters.
This narrow canonical subset accepts only `name` and `description` frontmatter; vendor-specific
controls are rejected.

This slice rejects symlinks, executable files, `scripts/`, unsupported files, non-UTF-8 data,
files over 1 MB, Skill packages over 4 MB, and source archives over 20 MB.

## Bootstrap boundary

`team-knowledge bootstrap [--source <git-repository>] [--catalog-path <relative-path>] [--ref <ref>] [--selector <name>] [--task <text>]`:

1. clones/fetches the source into ignored `.team-knowledge/cache/` and pins a commit;
2. reads and validates an immutable Git archive;
3. projects only factual evidence from the existing repository profiler;
4. maps canonical packages to native `AGENT_SKILL` resources with organization/team scope;
5. calls native `admit()` and gives the selected model CLI only admitted
   `id/name/description` metadata plus
   the factual evidence;
6. records the exact exposure receipt and passes selected IDs through native `validate()`;
7. plans only validated packages for `.agents/skills/<name>/` plus a Claude bridge at
   `.claude/skills/<name>`; and
8. applies the complete plan transactionally after collision and local-modification checks.

The selector is resolved in this order: explicit `--selector`,
`TEAM_KNOWLEDGE_SELECTOR`, then `codex`. There is no automatic provider detection,
cross-provider reconciliation, or deterministic semantic fallback. Selection reasons are
shown in the plan but are deliberately absent from the lock, as is selector identity.

All three providers receive the same semantic instruction and the same factual evidence plus
admitted routing metadata. Each invocation uses a fresh temporary working directory. Codex
uses ephemeral read-only structured execution; Claude uses safe mode with tools, Skills,
custom instructions, sessions, and MCP disabled; Copilot uses programmatic silent mode with
custom instructions, built-in MCP, experimental features, and available tools disabled.
Malformed Copilot text gets at most one serialization-only retry. Provider unavailability is
reported; one provider is never silently substituted for another.

`--task` is optional, transient semantic context for a declared future implementation task. It
is sent only to the selected model alongside the same factual evidence and routing metadata. It
is not deterministic matching input and is never recorded in the consumer config or lock. This
lets a repository prepare for a capability it does not yet demonstrate without making a task
description part of durable repository state.

`team-knowledge setup` is the new-machine entry point. It installs a single portable
`team-knowledge-prepare` Skill in the standard user-level Skill directory of Codex, Claude, and
Copilot, reports whether their CLIs are available on `PATH`, and refuses to overwrite a different
existing Skill. `--dry-run` diagnoses without writing. `--only` limits onboarding to the agent named
by `--selector`. The CLI does not install or authenticate a coding agent and never silently
substitutes one for another.

Install the CLI itself once from the organization’s approved Git distribution (for example using
`pipx install "git+https://github.com/<organization>/<team-knowledge-repository>.git@main"`), then
run `team-knowledge setup`. The installed Skill turns a natural-language request into task-scoped
bootstrap, asks only material clarification questions, and always previews before application. A
Codex plugin may package this conversational entry point as an optional user interface, but the CLI
remains the vendor-neutral installation path.

`team-knowledge setup --selector <codex|claude|copilot>` saves the person's default semantic selector
in a user-local configuration file, never in repository state. Resolution order is explicit
`--selector`, `TEAM_KNOWLEDGE_SELECTOR`, saved user preference, then Codex. This is a local invocation
choice only and is not written to a consumer config or lock.

## Committed and local state

Commit:

- `.team-knowledge/config.json`: repository identity and canonical Git URL/ref/catalog path;
- `.team-knowledge/lock.json`: pinned source and selection identities, Git revisions,
  full-package digests, materialized paths, and factual-evidence digest;
- `.team-knowledge/.gitignore`: exact local state categories.

Keep local:

- `.team-knowledge/cache/` and `.team-knowledge/runtime/`;
- `.team-knowledge/events.jsonl`;
- generated `.agents/skills/<managed-name>/` packages and
  `.claude/skills/<managed-name>` bridges.

The installer writes exact managed paths inside a marked block in `.git/info/exclude`. It
never ignores either Skills directory globally and never overwrites an unmanaged physical
package, file, directory, or incorrect bridge. The Claude entry is a relative directory
symlink to the single physical package; no copied fallback is created.

## Sync rules

`team-knowledge sync` first fetches and validates a complete new plan, then applies it as one
filesystem transaction. Central content/reference changes to a selected Skill update its
managed copy and lock. Explicit revocation removes it. Missing locked content without a
revocation is a source-integrity error. New Skills, routing metadata changes, pending model
work, or factual repository evidence changes rerun the explicitly chosen selector. Generated
physical packages and Claude bridges are excluded from factual evidence so their creation or
recovery cannot itself trigger semantic reassessment. Changing only the selector choice also
does not trigger reassessment.

Model nonselection never silently removes an installed Skill; it is reported as possibly no
longer relevant. A locally modified managed copy is never overwritten or removed. Network
failure leaves all current state untouched. Offline mode verifies locked copies against the
cached pinned commit and never claims the source is current.

## Current limits

This is one Git source, one team scope, and one vendor-neutral Agent Skills target. Codex,
Claude, and Copilot are selector choices, not separate committed targets. The bundled catalog is not wheel
package data; Git remains its canonical update and revision mechanism. The product does not publish Skills,
merge repository instructions, execute Skill bundles, authenticate users, rank knowledge,
serve MCP, or manage organization-wide policy. Source cache sharing, hosted distribution,
and additional materialization formats are intentionally out of scope.
