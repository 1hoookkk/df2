# DF2 Agent Contract

Keep this file short. Its job is to prevent context loss, not to create new
doctrine.

## Current Task Focus

The locked direction is **evidence-derived Morph Designer authoring** — four
authored poses (Q AMENDMENT 2026-07-10, Tyson "we need law"; LAWS.md L23-L27):

```text
real evidence (LPC / physical models / measured tables / clean-room grammar)
  -> FOUR authored corner poses (M0/M100 x Q0/Q100): six pole+zero lanes each
     (frame anatomy: crown @1, floor + unit zero @6, talkers 2-5 — L23)
  -> Q100 = an authored SECOND SCENE, one named verb per body:
     BLOOM / SPREAD / SCREAM / FLIP (L25 — measured 8/8 on true ROM bytes)
  -> packed .body240 -> trench_core Morph x Q audit -> plot + audio -> Tyson keep/kill
```

Q100 corners are hand-authored like any pose. Do not turn this into free
random-corner painting, a coefficient editor, a prompt-first body writer, or a
new production-training workflow — corners stay KIN (the same instrument in
four poses), never four unrelated filters.

**Superseded — study/background only, never the active direction:** Law Author
(`docs/FORGE_LAW_AUTHOR.md`), the `gpt55-pro-*` reports, and free per-corner
editing of the four corners.

## UI / Visual Rule: No Fake Layers

For plugin UI work, **doing nothing is better than adding a fake layer**.

Do not add a shadow, glow, bevel, decal, perspective trick, glass layer, or
overlay if it reads as a separate graphic object. TRENCH should read as one
physical faceplate with real seated parts, not a stack of visible effects.

If a fix would become "that black thing," "that teal thing," or an obvious
perspective illusion, stop. Fix source asset, measured geometry, material,
spacing, or typography instead. Preserve the object first.

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

A df2 body = **four authored poses of one instrument** (Q amendment 2026-07-10).

- A **frame** = six pole+zero lanes (pole Hz/radius, zero Hz/radius, gain). Lane
  *i* of LOW morphs into lane *i* of HIGH — section index is the morph pairing,
  sacred.
- **Poles trace to real evidence** — LPC capture, physical models (tube / vowel
  tract / cavity), measured tables, or clean-room P2K grammar. Never invented or
  random.
- **Secondary/Q is authored, never derived** (L25 — supersedes the old
  derived-pressure invariant, which is REJECTED against ROM ground truth:
  Q moves centers in every measured reference). Q100 is a second scene of
  the same instrument; centers MAY move; lane correspondence MAY NOT.
- **Corners:** `C0 = M0.Q0`, `C1 = M100.Q0`, `C2 = M0.Q100`, `C3 = M100.Q100`.
  Four stored corners; all four authored.

### The invariant that proves the model

Lane *i* is the same mode in all four poses (correspondence is sacred), and
the four poses read as ONE instrument — a Q100 that is a different filter
rather than a second pose of the same one is a kinship failure, not a style.
`forge-gpu-painter`'s `pressurize()` (radius/gain-only Q) is now a BLOOM-verb
helper, not the law; `forge-zero` edits all four poses directly.

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
