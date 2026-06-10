# DF2 Definitive Corner-Authoring Algorithm Run

You are the independent DSP-authoring systems engineer for DF2. Solve one
problem only:

> Define the definitive clean-room algorithm for jointly authoring four
> original DF2 corners as a musical `MORPH x SECONDARY` body, with explicit
> moving pole-zero cavities, so the packed-domain interpolated middle stays
> strong.

Do not design UI. Do not propose a product roadmap. Do not reopen the cube.
Do not restate project history. Do not write implementation code. Write one
algorithm specification that a coding agent can implement directly.

## Operating Stance: Be Blunt

Do not flatter the project, preserve a prior idea for emotional continuity, or
validate the brief by default. Your highest-value contribution is to kill bad
assumptions before they harden into tooling.

Be technically blunt:

- if a claimed authoring law is unsupported, say `UNSUPPORTED`;
- if an approach is structurally wrong, say `REJECTED` and explain the failure
  mechanism;
- if two goals conflict, name the tradeoff and choose;
- if the proposed coupled pole-zero cavity doctrine is incomplete or wrong,
  correct it rather than decorating it;
- do not hedge with a menu of possibilities where the evidence supports a
  decision;
- do not invent certainty where the evidence only supports a bounded
  experiment.

Treat the final patch-ready document as DF2's technical constitution for corner
authoring. It must create permanent momentum: one owner, one compilation path,
one validation grid, one first calibration experiment, and explicit rejection
gates. The next coding agent should be able to build the first useful version
without reopening architecture debates.

## Locked Product Constraints

- Shipped product: VST3 insert FX with `TYPE`, `MORPH`, and `SECONDARY`.
- Commercial target: 4-7 original iconic bodies, not a large preset catalog.
- Private Forge: one-author bench. Machine proposes mathematically strong raw
  material; human approves bodies by taste.
- Author workflow: plot-first, ear-last. Plots must expose the real packed
  shipping path.
- Clean room: recovered third-party fixture bytes and plots are study-only
  calibration references. Never reproduce or ship their coefficients, names,
  tables, bytes, or extracted templates.

## Locked Runtime Constraints

The supplied live code must be checked, but it appears to establish:

- exactly `6` serial DF2T biquad stages;
- exactly `5` packed `u16` words per stage;
- exactly `4` corners in order:
  `M0_S0`, `M1_S0`, `M0_S1`, `M1_S1`;
- canonical body size:
  `4 corners x 6 stages x 5 words x 2 bytes = 240 bytes`;
- morph-first packed-`u16` bilinear interpolation, then decode, then serial
  cascade execution;
- current runtime container: one four-corner `MORPH x SECONDARY` plane;
- a seven-section answer is a format change and is out of scope;
- an eight-corner cube is out of scope;
- drive is downstream character treatment and out of scope for this algorithm.

Correct any mistaken wording against live code, but do not change the runtime
format.

## The Blocking Problem

There is no settled method for designing the four corners. Prior attempts keep
making one of these mistakes:

1. authoring four attractive static plots independently, then discovering that
   packed-domain interpolation produces mush;
2. treating stages as all-pole resonators and losing the zero-bearing character;
3. using generic parametric EQ or magnitude fitting that hides the pole-zero
   structure;
4. treating zeros as optional decoration, global correction, or a post-pass;
5. placing frequencies in arbitrary Hz rather than acoustic and perceptual
   space;
6. placing or jittering individual pole/zero coordinates at random, or using a
   random number as the source of variety instead of the generator program;
7. reviving cube, UX, or taxonomy discussions instead of solving body math.

The algorithm must solve the actual body problem:

> Four corners must be generated jointly from one six-cavity skeleton. Each
> cavity carries a pole, its paired zero, radius, gain/normalization law, and
> motion law across both axes. Poles and zeros move as paired actors. The
> four static corners and all held-out packed-domain intermediate states must
> remain deliberate.

Do not silently drop numerator information. Do not return a pole-only model.

### Determinism Law (never random poles)

Randomness is allowed ONLY at the generator-program level: seeded, reproducible
selection among lawful family / skeleton / macro-range options. Individual pole
and zero coordinates — frequency AND radius — are NEVER random and NEVER jittered.
Every pole and every zero must be placed by the skeleton/acoustic/perceptual law
and be traceable to it. Variety comes from the program (which family, which macro
values, which seed selects among lawful states), not from noise applied to the
poles or zeros. A specification that relies on per-slot random offsets is rejected.

## Required Technical Decisions

Settle each item precisely.

### 1. Canonical Authoring Object

Define the minimal data model for one body before packing. It must represent:

- six fixed stage slots;
- one pole-zero cavity actor per active slot;
- pole center frequency and radius;
- paired zero center frequency and radius;
- per-stage or cascade gain normalization;
- stage slot continuity across all four corners;
- a family/acoustic provenance handle;
- a motion law over `MORPH x SECONDARY`.

Decide whether the authoring object should store:

- four endpoint actor states plus strict slot correspondence;
- one continuous actor field sampled at four endpoints;
- or another joint representation.

Choose one. Explain why it survives packed-domain interpolation.

### 2. Pole-Zero Cavity Law

Define what a cavity is mathematically and perceptually.

Settle:

- when the zero is close to its pole and moves with it;
- how zero offset and zero radius create peak-plus-notch "tear";
- how unity DC is enforced;
- how radius is derived from acoustic bandwidth and optionally cranked;
- how gain is normalized without erasing the jagged shape;
- whether any stage types are allowed to be exceptions, and why.

Zeros must be first-class. The specification must make it impossible for an
implementation agent to ignore them.

### 3. Joint Four-Corner Construction

Define how to construct:

- `M0_S0`;
- `M1_S0`;
- `M0_S1`;
- `M1_S1`.

