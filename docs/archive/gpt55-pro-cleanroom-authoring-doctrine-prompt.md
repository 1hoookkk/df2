# DF2 Clean-Room Authoring Doctrine: Final Brutal Adjudication

You are the independent DSP architect for DF2.

Solve one problem only:

> Define the definitive clean-room algorithm for generating original,
> musically-useful four-corner DF2 bodies from physical models, perceptual
> spacing laws, and the observed three-row Morph Designer compiler grammars.

Be brutal. Argue with yourself. Reject weak assumptions. Then land one usable
algorithm.

This is not a GUI-design task. This is not a heritage-history essay. This is not
an invitation to copy vendor presets. Do not produce a broad roadmap.

## Product Boundary

- DF2 is a VST3 insert FX plugin.
- Public controls are `TYPE`, `MORPH`, and `SECONDARY`.
- `TYPE` selects one authored body. `MORPH` and `SECONDARY` perform within it.
- Commercial scope is only `4-7` original iconic bodies.
- The Forge is a private single-author development bench.
- The human author owns taste. AI may generate lawful original raw material,
  plots, warnings, and contact sheets. AI must not rank-as-keeper, bless, or
  silently assemble finished bodies.
- The author trusts plots first and ears last.

## Locked Runtime Truth

Treat these as hard constraints:

- A shipping body is exactly four corners:
  `M0_S0`, `M1_S0`, `M0_S1`, `M1_S1`.
- Each corner contains exactly six serialized DF2T biquad rows.
- Each row stores five packed `u16` words.
- Canonical body size is exactly `4 x 6 x 5 x 2 = 240` bytes.
- Numerator and denominator structure both matter. Zeros must never be omitted.
- Shipping interpolation is packed-domain bilinear interpolation followed by
  decode and the serial cascade.
- The six rows are indexed correspondence lanes. They are not universally six
  semantic cavities, but they are not disposable bookkeeping.
- Endpoint quality is insufficient. The packed center and held-out off-axis
  states must be judged.

Do not reopen stage count, body size, interpolation order, cube format, runtime
sample-rate architecture, or product-control debates.

## Clean-Room Boundary

The private ROM corpus and Ghidra extraction are study-only evidence.

Never:

- reproduce or recommend copying vendor packed words;
- copy vendor rows, endpoint values, trajectories, preset names, tables, or
  curves into authored bodies;
- infer that an observed vendor coordinate is safe to reuse;
- claim that a clean-room physical model is historically how E-mu authored a
  ROM body unless the evidence actually proves it.

Use observed implementation facts to understand the container and available
grammar. Use public acoustics and original parameter ranges to generate DF2
material.

## Observed ROM-Body Lessons

Treat these as sanitized behavioral findings:

- The strongest sealed ROM bodies have foundations.
- Recurring foundation behaviors include:
  - hard descending cliffs;
  - rising shelves or edges;
  - opposed windows and hollows;
  - clustered vocal or cavity mountains;
  - distributed sweep fields.
- Local pole-zero tears and remote-zero counterweights both occur.
- Remote zeros can create broad slope, excavation, air-cap, window, and tension
  behaviors. They are not automatically mistakes.
- Sub-200 Hz pole collisions sometimes appear in useful bodies. Surface them as
  warnings; do not universally ban them.
- Morph and Secondary can change different aspects of one indexed lane.
- Rigid "every zero hugs its pole" and "six identical cavities" doctrines are
  false.

## Clean-Room Source Laws

Use these as candidate original source laws:

### Physical pole skeletons

- Human voice:
  - published vowel formant locations such as Peterson-Barney and Klatt;
  - meaningful phoneme transitions such as `oo -> ee`, `ah -> ee`, and
    `oo -> ah`;
  - formant bandwidths from published acoustic literature.
- Pipes and tubes:
  - open-open harmonic modes;
  - closed-open odd-harmonic modes;
  - length as a meaningful Morph transformation;
  - damping or end-condition as meaningful Secondary transformation.
- Bottles and cavities:
  - Helmholtz neck resonance;
  - body modes;
  - physical dimensions as authorable macros.
- Plates, bars, bells, shells, and membranes:
  - textbook modal ratios and dimension scaling;
  - damping, strike posture, and material response as macro dimensions.

### Perceptual synthetic skeletons

