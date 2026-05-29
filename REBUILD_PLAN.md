# REBUILD_PLAN.md — DF2 JUCE-shell rewrite (Option B)

## Context

DF2 ships two artifacts: the consumer **player** (JUCE/C++ shell over a Rust DSP
core) and the authoring **Forge** (Rust/egui). The Rust core (`trench-core`),
240-byte packed body format, AGC table, and X3 null parity are all
verified-clean (STATE.md `Now`, 2026-05-28). Every defect found in the recent
debug push lives in the **JUCE C++ shell** or in **Forge surfaces that have
crept into the player path**: the Body-strip normalized/denorm bug
(`STATE.md:41-46`), the input-mode-default-SLAM regression
(`STATE.md:47-51`), the latent `TrenchResponseDisplay` 4-cycle bug
(`STATE.md:52-56`), the drifted VST3 install paths
(`STATE.md:57-61`), and several decode-and-interpolation oddities surfaced by
a fresh-eyes external audit and verified against the actual code.

The goal of this plan is the **smallest honest player runtime**: selected
body → exact 240 bytes → `PackedCorners` → Morph/Q → fixed-rate cascade →
AGC/saturate → output. Forge stays out of the player except where it
publishes a body. Everything fancy (Teleport, 5D/QSound, SLAM extras, hot
reload, vectorscope, FX pane, capture tools) becomes opt-in or moves out of
the consumer shell entirely.

This plan is the **architecture and surgical work-item list** for that
rewrite. No source changes happen until the plan is approved and we exit
plan mode.

---

## Doctrine constraints (non-negotiable; kept across the rewrite)

These come from `CLAUDE.md`, the auto-memory index, and STATE.md. They
override any audit recommendation that contradicts them.

- **`trench-core` is the only DSP authority.** The player calls Rust via FFI;
  the C++ shell never re-implements biquads, AGC, or interpolation.
- **240-byte packed body is the single canonical coefficient path.** Source
  (`.body240` / JSON `packedWords` / `packed-body-v1`) → `BodyBytes240` →
  `PackedCorners` → `Cartridge`/runtime. `stages` is read-only fallback.
  (`STATE.md:269-282`)
- **Shipping morph interp is the packed-domain bilinear**
  (`PackedCorners::interpolate_biquad` via `cartridge.rs:303`). The f64
  bilinear path is **only** the legacy stage-coefficients fallback when
  `packed = None` (`cartridge.rs:309-316`). This is the truth surface; the
  audit's "convert ROM bodies to f64 and bilinear in f64" recommendation is
  rejected (see Rejected Audit Claims).
- **AGC table at indices 4-7 IS the E-mu character** (STATE.md `Now`,
  2026-05-28); filter peaks need ~+22…+28 dB to drive it. Output level is
  not just gain staging — it is timbre.
- **Chassis PNG + code-rendered overlays = identity.** Memory
  `df2-chassis-is-the-identity`. Never replace with pure egui/WebView, never
  delete the chassis to be "transparent".
- **All authoring tricks collapse to one shipped corner.** Memory
  `tricks-are-authoring-runtime-is-filters`. The player adds nothing of its
  own; the violence already lives in the corners.
- **Forge is authoring-only.** Forge fits / hot-reloads / browses; the
  player consumes baked bodies. The crossing artifact is the body file, not
  a live channel.

---

## Boundaries — keep / rewrite / move

