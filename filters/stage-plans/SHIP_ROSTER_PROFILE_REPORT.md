# Ship roster acoustic-profile pass

Date: 2026-07-20

Scope: `ship_iron_mouth` and `ship_riot_plate`; steps 1–3 only. No Q100
authoring, body assembly, promotion, or taste decision is made here.

## ship_iron_mouth

Stage Plan: `ship_iron_mouth.profile-plan.json`

Measured evidence:

- M0_Q0: DVTD `s1-01-bahn-tense-a`, SHA-256
  `c16082af4fffed4e15b5612753f41e786bdc01f6f83e24aee18d8a112f17f575`
- M100_Q0: DVTD `s2-03-tiere-tense-i`, SHA-256
  `d9e5c0601b915bcf7363494759da3da81966536db3c0725fe9e2cc802d25e0cc`
- Extraction: raw measured magnitude converted with `20*log10`, cropped to
  55–10500 Hz; no smoothing or normalization was written into the TF evidence.

Observed result:

- M100_Q0: PASS through the packed-runtime profiled fitter. Raw-source-grid
  residual RMS 6.65 dB, max absolute residual 23.32 dB. On the profiler's
  256-row optimization grid, weighted RMS changed 8.81 -> 6.99 dB and plain
  RMS changed 8.33 -> 7.41 dB. This is an achieved upper bound, not a format
  limit or a promotion verdict.
- M0_Q0: `REFUSED_MISSING_REGISTERED_FEATURE`. With the macro lane owning the
  low vowel resonance, the measured residual does not provide a fifth distinct
  certifying mountain inside the five shared authored pole boxes.

Rejected diagnostic: assigning 180–600 Hz to residual slot 1 made M0_Q0
mechanically fit, but double-spent one feature as a 672.7 Hz macro pole and a
599.9 Hz residual pole. M100_Q0 then refused. That plan was replaced; no band
was widened and no duplicate/borrowed feature was accepted.

Disposition: do not assemble a new Iron Mouth body from this profiling pass.
Source either a different measured M0 endpoint that supplies all five residual
roles after macro peeling, or deliberately redesign the shared lane plan and
re-run both endpoints.

## ship_riot_plate

Stage Plan: `ship_riot_plate.profile-plan.json`

Evidence trace: the candidate resolves to the analytic
`recipe_metal_bell_to_free_plate.json` and published/analytic metallic modal
ratios. No measured endpoint transfer functions were found in its evidence
chain.

Observed result: `REFUSED_NO_MEASURED_TF`. The old packed body and the recipe
were not rendered into pseudo-measurements, because fitting those would be
circular evidence.

Disposition: keep Riot Plate on the direct
physics/tables -> registered lanes -> `trench-core` pack path. To exercise the
acoustic profiler instead, source measured bell and free-plate impulse responses
with reproducible provenance.
