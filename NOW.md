# NOW

> **Incoming AI / GPT-5.5: start at `HANDOFF.md`** — it's the active prompt (primary task =
> the full painted-code Blender-style UI rewrite). In this file read ONLY the top block;
> everything below the first `---` is dated archive — verify against code before acting.

The one current-state file. Read this, trust this. (STATE.md = older worklog, archive.)

---

## THE ARCHITECTURE (locked — do not drift)

**The 8-corner cube IS the hidden authored body.**
- **X = Morph** · **Y = Q / stress / openness** · **Z = Transform / reality → nightmare**

**The player has only TWO horizontal sliders:**
- **Slider 1 = X (Morph)** · **Slider 2 = the authored path through Y + Z**

**What's the actual asset:** the **runtime** — `trench-core` (frozen, X3-null DSP:
cascade, AGC, packed math, interp) + the JUCE player that loads 240-byte bodies.
That is the product and it's committed. **Everything else is disposable tooling**
that just funnels poles → 240-byte bodies. Make a generator, throw it away, remake
it — no pedestal. Nothing in `tools/` or `dev/tmp/` is load-bearing; the runtime
imports none of it.

**Home for authoring = the Forge** (`forge/src/`, egui). Corners placed
INTENTIONALLY (the 5 architectures / source recipes), never randomly; every pole
zero-paired; the morph middle is the product. The 5 generators live in
`forge/src/generators.rs` (DF2T pole/zero math, 8 corners, tests pass): FORMANT ·
OVERDRIVE · COMB/FLANGE · KINEMATIC EQ · PHASE SHEAR. Next build: the Forge UI on
top of them (GEN menu + Z control + click-a-corner-to-tweak).

**Engine truth** (`trench-core/src/cascade.rs`): a corner = 6 biquads
(`CornerData=[[f64;5];6]`, kernel c0..c4); 12 cascade slots (6 active, 6 spare).
Frozen — author into it, never change it.

**Clean-room:** `dev/tmp/rom_poles_zeros.csv`, `bodies/rom/`, and
`~/trench_re_vault/artifacts/morpheus_cubes_baked/` are STUDY ONLY — never shipped.

## 2026-05-31 NIGHT — FORGE WORKFLOW REBUILT + HERITAGE RECOVERED (NEXT CHAT START HERE)

**State (OBSERVED): the Forge is the painter-only Blender-style bench, builds green, 32
tests pass.** Workspaces collapsed to **SHAPE → PLAYER → PUSH** (TRAJECTORY folded into
PLAYER as a route picker). Files: `forge/src/{app,paint,style,shape,player,push,
corner_library,source,generators}.rs`; thin `main.rs`. Done this session:
- **Cube is publishable (wire-A).** A composed GEN field ships as its Z-crossfade slice —
  byte-for-byte what PLAYER auditions. `forge_core::{body,packed_authority,
  publishability_error}` are cube-aware (read-only). PUSH is no longer a dead-end. Test:
  `gen_cube_publishes_byte_authoritative_slice`.
- **Heritage library 68 → 112 corners** (heritage 18→45, authored 4→16, design 1→6). Root
  cause: `tools/reindex_corner_library.py` defined `IDENTITY_WORDS` — the E-mu
  "section-off" pad `(2,1,2,1,1)`, which encodes to an unstable r=2.0 biquad — but never
  filtered it; `stages[:6]` grabbed pad stages interspersed with real ones and sank ~120
  templates. Fix = drop pad stages, keep the real filter, bypass-fill. **Heritage = the
  source templates.** Still rejected: ~95 genuinely-unstable edge poles + single-peak.
- **SHAPE = 8 per-corner gradient response plots** (2×4: Z0 floor / Z1 ceiling) + a bottom
  **AUDITION MIDDLE dock** (Morph + Q sliders + live-middle scope + continuous ring-out
  readout) — sweep/hear the middle WHILE composing. **Plots = validation, ear = judge.**
