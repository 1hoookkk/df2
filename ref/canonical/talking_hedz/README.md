# Talking Hedz Canonical Capture Slot

This directory is the first real E-mu null-test target for df2.

Required capture:

- Dry input: `ref/inputs/bypassed-pinknoise.wav`
- E-mu filter: Talking Hedz
- Capture clock: 39062.5 Hz
- Positions: the `positions` array in `MANIFEST.json`
- Wet files: place E-mu renders under `wet/` using the manifest filenames

Render the df2 candidate side with:

```powershell
cargo run -p trench-core --example render_talking_hedz -- ref/canonical/talking_hedz/df2_candidate
```

Then run the first real null gate with:

```powershell
cargo test -p trench-core --test talking_hedz_first_null -- --ignored --nocapture
```

The old `C:\Users\hooki\trenchwork_clean\ref\_BROKEN_CE_CAPTURE_QUARANTINE`
Hedz WAVs are not acceptable references; their own README says the capture
missed a stage, stored transformed values, and had radius drift.
