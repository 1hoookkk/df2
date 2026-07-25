# FILTER NOTEBOOK

> PART 1 is law. Every claim: number + date + proof path. If the proof stops
> passing, the claim is dead — fix or delete, never amend in place. One home
> per fact; other files may point here, never restate.
> PART 2 is standing methods, inventory, and dead ends. No prose anywhere.

# PART 1 — CANON

## 1. What a body is

- 240 bytes = 4 corners × 6 rows × 5 packed u16 words, authored at 39062.5 Hz.
  [`python -m tools.filter_cli pack`; decode `pyruntime.packed_interp`.]
- Row = biquad: pole (Hz, r), zero (Hz, r), SCALE word.
- Corners = (M0,Q0) (M100,Q0) (M0,Q100) (M100,Q100) — ALL FOUR AUTHORED.
- Judge through the packed runtime only, never design math.
  [`trench-core/src/minifloat.rs`, `stage_law.rs`.]

## 2. DSP foundations [literature]

1. Serial sections add in dB. (Oppenheim & Schafer.)
2. Stable iff poles strictly inside unit circle; enforced as packed r < 1 over
   a Morph×Q grid. [`filter_cli pack` certifies.]
3. r ≈ exp(−π·B/fs). (Klatt 1980 §5.)
4. Scaling a section's numerator by k = uniform 20·log10|k| dB; cannot change
   contrast. (RBJ cookbook.)
5. Vowels = formants + zeros from side branches; magnitude-only fitting cannot
   recover zeros. (Fant 1960; Sanathanan-Koerner in `filters/rails/dvtd_rails.py`.)
6. Perception is log-frequency; equal musical motion = equal log-Hz travel.
7. Tube partials f_n = n·v/2L harmonic; free-bar 1 : 2.76 : 5.40 : 8.93
   inharmonic = the metallic signature. (Fletcher & Rossing; tables §5.)
8. Level differences masquerade as quality; level-match and blind. (BS.1116.)

## 3. Project laws

- **L1. All 4 corners are AUTHORED. Q100 derivation is disproven.** MD-Q
  (bw ×0.375, centers/zeros held) misses real E-mu Q100 cascades by median
  max 32 dB, 200/204 pairs >6 dB off; centers move (median 0.19 oct), 108/880
  stages loosen (measured 2026-07-25, 102 bodies, `dev/tmp/dominance_test/`
  session audit). MD-Q = fallback verb only. Dead Q knob ⇒ re-author the two
  Q100 poses. [validator `tools/register_lanes.py` rejects derived Q100;
  `python -m tools.test_register_lanes`.]
- **L2. Stage slot i pairs across corners** — never score endpoints only.
  [`trench-core/tests/stage_correspondence.rs`.]
- **L3. SCALE = b0 = pure broadband level**; bounds crown, cannot move
  contrast. [`stage_law.rs` + pinned test.]
- **L4. Corner crowns sit −3..+27 dB** (ROM corpus). Bound hot bodies with a
  body-wide SCALE multiplier. [census `filters/docs/REFERENCE.md`.]
- **L5. Contrast lives in poles+zeros.** Deepen zeros = ear-safe; uniform
  pole-radius boost = ear-killed (+0.010 surgery, 2026-07-21; evidence LOST —
  re-prove before retry).
- **L6. Pole and zero of a stage move independently** (mean disagreement
  1.75 oct, n=200); stage number ≠ frequency rank (54% scrambled).
  [`dev/notebooklm/fuel/01_stage_logic.md`.]
- **L7. Bound gain with two numbers per corner: crown ≤ +27 and contrast.**
  141-body audit: all stable (max r 0.99955), gain budgets 0→107 dB median 43.
  [script LOST — re-run before relying.]
- **L8. Ship roster authority = `plugin/presets/approved_bodies.txt`**,
  hand-maintained; ear-approved families: ship_v2, master_body_trial.
  (`HANDOFF_20260721_NIGHT_shipping.md` §0.)
- **L9. Pass signature = alive on both axes + bounded** (n=18): Q travel
  ≥0.09 oct, morph jerk ≥20.7 dB, crown ≤~50 dB. Falsified at same n:
  direction coherence, monotonicity, near-cancellation, contrast. Necessary,
  not sufficient — ear decides. [`dev/tmp/why_pass_20260721/analyze.py`.]
- **L10. FRAMING LAW (ear-approved 2026-07-25, pink-noise A/B, B_FRAMED
  chosen):** corner crowns +2 / +8 / +25 / +27 dB (M0Q0/M100Q0/M0Q100/
  M100Q100), rewritten via SCALE words only. Tool + 21 certified CAVL bodies:
  `dev/tmp/framed_cavl/frame_cavl.py` (0 non-SCALE bytes, maxR 0.99890,
  nulls vs approved B within 0.03 dB).
