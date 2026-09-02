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
canonical Git source and reads its catalog from `.`. Config and lock provenance persist the
chosen URL, ref, and catalog path; sync always uses those recorded coordinates.

The canonical repository has a root `team-knowledge.json` with exactly
`schema_version`, `source_id`, `organization`, and `team`. Each
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

`team-knowledge bootstrap [--source <git-repository>] [--ref <ref>] [--selector <name>]`:

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
