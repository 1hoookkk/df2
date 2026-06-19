# DF2 Agent Contract

Keep this file short. Its job is to prevent context loss, not to create new
doctrine.

## Current Task Focus

The locked direction is **evidence-derived Morph Designer authoring** — two
frames in, Secondary derived:

```text
real evidence (LPC / physical models / measured tables / clean-room grammar)
  -> two authored Morph frames (LOW + HIGH): six pole+zero lanes each
  -> Secondary/Q DERIVES the PUSH corners (radius/gain only, no frequency motion)
  -> packed .body240 -> trench_core Morph x Q audit -> plot + audio -> Tyson keep/kill
```

Author only the LOW and HIGH frames; the Q100 corners are **generated, never
hand-authored**. Do not turn this into free four-corner painting, a coefficient
editor, a prompt-first body writer, or a new production-training workflow.

**Superseded — study/background only, never the active direction:** Law Author
(`docs/FORGE_LAW_AUTHOR.md`), the `gpt55-pro-*` reports, and free per-corner
editing of the four corners.

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

## The core model (locked)

A df2 body = **two authored Morph frames + a derived Secondary/Q law**.

- A **frame** = six pole+zero lanes (pole Hz/radius, zero Hz/radius, gain). Lane
  *i* of LOW morphs into lane *i* of HIGH — section index is the morph pairing,
  sacred.
- **Poles trace to real evidence** — LPC capture, physical models (tube / vowel
  tract / cavity), measured tables, or clean-room P2K grammar. Never invented or
  random.
- **Secondary/Q is derived, never authored.** It generates the PUSH corners from
  the frames by pressure only:
  - MAY change: pole radius, zero radius / notch depth, section gain, canyon depth.
  - MAY NOT change: pole or zero **center frequency**, lane correspondence, frame
    anatomy.
- **Corners:** `C0 = LOW.Q0`, `C1 = HIGH.Q0`, `C2 = LOW.Q100`, `C3 = HIGH.Q100`.
  Four stored corners; only two authored.

### The invariant that proves the model

At each morph endpoint, the Q0 and Q100 corners share **identical pole/zero
center frequencies**. If Secondary moves a center frequency, the model is broken.
`forge-gpu-painter`'s `pressurize()` enforces this by construction (it touches
radius and gain only); `forge-web`'s freehand per-corner edit predates the lock
and violates it.

### Roles of the machine room (evidence, not the product surface)

- `tools/three_layer_acoustic_forge.py`, `dev/tmp/real_source_surface_rack/` —
  evidence quarry / teacher surfaces. Mine frames from them; do **not** ship
  their direct fits as master bodies.
- QD search (`train.py model=v1`) — overnight candidate finder and audit stress
  test, not the creative center.
- `forge-gpu-painter` — the surface that enforces the locked model.

## Required Verification

A body is real only after its packed **240-byte** artifact passes the
`trench_core` Morph x Q grid audit: 240 bytes exactly, zero unstable and zero
nonfinite rows, every plot and audition generated from packed/runtime-probed
data. Do not claim success until the body is packed and probed through
`trench_core`.

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
