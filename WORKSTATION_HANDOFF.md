# TRENCH Workstation — Native Build Handoff

**Goal:** a native desktop workstation for auditioning, editing, and triaging
TRENCH filter bodies. Sparse, resizable, Blender/Premiere-style docked layout.
Controls are pole/zero/SCALE geometry — **not** a parametric EQ.

**Vehicle:** native desktop app. **Not** a browser / web page. (A web reshape
was prototyped this session and rejected — the browser is the wrong vehicle.)

---

## 0. Decisions locked

- **Native, not web.** No HTTP server, no HTML/JS/CSS front-end.
- **Reuse the runtime. Do not re-implement it.** `trench-core` and the
  `trench-workstation` library already own packing, packed-u16 interpolation,
  decode, response, stability sampling, audio, load/save, edits, and the proof
  bundles. The front-end is the only thing missing.
- **Recommended stack: Rust + `egui`**, a binary that depends on the
  `trench-workstation` lib crate and calls `AppState` **directly** (no FFI, no
  serialization boundary). This matches the existing `forge/` egui bench.
- **Alternative stack: JUCE / C++**, driving the existing C FFI in
  `workstation/src/native.rs` (`workstation_state_*`). Choose this only if the
  workstation must visually match the shipped plugin. It is more code.

If Rust+egui: add a new `[[bin]]` to `workstation/Cargo.toml` (e.g.
`trench-studio`) and `use trench_workstation::app::AppState;`. The lib already
builds as `rlib`.

---

## 1. Runtime facts (authority — do not renegotiate)

- A body is exactly **240 bytes**: 4 corners × 6 stages × 5 little-endian u16.
- Corner order is fixed: `M0_Q0`, `M100_Q0`, `M0_Q100`, `M100_Q100`.
- The 6 stages run as a **serial cascade**. Stage *i* is section **S(i+1)**.
- Runtime = Morph-first interpolation, then Q, on the packed u16 words; decode
  yields direct `[b0, b1, b2, a1, a2]` DF2T sections.
- **SCALE = b0.** No "gain dB" normalization anywhere.
- **Inactive = the exact identity biquad** (`[1,0,0,0,0]`). There is no packed
  on/off bit.
- **Real-root pairs stay explicit.** Never clamp a real-root row into conjugate
  Hz/radius controls.
- All four corners are authored; Q100 is a second pose, never derived. Stage
  index is sacred across corners — never sort lanes per pose.

Full contract: `AGENTS.md`, `CLAUDE.md`.

---

## 2. The backend is finished and gated — bind to it

Everything below already exists and is tested. The GUI only reads snapshots and
calls these methods.

### `trench_workstation::app::AppState`
```
AppState::new(repo_root) -> AppState        // loads a starter four-pose session
.snapshot() -> AppSnapshot                  // the whole UI model, serde-serializable
.screen() -> ScreenData                     // just the plot/geometry view
.select(corner, lane)                        // pick pose (0..3) + section (0..5)
.load_body_as_session(path)                  // open a .body240 as the edited session
.new_filter()                                // start from an identity body
.set_morph_q(morph, q)                       // 0..1 each; audition + combined response
.preview(EditRequest) -> PendingPreview      // stage one declared edit
.apply() -> EditResult                       // commit the pending edit (one undo step)
.discard_preview()
.undo() / .redo()
.fill_corner_from_source(corner, source_index, endpoint)   // Blend-Map source dropdown
.assign_lane_from_source(corner, lane, source_index, endpoint, source_section)
.render_audio(mode) -> AudioRender           // BODY SOLO | PRODUCT (see §5)
.keep() -> SaveReceipt                       // "Save Version": content-addressed bundle
```

