# Fitter — declare the shape, solve the poles/zeros

The cure for hand-wrestling 12 interacting variables: you **declare a target**,
an optimizer places the X's and O's. Two fitters behind one "Auto-Fit Target"
button. Academic rails below are **verified real** (standard DSP canon, correctly
attributed by Gemini this time — unlike the rejected "screamer class" theory).

## 1. Audio fit — vowels / acoustics (we mostly have this)
Drop a vowel WAV → extract its formants → snap to actor poles.
- **LPC envelope** → roots = poles. Levinson-Durbin solve, `numpy.roots`, sort by
  angle (frequency), take the top-N resonant pairs as actor lanes.
- This is **all-pole** — which **matches our validated vowel law (zeros banished)**.
  Do NOT bolt DC zeros onto fitted vowel poles (TESTED: kills the body). Use zeros
  only for a deliberate notch (nasal, shelf, mask/unmask).
- Wrap the existing `tools/fit_two_audio_arma.py` as the endpoint.
- **Rails:** Makhoul (1975), "Linear Prediction: A Tutorial Review," *Proc. IEEE*
  63(4); Levinson-Durbin recursion.

## 2. Macro-shape fit — synthetic / analog (new)
Declare a curve ("36 dB/oct LP @ 800 Hz", a shelf, a brick wall) → solve 6 biquads.
- **Bounded Levenberg-Marquardt** via `scipy.optimize.least_squares`.
- **Objective: error in log-magnitude (dB) on a log-frequency grid** — so the fit
  prioritises low/mid over the extreme top (matches how the minifloat words and
  the ear both weight things).
- **Constraints (guardrails so it doesn't explode):** pole radius `0 ≤ r ≤ 0.985`;
  **lock the foundation section** (e.g. section 6 held at the 60 Hz anchor);
  keep `f1<f2<f3` for vocal targets.
- **Rails:** Deczky (1972), "Synthesis of recursive digital filters using the
  minimum p-error criterion," *IEEE Trans. Audio Electroacoustics* (the seminal
  direct pole/zero magnitude fit); Steiglitz-McBride (1965) iteration (robust IIR
  coefficient fit).

## 3. Stable interpolation — the morph layer
Why the morph interior doesn't blow up, and the domain to reason in:
- **Line Spectral Frequencies / Pairs (LSF/LSP)** — Itakura (1975). Linearly
  crossfading raw biquad coeffs `(a1,a2)` can go unstable mid-morph; LSFs stay
  inside the unit circle. E-mu's log-compressed minifloat-word interpolation is
  the hardware cousin of this. The fitter's cost should weight **logarithmically**
  because the roots map logarithmically.
- **Implementation reference:** Julius O. Smith III (CCRMA), *Introduction to
  Digital Filters* — the modern code blueprint.

## 4. Source / law references (already in use)
- Klatt (1980), *JASA* 67(3) — cascade/parallel formant synth; all-pole, nasal =
  the one zero. (Our `tables/klatt_1980_*`.)
- Fant (1960), *Acoustic Theory of Speech Production* — the source-filter founding.
- Story & Titze MRI area functions — to make `physical-corners` vowels canonical.

## Wiring
- Small **FastAPI/Flask** endpoint wrapping (1) and (2); returns a JSON of 6
  pole/zero positions (Hz, radius) per corner.
- `zedit.html`: an **"Auto-Fit Target"** button → POST target (WAV or curve spec)
  → server returns positions → UI snaps the X's/O's → WASM redraws the Bode plot.
- Then hand-drag only to add dirt / set a collision / mask-unmask.

## Grading
- **OBSERVED:** the all-pole vowel law, zero-unmask, pole-collision, the
  body/foundation behaviour (this session, through the engine).
- **REFERENCE (real, unverified-in-engine-here):** the academic methods above —
  standard and correctly attributed; implement and verify against the plot.
- Build order: audio fit first (we have the pieces), then the scipy macro fitter.
