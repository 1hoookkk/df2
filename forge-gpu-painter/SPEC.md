# TRENCH FORGE — authoring surface spec v3 (Rust GPU painter)

**This document supersedes `forge-web/FORGE_DESIGN_BRIEF.md` and the layout/interaction
tiers of `forge-web/DESIGNER_UX.md`.** Tier-1 invariants and the measured Tier-2 defaults
from those documents are absorbed here unchanged. The web designer surfaces remain as
inspection tools; the product authoring surface is `forge-gpu-painter` (eframe/wgpu,
fully custom painted, trench-core linked in-process).

Evidence grades: **OBSERVED** (proven by execution) · **INFERRED** · **UNKNOWN**.

---

## 1. The object and the one law

A body = 240 bytes = 4 corners × 6 second-order sections × 5 packed u16 minifloat words.
Each section is a conjugate pole pair + conjugate zero pair (always both). Corners:
C0 = low·Q0, C1 = high·Q0, C2 = low·Q100, C3 = high·Q100. The runtime interpolates the
**log-encoded words** (integer u16 lerp, morph first then Q), so the interior diverges
from any continuous model by up to ~20 dB (OBSERVED). Consequences, non-negotiable:

- **Every curve on screen is computed from the packed words through the engine's own
  word-lerp.** The painter packs via `trench_core::compiler::pack_body` (the one
  CONSTRUCT encoder) and decodes the bytes it just packed. Plot == engine by
  construction — there is no second code path to drift.
- Hard limits (format + compiler): pole r ∈ [0.5, 0.9992] UI / clamped inside the unit
  circle by the compiler; zero r ∈ [0, 0.9995]; gain ∈ [−26, +12] dB packed linear;
  conjugate pairs only; `zero_on = 1` always (the all-pole branch rolls off −12 dB/oct —
  "no notch" = zero masked near the pole or low r_z).

## 2. The platform decision (why Rust changed the plan)

The browser plan assumed packing was expensive (WASM round-trips), so solvers were
specced as "continuous model at gesture rate, true runtime on release." **That plan is
obsolete.** In-process, a full forward pass — params → `pack_body` → 240 bytes → word
lerp → |H| over a 40–480-bin window — costs well under a millisecond (OBSERVED: the
curve-grip solver runs ~14 forward passes per pointer-move at frame rate, debug build).

**Rule: no solver in this product ever optimizes a surrogate.** Anything interactive is
solved against the true packed runtime, in-process. The ~20 dB interior divergence makes
any continuous-model preview a lying drag — the curve would track the finger, then snap
on release. With the encoder in-process the surrogate is unnecessary; the honesty gap is
closed by architecture, not by a disclaimer.

## 3. The two grips

**Grip 1 — per-feature handles (primary).** Filled circle = pole pair, ring = zero pair,
sitting on the section's own contribution curve. Drag horizontal = frequency (quantize
rails apply), vertical = radius (pole up = resonant, zero down = deeper notch),
Alt = per-frame gain, wheel = pole radius, Shift = fine. This grip is structure-
preserving by definition and teaches the instrument. (BUILT, OBSERVED.)

**Grip 2 — the curve grip (edit the sum; the stages follow).** The cascade in dB is the
sum of six section responses; wherever skirts overlap no single handle owns the
composite. Grab the combined curve anywhere that isn't a handle: a damped Gauss-Newton
solver moves the **K = 2 nearest unlocked sections** in root domain
[log2 f_p, ln(1 − r_p), gain dB] to chase a Gaussian target bump under the finger.
(BUILT for docked corners, OBSERVED.)

Constraint system (this is what makes the inverse problem usable — the solver may only
move what is allowed to move):

1. **Locks are the regularizer.** Locked sections (anchors) are excluded from the
   solver, from fits, and from corner tools. Parked zeros are never touched by the
   curve grip at all — a traveling or deepening zero is always a deliberate manual act.
2. **Minimum motion.** Tikhonov pull toward the grab state, frequency pinned hardest
   (λ_f > λ_r > λ_g), so the solver prefers radius/gain over re-placing poles.
