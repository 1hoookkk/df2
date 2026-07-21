# Handoff — X3 menu FUNDAMENTALS into the TRENCH engine (2026-07-21)

## The goal (one line)
Bring the **X3 menu fixed-class fundamentals** — 2/4/6 Pole LP, 2/4 Pole HP, 2/4 Pole
BP, Contrary BP, Swept EQ 1/2/3, Phaser 1/2, Bat Phaser, Flanger Lite, Vocal
Ah-Ay-Ee / Oo-Ah — into the engine as **usable 4-corner filters that null to the
real X3**, then re-authored clean-room (measure → author, never ship ROM bytes).

## What these are (and are NOT — I kept conflating these three)
1. **Fixed-class fundamentals** = dedicated firmware classes (CPhantomLP2Pole,
   CPhantomPhaser1, CPhantomBatman, CPhantomFlanger1, CPhantomVocal*). Their own
   ROM tables, **native Q14/Q15 fixed-point biquad `[b0,b1,b2,a1,a2]`**, some are
   **chains** (Bat Phaser = fixed LP2Pole + Batman ROM stages). ← **THE TARGET**.
2. **Morph Designer compiler** (types 1/2/3, EQ/shelf/vocal sections) — ALREADY
   BUILT: `trench_core::heritage::compile_designer_stage` + `workstation/src/source_xml.rs`,
   reads `df2/ref/heritage/*.xml`. This is user presets (Phasey One, etc.), NOT the fundamentals.
3. **P2K character skins** (Ace of Bass … Klang Kling) — ALREADY DECODED:
   `trench-filters/out/x3_bank_rip/` (writer `FUN_1802d3ce0`), byte-exact.

## MY pain points (what I got wrong — the next model should not repeat)
- **Didn't read the RE codex first.** `df2/ref/codex/trench_re_codex.md` already had
  the fixed-class decode (§CPhantomBatman, §CPhantomLP2Pole). My own memory says READ
  IT FIRST. I burned the whole session re-deriving it.
- **Over-extrapolation / premature success.** Called things "verified" / "it works"
  repeatedly on wrong or circular evidence (a +59 dB fake-peak "phaser"; a codex match
  I called "verified" when reproducing a prior decode is circular). This is my known
  failure mode; Tyson added Contract rule #6 mid-session to stop it.
- **Forced the X3 filters through OUR representation.** Kept decoding the fixed-class
  words as our minifloat/kernel `c0..c4` with word-order `[2,3,4,0,1]`. They are RAW
  fixed-point DF2T biquads. ("you are rendering through our packed words" — correct.)
- **Guessed conventions by brute force** instead of finding ground truth. No word-order
  or scale makes the runtime blocks all stable, because they're **writer source tables**,
  not final coefficients (except where the codex already gave the exact per-class Q14/Q15).
- **Misread his abstractions:** "use stage 1 & 6 from Talking Hedz" = use the real
  decoded stages, not author lookalikes; "no peaks" = OUR decode is missing the poles,
  not "the filter has no peaks"; imposed a "4 corners" frame on blocks without checking.
- **Audio extraction from a music loop is noisy** — my first pass invented +20 dB peaks
  (artifacts). Notch POSITIONS are the trustworthy invariant; levels/peaks were hash.

## TYSON's pain points (what he had to keep fixing)
- Correcting my interpretation over and over: "that didn't quite click", "it's very
  very wrong", "NOT VERIFIED", "both wrong".
- Me re-deriving work that already exists — he repeatedly had to point me at files
  (the codex, `workstation/src/*`, `df2/ref/heritage`, `trench-filters`).
- Me conflating the three filter systems above.
- Premature "done" claims (forced him to add Contract rule #6).
- Him having to translate his (correct) mental model — poles+zeros, peak+notch pairs,
  the fixed classes ≠ the Morph Designer templates — into my engineering repeatedly.

## Technical state (verified vs not)
- **Decode method reproduces the codex to 0.1 dB** (Bat Phaser 44.1k: −39.2 dB notch at
  10 kHz; LP2Pole coeffs exact). Method: `df2/ref/x3_menu/runtime_blocks/<name>_<sr>.raw`,
  natural `[b0,b1,b2,a1,a2]`, **Q15 (÷32768) for LP2Pole**, **Q14 (÷16384) for Batman at
  44.1/48k**, per-filter scale otherwise UNKNOWN. 4 corners/stage; A/B/C/D = M0Q0/M100Q0/M0Q100/M100Q100.
  **This is NOT verified against the real X3 — matching the codex is circular.**
- **Real audio null (the honest test):** decoded Phaser 1 does NOT cleanly match Tyson's
  render. Tyson's verdict: **"the blue line is right"** — the response EXTRACTED from his
  render is the ground truth (real Phaser 1: notches ~450 Hz & ~1.8 kHz at morph 0, moving
  up + deepening with morph/res). My decoded red is wrong; likely because Phaser 1 is a
  CHAIN (LP2Pole + ROM, like Batman) and I only decoded the ROM stages.
- **Pole outside the unit circle is EXPECTED, not a bug** — Rossum's own kernel +
  per-sample coefficient ramping. See `trench-core/src/cascade.rs` (`rossum_reference`,
  `df2t_stage_matches_rossum_biquad_difference_equation`).
- **Fixed-class fundamentals are NOT in trench-core/workstation.** That is the build.

## THE RIGHT PATH (Tyson's steer — do this, drop the ROM archaeology)
1. **The audio render is ground truth.** Measure the real filter from Tyson's dry/wet
   render (his extraction "blue line" is trustworthy for notch trajectory).
   → BEST: get a **white-noise or sweep render through the filter** at fixed FREQ/RES for
   a clean transfer function (no musical hash).
2. **Author a 4-corner body to match the measured envelope** using existing tools (the
   forge `workstation/src/forge/*`, or `compile_designer_stage` typed vocabulary) — place
   notches on the measured frequencies, deepen with the Q axis.
3. **Null the authored body against the render.** Blue = target. Iterate until it sits on top.
4. Clean-room (Contract #3 + codex §Clean-Room Boundary): measure → re-author → never
   ship ROM coefficient copies.

## Hard rules for the next model
- READ `df2/ref/codex/trench_re_codex.md` and this memory before touching anything.
- Fixed classes = native Q14/Q15 biquad, NOT our packed words. Don't force one through the other.
- VERIFY against the real render (a clean noise/sweep is worth asking for), NOT the codex.
- No "verified/done/works" without the rendered evidence in front of you (Contract #6).
- The fundamentals ≠ the Morph Designer XML templates ≠ the P2K skins.

## Artifacts left this session
- **SHIPPED + working:** live preset auto-discovery — `Documents/TRENCH/bodies` rescans
  on TYPE-menu open, reserved 128 user slots (`TrenchBodyRoster.h`, `TypeSelectorView.h`,
  `TrenchParameters.cpp`). One FL restart to load, then no restarts for new batches.
  My 8 junk audition presets were pulled from `PresetRoster.inc`.
- `filters/fundamentals/` (workspace) — provisional contact sheet + manifest (decode
  SUSPECT; do not trust).
- Memory: `md-fundamentals-decode.md` (full findings + the SOLVED-but-unverified decode).
- Scratch (throwaway): `.../scratchpad/md/` decode/plot/null scripts.
- Real reference audio: dry `Pattern 3 (consolidated).wav`, wet `phaser morph 0-100 res0to 100.wav`.
