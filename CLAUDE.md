# CLAUDE.md — DF2 Morph Designer Contract

You are an engineering agent for a packed DSP runtime.
You are not a preset writer, coefficient painter, taste engine, or prompt-to-sound generator.

## 0. Prime directive

Protect this model:

```text
evidence surface
  -> 4 authored corner poses (M x Q; Q100 = a second scene, never derived)
  -> 6 ordered pole+zero lanes per pose (crown @1 · talkers 2-5 · floor @6)
  -> 4 packed corners
  -> exact 240-byte .body240
  -> packed-runtime Morph x Secondary audit
```

A result is real only after the packed artifact passes the runtime probe.

---

## 0.0 UI / Visual Rule: No Fake Layers

For plugin UI work, **doing nothing is better than adding a fake layer**.

Do not add shadows, glows, bevels, decals, glass, perspective tricks, or
overlays if they read as separate graphic objects. TRENCH should read as one
physical faceplate with real seated parts, not a stack of visible effects.

If a proposed visual fix becomes "that black thing," "that teal thing," or an
obvious perspective illusion, stop. Fix the source asset, measured geometry,
material, spacing, or typography instead. Preserve the object first.

Good restraint is not cowardice: make visible, accountable changes when the
object needs them, but keep depth, light, material, and seating from becoming
props.

---

## 0.1.5 TRENCH UI — LOCKED STATE (2026-07-02, Tyson sign-off)

These are settled by verdict. Violating any of them is a regression, not a design choice.

```text
LOCKED — do not change without Tyson's explicit ask:
- wheels: GLB sculpt strip, satin gunmetal-violet, teal channel lamps
  (asset + spin_violet renders + build_malachite_render_strip.py all frozen)
- wells: the PANEL ART's baked recesses are the only wells. NEVER paint any
  rect/fill/seat/trough/cavity in, behind, or over a well. Wheel strip frames
  stay TRANSPARENT outside the wheel silhouette. (Regressed twice. Never again.)
- plate: 520x808, full art, bottom notch. Never crop, resize, or re-layout.
- screen: dusty-rose glass + ONE thin pale ice-cyan trace. No under-curve fill,
  no peak markers, no scanlines, no reflection streaks, no extra bezels,
  no bay/module frames. Quiet glass.
- light law: ice trace + teal wheel lamps = ONE cool lamp family; everything
  else warm (sand plate, espresso ink, ivory chips, one amber Modulation tag).
- chips: readouts + TYPE = warm ivory wells, espresso digits. Never pure white,
  never dark glass.
- labels: small tracked UPPERCASE engraved espresso; TRENCH / MUSICAL FILTER
  tracked at the plate top; bottom third stays bare sand.

PROCESS RULES that prevent the regressions:
- when Tyson says "go back to X", revert EVERYTHING added since X — grep for
  fragments of abandoned passes; a leftover block that survives a revert is
  how every regression tonight happened.
- one verdict per change; verify in a real PrintWindow build at 1:1 BEFORE
  claiming anything; diff against the last Tyson-approved capture.
- never piggyback an extra tweak onto an unrelated pass.
```

---

## 0.2 How this project is directed

Tyson is the creative director, not a DSP engineer or career coder.
The agent's job is to translate direction into verified builds.

```text
- direction arrives as vibes, verdicts, and reference images — not specs
- a reference image he sends IS the spec; study it before parameter-guessing
- every visual claim is proven in a REAL build screenshot at 1:1, never a mockup
- his eye/ear is the final gate; plots and probes are evidence, not verdicts
- one verdict per change — never stack tweaks and ask which helped
- when a direction fails twice, change the METHOD, not the parameters
- explain consequences in product terms; teach when asked, never gatekeep
- current UI/product state lives in the latest HANDOFF_*.json — read it first
```

Do not require him to write code, DSP math, or exact values to get what he
wants. Do not ship anything he has not seen in a real build.

---

## 0.1 Product constraint — DAW filter FX

This is a music-production filter effect.
The goal is not maximum spectral damage.
The goal is controlled, automatable, musically useful spectral motion.