3. **Trust region** (±0.5 per step in normalized params): sections never swap roles
   under a drag. Section index is the morph pairing — a role swap at one corner wrecks
   the interior, so pairing preservation is a hard property, not a preference.
4. **Visible motion.** Whatever the solver moved shows as moved handles, never a
   silently mutated body. The weighted residual vs the target prints live in dB.
5. **Docked first.** The grip currently requires MORPH and Q docked at 0/1 — the solve
   is exact there and the mental model is simple. The interior grip (solve corner moves
   so the *interpolated middle* lands where pulled) uses the same machinery and unlocks
   after the docked feel is proven. It is the only direct grip on the emergent interior
   and the interactive front-end of the surface optimizer (§5).

## 4. Solver doctrine (the research, distilled)

Searched the current landscape (2026-06). The **slice problem** — fit a static magnitude
target with a biquad cascade — is a mature, solved field twice over. The **surface
problem** — fit a 2D morph surface through a log-word interpolator — appears nowhere.
That asymmetry drives the sequencing.

- **Classical capture: benchmark AAA against vector fitting before committing.** AAA
  (barycentric rational approximation, greedy support points, no initial pole guess,
  ~40 lines) superseded vector fitting as the default; its known weakness is **noisy
  data**, where approximation-based methods (VF) do better. Our captures are real
  measurements — run both on the dirtiest reference capture and keep the winner.
  Pipeline either way: magnitude → minimum phase (cepstral) → complex fit → poles/zeros
  → project into format (order 12, conjugate pairs, radius clamps, six sections) →
  **polish closed-loop through the packed runtime**. That last step is ours alone; no
  paper has a bit-exact shipped-engine null to refine against.
- **The root domain is independently validated.** The differentiable-DSP literature
  converged on frequency-sampled biquad cascades (evaluate |H| at sampled frequencies —
  literally how our plot works) and on **stability via parameterization** (SVF-style
  frequency/damping params) rather than constraint penalties. Our (f_p, r_p, f_z, r_z,
  gain) control surface is the same move. Their failure mode (deep cascades N ≥ 64
  destabilize training) does not apply at N = 6.
- **No neural warm start needed for the curve grip.** Six sections under lock masks is a
  small Gauss-Newton problem at gesture rate (OBSERVED — shipped). IIRNet-style
  amortized prediction is a later luxury for draw-the-target capture, not a
  prerequisite.
- **The surface optimizer is an unclaimed combination of mature parts.** The packed
  chain — corner params → log words → bilinear word blend → decoded coefficients → |H|
  over a (morph, Q) grid — is differentiable almost everywhere (log-encode smooth,
  blend linear, magnitude evaluation standard). A surface-level loss with gradients
  through that chain is buildable from published components; nobody has assembled them
  across a morph dimension. Sequenced after the bank proves demand (≥ 3 banked bodies).

## 5. Topology: never re-architect the runtime

The "mature" way to build a morphing filter — interpolating LSFs or lattice
coefficients, as speech codecs have for forty years — guarantees a smooth, predictable
interior. **That is exactly the wrong outcome.** The 20 dB divergence, the cancellation
cells, the collapsing columns, the corner blooms — the emergent interior characterized
across the 50 reference bodies — comes from linear interpolation of log-encoded
direct-form words. A predictable interior is a crossfade; ours is an instrument.

Invention happens on the **authoring side only**: parameterizations (root domain,
locks/anchors, lawful paths, scopes) layered over a fixed runtime. Derived topology
labels (resonant SOS, pole-zero resonator, near-allpass, …) stay readback vocabulary —
information about root geometry, never a choice and never a quality judgment.

## 6. Format restriction: aggressive yes

- **Identity:** every verified asset — byte-null, corridor, 17×17 audit, reference
  fingerprints, plot==engine — hangs off this format. A second format forks the
  evidence chain and orphans half of it.
- **Headroom:** free corners, secondary-responsive zeros, drive routing, section
  re-pairing, ±25 dB per-frame gain rides are all in-format and mostly territory no
  reference ever used. Breaking format buys nothing we can't already reach.
- **Discipline:** the format is the regularizer that turns research output into
  shippable bodies. An unconstrained fit returns whatever order it likes; forcing
  order-12 conjugate-pair radius-clamped solutions is what turns "a match" into a body.

