# TRENCH — compiled project context (for NotebookLM)

Excerpts from the project's load-bearing documents, compiled 2026-07-17.
Sources: GPT_PRO_SYNTHESIS.md (2026-07-09, the settled constitution),
FILTER_NOTEBOOK.md (2026-07-17, the live method + measurements), plus the
2026-07-17 measured sweet-spot atlas and engine-lineage findings.
Where the two disagree, the later MEASUREMENT wins — see "Corrections" at the end.

---

## I. The constitution (settled law — from GPT_PRO_SYNTHESIS)

1. Body = **240 bytes = 4 corners × 6 stages × 5 packed u16.** Six stages, no 7th.
   Corner order M0_Q0, M100_Q0, M0_Q100, M100_Q100. No 8-corner cube (destroyed
   by design review: dimensional mismatch with the 2D product).
2. **MORPH = frequency, and it's LOGARITHMIC** — morph interpolates packed codes,
   so pole 400→4000 lands at 1274 Hz (geometric mean) at morph 0.5. All travel in
   octaves, never Hz deltas.
3. **Zeros are first-class and mandatory.** A large share are remote counterweights
   (>1.5 oct from their pole), not local. Carved zeros = "authored valleys."
4. **Poles are grounded, never invented/random** — formants (Peterson-Barney/Klatt),
   pipe/Helmholtz/modal laws, or Bark/ERB skeletons. Randomness only at program level.
5. **ONE encoder / one compiler.** A single owner compiles roots+SCALE to packed
   words; byte parity is a gate. (Rogue encoders once diverged 59 dB.)
6. **The packed MIDDLE is the product, and it's not invertible** — you author, you
   don't reconstruct. Endpoint beauty is cheap; bodies fail at the bilinear middle.
   plot==engine.
7. **Gain: flat-ended sections, not a trim.** Stacked all-pole sections crater the
   response; sections must sit at 0 dB off-resonance. Unity DC (never boost sub);
   survival gate across the whole Morph×Q grid, not just 4 corners.
8. **Distortion is NOT in the body** (6 linear biquads). Drive belongs to the
   playback chain.
9. **AI proposes lawful material + plots + warnings; the HUMAN approves.**
   Plot-first, ears-last. No ranking-as-keeper.
10. **Clean-room:** reference/vendor material = study-only; never reproduce bytes,
    rows, trajectories, or names.
11. **Firewall:** the authoring tool (sees poles/zeros/stages) is internal; the
    player product exposes only Body / Morph / Q / Output.

## II. The authoring model (from GPT_PRO_SYNTHESIS)

- Everything compiles to **6 pole+zero lanes**. The stack: chaptered bench UX
  (FIND→MORPH→BEND→PROVE→KEEP) → material drawers (Weight/Mouth/Teeth/Wire/Air,
  graded by provenance) → constructor-based authoring with center+throw as the
  edit gesture → the one-owner flat-section compiler → judged on the full
  Morph×Q plate (plot + clean/driven ear).
- Role vocabulary for lanes: ANCHOR / MOVER / TEARER / BLOOMER; motion verbs
  (PIN, CARRY, COUNTER, ORBIT, ZIPPER, POLE_SPLIT, POLE_FUSE, FORMANT_RELAY,
  KINEMATIC_CROSS) are labels layered on the same 6-lane model.

## III. The method that converged (from FILTER_NOTEBOOK, 2026-07-17, advisor-audited)

**New body = ROM archetype anatomy ⊗ measured rails.**
1. Decode the family's archetype through the stage law (packed words → per-lane
   pole/zero/scale geometry). Frame lanes are copied VERBATIM.
2. Moving lanes keep the archetype's zero-offset (octaves), radii, and scale —
   only the pole CENTER is re-railed to measured table frequencies.
3. Q100 corners inherit the archetype's own per-lane Q0→Q100 transform (measured
   per body — the corpus has NO universal Q direction).
4. Lane order = archetype lane order (stage correspondence is real and tested).
5. Compile through the one compiler with a 25×25 packed-grid stability certification.
6. Gate: bloom in the empirical band; corner + morph-sweep transfer functions vs
   the archetype on a shared scale.
7. Ear on broadband material. The ear is the only pass/fail.

**Corner law:** a body is 4 AUTHORED poses (M0/M100 × Q0/Q100). Q corners are
authored, never derived — radius-only lerp cannot make a real Q corner; measured
Q moves resonance centers. Corners sit on a ~0 dB floor with crowns −3..+27 dB.
Stage slot i pairs across corners (permutation-invariant per corner,
interior-defining across corners) — never score a fit on endpoints only.

