# TRENCH WAV source library

This folder is a dry-source audition library. Audio is grouped by physical
source rather than by intended preset or effect.

- `00_DROP_NEW_WAVS_HERE`: unsorted local additions.
- `01_robot_echolocation`: BatVision candidates (queued; dataset archives are large).
- `02_industrial_machines`: MIMII candidates (queued; verified archive is 1.08 GB).
- `03_space_plasma`: University of Iowa plasma-wave sonifications.
- `04_ice_ocean`: NOAA PMEL hydrophone and iceberg recordings.
- `05_seismic_planetary`: NASA Mars microphone and seismometer recordings.
- `06_bat_echolocation`: raw bat-call candidates (queued).
- `07_pulsars`: Jodrell Bank radio-pulsar sonifications.
- `08_clean_instruments`: University of Iowa anechoic/clean instrument notes.
- `09_orchestral_philharmonia`: selected Philharmonia instruments and percussion.
- `10_cc0_foley`: per-file CC0 Freesound candidates (queued).
- `_acquisition_queue`: verified sources that were not bulk-downloaded.

`SOURCE_LEDGER.csv` is authoritative for origin, conversion, technical format,
SHA-256, usage notes, and credit. Rebuild it after adding WAVs with:

```powershell
powershell -ExecutionPolicy Bypass -File .\refresh_source_ledger.ps1
```

No file has been loudness-normalized, peak-normalized, filtered, trimmed, or
otherwise audition-processed. AIFF and MP3 sources were decoded to PCM WAV only;
the ledger declares those conversions. Treat sampled/sonified scientific data
as evidence-derived audio, not literal airborne sound in its original setting.

