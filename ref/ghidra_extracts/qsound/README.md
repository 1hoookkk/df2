# QSound source set

This directory is reference-only measurement material. Nothing here ships in
the df2 binary or in cartridges.

## Carried source set

`qcreator_1998_source_set/` was copied from:

`C:\Users\hooki\trench_re_vault\analysis\qsound_lab\qcreator_extracted_auto`

Contents:

- `Qcreator.exe`
- `QMixer.dll`
- `QCREATOR.HLP`
- `qcreator.cnt`
- `Readme.txt`
- `_LICENSE.TXT`
- `extract_manifest.json`
- `Demos/Demo1.wav`
- `Demos/Demo2.wav`
- `Demos/Demo Readme.doc`
- `sndfiles/Syscheck.wav`
- `sndfiles/Test123.wav`

## Status

This is QSound source material, not a clean E-mu hardware or Emulator capture.
It can support reverse-engineering of the QSound graph and table/law
extraction, but it does not by itself prove the current
`qsound_spatial.rs` TODO constants:

- `ITD_SAMPLES_PER_LAW_UNIT`
- `LOW_SHELF_CORNER_HZ`
- `HIGH_SHELF_CORNER_HZ`

Those constants remain engineering defaults until table extraction or a clean
matched capture locks them.

## Required proof before runtime constants change

- ITD law coefficients and unit scalar.
- ILD law coefficients.
- Left/right low/mid/high band-law coefficient tables.
- Shelf corner frequencies.
- Matched dry/wet capture or extracted output target sufficient for a
  `tools/null_test.py` run across the +/-60 degree azimuth sweep.

Pass threshold: <= -60 dB null depth. <= -90 dB is bit-accurate.
