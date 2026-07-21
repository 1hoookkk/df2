# Registered lanes — the authoring IR

`.geometry.json` is compiled output, not the authoring model. The registered-lane
document is the first-class IR between source evidence and geometry:

```text
source catalog
  -> per-corner candidate features
  -> registered_lanes.json      (this layer)
  -> geometry.json              (emit)
  -> body240                    (pack, via tools/filter_cli -> trench-core)
```

A body is a six-lane animation with four keyframes. Lane identity is stable
across all four corners (`M0_Q0`, `M100_Q0`, `M0_Q100`, `M100_Q100`). The tool
never sorts, matches, repairs, normalizes, derives Q100, or changes root
topology — it validates what was authored and refuses everything else.

Contract: `filters/registered-lanes.schema.json`. Tool: `tools/register_lanes.py`.

## Document shape

```jsonc
{
  "schema_version": 1,
  "name": "my_body",
  "corner_order": ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"],   // fixed
  "secondary_axis": { "authored": true, "note": "how Q100 was authored" },
  "source_catalog": null,          // optional path to a source-catalog json
  "stage_plan": [                  // exactly 6, slot i = stage order i
    {
      "slot": 0,
      "lane_id": "f1_ridge",       // stable identity across all corners
      "role": "F1 ridge",          // musical role, human words
      "law": "local_peak_notch",   // see `laws` below
      "topology": "conjugate",     // or "real_pair" (IR-only, refused at emit)
      "pole_zero_relation": "zero co-located just under the pole",
      "law_params": { "colocate_max_octaves": 0.5 },   // inspectable thresholds
      "analysis": {                    // optional; required on all lanes for profiling
        "source": "macro_body",        // slot 0 only; slots 1..5 use "residual"
        "pole_band_hz": [55, 300],     // hard feature-search ownership
        "zero_band_hz": [55, 500],
        "pole_radius": [0.0, 0.98],    // hard optimizer bounds
        "zero_radius": [0.05, 0.98]    // positive minimum means notch must survive
      },
      "limits": {                  // continuity across adjacent Morph/Q edges
        "max_pole_octave_step": 3.0,
        "max_radius_step": 0.5,
        "max_scale_step_db": 24.0  // any of these may be null to disable
      }
    }
  ],
  "lanes": {
    "f1_ridge": {
      "assignments": {             // all four corners, exactly this order
        "M0_Q0": {
          "state": "active",       // or "identity" (EXACT identity biquad)
          "candidate": {
            "catalog_record": "workspace-tmp-...",   // or null
            "selector": { "frame": 12 }              // whatever reproduces extraction
          },
          "pole": { "hz": 700.0, "r": 0.97 },        // or {"real_roots":[a,b]}
          "zero": { "hz": 735.0, "r": 0.95 },
          "scale": 1.0,                              // SCALE = b0, (0, 4]
          "provenance": { "source": "...", "method": "..." }   // required
        }
        // M100_Q0, M0_Q100, M100_Q100 ...
      }
    }
  }
}
```

## Acoustic-profiler analysis

`analysis` is optional for inspection-only/manual IRs. If any lane declares it,
all six must declare it. Slot 0 owns the low-order `macro_body`; slots 1–5 own
features in `measured TF - fitted macro body`. Pole and zero bands are hard
authored bounds: the profiler refuses a missing feature instead of borrowing one
from another lane, sorting lanes, or guessing a replacement band.

After macro/residual feature extraction, the Rust profiler performs bounded
analysis-by-synthesis. Each coordinate proposal is encoded to packed words,
decoded through the runtime path, checked against the exact Stage Plan boxes,
then scored on 256 logarithmic rows. The cost weights 1–5 kHz by 2x, narrow
positive overshoots by another 5x, and content outside 60 Hz–10 kHz by 0.2x.
An accepted move must lower weighted RMS without increasing plain RMS above the
packed seed. The macro lane remains fixed; only residual pole/zero frequency,
radius, and distributed cascade gain are refined.

Run one measured corner through those bounds with:

```powershell
target\release\fit-candidates.exe corner.tf.json corner.fit.json --stage-plan body.registered_lanes.json
```

## Laws

The law vocabulary follows the section-type grammar (`filters/grammar/typed_vowl.py`):

| law | meaning |
|---|---|
| `local_peak_notch` | pole+zero co-located (Type 1); `colocate_max_octaves` (default 0.5) |
| `high_zero_cliff` | zero on the high rail (Type 2); `min_separation_octaves` (default 0.5) |
| `low_zero_sub_cut` | zero on the low rail (Type 3); `min_separation_octaves` (default 0.5) |
| `free` | no geometric constraint beyond the runtime contract |

Thresholds are stage-plan data, not hidden heuristics — edit them per lane.
Laws apply to active conjugate corners only; identity corners are exempt.

## Validation rejects

Missing/duplicate/reordered lanes · wrong corner order · slot identity changes ·
silent conjugate/real conversion (topology must match the plan) · real-root
lanes entering conjugate-only geometry (refused at emit, never projected) ·
derived Q100 (`secondary_axis.authored` must be `true` with a note) · inexact
identity (must be pole 0/0, zero 0/0, scale 1.0 exactly) · nonfinite geometry ·
pole radius > 0.9999 or hz > 19531.25 · scale outside (0, 4] · missing
provenance · unknown catalog records · `study_reference` records used as
numeric body evidence · law violations · continuity-limit violations across the
four adjacent Morph/Q edges.

## Commands

```text
python -m tools.register_lanes new      NAME [out]        # editable 6x4 template
python -m tools.register_lanes wrap     x.geometry.json   # import as free-law doc
python -m tools.register_lanes validate x.registered_lanes.json [--catalog cat.json]
python -m tools.register_lanes emit     x.registered_lanes.json [out.geometry.json]
python -m tools.register_lanes pack     x.registered_lanes.json [out.body240]
python -m tools.register_lanes laws
python -m tools.test_register_lanes                       # the test suite
```

`emit` writes canonical geometry (schema-valid, stage order preserved, canonical
stage keys only) plus the stage plan and per-corner provenance under the
`registered_lanes` top-level key. Emission is deterministic — identical input
yields byte-identical output. `pack` emits to a temp file and delegates to
`python -m tools.filter_cli pack`; there is no second compiler.
