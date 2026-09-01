# repo-adaptive-agents

This branch is the clean product baseline for the next product experiment. The upcoming
v0.1 will test whether an engineering team will contribute useful shared knowledge and
reuse it with coding agents. That product is **not implemented yet**.

## Current validated surface

The product baseline currently exposes the native deterministic admission-control package
at `repo_adaptive_agents.admission_control`. It provides:

- `admit()` for selective resource exposure when content must be withheld from a model;
- `validate()` for deterministic post-model enforcement;
- catalog transition validation and auditable exposure receipts.

This layer handles mechanical controls such as lifecycle, scope, revocation, dependencies,
mandatory and forbidden controls, conflicts, supersession, authority, and exact resource
identity. It does not interpret task semantics, rank knowledge, calculate semantic coverage,
or generate agent teams. Model/retrieval owns semantic relevance.

The initial package extraction is byte-for-byte traceable to the validated frozen tree
`b610f1b1232eeb2840e5cca2ddaf450ba64fa491`; a provenance test pins the five source-file
SHA-256 values.

## Development

Python 3.11 or newer is required.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
```

## Research history

The concise, public-safe decision record is in [`docs/research/`](docs/research/README.md).
It explains the experiments, supported and rejected claims, frozen identities, limitations,
and the registry for separately archived reproducibility artifacts. Private gold, raw model
outputs, and complete evaluation trees are deliberately excluded from normal Git history.

## Legacy tooling

The earlier deterministic repository profiler, capability recommender, provider-resolution
flow, role renderer, and adapter installer remain temporarily available for historical
compatibility. Their CLI commands are marked `legacy`; they are not the v0.1 product path
and are not the primary product story. They will be evaluated for removal in a later,
isolated cleanup after the v0.1 vertical slice exists.

Use `repo-adaptive-agents --help` to inspect those retained commands. No external provider
is downloaded, installed, or contacted by the deterministic CLI.
