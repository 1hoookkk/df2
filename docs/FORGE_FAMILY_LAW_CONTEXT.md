# Forge Family Law Context

This is the durable context pulled out of `dev/tmp`. The temp reports are study
material; this file records the clean-room laws to use for Law Author.

## Source Folders

- `dev/tmp/x3_p2k_family_browser/`
  - Highest leverage family contracts.
  - Uses aggregate bounds only.
  - Key files: `contracts/*.json`, `report.json`, paired response/root plots.
- `dev/tmp/p2k_full_vocabulary/`
  - Numeric rail and move-family evidence.
  - Key files: `frequency_rails.csv`, `skin_summaries.csv`,
    `row_motion_vocab.json`, `report.md`.
- `dev/tmp/p2k_reference_grammar/`
  - Zero-role and motion-law evidence.
  - Key files: `report.md`, `summary.json`, `pole_zero_tracks.png`,
    `foundations.png`.
- `dev/tmp/p2k_template_foundation_stages/`
  - Foundation-frame evidence.
  - Key files: `README.md`, `template_stage_summary.csv`,
    `foundation_reuse_nearest_response.csv`.

## Converted Laws

`tools/convert_family_reports_to_laws.py` converts the aggregate family
contracts into original `section-law-v1` presets under `recipes/laws/`.

Current converted laws:

- `family_bandpass_swept_eq.json`
- `family_morph_special.json`
- `family_phaser_comb.json`
- `family_slope_ladder.json`
- `family_vocal_formant.json`

All five currently compile through `tools/law_author.py` and pass the packed
runtime audit with max pole radius at the Q rim (`~0.9999`).

## Core Laws

### L1: Anchor

At rest, one low/body resonance must make the plot read as terrain rather than
flat response. The useful range is roughly `190-340 Hz`, depending on family.
This is not a hidden stage; it is one of the six real lanes.

### L2: Descending Terrain

The high band is subordinate to the body band. Strong downward tilt is legal.
The audit should reject high-band domination, not reject every steep downward
slope. Some converted families legitimately show corner tilt below `-100 dB`
while remaining stable and finite through the packed probe.

### L3: Canyons

Zeros are first-class. Every authored stage exposes zero Hz and zero radius.
Canyons exist at rest, not only after Q is cranked.

### L4: Q Crank

Secondary/Q should lock frequency and drive radius. Legal Law Author bodies may
hit `pole_r = 0.9999`; stability is judged by the packed-runtime probe, not by
a timid pre-cap.

### L5: Remote Zeros

Zeros do not have to hug poles. In the selected reference grammar:

- `7200 / 7200` sampled rows had numerator structure.
- `28.2%` of endpoint zeros were more than `1.5 octaves` from their pole.
- Mean pole-vs-zero motion disagreement was about `1.75 octaves`.

Law Author should allow `zero_offset_oct` and `zero_morph_oct` to move
independently from pole motion.

### L6: Six Lanes Only

Foundation means a law-level frame or one of the six stage roles. There is no
hidden seventh stage. All converted family laws emit exactly six sections.

## Important Rails

Use these as clean-room numeric rails, not as copied preset data:

- mouth rail: `780-790 Hz`
- low/low-mid anchors: `190-340 Hz`, `450-640 Hz`
- tear rails: `3790 Hz`, `4130 Hz`, `4440 Hz`
- air/cut rails: `8250 Hz`, `8875 Hz`, `9650 Hz`, `16500 Hz`, `17950 Hz`
- vocal bands:
  - F1/low-mid: `423-960 Hz`
  - F2/mouth: `1245-2275 Hz`
  - F3/bite: `2847-4887 Hz`
  - air: `8157-9322 Hz`

## Move Families

The full vocabulary study found:

- `high bank collapse`: 25 skins
- `remote-cut violence`: 13 skins
- `talking vowel glide`: 7 skins
- `shelf/cliff frame`: 3 skins
- `comb/phaser field`: 2 skins

These are the next Law Author behaviors to expose as family choices.

### High Bank Collapse

Upper rows collapse down into mouth/bite while high zeros cut the top. This is
the highest leverage family. It should not be implemented as "open the high
band upward."

### Remote-Cut Violence

Zero movement is the star. Let cuts move separately from peaks by multiple
octaves. This is the main missing richness knob in polite laws.

### Talking Vowel Glide

Morph slides formant frequencies. Secondary/Q locks those frequencies and
cranks radii toward `0.9999`.

### Shelf/Cliff Frame

Make a broad keep/kill frame first, then hang character rows inside it. Template
study found no exact packed-row reuse, but many response-shape neighbors.

### Comb/Phaser Field

Rows can be a field of cuts, not only a stack of peaks. The plot should show
staged canyons and a coherent center.

## Verification Commands

Convert aggregate reports to laws:

```powershell
python tools/convert_family_reports_to_laws.py
```

Compile one family law:

```powershell
python tools/law_author.py --preset family_vocal_formant --out dev/tmp/law_author/families/family_vocal_formant --grid 17
```

Compile all family laws:

```powershell
$laws = @(
  'family_bandpass_swept_eq',
  'family_morph_special',
  'family_phaser_comb',
  'family_slope_ladder',
  'family_vocal_formant'
)
foreach ($law in $laws) {
  python tools/law_author.py --preset $law --out "dev/tmp/law_author/families/$law" --grid 17
}
```

## Next Build

The next high-leverage build is not another report. It is a stronger Law Author
plot/audit surface:

- show pole tracks and zero tracks across corners;
- show max-radius grid;
- show center response and center sag;
- report remote-zero fraction and zero-motion disagreement;
- show all four corner stage tables, not only `M0_S0`.
