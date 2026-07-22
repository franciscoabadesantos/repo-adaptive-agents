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
- When preparing another repository, treat `propose` as the canonical assessment output.
  If `provider-discovery.json` reports `requires_provider_research`, complete that read-only
  public research before recommending adapter roles or targets. Record actual searches of
  provider marketplaces, skill/plugin repositories, code indexes, or the public web;
  product documentation alone is not provider discovery. If network research is not
  available, report the limitation.
- Any plausible installable provider named in a search result must appear as a structured
  candidate with `suitable`, `partial_only`, or `reject` coverage. Do not hide candidates in
  prose. A user may explicitly select a partial provider, but the unresolved remainder must
  stay visible and must not be reported as full capability coverage.
- Provider research is advisory. Record evidence, candidates, coverage limits, and a
  recommendation for every gap in `provider_research`, present it, then stop for the user's
  decisions. Do not create `provider_resolution`, expose adapter choices, or generate a
  bundle in that same step. After the user responds, record the separate resolution and
  rerun the repository-aware adapter query.
  Lack of permission to download or install a provider is not evidence that public research
  is unavailable. Do not bypass the gate with raw outcomes or invented roles.
- Treat `adapter-options <repo>` as the only adoption-time role/target query; global renderer
  catalogs are implementation details, not repository recommendations.
- After provider decisions unlock `adapter-options`, present its role and target choices and
  stop for the user's selection. Do not choose every target, infer a preferred harness, or
  generate an adapter bundle from the initial request to prepare a repository.
- Model capabilities before mapping them to agents.
- Use subagents only when they materially help.
- Prefer one implementation owner per file area.
- Keep generated changes auditable, reversible, and reviewable.
- Never commit, push, deploy, install integrations, or write to external systems unless explicitly requested.
- Never store credentials, tokens, secrets, or personal preferences in the repository.
- Distinguish shared repository configuration, team policy, and local user preferences.
- Ask before introducing external integrations or permanent repo-level agents.
- Treat every generated bundle as an unconfirmed tool proposal. The exact installation
  preview is the decision packet for its proposed roles, targets, and file additions.
- After presenting that preview, stop and ask the user before applying it. Approval of an
  earlier role/target discussion is insufficient, but approval of the exact preview accepts
  both its selection and its file plan; regeneration is required only when that plan changes.
- Do not hide validation failures by weakening checks.

## MVP boundaries

The first MVP should:
- analyze a local repository;
- create a structured repository profile;
- detect stack, architecture, tests, deploy tooling, and integrations;
- recommend capabilities and optional roles;
- identify useful but unavailable external capabilities;
- resolve capability gaps against optional local provider metadata without network access;
- emit a deterministic research brief for unresolved provider gaps so an authorized agent
  can compare public candidates without changing repository state;
- generate a portable repository profile and infrastructure plan;
- optionally render explicit, auditable harness adapters;
- preview and explicitly install new adapter files without overwriting repository state.

The first MVP should not:
- integrate with Jira, Confluence, Dify, or Cloudflare APIs;
- manage credentials;
- deploy remotely;
- create pull requests automatically;
- require an LLM for deterministic repository profiling;
- download, execute, or install knowledge providers.
- perform network research inside the deterministic CLI; external research remains an
  optional agent action governed by the generated brief and runtime policy.

## Validation

Run focused tests for changed code.
Use fixtures representing materially different repositories.
Report uncertainty and unsupported detections honestly.
