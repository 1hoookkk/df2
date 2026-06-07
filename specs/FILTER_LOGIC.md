# Filter Logic

Clean-room DSP ground truth for DF2/P2K authoring. This file describes structure
and aggregate behavior only. It must not be used to copy vendor bytes,
coefficient tables, exact endpoint tables, or product-facing preset names.

## Authority Boundary

OBSERVED: A P2K body is a packed runtime object:

```text
240 bytes = 4 corners x 6 sections x 5 packed u16 words x 2 bytes
```

OBSERVED: Corner order is:

```text
M0_Q0, M100_Q0, M0_Q100, M100_Q100
```

OBSERVED: The shipped runtime path is:

```text
body240
  -> PackedCorners
  -> packed-u16 Morph/Q interpolation
  -> minifloat decode
  -> kernel c0..c4
  -> direct biquad b0,b1,b2,a1,a2
  -> six-section cascade
  -> post-cascade AGC/output path
```

OBSERVED: Runtime interpolation is Morph-first packed-domain bilinear
interpolation in u16 space, then minifloat decode. It is not coefficient-space
float interpolation.

OBSERVED: The direct biquad form is:

```text
H(z) = (b0 + b1 z^-1 + b2 z^-2) / (1 + a1 z^-1 + a2 z^-2)

b0 = c4
b1 = (c0 - 2) * c4
b2 = (1 - c1) * c4
a1 = c2 - 2
a2 = 1 - c3
```

OBSERVED: Denominator roots are poles. Numerator roots are zeros.

OBSERVED: The runtime AGC is post-cascade behavior. It is not the body grammar
and does not create the pole/zero response shape.

INFERRED: The original P2K authoring process was likely table/grid assisted
with manual tuning on important families. This is an inference from repeated
rails, radius behavior, and row/corner motion patterns. It is not proof of the
original tool UI or author workflow.

## What P2K Presets Share

OBSERVED from the full P2K vocabulary study:

- Scope: 50 skins, 200 variant bodies.
- Every body is the same packed shape: 4 corners, 6 sections, 5 packed words per
  section.
- Every active section has numerator and denominator behavior. Pole-only
  authoring is incomplete.
- Section index is a correspondence slot across corners, not a fixed frequency
  rank.
- Poles and zeros often move by different amounts. Zero motion is first-class.
- Push/Q is not just "Morph 2". It often shifts, tightens, or moves cuts.
- The four variants of a P2K family are mostly pitch transpositions of the same
  grammar, not four unrelated designs.

OBSERVED aggregate move families across 50 skins:

| Move Family | Count | Share |
| --- | ---: | ---: |
| high bank collapse | 25 | 50% |
| remote-cut violence | 13 | 26% |
| talking vowel glide | 7 | 14% |
| shelf/cliff frame | 3 | 6% |
| comb/phaser field | 2 | 4% |

OBSERVED construction-read counts:

| Construction Read | Count | Share |
| --- | ---: | ---: |
| likely table assisted | 29 | 58% |
| clearly table/grid driven | 19 | 38% |
| impossible to tell | 2 | 4% |

INFERRED: The shared P2K fundamental is not a single universal zero table or a
single fixed formant model. The shared fundamental is a compact pole/zero
program:

```text
section[i] = pole target + zero target + pole radius + zero radius + section gain
surface    = 4 registered corners x 6 indexed sections
behavior   = packed-domain interpolation + cascade + post-cascade dynamics
```

## Section Logic

OBSERVED: The six sections are indexed correspondence rows. Row `i` at M0_Q0
interpolates with row `i` at M100_Q0, M0_Q100, and M100_Q100.

OBSERVED: Section number is not a universal spectral role. Full-study stage
ordering showed:

| Stage Order Type | Share of 200 variants |
| --- | ---: |
| strict low to high | 29.5% |
| mostly ascending | 11.5% |
| strict high to low | 5.0% |
| scrambled or clustered | 54.0% |

DO NOT: assume S1 is the fundamental.

DO NOT: sort sections by frequency before packing. Sorting breaks corner
correspondence.

