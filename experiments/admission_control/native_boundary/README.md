# Native admission-control boundary

This directory is development evidence, not a benchmark or product
integration. `thin_runner.py` demonstrates the intended boundary:

```text
public dictionaries
  -> representation translation
  -> native admit()
  -> caller-owned retrieval/model callbacks
  -> native exposure receipt
  -> native validate()
  -> serialization
```

The runner contains no lifecycle, scope, predicate, compatibility, dependency,
supersession, mandatory/forbidden, authority/conflict, exposure, or final
admission decisions. Those decisions originate in
`repo_adaptive_agents.admission_control`. The callbacks deliberately have no
reference semantic implementation: a future evaluation must supply the same
retrieval and model behavior to each condition.

Known prior benchmark cases are used only in the package's labelled
development/regression tests. No prior benchmark IDs, task tags, organization
vocabulary, scoring logic, or A/B condition logic is part of this boundary.
