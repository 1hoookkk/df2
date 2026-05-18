# STATE.md

**This file is the live cache.** Claude updates it on every code change.
If you (Tyson) want to know current project state, read this file.
If it disagrees with the repo, Claude is required to fix it before
doing new work (per CLAUDE.md session protocol).

Do not edit by hand unless correcting Claude.

---

## Current focus

(empty — set when first session starts)

## Pipeline status

- [ ] `trench-core/` carried over from old repo and building cleanly
- [ ] `juce-shell/` carried over and loading cartridges
- [ ] `tools/compile_raw.py` carried over and tested
- [ ] `tools/null_test.py` runs and produces null depth in dB
- [ ] First null test against `ref/canonical/` passes (internal consistency)
- [ ] Fresh X3 wet render of Talking Hedz captured for ground-truth null
- [ ] First df2 body authored: Talking Hedz match (calibration fixture)
- [ ] Talking Hedz match passes null test at all 4 corners ≤ −60 dB
- [ ] Talking Hedz match thrown away; pipeline now trusted

## RE findings & policy (2026-05-18)

### Reference extraction policy

`ref/ghidra_extracts/` is a measurement basis only — never shipping
source. Every extract carries a `_provenance` header and
`ships_in_df2_binary: false`. Authored cartridges null-test against
extracts; they never copy extracted coefficients. No extraction is made
without a named null test it supports.

### QSound source set carry

- QCreator/QMixer source set carried from
  `C:\Users\hooki\trench_re_vault\analysis\qsound_lab\qcreator_extracted_auto`
  to `ref/ghidra_extracts/qsound/qcreator_1998_source_set/`.
- Form: QCreator 1.0 / QMixer.dll extracted installer payload, help/content
  files, demo WAVs, and extraction manifest. This is not yet a clean E-mu
  QSound capture and does not retire the TODO constants in
  `trench-core/src/qsound_spatial.rs`.
- Current QSound status: source material located; authoritative ITD scalar,
  low/high shelf corners, ILD law, ITD law, and band-law tables still need
  extraction or matched clean capture proof.

QSound spatial null test target:
  Source: `ref/ghidra_extracts/qsound/qcreator_1998_source_set/` plus any
  future clean E-mu/QSound captures or Ghidra table extracts.
  Targets:
    - ITD samples-per-law-unit constant replacing the current TODO scalar.
    - Low/high shelf corner Hz replacing current engineering defaults.
    - ITD law coefficients and ILD law coefficients for `SpatialProfile`.
    - Left/right low/mid/high band-law coefficient tables.
  Verification: df2 stereo output through `qsound_spatial.rs` must null
    against measured/extracted QSound output at matched ITD/ILD/distance
    parameters to <= -60 dB across the +/-60 degree azimuth sweep.

### Verified RE findings

- 5 computed filter classes: CPhantomMorphLP / MorphLPX / Morph2 /
  MorphDesigner / FilterP2k. vtables at 0x1806d60d8 / 60f0 / 6110 /
  6130 / 6150.
- MorphLP zero table at DAT_1806d73c0 (16 × 12 bytes) — verified.
- MorphLPX zero table at DAT_1806d7480 (15 × 6 bytes) — verified.
- Bypass sentinels 0xDFFF / 0xFFFF at DAT_1806d7500, used by the master
  compiler FUN_1802c6590 for cascade padding.
- Stage type bytes 1/2/3 confirmed. Type 3 split-code hack
  (> 0xDB → 0xDC anchor at negative morph) applies only to filter
  classes 0/1.
- Cascade is variable-length 1–6 stages; active count at object
  offset 0x420.
- Talking Hedz descriptor lives in a runtime-loaded bank table indexed
  by skin 13 — NOT at a static .rdata address.

### Rejected hypotheses

- ARMAdillo octaves/dB perceptual encoding — scaling tables are
  filter-class linear (slope, offset) pairs, not perceptual.
- Morpheus 3D 8-corner cube architecture — not present in
  EosAudioEngine.dll (NotebookLM conflated Morpheus hardware with
  Emulator X).
- Q axis as a universal perceptual modifier — only true for
  P2K-authored vocal filters; MorphLP-routed filters collapse Q
  structurally.

### Open questions

- Audition harness not yet built (breakbeat / sustained Ah / saw chord
  A/B loop) — prerequisite before authoring the first shipping body.
- First Ghidra MCP session: extract the AGC 16-element table at its
  function offset, cross-reference against `agc.rs` const. Match →
  `agc.rs` provenance-verified; mismatch → `agc.rs` is wrong.
- Talking Hedz descriptor recovery — trace the constructor that
  initializes the bank table FUN_1802c0150 reads.
- `cascade.rs` ↔ Rossum biquad equivalence — Rust unit test; blocks
  meaningful null tests against E-mu reference.
- `hedz_rom.rs` feature-gating — first runtime work next session.
- `tools/heritage_coeffs.py` has broken imports — it `import`s
  `pyruntime.encode` / `pyruntime.stage_params`, which were not carried
  (the `pyruntime` package belongs to the divergent `trenchwork_clean`
  repo). The file does not run standalone. Decide: vendor the needed
  `pyruntime` modules, or rewrite `heritage_coeffs.py` self-contained.
- Carry-over quarantines (see `dev/tmp/inventory.md`): canonical
  wet-render set undefined; P2K count 43/35/35 conflict;
  `emu_zplane_filter_types.xml` is a manual transcription;
  `juce-shell/source` is forge-era; `talking_hedz_x3_surfaces` JSON
  provenance unclear.

### Resolved (2026-05-18)

- Quarantine #3 (`heritage_designer_sections.json` NotebookLM-derived):
  resolved. Genuine E-mu vendor Filter XML located in `Emulator X
  Family / Templates (2) / Filter` (69 templates) and carried to
  `ref/heritage/`. `heritage_designer_sections.json` regenerated from
  the XML via `tools/extract_designer_sections.py`
  (`heritage-designer-sections-v2`); the NotebookLM JSON is not carried.
  The old `template_count: 83` = 69 vendor + ~14 user-authored scratch
  files (the latter live only in the fuller `Templates/Filter` set).

## Shipping bodies status

| Body              | Authored | Null pass | Audible pass | Notes |
|-------------------|----------|-----------|--------------|-------|
| Speaker Knockerz  |          |           |              |       |
| Aluminum Siding   |          |           |              |       |
| Small Talk        |          |           |              |       |
| Cul-De-Sac        |          |           |              |       |

## Frame bank coverage

| Band                  | Frame count |
|-----------------------|-------------|
| sub (20–80 Hz)        | 0           |
| low (80–250 Hz)       | 0           |
| low-mid (250–1k Hz)   | 0           |
| high-mid (1k–4k Hz)   | 0           |
| high (4k–10k Hz)      | 0           |
| air (10k–20k Hz)      | 0           |

## Open questions

- Does runtime AGC exist in the E-mu engine? (Detect via null residual
  scaling with input level.)
- Is the MorphLP zero table's `FUN_1802c59b0` decoder worth REing, or
  does null testing against captured wets make it unnecessary?
- Capture method drift: are the existing 164 wet renders in `ref/canonical/`
  rendered through the same cascade math df2 uses? Verify before
  treating null results against them as ground truth.

## Active session

(Claude fills this in when working. Clears on session close after
appending to SESSION_LOG/.)
