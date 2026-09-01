# Frozen admission-control implementation state

Frozen at `2026-09-01T17:04:23+01:00` after the final verification run. Do not
change the implementation, matching behavior, lifecycle rules, schemas, or
tests before the independent blinded holdout is authored and predictions are
frozen.

## Git state

- Branch: `experiment/admission-control`
- HEAD: `d10dcbde88d405aaf7c5eca36e3a1c44d957345a`
- HEAD tree: `d0233f276dea882a71cac57a31730976b6d773b4`
- Tracked changes relative to HEAD: none
- Untracked files before this freeze record: 185. They include the earlier
  knowledge-resolution experiment and its frozen archive as well as this new
  experimental slice.

Repository policy did not authorize a commit, so the implementation is frozen
as an uncommitted experimental state on the dedicated branch.

## Digests

Admission-control slice aggregate SHA-256:
`601bc2b27450daaa7ef9aad6e34ab879bc60c9d6a31616c89c7bbc7a0616edba`

This is the SHA-256 of the sorted `sha256sum` output for:

- `src/repo_adaptive_agents/admission_control/*.py`
- `tests/test_admission_control.py`
- `experiments/admission_control/README.md`
- `experiments/admission_control/DEVELOPMENT_RESULTS.md`

The freeze record itself is intentionally excluded to avoid a self-referential
digest.

Whole dirty-state aggregate SHA-256 excluding this freeze record:
`5f3bb33ea14cdc21b555e25bf785d19ee272a0e20f34b18dca5faae89dcf2b66`

It was computed from the concatenation of `git diff --binary HEAD` and sorted
per-file SHA-256 lines for every file reported by
`git ls-files --others --exclude-standard`, excluding only this document.

## Slice file hashes

```text
138e2c01fcaff6f1357a1341d76a0278d39aa793d2f10534fd7d846a8d116b23  src/repo_adaptive_agents/admission_control/__init__.py
2530b479d346d03630212afbed7de9deb3e19b4d9b98e27aac773e39b1d86903  src/repo_adaptive_agents/admission_control/admission.py
8fd49f3598635b952d72dc3f28d88e2a27dff15a3881931900478d6da3dd4c5e  src/repo_adaptive_agents/admission_control/catalog.py
9edf494a2c2b40ba9128778c46e5d96ad68b392a24f8b2782635c1b7646425b5  src/repo_adaptive_agents/admission_control/models.py
f22a133bcfd5436c4081a4fc5d355f6bd59ce93bdd2a7b2b32ccf756c4a592a3  src/repo_adaptive_agents/admission_control/pipeline.py
5cc97e84dd801e868c2cfca5d39423d8bfbad2bfa6da378834fe164cc102ef2c  src/repo_adaptive_agents/admission_control/semantic.py
0f8f0eeef9e51bbfb1d30d721ddfcba5f31e3e134da773ad2b3f576b1c755ec6  src/repo_adaptive_agents/admission_control/writer.py
9b4759ab96299a529ed6745a6ed26dca14f75c20b0dff7e6810fe3e32ad61569  tests/test_admission_control.py
09ccb9680f28ec287a6fa69f99d9f43ec124f17e4c213240f666ed8234ad9ef5  experiments/admission_control/README.md
aea7333cdefbfb49dc4c3124febb17f298f4071cb05fd21c052dc6475fad64a7  experiments/admission_control/DEVELOPMENT_RESULTS.md
```

## Final verification

- Focused: 19 passed.
- Full repository: 211 passed, 57 subtests passed.
- Package compilation: passed.
- `git diff --check`: passed.
- No blinded benchmark was created or run.
