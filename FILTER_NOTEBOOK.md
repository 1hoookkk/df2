# FILTER NOTEBOOK — canon first, history second

> **How to read this file.** PART 1 is the only authoritative layer. Every claim
> carries an evidence tag:
>
> - **[LIT]** — established in published literature or a primary source held in
>   this repo. Citation given; needs no project-specific evidence.
> - **[PROOF]** — reproducible in this repo today by the named command or test.
>   If the command stops passing, the claim is dead: fix it or delete it.
> - **[MEASURED]** — measured in a past session; the evidence path is named and
>   was verified to exist. Data, not doctrine.
> - **[LOST]** — the evidence no longer exists. Do not rely on it; re-prove
>   before use.
>
> PART 2 is the session log — archaeology kept for context. **Nothing in PART 2
> is true until promoted into PART 1 with a tag and evidence.** Where the two
> parts disagree, PART 1 wins. (Rebuilt 2026-07-21: the log used to BE the
> notebook; verdicts and lore were cited as law. That era is over.)

---

# PART 1 — CANON

## 1. What a body is

- A body = **240 bytes = 4 corners × 6 rows × 5 packed u16 words**, authored at
  39062.5 Hz. [PROOF: `python -m tools.filter_cli pack x.geometry.json out.body240`;
  decode via `pyruntime.packed_interp.words_to_coeffs`.]
- A row = one biquad section: pole (Hz, r), zero (Hz, r), SCALE word.
- A corner = one authored pose of all 6 rows. The four corners are
  (Morph 0, Q 0), (Morph 100, Q 0), (Morph 0, Q 100), (Morph 100, Q 100).
- The runtime interpolates packed words. Judge everything through the packed
  runtime, never design math. [PROOF: `trench-core/src/minifloat.rs`,
  `trench-core/src/stage_law.rs`.]

## 2. DSP foundations [LIT]

1. **Cascade additivity in dB.** Serial sections add in dB magnitude: a body is
   the sum of 6 lane curves at a frozen knob. (Oppenheim & Schafer,
   *Discrete-Time Signal Processing*.)
2. **Stability.** A causal biquad is stable iff its poles lie strictly inside
   the unit circle; the exact coefficient test is the stability triangle
   (1+a1+a2 > 0, 1−a1+a2 > 0, 1−a2 > 0). (Oppenheim & Schafer.) Enforcement
   here: packed pole radius < 1 across a Morph×Q grid. [PROOF: `filter_cli pack`
   grid-certifies every emitted body.]
3. **Pole radius ↔ bandwidth:** r ≈ exp(−π·B/fs). The resonator relation used
   by the cascade formant model. (Klatt 1980, §5.)
4. **Numerator scaling = level only.** Scaling all b-coefficients of a section
   by k shifts |H| by 20·log10|k| dB uniformly — it cannot change peak-vs-valley
   contrast. (Algebra; RBJ Audio-EQ-Cookbook convention.)
5. **Source-filter model.** Vowels = source + vocal-tract resonances (formants);
   antiformant zeros arise from side branches/nasalization/frication. Magnitude-
   only analysis cannot recover zeros; phase-aware rational fitting can.
   (Fant 1960, *Acoustic Theory of Speech Production*; Sanathanan & Koerner 1963
   complex rational fitting — implemented in `filters/rails/dvtd_rails.py`.)
6. **Pitch perception ≈ log-frequency** (Bark/ERB scales; Moore & Glasberg).
   Equal musical motion = equal log-Hz travel — the basis for log-space morph.
7. **Resonator physics.** Open-open tube partials: f_n = n·v/2L, v ≈ 343 m/s —
   harmonic series. Free bar modes ≈ 1 : 2.76 : 5.40 : 8.93 — inharmonic; the
   inharmonicity is the metallic signature. (Fletcher & Rossing, *The Physics
   of Musical Instruments*. Repo tables: §5.)
8. **Listening judgments.** Small level differences masquerade as quality
   differences; formal protocols level-match and blind. (ITU-R BS.1116.)

## 3. Project laws (this engine, this format)

- **L1. Q100 is a second AUTHORED pose, never derived.** A dead Q knob means the
  Q100 poses were authored flat; fix = re-author the two Q100 corners, leave Q0.
  [PROOF: the validator in `tools/register_lanes.py` rejects derived Q100;
  `python -m tools.test_register_lanes`.]
- **L2. Stage slot i pairs across corners** — never score a fit on endpoints
  only. [PROOF: `trench-core/tests/stage_correspondence.rs`.]
- **L3. SCALE = raw b0 = pure broadband level** (§2.4 applied to the packed
  word). Use ONLY to bound absolute crown; it cannot move contrast.
  [PROOF: `trench-core/src/stage_law.rs` + pinned test.]
- **L4. Crown ceiling +27 dB.** ROM corpus corner crowns sit −3..+27 dB.
  [MEASURED: zeros/corner census, `filters/docs/REFERENCE.md`.] Bound a hot
  body with a body-wide SCALE multiplier (L3 keeps morph relationships intact).
