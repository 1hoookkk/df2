# DF2 Private Forge: Constructor Palette & Rendering-Grammar Adjudication

You are the independent DSP-tooling architect for DF2. Solve one problem only:

> Given the observed Morph-Designer Type 1/2/3 packed-word grammar and its
> measured behavior, specify the SMALLEST ORIGINAL constructor palette and the
> rendering-grammar architecture that lets a single author build 4–7 iconic,
> genuinely four-corner DF2 bodies — where abstract structure generators
> (physical models, Bark/ERB grids, explicit zero treatments) feed lawful
> pole/zero stages that compile into the locked 240-byte packed surface.

This is not a UX exercise. **Do not discuss GUI, layout, widgets, or
interaction.** Decide the math, the constructor set, and the data flow only.

Be blunt. If a proposed constructor is redundant, say which single primitive
subsumes it. If physical-model or Bark/ERB framing is the wrong abstraction for
this engine, say what replaces it and why. Do not protect a prior idea for
continuity. Make the decision.

## Deliverable

Write one patch-ready technical specification named:

`DF2 FORGE: CONSTRUCTOR PALETTE & RENDERING-GRAMMAR SPEC`

It must tell a coding agent exactly what to build next on top of the existing
v0 stage composer. Do not write code. Do not propose a broad roadmap. Do not
reopen the editing-surface debate (the root-domain six-lane composer is locked).

## Locked Runtime Facts (hard constraints)

- A body is exactly four corners `M0_S0, M1_S0, M0_S1, M1_S1`; each corner is six
  serialized DF2T biquads; each stage is five packed `u16` words; the artifact is
  exactly 240 bytes.
- One owner for packed math: decode is `c0=4·d0+d1, c1=d1, c2=4·d2+d3, c3=d3,
  c4=4·d4`; morph-first bilinear `u16` lerp before decode; this is `trench_core`
  and must not be reimplemented.
- A stage = one pole pair + one optional zero pair + section gain `g`. OBSERVED
  editable ranges that round-trip losslessly through pack→decode: freq 20 Hz–~17
  kHz, radius up to 0.999, **section gain g ∈ [0, 4.0] (hard ceiling; g>4 clamps
  in the packer and the plot lies)**.
- The identity/passthrough stage IS the chip pad row: kernel `[2,1,2,1,1]`.
- Authoring sample rate 39062.5 Hz.

## Observed Type 1/2/3 Behavior (the input evidence)

Measured by running the verbatim writers through the canonical decode and reading
the resulting pole/zero geometry and response (family 0, neutral modulation):

- **Type 1** — pole and zero CO-LOCATED at one frequency; gain splits their radii
  symmetrically; response is a clean resonant PEAK/NOTCH that returns to 0 dB on
  both sides (no pedestal). A surgical band.
- **Type 2** — pole sweeps; zero PINNED near Nyquist at low radius; response is a
  peak that rolls off above it — a SHELF / TILT / low-pass edge.
- **Type 3** — pole sweeps; zero PINNED deep-low (~57 Hz) at high radius (~0.99);
  response excavates the sub and rises into the resonance — a HOLLOW / sub-carve
  / high-pass body.
- All three are Morph-only: endpoint A and B are each duplicated across the
  Secondary axis, so historical Morph Designer collapses Secondary by construction.

Conclusion to pressure-test: the three types are not three constructors — they are
three ZERO TREATMENTS of one pole+zero actor (zero AT / ABOVE / BELOW the pole).

## Questions to Decide

1. **Smallest original palette.** State the minimal set of original primitives
   (clean-room, from public filter math — not vendor formulas) that reproduces
   every behavior in Types 1/2/3 and the multi-row foundations (cliff, window,
   opposed hollow). Argue whether the answer is exactly one parametric pole+zero
   actor with a zero-placement mode `{at, above, below, free}`, or whether
   additional irreducible primitives are required. Give each primitive's
   parameters, lawful ranges, default gain/normalization, and stability rule.

2. **Rendering grammar vs placement law.** Specify the data flow that separates
   WHERE poles go from HOW zeros render them:
   - physical-model sources (vocal tract / tube / modal) that emit pole sets;
   - Bark/ERB-distributed synthetic pole grids;
   - explicit per-pole zero treatments (the Type-1/2/3/free modes).
   Decide whether "Type N" should survive as a named render mode attached to each
   pole, or be dissolved into a continuous zero-placement parameter. Define how a
   placement law maps onto exactly six serialized stages and how it writes four
   DISTINCT corners (not a duplicated Secondary).

3. **Next adjacent writer.** From the observed adjacent class writers
   (`FUN_1802c5d60` fixed fallback rows; `FUN_1802c5e40` 16 six-word profile
   selector; `FUN_1802c5f10` 16 three-word mirrored profile selector;
   `FUN_1802c6020` independent three-row writer with signed spread controls,
   boundary folding, and radius clamps), name the SINGLE one worth extracting
   next and justify it strictly by which missing capability it adds to the palette
   above (e.g. structured multi-row spread / lawful contrary Secondary motion).
   Specify what to extract as behavior, not bytes.

## Clean-Room Boundary

The Type grammar and adjacent writers are recovered third-party behavior, for
STUDY only. Do not propose copying vendor coefficients, packed words, profile
tables, endpoint rows, or preset names into authored bodies. Every constructor
must be original parameter choices over public filter/acoustics math, and every
body must be judged through the real packed interpolation path.

## Output Format

1. Verdict (the palette decision, one paragraph).
2. The primitive(s): parameters, ranges, gain/normalization, stability rule.
3. The placement-law × zero-treatment data flow, mapped to six stages and four
   distinct corners.
4. The single adjacent writer to extract next, with the capability it adds.
5. First build slice: the smallest patch on top of v0, as an ordered task list.
6. Rejected approaches and why.
