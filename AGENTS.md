# DF2 Agent Contract

Keep this file short. Its job is to prevent context loss, not to create new
doctrine.

## Current Task Focus

The active Forge direction is **Law Author**:

```text
small law source -> six root-domain stages -> packed .body240 -> trench_core audit
```

Do not turn this into a coefficient editor, a prompt-first body writer, or a
new production-training workflow.

## Runtime Facts

- A body is exactly `240 bytes = 4 corners x 6 stages x 5 packed words x 2`.
- The packed runtime has **six stages total** per corner.
- Do not infer a hidden seventh stage from diagrams such as
  `1 lowpass + 6 parametric EQ sections`.
- Stage index is runtime correspondence across corners. It is not proof of a
  fixed musical role or low-to-high order.
- Zeros are first-class: every authored stage must expose pole Hz/radius, zero
  Hz/radius, and gain.
- `.body240` plus compiled cartridge JSON is the runtime artifact. Plots and
  auditions must be generated from packed/runtime-probed data.

## Law Author Rules

Law Author source lives in `docs/FORGE_LAW_AUTHOR.md`.

The law source should expose a small set of controls:

- anchor Hz and gain
- spectral tilt / high restraint
- canyon depth
- Q crank amount
- Morph spread
- density/richness

These controls compile to exactly six stage lanes at all four corners. The UI
may call a measured envelope a "foundation", but that is an authoring view, not
a hidden runtime stage.

## Required Verification

Every generated Law Author body must pass:

```powershell
python tools/law_author.py --preset hedz_like_anchor_canyons --out dev/tmp/law_author/golden_hedz_like
```

The command must emit:

- `law_source.json`
- `.body240`
- compiled cartridge JSON
- packed-runtime audit report
- response plot sheet

Do not claim success until the body is packed and probed through `trench_core`.

## Boundaries

Production authoring remains separate:

```powershell
python train.py model=v1
python scripts/export.py <verified-run-directory>
python scripts/verify_run.py <verified-run-directory> --promotion-dir <promotion-directory>
```

Do not use production training files to justify Forge behavior unless the task
explicitly asks about production authoring.

Reference bodies and P2K material are study evidence only. Study shapes and
derive laws; do not copy protected bytes, names, coefficient tables, or preset
tables into shipping bodies.

## Communication

Use evidence labels when claims are uncertain:

- `OBSERVED`: file, test, plot, or runtime output proves it.
- `INFERRED`: likely and useful, but not proven.
- `UNKNOWN`: not known yet.
- `REJECTED`: contradicted by current evidence.

Prefer short answers and concrete next steps. If the issue is a missing plot,
broken path, stale build, or bad assumption, fix that before writing more theory.