- Bark, ERB, or log-frequency spacing for intentionally synthetic distributed
  rows.
- Coherent translate, scale, spread, crossing, and clustering operations.
- No arbitrary root spraying and no per-coordinate random jitter.

### Explicit zero treatments

Physical equations often provide pole candidates, not a complete numerator law.
Treat zeros as an authored original layer:

- `LOCAL_TEAR`: nearby canyon or bite around a pole;
- `REMOTE_COUNTERWEIGHT`: broad slope, excavation, hollow, or air cap;
- `EDGE_ZERO`: cliff or shelf behavior;
- `NEUTRAL`: minimal added coloration where physical modes should dominate.

The algorithm must explain when and how these treatments are selected without
pretending that all zeros are literal physical anti-resonances.

## The Central Question

We have two ingredients:

1. Original physical or perceptual skeletons.
2. Three observed class-specific Morph Designer row grammars.

Determine how they fit together.

Are Types `1`, `2`, and `3`:

- useful clean-room rendering grammars beneath original pole skeletons;
- only metrology targets that should not constrain new authoring;
- a compact starter vocabulary supplemented by direct root-domain compilation;
- or something else?

Do not assume that one answer applies equally to physical voices, modal objects,
cliffs, and synthetic sweep fields.

## Required Output

Write a compact report titled:

`DF2 CLEAN-ROOM BODY AUTHORING: DEFINITIVE ALGORITHM`

Use exactly these sections.

### 1. Internal Argument

Write a short adversarial discussion between:

- `THE PHYSICIST`: insists on physical and perceptual source laws;
- `THE ROM ARCHITECT`: insists on respecting the observed packed runtime and
  compiler grammars;
- `THE PRODUCER`: rejects anything timid, slow, or cognitively expensive;
- `THE CLEAN-ROOM COUNSEL`: rejects contamination and unsupported historical
  claims.

Keep the argument under `1100` words. Make them disagree concretely.

### 2. Verdict

State the definitive authoring doctrine in one decisive paragraph.

### 3. Type 1 / Type 2 / Type 3 Behavioral Roles

For each observed Morph Designer type:

- summarize the mathematical behavior from the supplied formulas;
- state what it appears useful for;
- state what it cannot do safely;
- classify it as:
  - `CORE CONSTRUCTOR`,
  - `OPTIONAL STARTER`,
  - `METROLOGY ONLY`, or
  - `NEEDS PLOT SWEEP BEFORE USE`.

Be explicit about uncertainty. Do not invent semantic certainty from formulas
alone.

### 4. Original Skeleton Families

Define the smallest serious clean-room family set. Include:

- vocal/formant;
- tube/pipe;
- bottle/cavity;
- modal object;
- cliff/edge;
- synthetic distributed field.

For each family, specify:

- source law;
- pole-placement rule;
- allowed zero treatments;
- meaningful `MORPH`;
- meaningful `SECONDARY`;
- warnings to surface;
- whether Types `1`, `2`, or `3` are suitable starters.

### 5. The Generator

Specify one deterministic body-generation algorithm in numbered steps.

It must:

- generate a coherent six-row skeleton;
- produce all four corners as related postures of one program;
- preserve indexed-row correspondence;
- include explicit zero strategies;
- compile through the owned packed-word path;
- inspect corners, center, off-axis points, and a fixed held-out grid;
- emit warnings without automatically rejecting tasteful violence;
- generate contact sheets for the human author;
- never rank or approve taste.

### 6. Bounded Experiments

List at most `7` experiments, ordered by leverage.

Each experiment must contain:

- one question;
- one minimal generated sweep or plot;
- one decision that the result settles.

The first experiments must characterize Types `1`, `2`, and `3` from the
observed formulas before relying on them.

### 7. Immediate Build

Specify exactly one implementation slice that should be built now. It must be
small, plot-first, deterministic, and usable within one session.

### 8. Do Not Do

List at most `8` concrete failure modes to forbid.

## Hard Forbids

- No GUI design.
- No broad roadmap.
- No code.
- No vendor coefficient reproduction.
- No random root generation.
- No AI taste ranking.
- No claim that physical modelling was historically used by E-mu unless proven.
- No simplistic universal zero law.
- No silent promotion of hypotheses into facts.
- No relitigation of the locked runtime.

Produce a technical doctrine that a coding agent can implement immediately.
