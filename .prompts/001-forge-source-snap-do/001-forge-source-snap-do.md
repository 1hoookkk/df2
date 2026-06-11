# Prompt: Forge Verified Source Snap

## Objective

Implement the first real Forge source-snapping system. Replace the broken `TABLE` mental model with a verified source inventory that powers:

```text
START -> SNAP -> SHAPE -> BAKE
```

The goal is not a coefficient editor and not a per-corner workflow. The user should author the live sound, snap toward useful verified source shapes, and let Forge handle corner-word movement and packed-runtime verification.

## Context

Working directory:

```text
C:\Users\hooki\df2
```

Authority files:

```text
AGENTS.md
docs/FORGE_LAW_AUTHOR.md
forge-gpu-painter/SPEC.md
forge-gpu-painter/src/main.rs
forge-gpu-painter/HANDOFF.md
```

Evidence and source folders:

```text
recipes/laws
recipes/three_layer_acoustic_forge
forge/recipes
tables/exact_skeletons.verification.json
tools/verify_exact_skeletons.py
dev/tmp/source_snap_body240_probe_summary_17x17.json
dev/tmp/forge_source_snap_inventory/SOURCE_SNAP_SYNTHESIS.md
dev/tmp/physical_mountains/manifest.json
dev/tmp/klatt_ouiii_to_eh/klatt_ouiii_to_eh_allpole.audit.json
dev/tmp/klatt_ouiii_to_eh/klatt_ouiii_to_eh_allpole.body240
dev/tmp/law_author
dev/tmp/lpc_corners/index.json
dev/tmp/corner_library/corners
dev/tmp/synthetic_voice_terrain_capture_pack/README.md
dev/tmp/arma_source_pack
dev/tmp/prove_iconic_method
dev/tmp/null_grammar
dev/tmp/vowel_table
```

Fresh independent verification already exists:

```text
dev/tmp/source_snap_body240_probe_summary_17x17.json
```

It probes every `.body240` in the named source folders through `pyruntime.trench_ffi.packed_probe` on a 17x17 Morph x Q grid. Current result:

```text
forge_auto           pass 55/55
forge_recipe         pass 1/1
iconic_method        pass 9/9
klatt                pass 1/1
law_author           pass 31/31
lpc_corners          pass 6/6
null_grammar         pass 8/8
physical_mountains   pass 5/5
vowel_table          pass 12/12
```

This proves runtime stability and finite packed behavior. It does not erase provenance tiers.

## Non-Negotiable Runtime Facts

- A body is exactly `240 bytes = 4 corners x 6 stages x 5 packed words x 2`.
- There are six runtime stages total, not seven.
- Zeros are first-class.
- `.body240` and packed cartridge JSON are runtime artifacts.
- Plots, overlays, starts, and snaps must be generated from packed/runtime-probed data, not a surrogate continuous model.
- Do not copy protected preset/table bytes into shipping bodies. Study material can guide clean-room behavior only.

## Product Direction

Do not build another `TABLE` button. Do not make corners the normal authoring surface.

Build this:

```text
START: choose scratch or a verified source body
SNAP: move the current live sound toward verified source landmarks
SHAPE: direct response editing and solver-fit behavior
BAKE: write/probe .body240 and cartridge JSON
OVERLAY: show source response/landmarks without applying them
```

The normal workflow is live-position authoring:

```text
pick/listen to current Morph/Q -> snap or shape response -> solver moves needed corners -> bake
```

Per-corner controls are advanced details only.

## Source Tiers

Implement these tiers explicitly in data. Do not infer everything as equal.

### Tier A: Front-Rank Verified Sources

These may appear in the normal source browser and source snap UI.

1. Law Author

Paths:

```text
recipes/laws/*.json
dev/tmp/law_author/**/audit.json
dev/tmp/law_author/**/*.body240
dev/tmp/law_author/**/*.cartridge.json
```

Use as:

```text
START, SNAP, OVERLAY
```

Reason:

Source law, packed body, cartridge, and audit all exist.

2. Physical Mountains

Paths:

```text
dev/tmp/physical_mountains/manifest.json
dev/tmp/physical_mountains/*.json
dev/tmp/physical_mountains/*.body240
dev/tmp/physical_mountains/*.png
```

Use as:

```text
START, SNAP, OVERLAY
```

Reason:

Deterministic physical feedstock with manifest audit and packed bodies.

3. Klatt OUIII to EH

Paths:

```text
dev/tmp/klatt_ouiii_to_eh/klatt_ouiii_to_eh_allpole.audit.json
dev/tmp/klatt_ouiii_to_eh/klatt_ouiii_to_eh_allpole.body240
dev/tmp/klatt_ouiii_to_eh/klatt_ouiii_to_eh_allpole.compiled.json
```

Use as:

```text
START, SNAP, OVERLAY
```

Reason:

Clean all-pole formant source with explicit packed probe.

4. Exact Skeletons

Paths:

```text
tables/exact_skeletons.verification.json
tools/verify_exact_skeletons.py
```

Use as:

```text
START only
```

Rule:

Only rows with `"verdict": "PASS"` are visible. Current PASS: Butterworth only. Cheby2 and Elliptic must remain hidden.

### Tier B: Runtime-Verified Experimental Sources

These passed the 17x17 packed probe but should be behind `Experimental` until provenance is cleaned up.

```text
forge/recipes/auto
dev/tmp/prove_iconic_method
dev/tmp/lpc_corners
dev/tmp/null_grammar
dev/tmp/vowel_table
```

Use as:

```text
START > Experimental
OVERLAY
optional SNAP after source record has clear provenance
```

Special handling:

