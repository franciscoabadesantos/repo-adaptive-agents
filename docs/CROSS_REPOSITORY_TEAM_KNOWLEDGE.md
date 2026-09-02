# Cross-repository team knowledge

This vertical proves one property: a team can author a Codex Skill once, select it for
multiple relevant repositories, and keep every managed copy current from one Git source.

## Source contract

The canonical repository has a root `team-knowledge.json` with exactly
`schema_version`, `source_id`, `organization`, and `team`. Each
`skills/<directory>/team-knowledge.json` has exactly `schema_version`, a stable `id`, and
`state` (`active` or `revoked`). Semantic routing comes only from the standard Agent Skill
`name` and `description` in `SKILL.md`.

The complete materializable package consists of `SKILL.md` and optional UTF-8 files below
`references/` with `.md`, `.txt`, `.json`, `.yaml`, or `.yml` suffixes. The sidecar governs
the package but is not materialized. A deterministic SHA-256 covers every materialized path
and byte; the resource revision is the latest Git commit touching its Skill directory.

This slice rejects symlinks, executable files, `scripts/`, unsupported files, non-UTF-8 data,
files over 1 MB, Skill packages over 4 MB, and source archives over 20 MB.

## Bootstrap boundary

`team-knowledge bootstrap --source <git-repository> [--ref <ref>]`:

1. clones/fetches the source into ignored `.team-knowledge/cache/` and pins a commit;
2. reads and validates an immutable Git archive;
3. projects only factual evidence from the existing repository profiler;
4. maps canonical packages to native `AGENT_SKILL` resources with organization/team scope;
5. calls native `admit()` and gives Codex only admitted `id/name/description` metadata plus
   the factual evidence;
6. records the exact exposure receipt and passes selected IDs through native `validate()`;
7. plans only validated packages for `.agents/skills/<name>/`; and
8. applies the complete plan transactionally after collision and local-modification checks.

There is no deterministic semantic fallback. Codex selection reasons are shown in the plan
but are deliberately absent from the lock.

## Committed and local state

Commit:

- `.team-knowledge/config.json`: repository identity and canonical Git URL/ref;
- `.team-knowledge/lock.json`: pinned source and selection identities, Git revisions,
  full-package digests, materialized paths, and factual-evidence digest;
- `.team-knowledge/.gitignore`: exact local state categories.

Keep local:

- `.team-knowledge/cache/` and `.team-knowledge/runtime/`;
- `.team-knowledge/events.jsonl`;
- generated `.agents/skills/<managed-name>/` copies.

The installer writes exact managed paths inside a marked block in `.git/info/exclude`. It
never ignores `.agents/skills/` globally and never overwrites an unmanaged collision.

## Sync rules

`team-knowledge sync` first fetches and validates a complete new plan, then applies it as one
filesystem transaction. Central content/reference changes to a selected Skill update its
managed copy and lock. Explicit revocation removes it. Missing locked content without a
revocation is a source-integrity error. New Skills, routing metadata changes, pending model
work, or factual repository evidence changes rerun Codex selection.

Model nonselection never silently removes an installed Skill; it is reported as possibly no
longer relevant. A locally modified managed copy is never overwritten or removed. Network
failure leaves all current state untouched. Offline mode verifies locked copies against the
cached pinned commit and never claims the source is current.

## Current limits

This is one Git source, one team scope, and one Codex target. It does not publish Skills,
merge repository instructions, execute Skill bundles, authenticate users, rank knowledge,
serve MCP, or manage organization-wide policy. Source cache sharing, hosted distribution,
and additional agent targets are intentionally out of scope.
