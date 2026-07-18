# PRESET HANDOFF — converge, then ship 4–7 ROM-grade presets

**Written 2026-07-17, after the UI-lock session (branch `ui/five-point-cleanup`,
tip `0280811c`). The UI is locked and installed; the engine AMOUNT law is fixed
and test-proven (`trench-core/tests/amount_law.rs`). This handoff is about the
SOUND.**

## The task

1. **LOOK AT THE RECENT FILTER WORK FIRST — this is the whole point of the
   handoff.** The most recent filter work is sitting UNCOMMITTED in this
   working tree and in the newest untracked files; it is closer to the answer
   than anything in git history. Start with:
   `git status` + `git diff trench-core/src/minifloat.rs trench-core/src/response.rs`
   (another session's in-flight engine work — read it, judge it, fold it in or
   flag it), the untracked `trench-core/src/bin/tf_harness.rs`,
   `tf_harness_routed.rs`, `tf_oracle.rs`,
   `trench-core/tests/stage_correspondence.rs`, and
   `workstation/src/bin/trench_studio.rs` plus the modified
   `workstation/src/{app,model}.rs`. Only then widen to the rest:
   - `trench-core/src/bin/tf_harness.rs`, `tf_harness_routed.rs`,
     `tf_oracle.rs` — the response-measurement harnesses against the TRUE
     packed runtime.
   - `trench-core/tests/stage_correspondence.rs` — the stage-law certification.
   - The typed-grammar work (measured c4 third-ingredient + bandwidth-transpose
     Q law — lives as a dev/tmp monkeypatch, still needs its Rust port).
   - The existing three-layer bodies already in `plugin/presets/bodies/`
     (`three_layer_metal_bell_to_free_*` etc.) and everything the smoke test
     showed loading (`CAVL_*`, `METALL_*`, `RISERL_*`, `FUZZ_*`).
   - The morph_designer authoring path (NOT compile_body — its GAIN_MAX clamp
     is wrong for authoring).

2. **Converge on ONE method.** The recurring failure of this project is
   re-inventing the pipeline every session. Pick the single authoring method
   the evidence supports, write it down in this file's "Method" section, and
   use it for every preset. No new abstractions, no new tools unless the
   method literally cannot run without one.

3. **Deliver 4–7 usable presets** that sound like the ROM filters, built with
   the **three-layer system**. Usable means: survives Tyson's ear on real
   drums, not just clean plots.

## Laws that gate every preset (from measured evidence — do not re-derive)

- Authoring goes through morph_designer semantics; frequencies are pulled from
  measured tables, never invented.
- ROM Secondary law: Q MOVES CENTERS (median 0.58 oct), r→r^0.356, coherent
  transpose is the bloom lever. Q must BLOOM (real ROM bodies bloom 6–34 dB
  under Q) — a preset whose Q does nothing is dead on arrival.
- ROM corner-crown law: crowns sit −3..+27 dB at EVERY corner; respect the
  per-corner crown floor.
- The preset anatomy atlas (P2k_000–032) is the only valid evidence corpus;
  the RE vault (`trench_re_vault` behavioral_contract.yaml) is ground truth
  for any "is this faithful?" question.
- 4 corners are DERIVED from the home→away intent, never hand-placed; serial
  cascade needs flat-off-resonance sections.
- Morph must ride the per-sample coefficient ramp (already in the engine) —
  audition the MOVEMENT, not just endpoints.

## Acceptance per preset (all four, no skipping)

1. **Plot** — big dB-vs-log-Hz curves at pose 0 / 25 / 50 / 75 / 100, drawn
   from the packed runtime coefficients (the harness, not the design math).
2. **Bloom check** — Q sweep shows real bloom within the measured ROM range.
3. **Output audit** — measure the AUDIO (level-matched), not just the plot;
   the plot cannot see post-cascade damage.
4. **Ear** — render through the shipped engine and put it on the audition
   page (`/audition`) for Tyson. His ear is the only pass/fail.

## Working mode

Low reasoning is the right setting for this (Tyson-confirmed) BECAUSE the
method forbids invention: assemble from the measured laws, render, prove,
show. If a design step genuinely needs deep derivation, say so and slow down
for that step only. One preset at a time to the ear — never a deck of forty.

## Method (converged 2026-07-17 — survey done, tests green with the in-flight engine diff)

Author each preset as METHOD.md's 6-letter word written twice: six lanes from
the 8-shape alphabet, posed at the LOW and HIGH morph frames, frequencies
pulled from the measured tables (DVTD rails / HRTF / anatomy atlas), using
morph_designer semantics (`df2/tools/morph_designer.py` — flat-off-resonance
shapes that compose serially, packed through the real encoder; never
compile_body). Q corners are AUTHORED poses per the closed Q100 law — one
named verb per body (BLOOM / SPREAD / SCREAM / FLIP) sized to the measured ROM
bloom range — never derived by formula. Judgment then moves entirely to the
packed runtime via the TF harnesses: plot poses 0/25/50/75/100 from
`interpolate_biquad → biquad_cascade_complex` (tf-harness path), Q-sweep bloom
check against the 6–34 dB ROM range, level-matched output audit on rendered
audio (tf-oracle verify semantics: residual/null, not just curves), then
render through the shipped engine to `/audition` for the ear. Stage
correspondence is real (`tests/stage_correspondence.rs`): lane i LOW must be
the same physical object as lane i HIGH — pair lanes by identity when
authoring, and any fit-based step must score interior morph points, never
endpoints only. One preset at a time; no new tools.

**Pipeline per preset:** pick family + home→away intent → spell the word
(table frequencies) → author 4 corner poses → pack via the verbatim
words path → plot 5 poses + bloom from packed runtime → output audit →
`/audition` → Tyson's ear passes or the preset dies.