**Measured-source corner method (best for NEW families):** each corner is its own
pose from its own measured source — WAV capture → LPC → poles; magnitude target
(e.g. HRTF) → fitted corner; packed and certified on a 25×25 grid.

**Judging chain (cheapest first):** transfer-function views from the PACKED
runtime only (never design math): corner plots, 21-pose morph sweep, Q-bloom
family → then ear on broadband material (pink noise or a groove; a bare 808
masks everything above the first resonance).

**Dead ends (do not resurrect):** legacy compile_body for authoring (gain clamp
wrong); derived-Q tooling as law; endpoint-only fit scoring; rule-synthesized
generate→audition decks.

## IV. Measured reality (the corpus numbers, 2026-07-17)

- Ground truth = 33 measured factory bodies (the P2K ROM corpus), read-only.
- **ROM zero grammar** (n=198 lanes): 72% independent zero rails, 23% near-pole,
  5% parked.
- **Q-bloom calibration:** max pointwise dB rise Q0→Q100 over 5 poses, measured
  on all 33 ROM bodies = **13.9–254 dB, median 71** (pointwise metric).
- **Secondary/Q law (measured):** Q MOVES resonance centers (median |shift|
  0.58 oct, zero net direction — a scatter, not a law); radius transform
  r → r^0.356; coherent transpose is the bloom lever.
- **Sweet-spot atlas** (777 conjugate-pole lanes across all corners of all 33
  bodies) — five recurring pole/zero motifs:
  1. **The tooth** — zero riding its pole (~0 oct offset), slightly shallower
     (pole r≈0.978, zero r≈0.95): narrow vocal boost, no shoulder mud. n=164.
  2. **The trailing zero** — deep zero ~0.6 oct BELOW the pole (zero r≈0.97):
     formant behavior; peak sings, the octave under it is pre-scooped. n=93.
  3. **The leading zero** — zero ~0.9 oct ABOVE (r≈0.94): every peak carries its
     own de-esser; sweeps sound expensive, not screechy. Most common motif, n=227.
  4. **The far rail** — zero ~3 oct away: broadband tilt/gain-staging skeleton. n=238.
  5. **The true notch** — zero r=1.0, typically ~+1.7 oct above a modest pole:
     combs, phasers, hollow vowels. n=153.
- **Radius-vs-frequency law:** poles tighten low, loosen high — median r≈0.99
  under 800 Hz, ≈0.983 in the mids, ≈0.968 above 8 kHz. Inverting this yields
  the piercing "cheap digital" sound.
- **QC metric convention:** corner "floor" = MEDIAN dB of the packed transfer
  function (target ~0), "crown" = max dB; grid must extend to near-Nyquist or
  rising-tilt corners are invisible.

## V. Engine lineage (why the format is locked)

- The engine interpolates NON-LINEARLY ENCODED (perceptual: log-frequency,
  log-resonance) coefficients per sample, then decodes — this is why morphing
  sounds musical rather than like crossfaded presets. The coefficient ramp must
  be slower than the filter's own ring time.
- Correctness is established by null-testing against the reference engine.
- The vendor's own later software generation SIMPLIFIED the architecture:
  3 active stages (vs 6), 2 corners (no Q axis), zeros from a 16-entry
  depth-only lookup, morph quantized to 16 steps. The generation we hold is the
  musical peak of the lineage; the only thing above it (the 1993 8-corner cube,
  trilinear) can be layered ON TOP of the locked 240-byte format later — a cube
  is two bodies plus a crossfade; bilinear is a slice of trilinear.
- The market (2024–2026) contains no shipping anatomy-morphing filter plugin;
  demand threads have persisted for 15+ years.

## VI. Corrections — where later measurement overrules the constitution

1. Constitution said "SECONDARY/Q = pole radius, freq-locked — Q must not move a
   center." **Overruled by measurement:** real ROM bodies MOVE resonance centers
   under Q (median 0.58 oct). Q corners are authored photographs, not radius edits.
2. Constitution said "Q blooms 6–34 dB." **Metric superseded:** with the pointwise
   measure the empirical ROM band is 13.9–254 dB (median 71). Do not gate with the
   old number against pointwise measurements.
3. Constitution's "no 8-corner cube" stands for the PRODUCT surface (2D Morph×Q),
   but the cube remains a valid future container of locked bodies (see §V).
