# TRENCH handoff — 2026-07-20 night

Read `AGENTS.md` and `CLAUDE.md` first, per standing project rules. This file
is additive context for picking up exactly where this session stopped.

## Build/install state (verified, not assumed)

- `TRENCH_VST3` was built Release and installed to
  `C:\Program Files\Common Files\VST3\TRENCH.vst3`, SHA256-hash-verified
  against the build output.
- The old locked install was parked as
  `TRENCH.vst3.inuse-old-20260720-184500` (not deleted) because FL Studio
  held the DLL open at install time.
- **FL Studio must be fully quit and relaunched** to pick this up — it keeps
  VST3 DLLs loaded for its whole process lifetime, so closing/reopening just
  the plugin window inside FL is not enough. As of the last check in this
  session the user had not yet confirmed a full FL restart, so the visual
  fixes below are unverified in a live host.
- Proof renders all session came from the **FaceShot** headless harness
  (`build/TRENCH_FaceShot_artefacts/Release/TRENCH_FaceShot.exe`), a separate
  console app instantiating the same `PluginEditor`. It never touches the
  installed VST3 — always rebuild+reinstall the real plugin before judging
  "does this work," FaceShot only proves the source renders.

## What actually changed this session (all in the dirty working tree, nothing committed)

1. **Typography restored** to the bold/Arial + bone-white engraved-catch
   treatment for TRENCH/BODY (this was already the intended direction from a
   still-checked-in-but-modified `trench_face.png` reference; an earlier
   revert to committed HEAD's thin/non-bold typeface was WRONG and undone).
   `LabelsLayer.h`, `TypeSelectorView.h`, `Theme.h::drawEngravedText` (now
   bone-white `0xffe7dec9` instead of pure white).
2. **Curve rendering**: `GraphDisplay.h::drawResponseTrace` now renders the
   bloom+core stroke stack into a reduced-resolution offscreen image (alias
   scale currently `0.50f`) and blits it back nearest-neighbour-scaled, so
   the trace reads as a genuine low-res LCD stair-step instead of a smooth
   vector line. This was explicitly requested — "we aren't shipping E-mu
   source pixels" is unrelated to this file, the curve is procedurally
   generated, not sourced from any bitmap.
3. **Geometry nudges** in `UiLayout.h`: `typeSelector` bar shifted right
   (x=245, was 198) for BODY-label breathing room; `amountWheel` nudged left
   8px (x=864, was 872); `brandLabel` (TRENCH) bumped to 18.5pt.
4. **KEY+MIX header module**: `KeySnapBox.h` had its own background removed
   (now just hover-wash + text, meant to sit on a shared capsule).
   `FaceplateView.h::drawHeaderGroupCapsule` was added to paint one shared
   recessed capsule behind both `KeySnapBox` and `MixKnob` — **this attempt
   failed**: too-low contrast against the plate and it visually clips the
   panel's rounded top-right corner. Needs another pass — either pull the
   capsule geometry in from the corner and darken it, or drop the
   shared-background idea entirely and just add a thin divider line between
   the two controls with no fill. User's last word on it was still open.

## Critical fix: shipped E-mu hardware pixels (IP issue)

Found and fixed one instance, **flagged but did not fix two more**:

- **FIXED**: `plugin/assets/trench_roller_strip.png` and
  `plugin/source/ui/WheelControl.h` had been replaced (by an earlier
  same-day session) with code that literally cropped frames out of
  `C:\Users\hooki\do-it\emu-x3-bitmap-dump\BITMAP4331_2.bmp` — a dump of
  E-mu's own ROM/hardware bitmap — and shipped them almost unmodified as the
  product's wheel asset (`dev/build_raw_wheel_strip.py` is the script that
  did this; it must never be run again). Reverted both files to commit
  `aabd23be` ("pin recovered smoked-cobalt clean baseline", 2026-07-16) —
  verified pixel-independent of the E-mu dump (no dimension match anywhere
  in the 593-file dump folder). This is also the wheel the user identified
  as "the perfect wheel" from reference photos — light-grey ribbed body,
  blue cobalt lamp, 200x42 frames x257. Re-applied one small drag-tracking
  fix from HEAD (`displayNormalised()`'s `&& ! pressing` check) on top since
  it's a real bugfix unrelated to the asset.
- **NOT FIXED — still exposed**: `plugin/assets/display_bitmap4613.png`,
  `display_log_grid.png`, and `display_log_grid_rules.png` (the screen's
  glass/ruling texture) are ALL exactly the same pixel dimensions as
  `BITMAP4613_1.bmp`/`BITMAP4613_2.bmp` in the E-mu dump folder, with
  pixel-diff evidence of being lightly-to-moderately processed copies of
  that dump rather than original art. Unlike the wheel, **these have been
  this way since the 2026-07-18 commit `9ac18257`** — this is not from
  today's work and there's no clean git history to revert to. Fixing this
  means redrawing the screen texture from scratch as original art, not a
  file revert. This is a real, standing legal exposure in the shipped
  product and should be treated as a priority, not a someday-item.

## Open question: palette coherence ("one lit voice")

The curve/screen accent is currently coral/brick (`curveColour
0xffc96a54`), but the restored wheel's lamp is genuinely blue/cobalt (baked
into the `aabd23be` asset pixels, not a token). These are two different
colours on the same face. A prior long session flagged this exact mismatch
("teal wheel lamps next to that orange curve are two competing voices") and
resolved it by making everything teal — but that was reverted since, and the
curve has been coral all through today's work per the user's own reference
images. This was never resolved with the *current* wheel (blue). Last
question asked to the user (interrupted, no clean answer captured): should
the curve move to match the wheel's blue, or does the wheel's blue need to
become part of the family some other way? Needs a fresh verdict — don't
guess again, this has already burned two wrong guesses this session.

