# Rail Stitcher — design spec

2026-07-01

## Problem

Filter-body authoring is bottlenecked two ways at once:

1. Only 2 of 7 measured data wells (`vocal/dvtd`, `hrtf`) have been mined into
   pole/zero rails. The other 5 (`circuit`, `modal`, `simulators/k-wave`,
   `phononic`, `aeroacoustic`) sit unprocessed in
   `C:\Users\hooki\trench-filters\data\`.
2. The existing authoring tool (`shape_zero_forge.py` + `shape_forge.html`,
   in `C:\Users\hooki\surface-forge\`) already implements the right model —
   pick a LOW shape, pick a HIGH shape (poles locked, math-perfect, from
   tables), edit only the zeros — but the "shape" is a fixed dropdown of a
   handful of hand-authored families (vowel/tube/cavity/riser/metal). There's
   no way to browse multiple candidate rails within a well, audition them
   quickly, and pick which two become a body's LOW/HIGH.

Net effect: not enough mined candidates, and no fast way to judge the ones
that exist. "The only way we get usable presets" is fixing both.

## What this is NOT

- Not a generative/ML body-builder. No invented poles (CLAUDE.md §7).
- Not a change to the packed-math kernel, the compiler, or `compile_lanes`.
- Not (yet) the DL preference/ranking model. That depends on swipe data
  existing first — parked as an explicit future phase, not designed here.
- Not a fix for the `compile_body` / `GAIN_MAX` clamp bug found in the
  2026-07-01 compiler audit (`dev/tmp/packed_math_dup_audit_20260701.md`).
  That bug lives in `surfaceforge/export/body.py` / `fit/*.py`, a different
  call path than the one this tool uses (`shape_zero_forge.build()` →
  `morph_designer.compile_lanes`, confirmed clean). Tracked separately.

## Model (unchanged, restated for this spec)

- **Poles are locked, math-perfect, measured** — never authored by hand, never
  invented. They come from a well's mined rail.
- **Zeros are the operator's to edit** — ratio/depth multipliers per lane, as
  `shape_zero_forge.py` already does.
- **LOW/HIGH pick = what Morph does.** The operator chooses which two rails
  (same well or different wells) become the two authored corners. This is
  the creative act; the tool does not auto-assign it.
- **Q100 is derived, never authored** (CLAUDE.md §6) — but the derivation
  law's aggressiveness (how hard Secondary presses, i.e. the target pole
  radius at Q100) becomes an exposed control, since the baseline-Q policy is
  already known to be per-filter (REFERENCE.md).

## Architecture

Two additive layers on top of existing, working code. Nothing here forks or
replaces `trench-core`, `compile_lanes`, or the packed-runtime engine.

### 1. Extraction layer (per well)

One script per well, following the proven `dvtd_rails.py` / `hrtf_rails.py`
pattern: shared SK-fit core (`dvtd_rails.py` owns `fit_one`/`fit_model`/
`baseline_cap`; every other well's script imports it, no duplicate kernel).
Each script's only job is turning that well's raw data into a complex FRF,
then handing it to the shared fitter. Output shape matches the existing two:
`out/{well}_rails/{well}_rails_trench_runtime.json` + contact sheet + plots.

Sequencing (risk-ordered, not one big phase):

| well | status | why this order |
|---|---|---|
| vocal/dvtd | done (44 rails) | — |
| hrtf | done (48 rails) | — |
| phononic | data present (CSVs) | parsing job, not a sim — low risk |
| aeroacoustic | data present (H5/CSV) | parsing job, not a sim — low risk |
| simulators/k-wave | needs a sim run | medium — general tube/cavity, well-scoped |
| circuit | needs a sim (chowdsp_wdf) | open-ended — what topology to model is itself a design question. Separate follow-up spec. |
| modal | needs a sim (neuralresonator) | open-ended — what strike/excitation to generate is itself a design question. Separate follow-up spec. |

The gallery/stitcher UI (below) is built and usable against the 92 rails that
already exist. Each further well drops into the same gallery the moment its
script lands — no big-bang dependency.

### 2. Gallery + Stitcher UI

Extends `shape_forge.html` / `shape_zero_forge.py` (`forge_server.py` already
serves it) rather than building a new app — reuses existing plot rendering,
audio preview, and pack/gate plumbing.

- **Well picker** replaces the fixed family dropdown.
- **Rail gallery**: inside a well, a scrollable/swipeable list of every rail
  in that well's JSON — mini dB-vs-Hz plot (Tyson judges by plot) + one-tap
  audition on pink noise per rail. Swipe/star marks a rail as a candidate.
  This is the "data at my fingertips" piece — browsing, not a fixed table.
- **Stitch**: pick one starred rail as LOW, one (same or different well) as
  HIGH. Calls the same `build()`-shaped path `shape_zero_forge.py` already
  uses: poles locked from the two rails, zeros default to the rails' own
  zeros but stay editable per lane (existing `zedits` mechanism), body
  compiled via `compile_lanes` (confirmed clean path).
- **Q-bloom control**: one slider per stitched body, parameterizing the
  existing baseline-Q derivation law (`bandwidth = f/Q`, `r_pole =
  exp(-pi*bandwidth/SR)`, CLAUDE.md §8) — i.e. how hard Secondary presses at
  Q100. Does not touch pole/zero center frequencies at either Morph endpoint
  (Secondary-center-invariant, per CLAUDE.md §6/§9).

## Data flow

```
well's raw data (data/{well}/)
  -> {well}_rails.py (thin front-end + shared SK-fit core)
  -> out/{well}_rails/{well}_rails_trench_runtime.json  (many candidate rails)
  -> gallery UI reads all *_rails_trench_runtime.json files across wells
  -> operator swipes/stars candidates
  -> operator picks starred[LOW], starred[HIGH] (+ Q-bloom target)
  -> shape_zero_forge.build()-equivalent: poles from the two rails (locked),
     zeros = rail defaults (editable), compile_lanes -> packed 240-byte body
  -> existing gate() / runtime probe / render_png audit (CLAUDE.md §9-§13)
```

## Testing / gates

No new packed-math surface is introduced, so the existing required-tests list
(CLAUDE.md §12) applies unchanged to any body the stitcher produces:
240-byte serialization, corner order, Secondary-center invariant, lane
correspondence, packed-runtime plot generation, Schur stability over grid,
nonfinite rows = 0. New surface specific to this tool:

- Each `{well}_rails.py` script: rail JSON schema matches
  `dvtd_rails_trench_runtime.json`'s shape (so the gallery UI is generic
  across wells, not per-well special-cased).
- Gallery UI: swiping/starring a rail does not mutate the underlying rail
  JSON (read-only browse; stitched output is a separate artifact).
- Stitcher: `pole_words_locked()` (already exists in `shape_zero_forge.py`)
  must return true after any zero edit or Q-bloom change — poles never move.

## Open questions / explicit parking lot

- DL preference/ranking model trained on swipe data — parked until swipe
  data exists from real use of the gallery.
- Circuit and modal wells — parked as their own follow-up specs (simulation
  approach is itself a design decision, not just an extraction script).
- `compile_body` / `GAIN_MAX` clamp bug in `surfaceforge/export/body.py` and
  `fit/*.py` — tracked separately, does not block this tool.