- **L5. Contrast lives in poles+zeros.** Deepening zeros carves valleys without
  touching pole tuning — ear-safe (§2.4 corollary). Uniform-radius pole boosts
  are ear-risky; the +0.010 uniform-radius surgery was ear-killed. [LOST:
  session evidence died with a scratchpad — re-prove before re-attempting.]
- **L6. Pole and zero of a stage move independently** (mean disagreement
  1.75 octaves, n=200 variant bodies); stage number ≠ frequency rank (54%
  scrambled). [MEASURED: `dev/notebooklm/fuel/01_stage_logic.md`.]
- **L7. Bound gain with TWO numbers per corner: crown (≤+27, L4) and contrast.**
  The 141-body audit found all stable (max r 0.99955) but gain budgets 0→107 dB,
  median 43. [LOST: audit script died with a scratchpad; numbers recorded but
  not re-runnable — re-run before relying.]
- **L8. Curation before bounding.** Ship set = `plugin/presets/approved_bodies.txt`,
  the single hand-maintained roster authority (auto-regenerators frozen
  2026-07-21). Only two families are ear-approved: `ship_v2`,
  `master_body_trial`. (Verdict record: `HANDOFF_20260721_NIGHT_shipping.md` §0.)
- **L9. The pass signature is "mechanically alive on both axes + bounded", NOT
  morph coherence** (n=18: 7 pass vs 11 ear-rejected). All 7 passers have a
  real Q scene (Q travel ≥ 0.09 oct), a morph that moves the response (jerk
  ≥ 20.7 dB), and crown ≤ ~50 dB. 9/11 rejects fail ≥1 of: dead Q (6), flat
  morph (6), crown >110 dB (2). Falsified at the same n: pole-travel
  direction coherence, trajectory monotonicity, near-cancellation, contrast.
  2 rejects (tube_shout, throat_bend) pass all mechanical gates — their failure
  is character-level, not geometric. [MEASURED:
  `dev/tmp/why_pass_20260721/analyze.py`, packed-runtime probe, 2026-07-21.]
  Necessary conditions, not sufficient — the ear still decides.

## 8. TRENCH/X3 Roller Wheel Asset & Seating (Verified 2026-07-22)
- **Master Blend**: `wheel_variant_slate_charcoal_master.blend` (authored salvage mesh `geometry_0.001`, Z=0.38 top-left key light, Slate Charcoal OEM material `[0.08, 0.082, 0.085]`, metallic 0.35, roughness 0.38). [PROOF: `wheel_variant_slate_charcoal_master.blend`].
- **Shipping Runtime Asset**: `plugin/assets/trench_roller_strip.png` (128-frame 139×31 strip with fin ridge glow occlusion). [PROOF: `plugin/assets/trench_roller_strip.png`].
- **Faceplate Composite Proof**: `candidate_slate_charcoal_oem/trench_face_slate_charcoal_oem_proof.png`.
- **Key Law**: No procedural polar re-meshing or synthetic gear geometry; preserve authored salvage `geometry_0.001`. Fin ridge glow occlusion in `build_measured_glow_128.py` prevents cyan LED backlight from seeping through solid plastic fin blades.

## 3.5 TRENCH Workstation — the authoring surface (built 2026-07-24)

- `TRENCH_Workstation` (plugin/native/WorkstationEditor.cpp, existing CMake target)
  is the designer-only authoring app, visual-first (redesigned + stripped to
  load-bearing 2026-07-24): BIN = P2K BIQUADS (`df2/ref/presets/*.bin`, 51
  engine-ready 240-byte ROM extractions — verified byte-identical to the
  `bodies/rom` compiled-v1 jsons and engine-decoded to the vocal atlas formant
  ladder for talking_hedz) + SAVED/<family> user-body sections (collapsed,
  grouped by the operator's own name prefixes) + X3 REFERENCE only — no
  trench-generated pools (forge auto, desk, recipes, baked roster all removed
  from the source path per operator directive). P2K entries are the only
  donor/source material; SAVED entries open as working programs and cannot feed
  the donor tray. The BIN also exposes, without bulk-scanning either tmp tree:
  `trench-filters`' five named measured/simulated rail wells as non-packed
  authoring material; the three explicit `df2/dev/tmp/author_sheet` ear picks;
  and the collapsed `df2-workstation/dev/tmp/usable` set. The latter two are
  reopenable LAB programs only, never donors or promoted bodies. The X3 bank rip
  remains reference/teacher evidence and its bytes never enter a working body.
  The operator authors all four poses. The BIN is therefore organised as work
  to reopen (EAR PICKS, SAVED PROGRAMS, LAB PROGRAMS) and data to use
  (P2K POSES, MEASURED RAILS), not as a preset-generation or reference-
  comparison wizard. The X3 ghost section is deliberately absent.
  They behave as a single-open accordion so the active shelf cannot bury the
  next authoring route. P2K remains donor-only on both single- and double-click.
  The BIN index filters live by name, family, role, provenance note, or source
  path (`Ctrl+F` focuses it; Escape clears it). Search results retain their
  section/role context, and `Documents/TRENCH/index.json` is emitted in the same
  task order with a `section` field on every entry.
  EDITING: numeric PROPERTIES (click value, type; roots → encoder → words =
  the minifloat snap, display re-derives from words) + PZ EDITOR WINDOW
  (opened from PROPERTIES; handles = roots of the RUNTIME-probed interpolated
  biquads at the current pose, editing writes the active corner's words;
  drag = light install, full certify on release) + UNDO (64-deep snapshot
  stack, ctrl+Z or button) + RESET-to-loaded. Harness "click" action drives
  the real hit tests. [PROOF 2026-07-24: clicked UNDO and RESET restored
  byte-identical saves.]
- AUDITION: drop a wav on the app → LoopFeeder (WorkstationApplication.cpp)
  loops it into the processor input (linear-interp resample, try-lock so a
  load never blocks the audio thread); PLAY/STOP in the header; last loop
  remembered in `Documents/TRENCH/player_loop.txt`; harness loop/play actions.
  HERO-HANDLE EDITING: each stage's runtime pole = a circle ON the cascade;
  drag horizontal = pole Hz, vertical = exponential bandwidth (r 0.5–0.998),
  writes the active corner through the encoder; works at any XY pose incl.
  M50/Q50. The modal PZ window's OPEN button was removed (operator verdict:
  blocks the view, too vague for a serial cascade); grid click selects a
  corner without moving the puck.
