# GPT-5.5 Pro Compact Prompt: DF2 Literal Hz Pole/Zero Language

I am building original DF2 filter bodies for an audio plugin. I do **not** want an object taxonomy. I want a compact literal Hz-domain pole/zero authoring language for a Forge-style editor.

## Hard Constraints

- Sample rate: `39062.5 Hz`
- Nyquist: `19531.25 Hz`
- One body = `4 corners x 6 rows`
- Corners: `M0_S0`, `M1_S0`, `M0_S1`, `M1_S1`
- Each row is one persistent actor across all corners.
- Rows are literal pole/zero locations in Hz.
- No convolution, delay, extra stages, new DSP, ML, ROM copying, vendor preset names, vendor curves, or coefficients.
- P2K/E-mu only inspires the idea of musically distinct four corners. Do not copy anything.

## Goal

Invent a practical **Hz pole/zero language** that lets me author bodies like:

```text
55 pressure, 160 knock, 480 box, 1400 bite, 4000z tear, 9000 air
```

Everything must be in Hz. Avoid vague words unless tied to exact pole/zero behavior.

## Output Required

### 1. Hz Vocabulary

Give a compact dictionary of reusable roles. For each role include:

```yaml
role:
pole_hz_range:
zero_hz_range:
zero_role: local | remote | comb | shelf | fracture | damping | absent
bandwidth_hz:
musical_job:
failure_mode:
```

Include at least:

`pressure weight, sub anchor, knock, chest, box, nasal, throat, mouth formant, vowel bridge, metal mode, bell partial, shell mode, fracture notch, tear zero, comb tooth, air shelf, scream, fizz, damping zero, remote counterweight`

### 2. Six-Actor Grammar

Define row roles:

```text
1 low/weight
2 body/knock
3 cavity/formant
4 bite/motion
5 zero/fracture
6 air/extreme
```

For each row give legal Hz ranges, illegal overlaps, pole/zero relationship, corner motion rule, Q/secondary behavior, and failure conditions.

### 3. Four-Corner Rules

Define how to make unique but coherent corners:

```text
M0_S0 = HOME
M1_S0 = AWAY
M0_S1 = TIGHT HOME
M1_S1 = TIGHT AWAY
```

Rules must cover:

- legal HOME→AWAY distance in octaves/Hz
- minimum distinctness
- musical midpoint guarantee
- row identity preservation
- avoiding dead centers
- avoiding pole collisions
- avoiding zero/pole cancellation
- when Q should tighten/deepen/expose/damp instead of moving Hz

Define when to use:

`PIN, CARRY, COUNTER, ORBIT, ZIPPER, POLE_SPLIT, POLE_FUSE, FORMANT_RELAY, KINEMATIC_CROSS`

### 4. 12 Body Blueprints

Give 12 original, non-vendor iconic body blueprints. For each:

```yaml
name:
one_sentence_identity:
best_on:
musical_intention:
corner_logic:
expected_plot:
failure_mode:
M0_S0:
  - row: 1
    actor:
    pole_hz:
    zero_hz:
    zero_role:
    bandwidth_hz:
    gain_role:
    motion_rule:
  - row: 2 ...
M1_S0:
  - six rows...
M0_S1:
  - six rows...
M1_S1:
  - six rows...
why_corners_work:
```

Blueprint requirements:

- Exactly 6 rows per corner.
- Same row identity across all corners.
- Literal Hz values only.
- Use zeros deliberately.
- Stay below `19531.25 Hz`.
- Prefer musical usefulness over academic physical correctness.

### 5. Forge Editing Rules

Give practical rules for a human editor:

- if pole moves up, what happens to zero?
- when rows lock
- when rows cross
- when zero stays remote
- when zero stays local
- when a row becomes comb
- when Q tightens without Hz motion
- visual warnings
- definition of “complete morph”
- why a stable body can still be musically bad

End with:

```text
How To Use This In Forge
```

Give a short checklist for entering six actors, setting four corners, plotting, auditioning, and deciding keeper/reject.
