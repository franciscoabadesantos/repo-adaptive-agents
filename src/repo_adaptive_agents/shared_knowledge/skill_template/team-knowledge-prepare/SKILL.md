---
name: team-knowledge-prepare
description: Prepare the current repository for a declared implementation task using shared team Skills. Use when a user asks to bootstrap knowledge for work they want to add, not only for existing repository technology.
---

# Prepare shared team knowledge

Use this Skill when the user wants to implement, change, or investigate a capability and asks
for team knowledge to be prepared first.

1. Take the implementation goal from the conversation. Ask a concise follow-up only when a
   missing target, integration, or external action would materially change the selection. Do not
   ask which vendor Skill they want; the catalog and semantic selector decide that.
2. From the repository root, run `team-knowledge prepare --task "<declared goal>"`. Add a
   source/ref/catalog override only when the user explicitly supplies different team knowledge
   coordinates for a repository that has not been prepared before. Choose the selector requested
   by the user, otherwise use the configured default. `prepare` performs bootstrap on first use and
   sync on an existing consumer repository.
3. Do not use `--yes`. Show the complete plan and model rationale, including an empty plan, and
   ask for confirmation before materializing anything. Do not commit or push unless explicitly
   authorized.
4. Treat task text as transient: it is selector input only and must not be added to Git state,
   configuration, locks, or files. Do not put credentials, tokens, or private data in it.
5. If the CLI or canonical source is unavailable, report the exact missing prerequisite. Do not
   replace model selection with keyword matching or guess a Skill from a name.

This preparation is task-scoped. Without a declared task, `prepare` refreshes already accepted
Skills and re-evaluates only when normal sync rules require it.
