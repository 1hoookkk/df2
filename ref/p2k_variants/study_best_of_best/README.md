# P2K Best-Of-Best Study Corpus

Study-only recovered reference data. Do not ship it.

The exact `.bin` bytes and their packed words are the oracle. Analysis fields
are derived by loading those exact bytes through `trench_core`'s packed runtime
FFI at a `5 x 5` `MORPH x SECONDARY` grid. This preserves numerator and
denominator behavior: every sampled stage reports both poles and zeros.

Files:

- `exact_packed_bodies.jsonl`: lossless records, packed words, hashes, and
  sampled runtime-derived cavity analysis.
- `body_index.csv`: compact inventory.
- `sampled_cavities.csv`: flat analysis table for clustering and comparison.
- `frequency_grid.json`: frequency axis shared by every response curve.
- `response_curves.jsonl`: packed-runtime response arrays for plot tooling.
- `compact_algorithm_evidence.json`: endpoint-plus-center cavity view sized for
  a focused analysis prompt.
- `algorithm_evidence_digest.json`: smaller analytical digest for token-limited
  model runs.
- `algorithm_prompt_digest.json`: tuple-compressed digest for the focused Pro
  prompt.
- `llm_clarity_pack.json`: single-upload prompt context for relationship-level
  design analysis across the nine favorite bodies.
- `manifest.json`: layout, counts, provenance boundary, and file map.

The raw fixture bytes remain under `ref/p2k_variants/P2k_*`. This export is a
machine-readable study view, not an original-authoring library.