### Snapshot shape (serde JSON field names)
```
snapshot.screen:
  name, selectedCorner, selectedLane, morph, q,
  currentResponse.points[] { freq_hz, db }          // THE combined cascade curve
  selectedStage {
    identity: bool,
    pole:  RootGeometry,   zero: RootGeometry,
    scale: { value, display, db? },                 // SCALE = b0
    packedWords: [u16;5],  runtimeCoefficients: [f64;5]
  }
  corners[] { index, label, response.points[], lanes[] { lane_index, stage, response } }
  audit { morphPoints, qPoints, cells[] {position{morph_index,q_index}, finite, stable},
          pass, maximumPoleRadius, firstFailingPosition, ... }
snapshot.sourceCatalog.sources[] { index, name, ... }   // Blend-Map "measured/saved source"
snapshot.can_undo, can_redo, lastKeep
```

`RootGeometry` is one of:
`{"Conjugate":{hz,radius}}` | `{"RealPair":{root_a,root_b}}` | `"Degenerate"`.
(Rust: `trench_workstation::model::RootGeometry`.)

`EditRequest` fields: `cornerIndices[]`, `laneIndices[]`, `field`, `value`,
`secondaryValue?`, `relative`. `EditField` values: `pole_hz`, `pole_radius`,
`pole_geometry`, `pole_root_a`, `pole_root_b`, `zero_hz`, `zero_radius`,
`zero_geometry`, `zero_root_a`, `zero_root_b`, `scale`, `identity`.
An edit targeting a real-root row with a conjugate field is **refused** by the
core — surface the real-root controls instead, never auto-convert.

### C FFI (only for the JUCE path)
`workstation/src/native.rs` exposes the same surface as `workstation_state_*`
(`_create`, `_snapshot_json`, `_load_body_as_session`, `_select`,
`_preview_field`, `_preview_conjugate_root`, `_apply`, `_undo`, `_redo`,
`_set_morph_q`, `_fill_corner_source`, `_keep_json`, `_validate`, ...).

---

## 3. Proof gates — already executable and passing (the hard part is done)

`workstation/src/proof.rs :: run_proof_slice` enforces **18 gates** and the test
`proof::tests::proof_slice_passes_and_is_byte_reproducible` proves them PASS and
byte-reproducible. Run them:

```
cargo test  -p trench-core
cargo test  --manifest-path workstation/Cargo.toml         # 28+ pass, incl. proof
cargo run   --manifest-path workstation/Cargo.toml --bin proof-slice
```

The gates (do not re-derive; the GUI must not violate them):
no-op load/save byte-identical · edited reopen byte-identical · body/cartridge
parity · declared-selection-only · declared-word-scope-only · identity lanes
decode exactly · real-root round-trips · real-root conjugate edit refused ·
displayed coefficients == packed probe · plot uses packed-probe coefficients ·
one shared dB scale · raw audio not normalized · audio fits PCM16 no clip ·
BODY SOLO finite · PRODUCT finite · zero unstable rows · zero nonfinite rows.

Call the Morph×Q grid **sampled certification**, never a continuum proof.

---

## 4. Layout spec (the five zones)

Sparse, resizable, docked. Neutral charcoal surfaces, one restrained blue or
malachite accent, high-contrast response curve, thin separators, compact
readable type. No fake hardware, glow, textures, gradients, or dashboard chrome.

**1. Top toolbar** — one compact row: Play (starts silent) · Pink-noise source ·
Undo · Redo · Save Version · BODY SOLO / PRODUCT · KEEP / REPAIR / REJECT ·
current filter name + selected section. No second header, no decorative nav.

**2. Filter Library (left, collapsible)** — search; filter names; plain
Keep/Repair/Reject status text (no colored dots, no cards); selected-row
highlight; keyboard + scroll nav. Source = the `.body240` roster in
`filters/bodies/` (132 files today).

**3. Combined response (main viewport, dominant)** — draw **one** packed-runtime
curve for the full six-section serial cascade, on a fixed shared dB scale and log
frequency axis. No ghost curves, no draggable EQ nodes, no separate
normalization. When a section is selected, show **at most one** restrained marker
at its pole frequency. The curve always comes from packed words decoded through
trench-core (`screen.currentResponse`). Put a thin **S1–S6** selector directly
below the plot; selecting a section updates Section Properties without covering
the response.

