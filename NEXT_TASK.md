# State — THE TRENCH DESIGNER IS THE SURFACE (2026-07-26)

The Workstation opens INTO the Designer (full window; Esc = classic assembly
bench). Everything below is committed on ui/five-point-cleanup and pushed.

## What the Designer is now

- Engine: `trench-core/src/designer.rs` + FFI. Parity 69/69 heritage XMLs
  byte-equal (`cargo test --test heritage_parity`, fixtures vendored).
- Surface: 6 stage rows, scrub-drag sliders (dbl-click types, wheel steps),
  plain names FREQ/RES/LEVEL/ZERO/DEPTH, per-stage LO/HI anatomy minis,
  live 5-curve JOURNEY strip, section-level UNDO/REDO (one step/gesture).
- SHAPE dropdown speaks P2K: OFF/EQ/LP/HP + census roles PEAK / FORMANT /
  SWEEP / TILT / NOTCH (measured zero relations; imported rows read "P2K").
- Q pages: Q0/Q100 poses x M0/M100 rows = the 4-corner grid. AUTO Q100 =
  MD-Q bw x0.375 sketch.
- IMPORT: any loaded body (ROM preset, candidate, rail fit) lands as
  editable sections; the photograph stays as a grey A/B ghost. Proven on
  P2k_013 Talking Hedz incl. the S1 far-rail and S6 traveling-notch frame.
- WRAP (the cheat): drop a wav -> ARMA fit of early/late halves -> 4
  measured voices on S2..S5 + hedz TILT/NOTCH frame + AUTO Q100, playing
  through itself immediately. `dwrap` headless.
- Gates on every edit: certify 9x9, L10 active-row framing (you always hear
  the framed level), family gate RIDE/ARCH (advisory — ear judges). SAVE
  overwrites its own name in `bodies/candidates/`.
- Live drive: rewrite `ws_live.json` (or TRENCH_WS_SCRIPT path) while the
  app runs -> actions execute. Startup never replays a stale file.
  Actions: designer dpage dtype dset dshift dtemplate dmotif dsketch
  dfamily dsave dimport dwrap ddump + classic set.
- Plugin: in-place hot-reload — the processor watches the loaded body's
  .body240; Workstation SAVE updates the DAW plugin in <0.5 s (code in
  shared processor; reaches the DAW at next install).

## Repo

master = minimal load-bearing tree (56641dac lineage), pushed. Dev branch
pushed. Uncommitted stragglers: roller-glow files (trench_roller_strip.png,
UiLayout.h, SelectorLookAndFeel.h, TypeSelectorView.h, retint_roller_glow.py)
— commit or discard, Tyson's call. Stale branches still to cull.

## Open, gated on Tyson

- VST3 install (ship-vst3) — the built plugin includes hot-reload; explicit
  go required, then prove the bench->DAW loop live.
- Ear pass over candidates: TRENCH_HEDZ (hedz caricature: wider S1 ride,
  notch from 4.2k), VOWL_bahn_to_tiere (raw measured DVTD vowel journey —
  "its correct"), plus the earlier 5 functional TRENCH_*, TRENCH_303,
  7 XSTUDY_* (study-only), 21 CAVL.
- Wants noted, not built: 2x2 simultaneous corner view if pages feel
  blind; rail fitters (LPC/magnitude) folded into trench-core so zero
  Python remains in the loop.