DO: preserve the section identity across all four corners, even when audible
frequency order crosses.

## Zero Logic

OBSERVED: Zeros are mandatory in the P2K grammar.

OBSERVED: Endpoint zeros fall into at least two useful structural classes:

- Local zero: near the pole; creates a local peak/canyon relationship.
- Remote zero: far from the pole; creates broad tilt, kill bands, air cuts, or
  counter-motion.

OBSERVED from the full P2K row-role counts:

| Row Role | Count | Share |
| --- | ---: | ---: |
| remote cut | 463 | 38.6% |
| air kill | 176 | 14.7% |
| air cap | 144 | 12.0% |
| bite | 129 | 10.8% |
| mouth | 114 | 9.5% |
| blade | 47 | 3.9% |
| color row | 29 | 2.4% |
| frame | 28 | 2.3% |
| shelf | 25 | 2.1% |
| cliff | 17 | 1.4% |
| broad frame | 16 | 1.3% |
| low anchor | 12 | 1.0% |

INFERRED: The "missing layer" for clean-room authoring is explicit zero
topology. Poles alone produce resonant peaks. Zeros produce the visible notches,
shelves, cliffs, and phaser/flanger cuts.

DO NOT: author pole mountains without paired zero targets.

DO NOT: glue every zero to its pole. P2K often separates pole and zero motion.

DO: represent every section as pole + zero + radii + gain.

## Motion Logic

OBSERVED motion-tag counts across the full P2K study:

| Motion Behavior | Count | Share |
| --- | ---: | ---: |
| push shift | 799 | 23.3% |
| push cut walks away | 665 | 19.4% |
| big sweep | 489 | 14.2% |
| push tightens | 358 | 10.4% |
| high cut falls | 293 | 8.5% |
| crossing | 235 | 6.8% |
| cut walks away | 210 | 6.1% |
| small sweep | 183 | 5.3% |
| high bank falls | 146 | 4.2% |
| low keep | 58 | 1.7% |

INFERRED: A good clean-room recipe needs separate motion rules for:

- pole frequency;
- zero frequency;
- pole radius;
- zero radius;
- section gain.

DO NOT: treat Morph as "move every section together."

DO NOT: treat Q/Push as only pole radius.

DO: test corners, center, edges, and diagonals. Several P2K skins are defined by
their middle behavior, not only by endpoints.

## Shared Frequency Rails

OBSERVED: The full P2K set contains repeated frequency rails. These are
aggregate study evidence, not values to paste into a product preset.

Common aggregate rails include:

| Kind | Band | Approx Rail | Endpoint Hits | Skin Count |
| --- | --- | ---: | ---: | ---: |
| pole | sub | near-DC | 330 | 17 |
| zero | sub | near-DC | 325 | 17 |
| pole | mouth | around 780 Hz | 179 | 31 |
| zero | mouth | around 780 Hz | 175 | 31 |
| zero | mouth | around 785 Hz | 133 | 30 |
| pole | mouth | around 785 Hz | 129 | 27 |
| zero | upper/air | high fixed rails | repeated | many |

INFERRED: P2K shares calibration rails and repeated construction habits. It does
not support a "pure by-ear only" claim, and it does not support a single copied
textbook table claim.

DO NOT: copy these rails as a body.

DO: use the rail evidence to define broad authoring categories: sub, low, mouth,
bite, upper, air.

## Stability Logic

OBSERVED: The full study found 17 of 50 skins with unstable packed-grid points
under the audit criteria.

INFERRED: P2K behavior includes edge/damage states. "Always stable everywhere"
is not the historical behavior.

DO NOT: use instability as proof that a reference is invalid.

DO NOT: ship unstable generated bodies without an explicit design decision and
runtime guard.

DO: report max pole radius, unstable mask, nonfinite mask, and grid location for
every authored body.

## Manual And Tutorial Evidence

OBSERVED: `emu-mophatt-manual.pdf` supports the high-level Z-plane model:

- filters are described as complex frames interpolated by Morph;
- Morph changes many filter parameters at once;
- the product exposes 50 ROM filter types;
- filter "order" is exposed as 2 to 12 order, which maps naturally to cascaded
  second-order sections;
- the manual explicitly groups the vocabulary into low-pass, high-pass,
  band-pass, swept EQ, phaser, flanger, vocal/formant, and modelled synth-filter
  categories;
- the manual states that Frequency and Q control different elements depending
  on filter type.

OBSERVED: the Mo'Phatt manual's descriptions agree with the aggregate P2K
study: Q/Push is not one universal parameter. It can add peaks, move apparent
cavity size, tune a ring, or shift poles depending on filter type.

OBSERVED: `EMU Dillusion_PeakShelfMorph_Tutorial_WEB.pdf` is useful operator
evidence for Peak/Shelf Morph. It describes a two-frame morph where the shelf
parameter blends low-pass, mid-shelf, and high-pass behavior; Frequency changes
meaning depending on the shelf setting; resonance/Q makes the sweep more
aggressive.

INFERRED: these documents support the clean-room authoring model of
`filter type = topology + control mapping`, not a single shared frequency
formula.

DO NOT: treat either PDF as coefficient evidence.

DO NOT: copy tutorial example settings into shipped bodies.

## Clean-Room Implementation Rules

Use this structure for Forge/manual authoring:

```json
{
  "sections": [
    {
      "id": 0,
      "role": "study label only",
      "pole": { "hz_rule": "...", "radius_rule": "..." },
      "zero": { "hz_rule": "...", "radius_rule": "..." },
      "gain": { "rule": "..." },
      "motion": {
        "morph": "...",
        "q": "..."
      }
    }
  ],
  "corners": ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"],
  "verification": ["packed_runtime_probe", "morph_q_grid", "section_roots"]
}
```

Rules:

1. Author all four corners jointly.
2. Keep section identity fixed across corners.
3. Give every active section both poles and zeros.
4. Let pole and zero motion differ when needed.
5. Use gain as a bounded local budget, not as a hidden rescue for broken shapes.
6. Verify through `.body240` and `trench_core.dll`, not through a Python-only
   surrogate.
7. Plot cascade and individual sections. A body is not understood until both are
   visible.

## What Not To Do

- Do not copy P2K bytes, packed words, coefficients, endpoint tables, or product
  preset names into new shipped material.
- Do not call any generated body "P2K" unless it is a study reference.
- Do not use X3/P2K screenshots as exact target curves.
- Do not infer musical intent from magnitude-only curve matching.
- Do not assume a universal zero table.
- Do not assume stage number equals frequency order.
- Do not assume the fundamental lives in S1.
- Do not make AGC the filter grammar.
- Do not hide zero placement behind vague labels.
- Do not promote recipes that rely on silent radius clamping.
- Do not judge endpoints only; inspect the packed interpolation surface.

## Evidence Files

- `ref/presets/README.md`: packed P2K `.bin` source and byte-layout boundary.
- `pyruntime/packed_interp.py`: packed minifloat decode/interpolation reference.
- `pyruntime/trench_ffi.py`: shipped runtime FFI probe path.
- `trench-core/src/minifloat.rs`: runtime kernel and biquad conversion.
- `trench-core/src/ffi.rs`: packed interpolate/probe FFI.
- `dev/tmp/p2k_full_vocabulary/report.md`: full 50-skin/200-body aggregate
  study.
- `dev/tmp/p2k_full_vocabulary/row_motion_vocab.json`: machine-readable
  aggregate counts.
- `dev/tmp/notebooklm_hz_pack/01_stage_logic.md`: stage ordering and zero
  logic.
- `dev/tmp/notebooklm_hz_pack/06_corner_and_stage_patterns.md`: stage/corner
  rail patterns.
- `C:/Users/hooki/Downloads/emu-mophatt-manual.pdf`: official vocabulary and
  parameter-semantics evidence.
- `C:/Users/hooki/Downloads/EMU Dillusion_PeakShelfMorph_Tutorial_WEB.pdf`:
  community/operator evidence for Peak/Shelf Morph behavior.
