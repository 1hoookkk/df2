# SPEC.md

Frozen specification. Math, topology, format. Patent-faithful to Rossum
1992 (US5170369).

## Cascade

12 stages, serial DF2T biquad. 6 active stages (interpolated from
cartridge) + 6 passthrough.

Each stage stores kernel-form coefficients `[c0, c1, c2, c3, c4]`,
double-precision.

DF2T per-sample math (exact):

```
y  = c0 * x + w1
w1 = c1 * x − c3 * y + w2
w2 = c2 * x − c4 * y
```

Transfer function: `H(z) = (c0 + c1·z⁻¹ + c2·z⁻²) / (1 + c3·z⁻¹ + c4·z⁻²)`.

Denominator math: `c3 = a1 = −2R·cos(θ)`, `c4 = a2 = R²`, where R is
pole radius and θ is pole angle.

## Interpolation

4-corner bilinear interpolation in c-domain (coefficient space), not in
pole/zero space. Corners: M0_Q0, M0_Q100, M100_Q0, M100_Q100.

Order: Q first, then morph (Q resolved within each morph column, then
columns linearly mixed by morph).

Per-sample coefficient ramping over 32-sample control blocks. Linear
delta per sample.

## Sample rates

- **Authoring**: 39062.5 Hz (E-mu hardware clock: 10 MHz ÷ 256). All
  frame coefficients are computed at this rate.
- **Runtime**: 44100 Hz. The plugin runs at this rate. Sample rate
  shift is baked into pole-angle calculation at authoring time, not at
  runtime.

## Cartridge format

`compiled-v1`. JSON. One body = 4 keyframes (one per corner) × 12 stages
× 5 coefficients + global boost. See `cartridge.schema.json`.

## Stability

`y`, `w1`, `w2` checked for finite after each sample. Non-finite values
flush the stage (zero state and ramp), set instability flag, return 0.0.
No AGC. No soft clipping in cascade.

## Hard bans

- No cascade topology changes.
- No interpolation order changes (Q-first, then morph, in c-domain).
- No cartridge format changes.
- No gain baked into `c4`.
- No RBJ cookbook formulas in the character path.
- No compensation layers to rescue bad math.
