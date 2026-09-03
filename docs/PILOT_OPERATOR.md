# Cross-repository team-knowledge pilot

## Pilot question

Can real team knowledge be authored once, automatically assembled into the repositories where
it is useful, and consumed by teammates regardless of whether they use Codex, Claude, or
Copilot?

## Before inviting the team

Prepare a small real canonical corpus under `team-knowledge/skills/` through ordinary Git
review. The current catalog contains only its placeholder, so the teammate walkthrough is not
yet end-to-end runnable.

For the first useful proof, aim for:

```text
one real canonical Skill
        ↓
plausibly relevant to two repositories

plus

one unrelated repository
where it should not be selected
```

Additional real Skills are useful, but no arbitrary item count is required. Before starting:

- review canonical Skill content for secrets, personal data, and restricted information;
- confirm participants can install the tool;
- confirm each participant's chosen selector is installed and authenticated;
- verify their Git environment can access the canonical source, currently the
  `repo-adaptive-agents` repository over SSH; and
- when testing Claude consumption, verify the local filesystem supports the required relative
  directory-symlink bridge.

## Choose pilot coverage

Use real repositories and normal engineering work. Aim to cover:

- multiple repositories where the Skill is genuinely relevant;
- at least one genuinely unrelated repository;
- more than one coding-agent product where the team already has them available; and
- at least one selector/consumer mismatch.

For example, selection may happen with Claude while later consumption happens with Codex.
Do not require an artificial fixed provider matrix. Copilot selection is contract-tested but
was not live-smoke-tested during development because Copilot CLI was unavailable; observe the
first real Copilot participant carefully.

## What the teammate does

```text
bootstrap with an available selector
→ inspect the proposed plan
→ apply it if appropriate
→ commit only .team-knowledge durable state
→ use a normal coding agent
→ sync when the operator announces a central change
```

The selector and later consumer are independent. Switching coding agents does not require a
new bootstrap or semantic reassessment.

## What the operator observes

Record lightweight qualitative outcomes:

- selector used;
- Skills proposed and selected;
- obviously relevant omissions;
- obviously irrelevant inclusions;
- whether the teammate understood the bootstrap plan;
- whether committed versus generated state was clear;
- whether a normal coding agent could use the relevant selected Skill;
- whether switching consumer agents caused confusion; and
- any manual copying or installation the teammate believed was necessary.

Do not use `.team-knowledge/events.jsonl` as the core pilot success metric, and do not require
repository-local feedback commands.

## Lifecycle checks

Coordinate at least one real central Skill update and one explicit revocation through normal
Git history when appropriate:

```text
central content update
→ sync
→ selected repositories receive the updated package
→ no manual copying
```

```text
central revocation
→ sync
→ managed package and Claude bridge are removed
```

Prefer a real reviewed update or revocation. Do not invent knowledge solely to manufacture
these outcomes.

## Reconstruction check

On one already bootstrapped consumer, either use a fresh clone containing the committed
config and lock or remove only the generated managed package and bridge. Run sync and verify
that local Agent Skill exposure is reconstructed from committed provenance without semantic
reselection, unless normal sync rules independently require reassessment because the source,
routing metadata, or factual repository evidence changed.

## Failure and confusion signals

- A relevant Skill is repeatedly omitted.
- An unrelated Skill is selected where it has no plausible relationship.
- A teammate must already know canonical Skill names to succeed.
- A teammate manually copies canonical Skill content.
- Switching coding agents appears to require another bootstrap.
- Selector or consumer identity leaks into canonical resource identity.
- Generated `.agents/skills/` or `.claude/skills/` state has to be committed.
- A central update does not propagate.
- Revocation leaves a managed Skill exposed.
- A fresh clone cannot restore generated state from committed config and lock.
- Vendor-specific canonical copies appear necessary.
- The bootstrap plan is too confusing to review confidently.

## Do not benchmark-tune the pilot

- Use real repositories and normal engineering work.
- Do not invent repository evidence.
- Do not hand-select Skills before bootstrap.
- Do not repeatedly rerun selection until an expected answer appears.
- Do not rewrite Skill descriptions merely to force a desired outcome.
- Do not require Codex, Claude, and Copilot to select byte-identical sets.
- Do not optimize selector prompts around the trial.

Model semantic disagreement is permitted. Observe whether it materially harms the product
experience.

## Success criteria

| Check | Evidence sought |
| --- | --- |
| Canonical identity | One reviewed canonical Skill exists, with no vendor-specific copies. |
| Relevant distribution | The Skill is selected in multiple genuinely relevant repositories. |
| Relevant omission | The Skill is omitted from at least one genuinely unrelated repository. |
| Available selectors | Bootstrap works with the supported selectors teammates actually possess. |
| Cross-agent use | More than one coding-agent product consumes selected Skills where available. |
| Selector/consumer independence | At least one selector/consumer mismatch works without reselection. |
| Central update | Sync distributes a canonical content update without manual copying. |
| Revocation | Sync removes managed Skill exposure after explicit revocation. |
| Reconstruction | A fresh clone or deleted generated state is restored from config and lock. |
| Repository hygiene | Generated packages and Claude bridges remain local. |
| Comprehension | Teammates understand the workflow without learning its internal architecture. |

The primary qualitative success statement is:

> Real team knowledge written once is made available in the repositories where it is useful,
> and can be used regardless of whether the developer works with Codex, Claude, or Copilot.
