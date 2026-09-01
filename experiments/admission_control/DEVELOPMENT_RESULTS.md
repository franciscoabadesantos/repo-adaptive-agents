# Admission-control development results

Status: non-blind development/regression evidence only. The previous holdout
and its gold findings were known before these tests were written. These results
must not be used as independent evidence for the architecture.

The focused suite covers:

- expired, unapproved, wrong-scope, and forbidden resources being absent from
  model-visible selectable context;
- post-model rejection of hallucinated, unexposed, revoked, or otherwise
  inadmissible selections;
- explicit compatibility, Skill harness, and MCP network constraints;
- effective dates, revocation, organization/team/repository/path scope, and
  supersession;
- mandatory broader controls supplementing selected repository knowledge;
- explicit higher-authority precedence and blocking unresolved equal-authority
  conflicts;
- blocking when mandatory controls change between prefilter and validation;
- zero-selection and ambiguous tasks remaining semantic-layer decisions;
- distinct type contracts for Skills, repository instructions, MCP tools and
  resources, policies, and environment contracts;
- complete, hashed, atomic, no-overwrite audit persistence.

Final verification before freeze:

- `./.venv/bin/pytest -q tests/test_admission_control.py`: 19 passed.
- `./.venv/bin/pytest`: 211 passed and 57 subtests passed.
- `./.venv/bin/python -m compileall -q src/repo_adaptive_agents/admission_control`: passed.
- `git diff --check`: passed (the new slice is untracked, so focused tests and
  compilation are the substantive checks for those files).

No blinded benchmark was created or run.
