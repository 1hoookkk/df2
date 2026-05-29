# df2 — Claude working notes

## What this is
df2 is a **distortion engine**, shipped as two artifacts:
- **Player** (`juce-shell/`, JUCE/C++) — the consumer plugin. Plays and morphs a
  body. **Transparent**: adds nothing of its own. No in-player modulation/effects.
- **Forge** (`forge/`, Rust/egui) — the authoring/capture bench. Where bodies are
  designed, captured, fitted, auditioned. Not shipped to consumers.
- `pyruntime/` (FastAPI) — internal authoring runtime/reference, not a third
  plugin. See `pyruntime/CLAUDE.md` for its Forge-vs-Compiler boundary.

## Use case & range (what it's *for*)
- **Flagship: crazy 808s.** This is an 808 / bass / trap destruction engine first
  — knock, grit, harmonic saturation, speaker-blowing weight. *Speaker Knockerz*
  names the intent. Also: vocals (vowel/talkbox character), drums (crunch/glue),
  leads/synths (metallic edge).
- **The ceiling is violent on purpose, but "too much" is a position, not the whole
  instrument.** The morph is what gives it range: sit anywhere from gentle
  saturation to full destruction.
- **Therefore the 4 corners must span intensity** — not all be maxed-aggressive,
  or it becomes a one-trick "destroy" box. Kin *and* a range from tame → violent.

## The sound model (musical expectations)
- **Distortion IS the transfer functions.** Character lives in the corners (the
  filters) rendered through the faithful chip path, *including its saturation*.
  No clippers bolted between/after stages — the violence is in the corners.
- **Author the response surface first.** The creative truth is the full cascade
  magnitude over Morph × Q: low/body/bite/air balance, peaks, notches, slope,
  centroid, and how those move. Stage rows are the packing solver's bookkeeping,
  never the musical schema.
- **A body = 4 corners + a morph.** Corners are `M0_Q0`, `M100_Q0`, `M0_Q100`,
  `M100_Q100`. Morph (X) × Q (Y) is a **bilinear interpolation** of the 4.
- **The morph middle is the moat.** Author the 4 corners; the in-between
  **emerges** (read-only bilinear average). The emergence is the value — it can't
  be copied by reading the corners.
- **Coherent middle needs KIN corners.** The 4 must share a skeleton (like the
  ROM frames) or the middle mushes. 4 distinct *whole* corners (the ROM contract)
  — never per-stage / per-section tuning (that path is the trap).
- **All tricks are authoring-only.** Wavefold, physics, ARMA, modulation, math —
  every trick happens in the forge and **collapses to one shipped corner**. The
  player never modulates.
- Authoring sample rate is **39062.5 Hz** (10 MHz / 256). Shipping resamples.

## How presets are authored (THE canonical path — non-negotiable)
The E-mu ROM stores each filter as **240 bytes verbatim** (4 corners × 6 stages
× 5 `u16`) — no descriptor, no runtime compiler; the chip just plays four
hand-authored frames. **df2 authors at that exact level: bold, direct,
four-frame placement.** This is the ONLY authoring path.
- **Place poles directly; do NOT fit.** Use `tools/corner_words.py`
  (`bp`/`formant`/`notch`/`hedz_body` → `corner_words` → verbatim 240 bytes).
  The factorizer / "draw a curve and fit it" / `make_class_bodies` /
  `sweep_roster` generate-and-cull path is **RETIRED for authoring** — it drifts
  poles off their target, parks random near-Nyquist poles, and skips zero-pairing.
- **Poles on REAL frequencies + real bandwidths** (`tables/`: vowel formants,
  `klatt_1980_bandwidths.json` → `r_from_bw`, tube/modal/harmonic). Every pole is
  **zero-paired** (the Rossum `bp` structure; pure all-pole is unstable here).
- **The MORPH is a BOLD spectral journey** — poles travel far (sweep top↔bottom,
  vowel-migrate, open↔closed). Timid nudges are the failure mode; the ROM sweeps
  the whole constellation. Near-Nyquist poles are a deliberate bright extreme, not
  an artifact.
