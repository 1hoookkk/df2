# NEXT TASK — stress test every function BY REASON. delete delete delete.

Doctrine (Tyson, closing 2026-07-27): **absolute elegance only.** The plate has
FIVE wells — screen, two wheels, two readouts — and that is the feature budget.
The stress test is MENTAL, not mechanical: we are not hunting bugs, we are
arguing each function's reason to exist against the use case. We have a full
stack of sauce — the question is which of it belongs on the plate.

CORE (final form, 2026-07-27): **The product is the authored filter journey
created by the Morph interpolation. Don't sweep a filter — move through one.**
Every function either reveals that journey or gets out of its way; every tenant
is guilty until Morph is provably more expressive because it exists. The bodies
are the actual product inventory. A body earns the roster only when:
endpoints meaningfully differ · the interior holds desirable poses (better than
a transition) · fast AND slow travel sound intentional · direction and speed
phrase expressively · Q opens a second coherent path · the source stays
recognisable enough to feel causally connected.
The killer demo: one source, one body, one uninterrupted Morph ride. Nothing else.

Supporting frame: **TRENCH turns existing audio into a playable resonant
instrument — make any sound speak, sing, move or hit differently.** The input
is the exciter; BODY is the resonating object; MORPH articulates; Q is energy
and instability; KEY gives resonances tonal gravity; MOVE performs it; MIX
preserves the original identity; SLAM finishes it. Honest limitation: it rings
energy already present — transients/noise/rich harmonics excite it, a sparse
sine doesn't; it never slices or stretches time.

First-contact case, Tyson's sentence: an FL producer inserts TRENCH on a drum
loop and rides the filter until the loop sits, moves or grins. TRENCH is an
INSERT EFFECT — the resample loop runs through the playlist (process → TAKE →
drop → process again), never inside the plugin. Every TAKE commits through the
E-MU Ultra 20-bit dithered resample: pristine capture, grit only by choice, so
generational reprocessing stacks character, not mud.

Standing upgrades under this frame: KEY = "make it sing" (possible defining
power, judge there). MOVE = performance articulation, not modulation presets.
TAKE = asset creation (one sound → sample family), verdict tied to whether
instant asset creation is part of the product promise.

## The work: one function at a time → reason → verdict → keep lean or delete

For EACH function: state what it does FOR THE USE CASE in one sentence. If the
sentence needs "also" or "unless", it's two functions and one probably dies.
If no sentence exists, delete it whole (code, params, assets, docs) — the
TakeButton/clip/SeedButton deletions are the template. No "hidden but kept".

**Immediate burial audit** (before the function pass — tombstones with no home):
`bite` standalone param (Q-coupling is the product; hidden twin knob dies),
`inputMode` (slam-into-filter: UI story or death), `hdMode` (same). Fix
PLUGIN_VIEW.md's wrong "no hidden params" claim while at it.

**Testable fact that decides OUTPUT:** is the TAKE buffer captured pre- or
post-output-trim? Post → OUTPUT shapes the dragged WAV and earns its life;
pre → OUTPUT is host-gain cosplay and dies.

Order (performance core first, tenants last):

1. **MORPH wheel** — the instrument. Stress: fast rides, automation, modulation fights.
2. **Q wheel + CHEW** — record the 55% ceiling verdict and the morph-unevenness
   verdict (character or inconsistency?) while stressing.
3. **BODY switch** — cycling under audio; is post-persistence switching still jarring?
4. **THE SCREEN gestures** — SLAM drag, TAKE drag-off, MIX readout. Three
   tenants; do all three survive a hand that's just playing?
5. **MODULATION + 56 phrases** — source material, not 56 features. Cull to one
   winner per movement grammar: smooth breathe / stepped rhythm / one-shot rise
   / bounded wander. Target 4–6 shipping. Modulation's only job is continuing a
   good MORPH gesture after the hand lets go — if it fights the wheel, it loses.
6. **MIX** — screen-only readout discoverable?
7. **KEY** — candidate sentence exists: "makes the phrase-melody land in the
   track's key." Judge by ear with phrases running; if snapped phrases don't
   audibly sit in key, delete whole. (GPT argued delete from the wrong manual —
   heritage "key" was keyboard tracking; ours serves loop-to-melody.)
