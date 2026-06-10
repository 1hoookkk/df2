# DF2 Private Forge Coefficient-Surface Adjudication

You are the independent DSP-tooling architect for DF2. Solve one problem only:

> Specify the definitive private Forge GUI for authoring original DF2 bodies by
> editing the six serial pole-zero stages directly while continuously judging the
> real packed four-corner surface.

This is not a product UX exercise. The Forge is a private, single-author bench.
The author is a visual thinker who trusts plots and needs to create 4-7 original,
iconic bodies. The shipped plugin remains simple: `TYPE`, `MORPH`, `SECONDARY`.

Be blunt. If “edit coefficients in a GUI” is the wrong abstraction, say exactly
which decoded parameters should be edited instead and why. Do not protect a prior
idea for emotional continuity. Make the decision.

## Deliverable

Write one patch-ready technical specification named:

`DF2 PRIVATE FORGE: DEFINITIVE STAGE-COMPOSER SPEC`

It must tell a coding agent exactly what to build first. Do not write code. Do
not propose a broad roadmap. Do not reopen unrelated DSP architecture debates.

## Locked Runtime Facts

Treat these as hard constraints unless the supplied code excerpts contradict
them:

- Runtime body: exactly four corners ordered `M0_S0`, `M1_S0`, `M0_S1`,
  `M1_S1`.
- Runtime stage count: exactly six serial DF2T biquads.
- Each stage stores five packed `u16` words.
- Canonical body size: `4 corners x 6 stages x 5 words x 2 bytes = 240 bytes`.
- Both numerator and denominator structure matter: zeros and poles are present.
- Shipping interpolation: packed-domain morph-first bilinear interpolation,
  decode, then serial cascade.
- Plots and diagnostics must use the shipped `trench_core` FFI path.
- A seven-stage answer is a format change and out of scope.
- An eight-corner cube is out of scope for the shipping body.
- Clean-room boundary: supplied recovered reference evidence is private,
  study-only calibration material. Never reproduce, quote, ship, or turn its
  coefficients, packed words, names, tables, or direct derivatives into
  authored material.

## Settled Product Scope

- Shipped artifact: DF2 VST3 insert FX.
- Public controls: `TYPE`, `MORPH`, `SECONDARY`.
- Goal: 4-7 original iconic bodies, not a large preset catalog.
- Forge: private single-author development bench and recordable short-form
  content surface. It is not shipped.
- Human author owns taste. AI may propose lawful original raw material and flag
  failures. AI must not approve, rank as keeper, or assemble finished bodies.
- Author workflow is plot-first, ear-last. Sound audition comes after the shape
  is visually deliberate.
- No random poles. No random zeros. No per-coordinate jitter. Physical,
  acoustic, and deterministic macro programs may generate starting material.

## New Study Evidence You Must Respect

The supplied sanitized study report and plots were produced from selected
private reference fixtures by the release packed runtime. Treat them as
behavioral evidence only.

Observed:

1. Every sampled stage row carries numerator/zero structure.
2. A universal “every zero hugs its pole” doctrine is false.
3. Nearby zeros and remote zeros both matter:
   - nearby zeros can form local peak-plus-canyon tears;
   - remote zeros can create broad slope, shelf, excavation, air-cap, window,
     and cross-spectrum tension behavior.
4. The selected bodies do not use six equal cavities. They have foundations.
5. Multiple foundation construction methods appear:
   - descending slope foundation with resonant mountains layered above;
   - rising shelf/high-pass-like foundation with cuts and top-end peaks;
   - opposed broad stages that create a window, hollow, or tension field;
   - low-pass-like bass cliff with character peaks;
   - distributed broad-stage fields where no single stage is “the filter.”
6. Sub-200 Hz pole fusion appears in useful bodies. It must be surfaced, not
   universally banned.
7. Endpoint quality is insufficient. The packed middle and held-out surface
   states must remain visible while authoring.

## Additional Primitive-Architecture Evidence

The author supplied screenshots from the E-mu filter UI and a local primary
tutorial for Peak/Shelf Morph. Treat these as behavioral evidence, not as a
request to copy vendor implementation details.

Observed primitive palette in the UI:

- `2 Pole Lowpass`
- `4 Pole Lowpass`
- `6 Pole Lowpass`
- `2 Pole Highpass`
- `4 Pole Highpass`
- `2 Pole Bandpass`
- `4 Pole Bandpass`
- `Contrary Bandpass`
- `Swept EQ 1 Octave`
- `Swept EQ 2/1 Octave`
- `Swept EQ 3/1 Octave`
- `Peak/Shelf Morph`
- additional phaser, vocal, dual-EQ, and morph-designer classes

Observed screenshot behavior:

