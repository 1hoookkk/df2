# Prompt: Forge Source Browser And Snap Overlay, Custom Painter Only

You are working in:

```text
C:\Users\hooki\df2
```

Read these first:

```text
AGENTS.md
forge-gpu-painter/SPEC.md
forge-gpu-painter/HANDOFF.md
dev/tmp/forge_source_snap_inventory/source_inventory.report.json
forge-gpu-painter/assets/source_inventory.json
dev/tmp/source_snap_body240_probe_summary_17x17.json
tables/exact_skeletons.verification.json
```

## Absolute Rule

This is a **custom painter code** task.

Do not build this with stock widgets, tables, generic panels, or framework layout components.

Use the existing architecture:

```text
layout rects -> draw calls -> Frame hit lists -> interact()
```

egui may host the window, input, and painter access. The product UI itself must be drawn by Forge code:

- custom chips
- custom sliders
- custom menus
- custom mini plots
- custom source rows
- explicit hit-test rects
- cached source previews
- no disk IO inside paint

The wgpu plot path remains the hero plot path.

## Product Direction

The front surface is now Peak/Shelf Morph first:

```text
LOW FRAME:  FREQ | SHELF | PEAK
HIGH FRAME: FREQ | SHELF | PEAK
MORPH | PRESSURE | MASTER
AUDITION | BAKE | KEEP
```

The source browser is not allowed to turn Forge back into a coefficient editor or a research inventory page.

The packed artifact is still:

```text
4 corners x 6 stages x 5 packed u16 words x 2 bytes = 240 bytes
```

## What To Build

Build the real source browser and snap/overlay foundation from the generated inventory.

Use:

```text
forge-gpu-painter/assets/source_inventory.json
```

as the app-facing category list, backed by:

```text
dev/tmp/forge_source_snap_inventory/source_inventory.report.json
```

as the full evidence report.

The current hard-coded `SOURCE_STARTS` menu is only a temporary stub. Replace it or make it clearly data-backed.

## Source Categories

The browser must show these categories:

1. `Peak/Shelf Morph`

Use as:

```text
START, SNAP
```

This is the new editable front-door grammar from the PDF/spec.

2. `Verified Editable`

Groups:

```text
law_author
recipes/laws
dev/tmp/law_author
```

Use as:

```text
START, SNAP, OVERLAY
```

Reason:

Editable source laws and packed outputs exist. These are the best front Forge sources.

3. `Verified Previews`

Groups:

```text
dev/tmp/physical_mountains
dev/tmp/klatt_ouiii_to_eh
```

Use as:

```text
PREVIEW, SNAP, OVERLAY
```

Reason:

Packed bodies pass probe and have plots/audits, but not every source is editable as Peak/Shelf controls yet.

4. `Verified Exact`

Groups:

```text
tables/exact_skeletons.verification.json
tools/verify_exact_skeletons.py
```

Use as:

```text
START
```

Rule:

Only independent `PASS` rows are visible. Current expected visible row: Butterworth. Failed Cheby2/Elliptic stay hidden.

5. `Experimental Verified`

Groups:

```text
forge/recipes/auto
dev/tmp/prove_iconic_method
dev/tmp/lpc_corners
dev/tmp/null_grammar
dev/tmp/vowel_table
```

Use as:

```text
START_EXPERIMENTAL, OVERLAY
```

Rules:

- These passed packed probe, but should not dominate the front.
- Preserve source-level verdicts such as `dev/tmp/lpc_corners/index.json`.
- Do not promote failed source rows just because packed stability passes.

6. `Study Overlay`

Groups:

```text
dev/tmp/corner_library/corners/*
dev/tmp/synthetic_voice_terrain_capture_pack
dev/tmp/arma_source_pack
dev/tmp/capture_fit_bench
dev/tmp/screamer_test
recipes/three_layer_acoustic_forge
```

Use as:

```text
OVERLAY, FIT_PRIOR, SNAP_TARGET_AFTER_ASSEMBLY
```

Rules:

- Single-corner libraries are landmarks, not full verified starts.
- Capture packs are not packed-runtime proof.
- ARMA/source audio is fit input, not a normalized source inventory.
- Three-layer recipes need compile + packed probe before front promotion.

## UI Requirements

The source browser opens from `START`.

It must use custom-painted category columns or category bands with:

- category label
- source row label
- provenance/action label
- mini response plot when packed body bytes exist
- clear disabled state for preview/overlay-only rows
- no `TABLE` wording
- no visible `packedWords`
- no raw coefficient terms

Rows must be visually grouped:

```text
Peak/Shelf Morph
Verified Editable
Verified Previews
Verified Exact
Experimental Verified
Study Overlay
```

## Snap / Overlay Behavior

First implementation can be conservative.

Minimum viable behavior:

- `OVERLAY`: show packed response curve from selected source at current Morph/Pressure.
- `SNAP`: for verified editable sources, copy or blend the Peak/Shelf/source controls.
- `SNAP`: for packed preview sources, move selected frame or selected stage toward nearest source landmarks only if the source has decoded landmarks.
- `PREVIEW`: audition/render exact packed body without claiming editability.

Never silently convert a packed P2K/reference body into editable Peak/Shelf controls unless an explicit inverse/fitter produced that source and labeled it as inferred.

## Verification

Run:

```powershell
cargo check -p forge-gpu-painter
cargo build -p forge-gpu-painter --release
.\target\release\forge-gpu-painter.exe --mag-test
.\target\release\forge-gpu-painter.exe --table-gen-test
```

Also capture the source browser screenshot and verify:

- custom-painted menu/browser is visible
- the requested folder families are represented
- `TABLE` is not visible
- experimental and overlay-only rows are not presented as verified editable starts
- mini plots do not read from disk during paint

## Final Response

Report:

- app inventory path
- full evidence report path
- source categories implemented
- sources still preview/overlay-only and why
- exact build/test commands run
- screenshot path