8. **OUTPUT** — does it earn existence vs host gain?
9. **fiveD/QSound** — real thing, no home. In (needs a well and Tyson's art) or out.
10. **Onboarding** — five steps at true scale, live; trim anything that doesn't teach.

## Verdicts (recorded as spoken)

- **2026-07-27, tameness/saturation probe** (shipv2_303_cavity_acid, Q85, level-matched
  A/B set in tmp/agc_probe): Tyson picks **E** — untouched cascade is the direction;
  but raw E ride is "way too crazy". Measured: output tanh confiscates ~11 dB crest /
  ~15 dB resonance prominence (2× the AGC); AGC 16-number curve is heritage and
  PROTECTIVE (bypassing it makes the tanh crush worse); AGC_DRIVE moves opposite
  intuition (harder = livelier). Target = between A and E: keep AGC stock, rework
  output tanh into a safety net, not a tone stage. SLAM 100 flattens all upstream
  differences (separate question, unjudged). Side finds: &0xF wrap never fires;
  roster gain staging uneven (+14..+167 dB raw peak); cleanroom_lucifers_q max
  radius 0.877 — not actually a Q body, its level is all SCALE.
- **Follow-up diagnosis (same day):** tanh delta = almost pure transient (94–99% of
  removed energy in loudest 5%); "bizarre" F ride = AGC's unsmoothed tooth-jumps
  exposed (single-sample drops to 12.9 dB @ 39k / 15.9 dB @ 78k, ~25/s in bursts at
  specific morph regions) — the tanh was MASKING the zipper. All conclusions hold
  stronger at shipping 78125 rate. Fix must be paired: smooth AGC gain application
  (16 numbers stay; the jump becomes a glide — CHECK RE-vault behavioral contract
  first) + demote tanh to pure safety headroom. Neither alone is shippable.
- **SHIPPED 639472e4 — vault-authentic AGC chain** (Tyson: "ship it", G approved by
  ear): AGC_DRIVE 1.0 (Ghidra: the 2.22 pre-scale was never in the DLL path);
  POST_AGC_TRIM −6.5 dB keeps session level (±0.5 dB of old); saturate knee +12 dBFS
  = pure safety, 0 samples engaged both islands; character ≡ G (−125 dBc). NO FILTER
  null −24 → −6.5 dB (AGC never engages at unity on clean). OPEN: wet path now peaks
  ~+5 dBFS into SLAM — ear-pass SLAM at high drive on the new chain.
- **Phasor CHEW topology (US 10,514,883): TRIED AND REVERTED** — "apples to apples"
  (Tyson): no audible gain over shipped CHEW at fair calibration, so it dies (reverts
  7dda48fb + 873c3767; implementation archived at a9900a30 + d7a0e3f1). Facts kept:
  linear-identical static (4e-12) but a different filter under motion — ~5.4 dB
  quieter floor, prominence 32 vs 51-58 dB: the complex-state limit SPENDS resonance
  where shipped CHEW sharpens it. Shipped pole-radius CHEW confirmed as the sound.

## Standing rules

- One live function at a time; verdicts recorded HERE the moment they're spoken.
- Deletions: surgical, whole-path (UI + param + DSP + docs), proven by build+test.
- No new features during this pass. The empty lower-third of the plate is the
  ONLY expansion slot and it opens only with baked art.

## Carry-over facts (proven, don't re-litigate)

MIX0 bit-dry incl SLAM (−300 dB) · identity −240 dB · SLAM 0 hard bypass ·
settings persist across body switch · take drag doesn't drift SLAM ·
AGC −24 dB null at full scale on NO FILTER (open: too heavy?).

## References

PLUGIN_VIEW.md (surface map + state-line convention) · spec artifact:
https://claude.ai/code/artifact/68f8c688-9df6-41e0-bfe9-f67b8443711c ·
proofs: TRENCH_FaceShot ONBOARD/MIX/RATE/TYPE iter · pole_proof <body>.