- low-pass families expose progressively steeper foundations;
- `6 Pole Lowpass` visibly reaches a high cutoff near `20 kHz`;
- `4 Pole Highpass` visibly reaches approximately `18 kHz`;
- `4 Pole Bandpass` is a strong resonant bandpass foundation;
- `Contrary Bandpass` is a particularly violent crossing / contrast primitive;
- swept-EQ classes expose moving peaks with different octave-width laws;
- Peak/Shelf Morph exposes a compact two-frame macro surface.

Observed from the supplied Peak/Shelf Morph tutorial:

- the author defines a low morph frame and high morph frame;
- `SHELF` blends continuously across low-pass -> mid-shelf -> high-pass tone;
- `FREQ` changes meaning with the shelf state: low-pass rolloff, mid band, or
  high-pass boundary;
- per-frame `PEAK` sets relative frame volume;
- the overall Peak control changes the peak-filter volume as a whole;
- deliberately backing off an extreme low-pass frame can avoid pops and ugly
  distortion under saturated sweeps;
- the resulting movement is intentionally used as a smooth, distorted,
  belching transition rather than a static EQ correction.

Observed from local binary-study notes:

- Morph Designer is not the only class-specific writer targeting the packed
  corner banks.
- Morph Designer authors two logical endpoint frames and duplicates them across
  the historical secondary axis, making that generated surface effectively 1D.
- Other adjacent class writers emit different fixed or table-selected
  structures. Do not flatten all useful constructors into one fake universal
  formula.

This evidence changes the GUI question. The Forge may need two complementary
authoring paths that meet on the same six-stage surface:

1. Direct stage composition for sealed-body-class original work.
2. Lawful primitive constructors and two-frame macro operations that create or
   replace editable stage bundles.

Settle that architecture explicitly.

## New Morph Designer Template Evidence

A private study-only local Emulator X template folder contains `69` Morph
Designer XML templates. A sanitized structural digest is supplied. Do not copy
or reproduce the vendor endpoint rows.

Observed:

- every template contains exactly six serialized `designer-section` rows;
- every row carries `type`, `low-freq`, `low-gain`, `high-freq`, and
  `high-gain`;
- the observed row IDs are `0..3`, consistent with the static extraction where
  IDs `1..3` compile and `0` is skipped;
- the low/high fields are an explicit two-endpoint stage-program grammar;
- `18` of the `69` templates use all six active rows, while many deliberately
  use only two to four;
- the most common active pattern is repeated type-`1` rows, but mixed row
  grammars are also common.

This is not shippable content. It is evidence that the authoring problem can be
expressed as deliberate composition of a small lawful row vocabulary rather
than random poles or a universal six-identical-cavity recipe.

Settle whether the Forge should visibly expose an original, clean-room
stage-program composer inspired by that compact grammar:

- create an original row or bundle from a lawful constructor;
- edit its two endpoint postures;
- compile to packed words;
- inspect the resulting release-runtime curve and packed intermediates;
- optionally expand the result into a true four-corner DF2 body by authoring
  Secondary behavior deliberately.

Do not prescribe copying the reference rows or preserving vendor type IDs in
DF2's editable document.

## The Decision To Make

Specify the correct authoring surface.

The current candidate concept is:

```text
BODY SURFACE
  four corner miniplots
  large live packed-runtime response curve
  visible Morph and Secondary trajectories
  visible packed center and held-out checkpoints

SELECTED CORNER / STAGE COMPOSER
  six serialized stage lanes
  each lane exposes pole, zero, radius, and gain behavior
  complete serial cascade remains visible
  selected stage can be isolated visually

INSPECT
  raw kernel c0..c4 and packed u16 words available only as secondary diagnostics
```

Determine whether this is structurally right. Correct it where necessary.

## Questions You Must Settle

### 1. Editable Coordinates

Choose the normal editing coordinates. Compare:

- raw packed `u16` words;
- decoded kernel `c0..c4`;
- direct biquad `b0,b1,b2,a1,a2`;
- pole frequency, pole radius or bandwidth, zero frequency, zero radius,
  and normalization/gain;
- a mixed system with explicit foundation macros plus direct stage editing.

Choose one primary editing model and one diagnostic-only model. State why.

The author must be able to build extreme shapes intentionally without needing
to think like a DSP engineer. Do not hide zeros.

### 2. Foundation Authoring

The reference study shows multiple foundation methods. Define the smallest
useful set of explicit foundation operations the GUI must support in v1.

Settle whether foundations should be:

- editable ordinary stage lanes with role labels;
- generated stage bundles that remain editable afterward;
- macro operations layered above stage lanes;
- or another representation.

The GUI must make it possible to create:

- descending slope;
- rising shelf/high-pass-like lift;
- opposed window/hollow;
- low-pass bass cliff;
- remote-zero air cap;
- distributed broad-stage foundation.

Avoid a generic EQ-plugin workflow. The point is to compose serial pole-zero
behavior, not offer familiar EQ bands.

