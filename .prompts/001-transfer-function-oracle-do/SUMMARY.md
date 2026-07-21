# 001 — Transfer-Function Oracle (system-ID / body-authoring pipeline)

**Result:** A clean-room-capable transfer-function system-ID pipeline is built and runs
end-to-end on a synthetic hidden-body oracle (`prepare→synth→estimate→fit→verify→bundle`),
recovering held-out interior Morph×Q behaviour through the packed runtime ~27 dB RMS better
than the neutral baseline (candidate 9.9 dB mag-RMS vs baseline 37.5 dB, held-out ≈ train)
and passing every hard gate — exact 240 bytes, load/save identity, body/cart parity, and a
dense 33×33 certification with **0 unstable / 0 nonfinite** rows — with the whole thing
riding only on `trench-core`'s owned packed math (no second kernel).

## What it is
- `trench-core/src/bin/tf_oracle.rs` — the pipeline. Subcommands `prepare | synth | estimate | fit | verify | bundle | run`.
- Excitation: repeated Schroeder-phase multisine (flat on-bin, low crest, periodic → exact
  rectangular-window Welch). Estimator: `H = Sxy/Sxx` + coherence + confidence mask; bulk
  transport delay from the loopback fixture (group delay stays in H). Capture: 32-bit float
  WAV, absolute amplitude, no normalization.
- Fitter: variables = 4 corners × 6 stages × `[zero_p, zero_q, pole_p, pole_q, scale]` (monic
  pairs → classified `RootPair` → owned `stage_law::words_from_geometry`, so real-root pairs
  stay explicit). Init = flat-off-resonance `compiler::section_biquad` peaks/notches → strong
  per-corner refine against each corner's exact H → **stage-correspondence search from TRAIN
  interior error** (not frequency sort) → joint interior polish. Every candidate is scored
  through `pack → interpolate_biquad → biquad_cascade_complex`. ERB (Glasberg&Moore) + coherence
  weighting; a full-band ceiling barrier and a 17×17 interior-stability barrier keep the packed
  interior bounded and stable.

## Files created / modified
- **new** `trench-core/src/bin/tf_oracle.rs` (the pipeline)
- **new** `trench-core/tests/stage_correspondence.rs` (endpoint-preserving permutation regression)
- **mod** `trench-core/src/response.rs` (+`biquad_stage_complex`, `biquad_cascade_complex` — the single owner of complex cascade response)
- **mod** `trench-core/Cargo.toml` (+`[[bin]] tf-oracle`)
- generated: `dev/tmp/tf_oracle/<session>/` proof bundles (e.g. `s7/`)
- NOT touched: `minifloat.rs` (pre-existing dirty work preserved), UI, docs, lockfiles.

## Verification (session s7, `dev/tmp/tf_oracle/s7/`)
- estimator: loopback unity dev 0.000 dB / delay 0, LTI level-A/B 0.000 dB, repeatability rms 0, coverage 1.000
- fit: train 9.99 / held-out 9.94 dB mag-RMS (baseline 37.5); correspondence search beats the frequency-sorted identity permutation
- certification: 33×33 → 0 unstable, 0 nonfinite; permutation regression corner Δ 0.0 dB / interior Δ 85.6 dB
- body gates: 240 bytes, no-op load/save identical, body/cart parity, declared edit isolated to 1 word, real-root rows explicit (refused by conjugate reader)
- trench-core suite: 86 passed / 0 failed (all features); bin self-checks 5/5

## Honest status
- Recovery is **functional, not tight**: null −2.1 dB at center, ~10 dB mag-RMS. The peak-pick +
  Hooke-Jeeves fitter finds the right basin and generalizes but does not null. **The identified
  lever for a tight null is vector-fitting init** (Gustavsen&Semlyen: fit stable poles/residues
  to each corner's complex H → SOS, then correspondence) — R2 research is in hand; not yet coded.
- `owned_audit_gate` (crown −3..36 dB, parity <30 dB) reports `false`: that is a product-audibility
  gate, not a stability gate; a system-ID candidate matching an arbitrary target need not satisfy it.
  The REQUIRED stability/finite certification (0/0) passes.

## Provenance / clean room
Pipeline is clean-room-**capable**. This building agent's context HAS seen decoded E-mu/EmulatorX
coefficients (prior sessions), so a fitted REAL-target body from THIS agent must NOT be labelled
"strict clean room." Synthetic/authored oracles are self-produced and legal. No ROM/preset/P2K bytes,
coefficient rows, or protected names are read or copied. Fresh-run handoff: an unexposed operator runs
the exact reproduction command against the anonymous target (see below).

## Decisions needed
1. Second-gen bank targets are decided (Branching Mouth, Formant Coupler) — Tyson picks the cited
   frames to build (df2-morph-authoring taste gate) before the fitter authors bodies.
2. Code the vector-fitting init before authoring the bank tightly (functional fit is too loose for
   final bank bodies).

## Blockers
- Real anonymous black-box target capture is the only EXTERNAL blocker: it requires an operator to
  bounce wet WAVs from the target plugin in BODY SOLO (InputMode None, SpatialMode Off, AGC+saturation
  off, amount 1.0) at each grid state, driven by `excitation_A.wav`. Everything else runs headless.

## Next command
```
# reproduce the synthetic end-to-end proof:
cargo run -p trench-core --bin tf-oracle -- run --session <id>
# or target a specific legal clean-room body:
cargo run -p trench-core --bin tf-oracle -- run --session <id> --oracle fixtures/four-pose.body240
```
For a real anonymous target, replace `synth` with externally-bounced wet WAVs into
`dev/tmp/tf_oracle/<id>/capture/wet_<label>_A.wav`, then `estimate → fit → verify → bundle`.
