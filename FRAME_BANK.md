# FRAME_BANK.md

The frame bank is the upstream supply of static single-corner filter
states that 4-corner bodies are assembled from. This file is the durable
home for sourcing strategy, the Clean Room rule, and the validation gate.

Forge-generated bodies are flawed. The path forward is measured material
from real E-mu filters, re-authored under Clean Room.

## What a frame is

A **frame** is one static, fully-specified filter state at one corner
location: 6 cascaded biquad stages × kernel-form coefficients, plus a
behavioral signature and provenance record.

```
frame = {
  "id": "f0001",
  "stages": [{c0, c1, c2, c3, c4}, ...×6],
  "signature": {
    "peaks_hz":    [freq, ...],
    "notches_hz":  [freq, ...],
    "tilt_db_per_oct": float,
    "peak_db":     float,
    "band_center_hz": float,
    "band_width_oct": float,
    "category":    "vowel|comb|distortion|cavity|bass|brite|...",
    "label":       "Ah (large cavity)" | ...
  },
  "provenance": {
    "method":      "measured|authored",
    "source":      "P2k_017_M0_Q100" | "X3_Voxxy_LP_1",
    "extraction_date": "YYYY-MM-DD",
    "notes":       "..."
  }
}
```

A **body** is 4 frames assigned to corners (M0_Q0, M0_Q100, M100_Q0,
M100_Q100), plus a global boost and a name.

## Capture methods

### Tier 1 — P2K 4-corner decode from EosAudioEngine.dll

- **Source**: 240-byte coefficient blocks in `.rdata` section.
- **Yield**: 33 filters × 4 distinct corners = 132 frames.
- **Capture rule**: engine must be running at 39062.5 Hz. Captures at
  44100 Hz or higher contain `sqrt` compensation warping and are invalid.
- **Runtime offsets** (Cheat Engine validation):
  - Corner A (M0,Q0)    = `0x2C0`
  - Corner B (M100,Q0)  = `0x2FC`
  - Corner C (M0,Q100)  = `0x338`
  - Corner D (M100,Q100) = `0x374`
- **Storage**: `ref/p2k_skins/` — reference only, never shipped.

### Tier 2 — XML 2-corner extract from Emulator X templates

- **Source**: `designer-section` arrays in `Emulator X Templates/Filter/*.xml`.
- **Yield**: 77 templates × 2 corners (Q-duplicated) = 154 frames.
- **Limitation**: Q axis is degenerate — Q knob has zero effect on these
  frames. Pair with hand-authored Q100 frames when assembling bodies.

### Capture validation

Before trusting binary captures, dual-capture at least one filter
(P2k_017 Vocal Ah-Ay-Ee recommended) via both Ghidra static decode and
Cheat Engine runtime memory dump. Values must agree. Disagreement
implies runtime modification (per-voice scaling, AGC at load time) —
investigate before extending.

## Clean Room rule

The 33 P2K binary tables are the most valuable reference data and the
most legally sensitive. The workflow:

1. **Measure** the captured 240-byte block or the canonical wet render.
   Characterize the behavioral envelope: peaks, notches, tilt, corner
   shape, Q character.
2. **Author** a new 6-stage frame inside df2 that hits the same
   behavioral targets. Coefficients must differ.
3. **Document** in the frame's `provenance` block: which P2K filter was
   referenced, what the target envelope was.

Captured coefficients live in `ref/p2k_skins/` (reference). Authored
frames live in `vault/_frames/` (shipping material). Different directories,
different rules.

## Validation gate: null test

Bodies are validated by null test against E-mu wet renders, not by
visual magnitude match.

**Procedure**: render dry pink noise (or log chirp) through E-mu
Talking Hedz at known M/Q corner positions, capture at 39062.5 Hz.
Render the same dry signal through the authored df2 body. Sample-align,
invert one, sum, measure RMS difference in dB.

**Pass thresholds**:
- ≤ −90 dB: bit-accurate reproduction
- ≤ −60 dB: pass — perceptually identical, structural agreement
- −30 to −60 dB: structural agreement, real divergence; investigate
- ≥ −30 dB: pipeline failure

**Residual analysis**: if null residual scales with input level, suspect
runtime AGC (currently unproven). Document and investigate before
extending the pipeline.

**Tool**: `tools/null_test.py`.

## Frequency coverage discipline

Audit every frame for band coverage. Empty bands = body classes that
cannot be authored.

| Band       | Frequency      | Body classes that need it |
|------------|----------------|---------------------------|
| sub        | 20–80 Hz       | Speaker Knockerz          |
| low        | 80–250 Hz      | Speaker Knockerz, Cul-De-Sac |
| low-mid    | 250–1k Hz      | Small Talk, Cul-De-Sac    |
| high-mid   | 1k–4k Hz       | Small Talk, all vocal     |
| high       | 4k–10k Hz      | Aluminum Siding           |
| air        | 10k–20k Hz     | Aluminum Siding           |

Audit lives in `STATE.md`. If a shipping body's target band has zero
frames, that body cannot ship.

## Q-axis semantic rule

The Q axis is **not** a second vowel/character axis. It varies a physical
modifier of the same base shape (cavity size, body resonance, mouth
tightness, brightness intensity).

| Corner pair          | Allowed difference     | Banned difference        |
|----------------------|------------------------|--------------------------|
| M0_Q0 vs M0_Q100     | cavity, tilt, Q amount | vowel identity, category |
| M100_Q0 vs M100_Q100 | cavity, tilt, Q amount | vowel identity, category |

UI labeling: don't call the axis "Q" in shipping UI. Use "Body,"
"Cavity," "Mouth," "Size," or another body-specific term. Frame
`category` tags must match across the Q pair.

Authoring discipline: before assembling a body, write one sentence
naming both the morph and Q motions.

  *Example: "Morph moves Ah→Ee while body size tightens."*

If you can't write that sentence cleanly, the assignment is wrong.

## Pipeline

```
ref/canonical/*.wav  ──┐
ref/p2k_skins/*.json ──┼──► tools/extract_frames.py ──► vault/_frames/*.json
ref/x3_displays/*.png ─┤
                              │
                              ▼
                       tools/frame_catalog.py
                       (search / filter / inspect)
                              │
                              ▼
                       tools/body_assemble.py
                       (4 frame IDs → body JSON)
                              │
                              ▼
                       tools/compile_raw.py
                       (body JSON → compiled-v1 cartridge)
                              │
                              ▼
                       JUCE plugin loads cartridge
                              │
                              ▼
                       tools/null_test.py
                       (validates against reference WAVs)
```
