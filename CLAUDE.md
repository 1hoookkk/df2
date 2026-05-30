# df2 — Claude working notes

## What this is
df2 is a **distortion engine**, shipped as two artifacts plus an internal runtime:
- **Player** (`juce-shell/`, JUCE/C++) — the consumer plugin. Loads a body and
  morphs it. **Transparent**: it adds nothing of its own beyond the body's filter +
  the engine's own saturation. No in-player modulation/LFO/sequencing.
- **Forge** (`forge/`, Rust/egui) — the private authoring bench. Not shipped.
- **`trench-core/`** (Rust) — the DSP core (Player + Forge + tools call it via FFI).
- `pyruntime/` (FastAPI) — internal authoring runtime/reference, not a third plugin.

## ⚑ AUTHORING METHOD — corners, poles, scoring (validated 2026-05-30; the way that works)
The overnight listen-loop (`dev/tmp/heaps.py`; the `trench-listen-loop` skill) settled
HOW to mass-author good bodies. Load-bearing — do NOT re-derive these every session:
- **4 DISTINCT corner STATES, not 2 states × Q.** The four corners must be four genuinely
  different filter states spanning **low↔high (Morph X) × open↔closed (Q/Y)**. If the Q
  axis only *sharpens* the same shape, the morph feels samey and the corners collapse to
  two states — the #1 mistake. Each corner = a different real state (4 real vowels = the
  vowel quadrilateral; 4 real cavities; 4 real tube states).
- **Meaningful poles only.** Every corner's poles sit on REAL table frequencies (Klatt
  formants, modal ratios, cavity/Helmholtz, tube partials). Never invent pole/zero
  numbers; never math-drift them off the real anchors (compressing/expanding a center
  destroys the meaning). Real freqs in → meaningful filter out.
- **Score = a GATE, not a ranker.** Dumb-but-robust hard gates (any fail → reject):
  finite across the morph×Q grid · doesn't blow up · not flat · **body alive** (low end
  within ~26 dB of peak) · **≥2 real resonant peaks** (culls lowpass slopes/shelves) ·
  perceptibly **moves OR has a rich emergent middle** · **produces sane audio through the
  real engine** (the un-fakeable gate). The number = perceptual **Bark**-domain movement +
  mid-richness (the moat) + peakiness — a pre-sort, never a verdict.
- **Select for DIVERSITY, never by highest score.** Ranking by score converges every pick
  on the one metric-optimal shape → "they're all too similar." Instead: gate by quality,
  then **farthest-point select** (max-min distance in the morph signature = M0+MID+M100
  Bark profile) so the batch is maximally *different from each other*.
- **The EAR picks.** The loop culls broken/boring/samey and hands ~16 diverse, audio-
  verified candidates; the human chooses. No scorecard is the boss.

## ⚑ ARCHITECTURE PIVOT (2026-05-30) — read this first
We are **pivoting the DSP engine** from the frozen 6-biquad / packed-minifloat path
to a **modern 14-pole Virtual-Analog (ZDF) architecture**. This is a deliberate,
owner-approved rebuild. **The v2 engine does NOT exist yet** — the code shipping
today is still the v1 biquad engine below. Do not hallucinate v2 as present; build
toward it.

Consequence (state it plainly, don't bury it):
- **X3 null parity RETIRES.** It was parity to the old E-mu chip path; v2 is a
  modern engine, not a chip emulation, so −95 dB-vs-X3 stops being the gate.
- **Every existing packed-minifloat body must be re-derived** into the v2 domain.
- This is a **from-scratch DSP project** (VA filters + oversampling + in-loop
  saturation + k1/k2 morphing), not a tweak.

### v2 target engine
1. **14-pole cascade — 7 second-order sections.** Two routings:
   - *Vocal/acoustic:* 1 resonant LP + 6 parametric/peak sections (Paths A/B).
   - *Synth "AllPole":* 7 resonant LP sections in series (~42+ dB/oct) for tearing
     sweeps (Path C). **AllPole is valid in v2 because** the in-loop `tanh` tames
     self-oscillation (a VA ladder) — unlike the v1 biquad engine, where pure
     all-pole is unstable noise.
2. **Zero-Delay-Feedback / TPT filters (Zavalishin), 64-bit double.** Analog-matched
   response to Nyquist, stable under extreme Q and fast morphing; kills the
   wide-band LF quantization noise the 8-bit hardware suffered.
3. **In-loop `tanh` waveshaper** inside each stage's feedback loop (back-to-back
   diodes) — self-distorting resonance = the "greasy" tearing harmonics.
