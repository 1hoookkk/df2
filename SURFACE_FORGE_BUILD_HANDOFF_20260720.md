# Surface Forge — smallest build handoff

**Date:** 2026-07-20  
**Checkout:** `C:\Users\hooki\df2-workstation`  
**Build target:** the existing native `workstation` / `trench-studio` egui app

## Decision

Build this as a small native Rust/egui surface on top of the retained
`trench_workstation::app::AppState` API. Do not start a Python/DearPyGui app,
add a second compiler, or add a new Python FFI layer.

The blueprint names `tools/surface_forge.py`, `pack.py`,
`pyruntime/trench_ffi.py`, and `ship_iron_mouth.geometry.json`; none of those
files exist in this checkout. The live path is:

```text
workstation/src/bin/trench_studio.rs
  -> trench_workstation::app::AppState
  -> trench-core packed/interpolation/probe/audio runtime
```

`filters/stage-plans/ship_iron_mouth.profile-plan.json` exists as a plan, but
there is no matching geometry or body yet. Do not invent one for the GUI smoke
test; load an existing body through the current picker or `AppState` loader.

## Smallest useful surface

One toolbar plus exactly four working panes. Start with one loaded body and the
current session; the library, recipe catalog, source capture, and triage UI are
out of scope for this surface.

### 1. Travel pad

- Horizontal axis: Morph `0..100`.
- Vertical axis: Q `0..100`.
- One puck; drag calls `AppState::set_morph_q(morph, q)`.
- Display the current `M/Q` values.
- This is an audition/read coordinate. Moving it must not change body bytes.

### 2. Packed/runtime response

- Log-frequency combined six-stage cascade from `ScreenData.current_response`.
- One fixed dB scale for the whole session; no per-frame or per-render gain
  normalization.
- Six compact selectors `S1..S6` below the plot.
- Show six pole/zero markers, but make only the selected stage draggable in v1.
  The selected-stage drag edits the property pane below and commits only on
  drag release.
- Draw from packed/runtime-decoded rows, never directly from geometry JSON.

### 3. Lane registration locker

- Six rows: `S1` through `S6`, in permanent order.
- Pole and zero lock toggles per selected corner/stage.
- Optional plain role text from existing stage-plan/session metadata.
- A lock is a refusal boundary, not a hidden clamp or repair.
- Never sort lanes by frequency, response height, or pole order.
- Real-root rows show real-root controls; they cannot enter a conjugate editor.

### 4. Tension / export

- Four explicit corner toggles: `M0_Q0`, `M100_Q0`, `M0_Q100`, `M100_Q100`.
- Selected stage, selected field, delta, `Preview`, `Apply`, `Cancel`, `Undo`,
  and `Export`.
- Preview is cheap and reversible. Apply is one undo step and returns the
  exact changed corners, lanes, words, quantisation difference, and audit.
- Export uses the existing `AppState::keep()`/save-bundle path. Do not silently
  overwrite the source body or write an unproved replacement.

Toolbar only: Open body, Play/Stop, BODY SOLO/PRODUCT, Undo/Redo, Export.
Start silent. Keep the audition monitor conservative; BODY SOLO is the raw
six-stage cascade, PRODUCT is the retained full engine path.

## M50_Q50 contract

`M50_Q50` is a view coordinate, never a fifth stored keyframe. The body still
contains only the four authored corners, and the runtime still performs packed
Morph-first then Q interpolation.

Read path:

```text
pad position -> AppState::set_morph_q -> trench-core packed probe -> response/audio
```

Write path must not be implemented as a GUI-side JSON mutation. The current
`capture_runtime_position_to_corner` method captures one interior runtime point
into a chosen corner; it is not a general tension solver. The current relative
root edit applies one declared edit to all four corners; it is not weighted M50
editing either.

The stated `M25_Q0: M0 += 75%, M100 += 25%` rule is not an exact interior rule.
With bilinear weights `.75/.25`, those same corner increments produce only
`.75² + .25² = .625` of the requested interior change. Therefore:

