# Reverse-engineering Dave Rossum's Z-plane method (primary sources)

Clean-room STUDY of public primary sources — Rossum patent US5170369 (1992),
the Mo'Phatt operation manual (E-mu, public product manual), and the Dillusion
"EMU Peak/Shelf Morph" tutorial (public web tutorial, 2005). Method/process only;
no coefficients, bytes, names, or tables copied into shipping bodies.

## There are TWO methods, and they RE very differently

### 1. The MORPH / ENGINE method — FULLY recovered, confirmed against the patent

US5170369 "Dynamic Digital IIR Audio Filter and Method" (David P. Rossum, E-mu,
Dec 1992) **is the engine we ship.** Verbatim from the patent:

- **"16 bit coefficients are adequate for good frequency resolution."** → the
  packed-word minifloat.
- **"logarithmic interpolation of the coefficients is required to produce audibly
  meaningful sweeps. This is accomplished not through true logarithmic
  interpolation, but rather through linear interpolation of approximately
  logarithmically encoded coefficients."** → the minifloat is the log-encoding;
  the engine LINEARLY interpolates the log-encoded words. This is exactly what we
  RE'd as `FUN_1802c3d40` / `pyruntime.packed_interp`.
- **The morph formula, verbatim: `C(x) = Ca + x(Cb - Ca)`, x from 0 to 1**, "two
  coefficients each for poles and zeros." → Frame A coeff Ca, Frame B coeff Cb,
  x = Morph. Our packed bilinear lerp IS this formula.
- **"The poles of the filter are assumed to be, for important cases, near zero
  frequency and near unity radius."** → why the log-encoding exists, and why the
  iconic corridor sits at maxR 0.985–0.9997 near the rim. The encoding is built
  FOR resonant poles near self-oscillation.
- Sweep dynamics: the interpolating variable x is given a **destination + approach
  time (powers of 2, min 32 samples)**, increments per sample, clamps. → the glide.

**Conclusion:** our engine is not "like" Rossum's — the patent describes our packed
runtime to the formula. The RE of the morph is COMPLETE and PROVEN. (Confirms
memories `hedz-morph-interp-is-linear-u16`, `one-true-encoder-compile-body`,
`morpheus-source-validation`.) Why the morph middle is emergent and un-reproducible
by continuous kernel interp: linear-in-log-space is nonlinear in coefficient space.

### 2. The TYPE-AUTHORING method — recoverable for PARAMETRIC types, hand-made for the rest

A body = **two complete filter "frames" (A, B), morph interpolates between them**
(manual p.106: "we start with two complex filter types and interpolate between them
using a single parameter, the Morph"). The question is how the FRAMES were made.

**(a) Parametric types — Peak/Shelf Morph (Millennium / filter_type 0): FULLY
recoverable.** The Dillusion tutorial documents the exact authoring parameters,
two frames each:
- **FREQ** — corner/band frequency (its role depends on SHELF).
- **SHELF** — a continuous filter-TYPE coordinate: **−64 = lowpass, 0 = mid shelf,
  +63 = highpass**, values between blend the types (−32 = 50% LP + 50% midshelf).
  This is the key: SHELF is a continuous LP↔shelf↔HP morph parameter.
- **PEAK** — gain/volume of the peak filter per frame (sets relative frame levels).
- Morph (FilFreq) interpolates frame A → frame B; FilRes (Q) = Q on the sweep +
  saturation harmonics.
- Documented example is a **DnB reece stab** (Optical/Grooverider/Dillinja era):
  Frame A {Freq 246, Shelf −50, Peak −24 dB} → Frame B {Freq 4488, Shelf 30,
  Peak +1.5 dB}. Set Shelf from −64 (not lower) to avoid pops when saturating.

  → This is a clean, implementable algorithm: (Freq, Shelf, Peak)_A → _B → coeffs.
  It is the **bass/reece workhorse type**, and its method is fully documented in
  public sources. We can build an ORIGINAL parametric Peak/Shelf compiler (our own
  Shelf-blend DSP, original frame values) — clean-room.

**(b) Complex types — the 12th-order VOW / EQ+ iconic ones (TalkingHedz, AceOfBass,
the vowels): NO single algorithm.** The manual states it plainly: **"Because
creating the complex filtering is difficult and very time consuming, we have
created 50 different filters and installed them permanently in ROM."** The
type-list entries are descriptive frame-PAIRS, not formulas:
- AceOfBass: "Bass-boost to bass-cut morph" (2 EQ frames)
- AahAyEeh: "sweeps from Ah through Ay to Ee … Q varies the size of the mouth cavity"
- TalkingHedz: "'Oui' morphing filter. Q adds peaks."
- Eeh-To-Aah: "Q accentuates 'peakiness.'"

  → The "method" is: pick two meaningful complex filter postures (a vowel, a
  bass-boost EQ, an LP) as Frame A and B from real acoustic targets (formant
  tables, EQ shapes), morph between. The frames were hand-designed by ear /
  measurement. This CONFIRMS the earlier conclusion (no recoverable algorithm for
  the complex iconic types) — now backed by E-mu's own words.

## What this gives us (actionable)

1. The morph engine is settled — we ship Rossum's patent. Stop re-litigating it.
2. **Peak/Shelf Morph is a clean, documented, recoverable parametric type** — the
   one place a real E-mu authoring algorithm exists, and it's the DnB/bass/reece
   workhorse. Building an original parametric Peak/Shelf compiler (2 frames ×
   Freq/Shelf/Peak) is high-value for the bass lane and clean-room (public sources,
   our own DSP).
3. The complex VOW/EQ+ types stay frame-pair hand-design from acoustic targets —
   which is the "two coherent postures, morph between" pattern, simpler than the
   6-section composition the null-grammar attempted.