4. **k1/k2 (ARMAdillo) snapshot morphing.** Design static corner frames offline,
   encode each pole as k1 (freq/log-octaves) + k2 (radius/resonance), interpolate
   k1/k2 between corners (bilinear 2D square / trilinear 3D cube), decode to b1,b2
   per sample: `b2 = 1 − e^−k2`, `b1 = −2 + e^−k2 + 4·e^−k1` (Ding & Rossum 1991).
5. **Pre-filter cubic soft-clip + AGC** on the secondary/Transform axis, driving the
   peaks (+22…+28 dB) into saturation = the squelch/knock.
6. **4×/8× oversampling** around the whole filter+distortion block, linear-phase FIR
   decimate — eliminates the aliasing that 14 moving poles + clipping generate.

### DIFF — interpolator (v1 frozen → v2 imposed)
- **v1:** bilinear lerp of **minifloat-encoded 5 kernel coeffs** (c0..c4), 4 corners
  × 6 stages; decode minifloat→coeff per block. The reverse-engineered E-mu morph
  (`FUN_1802c3d40`) is a **plain truncating u16 lerp — NOT k1/k2**. Nulls vs real X3
  at −95 dB.
- **v2:** lerp **k1/k2 (radius/angle decoupled)**, decode to b1,b2 per sample.
- **Same principle** (interpolate in a log domain, never raw coeffs). **Difference:**
  k1/k2 cleanly decouples radius from angle (no coeff cross-warp), at a per-sample
  decode cost. **Myth flag:** "the chip decoded k1/k2 at sample rate" is the 1991
  *paper's* design, not what our reversed binary does — v2 adopts it as a modern
  choice, not a fidelity claim.

### DIFF — saturation (v1 frozen → v2 imposed)
- **v1:** **SLAM** (Mackie-desk pre-saturator) → linear biquad cascade → **AGC table
  limiter with the `&0xF` wrap** (EmulatorX-verified grit). No in-loop nonlinearity,
  no oversampling.
- **v2:** **cubic soft-clip + AGC pre-filter** → ZDF cascade with **in-loop `tanh`**
  → **4× oversampled**. The **`&0xF` wrap grit is dropped** (cleaned by OS + tanh).
- **Myth flag:** the cubic/`tanh` curves are standard VA (Moog/Prophet), **not** the
  E-mu chip's actual saturation (which was the table-AGC + wrap). v2 chooses the VA
  character on purpose.

### FX-host layer (df2 is an insert FX, not a synth voice)
No oscillator, no MIDI note-on/velocity — so the engine must come alive on
*arbitrary* audio (808s, vocals, busses). **Mandatory hygiene** (build regardless of
engine version):
- **Parameter smoothing** — 1-pole on every control; without it, DAW automation on
  Morph/Q zippers and clicks. Non-negotiable.
- **Stereo frame processing** — two parallel cascades, L/R interleaved per sample, not
  buffer-then-buffer.
- **Wet/dry parallel mix** — a Z-plane filter *destroys* the signal; the producer
  blends the dry track back under it. The single most-used control on a destructive FX.

**Optional reactive modulation** (the FX-native replacement for note-on; OFF by
default):
- **Envelope follower** — the input's amplitude envelope (attack/release) drives
  Morph / Q / Transform. An 808 transient sweeps the morph; a vocal swell opens the Q.
- **Side-chain in** — aux bus; a kick's envelope sweeps the morph on the bass track.
- **BPM-synced LFO** — query host tempo; lock a Morph LFO to musical divisions.

**Fork resolved:** "transparent player" is relaxed to **transparent-*by-default***.
Every modulator ships OFF → df2 is a pure user/automation-driven filter out of the
box; the producer opts into reactivity. Modulation is never forced into the signal.

### v1 engine (what ships TODAY — until v2 lands)
A body is **4 corners × 6 stages × 5 coeffs** (`NUM_STAGES=6`, `cascade.rs`). 240-byte
packed body = 4 corners × 60 bytes (30 `u16`, minifloat). Shipping morph =
`Cartridge::interpolate` → `PackedCorners::interpolate_biquad` (packed bilinear,
`cartridge.rs`). Keep it working while v2 is built; do not delete it until v2 ships
and bodies are re-derived.

## Use case & range
- **Flagship: crazy 808s / bass / trap destruction** — knock, grit, saturation,
  speaker-blowing weight. Also vocals (vowel/talkbox), drums (crunch/glue),
  leads (metallic edge).
- The ceiling is violent on purpose, but **"too much" is a position, not the whole
  instrument** — the morph spans gentle saturation → full destruction.
- **The 4 corners must span intensity** (tame → violent), kin but ranged — never all
  maxed-aggressive, or it's a one-trick "destroy" box.

## The sound model (architecture-independent — survives the pivot)
- **Distortion IS the transfer functions** rendered through the engine's saturation —
  no clippers bolted between/after stages; the violence is in the corners + the drive.