| Surface | Disposition |
|---|---|
| `trench-core/` (Rust DSP runtime, AGC, packed math, FFI) | **Keep.** No structural changes. Single source of truth. |
| 240-byte packed body format, `PackedCorners`, `Cartridge::from_body_bytes` | **Keep.** Authority. |
| AGC table + `saturate` + `& 0xF` wrap | **Keep verbatim.** Verified-faithful hardware. |
| Null vs X3 (-95.41 dB @ M50/Q50) | **Keep as ship gate.** |
| Chassis PNG (`BinaryData`) + code-rendered overlays (`TrenchChassisGlass`) | **Keep.** Identity. |
| Forge (`forge/`) — entire authoring app | **Keep, but quarantine from player.** Forge stops being a runtime path the player can be confused with. |
| `juce-shell/PluginProcessor.cpp` + `PluginEditor.cpp` + parameter layout | **Rewrite, small and disciplined.** Single signal path; everything optional becomes off-by-default and opt-in. |
| `TrenchAuthoringSlot` (Forge live hot-reload inside player) | **Remove from default player build.** Behind a dev-only flag, off by default. (STATE.md 2026-05-26 already removed its default hijack of the Body strip; this finishes the job.) |
| `TrenchFxPane`, `TrenchViewSwitch`, `TrenchResponseDisplay` (vectorscope) | **Move behind a "diagnostics" build flag**, default off in shipping. Main view stays chassis + Body strip + Morph + Q + Output. |
| `TeleportEngine`, SLAM-drive routing, 5D/QSound spatial mode | **Defer / opt-in.** Code stays in tree but does not appear in the parameter layout or signal path unless the corresponding feature flag is on. `clean_audio::kEnabled` (currently the gate) becomes a runtime feature toggle rather than a compile-time const so the diagnostic build can still flip it. |
| `forge_core.rs::load_reference_rom` | **Repair** — direct unpack, no interpolate-at-grid. (Verified bug.) |
| `forge_core.rs` fabrication fallback (`shift_corner` + `sharpen_corner`, `q_sharp=0.3` default) | **Repair** — bodies require all 4 corners explicit. Aligns with STATE.md 2026-05-28 "twin-anchor" doctrine that already retired the timid base→shift→sharpen path. |
| `EXPORT_BOOST = 4.0` hidden constant in keyframe JSON | **Make explicit metadata, runtime-applied-by-default-for-back-compat.** See work item EX-4. |
| `handleAsyncUpdate` / `lastLoadOk` | **Promote to audio-thread safe-state.** Load failure → bypass with logged error, not silent continuation on stale body. |

---

## The minimum honest player runtime

The signal path the rewritten shell guarantees. Everything else is opt-in.

```
[host audio in]
     │
     ▼
[selected body bytes] ── (exactly 240 bytes; .body240 or packedWords JSON
     │                    → BodyBytes240 → PackedCorners; rejects ≠240)
     ▼
[Morph, Q smoothed params]
     │
     ▼
[fixed-rate cascade island @ 39062.5 Hz]
     │   (LagrangeInterpolator SRC in/out around Rust FFI;
     │    cascade itself is trench_engine_process_block)
     ▼
[AGC + saturate (in Rust core, unchanged)]
     │
     ▼
[output makeup gain, default 0 dB]
     │
     ▼
[host audio out]
```

**Properties this guarantees:**

- A freshly loaded plug-in with no user input passes a calibrated test
  source through *only* this chain — no teleport, no SLAM, no 5D, no
  hot-reload watcher, no scope writebacks, no FX pane.
- Failed body load ⇒ bypass, not stale-body continuation.
- All character (AGC, `saturate`, `& 0xF` wrap) lives in `trench-core`
  exactly as it does today.
- Output level defaults to unity so AGC engagement is the user's choice,
  but the body's exported `boost` metadata still drives the cartridge load
  by default (see EX-4) so existing bodies don't go silent.

---

## Concrete work items

Each item names the specific files and the smallest defensible change.
Items prefixed `PL` are player-side, `FG` are Forge-side, `EX` cross-cut.

### PL-1. Player parameter layout — opt-in extras, conservative defaults

**Files:** `juce-shell/TrenchParameters.cpp`, `TrenchParameters.h`,
`PluginProcessor.cpp`.

- Confirm (and fix if regressed) that every parameter defaults to a clean
  identity value: `body=0`, `morph=0`, `q=0`, `slamDrive=0`, `fiveD=Off (0)`,
  `teleportMode=Off (0)`, `inputMode=Normal`, `output=0 dB`.
  - STATE.md `Now` flagged `inputMode` defaulting to SLAM and
    `slamDrive=0.35` (lines 39-40). My audit verification found `slamDrive`
    default `0.0f` at line 34 — likely already patched mid-session.
    **Verify on first pass and fix if it regressed.**
