# DATASETS — the grounded ground truth (read this before authoring)

**The rule:** every pole, zero, and frequency in a body is *looked up here*, never
invented. Author by transporting and combining these grounded values — not by
optimizing coefficients in free space. This file is the spine; the files it points
to are the truth. If a value isn't sourced below or in a file's own header, it is
not allowed in a shipped body.

## 1. Measured / physical tables — `tables/`
The data the math reads. Each file carries its own provenance; treat that as
authoritative over this summary.

| File | Domain | Grounding |
|------|--------|-----------|
| `vowel_formants.json` | vowels | F1–F3 + bandwidths (Peterson & Barney) |
| `klatt_1980_formants.json`, `klatt_1980_bandwidths.json` | vowels | Klatt 1980 calibration set |
| `tube_resonances.json` | tubes / pipes | harmonic partials, `f_n = n·c/2L` |
| `metallic_modes.json` | struck metal | inharmonic modal ratios (Rossing / Fletcher) |
| `family_intents.json` | cavity / cut / comb / vocal | home→away intent targets |
| `q_radius_table.json` | Secondary / Q | q-index → pole radius (measured corpus) |
| `morph_designer_type_primitives.json` | section types | E-mu type system (Ghidra RE) |
| `p2k_vocal_law.json` | vocal grammar | clean-room vocal bounds |
| `exact_skeletons.json` | filter-family morphs | exact corner projections (`scipy`) |
| `physical_models.py` | generators | Helmholtz / Euler-Bernoulli / Chladni formulas |

## 2. Decoded reference behavior — `docs/study/`
The empirical manifold authoring must stay on (aggregate behavior only — **never**
copied bytes, names, or coefficients):
- `P2K_atlas.{md,json}` — 50 presets × 4 corners × 6 stages, decoded as
  `pole_hz/r, zero_hz/r, gain`. The per-family pole/zero **pattern** reference.
- `P2K_FAMILY_REVERSE_ENGINEERING.md` — the five families and their morph / Q
  motion targets.
- `frequency_rails.csv`, `row_motion_vocab.json` — shared rails + motion vocabulary.

## 3. The one true engine — `trench-core/`
All packed math lives here: the minifloat codec, morph/Q interpolation, the
**series** cascade `H(z) = ∏ Hₖ(z)`, AGC, QSound, FFI. `pyruntime/` is
parity-guarded Python glue over it (`ffi_parity.py` proves byte-exactness). Never
add a second packer, interpolator, or engine copy.

## 4. The invariants — `AGENTS.md`, `CLARITY.md`
What a body is (4 corners × 6 ordered sections × 5 packed words), the runtime law
(section index is the morph pairing — do not scramble it), and the proven
dead-ends (firmware-integer path, generic `pressurize`, parallel/“survival”
makeup) that must not be revisited without new evidence.

## Do NOT ship or copy
`ref/presets/*.bin`, `ref/p2k_variants/**`, `*.body240`, heritage `*.xml`.
Reference teaches behavior only.
