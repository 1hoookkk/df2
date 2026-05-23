# TRENCH Corner Inventory — May 23 2026

## Summary by source

| Source | Files | Format | Sample rate | Notes |
|---|---|---|---|---|
| St. Olaf NMR-Talk | 5 | .wav | 8278 Hz | Cyclohexane, dichloromethane, cyclohexane+DCM mix, ethyl acetate, inositol. 4 s each. Mathematically pure FIDs — 1 to 3 decaying sines. |
| U Iowa plasma wave / space-audio.org | 12 mp3 + 3 wav | .mp3 / .wav | 25600–27440 Hz wav | Whistlers, chorus, AKR, bow shock, ion acoustic from Earth/Jupiter/Cluster |
| KB6 Syntiac hardware dumps | 5 bundles (129 wavs) | .wav | varies | EMU Proteus1/3/SP-12, Ensoniq Mirage, Yamaha RX-11 — raw converter+filter signatures |
| Stanford SoSH SOHO | 2 | .wav | 12000 Hz | 3-mode helioseismology + n1721 HMI mode |
| Vocal formant corner table | 1 CSV | data | n/a | 73 phoneme entries with F1/F2/F3/F4 + source |
| TRENCH 4-corner body candidates | 1 CSV | data | n/a | 14 morph paths pre-mapped to TL/TR/BL/BR |

## Skipped (and why)

- **HMDB / musicNMR (R)**: Would require installing R + the package locally and pulling raw FID `.txt` from each HMDB metabolite page one at a time. Better as an overnight automation pass — flag it for the sift loop if you want machine-generated additions to the NMR set.
- **Mnova GUI extraction**: Headless GUI app, 45-day trial. Not scriptable.
- **Xeno-Canto / BioAcoustica bird+cicada**: API works but quality-A filtering needs per-record inspection. Listed in `xeno/SOURCES.txt` for manual selection.
- **McGreevy natural radio compendium**: Total bundle is multi-GB on archive.org. Listed in `mcgreevy/SOURCES.txt` — pull only the tracks you've ear-checked against the spectrogram constraint.
- **LIGO violin modes**: GravitySpy archive needs a Zooniverse account and per-event review. Listed in `mcgreevy/SOURCES.txt`.

## Vocal formants — what's in the table

Each row gives one phoneme/voice combination as a corner pair. The "two corners, low and high" you described maps directly to F1 (low) and F2 (high). F3/F4 included where they carry character (rhotic /er/ where F3 drops to merge with F2; nasals where the antiformant sits between F2 and F3; the singer's formant cluster around 2.8–3.2 kHz).

Coverage:
- Peterson & Barney 1952: 10 General American vowels × male/female/child = 20 male+female rows
- Hillenbrand 1995: schwa, diphthongs (start/end), close-mid /o/
- Glides, laterals (clear vs dark L), nasals (m/n/ng)
- Fricatives (f/s/sh/th/h) — F1≈0 because there's no voicing pole; F2 is the noise peak
- Cross-linguistic: Australian English (Cox 2014), RP British (Wells 1962), French rounded fronts and nasals (Calliope 1989), German long rounded (IPDS Kiel), Japanese unrounded /M/ and devoiced /i/ (Vance 2008), Mandarin tones (Lee 1999), Korean /M/ (Yang 1996), Arabic pharyngealised /aS/ (Watson 2002), Hindi retroflex (Ladefoged 2003), Xhosa click (Traill 1985), Hebrew pharyngeal (Laufer 1988)
- Voice-quality endpoints: tenor singer's formant + soprano high-C F1 tuning (Sundberg 1987), metal growl + scream (Edge 2014), infant cry (Wermke 2002), elderly male (Linville 2001), whisper, yawn, gag

## Drop-in 4-corner body candidates

`formants/trench_4corner_body_candidates.csv` — 14 morph paths pre-laid as `[TL, TR, BL, BR] × [F1, F2]`. The canonical first row is the **Small Talk Ah-Ee** path (male ah → male ee top row, female ah → female ee bottom row). Other rows are unused territory:
- `yawn_to_shriek` — pharyngeal open to infant cry; would extend Small Talk's "Yawn → Shriek" station map.
- `fry_to_singers_formant` — Speaker Knockerz chest territory mating with operatic upper-formant cluster. New body candidate.
- `fricative_TH_to_S` — Aluminum Siding pure-noise corner. F1 anchored at near-zero, only F2 traverses.
- `infant_cry_to_elderly` — full lifespan arc. Diagonal corners on a single body.

## Files

```
nmr/                                  5 FIDs, 8278 Hz
plasma/                               12 plasma-wave mp3 + 3 plasma-wave wav
kb6/                                  5 hardware bundles
kb6/extracted/EMU_Proteus1/           17 wavs
kb6/extracted/EMU_Proteus3/           22 wavs
kb6/extracted/EMU_SP-12/              32 wavs
kb6/extracted/Ensoniq_Mirage/         31 wavs
kb6/extracted/Yamaha_RX-11/           27 wavs
soho/3modes.wav                       3 low-degree modes
soho/hmi.n1721.wav                    Single HMI mode, 8min
formants/vocal_formant_corners.csv    73 rows, 7 source families
formants/trench_4corner_body_candidates.csv  14 candidate body paths
```
