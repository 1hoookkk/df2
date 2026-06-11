# TRENCH FORGE painter — session handoff (2026-06-11)

**Use as a transitional prompt:** start the new session with
*"Read `forge-gpu-painter/HANDOFF.md` and `forge-gpu-painter/SPEC.md`, then continue."*
CLAUDE.md and the memory file `gpu-painter-direction` load automatically and carry the laws;
this file carries the session state.

## What this is

`forge-gpu-painter` — the Z-plane filter designer. eframe/wgpu, fully custom painted,
trench-core linked in-process. Every curve is computed from `trench_core::compiler::pack_body`
bytes through the engine's own word-lerp: **plot == engine by construction.** Tyson authors
bodies here; KEEP stages them for the bank; his verdict completes a bank entry.

## Direction: SPEC is now Peak/Shelf Morph first

`SPEC.md` has been rewritten around the Dillusion Peak/Shelf Morph tutorial:
two morph frames, each with FREQ / SHELF / PEAK, plus MORPH, PRESSURE, MASTER,
AUDITION, BAKE, KEEP. The old research/workbench surface is not the target front
door anymore. Keep the full custom code painter architecture, packed-runtime plot,
audit, audition, and KEEP pipeline, but move corner/stage/budget machinery behind
DETAILS.

## State: older workbench features are built, but should be folded behind DETAILS

This session added, all OBSERVED with headless proofs:

- **GPU plot layer** (`src/gpu_plot.rs`): one WGSL pass = hero core + glow + underfill +
  ghosts + Q-compare + brush footprint from a 480×4 R32Float row texture. Mirrors
  `axis_t/axis_f` (log AND Bark) and `y_for_db` exactly. egui path remains as fallback.
- **De-jank**: trench-core at dev opt-level 3 (`package."*"` skips workspace members — root
  Cargo.toml), `request_repaint()` not `_after(16ms)`, handle drags 1:1 on the axis,
  Ctrl-deliberate pins, cursor-anchored refusal hints, no cartridge parse in the audio callback.
- **Magnitude math**: cos-form power identity, **f64 trig + f64 accumulation**
  (`biquad_db_c`/`grid_trig`/`eval_packed_goal_t`). `--mag-test` arbitrates vs f64 complex
  truth: 0.000011 dB, 2.2× faster than the old form. **f32 here ships tens-of-dB notch errors
  (catastrophic cancellation) — never touch this math without re-running `--mag-test`.**
- **Workflow**: frames are the working unit — **Tab/Shift+Tab** flip frame/Q-row; **Q LINK**
  (bar2 chip, default on) derives Q100 rows from Q0 (r → 1−(1−r)·0.35); editing a Q100 corner
  auto-unlinks. Travel arcs: selected section's other-frame pole/zero as hollow draggable dots.
  Role labels on cards ("chest 134 Hz", F1–F3, p1–p6). **Hold C** = opposite-Q overlay.
  **Hold D + drag** = draw-the-target → Bark-binned pins → goal solve. **Hold H** = controls card.
  Plain plot drag stays inert; **Alt-drag on the white curve** deliberately enters the
  experimental inverse grip. It works at any (morph, q) by moving the nearest corner through
  the packed word-lerp at the live interior point. Autosave 30 s after edits → SEED ▸ restore.
- **KEEP** (bar1): fresh synchronous 17×17 audit (refuses if unstable) → stages
  `desk/bank/v1/staging/<slug>/` = body240 + cart.json + source.json + audit.json +
  provenance.json (SHA-256, encoder identity). BANK.md rows remain Tyson's.
- **START source browser**: bar2 **START** opens a categorized two-column menu with mini
  response plots. Verified editable Law Author rows load their `stages.json` sidecars into
  the six-biquad editor; verified packed preview rows draw from cached `.body240` bytes and
  remain preview-only until an inverse/import path exists. Exact starts still expose only
  skeletons that pass `python tools/verify_exact_skeletons.py`. Current result: Butterworth
  passes; Cheby2 and Elliptic fail the packed check and are hidden.
- **Plain six-biquad budget**: the right rail now shows `6 BIQUADS`, poles used, zeros
  used, and which S1-S6 slots are `pole+zero`, `pole only`, `zero only`, `flat`, `weak`,
  or `unused`. Section cards use the same plain labels instead of role names.
- **AAA vs VF bench** (`dev/tmp/capture_fit_bench/`): AAA wins smoothed envelopes, VF wins raw
  periodograms → routing rule recorded in SPEC §4.
- **Layout** (after "it doesn't flow"): bar1 = name·BAKE·AUDITION·KEEP·lamp; bar2 = menus +
  Q LINK + readouts; **right rail (always on) = navigation hub**: corner chips 2×2 laid out AS
  the morph square (same orientation as the surface map below), map = XY pad, MORPH/Q sliders,
  PLAY|SWEEP + NOISE/SAW/PAD, audit pins, morph-sweep map. Hit-testing is Frame-rect based —
  moving chips never touches `interact()`.

## Verify before claiming anything

```powershell
# close any running painter first — the exe lock silently fails builds
cargo build -p forge-gpu-painter --release
./target/release/forge-gpu-painter.exe --mag-test      # NEW EXACT, ~2×
./target/release/forge-gpu-painter.exe --goal-test     # accepted, 8.4 → 4.5 dB
./target/release/forge-gpu-painter.exe --interior-test # +5.57 of +6.0 dB at M45/Q30
./target/release/forge-gpu-painter.exe --draw-test     # 23 pins, 3.4 → ~1.1 dB
./target/release/forge-gpu-painter.exe --bake-once
./target/release/forge-gpu-painter.exe --keep-once     # stages + cleans a bundle
```

Screenshot loop: launch with `--boot-seed | --boot-bark | --boot-sweep | --boot-qcompare |
--boot-help | --boot-exact`, capture via `dev/tmp/painter_ux_session/capture.ps1`
(CopyFromScreen — PrintWindow returns black for wgpu), Read the PNG, judge against the
design law (hero curve only, near-black ground, textbook strings, no chrome).

## Cautions

- **The working tree is uncommitted** and mixes pre-session changes into `main.rs`.
  Commits are Tyson's call. Source checkpoints: `dev/tmp/painter_ux_session/main.rs.bak-*`.
- SPEC item 7 (differentiable surface optimizer) stays gated until the bank holds ≥ 3 bodies.
- Scratch boot is law; seeds/restore are explicit actions. Don't re-add chrome; Tier 3 is
  Tyson's hands. Register: textbook DSP only.

## The actual next move (not a tool)

The bank (`desk/bank/v1/BANK.md`) is empty while **40 corridor-surviving candidates sit on
the judgment sheets** (`desk/SHEETS.md`, wave1 + wave2). The highest-leverage hour is Tyson's
verdict session — keeps/kills in his words, first KEEP press, first bank rows. Machinery
changes need a failed verdict as their license (CLAUDE.md).
