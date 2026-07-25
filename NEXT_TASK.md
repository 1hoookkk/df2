# Next session — THE TRENCH DESIGNER (native authoring panel, fence OFF)

Goal: MD ergonomics + P2K reach inside the Workstation. Tyson designs in the
GUI; no compiler scripts, no Claude in the loop. L15 proved the ceiling was
the FENCE, not the surface; TRENCH-303 proved our primitives reach it.

Shipped meanwhile (2026-07-25): `tools/body_watcher.py` — save a
`*.registered_lanes.json` in `bodies/drafts/` → validate → pack+certify
(trench-core) → L10 active-row framing → re-certify 9×9 → journey PNG →
atomic drop into `bodies/candidates/`. Failure keeps last known-good.
Open gap (gated on go): in-place reload of the currently loaded body in the
plugin (today: reopen TYPE menu).

## 1. Engine (trench-core + FFI) — do FIRST, it unblocks everything

- `heritage.rs::compile_designer_stage` already emits type1/2/3 firmware
  words (RE recipe). PARITY TARGET SETTLED 2026-07-25: the oracle is the
  DIRECT firmware words. Proven: firmware words survive the f64
  kernel→encode round trip 27735/27735; the Python StageParams f32 chain
  drifts ±1 minifloat code on 55/69 XMLs (plumbing artifact, not law).
  `dev/tmp/xml/*.body240` are NOT oracles (lost script: fixed shift −32,
  invented Q poses) — generate fixtures fresh from `df2/ref/heritage/*.xml`
  through the direct-word path.
- Remaining Rust work: corner/body assembly (XML morph lerp with Python
  round semantics, shift = −32 + int((frequency+gain)·63), corner order
  M0Q0/M100Q0/M0Q100/M100Q100, LE u16 pack); TYPE FREE = pole (ladder step,
  r) + independent zero (ladder step, r 0..1.0) + scale via
  `words_from_roots`; FFI `designer_compile_corner(sections, morph, q) ->
  30 words` + `designer_body(sections) -> 240 bytes`, live-rate.
- Done = 69/69 heritage XMLs byte-equal through the Rust port (cargo test).

## 2. Panel (WorkstationEditor, mirror the X3 layout he screenshotted)

- Per stage (1–6): SHAPE dropdown = EQ / LP / HP / FREE.
  LO MORPH row: FREQ (ladder-quantized knob, ~68.4 c/step), Q, GAIN.
  HI MORPH row: same. FREE adds ZERO freq + r knobs per row.
- Zero-motif picker for FREE (starting points, editable — VERIFY numbers
  against the ROM zero-grammar census before hardcoding; claimed set:
  tooth ~0 oct / trailing −0.6 / leading +0.9 / far rail >1.5 /
  true notch r=1.0 +1.7).
- Q PAGE (not a knob): Q100 poses pre-filled ×0.375 sketch, every field
  hand-editable (derivation is a sketch, never the ship value).
- JOURNEY strip above the curve: live 5-curve M0..M100 miniplot
  (packed_probe FFI), always visible. Fixed −60..+30 scale (plot law).
- TEMPLATE menu = census rails (bass ride 110→330, sub→growl riser 30→1000,
  mid-climax arch 30→2200→300, parked squelch ~370–400, HF dropper
  9700→100, mid descender 4000→1500, vowel arch out-and-home) +
  attic-stack 303. Opening one pre-fills all six stages; he re-tunes.

## 3. Gates (background, every edit — the fence replaced by a net)

- certify(): packed stability over 9×9 Morph×Q grid (existing).
- Journey check: family-aware (arch wants mid crest, ride wants
  no-collapse; the real 303 FAILS a naive mid-crest gate).
- Framing L10 on SAVE: active-row framing (crowns +2/+8/+25/+27), never
  frame identity rows (silent-body trap). Same law the watcher runs.
- SAVE writes certified `.body240` → `bodies/candidates/` (TYPE menu scans
  it).

## 4. Proof plan (before install — install stays gated on Tyson)

- Parity: 69/69 heritage XMLs byte-equal through the Rust port.
- Round-trip: author Bass Shaper in the panel from scratch ≈ XSTUDY compile.
- Reach: rebuild TRENCH-303 (attic stack, free zeros) entirely in-panel.
- Headless: TRENCH_WS_SCRIPT actions for every new control.

## Standing context

- FILTER_NOTEBOOK.md deleted 2026-07-25 (de-ceremony). Measured laws
  recoverable: `git show 8d22ad19:FILTER_NOTEBOOK.md`. CLAUDE.md is the
  lean contract now.
- Builders to fold in then retire: `dev/tmp/journey01/build_*.py`.
- Candidates in menu awaiting his ear: 5 functional TRENCH_*, TRENCH_303,
  7 XSTUDY_* (study-only, never ship), 21 CAVL.