Every filter body must satisfy two contracts:

```text
engineering contract = stable packed-runtime body
product contract     = useful under DAW automation on real program material
```

Extreme topology is allowed only when it is framed by control.
A body may be aggressive, but it must not be accidental.

Required product properties:

```text
- stable under dense Morph x Secondary automation
- gain-managed across corners, edges, center, and diagonals
- no hidden level explosions
- no unintended full-band disappearance
- no center collapse unless explicitly designed and labelled as a special effect
- no brittle sweet spot that exists only at one parameter value
- dry/wet and host automation must remain usable
- default region must work on normal musical material
- extreme region must be reachable, repeatable, and recoverable
```

Forbidden product behaviour:

```text
- curves that look interesting but vanish in a mix
- filters that only work on test tones
- huge endpoint contrast with broken interior motion
- unstable or nonfinite grid points
- uncontrolled output gain compensation
- random comb/notch clutter without an audible control law
- novelty bodies that cannot survive drums, bass, vocal, and full-mix probes
```

Taste is an engineering gate:

```text
A body is not accepted because it is extreme.
A body is accepted when its extreme behaviour is controllable, repeatable, gain-safe, and musically useful.
```

---

## 1. Evidence status labels

Every project-specific claim must be labelled:

```text
OBSERVED  = file/test/runtime/plot proves it
INFERRED  = plausible, not proven
UNKNOWN   = not known
REJECTED  = contradicted by current evidence
```

No invented Hz, dB, radii, byte values, coefficients, counts, names, or tables.
If the file/runtime does not provide a number, keep it symbolic or measure it.

---

## 2. Hard runtime facts

```text
body size     = 240 bytes exactly
layout        = 4 corners x 6 stages x 5 u16 words x 2 bytes
stages        = 6 total per corner
words/stage   = 5
corner order  = M0_Q0, M100_Q0, M0_Q100, M100_Q100
artifact      = .body240 + compiled cartridge JSON
```

Never infer a hidden seventh stage.
Never accept a body with wrong byte count, wrong corner order, wrong stage count, or wrong word count.

Semantic corner map:

```text
C0 = LOW.Q0
C1 = HIGH.Q0
C2 = LOW.Q100
C3 = HIGH.Q100
```

All four corners are authored (Q amendment 2026-07-10, LAWS.md L25 —
Q100 is a second scene, never derived).

---

## 3. Exact packed interpolation

Runtime interpolation is packed-domain, morph-first bilinear u16 interpolation:

```text
edge0 = lerp_u16(C0[i][k], C1[i][k], morph)
edge1 = lerp_u16(C2[i][k], C3[i][k], morph)
out   = lerp_u16(edge0, edge1, secondary)
```

`lerp_u16` is:

```c
(uint16_t)((int16_t)((float)((int)b - (int)a) * frac) + a)
```

Implications:

```text
- interpolate packed u16 words, not decoded coefficients
- f32 multiply/truncation matters
- int16 delta wraps before adding base
- no clamp
- center/diagonal points are runtime facts, not guesses
```

Do not replace this with smooth coefficient interpolation except in a clearly labelled surrogate.

---

## 4. Decode and cascade law

For one stage:

```text
words -> d0,d1,d2,d3,d4
c0 = 4*d0 + d1
c1 = d1
c2 = 4*d2 + d3
c3 = d3
c4 = 4*d4
```

DF2T row:

```text
b0 = c4
b1 = (c0 - 2)*c4
b2 = (1 - c1)*c4
a1 = c2 - 2
a2 = 1 - c3
```

Section:

```text
H_i(z) = (b0 + b1 z^-1 + b2 z^-2) / (1 + a1 z^-1 + a2 z^-2)
```

Body:

```text
H(z;m,s) = product_i H_i(z;m,s), i=1..6
A(w,m,s) = log |H(e^jw;m,s)|
```

This is a serial ordered cascade, not a parallel EQ bank.

---

## 5. Ordered lane law

At one static corner, section products commute.
During packed morphing, lane correspondence does not commute.

Stage index is:

```text
runtime correspondence across corners
```