- POSITION LAW (operator): NOTHING moves the XY puck except the user's own
  grid drag / harness xy — pose drops and every edit keep the listening
  position. Full pair transparency on the hero: pole = ring, zero = x, both
  at the cascade curve; off-plot pairs named in the SENTINEL row with DC/NYQ
  edge ticks; identity stages listed as "off". CTRL+chip-drop = donor stage
  into the ACTIVE CORNER only (byte-proven single-corner scope); plain drop
  stays the all-corner hybrid swap. RESET = flat line (identity everywhere,
  undoable), not reload.
- PROBE TRANSPARENCY (glitch fix 2026-07-24): the editor probes with
  `trench_packed_probe` masks directly — an UNSTABLE stage still draws and is
  named in red in the sentinel row; only NONFINITE stages are zeroed out of
  the sum. The old bridge wrapper returned false on any mask, blanking the
  hero with a misleading "double-click to open" hint. Zeros are draggable on
  the hero like poles (× handles, r cap 1.0); degenerate/real-pair rows are
  editable by explicit recast from the identity roots (0,0,0,0,1).
  [PROOF 2026-07-24: edit changed exactly 1 word (corner 0 lane 1 pole-freq);
  undo and reset saves byte-identical to the pre-edit save.]
- RAILS ARE LOADABLE (2026-07-24): clicking a MEASURED RAILS entry opens the
  RAIL tray — entries stepped with </> (48 HRTF directions, 44 DVTD vowels,
  24 modal, 30 circuit), each entry's measured pole/zero pairs as chips
  (conjugate duplicates deduped, unity peak scale computed, encoder-snapped),
  dragged onto stage rows (CTRL = active corner only). Phononic is a
  trajectory file — not stage-loadable yet. Harness rail/raildrop actions.
  Tray language: donor/rail material is AMBER labeled by pole Hz; only the
  program's FILTER STAGES carry lane colours + S-numbers (the S1..S6 donor
  chip labels were a false mirror — operator confusion 2026-07-24).
- Program switch with unsaved edits auto-stashes the working bytes to
  `Documents/TRENCH/bodies/AUTOSAVE/<name>__autosave.body240` — work is never
  lost by clicking another body.
- OPERATOR DECISION 2026-07-24 (X3 donor surgery): decoded X3 fixed-class
  stages MAY be used as donor material inside new hybrid constructions —
  "I'm not shipping the presets verbatim, I'm doing donor surgery" — the same
  bar as the approved P2K complete-row study-candidate flow. Verbatim/near-
  verbatim whole-preset shipping stays out; clean-room reconstruction (the
  forge fit path, x3_workhorse_fit.py) remains the shipping route for the
  workhorse classes themselves.
- DEAD END CONFIRMED 2026-07-24 (rule 17): `ref/x3_menu/runtime_blocks/*.raw`
  for the FIXED classes are the WRITER SOURCE TABLES, not output biquad
  coefficients — decoding them as (2,3,4,0,1)/16384 biquads yields a2=0
  one-pole rows and +71 dB DC "corners" (6_pole_lowpass, measured). Any fit
  against those targets is a fit of garbage (x3_workhorse_fit's -70 dB null
  included). SUSPECT: X3 ghost curves generated through the same reader —
  verify before trusting the all-4-corner ghost bar for fixed classes.
  The true workhorse targets require either (a) porting the per-class
  writers per `dev/tmp/x3_generated_writers/README.md` + trench_re_vault
  (helper FUN_1802c59b0: slots 0/1 zero side, 2/3 pole side, 4 gain), or
  (b) the canonical wet-capture path (`ref/canonical/talking_hedz` model)
  through capture_compiler. Codex warning: X3 at 44.1k applies sqrt warping;
  39062.5 is the authoritative coefficient domain.