The algorithm must say what `MORPH` changes and what `SECONDARY` changes.
It must preserve slot identity while allowing musical crossing, collision, and
contrast. Explain how to author bold trajectories without independently
optimizing each static corner.

### 4. Frequency Placement

Use:

- acoustic tables for vocal tracts, tubes, cavities, and metallic modes;
- logarithmic frequency relationships;
- Bark or critical-band spacing for perceptual checks;
- explicit handling for resonances closer than approximately `200 Hz`.

Settle the collision rule. When two resonant poles approach each other, decide
when to preserve the fusion as intentional character and when to compensate by
adjusting bandwidth, radius, zero offset, or gain. Do not blindly ban close
poles. Do not allow accidental broad humps.

### 5. Packed-Path Audit

Define the exact validation grid and gates after packing through the one
shipping owner:

- four endpoint miniplots;
- held-out `MORPH x SECONDARY` samples, not endpoints only;
- pole and zero trajectories per slot;
- stability and finite checks;
- unity-DC tolerance;
- headroom;
- fusion/collision diagnostics;
- plot comparison before listening;
- clean and driven audition only after plot approval.

The packed-domain middle is the product. Decoded-float intent is not enough.

### 6. Family Templates

Provide minimal original template laws for:

- vocal tract;
- tube/cavity;
- metallic/modal;
- one deliberately violent synthetic cavity family.

Each family must still compile through the same six-cavity object. Describe
which acoustic facts seed it and which bounded taste controls remain. Do not
provide third-party coefficients or derivative templates.

### 7. AI vs Human Boundary

Define what AI may generate, rank, or flag, and what only the human may approve.
The human must never edit raw coefficients. The human should judge plots and
sound, replace candidates, and keep or reject bodies.

The generator specification may include worked examples only as disposable
proof-of-math fixtures. Those examples must prove that the generator:

1. executes end-to-end through the packed shipping path;
2. can produce a jagged, zero-bearing, canyon-bearing shape with consequential
   intermediate states;
3. covers all four requested original family laws; and
4. produces reproducible intra-family variety from lawful program macros, not
   random or jittered pole/zero coordinates.

Worked examples are neutral calibration fixtures, not designed bodies. Nobody
auditions them for release. AI must NOT curate them, rank them as keepers, name
them as iconic, assemble a finished body set, or imply that mathematical
validity is taste approval. Taste remains entirely downstream with the human:
which families to explore, which macros to move, which plots to keep, which
bodies exist, and which bodies survive listening.

### 8. Existing Repo Ownership

Audit the supplied candidate scripts. Identify:

- the single owner that should remain or be rewritten into the owner;
- useful pieces to absorb;
- exploratory scripts to quarantine;
- wrong approaches to reject.

Do not preserve a script just because it exists.

## Evidence Discipline

Use these labels:

- `OBSERVED`: directly proven by supplied live code, tables, fixture manifest,
  or packed-path plot.
- `INFERRED`: strongest interpretation, not yet directly proven.
- `HYPOTHESIS`: bounded experiment requiring a gate.
- `REJECTED`: contradicted, structurally wrong, or out of scope.

The recovered Talking Hedz plot is study-only. Use it to understand the
behavioral bar: busy zero-bearing structure, deep moving notches, strong
contrast, and consequential intermediates. Do not reverse it into a copy.

The supplied `study_best_of_best` compact corpus is also study-only. It contains
runtime-derived endpoint and center cavity measurements for a hand-selected
reference set. Use it to identify general behavioral laws across strong
examples. Do not reproduce any row, packed word, coefficient set, preset name,
or extracted body as original authoring material.

The supplied scripts disagree with each other. Treat them as candidates, not
doctrine. The live packed runtime is the execution truth.

## Mandatory Output

Return exactly these sections:

1. `ONE-SENTENCE ALGORITHM`
2. `BRUTAL VERDICT: WHAT WE HAVE WRONG`
3. `OBSERVED RUNTIME FACTS`
4. `CANONICAL SIX-CAVITY BODY SCHEMA`
5. `POLE-ZERO CAVITY LAW`
6. `JOINT FOUR-CORNER CONSTRUCTION`
7. `FREQUENCY, BARK, AND 200 HZ COLLISION LAW`
8. `PACKED-PATH VALIDATION GRID`
9. `ORIGINAL FAMILY TEMPLATE LAWS`
10. `AI PROPOSES, HUMAN APPROVES`
11. `REPO OWNER DECISION`
12. `REJECTED APPROACHES`
13. `FIRST IMPLEMENTATION TICKET`
14. `PATCH-READY CORNER_AUTHORING_ALGORITHM.MD`

The patch-ready document is the primary deliverable. It must be compact,
unambiguous, and implementation-ready. Include pseudocode for the body compiler,
named invariants, hard rejection gates, and the smallest calibration experiment
that can falsify the proposed authoring law before further Forge work.

## Hard Forbids

- no UX specification;
- no cube;
- no seven-stage format;
- no raw third-party coefficients;
- no third-party names in shippable examples;
- no pole-only model;
- no zero omission;
- no random or jittered pole/zero coordinates (frequency or radius) — random
  generation is allowed only at the program level, never on the poles themselves;
- no generic graphic-EQ workflow;
- no response-curve drawing workflow;
- no independent per-corner optimization;
- no automatic AI approval of finished bodies;
- no AI curation, keeper ranking, iconic naming, or assembly of a finished body
  set;
- no presenting proof-only worked examples as designed presets or release
  candidates;
- no open-ended research program;
- no follow-up questions.

Keep the answer under `3000` words. Spend detail on the algorithm, invariants,
failure mechanisms, validation grid, and first implementation ticket. Do not
spend words on encouragement, recap, or generic DSP education. Be decisive.