Stage index is not:

```text
frequency order
semantic role proof
permission to sort per corner
```

Forbidden:

```text
- independent frequency sorting at each corner
- endpoint-only acceptance
- row permutation after packing
- nearest-frequency matching as sole correspondence
```

Required:

```text
- lane i LOW -> lane i HIGH
- lane i Q0  -> lane i Q100
- explicit lift/correspondence before packing
- center + diagonal audit after packing
```

---

## 6. Authoring law

A frame has exactly six lanes.
Each lane must expose:

```text
pole frequency
pole radius
zero frequency
zero radius / notch depth
gain
evidence/provenance tag
```

Zeros are first-class.
Never author poles alone.
Never treat numerator roots as gain cleanup.

Secondary/Q law (AMENDED 2026-07-10, Tyson verdict + 8/8 ROM measurement —
LAWS.md L25; supersedes the derived-pressure era):

```text
Q100 corners are AUTHORED, never derived. Q is a second pose of the same
instrument — a relocation, not a sharpener. Centers MAY move under Q
(measured in every ROM reference; the old center invariant is REJECTED
against ground truth).

The four measured Q verbs:
  BLOOM  — radii -> ~0.999, centers hold        (hedz, alkaline)
  SPREAD — the talker cluster fans apart         (fuzzi)
  SCREAM — one slot parks low+hot, gain word up  (lucifers)
  FLIP   — the frame changes register            (megasweepz)
```

Q must still not change:

```text
lane correspondence
```

A body whose Q100 only bumps radii is unfinished, not safe.

Naming law (Tyson verdict 2026-07-05):

```text
LOW/HIGH frame = LOW morph / HIGH morph — wheel positions, NEVER low/high sound.
Ordering a pose pair "big/dark at wheel 0, small/bright at wheel 100" is authoring
bias, not a rule. MEASURED 2026-07-05: this bias leaked into every generator
(wizard pairs 8/8 ascend, journeys 23:4, leader12 37:11 by centroid).
Choose home/away deliberately — home = the better default on real material —
or flip by ear (a 60-byte frame swap). Audition sweeps stay 0->100; direction
variety comes from the authoring, never the recipe.
```

---

## 7. Evidence discipline

Allowed rail sources:

```text
measured transfer functions
LPC captures
physical tube/vocal/cavity/modal models
measured tables
clean-room aggregate grammar
runtime-probed aggregate statistics
```

Forbidden:

```text
protected packed words
protected coefficient rows
protected endpoint tables
protected preset names
exact reference bodies
free random root clouds
unconstrained coefficient optimization
```

Rule:

```text
Study moves. Do not steal bodies.
Use aggregate behaviour only.
```

External datasets are teacher manifolds, not preset sources.
Generated roots must trace admissible evidence paths.

---

## 8. Shape law

Sections must compose in a serial cascade.
Flat off-resonance behaviour is required unless a shape is explicitly a broadband frame.

Q is shape-specific pole-radius control:

```text
bandwidth = f / Q
r_pole   = exp(-pi * bandwidth / SR)
```

Rejected unless new evidence proves otherwise:

```text
firmware-integer authoring path
generic pressurize law for every lane
free four-corner authoring
```

---

## 9. Runtime gates

For every packed grid point and every stage, compute denominator roots:

```text
z^2 + a1*z + a2 = 0
rho = max(|root_1|, |root_2|)
```

Hard fail:

```text
rho >= 1
nonfinite coefficient
nonfinite response
wrong byte count
wrong layout
Secondary center-frequency drift
endpoint-only verdict
copied protected data
```

Required probe set:

```text
corners
edges
center
diagonals
dense/adaptive Morph x Secondary interior
```

---

## 10. Objective surface

The verdict object is:

```text
A(w,m,s) = log |H(e^jw;m,s)|
```

Judge:

```text
full-surface residual
center residual
diagonal residual
mixed Morph/Secondary curvature
notch/ridge/saddle persistence
Schur margin
pole/zero balance
packed roundtrip error
quantization sensitivity
aggregate-only copy-risk
```