- **Author the response surface first** — the full cascade magnitude over Morph × Q.
  Stages are bookkeeping, never the musical schema.
- **A body = 4 corners + a morph** (`M0_Q0`, `M100_Q0`, `M0_Q100`, `M100_Q100`);
  Morph (X) × Q (Y) is a snapshot interpolation of the corners.
- **The morph middle is the moat** — author the corners; the in-between *emerges*.
  The emergence is the value; it can't be copied by reading the corners.
- **Coherent middle needs KIN corners** (shared skeleton) + **slot registration**:
  pin a mover to a fixed stage slot with opposite endpoints (e.g. F2 rising / F3
  falling) and the lerp slides it — crossing/diverging trajectories are the moat; a
  per-corner fit can't produce them (the Talking-Hedz move).
- **All tricks are authoring-only** — wavefold/physics/ARMA/mesh/math happen in the
  Forge and **collapse to shipped corner frames**. The player never modulates.
- Authoring sample rate is **39062.5 Hz** (10 MHz / 256); shipping resamples.

## How presets are authored — the three valid paths
Pick one per body; never blindly guess a constellation.
- **Path A — Vocals/speech (Klatt).** Snap poles to formant targets F1–F5 + bandwidths
  (`tables/klatt_1980_*`, `vowel_formants.json` → `r_from_bw`); couple as a tract,
  thread zeros into the valleys *between* poles; **leave highs open** (no LP choke).
  The morph is the vowel journey; the middle vowel emerges (ah → [ay] → ee).
- **Path B — Acoustic bodies (area-function/physical).** Derive positions from a
  physical model (`tables/physical_models.py`, waveguide/area-function): randomize the
  *shape*, not raw freqs; raised-cosine constrictions; **authoring-only**, collapses
  to corner frames (`physical-corners` skill).
- **Path C — Aggressive synths (ROM splicing).** Use decoded ROM frames
  (`dev/tmp/rom_poles_zeros.csv`) as genetic material: splice/cross-pollinate real
  pole/zero frames, park zeros out of the way for naked screaming poles, drive into
  AGC overload = the squelch. *(Splice freely for authoring + personal/beta;
  commercial ship of E-mu-derived coefficients is a separate legal gate — attorney,
  not an authoring constraint.)*

### Anti-regression rules
- **Coupling, not EQ.** Never hand-tune isolated stages as uncoupled; never use
  fractional / sliding-real-pole math for synth scream (real poles don't ring).
- **Mud rule.** Never widen/lower Q to fix bass mud (broad low-Q *is* the mud) — use
  razor-sharp low poles + the **Balance Rule** (pair low weight with a stronger
  treble peak).
- **"Q adds peaks" / dormant poles.** Park some poles damped (low radius) so they read
  flat; the Q/secondary axis raises their radius → peaks sprout. Allocation of the
  existing budget, not stage-role tuning.
- **No unconstrained fitter.** A fit must target a deliberately-designed curve with
  kin + registration held; the generate-and-cull factorizer stays retired.

## Surface rules (non-negotiable)
- **The engine is machinery — never show it.** No coefficients, poles/zeros, z-plane,
  "radius", k1/k2, ARMAdillo, or "E-mu/EMU/Morpheus" anywhere a user/buyer/competitor
  sees. (Fine in internal code comments + Forge debug.) The hero is the **sound's
  shape** and its **named characters**.
- **The chassis PNG + code-painted overlays are the identity.** Never propose
  pure-code/egui/WebView or deleting the chassis. Palette authority = `TrenchStyle.h`.
- Surface the budget as **named actors**, never "stages/slots/poles."
- In Forge, magnitude plots come first; stage plots are debugging.
- **Plots shown to Tyson = simple magnitude curves** (dB vs log Hz, overlaid). Morph×
  frequency spectrograms / pole-track surfaces are Claude-internal analysis only.

## Working notes
- Forge is the bench; the player is the instrument. Authoring UI never goes in the
  player; playing UI never goes in the forge.
- **Dev loop: Standalone or AudioPluginHost, never FL** (FL caches the DLL until full
  exit). Verify by ear through the shipped engine, not just unit tests.
- When fits differ wildly across adjacent inputs, suspect the input, not the algo.
- `STATE.md` is the worklog — read it first, match its current form. `NOW.md` holds
  the current arc / DO-NEXT. Every code change updates `STATE.md` in the same commit.
- **Use only truth.** Pasted external content recurs that reintroduces wrong hardware
  claims (k1/k2-at-sample-rate as chip-fact, cubic AGC as chip-fact, 8-corner/30-byte
  layouts). When a doc contradicts the code/RE, the code wins — flag it, don't enshrine
  it. The v2 pivot is a *forward design choice*, kept honest by the diffs above.