- Do not promise that a 50 Hz drag produces exactly 50 Hz at the puck by using
  raw 75/25 deltas.
- If Tension is included in v1, add a core-owned `TensionRequest`/preview path
  that solves against packed/runtime words, respects the editable-corner mask,
  re-probes after quantisation, and returns the achieved value plus residual.
- Use a declared minimum-norm weighted correction over unlocked corners, with
  weights `[ (1-m)(1-q), m(1-q), (1-m)q, mq ]`, normalized so the requested
  runtime-space delta is actually met when the representation allows it.
- Refuse the preview when topology would change, a real-root row is addressed
  with conjugate controls, no editable corner contributes, or post-quantisation
  residual exceeds the agreed tolerance.
- If that solver is not ready, ship the pad and direct selected-corner editor
  with Tension disabled. Do not fake exact M50 behavior in the frontend.

The solver must preserve stage correspondence and report every changed packed
word. It must not sort, smooth, normalize, repair, or create an interior body
record.

## Runtime boundary

- UI thread owns `AppState`, previews, plots, and save/export.
- Audio thread owns `FilterEngine::process_block` and persistent filter state.
- Cross the boundary only through the existing audition control path: bounded
  scalar Morph/Q updates and a body swap at a block boundary.
- No UI allocation, file I/O, locking, or full sampled audit on the audio
  thread.
- Reuse the existing `AuditionStream`/rodio path in `trench_studio.rs` for the
  first build; do not introduce `process_audio()` as a new invented API.

## Existing APIs to use

```text
AppState::load_body_as_session
AppState::set_morph_q
AppState::screen
AppState::preview
AppState::apply
AppState::discard_preview
AppState::undo / redo
AppState::render_audio
AppState::keep

ScreenData::current_probe
ScreenData::current_response
ScreenData::selected_stage
ScreenData::audit

trench-core::PackedCorners / packed interpolation
trench-core FFI: trench_packed_probe, trench_certify_body,
               trench_pack_body_from_corner_words
```

The JUCE C ABI in `workstation/src/native.rs` is for the alternate C++ path;
do not use it for this native Rust/egui build.

## Acceptance gates

Before calling the surface build-ready:

1. Pad movement changes only the selected Morph/Q read position; body bytes are
   byte-identical before and after a read-only travel.
2. One selected-stage edit produces one `Preview -> Apply` undo step and reports
   only declared corners, lane, and packed words.
3. Pole/zero plots and readouts match `trench_packed_probe` after packing.
4. Real-root editing remains explicit and conjugate edits are refused.
5. M50 tension never writes an interior keyframe and reports its achieved value,
   residual, and changed words; otherwise the control stays disabled.
6. BODY SOLO and PRODUCT renders are finite, use fixed input, and are not
   per-render normalized.
7. Existing proof tests remain green:

```powershell
cargo test -p trench-core
cargo test --manifest-path workstation/Cargo.toml
cargo run --manifest-path workstation/Cargo.toml --bin proof-slice
cargo run --manifest-path workstation/Cargo.toml --bin trench-studio
```

Judge the final result from a real built window at true screen scale and from
the rendered audio. Sampled grid results are sampled certification, not a
continuum proof; audible keep/kill remains an operator decision.

## First implementation order

1. Reduce `trench_studio.rs` to the four panes above without changing the
   `AppState` or trench-core contracts.
2. Wire the Travel pad to `set_morph_q` and prove body bytes do not move.
3. Reuse the existing packed/runtime curve and selected-stage editor.
4. Wire stage/corner locks to explicit `EditRequest` masks.
5. Add Export/Undo/Apply status with changed-word receipts.
6. Add the core-owned Tension preview only after the direct editor passes.
7. Build, launch, screenshot, render BODY SOLO and PRODUCT, then hand the
   result to the operator for listening.

**Promotion rule:** a stable GUI edit is not automatically a good body. Keep
the original body available, preserve every rejected preview as evidence, and
promote only an operator-approved packed artifact.