- **L11. Crown travel (median 5.39 oct, 102 bodies) = STAGE DOMINANCE
  HANDOFF** in 67% overall, 85% of the 33 P2K ship presets (median 2 distinct
  dominant stages per body); the rest are full-stack slides (poles 3.3+ oct,
  REAL/open at a corner). Author characters by choosing which stage wins each
  corner; sweeps by sliding the stack. [`dev/tmp/dominance_test/`;
  HYPOTHESIS_BRIEF.md §3.]
- **L12. E-mu authored 51/51 P2K skins with all six stages active at every
  corner** (zero identity rows; 46/51 no flat stage at M0Q0). "2–3 sections"
  in the manual = teaching heuristic, not ROM practice. (2026-07-24.)
- **L13. P2K Q-pose statistics** (51 banks, 2026-07-25): bandwidth ×~0.375
  median under Q (EQ 0.379, LP/HP 0.374; typed_vowl 0.356 agrees); gain not
  the lever (median −0.3 dB); center moves per-preset design (median ~0, huge
  spread); ~25% loosen. Descriptive statistics — NOT a derivation law (L1).

## 4. Plot law

- All response plots share the fixed −60..+30 dB scale; per-plot autoranging
  forbidden. Dense packed-runtime evaluations (1024 log pts, 20 Hz → just
  under Nyquist), thin unsmoothed polylines.

## 5. Metrics — the only allowed meanings of "dB"

- **crown** — max |H| of a corner, QC grid (30 Hz–19.2 kHz, 512 pts, packed
  probe). **floor** — median |H| same grid. **contrast** — crown − floor.
- **surface distance ("copy-risk")** — RMS of Morph×Q surface vs nearest
  reference body; ship ≥ 6 dB clear. (`filters/docs/PRIOR_ART_LEDGER.md`.)
- **bloom** — max pointwise rise Q0→Q100 over a pose sweep. ROM band
  13.9–254 dB (median 71, n=33) — descriptive, not a gate.
- **fit residual** — RMS vs target in a stated band. DVTD gate ≤ 6 dB floored
  100–5000 Hz.

## 6. Evidence base

| what | where |
|---|---|
| Klatt 1980 formants/bandwidths | `filters/tables/klatt_1980_*.json` |
| Peterson-Barney vowels | `filters/tables/vowel_formants.json` |
| Tube + metal modes | `filters/tables/tube_resonances.json`, `metallic_modes.json` |
| DVTD 44 measured VVTFs (mag+phase) | `filters/rails/dvtd_rails.py` |
| SONICOM HRTF P0001 48 dirs | `filters/rails/hrtf_rails.py` (full: 403 subj `df2/dev/tmp/hrtf/sonicom/`) |
| Rossum US5170369 + E-mu manuals | `dev/notebooklm/fuel/` — study only |
| P2K ROM corpus (33) | `df2/bodies/rom/` — study only, never ship complete bodies |
| Heritage MorphDesigner XML (69 compiles) | `dev/tmp/xml/*.body240` |
| Intent tables (7 families, real physics) | `trench-filters/data/tables/family_intents.json` — read-only |
| Measured-source WAV pools | `wav-source-library/` |

Operator rules: complete-row hybrids = approved study candidates with exact
ownership evidence; clean-room reconstruction is the separate shipping step.
X3 donor surgery allowed (2026-07-24: decoded fixed-class stages as donor
material in new hybrids); verbatim whole-preset shipping stays out.

## 7. Ear protocol

- Gate order: pack+stability → copy-risk → plots → ear. Ear is the only
  pass/fail for character.
- Venue: live plugin, or `tools/render_tournament.py` (pink noise, shipped
  engine). Broadband material only — a bare 808 masks above the first
  resonance.
- Record every verdict with date + material, else it is folklore.
- Gap: no formal level-match/blind protocol yet (BS.1116 is the standard).

## 8. Workstation laws (authoring app — `plugin/native/WorkstationEditor.cpp`)

- BIN = P2K BIQUADS (donor-only) + SAVED + measured rails + LAB reopenables;
  X3 bank rip = teacher evidence, bytes never enter a working body.
- Position law: nothing moves the XY puck except the user's grid drag.
- Real-pair rows: conjugate editor cannot express them; recast is EXPLICIT
  only, drags refuse degenerate rows. (Byte-proven 2026-07-24.)
- Stage = START + END minis per Q side; chip drop on a mini loads that
  endpoint; CTRL+drop = active corner only (byte-proven single-corner scope).
- Probe transparency: UNSTABLE stages draw red; only NONFINITE zeroed.
- Audition defaults to CHAIN (shipping path), SOLO is the toggle; gain budget
  = −(mean of 5-pose median dB) clamp ±12; body switch loads MIX 100;
  MIX = true latency-compensated linear wet/dry (PunchBlend deleted).
- Autosave on program switch: `Documents/TRENCH/bodies/AUTOSAVE/`.
- Headless proof harness: `TRENCH_WS_SCRIPT` JSON actions — real code paths.
- Stage roots↔words FFI: `trench_stage_roots_from_words` / `_from_roots`
  [`cargo test --lib stage_roots_words_ffi`]. Load
  `df2-workstation/target/release/trench_core.dll` — the df2 dll is stale.
