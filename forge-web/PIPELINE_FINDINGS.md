# Findings — generator pipelines tested through the engine

The "best approach is hybrid" claim (different math per filter *character*) is
correct. Each pipeline tested through the shipped engine (`packed_probe`, the
0.0000-dB path) and the full morph-grid audit. Graded OBSERVED / REJECTED.

## 1. Analog / Swept (Early Rizer, MegaSweepz) — scipy.signal.ellip — WORKS ✓ OBSERVED
Tested Gemini's exact elliptic pipeline: `ellip(12, 1dB, 40dB)` LP at 8 kHz (corner A)
and 300 Hz (corner B), upper-half poles/zeros sorted by angle → 6 lanes → our encoder.
- **audit PASS, maxR 0.985, 0 unstable interior points** across the 17×17 morph×Q grid.
- **Clean result first try:** flat 0 dB passband, steep brick-wall cliff, elliptic
  stopband notches, cutoff gliding smoothly 8 kHz → 300 Hz across the morph.
- **Why it's clean where vowels fought:** for a low-pass, the **passband IS the body**
  — the lows are flat at 0 dB by definition, so there is **no foundation-vs-actor
  balance fight**. The thing that broke every vowel attempt simply doesn't exist here.
- **Zeros are GOOD here:** the elliptic zeros sit on the unit circle (r=1.0) just above
  cutoff — they ARE the brick-wall. (Opposite of vowels, where zeros must be banished.)
  → **Zero placement is character-dependent, not a global rule.**
- **Clamping caveat:** scipy's raw passband-edge pole hits r=0.99973; we clamp to 0.985
  for stability. That softens the resonant *edge peak* but the elliptic stopband notches
  still deliver the cliff — the slope stays brick-wall. Acceptable trade.
- **Verdict:** this is THE generator for the analog/swept family. Use ellip (notched
  brick-wall) or cheby1 (resonant peak). Ship it.

## 2. Vocal / Acoustic (TalkingHedz, MultiQVox) — ARMA / LPC all-pole — OBSERVED (earlier)
- Mine real audio (or Klatt tables) → **all-pole** poles. Zeros **banished** (Klatt law).
- The all-pole downward tilt is the body; formants are bumps on it. No DC zeros (kill
  the body), no Nyquist zeros (bury the formants) — both REJECTED by test.
- Tool: `tools/fit_two_audio_arma.py` (poles AND zeros; zeros from residual, not guessed).
- Status: law validated; the ARMA fitter wired into the UI is the next build.

## 3. Morph-Special / EQ (Peak-Shelf Morph) — scipy.signal.yulewalk — UNTESTED
- Draw an arbitrary target dB curve → `yulewalk` → zpk. For graphic-EQ-style morphs.
- Not yet run through the engine. Verify same way (pack → grid audit → plot) before trust.

## The hybrid law (confirmed)
- **Analog/swept → scipy classical (ellip/cheby).** Body is free (flat passband).
- **Vocal → ARMA/LPC all-pole.** Body is the tilt; zeros banished.
- **EQ/special → yulewalk.** (verify next)
- Then **human polish in `zedit.html`**: pin the foundation, set a pole collision,
  mask/unmask a zero. Math gets the authentic footprint; the UI weaponizes it.

## Process notes
- Per-corner gain: pin the passband (low for LP) to 0 dB, **distribute over 6 lanes
  (`^1/6`)** so no minifloat underflows.
- The **real interior-stability gate is the packed-grid audit** (`packed_probe` 17×17,
  maxR<1), not LSF math — the runtime interpolates packed words, not LSF. LSF/clamping
  are authoring-side guardrails; the grid audit is the truth.
- Corner names: **M0_Q0 / M100_Q0 / M0_Q100 / M100_Q100** (not HOME/AWAY/TIGHT).
- Artifacts: `dev/tmp/ellip_test/ellip.body240` + `ellip.png` (the working brick-wall sweep).
