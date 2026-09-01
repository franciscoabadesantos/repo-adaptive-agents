# Five-minute teammate tryout

Use a disposable Git repository so fictional examples never enter a real team's knowledge.
This walkthrough assumes the recommended installation in the main README is active.

```sh
demo_repo=$(mktemp -d /tmp/team-knowledge-demo.XXXXXX)
git -C "$demo_repo" init
git -C "$demo_repo" config user.name "Demo Engineer"
git -C "$demo_repo" config user.email "demo@example.invalid"
team-knowledge init --codex --repo "$demo_repo"
team-knowledge add --repo "$demo_repo" \
  --title "Settlement retry contract" \
  --summary "Use when changing settlement retry behavior." \
  --body "Preserve the original idempotency key across every retry."
team-knowledge add --repo "$demo_repo" \
  --title "Dashboard CSS convention" \
  --summary "Use when changing dashboard component styles." \
  --body "Use CSS modules and keep selectors locally scoped."
team-knowledge check --repo "$demo_repo"
team-knowledge index --json --repo "$demo_repo"
git -C "$demo_repo" add .team-knowledge .agents/skills/team-knowledge/SKILL.md
git -C "$demo_repo" commit -m "Add demo team knowledge"
```

Start Codex from the disposable repository, and ask:

```text
Explain the settlement retry behavior this team requires. Use repository team knowledge if relevant.
```

Codex should choose only `Settlement retry contract`, obtain it through the validated `use`
operation, and finish with:

```text
Used team knowledge: Settlement retry contract
```

Then ask an unrelated question such as `What is 2 + 2?` It should not use either item or add
a team-knowledge disclosure. This is a product check, not a benchmark; do not tune items or
prompts around it.

To inspect the CLI contract directly, copy the `exposure_id` and relevant ID from the index:

```sh
team-knowledge use --repo "$demo_repo" --exposure exp-... --json tk-...
```