## New, unstarted: ML-based key detection

Long research discussion, fully verified (see below), zero code written.
Context: `KeySnapBox` (manual 24-choice scale selector, real DSP wired
through `trench_engine_set_key_snap` → `snap_stage_to_key` in
`trench-core/src/engine.rs`, retunes cascade resonances to a chosen
diatonic scale, tested) has no auto-key-detection feeding it. An earlier
benchmark of classical algorithms (Edmkey/Essentia/QMUL) against
`dev/tmp/key_benchmark/fsld/` (1400 ground-truth loops) was set up but never
scored — this session scored it: best ~55.6% exact match, unusable as a
silent auto-set.

Verified-real research (checked citations against live web search, not
trusted blind — one had an implausible April-2026 date and checked out
anyway):

- S-KEY (Deezer/LS2N, ICASSP 2025) — arXiv:2501.12907
- Stem-JEPA (Sony CSL Paris, 2024) — arXiv:2408.02514
- Masked Contrastive Pre-Training / "Myna" (Yonay/Hammond/Yang, Apr 2026) —
  arXiv:2604.10021, code at github.com/echo-cipher/keymyna

User's directive: do NOT train on the FSLD loops (random/unlicensed-feeling
for this purpose). Use **RTNeural** (github.com/jatinchowdhury18/RTNeural —
verified real, already shipping in other audio plugins: AIDA-X, BYOD, Chow
Centaur/Tape) for real-time-safe CPU inference, not a heavy framework. Train
a small, shallow MLP/CNN, not a foundation model.

Agreed plan (not started):

1. Data: **GiantSteps+ EDM Key Dataset** (600 tracks, CC-BY-SA 4.0,
   purpose-built for EDM key estimation — verified real, zenodo.org/records/1095691)
   + pitch-shift augmentation to cover all 24 keys from one labeled set.
2. Features: 12-bin transposition-relative chroma vector, not raw
   spectrogram — keeps the model tiny.
3. Model: small MLP, chroma-in → couple dense layers → 24-way softmax.
   RTNeural handles Dense layers cleanly; avoid Conv1D/GRU, unnecessary for
   a single-frame classifier.
4. Pipeline: train in Python (torch), export weights to RTNeural's JSON
   format, load in C++ at plugin init, run inference off the audio thread
   (background thread, lock-free handoff — mirror the existing
   `KeyTrackDetector` pattern for thread safety), confidence-gated UX
   already agreed: >75% auto-populate the scale selector silently, split
   confidence shows a soft-glow "Suggested: X or Y" 1-click confirm instead
   of guessing.

Next session should start at step 1 (pull GiantSteps+, build the
chroma-extraction + augmentation script) if this is still the priority.

## Two flagged-but-unscoped priorities (user's own words, no detail given yet)

- "modulation is one we need to fix next" — no specifics captured on what's
  wrong with it. Ask before touching.
- "amount still doesn't feel useful" — note the AMOUNT gain law
  (`effectiveGainDb = authoredGainDb * amountNormalized`) is already wired
  and tested in `trench-core/src/engine.rs` per an earlier same-day session;
  "doesn't feel useful" reads as a UX/interaction complaint, not a missing
  DSP law. Don't assume which, ask.

## Working conventions this session leaned on

- Every visual change was proven with a fresh FaceShot render at true
  326x503 scale before claiming anything — do this every time, this session
  got two typography/palette guesses wrong by not doing it early enough.
- Proof renders live under `dev/recovery_faceshot_20260720_*/trench_face.png`
  (many timestamped folders from tonight — the most recent is
  `dev/recovery_faceshot_20260720_smoked_cobalt/`).
- `dev/UI_RECOVERY_HANDOFF_20260720.md` and `dev/UI_WHEEL_FAILURE_20260720.md`
  (repo root, not `dev/`) document earlier failed passes from this same day
  — read them before repeating an approach; several dead ends are recorded
  there (raw-native-bitmap wheel, painted rectangles, procedural capsule
  candidate rejected with a `raise SystemExit` guard still in
  `tools/roller_assemble_compact.py`).
- One change per verdict. This session's biggest time-losses were from
  guessing a direction and building on it before checking — the wheel asset
  investigation (grep the actual pixels before trusting a filename or a
  comment) and the typography revert-then-re-revert are the clearest
  examples. Verify against real evidence (pixel diffs, hashes, actual git
  history) before making a visual claim, every time.
