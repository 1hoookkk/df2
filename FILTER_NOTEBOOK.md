# FILTER NOTEBOOK — the index over everything filter

One page. Read this before authoring, fitting, or judging ANY body. Its job is
to stop sessions from re-deriving work that already exists. If you add filter
work anywhere, add its pointer here in the same commit.

## The good bodies (evidence-graded inventory)

| set | where | why they're good | caveat |
|---|---|---|---|
| P2K ROM corpus (33) | `df2/bodies/rom/P2k_000..032.json` | ground truth — the measured originals; every "is this good?" question is answered against these | read-only evidence, never ship them |
| ship_* five (2026-07-14/15) | `df2/presets/ship_*.body240` + `juce-shell/assets/{bodies,cartridges}/` | 4 corners per body from 4 DIFFERENT measured sources (whistler / iceberg / pulsar / HRTF; vowel LPC; razor combs) | ship_hybrid_cross corners plot as broadband gain slabs (+60..+110 dB shelves) — ear-check before trusting |
| cleanroom P2K replacements | `df2/presets/cleanroom_{megasweepz,lucifers_q}.body240`, provenance in `df2/dev/tmp/cleanroom_p2k_replacements/provenance.md` | full lane provenance, physical gate passed, verified NOT a copy of the reference | **FAILED the replacement null test 2026-07-17**: 35.4 / 44.3 dB from their targets (unrelated ROM pairs median 23.4) — they don't behave like the presets they replace; dropped from the ear page |
| three_layer_* ten | `df2-workstation/plugin/presets/bodies/three_layer_*.body240` | table-derived, stable, morph is real | Q corners are DERIVED (radius-only lerp — centers frozen); weakest corner anatomy of the lot |
| named cartridges | `df2/juce-shell/assets/cartridges/*.json` (anvil, gong, maul, …) | survived past ear rounds | provenance varies — check per body |

## THE method (converged 2026-07-17, advisor-audited): archetype ⊗ rails

**New body = ROM archetype anatomy × new measured rails.**
1. Decode the family's ROM archetype through the stage law (packed words →
   per-lane pole/zero/scale geometry). Frame lanes (e.g. Talking Hedz st0
   air-tilt, st5 body-pole + r=1.0 sliding notch) are copied VERBATIM.
2. Moving lanes keep the archetype's zero-offset (octaves), radii, and scale —
   only the pole CENTER is re-railed to measured table frequencies.
