# Handoff — the fundamentals are FRAMES; read the stage anatomy (2026-07-21)

Supersedes `HANDOFF_20260721_x3_fundamentals.md` (written before the model was
understood — that one still frames it as "decode the ROM," which is the dead end).

## THE ABSTRACTION (Tyson's words — this is the whole thing)
> "understand the purpose of those stages… the stage anatomy… that's the entire
> abstraction. the stages show it."

**A filter is an anatomy of purposeful biquad stages.** A stage is a biquad — five
numbers `[b0,b1,b2,a1,a2]`. Each stage is an *organ with a job*, and you read the
job straight off its pole/zero — you never decode or reverse-engineer it:
- **Stage 1 = the air / crown** — pole high, zero pulled low. Top, presence, brightness.
- **Stage 6 = the body / floor** — pole low, Nyquist zero as a lid. Weight, foundation.
- **Middle stages = the voice** — pole+zero-above = formant (peak); zero on the circle
  = anti-formant (notch); far zero = shelf; pole near Nyquist = bite.

Air on top, body on the bottom, voice in the middle. **The stages show it.** Don't
treat a filter as a monolith to crack; it's an anatomy to read and compose.

## THE MODEL THAT WORKS (solved "last night", per Tyson)
**FRAME + VOICE = an iconic P2K filter.**
- **FRAME** = the air+body anatomy (stages 1 & 6) + the stage-correspondence, i.e. a
  RECIPE. This is the portable E-mu character — it's what turns a plain vowel EQ into
  *Talking Hedz*. Stages 1 & 6 are the identity, not accessories.
- **VOICE** = new rich data dropped into the middle stages: **measured sources**
  (recorded objects) **and tables** (DVTD vowel rails, modal/metallic/tube tables).
- Recipes live in `recipe-index/recipe_index_v1.json` (33 entries) + `workstation/src/recipe_index.rs`.
  Contract is the key: `recipeDoesNotSupplyPoleScaffolds` + `recipeAppliesToFrozenPolesThroughZeroOnlyAuthoring`
  + no bytes/geometry/names. **The recipe = the zero-only topology (the anatomy/behavior);
  the POLES are frozen, measured Hz you bring in.** "The zeros define the stage behaviour."

## TODAY'S GOAL (why the fixed-class fundamentals were the next targets)
The vowel/Hedz frame was solved last night. The **fundamentals are the NEXT FRAMES**:
2/4/6-Pole LP, 2/4-Pole HP, BP, Contrary BP, Swept EQ 1/2/3, Phaser 1/2, Bat Phaser,
Flanger Lite, Vocal Ah-Ay-Ee / Oo-Ah. Each is a stage anatomy (phaser = a comb of
notch organs; LP = cascaded pole organs + Nyquist zeros; etc.). Getting each frame
lets you wear measured sources + tables inside a phaser, a lowpass, a flanger — not
just the vowel frame. **The goal is the FRAMES, not the exact ROM bytes.**

## WHAT IS DEAD — do not repeat (both agents burned the day here)
**Decoding the fixed-class ROM tables to get the filters.** Proven three ways:
- The ROM tables aren't finished filters — they're writer *source tables* fed through
  E-mu's runtime (Rossum state-space kernel, per-sample coeff ramping, sample-rate
  sqrt-warp, chained fixed stages, gain-comp, non-linear fixed-point interpolation).
  Decoded raw → **degenerate corners, notches in the wrong place, poles outside the
  unit circle.** (`scratchpad/md/phaser_truth.png`.)
- **Verifying against the ROM/codex is CIRCULAR** — matching a prior decode ≠ matching
  the real filter. Both agents called circular matches "verified."
- **We do NOT know the block schema — never decode them as 4 corners.** `extract_x3_menu_filters.py`
  `compact_corner_snapshot` *labels* each 40-byte stage as 4×5 "corners" (A/B/C/D =
  M0Q0/M100Q0/M0Q100/M100Q100), but that mapping is an **unverified assumption**, not a
  known layout. Any "corner" claim from the ROM blocks (mine included) is unproven. The
  render defines what a corner is — you render at a known FREQ/RES, so the corner meaning
  comes from the knobs, not from a guessed byte slice.