- The 3 EXTREME generators (TalkingHedz / Lucifer's Q / EarBender) already exist in
  `generators.rs` and match the spec (6 biquads, radius capped at the morph-stable brink;
  SLAM is the runtime violence, not unstable poles).

**DO NEXT (agreed order):**
1. **Real character in the LIVE audition.** Route the Forge audio through the SHIPPED
   engine (SLAM pre-sat + AGC `&0xF`), expose a DRIVE knob, persist per-body. **Do NOT
   reimplement SLAM/AGC in `audio.rs` (4th copy = `packed-math-triplicated`) — call
   trench-core via FFI.** Today `audio.rs` ends in a tanh stand-in, not the chip drive
   (the "judging it asleep" gap). Wrinkle: feed the engine ramped coeffs per block (no
   clicks on drag).
2. **QSound** as a per-body SPATIAL setting (can't bake into mono coeffs — store as body
   metadata, audition live). 2nd sanctioned optional effect (with SLAM); was out-of-scope,
   Tyson pulled it in.
3. Then **section-by-section polish** (SHAPE → PLAYER → PUSH), each ear-verified through the
   real engine before moving on.

**QUARANTINED (NOT in the checkpoint commit — confirm provenance):** `CLAUDE.md`
(pre-session edit), `### Permanent Master Acoustic Dictionary.txt` + `ref/p2k_variants/
combined/` (clean-room study, never ship), `HANDOFF.md`, `.claude/tdd-guard/`.

---

## 2026-05-31 LATE — SESSION WRAP (earlier today — superseded by the block above)

**① BLOCKER — DO THIS FIRST: the Forge CRASHED.** Not yet root-caused. OBSERVED this
session: `cargo build` clean (exit 0), `cargo test` 27/27 pass, headless launch idles
20s with NO startup panic → the crash is **interaction-triggered**, almost certainly in
the un-eye-verified FSM/GEN/cube paths (the +1020 dirty lines in `main.rs`). DO NOT guess
a fix. Get from Tyson: (a) the exact action right before the crash, (b) the panic text —
`cd forge; $env:RUST_BACKTRACE=1; cargo run`, reproduce, paste the `file:line` + reason.
Fix the root cause from there (used systematic-debugging skill; Iron Law = no fix without
the panic).

**② ARCHITECTURE LOCKED BY TYSON (2026-05-31) — memories updated:**
- **df2 is the ONLY thing we ship.** The Forge is the INTERNAL authoring bench, not a
  shipped product. (memory `df2-two-plugins`, rewritten — retires the old "two JUCE
  plugins + pyruntime" framing.)
- **One Rust surface** (the egui Forge app); the df2 plugin + Forge share the `trench-core`
  engine via **FFI**. (memory `one-rust-surface-shared-ffi-engine`.) DO NOT infer
  `juce-shell/` is retired — Tyson did not say that; don't touch it or the chassis.

**③ DOWNLOADS E-MU DECODE = REJECTED (vetted this session).** `~/Downloads/
decoded_emu_library.json` (+ `decode_emu_library.py`) is POLE-ONLY: it mis-modeled the
240-byte body (8×7×2 instead of the real 4 corners × 6 stages × 5 coeffs) and DROPPED the
numerator/zeros — every corner renders as one sliding resonant lowpass (all 13,872 PEQ
gains ≤ 0.08 dB, verified `dev/tmp/emu_vet/vet_library.py`). The zeros ARE present in the
real source (b0,b1,b2 = 3 of 5 packed words; `tools/extract_p2k_pz.py` + `bodies/rom/*.json`
prove it). Use the **zero-bearing decode** (`bodies/rom/` + `ref/p2k_variants/`), never the
Downloads file. (memory `deep-model-abstracts-corpus`.)

**④ ACTIVE TASK (GSD todo, commit `b5e33c0`): RE-INDEX the corner library.** Strip every
corner out of the scattered `dev/tmp/arma_source_pack/corners_audio_only` categories
(`_rom`/`_design`/`_physics`/`_heritage`[69]/`_authored`/`_reference`/`_voice`) + loose
`dev/tmp/*.body240` → **AUDIT each on ingest** (the vet gate: finite/alive/stable poles<1/
≥2 peaks/sane, through the REAL engine) → organise survivors into ONE clean canonical
index (compiled-v1 `.corner.json`: format/name/sampleRate 39062.5/stages 6/keyframes
[label,boost,stages[c0..c4]]) → **fix the Forge navigation** (collapse `available_sources`/
`available_presets`/`scan_bins`/`collect_corners` + the duplicated `source_pos` heuristic
at `main.rs` ~629 & ~678 into one `CornerLibrary` index). "Audit them in as they go."
dev/tmp + forge, ONE smooth change. Authentic corners supersede the synthetic
`Architecture` generators (roadmap #3). See `.planning/todos/pending/2026-05-30-re-index-
and-audit-the-forge-corner-library.md`.

**⑤ DEEP-AUDIO-MODEL TRACK (parked, the genre-defining direction).** Corners are
GENERATED by the model abstracting the corpus into a CLAP perceptual atlas (render real
corpus → embed → target a region → differentiable engine gradient-authors an ORIGINAL
corner → similarity-reject → ear). Built: `dev/tmp/diffengine/` (engine_v2/diff_trench/
corner_bank). Blocked: CLAP on numpy-ABI (transformers `ClapModel` is the path). Feed it
the CORRECT decode (③). The clean re-indexed library (④) is the corpus this later embeds.

**DIRTY TREE (pre-session — NOT touched this session, confirm provenance before commit):**
`forge/src/{dsp,forge_core,main}.rs` modified, `forge/src/generators.rs` untracked,
`trench-core/src/minifloat.rs` modified = the FSM/GEN/cube work. This session only added
`dev/tmp/emu_vet/`, `.planning/todos/`, and memories.

**NEXT-CHAT ORDER:** (1) root-cause + fix the crash. (2) execute the re-index/audit/
organise/fix-nav todo (④). (3) deep-model atlas stays parked until ①–④ land.

---

## 2026-05-31 (earlier) — converged Forge spec + roadmap (reference)

**Read these memories first:** `forge-converged-spec`, `role-division-corners-vs-cubes`,
`engine-unfrozen`, `naming-df2-not-trench`, `forge-source-recipe-spec`. They hold the
hard-won design from a long iterative session.

**Where the Forge is:** builds green, 27 tests pass. It has 4 sections
(SOURCE/SHAPE/TRAJECTORY/PLAYER), a strong engine-verified corner BANK (physical
modal + Klatt vowels + synthetic + 3 EXTREME generators TalkingHedz/Lucifer's Q/
EarBender), corners rendered CLEAN through the real engine+AGC (no slam; slam =
runtime/audition only), SHAPE = grid + click-a-corner → spectrum picker overlay (no
response curve), a 2-slider PLAYER cube. BUT the UI is **patchwork** from ~20 in-session
iterations.

**NEXT SESSION (the plan Tyson locked):**
1. **Full custom-painted UI REWRITE** — no generic egui widgets; painter-only custom
   controls. SPLIT out of main.rs: `paint.rs` (painted button/slider/tab/knob +
   hit-test), `style.rs`, `shape.rs`/`trajectory.rs`/`player.rs`, `app.rs`, thin
   `main.rs`. Build it CLEAN to `forge-converged-spec`, incrementally.
2. **Aesthetic split:** dev sections = ENGINEERING SCHEMATIC (precise, real units,
   not abstracted) but pick-up-and-play; PLAYER = the one polished view (hi-fi cube +
   auto-morph + Morph/Path/SLAM, nothing else). Section one = JUST the grid, no
   response curve; click a corner → spectrum picker (low→high × open→closed).
3. **AUTHENTIC corners replace synthetic generators.** Tyson hands a **clean-room
   decoded E-mu corner library**. Load THOSE authentic corners into the Forge as the
   bank; selection picks from loaded corners. New **canonical folder** for them; the
   render script auto-renders previews there. (Clean-room: study/compose on the bench;
   ship originals.)
4. **14-pole / 7-biquad engine (v2)** — Tyson: "14 was the winner." INTEGRATED (one
   `NUM_STAGES` 6→7 in `trench-core/src/cascade.rs`, propagate; no separate v1/v2
   layer), body 240→280 bytes, re-run the null. Pairs with the E-mu library. Lets
   TalkingHedz fit its full 7-section spec (LP+F1-4+nasal-notch+HF-shelf).

**UNIFY: Forge + differentiable engine + CLAP = ONE instrument (Tyson, 2026-05-31).**
Not a parked side-track — wired into the Forge:
- **CLAP = the Forge's EAR.** The spectrum-picker axes / where a sound "sits" come from
  CLAP embedding positions (not the brightness/openness heuristic); corners AUTO-LABEL
  by what they actually sound like (zero-shot), live.
- **Gradient = the Forge's HAND.** "Sound like THIS" (reference or text) → CLAP target →
  the differentiable engine gradient-descends a body to it → real engine renders → ear
  keeps/trashes. Author by intent, in the bench.
- **Tyson's ear trains it.** KEEP/TRASH distills CLAP into a TINY model that runs LIVE in
  the Rust Forge (labels/ranking); heavy CLAP does offline authoring + distillation.
- **CLAP ON THE DECODED E-MU LIBRARY = the spine.** Render the whole authentic
  decoded library through the real engine → CLAP-embed every render → a PERCEPTUAL
  ATLAS of the real E-mu sound-space. The loop: **embed the real → target a region of
  the atlas → gradient authors an ORIGINAL body that lands there → CLAP similarity-
  reject confirms in-spirit-but-distinct → ear keeps.** Clean-room SOLVED: embeddings
  are STUDY (analysis, never shipped); shipped bodies are originals in the same
  perceptual neighborhood. The atlas also IS the picker (real sounds, real positions)
  + auto-labels + "find one like X".
- **THE FORGE IS THE SURFACE.** All of it — the atlas/picker, author-by-intent,
  similarity-reject, labels — is driven from the Forge UI. The Python brain (CLAP +
  differentiable engine) runs BEHIND it; the Forge is the face.
- **Shape:** Python brain (CLAP + differentiable engine) ⟷ Rust Forge surface, unified
  through the canonical corner library + a query channel (label / rank / author-by-intent).
- **Built + working:** `dev/tmp/diffengine/` — engine_v2.py (gradients flow), diff_trench.py
  (proxy↔REAL 0.17–0.66 dB — gradient steers the real engine), corner_bank.py (renders
  through the real engine). CLAP blocked only on sklearn/pandas numpy-ABI; transformers
  `ClapModel` is the path (differentiable, native torch).

## ROADMAP (next builds, in order)

1. ✅ **Forge UI on the generators (DONE 2026-05-30).** GEN menu (5 archs) + Z·XFORM
   slider so the puck navigates the full cube; orbiting cube inset (ported from the
   cube_display prototype: 8 named+colored corners, trilinear weight blend lines,
   blend readout; Tab = hero view); live preview through the SHIPPED packed path
   (`PackedCorners::z_crossfade` of the two planes → `interpolate`). **DRAW was
   REPLACED by FSM** per Tyson: draw a target magnitude curve → `fsm_fit`
   (`arma::fit_corner_from_magnitude`) → the fitted pole/zero CONSTELLATION overlays
   the spectrum; SEED menu (Klatt vowels/tube/golden-flanger/harmonic-slice) pre-fills
   the curve for real corners, freehand = wild. TWEAK→slot bakes the nearest cube
   corner into FSM. New: `trench-core/src/minifloat.rs::z_crossfade` (additive,
   reuses `lerp_u16`); `dsp.rs::{fsm_fit, corner_poles_zeros, peq/klatt/tube/flanger/
   harmonic curve generators}`; `forge_core.rs::{CubeState, cube/FSM methods}`.
   All 69 forge + core tests pass; binary launches clean. See memory `fsm-replaces-draw`.
   **NOT YET ear/eye-verified by Tyson in the running Forge** — next session: open it,
   pick a GEN arch, drive Morph/Q/Z + orbit, draw a wild FSM curve + SEED a vowel,
   confirm it reads well on camera. (Pre-existing clippy eq_op errors in
   `trench-core/src/qsound_spatial.rs` are unrelated/untouched.)
2. **Cube-search skill** — drives the Forge generators: sweep each architecture's
   X/Y/Z field → render survivors through the REAL engine (noise + saw only) →
   CULL garbage (never pick) → diversity-cluster → audition for the ear. Reuses the
   proven `dev/tmp/sweep.py` loop's spirit but the generators are the source, not
   ad-hoc Python. NOT the deleted `df2-cube-search` (that reinvented sweep.py).
3. **CLAP taste model** — real audio preference model (NOT an LLM, NOT
   prompt-to-preset): generate cubes → render through real engine → frozen
   CLAP/LAION-CLAP embeddings + df2 Bark/log features → one training row each →
   small neural head → keep_prob / mutate_prob / tags / uncertainty → ranks future
   audition batches. Freeze CLAP first. GPU: optional — frozen-CLAP forward + a tiny
   head run fine on CPU for hundreds of candidates; GPU only pays off at 10k+ batch
   scale. The ear is still the final judge; the model only pre-sorts.

---

## ARCHIVE BELOW — older notes, superseded by the block above

## 2026-05-30 LATE — V2 3D CUBE + TWO-ROLLER UX + FIDELITY NOTES (next AI: START HERE)

**Read `CLAUDE.md` first, then this, then memory `df2-v2-3d-cube-direction`.** df2 is an
**insert FX** (processes 808/reese/vocal) — NOT a synth: no keyboard, no note-on, no
velocity. Front panel = **two horizontal rollers + a SLAM drive knob**.

This session designed **df2 v2 = the 8-corner 3D morph CUBE + its UX**, prototyped in
HTML (no repo code changed — all scratch in `dev/tmp/cube_byear/`, gitignored).

**LOCKED SURFACE (end of session) — the final architecture:**
- **Player = Morph + Path + SLAM.** Morph = X (the free real-time axis). **Path = ONE
  control that traverses the Forge-baked best route through the rest of the cube**
  (Y×Z = Q×Transform). SLAM = drive/character knob. (Resolves "2 controls for 3 axes":
  Morph is free, Path collapses the 3D volume into one designed sweep, SLAM is character.)
- **Forge = (1) design the FULL 8-corner 3D cube, (2) FIND THE BEST PATH through it.**
  The path is a 1D trajectory the Path roller follows. Forge PROPOSES the route that tours
  the most musical territory (max spectral travel / most-distinct corners), human nudges it
  by ear (machine proposes, ear curates). So the full 3D is designed; one curated 1D path
  is what ships per body.

**DECISIONS (this session):**
- Decoder is DEAD ("fuck the decoder"). Permanently parked.
- v2 = **8-corner 3D cube**: X=Morph, Y=Q, Z=Transform. Chosen over 4-corner+drive
  ("the 3d path is the better one"). I'd been steering to the cheaper path; the honest
  pricing showed 3D is better and NOT a core rewrite.
- **ARCHITECTURE (frozen core UNTOUCHED):** 8 corners = TWO 4-corner planes (Floor Z0 +
  Ceiling Z1). Runtime **Z-crossfades the two plane-bodies (packed u16 word-lerp) → ONE
  4-corner body → the EXISTING engine**. = full trilinear, reuses the verified
  packed-lerp morph. Proven in the prototype's `z_lerp`. So 3D costs authoring + UI, not
  a core rewrite or re-null (each plane is a normal 4-corner body).
- **Z = SHAPE morph.** SLAM drive stays a SEPARATE knob = the distortion/AGC character
  (already shipped; the ".4 cube Z=clipping-drive+AGC" advice IS df2 doctrine).
- **AUTHORING = KIN FIELD:** don't hand-place 8 corners. Define 6 REGISTERED slots
  (body/F1/F2/F3/air/top), each a band that SLIDES across X/Y/Z via per-axis deltas;
  the 8 corners are the field's vertex-readings → the whole VOLUME glides (no mush).
  Verified clean: sub ≤0.8 dB all corners, peaks +8..+16, finite. Tyson: "it works."
- **UX INTEGRATION:** two rollers stay. Roller1=Morph(X). Roller2 = a per-BODY baked
  PATH through the Q×Transform plane (diagonal / pure-Q / pure-Transform / curated). SLAM
  = knob. "Design in 3D (Forge), play in 2 (player)." Linking 2 axes = ZERO fidelity
  loss (bit-identical at every reachable point), loses 1 DOF of REACH (off-diagonal
  corners), recoverable per-body via the curated path.
- **Per-body Z meaning:** Z is EITHER a shape axis (8-corner body) OR "spent" on drive
  (.4 body — IronLung: peaks crash into a static distortion ceiling). Same engine, two
  body types. The .4 ships on TODAY's engine (no new format).

**PROTOTYPE (scratch, `dev/tmp/cube_byear/`):**
- `cube_display_view.py` → `cube_display.html` = THE working prototype: real-time 3D
  cube, TWO sliders (Morph + Intensity=Q+Transform linked), kin field, live Web Audio
  (pink → 6 RBJ biquads), auto-morph, single-line response.
- `design_surface.html` (drag bands on a Hz overlay); `author_cube.py` (renders the cube
  through the REAL trench engine: pink full-cube sweep).
- **HONEST CAVEAT:** prototype audio = CLEAN filter only (Web Audio RBJ), NO SLAM/AGC
  chip character. It proves navigation + kin field + display-logic, NOT final sound. Real
  chip audio = `pyruntime.trench_ffi.engine_render_slam` / the plugin.

**CLEAN-ROOM STUDY REFS — NEVER SHIP (E-mu-derived names + shapes):**
- `C:\Users\hooki\trenchwork_recovered\contracts\cleanroom\handoffs\emu_filter\cube_display\v1\`
  — 72 E-mu filter DISPLAY shapes (6-section morph-endpoint FORMAT). Use the FORMAT/
  display-logic for the visualizer; never the names/shapes.
- `C:\Users\hooki\df2\### Permanent Master Acoustic Dictionary.txt` — behavioral spec of
  ~20 Z-plane archetypes (Morph/Q/Transform behavior). Author originals in-spirit.
- NotebookLM = the recipe faucet (drafts Hz/Q/dB RECIPES; never coefficients).

**V2 ENGINE / FIDELITY NOTES (curated from NotebookLM; traps stripped):**
- SHIPPED core stays FROZEN (DF2T + packed-u16 morph, X3-null). Notes are v2-engine only.
- Sweep-stable topology (v2): Zavalishin TPT/ZDF (SVF) or normalized ladder/lattice —
  stable under fast sweeps. Already our v2 foundation (TPT SVF proven stable at Q=1e9).
- Interp in an ENCODED space, never raw biquad a1/a2 (warps pole paths). df2 ALREADY
  does this via packed 16-bit minifloat lerp. NOT ARMAdillo (discarded — clean-room).
- Cascade runtime safety (v2): L∞-norm peak scaling per stage (no overflow) + bandwidth/
  coupling compensation when high-Q peaks collide (<~200 Hz → tens-of-dB surge). df2
  already enforces the 200 Hz coupling FLOOR in authoring; L∞ + collision = runtime guard.
- Minimum-phase IIR = analog character, zero latency, no pre-ring. df2 already is.
- ".4 spent-Z" body type: saturation injected INTO the cascade so morphing peaks crash
  into a static distortion ceiling (IronLung). DROP its synth framing (no keyboard
  tracking / Note-On in an FX).

**DO NEXT (staging, no frozen-core surgery):**
1. (done) prototype proves navigation + Z-crossfade + kin field.
2. Firm up the 8 kin corners by ear (first pass done; iterate on Tyson's ear).
3. `compiled-v2` body format: two 4-corner planes + roller-2 path descriptor +
   Z-crossfade wrapper; re-run null per plane.
4. Forge 4→8 + Z + roller-path designer (egui; ~13 hardcoded "4" sites mapped by an
   Explore pass — corner array, `body()` bilinear→trilinear, puck+Z, labels).
5. Plugin: roller-2 = body path, two-plane load, display.

**OPEN DECISIONS for Tyson:** (resolved — surface is LOCKED: Morph + Path + SLAM.)
Remaining: how the Forge PROPOSES the best path (e.g. maximize cumulative spectral travel
through the 8-corner volume, or hit the most-distinct corners — then ear-nudge); and build
order — SHOW-IT (prototype a Path roller following a curated route) vs SPEC-IT (write the
compiled-v2 two-plane + Path body format). Also offered but declined: build IronLung as a
real .4 body through the chip engine (engine_render_slam) to hear the distortion ceiling.

**BLOCKER reminder:** still SELLABLE BODIES. The cube is the vehicle; the kin field +
by-ear loop authors the content. Don't let tool-building eclipse shipping auditionable
bodies. The whole session was prototype with CLEAN audio — the real chip sound (SLAM+AGC)
has not been heard on these corners yet.

---

## 2026-05-29 LATE NIGHT — GAIN-STAGING + FILTER-TYPE VOCABULARY + METHOD CROSSROADS (ARCHIVE — superseded by the v2 cube above)

**Read `STATE.md` top entry first — it has the full picture.** Then memories
`prefilter-slam-gainstaging`, `iconic-preset-constellation`, `authoring-surface-
fitter-proposes`, `agc-drive-is-the-character`.

The vocal "Small Talk" arc (peaking-EQ vowels) was **set aside**. Tyson re-aimed at
his favorite ROM presets — **bass/acid/sweep** — which is the right target for an
**insert FX** (TRENCH processes 808/reese/vocal on the chain; it is not a source).
Premium bar: each preset worth **$99–149 AUD**.

**WHAT WAS LOCKED THIS SESSION (doctrine + tooling, no bodies shipped):**
1. **Gain-staging is the spine.** SLAM (pre-cascade saturator) feeds the filter
   harmonics = density; AGC (post-cascade) = glue + wrap grit; clean input = max
   resonance; keep OUTPUT clean. Judge a body across the **drive ladder**
   (clean→slam→slammed→crush) on **real bass**, not pink noise. New render path:
   `trench_ffi.engine_render_slam`.
2. **Surface locked:** only SLAM + QSound optional; neutral default; presets 0/0.
   EOS/CVSD ripped from the shell (`TrenchParameters.cpp` → OFF/SLAM).
3. **Iconic presets are 5–6-pole CONSTELLATIONS** (not single resonances). Morph
   reshapes the constellation; Q tightens EVERY radius (the Talking-Hedz mechanism).
4. **Method crossroads (decide first):** hand-placing rich constellations to plot-
   match DOESN'T converge (coupled pole+zero, blows up). Canonical surface = fitter
   PROPOSES → human nudges by ear. But the shipped `fit_corner_from_magnitude` IS
   the retired factorizer; `forge_fit` (LSQ) is better but not wired to a stable
   packed export. **Wire that first.**

**THE PACK (Tyson names them):** 1 Deep Bouche · 2 Lucifer's Q · 3 MegaSweepz ·
4 Meaty Gizmo · 5 Klub Klassik · 6 BassBox 303 · 7 TB or not TB.

**TOOLING:** `tools/voxbench.py` (filter-type vocabulary + `verify_body` +
`audition_fx` drive-ladder + reese/808/pad sources). `.claude/workflows/trench-
listen-loop.js` (ran once on OLD vocal recipes; that output is superseded). Scratch
in `dev/tmp/voxlab` + `dev/tmp/loop_run` + `dev/tmp/pack` (gitignored).

**DO NEXT:**
1. Wire `forge_fit` → stable, zero-paired, **packed** export (the proper fitter).
2. Author the 7 via fitter-proposes → nudge-by-ear, plot-matched to curves drawn in
   each archetype's SPIRIT (original, NOT E-mu's data — clean-room). Audition on
   reese/808 up the SLAM ladder; ear picks; null gate; bake roster.
3. Delete dormant `Cvsd` + `SpatialMode::Trench` from `trench-core` → rebuild →
   re-run null gate (one verified pass).
4. **Hazard:** `PluginEditor.{cpp,h}`, `TrenchResponseDisplay.{cpp,h}`,
   `chassis_variants/*`, `runtime_layout.json` are dirty but NOT from this session —
   confirm provenance before committing.

---

## ARCHIVE — 2026-05-29 earlier night · VOCAL peaking-EQ breakthrough (parked, still valid doctrine)

The vocal method still holds (it's just not the current target): VOWEL filters =
parametric PEAKING EQ (flat baseline + formant bumps, no notches); Morph = the vowel
journey (ah→ay→ee); Q = mouth-cavity/Body-Size; **AGC drive is the character**
(audition driven, not boost=1.0 — see `agc-drive-is-the-character`); validate with
the simple magnitude curve. Small Talk candidates are in `dev/tmp/journeys/`. The
canonical vowel primitive is `tools/author_journey.py`.

---

## This session — 2026-05-29 earlier (skill/CODEMAP/repo lock)

**READ `CODEMAP.md` then `STATE.md` top entry.** Working tree committed;
`forge-recovery` ahead of origin (not pushed).

**What happened this session:**
- **Canonicalized the `df2-operator` skill.** It routed to 6 deleted docs
  (BRIEF/SPEC/BODIES/BRAND/ARCHITECTURE/FRAME_BANK) and asserted 2 things the
  code contradicts. Now routes to live files and names the **code** as authority.
- **Wrote `CODEMAP.md`** — where everything lives, the shipping signal path,
  dead-vs-real code, the central-screen anatomy, and repo hazards. The operator
  skill routes to it.
- **Fixed the resampler static bug** (`FixedRateTrenchIsland.cpp`): the unsafe
  4-arg `LagrangeInterpolator::process` read one sample past the buffer → random
  memory as full-scale noise from zero input. Now the bounded 6-arg overload +
  clear guard + a Catch2 silence test. **Unit-verified at 44.1/48/96 kHz — NOT
  yet ear-verified in a host.**
- **Locked the repo:** hardened `.gitignore` (vendored JUCE/clap, build
  artifacts, scratch, `bodies/generated/` cache), then 3 commits saving all
  in-flight work + the new docs/skill/CODEMAP.

**Two doctrine corrections** (now in the skill + CODEMAP; root `CLAUDE.md` still
carries the stale lines, worth fixing): shipping morph is the **PACKED-domain**
bilinear (`cartridge.rs:314` → `interpolate_biquad`), not decoded-f64; the
chassis is **not green** — palette is `TrenchStyle.h` (red-tinted PNG + bone +
phosphor-green accent, active-only).

**CANONICAL AUTHORING LOCKED (2026-05-29):** presets are made by **bold direct
4-frame placement** (`corner_words` → 240 bytes verbatim, like the ROM), scaled
via the `forge-corners` skill. Poles on real freqs+bandwidths, every pole
zero-paired, MORPH = a bold whole-spectrum journey, Q = a free per-body character,
KIN corners → the MIDDLE is the product. The factorizer / `make_class_bodies` /
`sweep_roster` generate-and-cull path is RETIRED for authoring. Validated against
the decoded ROM filters + the Morpheus source. See memory `canonical-preset-authoring`
and CLAUDE.md "How presets are authored". The 0529 factorizer sweep
(`dev/tmp/sweep/roster_0529`) is scratch — superseded.

**DO NEXT (agreed sequence — Tyson drives the order):**
1. **Author the first canonical bodies** — one bold body per category via the
   `forge-corners` skill (Vocal first: oo↔ee MORPH × lax↔tense Q), audition the
   MIDDLE through the shipped engine, ear-pick keepers, bake into the roster.
2. **Screen revamp** is shipped to the curve + SLAM/5D (commit a81fb2c); still
   needs the rust+blue faceplate PNG (image #1) dropped into
   `juce-shell/assets/images/` to seat the face + place the Slam/5D knobs.
3. **Gut the cruft** (CODEMAP §player dead files + the 12 MB zip).
4. **Execute `REBUILD_PLAN`** once the above settle.
5. **Ear-verify the resampler fix** in Standalone/AudioPluginHost — never FL.
6. *(optional)* push `forge-recovery` to origin.

---

## ARCHIVE — previous session, 2026-05-28 late

**READ STATE.md TOP ENTRY FIRST.** It has the full picture. Brief summary:

**Strategic position:** Tyson is exhausted, wants a fresh-eyes audit of the
codebase. A complete audit prompt for an external AI is in the conversation
transcript — proposes three rebuild paths. My read is Option B (rewrite the
JUCE shell, keep `trench-core`) — every bug found today lives in the JUCE C++,
the Rust core is solid.

**What shipped:** 7 new originals baked into the player (Voice Walk, Mason
Tube, Knock Burst, Metal Scream, Phaser Slide, Cut Edge, Maul). Plus a body-
strip bug fix that unlocked the other 45 baked bodies (clicks were collapsing
to index 0 or 1 only). VST3 rebuilt + installed to Program Files.

**The real blocker:** FL Studio was running continuously since May 25 — every
rebuild today was loaded into a process that wouldn't release the cached DLL.
Tyson needs to kill `FL64.exe` in Task Manager and reopen FL to actually load
today's work.

**Critical things to know next session:**
- AGC engages at +22 to +28 dB filter peaks (table indices 4–7). Below +15 dB
  it's dormant and bodies sound clinical.
- Engine ceiling: 12 poles + 12 zeros per corner (240-byte format, X3 parity
  is the patent anchor — don't break).
- Mud is broad-Q low-freq peaks, not narrow razor poles. Balance rule (low-mid
  peak ≤ mid+treble peak) is the real cull.
- Dev iteration must use Standalone or AudioPluginHost — never FL. Windows
  caches DLLs in the host process until full exit.
- Latent display bug still in `TrenchResponseDisplay.cpp` (`kBodyNames[4]`
  hardcoded). Cosmetic, not blocking.

**DO NEXT:**
1. Confirm `FL64.exe` is killed and FL reopened so the rebuilt plugin actually
   loads.
2. Have Tyson audition the 7 originals + Forge Audition vocal swaps on real
   source (808 / vocal / drum loop), not synthetic test tones.
3. If Tyson decides on the rebuild, hand him the audit prompt from the
   transcript and let an external AI produce the AUDIT.md + REBUILD_PLAN.md.
4. Otherwise: fix the `TrenchResponseDisplay` latent display bug, sort the
   two-VST3-install-path issue (delete LOCALAPPDATA copy), and start working
   through the bodies he marks as KEEP.

---

## ARCHIVE: previous "This session" — 2026-05-28 evening (FILTER TYPE CARDS)

**MISSION: a body is a named FILTER TYPE. The producer picks a class + card, optionally
a reference inside it, and listens. Code generates, culls, and frames as named machines.
Do NOT invent another authoring engine — this is a front door over the proven generators.**

**Read first:** `CLAUDE.md` (doctrine) -> `STATE.md` top entry -> this file.

**THE ONE WORKFLOW (producer front door):**
1. `python -m tools.make_class_bodies --list` (cards) · `--list-classes` (taxonomy).
2. `python -m tools.make_class_bodies --class EQ_CUT --campaign razor_shell --count 64 --seed 1001`
   -> whole 4-corner bodies, hard-culls broken, publishes survivors to
   `bodies/generated/gen_<campaign>_s<seed>_NN.bin`, writes a **purely musical**
   `dev/tmp/target_browser/<campaign>_s<seed>/audition.html` (card header + Candidate NN +
   KEEP/MAYBE/REJECT — no DSP on the surface).
   Add `--reference [slug]` to shape the card from a P2K reference (A/B preview page, never copied).
3. Listen, mark KEEP/MAYBE/REJECT, then:
   `python -m tools.make_class_bodies --keep <run_dir> cand_07 --notes "why it wins"`.

**v1 CARDS (`tools/filter_type_cards.json`):** speaker_knockerz · small_talk · razor_shell ·
aluminum_siding · cul_de_sac · glass_throat. Each maps to a `target_templates` archetype +
internal class tags + an optional reference inspiration.

**REFERENCE→ORIGINAL path (`tools/reference_brief.py`):** `--reference razor_blades` extracts a
musical brief from `bodies/rom/P2k_*.json`, generates ORIGINAL bodies, and **rejects any too close
to the reference**. Behaviour only — never copy coefficients/curves/names.

**VERIFIED RUN:** `make_class_bodies --class EQ_CUT --campaign razor_shell --count 64 --seed 1001`
-> 51/64 survived, 51 presets published, audition page DSP-clean.

**HARD RULES:**
- A body is the whole Morph/Q surface: M0_Q0(HOME), M100_Q0(AWAY), M0_Q100(TIGHT HOME),
  M100_Q100(TIGHT AWAY). Generate from cards/archetypes; the 4 corners are KIN by construction.
- NO stage roles / topology-locked pole bands (the stage-authoring trap — rejected this session).
- Gates cull broken only (unstable/non-finite/pedestal/clip/no-motion). Drift/chaos/off-target +
  similarity are advisory. The EAR is the boss; the avoided step is curation, not more generators.
- No coefficients/poles/packed words/stages/Q-numbers on the producer surface. No E-mu/Morpheus/
  Z-plane branding product-facing. Commercial release needs legal review.

**OVERNIGHT SWEEP DONE — audition queue waiting:** `dev/tmp/sweep/roster_0528/audition.html`.
Six families (Vocal/Cavity/Resonant/Knock/Comb/Cut), bold twin-anchor (HOME & AWAY genuinely
different, ~32 dB apart; tame→violent), 900 survivors / 1152, 16 shortlisted each (96 total),
all stable. Per-family readouts in `dev/tmp/sweep/roster_0528/families/*.md`.

**DO NEXT:** open `dev/tmp/sweep/roster_0528/audition.html`, A/B HOME→AWAY (should be genuinely
different now), mark KEEP/MAYBE/REJECT, run the per-body keep command shown on each card to lock a
v1 body per family. The shortlist order is a soft pre-sort, not a verdict — the ear chooses.
Re-run a family bolder/again: `python -m tools.sweep_roster --sweep <id> --family <fam> --seeds .. --count ..`
then `--merge`. Do not promote bodies before the ear chooses.

---

## v1 boundary

Four bodies shipped in compiled-v1 cartridges, loaded by the JUCE shell.
Personal distribution / closed beta first. wgpu visualization is not
present in this checkout and should not block the first body audition.

| Ships in v1                  | Defer to v1.5+              |
|------------------------------|-----------------------------|
| 4 bodies                     | Snapshot capture plugin     |
| JUCE shell + cartridge load  | Public forge / Filter Factory release |
| JUCE response display        | More bodies                 |
| Internal forge (Tyson only)  | Inspect panels / diagnostics UI |

**4 bodies target:** Speaker Knockerz, Aluminum Siding, Small Talk,
Cul-De-Sac. Current tracked body+cartridge pairs exist for Small Talk
and Speaker Knockerz; see `bodies/` for truth.

---

## Strategic pin

- **Revenue model:** plugin once, cartridges recurring.
- **Moat:** Filter Factory is private. The fact that only Trenchwork
  can produce Trenchwork bodies is the product.
- **Risk surface:** Rossum US10,514,883 active ~2038. Rossum Electro
  actively sells Morpheus Eurorack. Personal-distribution beta is the
  low-risk path; commercial release needs attorney.
- **Audience filter:** plugin is opaque on purpose. If a producer needs
  it explained, they're not the buyer.
- **Names:** Trenchwork (company), df2 (product), 1hook (music). No
  E-mu / Z-plane / Morpheus references in anything user-facing.

---

## Out of scope this quarter

PhantomVoice. QSound. MorphDesigner. Type 2/Type 3 compiler. template
parsing. SQLite archaeology. Public Forge. Inspect. UI metaphor work.
Brand exploration. ARMA extractor (gated by synthetic notch test that
hasn't been justified yet).

If one of these comes up: not now.
