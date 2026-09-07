# Catalog design

Start from the recurring decision an agent must make, the evidence it needs, and the safety or
quality failure a maintained procedure prevents. Do not create a Skill merely because a tool,
endpoint, or product has a named feature.

Use a single Skill when operations share the same discovery context, boundaries, and
foundational evidence. Use references for modes that differ only after the Skill is activated:
for example read versus write, migration versus repair, or ordinary versus batch work. Keep the
entrypoint short and route explicitly to the one reference required.

Create a separate Skill only when all of these are true:

- its description has a distinct, durable trigger for semantic selection;
- it requires materially different authorization, failure handling, or validation;
- its guidance can evolve independently without making the parent Skill harder to use.

Avoid a catch-all product Skill that becomes an undocumented manual, and avoid one Skill per
endpoint or UI action. Re-evaluate the catalog when an active repository would plausibly select
several nearly identical Skills for routine work.

When consolidating Skills before consumers have installed them, a clean replacement can be
appropriate. Once active consumers may have materialized an old Skill, use the catalog's
explicit lifecycle/revocation mechanism so synchronizations can remove it safely; do not delete
it in a way that leaves consumers with untracked stale copies.
