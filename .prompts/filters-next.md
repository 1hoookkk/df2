# THE BYTES ARE THE INSTRUMENT

You are working in C:\Users\hooki\df2-workstation. Read FILTER_NOTEBOOK.md first — it is the index; trust it over any handoff.

Everything you need already exists on disk. You are not inventing filters, you are ASSEMBLING them:

- **The ground truth**: `df2/bodies/rom/P2k_000..032.json` — 33 measured E-mu bodies. Decode them through `trench-core/src/stage_law.rs` before believing ANY claim about what filters do. Q is a second morph axis with four verbs (slide, relocate, grow, bloom) — measure the verb per body, never assume.
- **The raw material**: `df2/tables/` (measured formants, bandwidths, metal modes, family intents), `wav-source-library/` (11 categories of captures), SONICOM HRTF (403 subjects).
- **The one compiler**: `trench-core --bin body-from-geometry` — geometry JSON → certified 240 bytes. Nothing else writes bodies.
- **The verdicts so far**: `dev/tmp/bytes_truth_qc/qc.html` — 26 bodies judged from their stored words: 11 clean, 15 broken with exact per-stage diagnoses sitting next to each plot.

THE LAW THIS PROJECT KEEPS RE-LEARNING, SO DON'T:
1. **Judge the bytes.** Decode the stored words and plot ALL FOUR corners. Geometry-space plots and Q=0 slices lie by omission. The encoder's scale clamp (3.95) silently breaks floors — measure after it, always.
2. **Four corners = four authored photographs.** Any corner derived by formula is a dead body. The archetype's own decoded Q transform is the only legal Q source.
3. **New body = archetype anatomy ⊗ measured rails.** Copy frame lanes verbatim, re-center moving lanes to table data, keep lane order (stage correspondence is real: `trench-core/tests/stage_correspondence.rs`).
4. **The loop closes on audio.** Coefficients → bytes → shipped-engine render (broadband, never a bare 808) → the ear. Tyson's ear is the only pass/fail. One preset at a time.

THE NEXT MOVES, IN LEVERAGE ORDER:
1. Fix the 15 broken bodies using their per-stage diagnoses — most are one clamp-aware renormalization away. The ship_* five are the prize: their corner SOURCES (whistler/iceberg/pulsar/HRTF) are great, their gain staging is broken.
2. Put the 11 clean bodies on one audition page for the ear. Kill or keep.
3. Whatever survives: package as cartridges through the one load path (Body strip → roster → loadCartridge).

Do not create new tools. Do not re-derive the method. The instrument is on disk — play it.
