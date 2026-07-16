# AGENTS.md

## Scope

Work only inside this repository unless the user explicitly authorizes another path.

## Product direction

This repository builds a repo-adaptive agent bootstrapper. It must analyze different
types of repositories, recommend useful capabilities and agents, identify optional
integrations, ask for missing decisions, and generate auditable `.codex/` proposals.

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
- Do not hide validation failures by weakening checks.

## MVP boundaries

The first MVP should:
- analyze a local repository;
- create a structured repository profile;
- detect stack, architecture, tests, deploy tooling, and integrations;
- recommend capabilities and agents;
- identify useful but unavailable external capabilities;
- generate a proposed `.codex/` tree;
- show changes without committing or pushing.

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
