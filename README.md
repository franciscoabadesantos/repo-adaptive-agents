# Shared team knowledge for coding agents

Capture repository-specific engineering knowledge once, review it with the team in Git, and
let Codex reuse it during normal coding work. When knowledge influences an answer, Codex says
which item it used so teammates can trust, correct, or retire it.

This v0.1 is deliberately small: one team, one repository, Markdown knowledge, a CLI, and one
Codex Skill. It requires no hosted service.

## Five-minute quickstart

You need Python 3.11 or newer, Git, and an installed and authenticated Codex CLI.

### 1. Install from a fresh clone

From this repository's root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
team-knowledge --help
```

Keep that virtual environment active for the remaining commands. `python -m pip install .`
is the recommended installation path for the team pilot.

### 2. Enable team knowledge in your repository

```sh
cd /path/to/your/team/repository
team-knowledge init --codex
```

This creates `.team-knowledge/` and the repository-local Codex Skill at
`.agents/skills/team-knowledge/SKILL.md`. The files are ordinary text and Markdown.

### 3. Add one useful item

```sh
team-knowledge add \
  --title "Settlement retry contract" \
  --summary "Use when changing settlement retry behavior." \
  --body "Preserve the original idempotency key across every retry."
team-knowledge check
```

Good items capture knowledge that teammates repeatedly explain: internal contracts,
operational gotchas, debugging procedures, testing practices, architectural constraints,
and repository-specific pitfalls. Keep each item concise and actionable. See
[Writing useful team knowledge](docs/TEAM_KNOWLEDGE_GUIDE.md).

### 4. Review and publish through Git

```sh
git add .team-knowledge .agents/skills/team-knowledge/SKILL.md
git commit -m "Add settlement retry team knowledge"
```

Open a normal pull request. There is no separate approval database: knowledge is available
when its reviewed Markdown is present in the checked-out Git revision.

### 5. Ask Codex a normal coding question

Start Codex in the repository and work normally. When the task may benefit from team context,
the Skill lets Codex inspect the title/summary index, choose relevant items, and request their
validated bodies. A response influenced by an item ends with a disclosure such as:

```text
Used team knowledge: Settlement retry contract
```

This means Codex selected that exact item and it survived current native validation. Merely
appearing in the index is not enough to be disclosed.

For a disposable two-item walkthrough, use [the teammate tryout](docs/TEAMMATE_TRYOUT.md).

## Everyday commands

```sh
team-knowledge add --help
team-knowledge list
team-knowledge show tk-<generated-id>
team-knowledge check
team-knowledge feedback tk-<generated-id> useful
team-knowledge feedback tk-<generated-id> outdated
team-knowledge feedback tk-<generated-id> incorrect
team-knowledge revoke tk-<generated-id>
```

`feedback` records a local signal without changing the knowledge item. If an item is wrong or
stale, use the normal review process to correct its Markdown or use `revoke` to preserve its
history while preventing future validated use.

## Files and local data

```text
.team-knowledge/
  config.json
  .gitignore
  items/
    tk-<generated-id>.md
.agents/
  skills/
    team-knowledge/
      SKILL.md
```

The ignored `.team-knowledge/events.jsonl` contains lightweight local pilot events with
repository-scoped pseudonymous actors. Ignored exposure receipts live under
`.team-knowledge/runtime/`. Neither stores prompts, repository source code, model responses,
or knowledge bodies.

## How the boundary works

Codex owns semantic relevance; this package does not rank or keyword-match knowledge. The
Skill calls two machine-readable operations:

```sh
team-knowledge index --json
team-knowledge use --exposure exp-... --json tk-...
```

`index` exposes only admitted IDs, revisions, titles, and summaries. `use` re-reads current
Markdown and uses `repo_adaptive_agents.admission_control` to reject changed, revoked,
invalid, unknown, or unexposed selections before returning any bodies.

Ordinary knowledge uses normal visibility. Add `--restricted` only when an inadmissible item
must also be withheld from the model-visible index.

## More information

- [Product scope and exact behavior](V0_1_PRODUCT_SPEC.md)
- [Writing useful team knowledge](docs/TEAM_KNOWLEDGE_GUIDE.md)
- [Pilot operator checklist](docs/PILOT_OPERATOR.md)
- [Public-safe research and architecture history](docs/research/README.md)

The older profiler, provider, role, and adapter commands remain legacy and are not part of
this product path.