- Move Teleport, SLAM extras, and 5D out of the *default* parameter layout
  into an "extras" layout block compiled in only when
  `TRENCH_PLAYER_EXTRAS` is defined. In the shipping build this block is
  empty; in the diagnostic/dev build it adds them back.
- `clean_audio::kEnabled` becomes a runtime toggle backed by a state-saved
  bool (default `true`), so a single binary can be A/B'd without recompiling.
  The shipping UI does not expose the toggle.

### PL-2. Single signal path in `processBlock`

**Files:** `juce-shell/PluginProcessor.cpp`.

- Reduce `processBlock` to: parameter pull → `FixedRateTrenchIsland::process`
  → output gain. No conditional teleport / SLAM / 5D / spatial branches in
  the main path. The extras (when compiled in) live in a clearly-named
  separate function called *only* if their per-feature parameter > 0.
- Remove the "force `slamDrive=0`, `fiveD=0` only when clean_audio"
  pattern; in the rewritten shell those parameters do not exist in the
  default build, so there is nothing to force. (Today's gate at
  `PluginProcessor.cpp:162` was a band-aid over a parameter-layout problem.)

### PL-3. Safe-state load failure

**Files:** `juce-shell/PluginProcessor.cpp` (`handleAsyncUpdate`, `processBlock`).

- After a failed `loadCartridge*`, set an atomic `audioBypassed=true`. While
  set, `processBlock` zeroes the buffer (or passes through dry, picker's
  call) and `getLastLoadOk()` keeps returning `false` for the UI.
- Successful load clears the flag *before* swapping in the new body so
  there's no window where audio is processed against an inconsistent core.
- Log on failure stays (already present). Surface the failure visibly in
  the chassis (small "BODY FAILED — bypass" overlay, code-painted, no asset
  change).

### PL-4. View — main vs diagnostics

**Files:** `juce-shell/PluginEditor.cpp`, `TrenchViewSwitch.h`,
`TrenchFxPane.h`, `TrenchResponseDisplay.cpp`.

- **Default shipping editor** = chassis + `TrenchBodyStrip` + Morph wheel +
  Q wheel + Output knob. That is the consumer surface.
- `TrenchFxPane`, `TrenchViewSwitch`, `TrenchResponseDisplay` compile in
  under `TRENCH_PLAYER_DIAGNOSTICS` flag (off by default). They live in the
  tree, run in dev builds, do not ship.
- While we're in `TrenchResponseDisplay.cpp`, fix the latent cosmetic bug:
  hardcoded `kBodyNames[4]` and `bodyIndex() % 4` at lines 14-17 and 441 —
  read the live roster instead of a 4-cycle. (Cheap; do it because we're
  in the file.)

### PL-5. Body-strip parameter contract

**Files:** `juce-shell/TrenchBodyStrip.cpp` (`setIndex`, `setValueAsCompleteGesture`).

- Confirm the 2026-05-28 fix is in place: param contract is **denormalized**
  for `setValueAsCompleteGesture` (memory `juce-param-contract-norm-vs-denorm`).
- Add one test sweep over indices 0..N-1 to guard against future regression
  — even a manual checklist in `juce-shell/README.md` is enough.

### PL-6. VST3 install hygiene

**Files:** `juce-shell/CMakeLists.txt`, packaging script.