- `dev/tmp/lpc_corners/index.json` includes its own `verdict`; preserve those verdicts. Do not promote a row with `FAIL` just because the packed body is stable.
- `prove_iconic_method` is useful but proof/demo material. Do not front it above Law Author/Physical/Klatt.

### Tier C: Overlay-Only / Study Sources

Do not use these as verified starts or snaps until promoted through a full-body packed probe gate.

```text
dev/tmp/corner_library/corners/*
dev/tmp/synthetic_voice_terrain_capture_pack
dev/tmp/arma_source_pack
dev/tmp/capture_fit_bench
dev/tmp/screamer_test
```

Use as:

```text
OVERLAY
FIT PRIOR
SOURCE LANDMARKS
STUDY ONLY
```

Rules:

- Corner-library files are compiled single-corner JSON. They are excellent landmark overlays but are not full four-corner bodies by themselves.
- Synthetic voice pack README explicitly says it is not packed-runtime proof.
- ARMA source pack contains raw audio, probe reports, fitted corners, and study fixtures; do not present raw audio or heritage names as shipping sources.
- Screamer/P2K material is study evidence only.

## Implementation Requirements

### 1. Build a Canonical Source Inventory

Create a source inventory builder, preferably:

```text
tools/build_forge_source_inventory.py
```

It must:

- scan the source paths above
- run or consume a 17x17 `packed_probe` gate for every `.body240`
- include `sha256`, byte length, max pole radius, unstable row count, nonfinite row count
- include provenance tier: `front_verified`, `experimental_verified`, `overlay_only`, `quarantined`
- include surface roles: `start`, `snap`, `overlay`
- include human labels, not folder jargon
- write a machine-readable inventory, for example:

```text
forge-gpu-painter/assets/source_inventory.json
dev/tmp/forge_source_snap_inventory/source_inventory.report.json
```

Do not rely on folder names alone. Every visible source must have an evidence reason.

### 2. Wire Forge to the Inventory

In `forge-gpu-painter`:

- remove `TABLE` as visible UI language
- load the canonical source inventory
- make `START` read verified source bodies from inventory
- show Tier A sources first
- put Tier B under `Experimental`
- hide Tier C from starts

The existing hardcoded exact skeleton path can remain only as a migration fallback, but UI language must say `verified start`, never `table`.

### 3. Implement Source Overlay

Add an overlay mode that can show:

- source response curve at current Morph/Q
- source pole frequency guide lines
- source zero frequency guide lines
- source label and verification badge

Overlay is non-destructive. It must not modify the body.

### 4. Implement First Snap Behavior

Implement the smallest useful `SNAP` that respects the new workflow.

The first version should support:

```text
SNAP TO SOURCE RESPONSE
SNAP SELECTED FILTER TO NEAREST SOURCE POLE/ZERO
SNAP ALL ACTIVE FILTERS TO SOURCE LANDMARKS
```

Preferred behavior:

- user chooses a verified source
- Forge evaluates the current body and source body at the live Morph/Q point through packed runtime
- Forge derives source landmarks from the packed probe rows at that live point
- snap modifies the live sound through existing solver/authoring paths
- packed body is rebuilt and re-probed

Do not make the user choose a corner as the normal path.

If full live-position inverse solve is too big for the first pass, implement a conservative first step:

- selected filter snap moves the selected stage pole/zero toward nearest source pole/zero at current live point
- then rebuilds packed body and audits
- explicitly label it `selected filter` behavior

### 5. Verification Gates

Every source inventory build must fail or quarantine entries when:

- body length is not 240 bytes
- any 17x17 point has unstable rows
- any 17x17 point has nonfinite rows
- exact skeleton sidecar verdict is not PASS
- source has only corner JSON and no full body

### 6. UI Language

Use these words:

```text
START
SNAP
OVERLAY
SHAPE
BAKE
KEEP
verified source
experimental source
study overlay
```

Avoid these words on the front surface:

```text
TABLE
coefficient
corner editor
packedWords
max |p|
fixture
corpus
compiler table
```

### 7. Tests and Proof

Add or update tests/scripts so this is provable:

- inventory builder produces JSON
- inventory includes at least:
  - Law Author source
  - Physical Mountains source
  - Klatt source
  - Butterworth verified start
- Cheby2/Elliptic are not visible when their verification sidecar says FAIL
- `cargo check -p forge-gpu-painter`
- `cargo build -p forge-gpu-painter --release`
- `forge-gpu-painter.exe --table-gen-test` may remain as a legacy CLI test but its output should say `verified start`, not `TABLE`
- existing app tests still pass:
  - `--mag-test`
  - `--goal-test`
  - `--interior-test`
  - `--draw-test`

Also capture a screenshot of the front surface and verify:

- no visible `TABLE`
- `START` exists
- `SNAP` exists or has a clear placeholder if implementation is staged
- source overlay/details are not front clutter

## Output Specification

Produce:

```text
dev/tmp/forge_source_snap_inventory/source_inventory.report.json
forge-gpu-painter/assets/source_inventory.json
```

Update:

```text
forge-gpu-painter/src/main.rs
forge-gpu-painter/SPEC.md
forge-gpu-painter/HANDOFF.md
```

If you introduce Rust modules, keep them small and obvious, e.g.:

```text
forge-gpu-painter/src/source_inventory.rs
```

## Success Criteria

This is successful when:

- a user can start from verified sources without seeing a `TABLE` button
- a user can overlay source response/landmarks without applying them
- a user can perform at least one meaningful snap toward a verified source
- all visible sources have provenance and packed-runtime verification
- study/capture/corner material is not silently promoted as verified
- no normal workflow asks the user to babysit four corners

## Final Response Requirements

Report:

- source inventory path
- number of front verified sources
- number of experimental verified sources
- number of overlay-only sources
- verification commands run
- screenshot path
- any sources quarantined and why