- **Q is a FREE chosen character per body** (resonance / vocal-stress / shelf /
  notch-depth) — confirmed against the Morpheus source. NOT universally "sharpen".
- **Scale via the `forge-corners` skill** (parallel subagents, one bold body each).
  Audition the **middle** through the shipped engine; the ear picks keepers, no
  scorecards.

## The encoding (strict — this is the real one)
A body is **4 corners × 6 stages × 5 coefficients** (`NUM_STAGES = 6`,
`NUM_COEFFS = 5`; `trench-core/src/cascade.rs:3-4`). It exists in two forms:

**1. Kernel coefficients `c0..c4` — the working/shipping form.**
- `compiled-v1` JSON: `EncodedCoeffs { c0, c1, c2, c3, c4 }` per stage
  (`pyruntime/encode.py`, `trench-core/src/cartridge.rs`). DF2T biquad kernel
  coefficients (`raw_to_encoded`: resonator path + lowpass path).
- The **shipping morph is a bilinear lerp in the PACKED (minifloat/ARMAdillo-encoded)
  domain**, NOT over decoded coefficients. `Cartridge::interpolate(morph, q)`
  (`cartridge.rs:314`) dispatches to `PackedCorners::interpolate_biquad` whenever
  `packed = Some(_)` — every body on the 240-byte path. The decoded-f64 bilinear
  (`interpolate_legacy_stages`) is **legacy fallback only**; no shipping body uses
  it. Confirmed against the Morpheus source: the hardware "linearly interpolates the
  coefficients in the encoded space at the sample rate." Boost interpolates the same
  way (`interpolate_boost`).

**2. Packed-16 minifloat — the native ROM word format.**
- `trench-core/src/minifloat.rs`, behind the `packed_interp` feature. **5 packed
  `u16` words per stage** (`PackedStage = [u16; NUM_COEFFS]`). A raw ROM corner
  block is **240 bytes** = 4 corners × 60 bytes, 30 `u16` little-endian each,
  stage-major (`from_rom_bytes`). `decode`/`encode` convert word ↔ f64.
- The packed domain **IS** the shipping interpolation domain (see above) — this is
  the E-mu/ARMAdillo design: linear interpolation of the log-encoded words gives
  perceptually-meaningful sweeps. `lerp_u16` (int16-truncate the delta then add base
  — the E-MU/MSVC `FUN_1802c3d40` formula, wraps, no clamp) is the exact-E-mu
  truncating variant; the shipping path is `interpolate_biquad` (packed bilinear).
  Words derived from coefficients are "derived-packed-canonical" (`from_corner_data`),
  not claimed bit-exact to E-mu.

**Not part of the encoding:**
- **There is NO "Glyph12" / feature fingerprint.** That name is a discarded
  discussion title, not code. Do not look for or invent it.
- **Character is derived, not stored.** Brightness/complexity/etc. are computed
  from the frequency response (`pyruntime/analysis.py → body_profile`:
  `spectral_tilt_db`, zero-crossing count, morph-trajectory distance), never held
  in the encoding.
- **Response targets are stored outside the cartridge contract.**
  `specs/response_target.v1.schema.json` is the design/input schema. A compiled
  cartridge may include `authoringModel=response-surface-v1` and `responseAudit`
  as provenance, but `packedWords` remains the coefficient authority.

## Surface rules (non-negotiable)
- **The encoding is machinery — never show it.** No coefficients, poles/zeros,
  z-plane, "radius", or "E-mu/EMU" anywhere a user/buyer/competitor can see. The
  hero is the **sound's shape** and its **named characters**, never the math.
- **The chassis is the identity.** Keep the PNG chassis + code-painted overlays.
  Never propose deleting it or going pure-code/egui/WebView for the player.
- Surface the abstracted budget as **named actors**, never "stages/slots" or
  individually-designed filters.
- In Forge, magnitude plots and response-audit numbers come first; stage plots are
  debugging for the final factorization.

## Working notes
- Forge is the bench; the player is the instrument. Don't put authoring UI in the
  player or playing UI in the forge.
- When fits differ wildly across adjacent inputs, suspect the input, not the algo.
- `STATE.md` is the worklog — read it first, match its current form.