**4. Blend Map (lower-left)** — a two-axis field with one draggable cursor. Four
positions, each with a small source indicator, a dropdown to pick another
measured/saved source (`sourceCatalog.sources`), and a plain position label.
Fixed mapping:
`Bottom Left = M0 Q0 · Bottom Right = M100 Q0 · Top Left = M0 Q100 · Top Right = M100 Q100`.
Dragging the cursor updates the combined response + audition target live
(`set_morph_q`). Clicking a position selects that corner for editing. Axes are
labeled **Horizontal Blend** / **Vertical Blend** — do not invent
Brightness/Darkness/Size/Width.

**5. Section Properties (lower-right)** — show only the selected position +
section. Always: S1–S6 selector; geometry type; SCALE (= b0); active state
(inactive writes the exact identity biquad); Undo + Revert.
- **Conjugate section:** Pole frequency, Pole radius, Zero frequency, Zero radius.
- **Independent real-root pair:** replace those with explicit Pole 1, Pole 2,
  Zero 1, Zero 2. Never silently convert real roots to conjugate controls.
- **Do NOT include:** peaking/shelf/EQ-type menus, Add Pole, Add Zero, gain-dB
  normalization, or a wall of permanent sliders.

---

## 5. Behaviour

- Leaving an unsaved filter restores its original packed words (re-open the body
  or discard the session).
- Undo operates per edit gesture (one `preview`+`apply` = one undo step).
- **Reject** advances to the next surviving candidate. **Repair** queues the
  candidate. **Save Version / KEEP** creates a new versioned bundle via
  `keep()` — content-addressed, never a silent overwrite of the source.
- Every edit reports the exact position, section, and packed words changed
  (`EditResult.changed_words`).
- **BODY SOLO** = the six-section cascade only, unity I/O, no AGC / DC-block /
  saturation / desk — "what the raw body does to sound." **PRODUCT** = the full
  retained `FilterEngine` path — "what the shipped plugin outputs."
- App starts silent. (Note: pink noise through a high-radius body rings hard and
  is un-limited in BODY SOLO — keep the audition level conservative and never
  auto-play on load.)
- Triage (keep/repair/reject) and the library roster are **app/session state**,
  not runtime law. Keep them in the GUI; every packed change still goes through
  `AppState`.

---

## 6. What this session already did

- **Verified all 18 proof gates are executable and passing** (see §3). The
  runtime, packing, decode, response, audio, load/save, edits, and proof bundles
  are complete. A native GUI is the only remaining work.
- Added `Excitation { Probe, Pink, Silent }` + `render_audio_ex` in
  `workstation/src/model.rs` (gate-safe: `render_audio` still delegates to the
  byte-identical Probe stimulus, so `proof.rs` is unaffected). Reuse this for the
  transport's silent/pink source. **Keep this change.**
- Prototyped a web/HTTP reshape (`workstation/src/main.rs` + `workstation/ui/*`).
  **Being dropped — browser is not the vehicle.** These files are git-ignored and
  can be ignored or deleted; nothing depends on them. Do not port their DOM code.

## 7. Where things are

```
trench-core/                 the runtime (packing, interp, decode, response, engine, certify)
workstation/src/app.rs       AppState — the whole authoring/edit/keep API (bind here)
workstation/src/model.rs     Session, EditRequest/EditField, RootGeometry, ScreenData, render_audio_ex
workstation/src/proof.rs     the 18 gates + run_proof_slice + reproducibility test
workstation/src/native.rs    C FFI (only if you build the JUCE path)
workstation/src/bin/         proof-slice, recipe-proof, ... (CLI proofs)
filters/bodies/*.body240     the filter library roster (132 files)
fixtures/*.body240           identity / conjugate / real-root / four-pose test bodies
forge/                       existing one-file egui bench (pattern for the native GUI)
```
