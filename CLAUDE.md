# CLAUDE.md

## What this repository is

A **Z-plane morphing filter engine**.

The filter is a serial cascade of **6 second-order IIR sections** — a 12th-order SOS cascade — float DSP throughout.

A preset ("**body**") is four authored coefficient keyframes placed at the corners of a 2-D control space: **MORPH × Q**.

At runtime the engine:

1. **bilinearly interpolates the stored coefficient words, linearly in their encoded space**,
2. **decodes** the interpolated words to float biquad coefficients,
3. applies **per-sample linear coefficient ramping** into the cascade.

The encoding space is **perceptually warped** (log-like in frequency and resonance). That warp is why linear interpolation of encoded words produces musical travel, and why **every intermediate wheel position is a real, playable filter**.

**The interpolation is never replaced with log/exp coefficient math. The warp lives in the encoding, not the interpolator.**

### Sample rate

One fixed internal sample rate: **39,062.5 Hz**. Sample-rate conversion happens at the plugin boundary.

The engine is **not multirate** and **not fixed-point**. The 16-bit stored words are a custom **minifloat storage encoding only**; all runtime math is float.

---

## Binary contract — `.body240`

```text
240 bytes = 4 corners × 6 sections × 5 little-endian u16 packed words.

Corner order: (M0,Q0), (M100,Q0), (M0,Q100), (M100,Q100).

Word row = minifloat-encoded [zero-mag, zero-r², pole-mag, pole-r², SCALE].

SCALE is pure broadband level (b0) and cannot change spectral contrast.

The runtime interpolates words, then decodes.
```

---

## Signal chain after the cascade

- **AGC leveller** owns output level.
- **SLAM off is exact unity.** The driven SLAM path uses −6 dB internal
  headroom with compensating output gain, preserving all body/pose differences.
- **SLAM** — final output saturation stage — sits after that calibration.
- A final sample-safety ceiling sits after MIX: identity below −0.5 dBFS,
  softly bounded to an exact −0.1 dBFS ceiling for abusive combinations.
- **CHEW** is the user-facing dynamic pole-radius distortion amount. **Q does not drive CHEW**; Q selects the authored body coordinate, while the resulting section levels naturally affect how strongly CHEW reacts.
- The legacy **BITE** interstage-saturator path remains in `trench-core/src/cascade.rs`, but the plugin leaves its drive at zero.

Constants: `trench-core/src/engine.rs` (AGC, SLAM) and `trench-core/src/desk_drive.rs`.

---

## Surface / stack

**Rust core crate** — the sole DSP engine and compiler: encoding, decoding, interpolation, cascade, stability certification. Exposed over a **C FFI**.

**C++ JUCE plugin (VST3)** — hosts the Rust core via the FFI; owns UI and parameter plumbing. UI layout is **data-driven and hot-reloadable**.

**Python toolchain** — authoring, analysis, packing, plotting. It delegates all packed math to the Rust core through the FFI and **never reimplements it**.

Paths: `trench-core/` (Rust core) · `plugin/` (JUCE VST3) · `tools/` + `pyruntime/` (Python toolchain) · `bodies/candidates/` (certified bodies awaiting ear verdict).

### Authority

The exact cascade topology, ramp constants, and encoder tables live in the **Rust source**. The code is the authority — **extend it, don't reinvent it**.

Where a numeric DSP constant is needed and not stated here, read it from the Rust source or the toolchain output. Do not type it from memory.

**Plot law**: all response plots use the fixed −60..+30 dB scale, dense packed-runtime evaluation, no autoranging.

---

## Execution

Inspect first. Make the smallest change that solves the problem. Run it.

Prove it with **runtime evidence on the real path** — packed bytes, true sample rate — not design math.

Write high-confidence code aggressively: the contracts above are fixed, so anything consistent with them can be implemented directly without staging or asking.

Lead with results.
