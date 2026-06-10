# GPT-5.5 Pro Prompt: Literal Hz Pole/Zero Language for DF2 Bodies

I am building original DF2 filter bodies for an audio plugin. I do **not** want an object taxonomy. I want a literal Hz-domain pole/zero authoring language.

## Runtime Constraints

- Sample rate: `39062.5 Hz`
- Nyquist: `19531.25 Hz`
- Each body has exactly 4 corners:
  - `M0_S0`
  - `M1_S0`
  - `M0_S1`
  - `M1_S1`
- Each corner has exactly 6 persistent rows/actors.
- Each row is a pole/zero actor, not a generic EQ band.
- The same row index must preserve identity across all four corners.
- Output must be authorable as literal Hz targets:
  - `pole_hz`
  - `zero_hz`
  - pole role
  - zero role
  - Q/bandwidth guidance
  - motion rule
- No convolution.
- No delays.
- No new DSP architecture.
- No extra stages.
- Do not copy E-mu/P2K names, curves, coefficients, ROM data, or presets.
- P2K is only inspiration for the idea that four corners can be musically distinct.

## Goal

Invent a practical Hz language for original iconic DF2 bodies. The language should let me author bodies by saying things like:

```text
55 pressure, 160 knock, 480 box, 1.4k bite, 4k tear-zero, 9k air
```

and then turn that into four musical corners that work together.

I want literal pole/zero locations in Hz. Everything should be in Hz.

Do **not** give me vague descriptions like “metallic,” “organic,” or “warm” unless they are attached to specific pole/zero Hz behavior.

## Required Output

Build the answer in 5 parts.

---

## Part 1 — Hz Vocabulary

Create a dictionary of reusable pole/zero roles. For each role give:

- `role_name`
- typical `pole_hz` ranges
- typical `zero_hz` ranges
- whether the zero is:
  - local
  - remote
  - comb
  - shelf
  - fracture
  - absent
- Q/bandwidth guidance in Hz
- musical job
- failure mode

Include at minimum:

- pressure weight
- sub anchor
- knock
- chest
- box
- nasal
- throat
- mouth formant
- vowel bridge
- metal mode
- bell partial
- shell mode
- fracture notch
- tear zero
- comb tooth
- air shelf
- scream
- fizz
- damping zero
- remote counterweight

---

## Part 2 — Six-Actor Grammar

Define how to build a six-row body:

- Row 1: low/weight actor
- Row 2: body/knock actor
- Row 3: cavity/formant actor
- Row 4: bite/motion actor
- Row 5: zero/fracture actor
- Row 6: air/extreme actor

For each row define:

- legal Hz ranges
- illegal overlaps
- legal pole/zero relationships
- how the row should move across corners
- how the row should respond to the secondary/Q axis
- failure conditions

---

## Part 3 — Four-Corner Rules

Invent rules for making four corners unique but coherent:

- `M0_S0` = HOME
- `M1_S0` = AWAY
- `M0_S1` = TIGHT HOME
- `M1_S1` = TIGHT AWAY

The secondary/Q axis must usually tighten, deepen, expose, or damp. It should not randomly become a new preset.

Define:

- legal corner distance in Hz/octaves
- minimum distinctness between HOME and AWAY
- maximum chaos allowed at midpoint
- how to guarantee the midpoint is musical
- how to preserve row identity
- how to prevent dead centers
- how to prevent pole collisions
- how to prevent zero/pole cancellation killing the body

Also define when to use these motion rules:

- `PIN`
- `CARRY`
- `COUNTER`
- `ORBIT`
- `ZIPPER`
- `POLE_SPLIT`
- `POLE_FUSE`
- `FORMANT_RELAY`
- `KINEMATIC_CROSS`

---

## Part 4 — 30 Original Body Blueprints

Give me 30 original iconic body blueprints.

Each blueprint must include:

- original name, non-vendor
- `one_sentence_identity`
- musical intention
- source material it is best on:
  - 808
  - vocal
  - pad
  - drum bus
  - lead
  - noise
  - FX
- six actors with literal `pole_hz` and `zero_hz`
- all four corners in Hz
- `M0_S0` row table
- `M1_S0` row table
- `M0_S1` row table
- `M1_S1` row table
- expected response plot description
- why the corners work together
- failure mode

Rows must look like this:

```yaml
row: 1
actor_name:
pole_hz:
pole_radius_guidance:
zero_hz:
zero_radius_guidance:
zero_role:
bandwidth_hz:
gain_role:
motion_rule:
corner_behavior:
```

Rules for the blueprints:

- Every final body must fit `4 corners x 6 rows`.
- Every row must include literal Hz values.
- Every row must preserve actor identity across all four corners.
- Use zeros deliberately. Do not leave all zeros blank unless that is musically justified.
- Stay below `19531.25 Hz`.
- Prefer useful musical bodies over academic correctness.
- Use physical acoustics only as inspiration for pole/zero locations.
- Do not use E-mu, P2K, Morpheus, Z-plane, ROM, or vendor preset names.

---

## Part 5 — Forge Editing Rules

Give practical editing rules for a human pole/zero editor:

- if I drag this pole upward, what should happen to its zero?
- when should rows be locked?
- when should rows cross?
- when should a zero stay remote?
- when should a zero stay local?
- when should a row become a comb tooth?
- when should Q tighten without moving Hz?
- what visual warnings should the editor show?
- what makes a body a “complete morph”?
- what makes a body musically bad even if stable?

## Important Style Requirements

- Be creative, but stay in literal Hz.
- Do not drift into long general acoustics prose.
- Do not return a bibliography-first answer.
- Do not over-explain DF2.
- Do not invent new DSP.
- Do not suggest ML training.
- Do not suggest convolution, delays, granular, wavetable, or external effects.
- Everything must be expressed as pole/zero Hz targets.
- The result should be usable by a human author inside a Forge-style pole/zero editor.

## Final Deliverable

End with a compact checklist titled:

```text
How To Use This In Forge
```

The checklist should explain how I take one of the blueprints, enter the six actors, set the four corners, plot the result, and decide whether it is a keeper.
