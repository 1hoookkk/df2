# TRENCH — Data Sources

The material the compiler draws on. Every preset is a `geometry.json` recipe (pole/zero
per stage per corner) packed by **THE compiler** — `python -m tools.filter_cli pack`
(`target/release/body-from-geometry.exe`, grid-certified). These sources supply the
*voice* that fills a frame, plus the study evidence behind the *frames* themselves.

A machine-readable index of the same material lives in `catalogue.json`.

---

## Voice — formants & vowels
Formant frequencies drive the voice stages (the mid resonances).

| source | citation | path |
|---|---|---|
| Klatt formants | Dennis H. Klatt, "Software for a cascade/parallel formant synthesizer," *JASA* 67(3):971–995, 1980 (F4/F5 held at 3300 Hz) | `filters/tables/klatt_1980_formants.json` |
| Mullen formants | Mullen 2006 (per-vowel F4), cross-checked vs Klatt | (same file) |
| Peterson–Barney vowels | Peterson & Barney 1952 vowel formants | `filters/tables/vowel_formants.json` |
| DVTD vocal-tract data | Dynamic Vocal Tract Database (per-subject vowel rails) | `../trench-filters/data/vocal/dvtd/` (+ `dvtd_supplemental_code/README.md`) |

## Voice — physical-model tables (inharmonic)
Modal frequency ratios; multiply by a chosen fundamental to place the poles.

| source | citation | path |
|---|---|---|
| Membrane (drumhead) modes | Bessel-function circular-membrane theory; Rossing & Fletcher, *The Physics of Musical Instruments* | `filters/tables/membrane_modes.json` |
| Metallic / struck-metal modes | Euler–Bernoulli beams, Chladni plate modes, tuned-bell minor-third partials; Rossing & Fletcher | `filters/tables/metallic_modes.json` |
| Aeroacoustic / phononic / circuit | physics-simulation response data | `../trench-filters/data/{aeroacoustic,phononic,circuit,modal,simulators}/` |

## Voice — HRTF / measured spatial responses
| source | citation | path |
|---|---|---|
| SONICOM HRTF | SONICOM 2022 HRTF dataset (KEMAR + subjects P0001…) | `../trench-filters/data/hrtf/` (`_metadata/sonicom_2022_*`) |
| SADIE II | SADIE II V2-1 HRTF dataset | `../trench-filters/data/hrtf/sadie_ii/` |
| Oldenburg MMHR | Oldenburg multi-mic HRIR | `../trench-filters/data/hrtf/oldenburg_mmhr/` |
| Aalto | Aalto laser-spark HRIR | `../trench-filters/data/hrtf/aalto_laser_spark/` |

## Voice — sound-source library (raw audio → transfer functions)
~14,300 wavs for ingest via `tools/tf_ingest.py`. Root: `wav-source-library/`.
Categories: `robot_echolocation, industrial_machines, space_plasma, ice_ocean,
seismic_planetary, bat_echolocation, pulsars, clean_instruments,
orchestral_philharmonia, cc0_foley, measurement_quartet` (+ `audition_stems`,
`00_DROP_NEW_WAVS_HERE`).

---

## Frames — X3 study evidence (READ-ONLY, clean-room)
The frames and the fundamental "block" vocabulary are *read* from decompiled/ROM
reference. **Study evidence only — no protected bytes, names, coefficient rows, or
endpoint curves are copied into shipped work** (clean-room rule).

| source | what it is | path |
|---|---|---|
| X3 fixed-class fundamentals | the 17 blocks (LP/HP/BP/EQ/PHA/FLG/VOW), minifloat-packed runtime blocks | `../df2/ref/x3_menu/runtime_blocks/*_48000.raw` |
| P2K ROM presets | real ROM-decoded iconic presets (Talking Hedz, etc.) | `../df2/bodies/rom/P2k_*.json` and `../surface-forge/out/foundry/ROM_GOLD/` |
| Morph Designer oracle | Ghidra extraction of the compiler + minifloat decode (`FUN_1802c3600`) | `../df2/ref/ghidra_extracts/morphdesigner_types.md` |
| RE codex | reverse-engineering notes (context, not a decode oracle) | `../df2/ref/codex/trench_re_codex.md` |

Codec: X3 runtime blocks and `.body240` files are **minifloat-packed u16**, decoded by
`pyruntime/packed_interp.py` (the only correct decoder).

---

## Recipes & compiler
| item | path |
|---|---|
| THE compiler (recipe → body, grid-certified) | `tools/filter_cli.py` → `target/release/body-from-geometry.exe` |
| Family / section laws | `../df2/recipes/laws/*.json` |
| Recipe index | `recipe-index/recipe_index_v1.json` |
| Harvested preset library (143 compiler-verified recipes) | `C:\Users\hooki\preset_library\` (`presets_index.csv`) |

## Reference laws (measured this session)
- Body container: 4 corners × 6 stages × 5 u16 words = 240 bytes (biquad budget = 6).
- Stage 5 is a unit-circle notch in every ROM frame (mandatory).
- Unused stage slots take the sentinel `[0xdfff,0xffff,0xdfff,0xffff,0xe000]` (phantom passthrough).