Revisit condition (the only one): a specific authored intention repeatedly failing to
express in-format — a seventh section, real-axis poles, more than bilinear corners.
That is a format-v2 project with its own measured corridor and harness, sequenced after
the bank proves the demand. Never a quiet extension of this tool.

## 7. Workflow: corners-first, measured middle (LOCKED, Tyson 2026-06-10)

1. Author the four corners as the intended states (corner chips / keys 1–4; edit scope
   = this corner / this frame / all corners).
2. Probe the interior through the real runtime: the surface map (morph × Q max |H|),
   the morph-sweep heat map, and the live curve at any (morph, Q).
3. Repair by re-editing corners — scope + locks express the orthogonal moves (common,
   morph-differential, Q-differential); root→word nonlinearity is absorbed by always
   measuring through the engine.
4. Verify the pin states: center (m50 q50) + the four 25/75 quarter states — printed
   under the surface map; four general-position samples pin the bilinear surface.
5. The ambient 17×17 audit (stability + max |H|) re-judges continuously; the lamp is
   the standing verdict. Unstable cells render red at their coordinates.

## 8. Design space: all the type families

The taxonomy to cover (clean-room: the manual's category descriptions, never its
coefficients): low-pass sweeps · high-pass · band-pass · parametric EQ boost/cut ·
vowel formant morphs · notch combs / phase-shifter · flanger · resonant peaks ·
wah/distortion-tone hybrids. Order 2–12 = how many of the six sections are enabled.

Seeds exist for each family (SEED menu) as **start states, not presets**: type
templates are textbook constructions; vowel pairs come from Peterson-Barney formants
with radius from bandwidth (r = exp(−πB/SR)); tube partials and metallic mode ratios
come from `tables/*.json`. LPC fit: drop a WAV → trench-core LPC poles + spectral
valleys into the low (Shift: high) frame, locked sections held.

## 9. Rule tiers (carried over)

- **Tier 1 — invariants:** format + stability physics (§1 limits); every curve through
  the packed runtime; 17×17 audit before anything enters the bank; clean-room.
- **Tier 2 — measured defaults, one gesture to override:** zeros boot parked and
  Q-invariant (the reference set's numerator is secondary-invariant — median zero
  radius change +0.0000 across 193 sections); Q-axis = pole radius toward the rim
  (~0.999); quantize defaults to the measured-resonance table. Off-corridor moves are
  available novelty, never faults.
- **Tier 3 — taste/ergonomics:** layout, colors, glyphs, drag feel — hypotheses until
  Tyson's hands vote. Current palette: near-black ground, white truth curve, per-section
  hues, ice for interaction, ember for audit-in-progress, red reserved for instability.

## 10. Pipeline (end-to-end, all BUILT)

`pack_body` bytes → live plot/maps → ambient audit → **BAKE**
(`dev/tmp/forge_gpu_painter/<name>.body240` + source JSON) → **AUDITION**
(`Documents/TRENCH/authoring_slot.json`, compiled-v1 packedWords — hot-reloaded by the
plugin's Forge Audition slot) → keep/kill by ear in the plugin → bank entry with
Tyson's verdict (KEEP-into-bank wiring from this surface: not yet built).

## 11. Sequencing

| # | item | status |
|---|---|---|
| 1 | custom-painted surface, handles, locks, undo, seeds, audit, bake/audition | **BUILT (OBSERVED)** |
| 2 | curve grip, docked corners, true-runtime Gauss-Newton | **BUILT (OBSERVED)** |
| 3 | in-app audio (engine → cpal, AGC + saturation chain = the product chain) | next |
| 4 | interior curve grip (corner moves so the interpolated middle lands) | after 3 proves the feel |
| 5 | capture fit: AAA vs vector fitting benchmark on the dirtiest reference, then draw-the-target | after 3 |
| 6 | KEEP → bank artifacts from this surface (17×17 + byte provenance recorded) | with first keeper |
| 7 | differentiable surface optimizer (gradient through the packed chain, surface loss) | own project; bank ≥ 3 first |
