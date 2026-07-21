# df2 — Hz Placement Pack (for NotebookLM)

## The goal

Help you **create presets** without ever placing a pole or zero at a random or
invented frequency. Ask it "where do the poles and zeros go for a [vowel / tube /
metal / aggressive] body" and it answers in **measured Hz**, with the **stage
logic** and **fundamentals** behind the answer. It's a placement oracle, not an
encyclopedia.

## HARD RULE: never invented Hz

Every frequency is **measured** (the rails, through `trench_core.dll`) or
**published** (the vowel / tube / metal tables). No band, no approximated range,
no guessed number. NotebookLM only answers from its sources, so this rule + that
behavior mean it **cannot** hand you a made-up Hz.

## Read in this order

1. **00_packed_body_format** — what a body IS: 240 bytes = 4 corners x 6 stages x 5 packed words.
2. **01_stage_logic** — how the 6 stages behave: correspondence slots (not fixed lanes — order is scrambled 54% of the time), every stage has a zero, pole and zero move independently (1.75 oct), variants are pitch transpositions.
3. **02_fundamentals** — how to build: the six-stage actor program, the two zero roles (local 58.5% / remote 28.2%), base shapes, motion posture.
4. **03_placement_by_intent** — THE answer: where the poles and zeros go, in Hz, for vowel / tube / metal / aggressive bodies, and how each moves.
5. **04_frequency_rails** — the measured data: where poles/zeros actually land, grouped by physical model (vowel / tube[open|closed] / metal).
6. **05_physics_anchors** — published vowel / tube / metal frequencies.

## Ask it like this

- "For a vowel body, where does F1 sit and where do the zeros go?"
- "Tube body — open vs closed, what frequencies?"
- "Is stage 1 always the lowest pole?" (no — 54% are scrambled)
- "How do I make it aggressive without just turning up gain?"
- "Where do remote-cut zeros land relative to their pole?"

Clean-room: frequencies and structure only. No packed words, no coefficients, no
shippable bodies. Built from the P2K study fixtures via the shipped engine.
