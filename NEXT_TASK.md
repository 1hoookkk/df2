# Next session — one focused task

**Build the measured-object body factory as a real tool, and use it to make
the first SIMPLE-EFFECTIVE presets.**

Ear-gate first: Tyson's verdict on `WOODMETAL_violin_to_storm_E` (render +
plot delivered 2026-07-25). Direction was approved at variant C ("Hey there
we go"); E adds the measured low shelf + flat-off-resonance sections.

## The task

**Tyson's diagnosis of variant E (verbatim ground truth): "The gap is that
they are just peaks. Nothing else."** A body is not peaks on a flat line —
every E-mu row carries a pole AND an independent zero (L6: they disagree by
1.75 oct on average). The extraction must deliver the FULL anatomy: poles,
antiresonances/notches, tilt — the violin IR's deep notches are measured and
were thrown away.

1. **Time-domain modal ID for poles** (matrix pencil / Prony on the IR) AND
   **zero recovery** (phase-aware rational fit — the DVTD
   Sanathanan-Koerner fitter in `filters/rails/dvtd_rails.py` already does
   this; point it at the IRs). Test: recovers the violin's ~1.27 kHz main
   mode AND its two deep notches near 2-3 kHz.
2. **One permanent tool** (extend `tools/tf_ingest.py`, do not fork): IR in →
   6 rows each with pole + independent zero + scale. Never pure resonators
   (bury each other — variant D), never bare peak EQs (just peaks — variant E).
3. **Author 2–3 SIMPLE-EFFECTIVE bodies with it** (Tyson 2026-07-25: "starting
   to prefer the more simple but effective presets... there might be more for
   the user in those"): bass-shaper/sweep archetypes — shelf + few peaks,
   slide-the-stack travel (L11 sweep mechanism), framing L10 from birth,
   all four poses authored (L1). One at a time to the ear.

## Standing context

- Framing law L10 + tool: `dev/tmp/framed_cavl/frame_cavl.py` (21 CAVL bodies
  framed, first A/B pair judged "boring" — cavity sources, not the law).
- Dominance L11: characters = stage handoff, sweeps = slide the stack.
- Working pipeline + variants A–E: `dev/tmp/wood_metal_storm/`.
- Source pool: `wav-source-library/measured_objects/` (IR library MIT:
  cymbals, violin, ukulele, piano, kalimba, steel pan, glockenspiel;
  OpenAIR rooms: mine, tunnel, cathedral) + modal tables.
