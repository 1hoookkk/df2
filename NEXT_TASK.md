# NEXT TASK — stress test every function BY REASON. delete delete delete.

Doctrine (Tyson, closing 2026-07-27): **absolute elegance only.** The plate has
FIVE wells — screen, two wheels, two readouts — and that is the feature budget.
The stress test is MENTAL, not mechanical: we are not hunting bugs, we are
arguing each function's reason to exist against the use case. We have a full
stack of sauce — the question is which of it belongs on the plate.

Use case, Tyson's sentence: **an FL producer inserts TRENCH on a drum loop and
rides the filter until the loop sits, moves or becomes something they grin at.**
TRENCH is an INSERT EFFECT — the resample loop runs through the playlist
(process → TAKE → drop → process again), never inside the plugin.

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
