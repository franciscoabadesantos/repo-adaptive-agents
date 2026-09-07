# Research and refresh

Research is a design input, not a ritual. Do it before adding or materially changing a Skill
when a conclusion depends on a technology that is new, fast-moving, version-sensitive, or
externally controlled. This includes vendor APIs, DSL schemas, plugins, agent/tool standards,
authentication and authorization models, security behavior, and any capability whose incorrect
assumption could create an unsafe or unusable workflow.

Fresh research is also required when an upstream release/deprecation, target-workspace error,
observed trace, or user report contradicts the current Skill. A stable internal convention
backed by maintained code and focused tests does not need broad external research for an
unrelated wording edit.

## Research proportionally

1. Formulate the decision that the research must change; do not collect generic product facts.
2. Prefer current official documentation, versioned specifications, release notes, and official
   source/schema examples. Use a sanitized target export, trace, or controlled test to confirm
   workspace-dependent behavior.
3. Separate documented capability from target availability and observed behavior. Do not turn a
   documentation example into a claim that the team's workspace is configured for it.
4. Record concise, durable evidence: source identity, relevant version or observation date when
   material, decision supported, and remaining uncertainty. Link or summarize only what changes
   the procedure; do not copy manuals into the Skill.
5. Update the Skill only where the evidence changes agent decisions. Otherwise retain the
   existing guidance and report that no canonical rule changed.

## Keep the catalog fresh without churn

Each technology-facing Skill should make its volatile assumptions visible and say how to verify
them at use time. Trigger review from evidence, not an arbitrary automatic rewrite: a failed
test, an import/runtime error, a vendor change, a new integration, a security concern, or a
recurring request that exposes a gap.

When a review finds a better method, make the smallest supported change, validate it, and keep
the prior method only if it remains a supported compatibility path. If behavior cannot be
verified, label it as not established and provide the evidence needed for a future correction.