- REAL-PAIR ROW LAW (operator bug report "goes to the sky", 2026-07-24):
  heritage/XML bodies carry real-pair rows (broadband shelf/tilt character)
  that the conjugate pair editor CANNOT express. The silent recast-on-drag
  deleted their character (tens of dB broadband jumps from a tiny touch).
  Byte-proven: encoder roundtrip is IDENTICAL for every conjugate row (the
  handles are honest); recast is now EXPLICIT ONLY (typing in STAGE DETAIL),
  drags refuse degenerate rows with a named status message.
- STAGE = START + END (operator design law 2026-07-24): every stage row shows
  BOTH morph endpoints of the active Q side as minis; clicking one aims the
  editor at that endpoint (puck never moves), dropping a donor/rail chip ON an
  endpoint mini loads just that endpoint. Body = 6 stages x (start, end).
- WRITER PORT PROVEN 2026-07-24: `dev/tmp/port_lpx_writer.py` ports the
  CPhantomMorphLPX writer law (trench_re_vault CPhantomMorphLPX contract:
  freq = 442*byte+4896 @44.1k family, freq_half = (raw>>1)+0x6400, 16-entry
  zero-depth table, cross-cancelling 3-stage ladder, 0xDFFF sentinels) into a
  BODY GENERATOR: user freq bytes in -> certified .body240 out (M0 = table
  entry 0, M100 = entry 15; Q banks duplicated per the codex degenerate-Q
  proof). LPXPORT_demo: M0 = clean LP ladder (65/456/1499 Hz cross-cancelled),
  M100 = flat + screaming ~6 kHz sweep peak; certify PASS maxR 0.99999.
  Caveat: the X3 original recompiles per 1/16 morph step; our engine
  interpolates the two endpoint banks (smooth approximation of the stepped
  trajectory). The same port pattern applies to the remaining menu writers
  (fixed classes need their writer decompiles pulled from the vault Ghidra
  project first).
- TRAJECTORY DRAG (2026-07-25): with the puck mid-morph (0.05<m<0.95), a hero
  handle drag moves BOTH endpoints of the active Q side by the same frequency
  RATIO + bandwidth factor — design the stage's whole trajectory from the
  centre; at a corner the drag shapes that endpoint alone. P/Z LOCK button
  (header): FREE -> POLES only -> ZEROS only, persistent version of SHIFT/ALT.
- THE AUTHORING-SURFACE GAP (operator: "these are NOT what I authored",
  2026-07-25 — bytes verified identical, so the machine differed): the
  workstation auditioned in body-solo (no AGC/sat/slam/bite) while FL runs
  the full chain. FIXED: the workstation now defaults to CHAIN (the shipping
  path) with a SOLO toggle. Plus three chain laws per operator: (1) GAIN
  BUDGET — per-body makeup at body-switch = -(mean of 5-pose median dB),
  clamp +/-12, applied post-island both paths; (2) every body switch loads
  MIX = 100%; (3) MIX is now a TRUE latency-compensated linear wet/dry —
  the old PunchBlend psycho-blend (sqrt/square band laws + transient
  ducking) was program-dependent at every setting except 0/100 and is
  deleted. MIX wheel: 38x225 @ (866,694), label 13.5pt.
- SHIP STATE 2026-07-25 (installed): TYPE menu = SIGNATURE (Bruh, Low Pass
  Pressure, Fable, Speaker Knockerz, Bass Time — Tyson's ear picks, byte-
  verified, certify PASS) + Contrary Sweeps (the one real workhorse). The
  full ship-v1 list (39 bodies + roster) is ARCHIVED verbatim at
  `presets_ship_v1/`. The three requested MD classes are pending real
  sources: Peak/Shelf Morph writer = FUN_1802c6020/CPhantomMorph2 (tables
  extracted, formula needs one vault decompile pass), Contrary Bandpass =
  ROM-table class (decode open), "Tilt Shelf Morph" does not exist in the X3
  menu (nearest = Dual EQ Morph family). Both plugin dropdowns (TYPE +
  modulation) now share ONE LookAndFeel: SelectorLookAndFeel teal-glass
  (13.5pt, lamp tick + rail, submenu arrows); the TYPE menu's bakelite copy
  deleted, AuditionItem re-inked to the shared palette.
- ROSTER MASS DELETION (2026-07-25, operator: "preset list 100% unusable"):
  PresetRoster.inc cut 63 -> 40 name-true entries, verified by response match
  against the 69 heritage XML exports. DELETED: the entire "cleanroom"
  fixed-class block (misdecoded writer source tables + the micro-shift IP
  dodge), harmonic_lp_* (actually Buzzy/LowFreqHiRez), 4pbp (Super_Steep_Q),
  modernlopass (Peak_Shifter_2), phasey_one (EQ_Shifter), super1khipass,
  notchsweeper, ac_* mixups/dupes. VST3 builds clean; NOT INSTALLED (gate).
