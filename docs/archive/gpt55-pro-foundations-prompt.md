You are a world-class DSP filter engineer. I'm building a morphing Z-plane filter plugin
and I need you to specify a set of FOUNDATION filter types — the standard generic functional
filters (lowpass, highpass, bandpass, swept EQ, phaser, flanger, vowel, EQ-morph) — precisely,
in MY format, so I can implement each as a thin "starter card" the user opens and then sculpts
by ear. Be concrete and testable: pole/zero numbers, not philosophy. Where a choice is
uncertain, say so and give the test (plot the packed magnitude response).

These are GENERIC textbook filters (a 2-pole lowpass is universal DSP, not anyone's IP). DERIVE
them from standard filter theory — Butterworth/Chebyshev pole patterns, RBJ peaking/shelf EQ,
Klatt/Peterson-Barney formant tables, comb/all-pass for phasing/flanging. Do NOT copy any
manufacturer's coefficients, bytes, or presets. Clean-room: math only.

## MY FORMAT (the immovable target)
- A "body" = 4 corners × 6 second-order sections × packed coefficients = one 12th-order IIR
  cascade. Fs = 39062.5 Hz.
- The 4 corners are (Morph0,Q0), (Morph100,Q0), (Morph0,Q100), (Morph100,Q100). The runtime
  interpolates the PACKED coefficients (morph-first, then Q) — the morph interior lives in
  coefficient space, not in response space.
- Each section is a pole+zero pair (both present). I express a section as:
  `pole_hz, pole_radius, zero_hz, zero_radius, gain_db`.
- Morph = pole/zero FREQUENCY placement (HOME→AWAY). Q (Secondary) = pole RADIUS / sharpness.
- An IDLE section = pole and zero coincident (same Hz + radius) so it cancels to flat 0 dB.

## MY AUTHORING MODEL (so the cards fit it)
- POLES come from the backend (verified real resonances, e.g. LPC-fitted from real audio); the
  user mostly does NOT hand-place them.
- ZEROS are first-class — the user carves them (canyons, notches, articulation).
- MOTION is what's authored: the HOME→AWAY travel plus Q-pressure.
- MEASURED constants from the real designer presets (use as rails): every shipped body uses
  **6 active zeros**; pole radius lives in **0.990–0.9998**; iconic bodies hit ~17 dB RMS
  morph-motion and ~10 dB RMS Q-pressure (functional utility versions sit ~3× lower).

## THE FOUNDATION TYPES TO SPECIFY
2 Pole Lowpass · 4 Pole Lowpass · 6 Pole Lowpass · 2 Pole Highpass · 4 Pole Highpass ·
2 Pole Bandpass · 4 Pole Bandpass · Contrary Bandpass · Swept EQ 1 Octave · Swept EQ 2/1 Octave ·
Swept EQ 3/1 Octave · Phaser 1 · Phaser 2 · Bat Phaser · Flanger Lite · Vocal Ah-Ay-Ee ·
Vocal Oo-Ah · Dual EQ Morph · Dual EQ + LP Morph · Dual EQ Morph/Expression · Peak/Shelf Morph

## FOR EACH TYPE, RETURN (concrete + machine-readable)
1. **DSP identity** — what it actually is: pole/zero topology, slope (dB/oct), the standard
   filter it derives from, and how a phaser/flanger's notches map to z-plane zeros.
2. **Mapping to my 6 sections** — which sections are active and each section's role, plus a
   CONCRETE starter per section:
   - `pole_hz` at Morph0 and Morph100 (the travel)
   - `pole_radius` at Q0 and Q100 (the pressure)
   - `zero_hz`, `zero_radius`, and how the zero moves across Morph (if it does)
   - `gain_db`
   Use all 6 sections; idle ones = pole+zero coincident (flat). Keep resonant poles in 0.990–0.9998.
3. **Motion + control** — what Morph moves (the gesture in one line), what Q/Secondary exposes,
   and where the user should carve zeros to give it life vs. a dead utility filter.
4. **Audition on** — the source (808, hat, reece, saw, noise, vocal).

## OUTPUT
A JSON array `foundations[]`, one object per type, with fields:
`{ type, family, dsp_identity, sections:[{role, pole_hz_home, pole_hz_away, pole_r_q0, pole_r_q1,
zero_hz, zero_r, zero_moves, gain_db}], morph_moves, q_exposes, carve_zeros_where, audition_on,
note }` — where `note` is the one DSP thing that makes it musical, not dead.
Then a short prose section: which of these foundations is the strongest base for an aggressive
DnB/bass product, and why, with the test that proves it.
