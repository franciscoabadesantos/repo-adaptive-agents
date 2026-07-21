# AGENTS.md

## Scope

Work only inside this repository unless the user explicitly authorizes another path.

## Product direction

This repository builds a repo-adaptive agent-infrastructure bootstrapper. It must analyze
different types of repositories, preserve their native contracts, recommend useful
capabilities and optional roles, identify optional integrations, ask for missing decisions,
and generate portable, auditable proposals. Harness-specific adapters are opt-in outputs.

Do not assume that repositories are frontend applications. Support different stacks,
architectures, workflows, risks, and organizational preferences.

## Workflow

- Inspect before editing.
- Keep the deterministic core separate from optional LLM-assisted behavior.
- Model capabilities before mapping them to agents.
- Use subagents only when they materially help.
- Prefer one implementation owner per file area.
- Keep generated changes auditable, reversible, and reviewable.
- Never commit, push, deploy, install integrations, or write to external systems unless explicitly requested.
- Never store credentials, tokens, secrets, or personal preferences in the repository.
- Distinguish shared repository configuration, team policy, and local user preferences.
- Ask before introducing external integrations or permanent repo-level agents.
- Treat role/target selection and installation as separate approvals. After an adapter
  install preview, stop and ask the user before applying the exact plan; never infer that
  approval from an earlier role/target selection.
- An agent-selected bundle is an unconfirmed proposal, not a user choice. It may be
  previewed for discussion but must be regenerated after explicit user selection before
  installation.
- Do not hide validation failures by weakening checks.

## MVP boundaries

The first MVP should:
- analyze a local repository;
- create a structured repository profile;
- detect stack, architecture, tests, deploy tooling, and integrations;
- recommend capabilities and optional roles;
- identify useful but unavailable external capabilities;
- generate a portable repository profile and infrastructure plan;
- optionally render explicit, auditable harness adapters;
- preview and explicitly install new adapter files without overwriting repository state.

The first MVP should not:
- integrate with Jira, Confluence, Dify, or Cloudflare APIs;
- manage credentials;
- deploy remotely;
- create pull requests automatically;
- require an LLM for deterministic repository profiling.

## Validation

Run focused tests for changed code.
Use fixtures representing materially different repositories.
Report uncertainty and unsupported detections honestly.