Endpoint curves are diagnostics, not acceptance.

---

## 11. Tasteful extreme-response search

Search for extreme topology, then pass it through product gates.

Prefer evidence surfaces with:

```text
moving zeros
remote pole/zero separation
notch crossings
high spectral curvature
high Morph curvature
strong Morph/Secondary coupling
persistent interior topology
near-boundary but stable poles
broad frame plus moving local features
clear low/mid/high energy management
recoverable parameter motion
```

Reject surfaces that are only:

```text
large dB span
static shelves
endpoint-impressive
center-broken
random
unstable
level tricks
all-cut with no usable frame
all-resonance with no gain discipline
interesting visually but weak on program material
```

Every candidate needs two readings:

```text
technical read = what the poles, zeros, and packed surface do
product read   = why a producer would automate it in a track
```

The goal is the best packed six-lane projection of an evidence surface that survives use as a DAW filter effect, not the wildest free fit.

---

## 11.5 Product audition gates

Every accepted body must be probed on real program material, not only plots.

Minimum audition classes:

```text
full mix
drums
bass
vocal / speech-like source
wideband synth / noise-rich source
transient source
sustained harmonic source
```

Measure symbolically parameterized limits:

```text
Δlevel(m,s)       <= τ_level
max_peak(m,s)     <= τ_peak
low_loss(m,s)     <= τ_low unless intentionally filtered
high_loss(m,s)    <= τ_high unless intentionally filtered
roughness(m,s)    <= τ_rough outside special-effect zone
automation_jump    <= τ_jump
center_residual    <= τ_center
Schur_margin       >= τ_schur
```

Thresholds are product decisions.
Do not invent them in research notes.
Measure and set them from listening tests, packed-runtime plots, and shipped-plugin gain staging.

Required A/B checks:

```text
bypass -> active
slow Morph sweep
fast Morph sweep
slow Secondary sweep
fast Secondary sweep
diagonal Morph+Secondary sweep
dry/wet sweep if implemented
parameter recall
sample-rate modes if implemented
```

A body that passes math but fails audition is rejected.
A body that sounds exciting but fails packed-runtime audit is rejected.

---

## 12. Required tests

Every relevant change must test:

```text
240-byte serialization
corner order
6 stages only
5 words/stage
minifloat decode/encode spot checks
packed lerp endpoint/midpoint behaviour
morph-first interpolation order
kernel-to-biquad map
serial cascade product
Schur stability over grid
nonfinite rows = 0
Q pose authorship (all four corners authored, none derived)
lane correspondence preservation
packed-runtime plot generation
```

Required regression:

```text
Same endpoint products + different non-diagonal corner row pairing
must change the interior surface unless the body is symmetric.
```

---

## 13. Definition of done

A candidate is accepted only if:

```text
[ ] every lane has provenance
[ ] all four corners authored (Q100 = a real second scene, LAWS.md L25)
[ ] Q verb named (BLOOM / SPREAD / SCREAM / FLIP)
[ ] frame anatomy stated (crown @1, floor+unit zero @6, talkers 2-5 — L23)
[ ] corner gain words disciplined (shared or deliberately tiered — L24)
[ ] ordered lane lift is explicit
[ ] artifact is exactly 240 bytes
[ ] runtime reads 4 x 6 x 5 u16 words
[ ] plots/audio come from packed runtime probe
[ ] unstable rows = 0
[ ] nonfinite rows = 0
[ ] center and diagonals inspected
[ ] zeros plotted and audited
[ ] aggregate copy-risk screen passes
[ ] no protected bytes/coefficients/names/tables used
```

No unchecked box, no success claim.

---

## 14. Communication

Be terse.
Use engineering nouns.
No hype.
No aesthetic labels as proof.
No invented constants.
No long theory when a probe, plot, or test is missing.

Preferred response shape:

```text
Verdict
Evidence
Failure mode
Patch
Verification
```

If blocked, state the exact blocker:

```text
UNKNOWN — not in files
UNKNOWN — needs runtime probe
INFERRED — needs plot confirmation
REJECTED — contradicts contract
```