### 2A. Primitive Constructor Palette

Decide whether the first useful Forge needs a visible primitive palette derived
from the observed behaviors above.

For each recommended v1 constructor, specify:

- purpose;
- number of serialized stages consumed;
- editable musical controls;
- whether it creates a foundation, character actor, or multi-stage bundle;
- whether it is naturally a two-frame macro, a true four-corner field, or a
  starter that becomes ordinary editable stages immediately after insertion;
- how it remains visible and editable after insertion.

At minimum adjudicate:

- 2/4/6-pole lowpass;
- 2/4-pole highpass;
- 2/4-pole bandpass;
- contrary bandpass;
- swept EQ with width law;
- Peak/Shelf Morph.

Do not cargo-cult a vendor menu. Keep only constructors that materially speed
the creation of original iconic surfaces.

### 3. Stage Interaction

Specify exactly what direct manipulation means:

- horizontal pole and zero dragging;
- vertical dragging, wheel, modifier keys, or side controls for radius,
  bandwidth, gain, and zero depth;
- isolate/bypass/lock behavior;
- stage role labels;
- local peak/canyon versus remote-zero display;
- how the serial cascade and individual stage curves remain legible together.

The author needs a fast, natural, camera-legible interaction loop.

### 4. Four-Corner Semantics

Specify how editing works across `MORPH x SECONDARY`:

- editing a single corner;
- copying or linking a stage across corners;
- editing one serialized stage slot as a four-corner field;
- locking foundation stages while moving character stages;
- showing packed midpoint damage immediately;
- intentionally allowing collisions and role changes without accidental mush.

Decide what should happen by default when the author drags a pole or zero in
one corner. The answer must preserve author control while keeping the surface
manageable.

### 5. Continuous Packed Audit

Define the always-on diagnostic loop through `trench_core`:

- endpoint plots;
- center;
- edge midpoints;
- diagonal checkpoints;
- optional dense grid;
- stability and nonfinite checks;
- pole radius;
- collision/fusion warnings;
- remote-zero classification;
- stage-track display;
- response headroom;
- clean versus driven preview boundary.

Warnings must inform taste, not substitute for it. Separate hard rejection
gates from plot annotations.

### 6. Data Ownership And Compile Path

Define the single source of truth before and after packing:

- authoring document schema;
- editable decoded stage representation;
- compiled packed 240-byte body;
- release FFI probe;
- hot reload or preview path;
- save/export boundaries.

State precisely which artifact is editable and which artifact is authoritative
for runtime proof.

Also settle how a two-frame macro such as Peak/Shelf Morph coexists with a
four-corner body:

- remain a degenerate 1D body duplicated across Secondary;
- act as a starter that the author later expands into a true 2D body;
- become a multi-stage operation inside a true 2D body;
- or another explicit method.

Choose the default and explain the tradeoff.

### 7. Exact First Build

Give a bounded implementation sequence for a coding agent:

- v0: minimum useful stage composer;
- v1: four-corner field editing and continuous packed checkpoints;
- v1.1: foundation recipes and deterministic physical skeleton starters.

For each phase, list visible controls, saved artifacts, and acceptance tests.

The first build must become useful quickly. Do not hide the core editor behind
an atlas, taxonomy, quarry, workflow wizard, or AI assistant.

## Explicit Rejections

Reject these unless you prove one necessary:

- editing packed words as the normal workflow;
- pole-only models;
- zeros as decoration or a global post-pass;
- six identical unity-DC cavities as the universal body model;
- random poles, random zeros, coordinate jitter;
- generic parametric EQ UI;
- a full-screen map as the main authoring surface;
- a cube editor;
- an elaborate multi-step chapter workflow;
- AI selecting taste;
- reference-template copying;
- diagnostics that pretend to certify musical quality.

## Required Output Structure

Use this exact structure:

1. `VERDICT`
2. `WHAT THE AUTHOR EDITS`
3. `SCREEN ANATOMY`
4. `FOUNDATION OPERATIONS`
5. `FOUR-CORNER EDIT SEMANTICS`
6. `ALWAYS-ON PACKED AUDIT`
7. `AUTHORING DOCUMENT SCHEMA`
8. `COMPILE AND PREVIEW PATH`
9. `FIRST IMPLEMENTATION SEQUENCE`
10. `REJECTED APPROACHES`
11. `OPEN EXPERIMENTS`

Label claims `OBSERVED`, `INFERRED`, or `RECOMMENDED`. Keep the specification
concrete. The next coding agent must be able to implement it without another
architecture discussion.

In `OPEN EXPERIMENTS`, rank the smallest exact metrology capture set still worth
collecting from the reference UI. Name the filter class, control sweep, and what
decision each capture would settle. Keep this bounded: request no more than six
captures and distinguish evidence needed before v0 from evidence that can wait.
