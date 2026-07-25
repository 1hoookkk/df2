# Next session — one focused task

**Build the measured-object body factory as a real tool, and use it to make
the first SIMPLE-EFFECTIVE presets.**

Ear-gate first: Tyson's verdict on `WOODMETAL_violin_to_storm_E` (render +
plot delivered 2026-07-25). Direction was approved at variant C ("Hey there
we go"); E adds the measured low shelf + flat-off-resonance sections.

## The task

1. **Replace peak-picking with time-domain modal ID** (matrix pencil / Prony
   on the IR): exact mode freq + damping, no grids, no prominence heuristics.
   Test it must pass: recovers the violin's ~1.27 kHz main body mode that
   spectral peak-picking missed (`dev/tmp/wood_metal_storm/build_variant_c.py`).
2. **One permanent tool** (extend `tools/tf_ingest.py`, do not fork): IR in →
   modes (pole freq/bandwidth), measured tilt (shelf), strongest notches
   (zeros) out — sections as flat-off-resonance RBJ (peak/shelf), never pure
   resonators (they bury each other in the serial cascade — re-proven
   2026-07-25, variant D).
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
