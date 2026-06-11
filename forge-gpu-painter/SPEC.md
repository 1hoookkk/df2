# Forge Painter Spec: Peak/Shelf Morph Surface

## 1. Product

Forge is a custom-painted filter authoring surface for making legal DF2/P2K-style
`.body240` bodies without asking the user to think in packed words, corners, or
coefficient rows during normal work.

The front surface is built around the Peak/Shelf Morph workflow from the Dillusion
tutorial:

```text
low morph frame + high morph frame
each frame: FREQ, SHELF, PEAK
global: MORPH, PRESSURE, MASTER PEAK
```

The result is still the packed runtime artifact:

```text
4 corners x 6 stages x 5 packed u16 words x 2 bytes = 240 bytes
```

The UI is an authoring grammar over the packed body, not a replacement for it.

## 2. Runtime Contract

- A body is exactly 240 bytes.
- A body has four corner banks:
  - low frame, low pressure
  - high frame, low pressure
  - low frame, high pressure
  - high frame, high pressure
- Each corner has six stages.
- Each stage has five packed words.
- Zeros are first-class. Every authored stage must have pole Hz/radius, zero
  Hz/radius, and gain.
- Plots, audits, audition slots, and KEEP outputs must be generated from packed
  runtime-probed data.
- P2K/reference bodies that already exist as packed words remain packed-word
  truth. They may be previewed, overlaid, auditioned, and used as snap targets.
  They are not editable as FREQ/SHELF/PEAK unless a writer grammar or inverse
  fit explicitly produces an editable source.

## 3. PDF-Derived Authoring Model

The Dillusion tutorial describes five practical controls:

- `MORPH`: position between the two filter frames. In the hardware workflow,
  FilFreq sweeps this value.
- `FREQ`: a frame frequency control whose meaning depends on SHELF.
- `SHELF`: frame tone, from low-pass through mid shelf to high-pass.
  - low values behave more like low-pass
  - middle values behave more like a mid shelf
  - high values behave more like high-pass
  - values between boundaries blend those behaviors
- `PEAK`: per-frame relative level for the filter sweep.
- `PRESSURE`: overall resonance/saturation pressure. In the tutorial this is
  driven by FilRes and makes the sweep more drastic.

Forge names these plainly:

```text
MORPH      = where we are between the two frames
PRESSURE   = Q / saturation / danger amount
FREQ       = the frame's main frequency
SHELF      = low-pass <-> mid shelf <-> high-pass tone
PEAK       = frame level/emphasis
MASTER     = overall filter level
```

## 4. Front Surface

The first screen must be sparse.

Visible by default:

- full-width response plot
- `START`
- `MORPH`
- `PRESSURE`
- frame A controls: `FREQ`, `SHELF`, `PEAK`
- frame B controls: `FREQ`, `SHELF`, `PEAK`
- `SWEEP`
- `AUDITION`
- `BAKE`
- `KEEP`
- stable/checking lamp
- `DETAILS`

Hidden behind `DETAILS`:

- four corner banks
- six-biquad budget
- per-stage pole/zero rows
- packed word/provenance data
- audit heat map
- source inventory details
- advanced snap settings

Forbidden on the front surface:

- `TABLE`
- `packedWords`
- coefficient editor language
- normal per-corner editing
- visible six-card workbench
- research corpus/provenance jargon

## 5. Main Layout

```text
top bar:
  TRENCH FORGE | body name | stable lamp | AUDITION | BAKE | KEEP

plot:
  live packed response, large and uncluttered
  low-frame ghost
  high-frame ghost
  optional source overlay

control band:
  START | SWEEP | MORPH slider | PRESSURE slider | MASTER

frame band:
  LOW FRAME:  FREQ | SHELF | PEAK
  HIGH FRAME: FREQ | SHELF | PEAK

details drawer:
  source, snap, corners, six-stage budget, audit
```

The plot is the hero. Controls orbit it; they do not compete with it.

## 6. Custom Painter Architecture

This remains full custom code painter style.

- egui hosts the window, input events, and painter access only.
- Product UI is not built from stock egui widgets.
- Every visible control is drawn by Forge code:
  - layout rects
  - hit-test records
  - custom text, chips, dials, sliders, mini plots
  - explicit hover/active/drag states
- The response plot stays wgpu-backed.
- GPU resources are retained and updated; no per-frame buffer or texture creation.
- Paint code must not read source files from disk. Source body bytes and mini-plot
  previews are loaded or cached outside the paint path.
- Input follows the same structure:

```text
layout() -> draw_*() fills Frame hit lists -> interact() consumes hit lists
```

This keeps the app painter-like and deterministic while avoiding widget soup.

## 7. Data Model

Normal editable body:

```rust
struct PeakShelfPatch {
    name: String,
    low: FrameControls,
    high: FrameControls,
    morph: f32,
    pressure: f32,
    master_peak_db: f32,
}

struct FrameControls {
    freq_hz: f32,
    shelf: f32,      // -64..+63
    peak_db: f32,
}
```

Advanced compiled body:

```rust
struct Section {
    on: bool,
    locked: bool,
    role: String,
    corners: [CornerStage; 4],
}

struct CornerStage {
    pole_hz: f32,
    pole_r: f32,
    zero_hz: f32,
    zero_r: f32,
    gain_db: f32,
}
```

Packed source body:

```text
raw .body240 bytes
compiled-v1 cartridge JSON
audit/provenance sidecars
```

The UI always distinguishes:

- `editable`: controls can be changed and recompiled
- `packed preview`: exact packed body, not editable yet
- `study overlay`: visual/reference only

## 8. Peak/Shelf Compiler

The Peak/Shelf controls compile into exactly six pole-zero lanes.

Suggested lane roles:

1. `shelf_spine`: low-pass/high-pass boundary energy
2. `low_weight`: bass/body compensation
3. `mouth_band`: mid shelf or vowel-ish emphasis
4. `bite_cut`: moving notch/canyon
5. `upper_tear`: high-mid edge
6. `air_cap`: high restraint/air

Corner mapping:

```text
C0 = low frame, pressure 0
C1 = high frame, pressure 0
C2 = low frame, pressure 1
C3 = high frame, pressure 1
```

SHELF mapping:

```text
-64       mostly low-pass
  0       mostly mid shelf
+63       mostly high-pass
between   blend the neighboring behaviors
```

FREQ mapping depends on SHELF:

- low-pass region: cutoff/rolloff boundary
- mid-shelf region: band center
- high-pass region: boundary/knee

PRESSURE mapping:

- increases pole radius
- deepens or focuses zeros where useful
- may trim gain to avoid unstable or unusable bodies
- must never hide instability

MASTER PEAK:

- applies a final level/emphasis policy during compile
- must be audited post-pack

## 9. Source Browser

`START` opens a categorized source browser with mini plots.

Categories:

- `Peak/Shelf Morph`
- `Verified Editable`
- `Packed Preview`
- `Clean Templates`
- `Study Overlay`

Rules:

- mini plots are generated from packed/runtime response when body bytes exist
- verified editable rows load source controls or stage sidecars
- packed preview rows do not pretend to be editable
- P2K/reference packed bodies can be selected as overlays or snap targets
- failed or unverified sources stay hidden or quarantined

## 10. Core Interactions

Basic authoring path:

```text
START -> set LOW frame -> set HIGH frame -> sweep MORPH -> raise PRESSURE -> AUDITION -> BAKE -> KEEP
```

Direct manipulation:

- drag curve left/right region: adjust frame FREQ
- drag curve up/down: adjust frame PEAK
- drag shelf handle: adjust SHELF tone
- hold modifier or use DETAILS: expose pole/zero surgery
- snap: move the current frame toward a verified source landmark
- overlay: show source response without applying it

The default interaction edits the simple frame controls. It must not make the
user babysit four corners.

## 11. Bake And Keep

`BAKE` writes:

```text
dev/tmp/forge_gpu_painter/<name>.body240
dev/tmp/forge_gpu_painter/<name>.source.json
```

`AUDITION` writes:

```text
Documents/TRENCH/authoring_slot.json
```

`KEEP` stages:

```text
desk/bank/v1/staging/<slug>/<slug>.body240
desk/bank/v1/staging/<slug>/<slug>.cart.json
desk/bank/v1/staging/<slug>/<slug>.source.json
desk/bank/v1/staging/<slug>/<slug>.audit.json
desk/bank/v1/staging/<slug>/<slug>.provenance.json
```

KEEP refuses unstable packed audits.

## 12. What Current Forge Helps

Forge already helps with:

- exact 240-byte packed body output
- packed-runtime plotting
- stable/audit checks
- custom painter architecture
- audition/bake/keep pipeline
- six-biquad budget in advanced view

Forge currently hurts the Peak/Shelf workflow when it:

- exposes stage/corner detail too early
- makes `SNAP`/`TABLE`/source research language visible before sound-making
- lacks direct `FREQ / SHELF / PEAK` frame controls
- makes the user infer that MORPH is the hardware-style FilFreq sweep
- treats Q pressure as a technical row issue instead of the "make it drastic"
  control from the tutorial

## 13. Verification

Before claiming the app works:

```powershell
cargo check -p forge-gpu-painter
cargo build -p forge-gpu-painter --release
.\target\release\forge-gpu-painter.exe --mag-test
.\target\release\forge-gpu-painter.exe --goal-test
.\target\release\forge-gpu-painter.exe --interior-test
.\target\release\forge-gpu-painter.exe --draw-test
.\target\release\forge-gpu-painter.exe --table-gen-test
python tools/law_author.py --preset hedz_like_anchor_canyons --out dev/tmp/law_author/golden_hedz_like
```

UI screenshot checks:

- no visible `TABLE`
- no default per-corner workbench
- plot dominates the screen
- LOW/HIGH frames are visible
- each frame has FREQ/SHELF/PEAK
- MORPH and PRESSURE are obvious
- DETAILS contains the packed/corner/stage machinery

## 14. Implementation Order

1. Replace the front workbench with the Peak/Shelf frame surface.
2. Keep existing packed-runtime plot and audit code.
3. Add `PeakShelfPatch` source JSON.
4. Write `compile_peak_shelf_patch()` to six lanes and four corners.
5. Add `START -> Peak/Shelf Morph` with mini plot.
6. Move corner chips, section cards, and six-biquad budget into DETAILS.
7. Keep packed preview and source overlay, but label them honestly.
8. Verify bake/audition/keep from the simplified surface.

The target is not a smaller coefficient editor. It is a simpler musical
instrument for producing the same exact 240-byte packed bodies.