- Single install location for shipping: `C:\Program Files\Common Files\VST3\`
  (Release). Remove any LOCALAPPDATA fallback from the build output so FL /
  Bitwig / Reaper cannot scan a stale copy. (STATE.md `Now` lines 57-61.)
- Document in `juce-shell/README.md` the requirement to fully exit DAWs
  before iterating (memory `fl-caches-dll-restart-or-standalone`).

### FG-1. ROM decode — direct unpack

**Files:** `forge/src/forge_core.rs::load_reference_rom`,
`trench-core/src/minifloat.rs::from_rom_bytes`.

- Replace the four `packed.interpolate(0.0, 0.0)` / `(1,0)` / `(0,1)` /
  `(1,1)` decode calls at `forge_core.rs:702-705` with direct unpack of each
  corner's 5 `u16` words (the path already exists at
  `minifloat.rs:183-198`). Result is byte-identical for verbatim ROMs.
- Add a Rust test in `trench-core/tests/`:
  `load_rom_then_export_is_byte_identical` (extends the existing
  `loaded_240_byte_body_exports_verbatim` to specifically cover ROM-source
  bodies).

### FG-2. Forge fabrication fallback — remove from publish path

**Files:** `forge/src/forge_core.rs::body` and
`forge/src/forge_core.rs::Default impl`.

- The `dsp::shift_corner(home, 1.5, ...)` and `dsp::sharpen_corner(home, ...)`
  fallbacks at `forge_core.rs:808-809` may stay as **in-Forge UI seeds**
  (drag a starter into an empty slot) but must not appear in any
  publish/export path. The exporter requires all four corners explicit.
- `q_sharp` UI default stays at 0.3 (its current value, set in
  `STATE.md:418-422` for the puck-opens-on-Q0 behaviour) — `q_sharp` is
  only consulted by the fabrication fallback, so the publish gate is what
  matters, not the UI seed value. (The STATE.md 2026-05-28 "twin-anchor"
  doctrine that retired base→shift→sharpen is about the generator, not the
  Forge UI seed; do not conflate.)
- A body file exported with auto-fabricated corners is rejected at the
  export gate (returns an error, surfaces in Forge UI). The author must
  load / draw / fit a real corner into each of the four slots before the
  exporter will write a `.body240`.

### EX-3. Single owner for shipping interpolation

**Files:** `trench-core/src/cartridge.rs`, `forge/src/dsp.rs`,
`pyruntime/packed_interp.py`.

- Shipping path stays `PackedCorners::interpolate_biquad`
  (`cartridge.rs:303`). This is the only interp the player runs.
- `forge/src/dsp.rs::body_preview` already packs-then-interpolates through
  the core (`STATE.md:294-305` notes the FFI delegation; verify it still
  routes there).
- `pyruntime/packed_interp.py` delegates to `trench_packed_interpolate`
  FFI; raise if core missing (no Python mirror), matching the AGC table
  pattern at `STATE.md:178-187`.
- The decoded-f64 bilinear path in `Cartridge::interpolate`
  (`cartridge.rs:309-316`) is renamed `interpolate_legacy_stages` and
  documented as "fallback when `packed = None`; never used for shipping
  bodies." This makes it impossible to read the code and think there are
  "two production paths."

### EX-4. Boost as metadata, not hidden runtime surprise

**Files:** `forge/src/forge_core.rs` (`EXPORT_BOOST`, exporter),
`trench-core/src/cartridge.rs` (`interpolate_boost`),
`juce-shell/PluginProcessor.cpp`.

- Keep `boost` as **explicit metadata** on the cartridge JSON, but rename
  the constant from `EXPORT_BOOST` (a constant looks fixed) to a
  `default_boost_for_engagement()` helper, with a comment citing AGC indices
  4-7 (`STATE.md:80-84`) so future readers know it is a calibration choice,
  not a blind multiplier.
- The runtime applies `boost` as it does today
  (`cartridge.rs::interpolate_boost`). No change in audible behaviour. The
  *change* is naming and discoverability, not value.
- Each body record may now override `boost`; the publisher (Forge / tools)
  may omit it, and the loader defaults to 1.0 in that case. New bodies
  authored against the "Output knob is the user's control" doctrine ship
  with `boost: 1.0`; legacy bodies retain `boost: 4.0` from their JSON, so
  the roster does not change loudness without intent.

### EX-5. Surface `lastLoadOk` failures

Covered by **PL-3** (audio-thread safe-state). EX-5 is the cross-cut on
**Forge** + **player**: when Forge publishes a `.body240` via the
authoring-slot path used in dev builds, a load failure on the player side
must propagate back to Forge's audition pane so the author sees it, not
just the JUCE log. (Diagnostic-build-only.)

---

## Deferred / opt-in (out of the default player)

| Feature | Where it goes |
|---|---|
| Teleport engine | Compiled in only with `TRENCH_PLAYER_EXTRAS`; default off in shipping. Code stays in tree. |
| SLAM-drive routing as a parameter | Same as Teleport. AGC-engagement remains via `boost` metadata + Output knob. |
| 5D / QSound spatial mode | Same. Single binary, runtime toggle, default off. |
| `TrenchFxPane`, `TrenchViewSwitch`, `TrenchResponseDisplay` (vectorscope) | `TRENCH_PLAYER_DIAGNOSTICS` flag; default off. |
| `TrenchAuthoringSlot` (Forge hot-reload watcher inside player) | `TRENCH_PLAYER_DIAGNOSTICS` flag; default off. Diagnostic build keeps Forge's "Forge Audition" roster slot. |
| Browser audition helpers (`tools/sweep_roster.py`, `target_browser.py`, `make_class_bodies.py`, etc.) | Untouched. Authoring-side; never enter the player runtime. |
| Capture VST (`TRENCH_CAPTURE_VST3`) | Untouched. Separate target. |
| Forge UI experiments | Untouched. Authoring-only. |

---

## Rejected audit claims

Documented so future fresh-eyes audits don't re-propose them.

- **"Strip the chassis / vectorscope / FX pane — consumer plug-in should be
  transparent."** → Rejected on doctrine. Chassis PNG + code overlays IS
  the identity (memory `df2-chassis-is-the-identity`). What we *do*
  agree with the audit on: the FX pane and vectorscope are diagnostic
  surfaces, so they move behind a flag — but the chassis stays for both
  shipping and diagnostic builds.
- **"Remove `EXPORT_BOOST`, default 0 dB; level control belongs in the
  host."** → Rejected. Output level is timbre on this engine because of
  the AGC engagement curve at +22…+28 dB peaks
  (`STATE.md:80-84`). The plan *does* rename and document the
  constant (EX-4) so it is visible rather than hidden, but the value and
  application remain.
- **"Teleport engine is applied by default."** → Falsified. `kEnabled=true`
  in the current build already gates teleport off
  (`TrenchCleanBody.h:9`, `PluginProcessor.cpp:214-232`), defaults
  for mode/amount are 0/0.0. The plan still removes Teleport from the
  default parameter layout (PL-1) — but for *surface clarity*, not because
  it was leaking audio.
- **"Slam drive, 5D enabled by default."** → Falsified. `slamDrive` default
  `0.0f` (`TrenchParameters.cpp:34`), `fiveD` default `0` = Off
  (`TrenchParameters.cpp:46`). The STATE.md 2026-05-28 note about
  `slamDrive=0.35` referred to a regression already patched in-session;
  PL-1 keeps watch for re-regression.
- **"C++ has its own duplicate resampler + biquad path."** → Falsified for
  biquads. C++ does Lagrange SRC only; the cascade lives in Rust and is
  called via FFI (`FixedRateTrenchIsland.cpp:46` → `bridge.process()`
  → `trench_engine_process_block`). No DSP duplication to remove.
- **"Convert ROM bodies to decoded f64 once and use canonical f64 bilinear
  everywhere."** → Rejected. The shipping interp IS the packed-domain
  bilinear (`cartridge.rs:303`, `PackedCorners::interpolate_biquad`), and
  null vs X3 (-95.41 dB) was achieved with it. Converting away from packed
  would break null parity. The audit had the layering inverted.
- **"Require all four corners explicitly defined before assembling any
  body; remove `shift_corner`/`sharpen_corner` entirely."** → Partially
  accepted. The fallbacks must not appear in the publish path (FG-2), but
  they remain valid **in-Forge UI seeds** for dragging a starter into an
  empty slot. Authoring is interactive; only the export is strict.

---

## Verification plan

The rewrite is done when *all* of these pass.

### Build & install
- `cmake --build juce-shell/build --config Release --target TRENCH_VST3
  TRENCH_Standalone` → exit 0.
- Single VST3 in `C:\Program Files\Common Files\VST3\TRENCH.vst3`; no copy
  in `%LOCALAPPDATA%`.

### Core unchanged
- `cargo test -p trench-core` → all green (regression on AGC, packed math,
  null parity, body-bytes-canonical).
- Existing null-vs-X3 ship gate (`tools/null_test.py`) ≤ -60 dB at every
  tested M/Q position; spot-check M50/Q50 should still hit -95 dB band.

### New player guarantees
- Load fresh shipping build in `TRENCH_Standalone.exe` with no input.
  Calibrated sine through the cascade with default params: bit-exact to
  the same input run through the standalone Rust core via FFI (`pyruntime`
  bridge). No extras altering output.
- Failed body load (point the roster at a deliberately broken JSON): plug-in
  bypasses (silent or dry per choice), `getLastLoadOk()` returns `false`,
  chassis overlay shows "BODY FAILED — bypass", JUCE log shows the parse
  error.
- Body strip click-through 0..N-1 lands on the named body every time
  (regression guard for `juce-param-contract-norm-vs-denorm`).
- `inputMode` default = Normal, `slamDrive=0`, `fiveD=Off`,
  `teleportMode=Off`. (Param dump on first boot.)
- In shipping build the FX pane and vectorscope are absent from the
  editor (View switch is gone or stubbed). In `TRENCH_PLAYER_DIAGNOSTICS`
  build they reappear unchanged.

### Forge / authoring
- `cargo test -p trench-forge load_rom_then_export_is_byte_identical`
  (new) → all green.
- Forge export with one corner missing → returns an explicit error,
  surfaces in UI, no `.body240` written.
- `EXPORT_BOOST` → `default_boost_for_engagement()` rename builds; existing
  cartridges in `juce-shell/assets/cartridges/` load with audibly
  identical level.

### A/B against the current build
- Run the 8 shipped originals (Voice Walk, Mason Tube, Knock Burst, Metal
  Scream, Phaser Slide, Cut Edge, Maul, Razor Shell from STATE.md `Now`
  17-22) through current build vs rewritten build at the same DAW gain.
  Audible regressions = blockers; subtle level differences attributable to
  the documented EX-4 path are acceptable as long as `boost` metadata is
  preserved.

---

## Out of scope for this plan

- Authoring/Forge UI changes beyond FG-1 / FG-2 / EX-3.
- Any new DSP, format, or body fields. The 240-byte format is frozen.
- A Cartridge V2 format. Memory `df2-two-plugins` and the 12-pole/12-zero
  ceiling discussion (`STATE.md:77-79`) belong to a future engine,
  not this rewrite.
- Marketing surface / naming / chassis art changes. Code-overlay polish only.

---

## Open questions for the next pass (post-approval, before execution)

1. **`TRENCH_PLAYER_DIAGNOSTICS` granularity** — one flag, or split
   (`...DIAG_FX_PANE`, `...DIAG_HOT_RELOAD`, `...DIAG_VECTORSCOPE`)?
   One is simpler; split lets QA isolate.
2. **Failed-load behaviour: silent vs dry.** Bypass-with-silence is safe;
   dry passthrough avoids a "no audio" panic call. Default to one in this
   plan and revisit by ear.
3. **Body-strip regression guard** — manual checklist in README or a
   `pluginval`-driven script in CI? Both are cheap.
4. **Roster-side `boost` migration** — when EX-4 lands, do we rewrite the
   existing cartridges in `juce-shell/assets/cartridges/` to make `boost`
   explicit (preserving current values), or leave them as-is and rely on
   the loader default? Explicit is honest; rewriting touches 50+ files.
