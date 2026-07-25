# Interesting preset recuts — 2026-07-13

This is an isolated audition pack for the latest VOWL/sweep/tear recuts. Original source bodies remain in place and were not overwritten, moved, or normalized.

## What changed

The old VOWL chord was nearly flat because each stage's pole and zero centers were co-located, with only a small radius separation. The two VOWL recuts keep six lane identities but author independent zero centers in the valleys between formants. The sweep recut begins with sparse moving mechanical centers and resolves into authored vowel centers. The tear recut begins with crossed tear/notch centers and resolves into upper metallic/glass centers.

These are explicit designs, not a fitter. Each body has six stages in each of four independently authored corners: M0_Q0, M100_Q0, M0_Q100, M100_Q100. Q100 is not derived.

## Candidates

- `VOWL_CHORD_2actor_recut` — `d9b10e01a48389d7b597c7ab3a191882d88fb94cc8bda0e791e68a566228e67d` — Two vocal actors with independent inter-formant valleys; a vowel chord instead of six near-cancelled resonators.
  body: `C:\Users\hooki\df2\dev\tmp\interesting_presets_2026-07-13\candidates\vowl_chord_2actor_recut.body240`
  design/provenance sidecar: `C:\Users\hooki\df2\dev\tmp\interesting_presets_2026-07-13\candidates\vowl_chord_2actor_recut.design.json`
  observed reference only: `C:\Users\hooki\df2\bodies\proofs\VOWL_CHORD_2actor.body240` — `cedd05b7be1f2440fd15244cb2c935d0bf014f1d24eb07c0c4a1e7901868cdba`
- `VOWL_CHORD_2actor_duet_recut` — `43e948c66d2e05cadf125f42d3ca079c04925ddbe64dc0aab46468c36944063b` — A more unstable-feeling duet: crossed mouths plus an upper glass zero that makes the last actor tear into air.
  body: `C:\Users\hooki\df2\dev\tmp\interesting_presets_2026-07-13\candidates\vowl_chord_2actor_duet_recut.body240`
  design/provenance sidecar: `C:\Users\hooki\df2\dev\tmp\interesting_presets_2026-07-13\candidates\vowl_chord_2actor_duet_recut.design.json`
  observed reference only: `C:\Users\hooki\df2\bodies\proofs\VOWL_CHORD_2actor_duet.body240` — `655ec8c2c701b6d80d06cc222a9c09aa4abba12c31bc42f2c6d37601aeaf28f7`
- `SWEEP_TO_VOWEL` — `8ba6541c7a80b2b9e9b77316c5aa851a6989965382d89449ddac3e264679d268` — A sparse mechanical sweep at Morph 0 that resolves into a voiced multi-formant mouth at Morph 100.
  body: `C:\Users\hooki\df2\dev\tmp\interesting_presets_2026-07-13\candidates\sweep_to_vowel.body240`
  design/provenance sidecar: `C:\Users\hooki\df2\dev\tmp\interesting_presets_2026-07-13\candidates\sweep_to_vowel.design.json`
  observed reference only: `C:\Users\hooki\df2\juce-shell\assets\bodies\sweep.body240` — `c2bf61d6e1981afd103ae5a35ab6157d6ba30ac3bf562880de8c593d02afa569`
- `TEAR_TO_GLASS` — `1126dc1ddbeb2b576dc638de8f79879a7f6d97c0fbd5d12897633c23775770bc` — A crossed 808-like tear at Morph 0 that opens into metallic glass and high-air shards at Morph 100.
  body: `C:\Users\hooki\df2\dev\tmp\interesting_presets_2026-07-13\candidates\tear_to_glass.body240`
  design/provenance sidecar: `C:\Users\hooki\df2\dev\tmp\interesting_presets_2026-07-13\candidates\tear_to_glass.design.json`
  observed reference only: `C:\Users\hooki\df2\juce-shell\assets\bodies\ship_808_tear.body240` — `44feb36b7c138086c77dd83f858957f601c94e4d1af81cd4bb596935377f27f0`

## Runtime and sampled certification

Backend: `pyruntime.trench_ffi -> shipped trench_core packed_probe and FilterEngine FFI`
Runtime library: `C:\Users\hooki\df2\target\release\trench_core.dll`
Plots and probe data come from `pyruntime.trench_ffi.packed_probe` rows returned by the shipped `trench_core` decoder. Audio comes from the shipped FilterEngine FFI; there is no silent fallback renderer.
Probe grid: `17x17` (289 points per candidate). This is sampled certification, not continuum proof.

| Candidate | unstable rows | nonfinite rows | maximum pole radius | observed pole movement Hz | observed zero movement Hz |
|---|---:|---:|---:|---:|---:|
| `VOWL_CHORD_2actor_recut` | 0 | 0 | 0.977998944 | 609.638 | 790.084 |
| `VOWL_CHORD_2actor_duet_recut` | 0 | 0 | 0.979000862 | 1806.433 | 8240.252 |
| `SWEEP_TO_VOWEL` | 0 | 0 | 0.977998944 | 1636.486 | 5080.140 |
| `TEAR_TO_GLASS` | 0 | 0 | 0.983999029 | 2255.841 | 6884.944 |

The four authored corner reports and observed Q0→Q100 pole/zero center movements are in `manifest.json` under each candidate. No Q values were derived, repaired, normalized, reordered, or rejected because of an old derived-Q rule.

## Audio

Native engine sample rate: `44100 Hz`.
Every candidate has seven files in `wav_raw/` and matching files in `wav_listen/`: frozen snapshots, Morph sweeps at Q0/Q50/Q100, and Q sweeps at Morph 0/50/100. The source set is deterministic pink noise, saw, and 808/short drum. An approved real material loop was not found; status is `UNKNOWN` and it was omitted.

`wav_raw/` is faithful engine output at unity I/O. It is not clipped, normalized, or replaced. `wav_listen/` applies one clearly documented scalar per candidate uniformly to all seven files for easy comparison; the scalar and raw peak are in `manifest.json`.

## Proof artifacts

- `plots/<name>_runtime.png`: four runtime corner curves, Morph sweeps, Q sweeps, six-lane pole/zero schematic, and secondary stability/nonfinite map on shared axes.
- `plots/contact_sheet.png` and `plots/comparison_sheet.png`: identical runtime-derived dB scale (`-100…60 dB`).
- `proof/*.roundtrip.body240` and `proof/*.roundtrip.cart.json`: packedWords/body-cart parity checks through `tools/author_body.py`; each raw roundtrip is byte-identical to the generated body.
- `candidate_table.csv`: short listening table. The decision field is blank for you to mark `KEEP` or `KILL`; this pack contains no keep/kill verdict.

## Exact commands

```powershell
Set-Location -LiteralPath 'C:\Users\hooki\df2'
python 'C:\Users\hooki\df2\dev\tmp\interesting_presets_2026-07-13\build_interesting_presets.py'
```

Runtime authority: `trench_core` only. Source provenance for these new authored geometries is `UNKNOWN` beyond the explicit design records in their sidecars. P2K material was not copied or used in this pack.

No plugin UI, workstation UI, runtime math, source-area body, or candidate byte outside this isolated output folder was modified.