- THE MEASURED Q LAW (2026-07-25, decisive — measured across ALL 51 P2K
  banks, split by stage geometry): pole bandwidth x ~0.375 under Q for BOTH
  stage types (EQ-type median 0.379, LP/HP-type 0.374; typed_vowl measured
  0.356 independently — two agreeing measurements). Gain is NOT the Q lever
  (median ~-0.3 dB both types); the E-mu Adv Apps Guide's "EQ sections get
  gain, LP/HP get Q" describes its WHEEL ROUTING, not bank content — THE
  MANUAL LIES about the banks. Centre moves are per-preset design (median ~0,
  huge spread), not law. ~25% of stages LOOSEN under Q (dominance direction).
  CORRECTED 2026-07-25 (Tyson's challenge, then measured on all 102 E-mu
  bodies): "Q banks are DERIVED" is FALSE. Predicting Q100 from Q0 via MD-Q
  (bw x0.375, centers/zeros held) misses the real Q100 cascades by median
  max|err| 32 dB (shape-only, offset removed); 200/204 Q pairs off >6 dB.
  Real Q poses move centers (median 0.19 oct, 75th pct 0.37) and 108/880
  stages LOOSEN. E-mu's Q corners are a SECOND AUTHORED POSE per axis, same
  as morph — the forge's 2 morph frames + 2 Q frames are all real data.
  MD-Q (header button / harness mdq: bw x0.375, zeros hold, dominance
  direction, identity+real-pair rows flat, r ceiling 0.998, stability-gate
  reverted on fail) remains a usable DEFAULT verb when no measured/authored
  Q pose exists — it is not ROM practice, and deriving Q is a candidate root
  cause of the generic dead-Q feel.
  [PROOF: STITCH_hedz_zoom_ear_mdq blooms at Q100, PASS — proves the verb
  runs, not that derivation matches E-mu.]
- MEASURED FACT 2026-07-25 (dominance test, 102 E-mu bodies —
  `dev/tmp/dominance_test/`, full write-up HYPOTHESIS_BRIEF.md §3): crown
  travel (median 5.39 oct) is carried by STAGE DOMINANCE HANDOFF in 67%
  overall and 85% of the 33 P2K ship presets — a different stage wins the
  crown at the low- vs high-crown corner (median 2 distinct dominants across
  the 4 corners). The non-handoff third are the classic full-range sweeps
  (Super_Lo_Pass etc.) whose pole stacks genuinely slide 3.3+ oct and go
  REAL/open at a corner. Authoring travel = choose which stage wins at each
  corner (characters) or slide the whole stack (sweeps).
- MEASURED FACT 2026-07-24: all 51 P2K skins use ALL SIX stages at every
  corner (zero identity rows; 46/51 have no effectively-flat stage at M0Q0,
  5/51 exactly one <0.75 dB span). The "2-3 active sections" guidance was an
  authoring heuristic, not ROM practice.
  All response plots share the OVERALL CASCADE scale (−60..+30 dB).
  Per-plot autoranging is forbidden: it made identical packed responses look
  different between donor chips, the 2×2 grid, lanes, and the hero.
  Curves are dense raw packed-runtime evaluations (1024 log-frequency points,
  20 Hz to just below the 39.0625 kHz runtime Nyquist), drawn as thin unsmoothed
  polylines so narrow poles and zeros are not softened by the display.
  No MORPH/Q/DRIVE knobs, no SOLO, no GUIDE. The authoring flow starts with a
  2×2 corner grid: click a corner to select its authored pose for editing, or
  drag continuously in XY to audition the packed runtime without silently
  changing the selected edit corner. One OVERALL CASCADE hero is the response
  truth; the lane curves stay in the lane editor. A bank donor exposes its 4
  authored pose chips and 6 lane chips: click a pose into the selected corner
  or drag it to any corner; drop a lane on a LANE row = verbatim INSERT.
  There is deliberately no generic DERIVE Q action: Q100 remains an authored
  pose sourced from real bank data per [L1]. [PROOF 2026-07-24: starting from
  a bank pose, pose-copy emitted the exact expected 240 bytes; immediate UNDO
  restored the source body byte-identically.] LANES rows have per-lane minis +
  drag-to-rearrange
  (whole-lane permutation across all 4 corners), PROPERTIES. All custom paint; every
  mini is single curve + 0 dB line + thin border, probed from the packed runtime.
  Load → edit → SAVE lands in `Documents/TRENCH/bodies` (live plugin rescan).
  [PROOF: scripted harness below; drop+move byte-verified vs parents 2026-07-24.]
- SWAP STAGE = verbatim 5-word × 4-corner lane copy (no decode/refit); lane OFF =
  the identity row (0xdfff ffff dfff ffff dfff → biquad (2,1,2,1,1) passthrough).
  [PROOF: byte diff of a saved swap+mute body vs its two parents, 2026-07-24.]
