# METHOD.md — the authoring model, one page

Written 2026-07-04, the night it clicked. This is the answer to "what do I
actually DO to make a body." If a session makes Tyson re-explain any of this,
that session has failed. Figures: `out/method_primer/*.png`.

---

## The model (four lines)

1. **8 letters** — a lane (stage) is one of 8 shapes: PEAK, CUT/notch,
   LO-shelf, HI-shelf, LP, HP, deep-low zero, near-Nyquist zero (+ parked =
   flat). A lane's 5 numbers (pole Hz/r, zero Hz/r, gain) cannot make anything
   else. `out/method_primer/lane_alphabet.png`
2. **A 6-letter word, written twice** — authoring = the 12 rows: 6 lanes at
   the LOW frame, the same 6 lanes at the HIGH frame. ~36 numbers, most
   pre-filled from measured data. Lane i LOW ↔ lane i HIGH is the same
   physical object; the pairing IS the morph choreography
   (`lane_pairing_demo.png` — same endpoints, different pairing = different
   filter).
3. **4 photographs** — all four corners are AUTHORED poses of one instrument
   (Q amendment 2026-07-10, df2/LAWS.md L25 — the "compiler derives Q" era is
   over; measured ROM Q relocates centers in every reference).
4. **2 knobs** — MORPH slides each lane between its two poses; Q plays the
   body's authored second scene, one named verb per body: BLOOM (radii →
   ~0.999, centers hold) / SPREAD (talker cluster fans apart) / SCREAM (one
   slot parks low+hot, gain word up) / FLIP (the frame changes register).

Why stages aren't bookkeeping: in dB a serial cascade is ADDITION — the body
curve is the sum of 6 simple lane curves (`vowel_decomposition.png`, the real
oo→ah body taken apart). At a frozen knob, order is irrelevant; in motion,
lane identity is everything.

## The 4 ship filters, spelled (manual quotes = archetype behavior)

| filter | spelling | archetype one-liner (Mo'Phatt manual) |
|---|---|---|
| Vowel/Morph | PEAK×3 formant rails + CUT×1–2 measured zero rails + shelf | TalkingHedz: "Q adds peaks" |
| Fuzz | one razor PEAK (driver → saturator) + HP + near-Nyq zero | FuzziFace: "Q functions as mid-frequency tone control" |
| Violent | PEAK×4–5 mid spray + HP | LucifersQ: "Violent mid Q! care with Q 40-90" |
| Q-bloom/Bright | body-vs-needle PEAK contrast / PEAK comb + air zero | MeatyGizmo: "inverts at mid-Q" / DJAlkaline: "Q shifts ring frequency" |

Order column in the ROM table = lane budget: 06-order bodies are 3-lane words
(AahAyEeh, FlangerLite "contains three notches"). Small words are legitimate.

## Where the numbers come from (never invented)

Poles/zeros measured: DVTD rails (vowel, incl. zero rails for bite), HRTF
(Alkaline), circuit sim (Fuzzi, pending), modal sim (Lucifers/Meaty, pending).
Klatt/table proof: `df2/dev/tmp/vowel_from_tables/` (<1% formant placement) —
NB rename before bank, "Ooh-To-Aah" is a ROM preset name.

## Division of labor (the parallel-session reconciliation)

- **Model/compile** = morph_designer lineage (CLARITY.md law; SHAPE/FREQ/GAIN,
  per-shape Q law). `df2/tools/morph_designer.py` — COMMIT IT, it's untracked.
- **Surface/judgment** = forge-gpu-painter (plot==engine, live audition,
  KEEP gate). Its internal peak_shelf `pressurize()` compiler is the dead-end
  part, not the app.
- **CLOSED 2026-07-10 — the Q100 law**: Q corners are AUTHORED, never derived
  (df2/LAWS.md L25). The three competing radius formulas were all answers to
  the wrong question; the measured 0.356 bandwidth transpose survives only as
  the BLOOM verb's starting pose. Derived-Q tooling (QLINK, pressurize) =
  helpers for one verb, not the law.

## Baseline-Q per filter (deliberate, not one rule)

Vowel damped at rest (r≤0.99, headroom to bloom) · Fuzz HOT at rest (driver
pole stays sharp) · Lucifers moderate→violent · Meaty/Alkaline moderate→razor.
The filter never clips itself: it aims resonant gain at the engine saturator.