3. Q100 corners inherit the archetype's own per-lane Q0→Q100 transform
   (measured per body — the corpus has NO universal Q direction; the "+0.58
   oct" figure is an |Δ| median of a zero-net-direction scatter, NOT a law).
4. Lane order = archetype lane order (stage correspondence preserved).
5. Compile: `body-from-geometry` (trench-core bin, stage law, 25×25 certify).
6. Gate: bloom in the EMPIRICAL ROM band 13.9–254 dB (median 71); corner +
   morph-sweep TF vs the archetype, shared scale.
7. Ear on broadband material.
Demo set that passed 1–6: `dev/tmp/ship_v2/` (vowel/fuzz/violent/gizmo off
their four archetypes). Builder: session scratchpad `make_ship_presets.py`.
ROM zero grammar (measured, n=198 lanes): 72% independent zero rails, 23%
near-pole, 5% parked. Never co-locate wide zeros on every pole.

## The measured-source corner method (best for NEW families)

`df2/tools/build_hybrid_cross.py` pattern: **each corner is its own pose from
its own measured source.**

- corner from a WAV capture → LPC (`tools/lpc_extract.py`) → poles → kernels
- corner from a magnitude target (HRTF etc.) → `trench_ffi.fit_corner_from_magnitude`
- pack via `pyruntime.packed_interp.coeffs_to_words` → `src/utils/body240.raw_from_words`
- certify: 25×25 `trench_ffi.packed_probe` grid (unstable/nonfinite masks, max radius)

Measured-source pools: `df2-workstation/wav-source-library/` (11 categories:
plasma, ice, seismic, pulsars, bats, machines, instruments, foley…),
SONICOM HRTF (403 subjects, `df2/dev/tmp/hrtf/sonicom/`), and the frequency
tables in `df2/tables/` (vowel_formants, tube_resonances, metallic_modes,
family_intents, membrane_modes, klatt_1980_*).

## Corner law (why "4 distinct corners" keeps coming up)

- A body is 4 AUTHORED poses (M0/M100 × Q0/Q100). Q corners are authored,
  never derived — the recipe formats that lerp radius only (three-layer forge
  `anatomy_state`) cannot make a real Q corner. Measured ROM Q: centers MOVE.
- ROM corners sit on a ~0 dB floor with crowns −3..+27 dB. Stacked broadband
  shelves between corners = not ROM anatomy.
- Stage slot i pairs across corners (permutation-invariant per corner,
  interior-defining across corners) — `trench-core/tests/stage_correspondence.rs`.
  Never score a fit on endpoints only.

## Judging (transfer functions + ear, in that order of cheapness)

- TF views from the PACKED runtime only (`packed_bilinear` → response; never
  design math): corner plots, 21-pose morph sweep, Q-bloom family.
  Session scripts: this session's `compare_vs_rom.py` / `gate_three_layer.py`
  (scratchpad; re-create from this description if gone — ~100 lines each).
- **Bloom gate calibration (measured 2026-07-17):** max pointwise dB rise
  Q0→Q100 over 5 poses, measured on all 33 ROM bodies = **13.9–254 dB,
  median 71**. The old "6–34 dB" number used a different metric — do not
  gate with it against pointwise measurements.
- Ear: `df2/tools/render_tournament.py` (pink noise, keep/kill page) or
  `tools/render_audition.py` (groove). Use broadband material — a bare 808
  masks everything above the first resonance. The ear is the only pass/fail.

## Bytes-truth fix round (2026-07-17)

- QC verdicts: `dev/tmp/bytes_truth_qc/` (26 bodies judged from stored words;
  metric: **floor = MEDIAN dB, crown = max dB**, 30 Hz–19.2 kHz packed TF).
- Fixer: `dev/tmp/bytes_fix/fix_bodies.py` — clamp-aware per-stage SCALE
  median-flatten + residual split + contribution-targeted pole-radius crown
  trim, compiled via body-from-geometry, re-QC'd from packed bytes.
  13/15 broken bodies fixed (all five ship_*); report `dev/tmp/bytes_fix/fix_report.json`.
- QUARANTINED (need corner re-authoring from source, renorm can't help):
  `weird_golden_punch` (M100_Q100 = authored +90 dB Nyquist shelf),
  `weird_picket_ghost` (M0_Q0/M0_Q100 = six stacked aligned low-freq resonances).
- Comb/notch rebuild (same day, "look silly" verdict): the three weak bodies
  re-assembled as archetype ⊗ rails — comb_low_to_sparse ← P2k_030 Tooth Comb,
  razor_cut_field ← P2k_018 Razor Blades, phase_needle ← P2k_026 Dream Weava
  (the notch-ladder photograph). One coherent log-freq transpose per M-pose to
  each body's own authored anchor, radii/scales/offsets verbatim, then floor
  renorm. Copy-risk clear (15.7–28.2 dB RMS from nearest ROM).
  Builder: `dev/tmp/bytes_fix/assemble_comb_notch.py`.
- FULL ARCHETYPE CATALOG (2026-07-17 evening): all 33 ROM archetypes re-issued
  as legal bodies via per-pose musical transpose (searched candidate menu,
  asymmetric semitone pairs so the morph travel changes too) + floor renorm +
  crown trim + 25×25 certify. 33/33 passed copy-risk (7.8–33.8 dB RMS clear)
  and corner QC. Builder: `dev/tmp/bytes_fix/build_all_archetypes.py`; bodies +
  `catalog_report.json` in `dev/tmp/arch_catalog/`. 15 real-pole lanes (of 792)
  approximated as symmetric broad tilts — logged in the report.
- CLEAN-ROOM TEMPLATE (2026-07-17 night): `dev/tmp/bytes_fix/build_vowel_stress_cleanroom.py`
  — bodies from tables + measured grammar ONLY (freqs: public tables; radii:
  r=exp(−πB/fs) from table bandwidths; zeros: atlas motif medians; Q corners
  AUTHORED as their own table poses, never derived). New gate: per-corner
  response distance vs all 132 ROM corners (≥6 dB) on top of surface copy-risk.
  First body `vowel_stress` cleared everything (surface 21.1, per-corner worst
  10.4 dB). The transposed arch_catalog 33 = INTERNAL parts reference only —
  they reproduce rows and carry E-mu names; never ship them.
- Ear round: 24 survivors (11 clean + 13 fixed) staged in
  `dev/tmp/bytes_survivors/`, rendered via shipped engine. Page (with per-body
  4-corner plots) now built by THIS repo's `tools/render_tournament.py` →
  `df2-workstation/dev/tmp/audition/tournament/tournament.html`; the df2 copy
  of the tool is plot-less and superseded. Awaiting keep/kill.

## SALVAGE (2026-07-17 dev/tmp harvest — read before authoring or launching)

- **`df2/dev/tmp/trench_money_pack_rc1/`** — a FINISHED RC1 pack from 2026-06-30:
  four named clean-room bodies (**Rubber Mouth / Mass Driver / Bright Servo /
  Glass Cliff**), each with KEEP verdict + per-body behavior metrics + byte/row
  clean-room audit (0 row matches), plus `LAUNCH_CHECKLIST.md` (product gate,
  demo plan, $49–79 pack / $149 plugin price test) and `PRODUCT_COPY.md`
  (positioning: "playable Morph×Q instrument, not a static filter bank").
  These four ARE V1-menu candidates that already passed every gate.
- Past ear/gate rounds with written verdicts: `powerful_corners/PICKS.md`
  (scored corner-pair picks + the LOW/HIGH same-donor lane rule),
  `premium_filters/KEEP_KILL.md` (mechanical passes, taste UNAPPROVED),
  `shipping_filters_q_authored/KEEP_KILL.md` (the authored-Q four incl.
  ship_deep_mouth lineage), `p2k_shootout_replacements`, `p2k_behavior_filters`.
- NotebookLM fuel bundled → `dev/notebooklm/fuel/` (13 MB): the hz-pack 7-doc
  curriculum, Mo'Phatt manual text, X3 manual PDF, patent US5170369 text,
  Morph Designer manual digest. Upload alongside TRENCH_CONTEXT_COMPILED.md.
- Bulk archive candidates (reproducible render farms, >50% of all files):
  target_browser, production_authoring, thumbwheel_blender, curve_gallery,
  roller batches, x3_warm recolors, the four 216-file arma/diag trees.

## Dead ends (do not resurrect)

- `compile_body` for authoring (GAIN_MAX clamp wrong).
- Derived-Q tooling as the law (QLINK/pressurize) — helpers for one verb only.
- Endpoint-only fit scoring (see stage correspondence test).
- Rule-synthesized deck-of-40 generate→audition loops.

## Measurement/fit harnesses (uncommitted, tested 2026-07-17)

`trench-core/src/bin/tf_oracle.rs` — capture → complex TF estimate → fit
against TRUE packed runtime → train/held-out metrics → null-test bundle.
`tf_harness.rs`, `tf_harness_routed.rs`, `tests/stage_correspondence.rs`.
Method statement: `PRESET_HANDOFF.md`.