- SHIP STATE 2026-07-25 (installed): TYPE = SIGNATURE 5 ear picks + Contrary
  Sweeps; ship-v1 archived at `presets_ship_v1/`. Roster cut 63→40 name-true
  (2026-07-25); VST3 builds, NOT INSTALLED (gate).
- Wheel asset: `plugin/assets/trench_roller_strip.png` (128×139×31, master
  blend `wheel_variant_slate_charcoal_master.blend`); no procedural re-meshing.

# PART 2 — STANDING METHODS, INVENTORY, DEAD ENDS

## Methods that stand

- **Intent → geometry → framing:** HOME/AWAY from
  `trench-filters/data/tables/family_intents.json` (real physics) → framing
  per L10. The generator's output was never framed before 2026-07-25.
- **Archetype ⊗ rails** (2026-07-17): ROM archetype anatomy × new measured
  rails; frame lanes verbatim, movers re-railed (pole centers only), Q corners
  inherit the archetype's own per-lane transform. Passing set `dev/tmp/ship_v2/`.
  ROM zero grammar n=198: 72% independent rails, 23% near-pole, 5% parked.
- **Measured-source corners** (`df2/tools/build_hybrid_cross.py`): each corner
  its own pose from its own measured source; LPC or magnitude fit → words →
  25×25 certify.
- **TF-ingest** (`tools/tf_ingest.py`): any IR/modal table → QC-grid |H| →
  fit. violin_cave APPROVED ("Yes thats the sound"). Detilt before fitting
  dense sources (raw piano residual 86.9 dB).
- **Registered lanes** (`tools/register_lanes.py` + schema + 24 tests): the
  authoring layer; validator enforces L1/L2/provenance.
  Feed: `tools/extract_candidates.py` (+16 tests, `fit-candidates` bin).
- **LPX writer port** (`dev/tmp/port_lpx_writer.py`, 2026-07-24): vault
  CPhantomMorphLPX law → certified body generator; pattern extends to the
  other menu writers (need vault decompiles).
- **Framing tool**: `dev/tmp/framed_cavl/frame_cavl.py` (L10).
- **Dominance audit**: `dev/tmp/dominance_test/dominance_test.py` (L11).

## Inventory

- 21 framed CAVL bodies certified, awaiting ear one at a time:
  `dev/tmp/framed_cavl/`. First A/B (wine→tin) delivered 2026-07-25.
- RC1 salvage: `df2/dev/tmp/trench_money_pack_rc1/` — four clean-room bodies
  with KEEP verdicts + launch checklist + product copy.
- 12 old-school hybrids: `plugin/presets/bodies/` + provenance md
  (operator-promoted 2026-07-22).
- Ship provenance audits: `dev/tmp/ship_provenance.json`,
  `corner_provenance.json`; clean-room duty: CLEANROOM_BRIEF.md (11 ship
  presets carry verbatim E-mu corners incl. all five ear picks).
- Verdict archives: `powerful_corners/PICKS.md`, `premium_filters/KEEP_KILL.md`,
  `shipping_filters_q_authored/KEEP_KILL.md`.
- Uncommitted harnesses: `trench-core/src/bin/tf_oracle.rs`, `tf_harness*.rs`.

## Dead ends (do not resurrect)

- Deriving Q100 from Q0 as law — disproven by measurement (L1). QLINK /
  pressurize / mdq = fallback verbs only.
- Endpoint-only fit scoring (L2).
- Floor-down/crown-keep reshape via SCALE (contradicts L3; measured dead
  2026-07-21).
- `compile_body` for authoring (GAIN_MAX clamp wrong; stage_law test).
- +0.010 uniform-radius Q-bloom surgery — ear-killed 2026-07-21.
- ROM-fundamental / frame+voice stage authoring — zero passing presets
  (verdict 2026-07-21); `.prompts/002-measured-cross-presets.md` = DO-NOT-RUN.
- Decoding fixed-class ROM tables as biquads — they are WRITER SOURCE TABLES
  (a2=0 rows, +71 dB DC corners, 2026-07-24); any fit against them is a fit
  of garbage. True targets: port the per-class writers (vault) or wet-capture
  (`ref/canonical/talking_hedz`). X3 ghost curves for fixed classes are
  SUSPECT until re-verified. X3 @44.1k applies sqrt warping; 39062.5 is the
  coefficient domain.
- Anatomy-FM (audio-rate morph) — "FM sounds wrong" (2026-07-18); revival
  needs a new method, not parameters. Per-sample coefficient ramp is LAW.
- bodyN (>6 stages) — inaudible vs 6 on drums (3.75→2.45 dB RMS); wait for a
  source that audibly needs it.
- Rule-synthesized generate→cull decks (~40 died 2026-07-18); phone decks.
- Invented composite scores (median-|H| makeup gain, response-distance
  provenance, harmonic-series fit — all confidently wrong 2026-07-25,
  HYPOTHESIS_BRIEF.md §5). Prefer byte counts, peak levels, hashes.
- Distance-threshold originality gates — reward micro-shift copies; deleted
  twice. Provenance is how a body was MADE.
