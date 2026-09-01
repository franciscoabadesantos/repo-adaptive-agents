# Knowledge-resolution research

## What was tested

The research compared technology tags, lexical retrieval, deterministic
resolution, direct model selection, and hybrid model-plus-deterministic
resolution. A later blind holdout varied model-visible resource context and a
structured eligibility condition across repeated trials.

## What happened

The development resolver achieved perfect results on its small authored
corpus, but that corpus and its rules were deliberately narrow. Diagnostic
paraphrases exposed brittle task interpretation. In the blind holdout,
structured gating enforced explicit eligibility but did not establish that the
system should own semantic interpretation, ranking, or coverage.

## What was learned

Models/retrieval should decide relevance. Deterministic code should enforce
only represented, auditable constraints around the selected resources.

## Limitations

- The development corpus contains authored gold and is not blind evidence.
- Lexical TF-IDF was used where embeddings were unavailable.
- Final blind-scoring analysis is not present in the workspace and remains an
  explicit placeholder.