- X3 ghost overlay: decoded fixed-class corner curves dumped by
  `df2/tools/x3_reference_dump.py` to `Documents/TRENCH/reference/x3/*.json`
  (curves only — no X3 words leave df2). The roster is NOT a fit target:
  operator verdict 2026-07-24 "99% of the presets in the selector are
  fundamentally wrong"; a bake passes only when ALL FOUR corners match
  (the cleanroom fitter's 6-pole LP failed M0_Q100 by +14 dB bounce-back).
- Headless proof harness: set `TRENCH_WS_SCRIPT` to a JSON action list
  (program/source/insert/drop/move/posefrom/xy/prop/pz/undo/reset/off/ghost/pose/save/shot/quit) — exercises the real
  code paths and snapshots the editor; no mouse automation.
- Stage roots↔words over FFI: `trench_stage_roots_from_words` /
  `trench_stage_words_from_roots` in trench-core/src/ffi.rs.
  [PROOF: `cargo test --lib stage_roots_words_ffi`.] Python callers must load
  `df2-workstation/target/release/trench_core.dll` — the dll pyruntime finds in
  df2 is stale (missing the stage encoder).
- First measured cross-source hybrid via the frame-middle path
  (`dev/tmp/build_hedz_hrtf.py`, 2026-07-24): Talking Hedz S1+S6 verbatim
  (all 4 corners) + S2–S5 from SONICOM HRTF rails, morph = az000→az090
  trajectory, per-stage scale computed for 0 dB peaks, Q edge left to the
  in-app Q LAW. Certified maxR 0.99915 PASS; saved as
  `HRTF_hedz_front_to_side`. Frame words byte-verified verbatim, 80/80 middle
  words replaced. AWAITING EAR.

## 4. Metrics — the only allowed meanings of "dB"

A number without its metric name and grid is not evidence.

- **crown dB** — max |H(f)| of one corner over the QC grid (30 Hz–19.2 kHz,
  512 pts, packed-runtime probe).
- **floor dB** — median |H(f)| over the same grid.
- **contrast dB** — crown − floor of one corner.
- **surface distance dB ("copy-risk")** — RMS of the Morph×Q response surface
  vs the NEAREST reference body; ship threshold ≥ 6 dB clear.
  (`filters/docs/PRIOR_ART_LEDGER.md`.)
- **bloom dB** — max pointwise |H| rise Q0→Q100 over a pose sweep. The corpus
  band 13.9–254 dB (median 71, n=33) is DESCRIPTIVE — not a pass gate.
- **fit residual dB** — RMS error of fit vs target in a stated band. DVTD gate:
  floored 100–5000 Hz band ≤ 6 dB (`filters/rails/dvtd_rails.py`).

## 5. Evidence base (paths verified 2026-07-21)

| what | where | nature |
|---|---|---|
| Klatt 1980 formant + bandwidth tables | `filters/tables/klatt_1980_formants.json`, `klatt_1980_bandwidths.json` | published [LIT] (Klatt, D.H. 1980, "Software for a cascade/parallel formant synthesizer," JASA 67(3)) |
| Peterson-Barney vowel formants | `filters/tables/vowel_formants.json` | published [LIT] (Peterson & Barney 1952, JASA 24(2)) |
| Tube + metal mode tables | `filters/tables/tube_resonances.json`, `metallic_modes.json` | published physics (§2.7) |
| Dresden Vocal Tract Dataset — 44 measured VVTFs, magnitude+phase | fitted by `filters/rails/dvtd_rails.py` | measured [LIT] (Birkholz et al., figshare s/5b81026892f7b39b429e) |
| SONICOM HRTF (P0001, 48 directions) | `filters/rails/hrtf_rails.py` | measured [LIT] |
| Rossum patent US 5,170,369 ("Dynamic Digital IIR Audio Filter," E-mu, 1992) + E-mu manuals | `dev/notebooklm/fuel/` | primary historical sources — STUDY ONLY |
| Stage-logic census (n=200 variants) | `dev/notebooklm/fuel/01_stage_logic.md` | [MEASURED] |
| P2K ROM corpus | `df2/bodies/rom/` (df2 worktree) | Complete reference bodies remain study-only. Operator rule 2026-07-22: literal complete-row hybrids may remain as approved plugin study candidates with exact ownership evidence; clean-room shipping reconstruction is a separate later step. |

### 5.1 Frame-middle pairing rule (operator correction 2026-07-22)

- The complete packed six-stage product is the candidate. A frame is not required to be neutral or universally portable.
- The S1/S6 quotient is a diagnostic for unsafe gain and pathological shaping only; it does not define candidate validity.
- Preserve bounded, operator-approved pairings. Do not demote the twelve approved old-school hybrids because another pairing exposes an unsafe quotient.
- Generate and audition one deliberate frame-middle pairing at a time. Tyson performs the musical selection.
- Clean-room shipping reconstruction is a separate later step from study selection.

## 6. The ear protocol

- Gate order (cheap→expensive): pack+stability [PROOF] → surface distance →
  response plots → ear.
- The ear is the only pass/fail for character. Venue: live plugin
  hover-audition, or `tools/render_tournament.py` keep/kill page on broadband
  material (a bare 808 masks everything above the first resonance).
- Record every verdict with date + listener + material, or it is folklore.
- Known gap: no formal level-match/blind protocol yet; BS.1116 (§2.8) is the
  standard to approximate.

## 7. Dead ends (verified dead — do not resurrect)

- Derived-Q tooling as law (QLINK, pressurize) — helpers for one verb only [L1].
- Endpoint-only fit scoring [L2].
- "Floor-down/crown-keep" reshape via SCALE — contradicts §2.4.
- `compile_body` for authoring (GAIN_MAX clamp wrong) [PROOF: stage_law test].
- ROM-fundamental / frame+voice stage authoring — produced ZERO passing presets
  (verdict 2026-07-21). `.prompts/002-measured-cross-presets.md` = DO-NOT-RUN;
  its output is the rejected measured-cross set.
- Decoding the fixed-class ROM tables — circular vs the codex; block schema
  unknown. (Session verdict; study-side only, does not affect shipping.)

---

# PART 2 — SESSION LOG (archaeology — UNVERIFIED until promoted)

Everything below is dated session work, kept so the next context knows what was
tried. Treat every claim as a lead, not a fact: re-prove and promote into
PART 1 before relying on it.

---

## The good bodies (evidence-graded inventory)

| set | where | why they're good | caveat |
|---|---|---|---|
| P2K ROM corpus (33) | `df2/bodies/rom/P2k_000..032.json` | ground truth — the measured originals; every "is this good?" question is answered against these | never ship a complete reference body; literal-row hybrids are study candidates and clean-room shipping reconstruction is separate per Part 1 §5.1 |
| ship_* five (2026-07-14/15) | `df2/presets/ship_*.body240` + `juce-shell/assets/{bodies,cartridges}/` | 4 corners per body from 4 DIFFERENT measured sources (whistler / iceberg / pulsar / HRTF; vowel LPC; razor combs) | ship_hybrid_cross corners plot as broadband gain slabs (+60..+110 dB shelves) — ear-check before trusting |
| cleanroom P2K replacements | `df2/presets/cleanroom_{megasweepz,lucifers_q}.body240`, provenance in `df2/dev/tmp/cleanroom_p2k_replacements/provenance.md` | full lane provenance, physical gate passed, verified NOT a copy of the reference | **FAILED the replacement null test 2026-07-17**: 35.4 / 44.3 dB from their targets (unrelated ROM pairs median 23.4) — they don't behave like the presets they replace; dropped from the ear page |
| old-school hybrid signature bodies (12) | `plugin/presets/bodies/{speaker_knockerz,...,mine_field}.body240`; provenance in `plugin/presets/oldschool_hybrids.provenance.md` | operator-promoted 2026-07-22; complete ROM S1/S6 rows around complete independently measured HRTF or violin/mine S2-S5 rows | exact packed rows; no decode/refit/normalization; sampled certification and audition evidence remain in `dev/tmp/iconic_presets_20260722/rom_frames_rich_sources_01/` |
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

## Gain budget + corner authoring laws (proven 2026-07-21 filter session)

- **SCALE (=b0) is pure broadband level.** It scales a section's whole numerator,
  so it shifts a corner up/down uniformly and **cannot** change crown-vs-floor
  contrast. Use it ONLY to bound absolute crown (the +27 trim).
- **Q100 is a second authored pose, NEVER derived.** A "dead Q knob" means the
  Q100 poses were authored flat — fix = re-author just the two Q100 corners hot,
  leave the Q0 poses.
- **+27 dB corner-crown bound:** a hot body is bounded with a body-wide SCALE
  multiplier (pure vertical shift, morph relationships intact).
- **Contrast/character lives in poles+zeros.** Ear-SAFE lever = deepen **zeros**
  (carve valleys, poles untouched — restores crown-vs-floor without touching
  tuning). Ear-RISKY = Q-bloom pole surgery (the +0.010 uniform-radius boost was
  ear-killed).
- **Roster audit (141 bodies):** all stable/legal (max r 0.99955, 0 unstable/
  nonfinite), but **gain budget wildly unbounded: 0→107 dB, median 43.** Bound
  with TWO numbers per corner — absolute crown (clip ceiling ≤+27) and contrast
  (character) — not one.
- **Curation before bounding** (verdict 2026-07-21): bounding won't fix janky,
  it just stops clipping. Lock the ship set first, bound only that set.

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

## The four TRENCH namesakes (2026-07-18)

- Archetype ⊗ NEW MEASURED RAILS off the four founding families:
  `tube_shout` ← P2k_007 Fuzzi Face (closed-open tube L 0.60→0.15 m),
  `bell_rake` ← P2k_029 Lucifer's Q (tuned-bell partials f0 400→1200),
  `skin_hit` ← P2k_004 Meaty Gizmo (drumhead modes f0 120→400),
  `acid_vox` ← P2k_015 DJ Alkaline (Klatt 'oo'→'ae' + F4/F5).
  Movers re-railed rank-matched (pole centers only); zeros/radii/scales/frames
  verbatim; Q corners inherit each archetype's own per-lane Q transform.
  Builder: `dev/tmp/bytes_fix/build_namesakes.py` → `dev/tmp/namesakes/`.
  Gates ALL CLEAR: surface copy-risk 29.2–43.8 dB, per-corner worst 8.1 dB,
  floors ~0, bloom 18.5–199.3 dB (in band), mutual distance 26.4–37.3 dB.
  On the tournament page for keep/kill; not in the roster until the ear says.

## Morph strengthening verdicts (2026-07-18)

- **Anatomy-FM (audio-rate morph) FAILED the ear** — "FM sounds wrong"
  (scout render `dev/tmp/hd_ab/reese_ps_fm_48k.wav` vs lerp32). RATE:AUDIO is
  OUT of the build queue. A revival needs a different METHOD (single-axis or
  single-lane FM), not re-tuned parameters. 32-grid + per-sample ramp stands
  (−32.6 dB vs per-sample targets, measured).
- Morph roadmap that stands: Z_CUBE (body-to-body morph) is the next
  strengthener; the per-sample coefficient ramp is LAW — new features modulate
  targets, never coefficients.

## TF = the internal representative for measured objects (2026-07-18)

- `tools/tf_ingest.py`: IR wav OR modal table → |H(f)| dB on the QC grid
  (30 Hz–19.2 kHz, 512 pts, floor=median 0 dB) → `fit_corner_from_magnitude`.
  Any measured source (guitar body, cymbal modes, room IR, area function)
  becomes the SAME object before fitting. End-to-end proven (bell modes →
  6 finite fitted rows). Datasets landing in `wav-source-library/measured_objects/`
  + `audition_stems/` with PROVENANCE.md (license per file; NC audio = modal
  data only, never ship the audio).

## Registered-lane IR (2026-07-19) — the authoring layer above geometry

- `.geometry.json` is COMPILED OUTPUT; the authoring model is
  `*.registered_lanes.json` (`filters/registered-lanes.schema.json`,
  `tools/register_lanes.py`, doc `filters/docs/REGISTERED_LANES.md`).
  Six stable lane IDs × four explicit corners, stage plan with law
  (`local_peak_notch`/`high_zero_cliff`/`low_zero_sub_cut`/`free`),
  topology, provenance per assignment, continuity limits. Validator
  rejects derived Q100, inexact identity, topology swaps, missing
  provenance, study-reference evidence. `emit` → canonical geometry;
  `pack` delegates to `tools/filter_cli pack` (no second compiler).
  Tests: `python -m tools.test_register_lanes` (24 checks).

## Candidate extraction (2026-07-19) — the feed into registered lanes

- Four TF JSONs (tf_ingest shape) → one deterministic `*.candidates.json`
  (`filters/candidate-set.schema.json`, `tools/extract_candidates.py`).
  Numerical owner = new `trench-core` bin `fit-candidates`
  (`arma::fit_corner_from_magnitude` → `minifloat::encode` words →
  `stage_law::geometry_from_words` exact classification; residual via
  `response::biquad_cascade_complex` over the QUANTIZED words). No slots,
  no lane ids, no cross-corner matching, no derived anything — candidates
  are unordered per-corner features for MANUAL registration in
  `register_lanes`. Real proof set: `dev/tmp/candidate_extraction/`
  (violin dampened/resonant + ukulele + piano; byte-identical re-runs).
  Tests: `python -m tools.test_extract_candidates` (16 checks).
  CAVEAT: residuals on raw un-detilted IR curves are honest and LARGE
  (piano 86.9 dB rms) — detilt/floor the TF before fitting dense sources.

## Measured-object verdicts (2026-07-18 night)

- **violin_cave APPROVED — "Yes thats the sound."** The TF lane (tf_ingest
  detilt + floor renorm → fit → pack) is the measured-object front door.
- **bodyN scout FAILED the ear**: 6 vs 12 stages (residual fit, series render)
  = "No difference". Measured: 3.75→2.45 dB RMS at 1/12-oct — inaudible on
  drums. body240's 6 stages carry a measured object. bodyN waits until a
  source audibly needs >6 resonances/corner (plateau at ~2 dB was the greedy
  solver's floor, not proof of a format limit). Scout renders:
  `dev/tmp/measured_objects/violin_{6,12}stage_drums.wav`.

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
- "Floor-down/crown-keep" reshape via SCALE — SCALE is pure level, cannot move
  contrast (measured dead, 2026-07-21).
- +0.010 uniform-radius Q-bloom pole surgery — ear-killed (2026-07-21).
- ROM-fundamental-biquad-logic → measured-data foundation/stage authoring —
  produced ZERO passing presets (Tyson verdict 2026-07-21: "was for nothing").
  Includes `.prompts/002-measured-cross-presets.md` output (the rejected
  measured-crosses). What passes = measured Dvtd S2-quad + shipv2 authoring.

## Measurement/fit harnesses (uncommitted, tested 2026-07-17)

`trench-core/src/bin/tf_oracle.rs` — capture → complex TF estimate → fit
against TRUE packed runtime → train/held-out metrics → null-test bundle.
`tf_harness.rs`, `tf_harness_routed.rs`, `tests/stage_correspondence.rs`.
Method statement: `PRESET_HANDOFF.md`.
