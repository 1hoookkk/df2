# Stage logic — how the six stages actually behave

Measured across 200 P2K variant bodies through the shipped engine. (No invented
Hz here; frequencies live in doc 04.)

## The six stages are correspondence slots, not fixed lanes

Stage `i` of HOME only ever blends with stage `i` of AWAY / PUSH HOME / PUSH AWAY.
The slot is a registration channel. **It is NOT a fixed frequency lane** — "stage 1
= the lowest pole" is only true about a third of the time:

| stage order | share of 200 variants |
|---|---:|
| strict low -> high | 29.5% |
| mostly ascending (<=1 swap) | 11.5% |
| strict high -> low | 5.0% |
| scrambled / clustered | 54.0% |

So **do not assume stage number = frequency rank.** 54% pack their stages into
clusters or reverse them. Two whole families (deep_bouche, dream_weava) run strictly
high -> low. Read the actual frequency, not the slot index.

## Every stage carries a zero

Every sampled row has numerator structure: **7,200 of 7,200**. A pole-only stage is
incomplete. If a stage is active, it has a notch as well as a peak.

## A stage's pole and zero move independently

Across the Morph/Secondary surface, a stage's pole and its zero move by **different
amounts — mean disagreement 1.75 octaves**. The notch is NOT glued to the peak.
That independent motion (the cut sliding away from the resonance) is where most of
the character and violence comes from.

## The four packed variants are pitch transpositions

A family's 4 `.bin` variants are mostly the SAME grammar scaled in pitch. Median
pole-frequency ratio vs variant 0:

| variant | ratio |
|---|---:|
| 0 | 1.00 |
| 1 | 0.92 |
| 2 | 0.46 |
| 3 | 0.23 |

So variants ladder the whole constellation down in lock-step — they are not four
different designs.

## Sub-200 Hz pole fusion is allowed

Stages fusing below 200 Hz at the endpoints is a real source of broad low mass, not
an automatic bug. Inspect it on the plot; don't reject it by rule.
