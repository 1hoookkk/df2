---
name: physical-corners
description: Build df2/TRENCH filter corners from REAL physical models (vocal-tract / tube / modal acoustics) instead of fitting WAVs or hand-placing formants. Use when asked to author corners, bodies, or cartridges "from physics", "physically modelled", "vocal tract", "tube/pipe", "modal/bell/drum/plate/string", or to generate a 4-corner morph grounded in acoustics. Writes a compiled-v1 cartridge that the running TRENCH hot-reloads.
---

# Physical-modelling corners

A df2 corner is a spectral shape: 6 resonant sections (poles) with optional
anti-resonances (zeros). With **real physical modelling you don't fit anything** —
an acoustic model's modal frequencies + dampings ARE the poles, and its
anti-resonances ARE the zeros. This skill turns a physical spec into **4 distinct
corners** (exactly like the ROM's 4 verbatim corners — M0_Q0 / M100_Q0 / M0_Q100 /
M100_Q100) and writes a `compiled-v1` cartridge to
`~/Documents/TRENCH/authoring_slot.json`. A running TRENCH (standalone or VST)
hot-reloads it within ~0.5 s. The runtime morphs between the 4 — the "magic in the
middle", grounded in acoustics.

## Pipeline
```
physical model → modal freqs + dampings (poles) [+ anti-resonances (zeros)]
   → 6-section CornerData (kernel form, df2 rate 39062.5 Hz)
   → 4 corners → compiled-v1 cartridge → authoring_slot.json → TRENCH hot-reloads
```
No WAV, no spectral fitting. The script: `scripts/physical_corners.py` (numpy only).

## The three models (`--model`)

- **`tract`** — Kelly–Lochbaum lossless tube from a vocal-tract **area function**
  (reflection coeffs → all-pole polynomial → roots = formants). Default morph =
  `u a i ae`. NOTE: the lattice is exact (a uniform tube returns 500/1500/2500 Hz,
  the neutral schwa), but **canonical vowel accuracy needs measured area functions**
  (Story/Titze MRI). The built-in area functions are approximations — they produce
  *real* tract resonances, just not textbook-precise vowels (F1 plateaus ~700–850
  for close vowels). To sharpen: replace the vectors in `VOWELS` with measured data.
- **`tube`** — open/closed/conical cylindrical pipe. **Textbook-exact:** closed-open
  17.5 cm → 500/1500/2500/3500… = (2n−1)·c/4L. Four lengths = a pipe-size morph.
- **`modal`** — `--kind bar|membrane|plate|bell|string`. Modal frequency ratios +
  dampings → inharmonic resonant bodies (bells, drums, metallic). Four fundamentals
  = a body-size morph.

## Run — PRIMARY path is `--preset` (curated physical bodies)
Physics is the primary corner factory; WAVs are a flavor option in the Forge picker.
```bash
# pick a curated physical body (4 whole corners) and hot-reload it
python .claude/skills/physical-corners/physical_corners.py --preset morph_worlds
python .claude/skills/physical-corners/physical_corners.py --list-presets
# presets: vox pipes bells glass skins  (single-domain)
#          throat_metal morph_worlds cavern string_voice  (cross-physics = crazy filters)
```
Raw model access (when a preset isn't enough):
```bash
# default: physical vocal-tract vowel morph, hot-reloads into TRENCH
python .claude/skills/physical-corners/physical_corners.py

# inspect the physics without writing
python .claude/skills/physical-corners/physical_corners.py --model tract --list-formants

# a closed-open pipe morph (exact acoustics)
python .claude/skills/physical-corners/physical_corners.py --model tube --length 18

# a bell-body morph
python .claude/skills/physical-corners/physical_corners.py --model modal --kind bell --f0 220
```

## Notes
- Output rate is fixed at df2's authoring rate (39062.5 Hz); poles are placed there.
- Corners are peak-normalised (~+6 dB heritage base); cartridge `boost` ~1.5. The
  player's output saturation stage catches any transient overshoot.
- Each corner keeps ≤6 sections (the ROM corner budget). Don't add "stages" — 4
  distinct corners is the whole contract.
- Roadmap: plug measured Story area functions into `VOWELS` for canonical vowels;
  add conical horns and 2-mass voiced source; per-corner anti-formant (nasal) zeros.