- **Clean-room forbids shipping the bytes anyway** (Contract #3 + codex §Clean-Room).

## THE RIGHT PATH (proven today, on Phaser 1)
**The render is ground truth** (Tyson: "the blue line is right"). The stage anatomy is
**legible from the real filter's response**:
1. **Render** the filter (white noise or sweep → the output spectrum IS the magnitude;
   4 corners = FREQ/RES ∈ {0,100}²). Tyson's existing Phaser 1 render already gave the
   diagonal corners.
2. **Read the anatomy** off it — measure the poles (peaks) and zeros (notches). For
   Phaser 1: RES0 → notches 452 & 1814 Hz, no peaks; FREQ100/RES100 → notches 1814 &
   7601 Hz + resonant peaks 1319 & 5405 Hz. (`scratchpad/md/stages_from_render.png`.)
3. **Assemble frame + voice** — author each stage as frozen poles (measured Hz) + the
   zero recipe (its anatomy). Author STABLE (poles inside the circle); the ROM's outside
   poles are a runtime artifact, not something to reproduce.
4. **Verify each plot against the render** — not the ROM, not the codex.

Claude did exactly this: `scratchpad/build_phaser1.py` → a stable 4-corner Phaser 1
(`Documents/TRENCH/bodies/FUNDAMENTALS/06_PHA/phaser_1.body240`, grid-certified 0/0,
max_r 0.984), notches sweeping with FREQ, peaks arriving at RES100
(`scratchpad/md/phaser1_authored.png`). It is NOT yet nulled against the render — treat
as a first frame, verify + refine against the blue.

## WHAT EACH AGENT LEFT
- **CODEX/GPT** — `dev/tmp/fixed_class_bodies/` (15 `.body240` + `phaser_1_proof.png`).
  Built by decoding the ROM → analytical target → ARMA fit. **Discard as filters:** the
  target is the wrong (ROM) curve, and the fit doesn't even match it (spurious +30 dB
  peaks, missed notches — see the proof PNG). Its scale-mapping (LP called Q14) also
  contradicts the codex (LP2Pole = Q15). Useful only as a record of the dead path.
- **CLAUDE** — `scratchpad/` (render→stages pipeline: `stages_from_render.py` logic,
  `real_null.py`, `build_phaser1.py`; plots in `scratchpad/md/`). The render→anatomy→
  author pipeline is the keeper. Also SHIPPED + working this session: **live preset
  auto-discovery** (`Documents/TRENCH/bodies` rescans on TYPE-menu open, reserved 128
  slots — `TrenchBodyRoster.h`, `TypeSelectorView.h`, `TrenchParameters.cpp`). One FL
  restart to load, then no restarts for new batches.

## VERIFICATION STANDARD (Contract #6 — added this session because both agents violated it)
Never call anything verified/done without the rendered plot in front of you, and match
it against the **real render (blue)**, never the ROM/codex. A clean white-noise render
per filter (fixed FREQ/RES) makes it exact.

## GROUND TRUTH LOCATIONS
- Recipes/frames: `recipe-index/recipe_index_v1.json`, `workstation/src/recipe_index.rs`,
  `filters/` (METHOD.md = the frame+voice authoring model; archetypes; rails; tables).
- Measured sources: `out/candidates_partial_20260720_2103/` (186 bodies + audio).
- Tables (voice): `filters/tables/` (dvtd, klatt, modal, metallic, tube, vowel).
- Stage roles taxonomy: `pyruntime/stage_roles.py` / trench-core.
- RE codex (read for context, NOT as a decode oracle): `df2/ref/codex/trench_re_codex.md`.
- Real reference audio: dry `Pattern 3 (consolidated).wav`, wet `phaser morph 0-100 res0to 100.wav`.

## HARD RULES
1. Fundamentals are FRAMES (stage anatomies), not ROM bytes to copy. Read the anatomy.
2. Frame (recipe / stages 1 & 6) + voice (measured poles / tables) = the filter. Assemble.
3. Poles are frozen/measured Hz; recipes are zero-only topology. Don't invent poles.
4. Ground truth = the render (blue). Verify there, never against the ROM decode (circular).
5. **Never decode the ROM blocks as 4 corners — the schema is unknown.** Corners are
   defined by the FREQ/RES you render at, not by a guessed byte slice.
6. No premature success. Rendered plot first, then the claim. Correct yourself before Tyson has to.
