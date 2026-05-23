# STATE.md

**This file is the live cache.** Claude updates it on every code change.
If you (Tyson) want to know current project state, read this file.
If it disagrees with the repo, Claude is required to fix it before
doing new work (per CLAUDE.md session protocol).

Do not edit by hand unless correcting Claude.

---

## State correction (2026-05-23)

- Live repo reality: root `Cargo.toml` is now a Cargo workspace with
  `members = ["trench-core", "forge"]`. Older Forge notes that say there
  is no root workspace are historical and superseded.

## Session note (2026-05-23) — Forge ARMA fitter replaces LPC final path

Forge's upload-to-corner fitter no longer uses LPC pole/nearest-valley
sections as the final answer. `forge/src/dsp.rs` now adds
`fit_corner_arma_from_window(window, source_sr, runtime_sr, options) ->
FitResult`: LPC provides initial candidates only, then a coordinate-descent
ARMA refinement optimizes six active pole-zero sections against a smoothed,
perceptually weighted source envelope. Every candidate is stabilized,
conformed to the packed minifloat range, encoded with
`PackedCorners::from_corner_data`, decoded at the same corner, and scored
post-pack. The score includes weighted residual, formant peak error, max
pack drift, and impossible-notch penalties.

`forge/src/main.rs::refit_anchor` now calls the ARMA fitter. `Review` fits
no longer auto-assign; only `Ready` can assign to LOW/HIGH or hidden C/D.
Inspect now reports source peak frequencies, fitted peak frequencies,
pre/post-pack residual, formant error, max pack drift, and the review/block
reason. The product surface layout and runtime cascade/cartridge/interp
topology were not changed.

Diagnostics from `cargo test -p trench-forge dump_real_fit_pipeline --
--nocapture`:
- `vowel_oo.wav`: Ready, residual/post-pack residual 7.3 dB, formant
  error 0.64, max pack drift 0.00000. Source peaks 296/384/462/748/934 Hz;
  fitted peaks 296/343/398/462/836 Hz.
- `vowel_eh.wav`: Review, residual/post-pack residual 6.0 dB, formant
  error 1.31, max pack drift 0.00000. Source peaks 296/462/577/748/836 Hz;
  fitted peaks 384/445/516/599/695 Hz. This no longer collapses into a
  broad low-pass blob, but is still analysis/peak-lock limited rather than
  pack-range limited.

This initial ARMA pass was superseded by the stylised-target pass below; the
current focused tests and verification count are listed there. No runtime
topology or cartridge changes were made.

## Session note (2026-05-23) — Forge stylised low-Q target extraction

Forge no longer treats a recording as a literal response curve for the fitter.
`forge/src/dsp.rs` now inserts a stylised target layer between
`source_envelope`/window analysis and the six-stage ARMA refinement:
`stylized_target_from_raw` heavily smooths the analysis envelope, preserves
broad tilt, extracts major landmarks below 8 kHz, keeps important valleys, and
reduces the high band to a small number of teeth/scar peaks. The default
`TargetMode::LowQGraphic` clamps the fitter toward broad pole radii, moderate
zero bite, and no ultra-narrow or single-stage-dominated frame.

The fitter still optimizes the actual six pole-zero cascade, but it now scores
against the simplified target after the `PackedCorners::from_corner_data`
round-trip. Formant gating ignores decorative high-scar peaks above the
formant band; those peaks remain diagnostic/target features but do not force
vowel auto-assignment. Inspect now overlays raw source, simplified target, and
post-pack fit, and lists detected peaks/valleys plus per-stage
role/frequency/radius/zero diagnostics.

Diagnostics from `cargo test -p trench-forge dump_real_fit_pipeline --
--nocapture` after this change:
- `vowel_oo.wav`: Review, residual/post-pack 5.2 dB, formant error 1.83,
  pack drift 0.00000; source peaks 237/331/413/516/934/8326 Hz, fit peaks
  255/319/398/498/4955 Hz.
- `vowel_eh.wav`: Review, residual/post-pack 2.8 dB, formant error 1.08,
  pack drift 0.00000; source peaks 237/413/516/645/836/8326 Hz, fit peaks
  275/343/429/536/669 Hz.

Focused tests now cover: DJ-Alkaline-like graphic low-Q target extraction,
vowel-like landmark preservation, post-pack closeness to the simplified
target, and Ready-only auto-assign. Verification: `cargo fmt -p
trench-forge` passed and `cargo test -p trench-forge` passed: 10 tests.
Existing `trench-core` warnings remain. Current limitation is mainly the
analysis/landmark gate and local optimizer; pack drift is effectively zero in
the tested cases.

## Current focus

> **SUPERSEDED (2026-05-19) — read "Active session" below first.** This
> section predates the morph-interpolation work. Its −35/−27 dB Q100
> corner-null figures were measured under an inverted-lag bug; corrected
> results are in "Packed parity — VERIFIED RE-AUDIT" and "Rust cascade
> parity" below. Live state and the next task (Type 2/3 compilers) are in
> "Active session". The morph interpolation is proven, auditioned, and the
> encoded-domain fix is decided.

Talking Hedz null gap is isolated. The "candidates null poorly" symptom
was 90% a bug in `tools/render_hedz.py`: it appended df2's ~20 Hz DC
blocker, which the E-mu heritage render does not have. That extra filter
collapsed the null from -69 dB to -3 dB. Fixed via `--no-dc-block`.

With the DC blocker off, the validated source `P2k_013.json`, and the
runtime->P2K corner swap (re-proven-facts.md), diagonal nulls are:

| corner (runtime) | null depth | gate (-60 dB) |
|------------------|-----------|---------------|
| M0_Q0            | -69.4 dB  | PASS          |
| M100_Q0          | -62.3 dB  | PASS          |
| M0_Q100          | -35.2 dB  | FAIL          |
| M100_Q100        | -26.8 dB  | FAIL          |

The two Q0 corners pass. Q100 corners investigated further:

- Empirical transfer function (csd, wet/dry vs cand/dry) matches to
  0.0-0.3 dB / 0.0-1.7 deg at every frequency — the Q100 filter is
  essentially correct, not "sharper/deeper".
- SR-mismatch / clock-drift ruled out: best candidate resample ratio is
  1.00000 (no drift).
- Windowed null (8 segments): 7/8 segments null -42 to -44 dB; the final
  1/8 nulls -15 to -27 dB and drags the whole-file figure to -27/-35.
  The corrupt tail is a capture artifact (length/trim mismatch between the
  wet region and 222323232.wav) — retrim and re-null.
- Clean residual after excluding the tail is ~-42 dB, and it is uniform:
  loud-only windows null the same as all windows (not a noise-floor or
  quiet-passage effect).
- Coefficient precision ruled out: a free 30-parameter least-squares refit
  of the 6-stage cascade against the wet cannot beat ~-45 dB. If an
  unconstrained LTI fit stalls there, -42 dB is the structural limit -
  the Q100 wet is not reproducible as a 6-biquad cascade of this dry.
- Raw-ROM re-decode is not possible here: no EosAudioEngine.dll and no
  raw P2K uint16 bytes in the repo. `pyruntime/minifloat.py` has the
  decoder but nothing to feed it.

CONCLUSION: Q100 (-60 dB) is blocked on the captures / non-LTI X3
behavior, not on P2k_013.json. No coefficient change reaches the gate.
Next step is Tyson's: recapture the Q100 wets clean (verify knobs sit at
the literal M/Q corner, no automation, and that X3 per-sample coefficient
interpolation is not active). If a clean recapture still caps at ~-42 dB,
X3 does something non-LTI at high Q and the -60 gate is a spec question.
The render kernel was ruled out: the proprietary Rossum form
(`temp/s0/s1` state recursion) has transfer function
`H(z) = c4(z² + (c0-2)z + (1-c1)) / (z² - (2-c2)z + (1-c3))` — exactly a
biquad, so `sosfilt` is a faithful stand-in. The gap is not the kernel.

Sources: validated cartridge is `trenchwork_clean/datasets/p2k_skins/
P2k_013.json` (a1 direct, 44.1k ROM domain), NOT `Talking_Hedz.json`
(equivalent but reconstructs a1 from pole_freq). `--native` SRC rendering
is a slow hardware experiment only; X3 VST parity stays on the 44.1 kHz path.

## Pipeline status

- [ ] `trench-core/` carried over from old repo and building cleanly
- [ ] `juce-shell/` carried over and loading cartridges
- [x] `tools/compile_raw.py` carried over and tested
- [x] `tools/null_test.py` runs and produces null depth in dB
- [ ] First null test against `ref/canonical/` passes (internal consistency)
- [ ] Fresh X3 wet render of Talking Hedz captured for ground-truth null
- [ ] First df2 body authored: Talking Hedz match (calibration fixture)
- [ ] Talking Hedz match passes null test at all 4 corners ≤ −60 dB
- [ ] Talking Hedz match thrown away; pipeline now trusted

## RE findings & policy (2026-05-18)

### ref/ assembly (2026-05-19)

Brought into the repo as reference (not shipping source):
- `ref/p2k_skins/00_talking_hedz.json` — validated 4-corner P2K
  cartridge (= P2k_013). Drives ROM-playback null tests at all 4
  corners. From trenchwork_clean/cartridges/.
- `ref/heritage/{DIARY.md,INDEX.md,Ear_Bender.csv}` — forge design
  knowledge. From trenchwork_backup/docs/calibration/.
- `ref/codex/trench_re_codex.md` — verified RE findings (the annotated
  clean copy, with the [UNVERIFIED]/[SCOPE] corrections).
- `ref/patents/US5170369.pdf` — Rossum 1992, primary source.

### Authoring compile path (2026-05-19)

Validated end-to-end: `test.xml` -> `pyruntime/designer_compile.py`
(`parse_xml` + `compile_designer`, Type 1 branch) -> kernel coeffs ->
df2 cascade nulls -133.6 dB (M0) / -140.1 dB (M100) vs E-mu wet.
Type 1 compiler is bit-exact. `pyruntime/` (the designer compiler +
forge) is now copied into df2 — `import pyruntime.designer_compile`
works from the repo root. STILL OPEN: Type 2 (Shelf) and Type 3
(vocal) compiler branches untested.

`render_hedz.py` now defaults `--calib` to the in-repo
`ref/p2k_skins/00_talking_hedz.json` (also accepts the keyframes
cartridge layout). Verified: M0_Q0 still nulls -69.4 dB PASS.

Notes on the pyruntime copy: `pyruntime/CLAUDE.md` is package doc
(forge/compiler boundary) and loads as nested instructions when
working in that subtree — kept intentionally. `pyruntime/recipes/
type_census.py` has a stale hardcoded `C:/Users/hooki/trenchwork/...`
path; it is a dev script, not in the compile path.

### Morph interpolation — FUN_1802c3d40 decompiled (2026-05-19)

Pulled the real decompilation via the Ghidra MCP. The Z-plane morph
surface interpolator is a **linear 2D bilinear lerp in the u16 integer
domain**:

    topEdge = A + (short)trunc((B-A) * morphX)     # corners 0->1
    botEdge = C + (short)trunc((D-C) * morphX)     # corners 2->3
    out     = topEdge + (short)trunc((botEdge-topEdge) * Q)

6 stages x 5 params, corner banks at u16 offsets 0/30/60/90, output 120.
A/B/C/D = M0_Q0 / M100_Q0 / M0_Q100 / M100_Q100. No log, no ARMAdillo,
no increment table — straight-line lerp of the raw minifloat words with
integer truncation at each step. The morph curve comes entirely from the
nonlinear minifloat decode (FUN_1802c3600) afterward.

df2 bug: `cartridge.rs:interpolate()` runs the same bilinear formula on
DECODED FLOATS. Fix: store u16 words, lerp them per above (truncate to
u16 each step; morph-first order, not the current Q-first), then decode.
Do not trust the stale `pyruntime/minifloat.py::interpolate_packed`
helper as the oracle yet: it is Q-first and clamps. The faithful model is
morph-first packed u16 interpolation with E-MU/MSVC-style int16 truncation
at each lerp step, followed by a 65536-entry minifloat decode LUT and
`c0=4*d0+d1`, `c1=d1`, `c2=4*d2+d3`, `c3=d3`, `c4=scale*d4`.
ARMAdillo (patent FIG. 11) is a separate temporal glide, NOT on this path.

### Coefficient-field bakeoff harness (2026-05-19)

Added `tools/coefficient_field_bakeoff.py` as an offline-only analysis
harness. It does not modify runtime code or cartridge assets. Outputs are
written under `dev/tmp/coefficient_field_bakeoff/<timestamp>/`.

Latest run:
`dev/tmp/coefficient_field_bakeoff/20260519_153746/`

- Oracle: packed u16 corners -> morph-first int16-truncating bilinear ->
  decode LUT -> c0..c4 recombination. Because raw ROM u16 words are not
  present here, the harness derives packed corner words from the decoded
  c0..c4 in `ref/p2k_skins/00_talking_hedz.json`.
- Sampled 17x17 training grid and 16x16 held-out offset grid.
- Fitted Chebyshev d4, bicubic spline, and thin-plate RBF coefficient
  surfaces per stage/coefficient.
- All fitted surfaces stayed pole-stable on all 256 held-out points.
- Held-out metrics: decoded-float bilinear mag RMS 7.475 dB; Chebyshev
  1.617 dB; bicubic 0.516 dB; RBF 0.507 dB.
- Listening/render proxy: exact 50% is on the training grid, so exact
  spline/RBF nulls there are not evidence by themselves. The nearest
  held-out midpoint proxy (0.46875, 0.46875) best result is Chebyshev at
  -20.18 dB vs the packed oracle, about 20.16 dB better than decoded-float
  but still far above the -60 dB gate. Real success is not claimed yet.

### Packed parity gap diagnosis (2026-05-19)

> **SUPERSEDED — see "Packed parity gap — VERIFIED RE-AUDIT" below.**
> The -24.38 dB "clean window" figure in this section is WRONG: it came from
> an inverted lag sign. Correct alignment gives -53.75 dB. The "ROM words"
> fix path is downgraded to an unproven ~6 dB optimization.

Tool: `tools/packed_gap_diagnosis.py`
Output: `dev/tmp/packed_gap_diagnosis/20260519_172643/`

The reported -12 dB midpoint null was a tail-trim artifact, not an accuracy figure.

**Corrected result: clean windows all null at -24.38 dB uniformly.**

X3 capture is 13343 samples shorter than the df2 render. The last 1/8 time window
(where x3 has gone silent but packed still has content) drags the whole-file null
from -24 dB to -12 dB. Proper measurement uses only the first ~5 seconds.

**Corner encode-roundtrip null depths (all PASS the -60 dB gate):**

| corner | null (float vs packed-roundtrip) | max_Q |
|--------|----------------------------------|-------|
| M0_Q0  | -82.45 dB                       | 163.4 |
| M100_Q0 | -81.62 dB                      | 145.9 |
| M0_Q100 | -68.46 dB                      | 606.5 |
| M100_Q100 | -63.72 dB                    | 779.8 |

Encode quantization at corners is NOT the bottleneck.
Per-stage pole angle error: max 0.000126° (negligible).

**Residual character (clean windows): static, broadband, temporally uniform.**
Each of 6 clean windows nulls at exactly -24.38 dB — same null depth in every
time window and every frequency band. The error is a static broadband filter shape
mismatch, NOT a resonance-specific phase error, NOT AGC-driven.

**Ranked causes:**
1. PRIMARY: P2K JSON stores decimal-truncated floats (6 d.p.). Re-encoded to u16
   → 0-2 LSB difference from original ROM words → packed bilinear compounds this
   into static midpoint filter mismatch (~0.5 dB magnitude, ~2-3° phase).
2. SECONDARY: Tail trim artifact dragging whole-file null from -24 to -12 dB.
3. NOT FACTORS: AGC, boost, pipeline, interpolation order.

**Fix path**: Obtain original E-mu ROM u16 corner words for skin 13 via Ghidra
static extraction of 240-byte block from EosAudioEngine.dll `.rdata` section,
OR Cheat Engine runtime dump at offsets 0x2C0/0x2FC/0x338/0x374. Replace
derived-packed corners with ROM words. Expected result: -90+ dB (bit-accurate).

### Packed-domain interpolation experiment (2026-05-19)

Files added (experiment only, not the shipping path):
- `pyruntime/packed_interp.py` — clean scalar Python implementation of
  the morph-first packed u16 bilinear interpolation formula. Supersedes
  the stale `pyruntime/minifloat.py::interpolate_packed` (which is Q-first
  and clamps). New module is morph-first and wraps per MSVC i16 semantics.
- `trench-core/src/minifloat.rs` — Rust implementation: `decode`, `encode`,
  `lerp_u16`, `PackedCorners`. Gated behind the `packed_interp` Cargo
  feature flag (not compiled in default builds).
- `trench-core/tests/packed_interp_test.rs` — 7-test integration suite.
  Run: `cargo test -p trench-core --features packed_interp --test packed_interp_test`
- `tools/packed_interp_report.py` — verification report script.

Verification results (2026-05-19):

Python scalar (`packed_interp.py`) vs numpy oracle (`coefficient_field_bakeoff.py`):
- PASS at all 6 test points (diag 25/50/75, offset 25/50/75): max |Δ| = 0.00
- `lerp_u16` scalar vs numpy: PASS on all 8 handpicked edge/boundary cases
  (including wrapping at 0→0xFFFF with frac=1.0, and the exact C cast order)

Rust (`minifloat.rs`) unit tests: all 4 pass without feature flag.
Rust integration tests (`packed_interp_test.rs`): all 7 pass with --features packed_interp.
Existing focused tests (compile_raw_roundtrip, cartridge_schema_tests,
runtime_morph_q_audit, render_diff_harness): all pass unchanged.

Decoded-float vs packed at midpoint (M=0.5, Q=0.5) using hedz JSON:
- Max coefficient |Δ|: 0.508 (stage 5, c0)
- Render null depth: −0.06 dB (near-full cancellation failure = audibly distinct paths)
- Report: `dev/tmp/packed_interp_report_20260519_161550.md`

Per-stage Δ at midpoint (packed − decoded-float):

| stage | Δc0 | Δc1 | Δc2 | Δc3 | Δc4 |
|---|---:|---:|---:|---:|---:|
| 0 | -0.019 | -0.003 | -0.036 | -0.021 | +0.000 |
| 1 | -0.000 | +0.000 | -0.015 | -0.009 | +0.000 |
| 2 | -0.022 | -0.021 | -0.016 | -0.013 | +0.000 |
| 3 | -0.006 | -0.006 | -0.005 | -0.005 | +0.000 |
| 4 | -0.047 | -0.016 | -0.027 | -0.023 | +0.000 |
| 5 | -0.508 | -0.000 | -0.031 | -0.003 | +0.000 |

Corner words are derived-packed-canonical (no raw ROM u16 bytes in repo).
The packed path is NOT the default shipping path. No cartridge format or
cascade topology was changed.

### A/B render from Rust Cascade (2026-05-19)

Files added:
- `tools/bake_cartridge.py` — converts P2K JSON stages to pre-compiled c0..c4
  (Python stage_to_kernel convention). Output: `dev/bake/00_talking_hedz_compiled.json`.
- `trench-core/tests/packed_interp_ab_render.rs` — renders 4 WAVs using the
  actual Rust Cascade (behind `packed_interp` feature flag).

Run:
```
python tools/bake_cartridge.py   # first time only
cargo test -p trench-core --features packed_interp --test packed_interp_ab_render -- --nocapture
```
WAVs written to `dev/tmp/packed_interp_ab/<timestamp>/`.

Results (2026-05-19, compiled hedz cartridge):
- midpoint (M=0.5, Q=0.5): null = **+3.20 dB** (packed vs float)
- max|biquad coeff diff| at midpoint: 0.272 (after kernel→biquad conversion)

Audio content: float 97.7% non-silent / peak 0.54; packed 89.3% non-silent / peak 0.99.
Latest WAVs: `dev/tmp/packed_interp_ab/2026138_065851/`

Positive null depth means the difference signal is louder than the packed reference.
The two paths are materially different.

Coefficient-space note: the Python stage_to_kernel convention (all-positive c0..c4)
is incompatible with the Rust Cascade's DF2T biquad form (c1/c3 negative). A
`kernel_to_biquad()` step in the test file converts before rendering.
Ramp fix: the 32-sample coefficient ramp must be warmed up on silence, then
`set_targets` called again to zero residual deltas — otherwise the first signal block
overshoots the target poles outside the unit circle.

**Audition result (2026-05-19):** packed midpoint sounds more "ooo" than the float path.
The packed path is darkening/rounding the vowel character, not brightening toward "Aee."
Source is derived-packed-canonical (re-quantized from float, not original ROM words) —
so "ooo" reflects the re-quantization artifact, not necessarily the historical packed sound.
Next question: does float or packed match an E-MU hardware reference at M=0.5 Q=0.5?
That comparison determines whether packed is correcting or corrupting the midpoint sound.

**Midpoint wet received (2026-05-19):** `C:\Users\hooki\Downloads\hedzm50q50.wav`
compared against df2 renders from `C:\Users\hooki\Downloads\222323232.wav`.
Lag-aligned overlap results:

| candidate | lag | null | gain-matched null | gain |
|-----------|----:|-----:|------------------:|-----:|
| decoded-float M50_Q50 | 2930 | -0.21 dB | -0.46 dB | 3.622 |
| derived-packed M50_Q50 | 2817 | -11.92 dB | -12.19 dB | 0.940 |

Output/report: `dev/tmp/hedz_midpoint_reference_compare/20260519_hedzm50q50/`.
Channel-choice sanity check did not change the result. Corner sanity against
existing Downloads candidates reproduced the known nulls:
M0_Q0 -69.41 dB, M100_Q0 -62.26 dB, M0_Q100 -35.22 dB, M100_Q100 -26.84 dB.
Conclusion: for the new E-MU M50_Q50 wet, derived-packed is much closer than
decoded-float, but still nowhere near the -60 dB gate. This supports packed
interpolation as the correct direction, while raw ROM packed words / capture
trim / remaining source mismatch are still unresolved.

Frequency diagnostic:
`dev/tmp/hedz_midpoint_reference_compare/20260519_hedzm50q50/m50q50_frequency_overlay.png`
and `FREQUENCY_REPORT.md`.

> **NOTE:** the -12.19 dB packed figure above is the tail-contaminated
> whole-overlap null (correct, but contaminated). The clean-region null is
> -53.75 dB — see the VERIFIED RE-AUDIT section below.

### Packed parity gap — VERIFIED RE-AUDIT (2026-05-19)

Independent audit, recomputed from the raw WAVs without trusting the prior
diagnosis.

Tool: `tools/verified_packed_audit.py`
Output: `dev/tmp/verified_packed_audit/20260519_201750/VERIFIED_DIAGNOSIS.md`

**The prior -24.38 dB "clean window" figure was wrong — a lag-sign error.**
Correct convention: X3[n] aligns with cand[n-lag], lag = 2817 (the X3
capture starts 2817 samples after the df2 render onset). The prior diagnosis
shifted the candidate the wrong direction.

Verified M50/Q50 nulls (cartridge `ref/p2k_skins/00_talking_hedz.json`):

| candidate | whole-overlap | clean-window (-53 region) |
|-----------|--------------:|--------------------------:|
| derived-packed | -12.19 dB (tail-contaminated) | **-53.75 dB** |
| decoded-float  | -0.07 dB | -0.08 dB (does not align at any lag) |

- Clean window = X3 content bounds [7283, 254915); df2 [4466, 252098).
  The X3 capture goes hard-silent ~16935 samples before the dry content
  ends — it was ended early, not just shorter. Tail must be excluded.
- The packed null is razor-sharp in lag: -22 dB at 2816, -53.75 at 2817,
  -13 at 2820. A genuine sample-accurate alignment.
- Windowed clean nulls: -52.5 to -54.8 dB, flat to 2.3 dB across 5.6 s.
  Residual is static/LTI — no drift, no time variation.
- Band nulls (clean): sub/low -65, high/air/high-mid -61 to -62,
  **low-mid (250-1000 Hz) -53.5** is the single limiting band.
- AGC and boost verified as bit-exact identity (cascade peak 0.36 never
  reaches the AGC table threshold; boost = 1.0). "Not factors" confirmed.
- Corner encode-roundtrip reproduced exactly (-63 to -82 dB). These do NOT
  test ROM-word fidelity — no ROM reference exists in the repo.

CONCLUSION: derived-packed M50/Q50 nulls -53.75 dB, ~6 dB from the -60
gate — an optimization, not the -24 dB failure previously reported. The
"obtain ROM words" fix path is now an unproven ~6 dB hypothesis, not a
rescue. Ranked causes: (1) corner-word encode quantization compounding
through the integer-truncating u16 lerp [moderate]; (2) derived words ≠
ROM words [low, unproven]; (3) low-mid band coefficient mismatch [where
the residual lives]. Next: audition -53.75 dB for transparency; re-audit
the Q100 *corner* nulls (STATE "Current focus" records -35/-27 dB — almost
certainly the same inverted-lag bug, since a midpoint blending both Q100
corners could not reach -53.75 dB if those corners were truly -27 dB off).

Gain-matched aligned spectra show derived-packed matches the E-MU midpoint's
main PSD peaks at ~493, 600, 2137, 2740, and 5060 Hz. Decoded-float shifts the
low formant structure upward (~740 and 1319 Hz), which explains why it loses
the real midpoint vowel. Band RMS spectral error confirms the direction:
decoded-float is off by 16.72 dB in low-mid and 19.08 dB in high-mid, while
derived-packed is 0.33 dB and 0.47 dB respectively. The remaining -12 dB null
gap is therefore probably not gross formant placement; look next at trim,
time variation/ramping, AGC/gain law, raw ROM words, or residual non-LTI/capture
behavior.

### Morph interpolator decomp — confirmed via Ghidra MCP (2026-05-19)

Decompiled `FUN_1802c3d40` from the live E-mu engine binary (`EmulatorX.bin`,
the 33 MB x64 PE; base 0x180000000).

**The interpolator is bit-identical to `pyruntime/packed_interp.py`:**
morph-first packed u16 bilinear, `(short)trunc((float)(int)(B-A)*frac)+A`
with int16 truncation at every lerp step. Corner role assignment confirmed:
A/B/C/D = M0_Q0 / M100_Q0 / M0_Q100 / M100_Q100.

**Live `CPhantomRTFilter` object offsets (verified from the decomp):**

| field | offset | notes |
|-------|--------|-------|
| corner A (M0_Q0) words   | 0x2C0 | 30 u16 (6 stages × 5) |
| corner B (M100_Q0) words | 0x2FC | 30 u16 |
| corner C (M0_Q100) words | 0x338 | 30 u16 |
| corner D (M100_Q100) words | 0x374 | 30 u16 |
| interpolated u16 output  | 0x3B0 | decoded by `FUN_1802c3600` |
| decoded c0..c4 floats    | 0x540 | 5 floats × stage count |
| active stage count       | 0x420 | int |

These match FRAME_BANK.md Tier 1 exactly (A 0x2C0 / B 0x2FC / C 0x338 /
D 0x374). The 240-byte coefficient block = 4 corners × 30 u16 = 240 bytes.

**Interpolation is no longer a suspect** for the packed midpoint gap. The
runtime morph/Q math is proven bit-exact against the df2 packed model. The
only remaining suspect for the -53.75 dB → -60 dB gap is **corner-word
truth**: the derived-packed words (re-encoded from the P2K JSON's decoded
floats) vs the original ROM / runtime-loaded u16 words.

**Static source path (runtime-loaded — no static .rdata address):**
`FUN_1802c0150` resolves skin 13 → stores the skin-descriptor pointer at
`this+0x20`. `FUN_1802c02b0` then calls
`descriptor->vtable[1](descriptor, this[3], this)`, which copies the corner
words into the filter object's 0x2C0 banks. The descriptor table is built
at runtime; there is no static `.rdata` address for the Talking Hedz
descriptor. Static `.rdata` extraction is therefore ruled out for skin 13 —
the viable capture is a Cheat Engine runtime dump at object+0x2C0.

Checklist for the dump: `dev/tmp/cheat_engine_dump/CHECKLIST.md`.

### Packed parity — RESOLVED, bit-accurate (2026-05-19)

The skin-13 ROM corner words were captured by Cheat Engine runtime dump
(Emulator X3 VST in FL Studio, 44100 Hz). With them, the packed path is
**bit-accurate**.

Tools: `tools/rom_corner_audit.py`, `tools/locate_corners_in_dump.py`.
Captured data (reference-only, never shipped):
- `dev/tmp/cheat_engine_dump/skin13_region_full.bin` — 73728-byte region dump.
- `dev/tmp/cheat_engine_dump/skin13_corners_rom.bin` — 240-byte carved
  4-corner u16 block (A/B/C/D, 30 u16 each), found at object+0x2C0.

**Result — M50/Q50 clean-window null vs X3 wet:**

| path | null | gate -60 dB |
|------|-----:|-------------|
| decoded-float bilinear | -0.08 dB | fail |
| derived-packed (JSON 6-dp words) | -53.75 dB | fail |
| **ROM words + morph-first u16 lerp + c4=4*d4** | **-95.41 dB** | **PASS (bit-accurate)** |

**Three facts settled:**

1. **The `P2k_013` JSON corner coefficients are accurate.** All 4 ROM
   corners decode to the JSON grids within 2-3e-6. The JSON is correct to
   its stored precision; it was never structurally wrong.

2. **c4 recombination correction.** The engine's word→coeff recombination
   is `c0=4d0+d1, c1=d1, c2=4d2+d3, c3=d3, c4=4*d4`. df2's model used
   `c4=d4`. The 4.0 scale is the constant `FUN_1802c0150` writes to
   `this+0x2a8`. This is a **no-op for the derived-packed path** — encoding
   `c4` vs `c4/4` is a uniform minifloat exponent shift (−0x2000), the
   integer lerp passes a uniform offset through linearly, and the ×4 on
   decode undoes it exactly. It matters only for **reading real ROM
   words**: ROM `w4` are stored in the `/4` domain, so the old `c4=d4`
   decode read them 4× too small and turned the ROM dump into garbage
   (−0.00 dB). Fixed so the model is hardware-faithful and can ingest ROM
   words.

3. **The −53.75 dB derived-packed gap is JSON 6-decimal-place truncation.**
   `00_talking_hedz.json` stores coefficients to 6 d.p.; re-encoding those
   to u16 gives words that differ from the true ROM words by 22-422 LSB in
   w0-w3. Propagated through interpolation, that caps the derived path at
   −53.75 dB; real ROM words remove it → −95.41 dB. (The original
   `packed_gap_diagnosis` "decimal-truncated floats" hypothesis was right.
   The c4 bug was a *separate* defect that did not affect this number.)

Interpolation order, capture trim, AGC, and non-LTI behavior were all
correctly ruled out by the earlier audit. The packed-domain interpolation,
done faithfully with real ROM words, reproduces E-mu hardware bit-accurately.

**Code fix applied (2026-05-19):** `c4 = 4*d4` / `w4 = encode(c4/4)` in
`pyruntime/packed_interp.py` (`words_to_coeffs`, `coeffs_to_words`),
`tools/coefficient_field_bakeoff.py` (`words_to_kernel`, `kernel_to_words`),
`trench-core/src/minifloat.rs` (`interpolate`, `from_corner_data`). Rust
tests green (38 lib + 7 `packed_interp` integration). The derived-packed
−53.75 dB is unchanged by the fix, as expected (no-op on that path).

The packed path is still NOT the default shipping path and the cartridge
format is unchanged — promotion is a separate decision for Tyson.

### Rust cascade parity — VERIFIED bit-accurate (2026-05-19)

The shipping Rust `trench-core` `Cascade` reproduces the Python
`scipy.sosfilt` M50/Q50 ROM-word reference **exactly** — verified from
scratch, not assumed. The −95.41 dB bit-accurate result now reaches the
actual shipping runtime, not just a Python stand-in.

The 2026-05-19 A/B-render `+3.20 dB` "divergence" was never a Rust-vs-Python
measurement: it compared packed vs decoded-float interpolation (two
different coefficient sets, both rendered inside Rust) on pink noise with
peak normalisation. There was no cascade bug.

Tools: `trench-core/tests/rust_cascade_parity.rs` (feature `packed_interp`),
`tools/rust_cascade_parity.py`.
Outputs: `dev/tmp/rust_cascade_parity/rust_rom_m50q50.wav` (Rust render,
float32), `dev/tmp/rust_cascade_parity/<ts>/PARITY_REPORT.md`.

Pipeline (both paths): `skin13_corners_rom.bin` (240 raw ROM u16) →
morph-first u16 bilinear `interpolate(0.5,0.5)` (c4=4·d4) → Rossum kernel.
Rust: `kernel_to_biquad` → `Cascade` (12-stage DF2T, fixed coeffs warmed up
on silence, zero state). Python: `kernel_to_sos` → `scipy.sosfilt`. AGC and
boost are verified identity (cascade peak 0.363 < AGC table threshold;
keyframe boost = 1.0).

| comparison | result | acceptance |
|---|---:|---|
| Rust render vs Python ref | 0/307386 samples differ, −578 dB | ≤ −90 dB PASS |
| Rust render vs X3 wet | −95.41 dB (lag 2817) | ≈ −95 dB PASS |
| Python ref vs X3 (control) | −95.41 dB | matches prior |

The Rust render is **bit-identical** to the Python reference (max sample
diff 0.0). `cascade.rs` and `scipy.sosfilt` both run the same DF2T
difference equation (`y=c0·x+w1; w1=c1·x−c3·y+w2; w2=c2·x−c4·y`) in f64, so
the f32 output lands on the same value every sample.

Code: added `PackedCorners::from_rom_bytes` to `trench-core/src/minifloat.rs`
(parses the 240-byte corner block verbatim — no decode/re-encode round-trip,
unlike `from_corner_data`). 39 lib tests + 8 `packed_interp` integration
tests green; default-feature build unchanged. No cartridge asset, cartridge
format, cascade topology, or default interpolation path changed.

The open question `cascade.rs ↔ Rossum biquad equivalence` is now closed.

### Reference extraction policy

`ref/ghidra_extracts/` is a measurement basis only — never shipping
source. Every extract carries a `_provenance` header and
`ships_in_df2_binary: false`. Authored cartridges null-test against
extracts; they never copy extracted coefficients. No extraction is made
without a named null test it supports.

### QSound lab classification

`C:\Users\hooki\trench_re_vault\analysis\qsound_lab\INVENTORY.md` is the
current classification pass. It labels files as primary or derivative and
records the numeric/hex/WAV candidate searches. No QSound files are promoted
into `ref/` yet.

Current QSound status:
- QCreator/QMixer vendor binaries, docs, extracted payloads, and demo WAVs
  exist in the lab folder.
- No file currently qualifies as a `qsound_spatial.rs` null target because
  no candidate names matched ITD/ILD/distance/azimuth parameters or proves
  shelf corners, ITD scalar, or band-law coefficients.
- The TODO constants in `trench-core/src/qsound_spatial.rs` remain live.

QSound spatial null test target remains planned, not sourced:
  Source: future promoted primary sources under `ref/qsound/` or
  `ref/ghidra_extracts/qsound/`.
  Targets:
    - ITD samples-per-law-unit constant replacing the current TODO scalar.
    - Low/high shelf corner Hz replacing current engineering defaults.
    - ITD law coefficients and ILD law coefficients for `SpatialProfile`.
    - Left/right low/mid/high band-law coefficient tables.
  Verification: df2 stereo output through `qsound_spatial.rs` must null
    against measured/extracted QSound output at matched ITD/ILD/distance
    parameters to <= -60 dB across the +/-60 degree azimuth sweep.

### Verified RE findings

- 5 computed filter classes: CPhantomMorphLP / MorphLPX / Morph2 /
  MorphDesigner / FilterP2k. vtables at 0x1806d60d8 / 60f0 / 6110 /
  6130 / 6150.
- MorphLP zero table at DAT_1806d73c0 (16 × 12 bytes) — verified.
- MorphLPX zero table at DAT_1806d7480 (15 × 6 bytes) — verified.
- Bypass sentinels 0xDFFF / 0xFFFF at DAT_1806d7500, used by the master
  compiler FUN_1802c6590 for cascade padding.
- Stage type bytes 1/2/3 confirmed. Type 3 split-code hack
  (> 0xDB → 0xDC anchor at negative morph) applies only to filter
  classes 0/1.
- Cascade is variable-length 1–6 stages; active count at object
  offset 0x420.
- Talking Hedz descriptor lives in a runtime-loaded bank table indexed
  by skin 13 — NOT at a static .rdata address.

### Rejected hypotheses

- ARMAdillo octaves/dB perceptual encoding — scaling tables are
  filter-class linear (slope, offset) pairs, not perceptual.
- Morpheus 3D 8-corner cube architecture — not present in
  EosAudioEngine.dll (NotebookLM conflated Morpheus hardware with
  Emulator X).
- Q axis as a universal perceptual modifier — only true for
  P2K-authored vocal filters; MorphLP-routed filters collapse Q
  structurally.

### Open questions

- Audition harness not yet built (breakbeat / sustained Ah / saw chord
  A/B loop) — prerequisite before authoring the first shipping body.
- First Ghidra MCP session: extract the AGC 16-element table at its
  function offset, cross-reference against `agc.rs` const. Match →
  `agc.rs` provenance-verified; mismatch → `agc.rs` is wrong.
- Talking Hedz descriptor recovery — trace the constructor that
  initializes the bank table FUN_1802c0150 reads.
- `hedz_rom.rs` feature-gating — first runtime work next session.
- Carry-over quarantines (see `dev/tmp/inventory.md`): canonical
  wet-render set undefined; P2K count 43/35/35 conflict;
  `emu_zplane_filter_types.xml` is a manual transcription;
  `juce-shell/source` is forge-era; `talking_hedz_x3_surfaces` JSON
  provenance unclear.

### Resolved (2026-05-18)

- Quarantine #3 (`heritage_designer_sections.json` NotebookLM-derived):
  resolved. Genuine E-mu vendor Filter XML located in `Emulator X
  Family / Templates (2) / Filter` (69 templates) and carried to
  `ref/heritage/`. `heritage_designer_sections.json` regenerated from
  the XML via `tools/extract_designer_sections.py`
  (`heritage-designer-sections-v2`); the NotebookLM JSON is not carried.
  The old `template_count: 83` = 69 vendor + ~14 user-authored scratch
  files (the latter live only in the fuller `Templates/Filter` set).

- `tools/heritage_coeffs.py` import fix: resolved. The three modules it
  needs (`constants.py`, `stage_params.py`, `encode.py`) are vendored
  into `tools/pyruntime/`. `heritage_coeffs.py` now runs standalone
  (type1/2/3 compile verified).
- Frame-bank source decided: the 69 vendor Filter XMLs in `ref/heritage/`
  compiled through `heritage_coeffs.py` are the bank. The Orbit/Planet
  Phatt ROM rip is cross-validation only — `rom_deep_scan` mis-segments
  blocks and hardcodes 5 names; full ROM-directory RE is deferred (not
  on the critical path; XML gives 69 named filters cleanly).

- Compiler/runtime harness repair: `Cartridge::from_json` now preserves
  `drive`, `spatial_profile`, and `mod_fn`; `tools/compile_raw.py`
  round-trip tests point at the carried compiler and use legal table
  radii/HF brace stages; the render-diff fixture is regenerated from
  `Cartridge::hedz_rom()` instead of a removed cartridge JSON path.
  Focused gate passed:
  `cargo test -p trench-core --test compile_raw_roundtrip --test cartridge_schema_tests --test runtime_morph_q_audit --test render_diff_harness --no-fail-fast`.
  `tools/null_test.py` was sanity-checked against the regenerated Hedz
  fixture and reports a -537.74 dB self-null.

## Future capability (post-v1)

- Morpheus 3D cube morphing (8-corner, function-generator-driven): a
  separate filter engine, not an extension of df2's frozen 4-corner
  runtime. Separate RE (Morpheus hardware, not EosAudioEngine.dll).
  Evaluate for v2. Closed for v1 — does not change the v1 E-mu sound,
  which is the P2K Morph×Q filters plus the four authored bodies.

## Design decisions

- **Runtime vs authoring split (2026-05-18).** The runtime stays the
  frozen, patent-faithful E-mu Z-plane cascade — that character *is* the
  product; a modern engine (Bark-bilinear warp, allpass-substituted
  delays, tube-model vocals) would sound good but would no longer sound
  like E-mu, and is out of scope for df2 (it would be a separate
  product). Modernization is allowed only on the **authoring side**:
  Filter Factory's frame fitter may use perceptually-weighted Prony /
  ARMA fitting (Bark axis for mids, ERB-weighted for low frequencies).
  That produces ordinary biquad coefficients for the frozen cascade —
  smart authoring, dumb faithful runtime. No runtime change.

## Shipping bodies status

| Body              | Authored | Null pass | Audible pass | Notes |
|-------------------|----------|-----------|--------------|-------|
| Speaker Knockerz  |          |           |              |       |
| Aluminum Siding   |          |           |              |       |
| Small Talk        |          |           |              |       |
| Cul-De-Sac        |          |           |              |       |

## Frame bank coverage

| Band                  | Frame count |
|-----------------------|-------------|
| sub (20–80 Hz)        | 0           |
| low (80–250 Hz)       | 0           |
| low-mid (250–1k Hz)   | 0           |
| high-mid (1k–4k Hz)   | 0           |
| high (4k–10k Hz)      | 0           |
| air (10k–20k Hz)      | 0           |

## Open questions

- Does runtime AGC exist in the E-mu engine? (Detect via null residual
  scaling with input level.)
- Is the MorphLP zero table's `FUN_1802c59b0` decoder worth REing, or
  does null testing against captured wets make it unnecessary?
- Capture method drift: are the existing 164 wet renders in `ref/canonical/`
  rendered through the same cascade math df2 uses? Verify before
  treating null results against them as ground truth.
- Full `cargo test -p trench-core --no-fail-fast` is not clean in this
  checkout because several tests still reference absent old-repo assets:
  `C:\Users\hooki\reference/canonical_audio`,
  `authoring/compilers/compile_grid.py`, `cartridges/factory/manifest.json`,
  `juce-shell/assets/cartridges/*.json`, and `cartridges/factory/vowels`.

## Active session

**HANDOFF (2026-05-20) — ROM stage-layout audit done; banded-slots fitter
falsified before code; existing role machinery surveyed; LPC extractor
built and verified.** The Audio-to-Cartridge pipeline now has its first
machine. The next-session task ("joint coherent 4-corner Forge fit") still
stands, but the structural prior for it shifted twice this session and is
worth recording before writing fitter code.

### ROM stage-layout audit — banded-slots falsified

Tool: `tools/rom_stage_layout_audit.py` (read-only; decodes the captured
240-byte ROM block via `tools/rom_corner_audit.words_to_kernel_c4x4` and
prints per-stage pole frequency, radius, Q for all 4 corners).

Findings for Talking Hedz, skin 13:

| stage | role | M0_Q0 | M100_Q0 | M0_Q100 | M100_Q100 |
|---|---|---:|---:|---:|---:|
| 0 | top edge (PHASE_SCAR) | 10.5 kHz | 9.5 kHz | 11.5 kHz | 10.1 kHz |
| 1 | F1 (FORMANT, FLUID) | 1006 Hz | **227 Hz** | 1076 Hz | **219 Hz** |
| 2 | low-upper (FORMANT) | 1.77 kHz | 2.67 kHz | 1.70 kHz | 2.42 kHz |
| 3 | upper (FORMANT) | 2.65 kHz | 3.08 kHz | 2.50 kHz | 2.72 kHz |
| 4 | high-air (PHASE_SCAR) | 5.20 kHz | 5.40 kHz | 4.91 kHz | 4.97 kHz |
| 5 | F2 (FORMANT, FLUID) | **225 Hz** | 2.02 kHz | **178 Hz** | 1.70 kHz |

Stages 0, 2, 3, 4 hold stable frequency bands across all 4 corners. Stages
1 and 5 **cross**: stage 1 drops 1 kHz → 220 Hz across the M axis while
stage 5 climbs 200 Hz → 2 kHz. The bilinear interpolator pairs by index,
so this is an explicit F1/F2 formant migration baked into E-mu's stage
assignment. A frequency-ordered "banded slots" fitter would have forbidden
the crossing — it was falsified before any code was written.

Q axis is structurally simpler: mostly increases pole radius (Q jumps
~5–60 → ~85–800 across the cross-the-board), but stage 5 *does* drift
15–21 % in frequency along Q. A naive "freq locked across Q" simplification
would have discarded real ROM behaviour.

### Existing role machinery — surveyed, gap identified

Two read-only Explore agents mapped the Forge pipeline. Result: the
"phoneme / anatomical role" vocabulary already exists in code, but the
fitter does not consume it.

| symbol | file:line | role |
|---|---|---|
| `Actor` enum (FOUNDATION/MASS/THROAT/BITE/AIR/SCAR) | `pyruntime/macro_compile.py:26` | compile-time slot allocator |
| `StageRole` enum (FORMANT/ANTI_FORMANT/SHELF/PHASE_SCAR/CORRECTION_LIGAMENT/LATENT) | `pyruntime/stage_roles.py:8` | per-role bounds: freq, radius, gain, zero_energy |
| `RolePolicy` (role + RigidityClass + bounds + InterpolationPolicy) | `pyruntime/preset_schema.py:44` | per-stage tagging structure |
| `slammed_dark_bright_belch.py` | `pyruntime/recipes/` | working precedent — 6 per-stage roles + audit gates |

The fitter (`pyruntime/forge_fit.py`) is **role-blind** — it consumes
magnitude+phase response and a perceptual profile only. That is the gap.
A joint fitter that reads `RolePolicy.bounds` as per-stage box constraints
is the small reversible step; no GUI is required for that wire-up.

### NotebookLM phoneme-GUI proposal — evaluated

Two pasted NotebookLM messages this session pushed a "Puppeteer / Phoneme
GUI" architecture and a Wasm/Web prototype direction. Four premises
verified against the codebase / data:

| claim | verdict |
|---|---|
| `Morph Points vs A/B Frames` doc | not present in repo (fabricated reference) |
| "puppeteer" UI metaphor | not found in codebase |
| "14-bit P2K parameter space" | wrong; the encoding is 16-bit u16 minifloat |
| "c-domain bilinear preserves analytic continuity of roots" | backwards; c-domain decoded-float bilinear is the path that nulls −0.07 dB at the midpoint, i.e. the bug we are fixing; the engine works in u16 word space |
| "Q axis locks frequency" | partially true; stage 5 drifts 15–21 % in freq along Q — a hard lock would discard real ROM behaviour |
| "midpoint must be in the cost function" | valid; matches the retained 2026-05-19 handoff note |

Operational conclusion (consistent with the user's "build the LPC extract,
skip the GUI" directive): the role vocabulary is sufficient *in code*;
build a CLI/recipe-driven role-bounded fitter first; revisit the GUI only
after the role-bounded joint fit has either passed or failed the −60 dB
gate on Talking Hedz.

Plan written to `~/.claude/plans/read-this-then-rrad-kind-bumblebee.md`
but **not executed** — user paused the joint-fit work in favour of the
audio-to-cartridge factory.

### LPC extractor — built and verified

Files added:

- `tools/lpc_extract.py` — load → mono → resample to 16 kHz → frame-RMS
  steady-state region (within 3 dB of peak, longest contiguous run) →
  conditional pre-emphasis → Hamming → LPC order 12 (autocorrelation via
  `scipy.linalg.solve_toeplitz`, the Levinson-Durbin solve) → `np.roots`
  → filter (imag > 0, |z| < 1, 90–7000 Hz) → sort by radius desc, take
  top 6 (pad warning if fewer) → re-sort by freq asc → bandwidth
  `−sr/π · ln(r)`. Writes `<basename>.lpc.json` + stdout table.
- `tools/lpc_test_input_gen.py` — two fixtures: `dev/tmp/lpc_test_input.wav`
  (flat 110 Hz impulse train through 6-pole all-pole at F=730/1090/2440/
  3500/4500/5500 Hz, r=0.96) and `dev/tmp/lpc_test_input_voiced.wav`
  (same, with `1/(1 − 0.97·z⁻¹)` source tilt baked in before the all-pole).
- `tools/lpc_verify_plot.py` — overlays signal spectrum, truth envelope,
  recovered envelope, and pole markers for both fixtures. Output:
  `dev/tmp/lpc_verify_plot.png`.

**Conditional pre-emphasis** (amended after the first verification failed
the spec's own gate): FFT-magnitude regressed against log2(freq) over
200–4000 Hz; pre-emphasis (coef 0.97) is applied only when measured tilt
is steeper than −3 dB/oct. Decision and measurement logged in the JSON
under a new `preemphasis` block. Without the conditional gate, spec-
default pre-emphasis on the flat fixture spent one pole pair cancelling
its added zero and dropped F1 entirely.

Verification gate: ±20 Hz freq, ±0.01 radius vs ground truth.

| fixture | measured tilt | preemph | worst Δf | worst Δr | gate |
|---|---:|---|---:|---:|:---:|
| flat | −2.46 dB/oct | skipped | +4.17 Hz | −0.0016 | PASS |
| voiced | −8.00 dB/oct | applied | +11.08 Hz | −0.0047 | PASS |

Visual confirmation in `dev/tmp/lpc_verify_plot.png` (truth envelope and
recovered envelope coincide at every formant for both fixtures).

Scope discipline: this session built only the extraction script. No
fitter, no runtime change, no cartridge code touched, no body authored.
Order 12 LPC chosen to match the 6-formant ground truth; not yet tuned
for real audio (TIMIT vowels, drums, Helmholtz resonators).

### Ghidra scope correction — Type 3 / Type 2 still matter

Correction to any over-broad "done with Ghidra" framing: P2K/Talking
Hedz runtime mystery is closed, but Type 3 and Type 2 compiler grammar are
still important for musical authoring.

LPC is the extraction engine: it can recover literal pole/formant targets
from source audio. Type 3 is the taste grammar for Ear Bender-like vowel
motion: vocal/formant constraints, high-frequency compression, split-code
anchor behaviour, and the tricks that keep resonance motion musical rather
than literal. Type 2 is the shelf/body/tilt grammar: weight, brightness,
and non-vocal body shaping.

Priority:

1. For the first LPC proof, do not wait on Ghidra. Build the CLI path from
   extracted poles to packed/post-encode audition and prove one source can
   become a valid morphable body.
2. For Ear Bender / Morpheus-feeling presets, extract Type 3 first, then
   Type 2. Treat `FUN_1802c6590` as authoring grammar/metrology, not a
   shippable coefficient source.

### NEXT (separate session)

1. First LPC proof: build the fitter that consumes `lpc_extract`'s pole list and authors
   4-corner d-space coefficients per the plan at
   `~/.claude/plans/read-this-then-rrad-kind-bumblebee.md`. Use the
   existing `StageRole` + `RolePolicy` vocabulary; do not invent a new
   role taxonomy. Tag Talking Hedz per the table above (4 FORMANT, 2
   PHASE_SCAR, RigidityClass.FLUID for stages 1 and 5). Verify by post-
   encode null vs `hedzm50q50.wav`, −60 dB gate. Body authoring
   populates four corners only; intermediate morph behaviour is produced
   by the runtime's bilinear-on-packed-u16 plus nonlinear minifloat
   decode — author endpoints, trust the trajectory.
2. Ear Bender grammar pass: extract and document Type 3 first, then Type 2,
   from `FUN_1802c6590` and related tables. Turn the findings into bounds,
   anchor/compression rules, and test vectors for the manufacturing
   pipeline. Do not re-open generic "find the authoring tool" Ghidra work.
3. If the joint fit clears the gate on Hedz, apply the same machinery to
   the four shipping bodies. If not, the ROM corners already null at
   −95 dB and stand as the calibration; Hedz reproduction is shelved
   and originals proceed on intent gates (preset_audit) rather than
   null gates.

### Prior handoff (2026-05-20) — retained for context

**HANDOFF (2026-05-20) — FilterP2k state-writer confirmed; ROM dump
comparison complete.** This does not change the runtime target, cascade
topology, interpolation order, or cartridge format. The useful discovery is
upstream: X3 has class-specific packed-state compilers/writers, but no
generic "frequency Hz -> packed word" inverse that replaces authoring and
fitting.

### Ghidra pivot result — FilterP2k

Confirmed in Ghidra: the `FilterP2k` virtual writer adjacent to the vtable
region around `0x1806d6150` is `FUN_1802d3ce0`.

`FUN_1802d3ce0` copies a precompiled 240-byte bank, not a MorphDesigner
descriptor:

```text
source = DAT_1806d762e + ((this+0x0c) + (this+0x18) * 4) * 0xf0
copy 6 stages x 4 corners x 5 u16 words
write A/B/C/D to object+0x2C0/+0x2FC/+0x338/+0x374
set active stage count object+0x420 = 6
```

So Talking Hedz/P2K does not go through `FUN_1802c6590` at refresh time.
The class-specific writer copies the packed corner bank; the normal refresh
chain then runs `FUN_1802c3d40` packed Morph/Q lerp and
`FUN_1802c3600` decode/recombine.

### CE dump compare — rerun

Command:

```text
python tools/rom_words_compare.py dev/tmp/cheat_engine_dump/skin13_corners_rom.bin
```

Latest report:
`dev/tmp/cheat_engine_dump/rom_words_compare_20260520_190842.md`.

Result:

| midpoint source | clean null vs X3 M50/Q50 |
|---|---:|
| derived-packed from 6-dp JSON | -53.75 dB |
| CE ROM dump words | -95.41 dB |

Interpretation: the audible target is unchanged. The ROM-word dump proves
that the packed bank path is bit-accurate for Talking Hedz M50/Q50. The
prior `-53.75 dB` derived-packed gap is from JSON precision / derived-word
loss, not from a hidden runtime trajectory, cube interpolation, or a
missing frequency-to-word inverse.

**HANDOFF (2026-05-20) — Forge fitter built; calibration partial.** Read
CLAUDE.md / SPEC.md / FRAME_BANK.md / BODIES.md / this file first. The
prior 2026-05-19 handoff that follows this section is retained for context;
its task (stand up the Forge) is done — the live state is here.

### THE LESSON — locked

**Independent per-corner fitting is invalid for morph bodies.** A
morphing body is not four separate filters. It is **one staged instrument
with four coordinated corners.** Stage *i* must be the same "actor"
(the same physical resonator role) in all four corners. The encoded
morph lerps u16 words stage-by-stage; if stage 1 in corner A is the "ooh
throat" and stage 1 in corner B is some unrelated upper resonance, the
midpoint blends nonsense. That is exactly why the first calibration run
produced 4 per-corner fits at machine precision *and* an M50/Q50 of
−0.69 dB. The fitter is fine; the body model was wrong.

Authoring discipline going forward: fit morphable **bodies**, not
filters. Per-corner authoring is a sub-step of body authoring, never the
whole job.

### NEXT-SESSION PRIMER (verbatim)

> Do not continue independent per-corner fitting. The next task is a
> joint coherent 4-corner Forge fit: one shared 6-stage layout, per-corner
> parameter variation within matched stage slots, verified after minifloat
> encode/decode through `PackedCorners::from_corner_data`. Treat Q100 wets
> as bad captures until recaptured; use ROM-decoded corner behavior as
> reference-only measurement, never copied data.

### Priority order

1. Joint coherent 4-corner Forge fit — one shared 6-stage layout, per-
   corner parameter variation within matched stage slots.
2. Post-quantisation verification: encode → `PackedCorners::from_corner_
   data` → packed morph-first interpolate → render → null. Do NOT judge
   the body on pre-encode response match; the gate is post-encode.
3. Use ROM-decoded corner responses as reference-only measurements until
   the Q100 wets are recaptured. Never copy ROM coefficients or words
   into authored output.
4. Recapture the 2 Q100 corner wets (`m0q1`, `m1q1`) with the Q knob
   verified static, no automation. Until then the current Q100 captures
   are not usable evidence.

### Forge fitter — built (2026-05-20)

New, Forge pipeline (no heritage_coeffs / designer_compile imports):
- `pyruntime/forge_fit.py` — Bark/ERB-weighted, **phase-aware** cascade
  fitter. Fits a target complex response with a 6-biquad cascade in
  d-space (the five minifloat-decode components per stage, box-bounded
  [0,1] so the authored corner survives encode→u16→decode). `perceptual_
  weight` has per-body profiles (vocal/sub/bright/broad). `fit_corner`
  does peak-picked + random restarts, complex residual, stability penalty.
- `tools/forge_hedz_calibration.py` — fits the 4 ROM-decoded corner
  responses, encodes, interpolates M50/Q50, nulls vs the X3 wet.
- `tools/forge_corner_fit.py` — fits each corner from its **measured X3
  wet** (exact-lag-aligned full-FFT transfer function H=Y/X). Pure
  behavioural measurement, no ROM data in the targets.

### What is proven
- The fitter reproduces a **clean** target to machine precision: −272 dB
  weighted response match; authored corners, post-encode, render identical
  to the ROM-decoded reference at −183 to −230 dB. As a per-corner
  authoring tool against clean targets, it works.

### What is NOT done — Talking Hedz is not recreated
1. **Independent per-corner fits do not morph.** A 12th-order response has
   many valid 6-biquad factorisations; fitting corners independently lands
   each on a different one. The morph lerps u16 words stage-by-stage, so
   mismatched stages give garbage: M50/Q50 from independently-fit corners
   nulled **−0.69 dB**. Fix needed: a *joint* fit, all 4 corners sharing
   one stage decomposition (stage i = the same resonator in every corner).
2. **The two Q100 corner wets are bad captures.** Of the 4 corner wets
   (`C:\Users\hooki\Downloads\hedz regions - m{0,1}q{0,1}.wav`): the two
   Q0 wets match the ROM corners **bit-accurately** (ROM kernel renders
   null −98.8 / −100.3 dB vs them). The two Q100 wets match **nothing** —
   −0.2 dB against every one of the 16 ROM-corner×wet pairings. They are
   non-static / non-LTI captures. Recapture Q100 with the Q knob verified
   static, no automation. (This is the STATE "Current focus" Q100 item,
   now confirmed with fresh wets.)
3. **Fitting against measured wets is currently unreliable.** Best result
   M0_Q0 = −40.3 dB render-vs-wet (structural agreement, short of the −60
   gate). M100_Q0 collapsed to −1 dB in the harness even though a
   standalone check shows −50 dB is reachable at the correct lag (3421) —
   the lag-refinement loop in `forge_corner_fit.py` diverges. The
   measurement front-end (sample-exact lag + low-variance H=Y/X estimate)
   is the bottleneck, not `forge_fit.py` itself.

### Measurement facts established
- `find_lag` (xcorr argmax) is offset from the true wet/dry lag by the
  filter's group delay (~8–12 samples). The TF needs a *sample-exact*
  lag — a 1-sample error multiplies H by z^k and makes it unfittable as a
  biquad cascade. True Q0 lags: m0q0 = 408, m1q0 = 3421.
- A coarse log grid cannot represent the corners' Q≈160–600 resonances;
  the fit must use the native FFT grid (decimated), not a resampled grid.

### NEXT — finish the Forge calibration
1. **Stabilise the measurement.** Decouple lag from the fit loop: get the
   exact lag once (render-null alignment against a rough model, or a clean
   causality test), then a low-variance TF (Welch-averaged H=Pxy/Pxx, or
   longer excitation). Target a measured-TF noise floor below −60 dB so a
   tight fit can reach the gate.
2. **Joint coherent fit.** Fit the 4 corners together with shared stage
   identity (sorted poles + corner-to-corner continuity regularisation) so
   the morph is coherent. For *original* bodies this is the whole job —
   the morph is *defined* by the corners. For the Talking Hedz fixture,
   reproducing the *specific* X3 M50/Q50 midpoint additionally needs the
   joint fit to match E-mu's realisation (the midpoint wet `hedzm50q50.wav`
   becomes a 5th joint target). NOTE: derived-packed (ROM's own realisation
   at 6-dp coefficient precision) only reaches −53.75 dB at the midpoint —
   the midpoint gate is extremely sensitive and may need near-bit-exact
   corner words.
3. Recapture the 2 Q100 corner wets static, or fall back to ROM-decoded
   Q100 responses as the reference (FRAME_BANK Clean Room authorises this).

### Prior handoff (2026-05-19) — retained for context

### What this session settled
- The Rust `Cascade` reproduces the Python `scipy.sosfilt` ROM-word
  reference **bit-identically** (0/307386 samples differ; −95.41 dB vs X3).
  The runtime cascade is trusted. See "Rust cascade parity — VERIFIED
  bit-accurate" above. New: `trench-core/tests/rust_cascade_parity.rs`,
  `tools/rust_cascade_parity.py`, `PackedCorners::from_rom_bytes`.
- The musical morph is the **encoded-domain interpolation**: encode corner
  floats → u16 words → morph-first u16 lerp → nonlinear decode. df2's
  default `cartridge.rs::interpolate()` does decoded-float c-domain
  bilinear (the crossfade) — 9-15 dB off the true midpoint
  (`tools/morph_interp_demo.py`).
- Tyson auditioned `dev/tmp/morph_sweep_audition/` (Q=0 morph row): moves
  through distinct vowels (broadband → ooh → ooh+aaa → eee), no smear.
  Encoded interpolation confirmed by ear. Tool:
  `trench-core/tests/morph_sweep_audition.rs` (morph {0,.12,.25,.5,.75,1} ×
  Q {0,1}). `m050_q100` peaks 1.18 (stable, tall high-Q resonance); the
  Q=1 row is NOT null-checked (no Q100 hardware capture in repo).

### NEXT TASK (fresh context): stand up the Bark/ERB-weighted Forge fitter

Goal (Tyson, clarified 2026-05-19): author **original iconic skins** — not
replay or recompile E-mu's. Method: perceptual ARMA fitting — fit a target
response into the 6-biquad cascade's coefficient space with the error
weighted by critical band (Bark for mids, ERB for lows; emphasis shifted
per body). This is "Filter Factory's frame fitter" from CLAUDE.md's
runtime/authoring design decision. It lives in the Forge pipeline
(`pyruntime/` — `target.py`, `stage_math.py`, `analysis.py`, `forge_*`),
never the heritage Compiler.

**Calibration fixture — remake Talking Hedz the Clean Room way.** Before
trusting the fitter on originals, prove it: measure the X3 Talking Hedz
*behavior* and author original corners (own coefficients — NOT E-mu's
params or ROM words) that null against it. Coefficients differ, behavior
matches — the Clean Room rule. Run through the encoded interpolation +
`Cascade`, null vs the X3 wet `C:\Users\hooki\Downloads\hedzm50q50.wav` at
M50/Q50; target the −60 dB gate. This is the pipeline-status item "first
df2 body authored: Talking Hedz match (calibration fixture) → thrown away →
pipeline trusted."

Notes for the fresh context:
- Bark/ERB is perceptual weighting of *hearing*, NOT a vocal-only scale —
  it tells the fit where the 6 biquads' limited resolution should go. Per
  body: Small Talk → Bark mids; Speaker Knockerz → ERB lows; Aluminum
  Siding → high-band; Cul-De-Sac → broadband. Same family, emphasis moves.
- The fitter must eventually cover all 3 heritage filter shapes — Type 1
  peaking, Type 2 shelf, Type 3 vocal. Talking Hedz exercises the vocal
  shape; shelf/peaking fixtures come later.
- Corner-level behavioral targets: the M50/Q50 wet is on disk; the 4
  *corner* X3 wets are not (ask Tyson). Until then the ROM-decoded corner
  responses (`dev/tmp/cheat_engine_dump/skin13_corners_rom.bin`) may serve
  as the measurement reference — reference-only, Clean Room: measure the
  envelope, author fresh coefficients, never copy.
- Compile-from-P2K-parameters (heritage Compiler, `designer_compile.py`
  type1/2/3) is **metrology only** — it can produce reference targets for
  the Forge to fit, but its output is E-mu-derived data, not a shippable
  remake. Type 1 compiler is bit-exact; Type 2/3 branches untested — verify
  only if used as a metrology source.

### Queued: execute the morph interpolation reconciliation
DECISION: GO (Tyson, 2026-05-19). A focused, self-contained runtime task —
independent of the Forge work above; do it when picked up. Scope:
- `cartridge.rs::interpolate()` — replace decoded-float bilinear with
  encode → morph-first u16 lerp → decode. Corners are biquad-form; needs
  biquad↔kernel conversion around `PackedCorners` (kernel↔biquad helpers
  are in `rust_cascade_parity.rs` / `morph_sweep_audition.rs`). Encode the
  4 corners once at `Cartridge` construction; store a `PackedCorners`.
- Un-gate `minifloat` in `lib.rs` (drop `#[cfg(feature="packed_interp")]`)
  — it becomes core runtime.
- SPEC.md "Interpolation" section + hard-ban line → morph-first/
  encoded-domain. This is the ONE authorized SPEC change.
- Cartridge format UNCHANGED (`compiled-v1` keeps float corners; runtime
  derives words at load). The −53.75 dB derived-packed gap is a
  heritage-reproduction artifact (JSON 6-dp vs ROM words); for original
  bodies the body's sound is *defined* by encode→lerp→decode of its corners.
- Test fallout: `runtime_morph_q_audit.rs`, `cartridge_schema_tests.rs`,
  `render_diff_harness.rs`, any test asserting `interpolate()` output.
  `packed_interp_ab_render.rs` is obsolete (packed-vs-float A/B, question
  answered) — remove it.

### Watch-outs (contamination — memory `df2-contamination-vigilance`)
Pasted AI messages this session reintroduced rejected hypotheses. Verified
facts: morph interp = linear u16 bilinear lerp + nonlinear decode (NOT log,
NOT perceptual). ARMAdillo = a separate temporal glide, NOT the morph path.
There is NO "Cube" — the Morpheus 8-corner cube is rejected; df2 is a flat
4-corner grid. The cascade is 12 stages (6 active + 6 passthrough), 12th
order — not 14. Runtime flushes non-finite values; it has NO AGC (SPEC).

### Do NOT
Touch cascade topology; change the cartridge format; modernize runtime DSP.
Amending the SPEC *interpolation clause* IS authorized (decision above) —
only that clause, only toward verified heritage behavior. Commercial /
patent decisions wait for an attorney.

### Also deferred (Tyson's call when reached)
- Audition the −53.75 dB derived-packed path vs the −95 dB ROM-word path.
- Corner-wet re-null with the corrected lag (`x3[n] ↔ cand[n-lag]`); needs
  the 4 corner X3 wet files — ask Tyson if on disk.
- M/Q-surface breadth (needs new X3 captures). Glyph12 v0 (separate branch).

Latest session log: `SESSION_LOG/2026-05-19.md`.

---

## HANDOFF (2026-05-20 evening) — vocabulary lock-in; next task unchanged

Late session with Tyson clarifying product framing and naming hygiene. **No
code shipped this block — the next-session task remains the joint coherent
4-corner Forge fit documented above.** What changed is the framing around
it, plus four product decisions that affect future blocks.

The session re-discovered things STATE.md already had documented (role
machinery, role-blind fitter gap, "stages as actors" framing from the ROM
stage-layout audit). Recording the re-discoveries here so they aren't
re-invented again next time.

### ARMAdillo vs ARMA — naming hygiene

These are different stages of the pipeline, easy to conflate:

- **ARMAdillo** = the trajectory *between* corners. Packed u16 minifloat
  morph-first bilinear interpolation in the runtime. Already verified
  bit-accurate at −95.41 dB on Talking Hedz M50/Q50 with ROM words. Frozen
  (the morph-interpolation reconciliation in `cartridge.rs` is the one
  authorised SPEC change — see "Queued" block above).
- **ARMA** = the per-corner extraction. Pole+zero fitting of measured
  responses, authoring side. This is what `pyruntime/forge_fit.py` already
  does — Bark/ERB-weighted phase-aware least-squares in d-space (the five
  minifloat-decode components per stage). Not the all-pole LPC of
  `tools/lpc_extract.py`; the kernel form `[c0..c4]` carries numerator
  structure and `forge_fit.cascade_response` evaluates both.

The kernel form was always ARMA-shaped (c0/c1/c2 numerator = zeros,
c3/c4 denominator = poles). The fitter optimises both halves jointly. No
new extractor needs building for ARMA capability — the role-blind gap and
the measurement-frontend lag/TF noise floor (lines 1004–1010 above) are
the real next problems.

### Stages as actors — confirmed, not new

The ROM stage-layout audit table (lines 713–720 above) already shows
stages 0/2/3/4 hold stable frequency bands while stages 1 and 5 cross in
frequency across the M axis (1 kHz → 220 Hz vs 200 Hz → 2 kHz). That is
formant migration *inside* a fixed stage identity — exactly the
"actor stays the actor; the band the actor covers migrates" framing. The
banded-slots fitter was correctly falsified before code; the role-bounded
fitter is the documented next step.

Cross-corner consistency is automatic under this framing: stage *i* has
the same `RolePolicy.role` in all four corners (`FORMANT` is `FORMANT`
across the body). Bilinear interp moves the actor's frequency without
crossing actor identities.

### Body-specific labels (Tyson's vocabulary)

User-facing names that ride on the existing `StageRole` taxonomy. The
existing machinery — `pyruntime/stage_roles.py::StageRole`,
`pyruntime/preset_schema.py::RolePolicy` (`role` + `rigidity` + `bounds`
+ `interpolation` + `note`) — is the authoritative slot system. The
labels below go into `RolePolicy.note` per stage; the typed `role`
field stays a member of the StageRole enum.

**Talking Hedz** (calibration fixture; tagging matches the ROM audit
above)

| stage | StageRole | rigidity | label (note) |
|---|---|---|---|
| 0 | PHASE_SCAR | RIGID | top edge |
| 1 | FORMANT | FLUID | F1 |
| 2 | FORMANT | RIGID | low-upper |
| 3 | FORMANT | RIGID | upper |
| 4 | PHASE_SCAR | RIGID | high-air |
| 5 | FORMANT | FLUID | F2 |

**Small Talk** (shipping body, vocal cavity profile)

| stage | StageRole | rigidity | label |
|---|---|---|---|
| 0 | PHASE_SCAR | RIGID | Air/Lip |
| 1 | FORMANT | FLUID | Throat |
| 2 | FORMANT | RIGID | Formant A |
| 3 | FORMANT | RIGID | Formant B |
| 4 | ANTI_FORMANT | RIGID | Bite |
| 5 | SHELF | RIGID | Chest/Tilt |

**Speaker Knockerz** (shipping body, sub-pressure / cone profile)

| stage | StageRole | rigidity | label |
|---|---|---|---|
| 0 | SHELF | RIGID | Root |
| 1 | FORMANT | FLUID | Cone |
| 2 | FORMANT | RIGID | Box |
| 3 | ANTI_FORMANT | RIGID | Tear |
| 4 | PHASE_SCAR | RIGID | Edge |
| 5 | PHASE_SCAR | FLUID | Rip |

Aluminum Siding and Cul-De-Sac labels to be authored when their bodies
are fit. The StageRole assignments above are first-draft and subject to
revision against the actual fits.

Storage: per-body `RolePolicy` files (or a single `PresetSchema` per
body). Path TBD; the existing `pyruntime/recipes/slammed_dark_bright_belch.py`
is the precedent — see lines 740–751 above.

### df2 player gets a sample import slot

Product decision. Player UI gains a sample import: drag in a one-shot
(808, vocal stab, drum hit), the plugin triggers it on note-on (or a
transport-synced trigger) and runs it through the active cartridge's
morphing filter cascade. v1 scope: single mono sample slot, simple
one-shot triggering, no looping, no pitch tracking beyond root-note
transposition.

Open: whether the player also accepts host audio input (parallel path)
or only triggers the imported sample. Default assumption: both, mixed
or switchable. Pin this down when the JUCE shell session opens.

### −53 dB / −95 dB — honest framing

For future reference and to head off the recurring "drop the −53 dB"
temptation: the −95 dB null uses ROM packed words directly; the −53 dB
null is *derived-packed* (float coefficients round-tripped through the
encoding chain). The frozen cartridge format (`compiled-v1`) stores
float coefficients per keyframe and re-packs at load — that round-trip
is the dominant precision floor on derived bodies, not the LPC-vs-ARMA
distinction. For four destruction-machine bodies aimed at beat
producers, the floor is below where the bodies operate; the loss is
likely inaudible in practice. The 42 dB gap is the *cost* of the frozen
format; the format stays frozen for v1.

### Document set status

- **STATE.md** (this file) is a work log. Append new session blocks; do
  not rewrite historical sections.
- **SPEC.md / CLAUDE.md / BODIES.md** are frozen except for the
  morph-interpolation amendment authorised in the "Queued" block above.
- **FRAME_BANK.md** describes a Clean-Room-only pipeline ("Forge-generated
  bodies are flawed; the path forward is measured P2K + Clean Room
  re-author") and a different pipeline diagram (`extract_frames` →
  `frame_catalog` → `body_assemble` → `compile_raw`). Tyson's
  2026-05-20 direction keeps the Forge factory as the v1 ship path.
  FRAME_BANK.md needs a follow-up rewrite; until then treat its Clean
  Room sourcing notes as still useful reference for P2K/heritage
  material, and its pipeline diagram as deprecated.
- **pyruntime/CLAUDE.md** documents the FORGE / COMPILER boundary;
  authoritative for that subtree.

### Next-session task — unchanged

1. Wire `pyruntime/forge_fit.py::fit_corner` to consume `RolePolicy.bounds`
   as per-stage box constraints (the small reversible step from lines
   734–750 above). `fit_corner` currently takes a perceptual `profile`
   name and an optional `weight` array — both are global. Per-stage
   bounds need to be added either as a stability-style residual penalty
   keyed on derived `(freq, radius, gain)` per stage, or as a constrained
   optimisation over the d-space subset that maps inside each stage's
   `RoleBounds`. Penalty is the lighter change.
2. Author the three `RolePolicy` / `PresetSchema` files (Talking Hedz,
   Small Talk, Speaker Knockerz) per the tables above.
3. Joint coherent 4-corner fit on Talking Hedz with the role-bounded
   fitter. Shared 6-stage layout, per-corner parameter variation within
   matched stage slots. Targets: ROM-decoded corner responses
   (reference-only per FRAME_BANK Clean Room) + the M50/Q50 midpoint
   wet as a 5th joint target.
4. Post-encode null gate via `PackedCorners::from_corner_data`. Pass =
   ≤ −60 dB at corners + midpoint. Audition.

The independent-per-corner failure mode (lines 921–935 "THE LESSON —
locked") is the failure to avoid. Each step verifies the previous.

### Addendum (2026-05-20 evening, later) — universal vocabulary + product framing

> **Words name the roles. Packed words play the roles. Four corners make the body.** (Tyson, 2026-05-20)

The architecture in 13 words. Authoring-side labels (Words) drive the
Forge fit; runtime-side packed u16 (Packed words) drives the cascade;
the body is defined by exactly four authored corner points and the
bilinear interpolation surface between them.

Three clarifications from Tyson after the block above was written.

**Universal Forge stage vocabulary** — supersedes the per-body label
drafts in the tables above:

| stage | label | semantic role |
|---|---|---|
| 0 | Root | bedrock / foundation / sub anchor |
| 1 | Body | low mass / midrange weight |
| 2 | Mouth | formant / vocal-like resonance |
| 3 | Scar | anti-resonance / notch / cut |
| 4 | Edge | high-mid sharpness / bite |
| 5 | Rip | ultra-high / shatter / break |

Same six labels for every body. Frequency band per stage differs per
body — Small Talk's Mouth ~1.5–2 kHz, Speaker Knockerz's Mouth maybe
~200–500 Hz, etc. The Forge fits each body's coefficients to satisfy
its label/band assignment.

**"Words name the roles. Packed words play the roles."** Labels are
authoring-side only — they live in `RolePolicy.note` and in Forge's
fit logic, never in the runtime. The runtime decodes packed u16,
lerps morph-first, reconstructs kernel, renders. Zero role awareness.
Musicality is baked at authoring time by (a) four good corners, (b)
each stage carrying the same label/role across all four, (c) the
nonlinear minifloat decode making in-between coefficient paths
characterful.

**df2 ships as two plugins, not three:**

1. df2 player — consumer (load cartridge, morph/Q, sample import slot).
2. df2 forge — mixer-channel capture-and-author. Snapshots the upstream
   signal chain's filter response, ships to the backend, gets a
   cartridge back. Four chain-state snapshots → joint-fit → one cartridge.

`pyruntime/` FastAPI is the engine *behind* the forge plugin, not a
separate plugin. Earlier framing as "three plugins (player + snapshot +
forge backend)" was wrong.

### Code shipped 2026-05-20 evening

- `pyruntime/forge_joint.py` (NEW) — joint coherent 4-corner fitter.
  Sibling to `forge_fit.py`. Per-stage `StageBand` bounds via residual
  penalty; per-corner pole-frequency seeds; one shared 6-stage layout
  across the 4 corners. Anchors stage identity by initialization (seeds)
  and during the fit (bounds). Replaces the independent per-corner
  pattern that failed at −0.69 dB.
- `tools/forge_hedz_joint_calibration.py` (NEW) — calibration CLI.
  Reads ROM-decoded corner responses (reference-only), runs
  `joint_fit_corners` with Talking Hedz `HEDZ_BANDS` + per-corner
  `HEDZ_SEEDS` derived from the ROM stage-layout audit table,
  encodes, interpolates morph-first at M50/Q50, renders, nulls against
  `hedzm50q50.wav`. **Not yet run.** Ready for the next session to invoke.

### Open for next session

1. Run `python tools/forge_hedz_joint_calibration.py --restarts 12`.
   Read the M50/Q50 number. Pass = ≤ −60 dB; failure tree in the script's
   `## Verdict` section.
2. If pass: author original bodies (Small Talk, Speaker Knockerz, etc.)
   via the same joint-fit machinery. Each needs its own `StageBand` list
   + per-corner seed positions derived from captured/measured material.
3. If fail: triage per the four-branch failure tree (stage anchors /
   joint constraints / optimizer factorization / Hedz precision floor).
4. df2 forge plugin (the mixer-channel capture-and-author) is a separate
   JUCE workstream — not blocking the calibration test.
5. Sample import slot on df2 player is a separate JUCE workstream.

### Addendum (2026-05-21 evening) — Prony / Steiglitz-McBride IR pipeline

Pivot away from broadband + Welch CSD + iterative ARMA fit. New
shipping path is a direct closed-form translation from impulse response
samples to packed cartridge:

  dirac.wav --[chain @ corner i]--> wet_i.wav
  wet_i.wav --[align + trim]--> h_i (the impulse response)
  h_i --[Steiglitz-McBride, p=q=12, 8 iter]--> (b, a) polynomials
  --[stabilize, tf2sos, geometric gain redistribute]--> 6 biquads
  --[kernel_to_words]--> 6 stages × 5 u16 words × 4 corners = 240 bytes

Rationale: ARMA fit on Welch CSD smeared transient resonances (steady-
state spectral estimation kills phase coherence and sharp peaks).
Prony fits time-domain IR samples directly, preserving the impulse-
domain peak by construction. Steiglitz-McBride iterates Prony to
handle the ill-conditioned linear system that pure Prony hits on
high-Q (near-unit-circle) poles.

Code shipped tonight:
- `tools/make_dirac.py` — emit a clean dirac WAV (single 1.0 sample,
  zeros after). Run through the mixer chain at each M/Q corner state
  to produce the four wet IRs.
- `tools/capture_ir_to_cartridge.py` — Prony or Steiglitz-McBride
  fit (`--method stmcb` default, `--method prony` for diagnostic).
  Stabilizes the AR polynomial (reflects |z|>1 roots inside),
  factors via `scipy.signal.tf2sos` with nearest-zero pairing,
  redistributes per-stage gain geometrically (every stage's c4 lands
  at G^(1/6) instead of one stage carrying the whole cascade gain),
  encodes to u16, writes a `compiled-v1` cartridge. Stage identity
  across corners is the per-corner ascending-pole-frequency ordering
  (each corner sorted independently; matching ranks become the
  "actor" pairs across corners — works when actors don't cross in
  frequency; corner endpoints correct regardless).

Synthetic 4-corner verification (`dev/tmp/capture_ir_pipeline_test/`):
- Raw IR null vs captured wet at each corner: −38 to −53 dB across
  the four corners (M0_Q0 -38.3, M100_Q0 -43.4, M0_Q100 -38.2,
  M100_Q100 -53.4 dB).
- Packed (u16 round-trip) IR null: −14 to −53 dB. The packing loss
  varies with the corner's pole Q (sharp poles have c3=1-r² near
  zero where the minifloat resolution is coarse). This is the same
  cartridge-format precision floor documented at lines 1249-1260
  for derived-packed bodies, and is below where destruction-machine
  bodies operate.

What was rejected and why:
- Log sine sweep + Farina deconvolution: cleaner SNR than dirac for
  noisy/dynamic chains, but for clean LTI plugin chains the dirac
  is exact. Sweep stays available for future captures with noise;
  for now the dirac path is simpler and bit-exact.
- Iterative ARMA fitter (`pyruntime/forge_joint.py`) with Welch CSD
  front-end: superseded for IR captures. Stays for measurements
  where only program material exists (no clean dirac/sweep).

Verified the output cartridge loads through the Rust core
(`Cartridge::from_json` → 4 corners, finite M50/Q50 interpolation,
distinct corners) and that `tools/player.html` handles the 6-real +
6-passthrough stage layout (it counts active stages by walking until a
passthrough; Rust takes `.take(NUM_STAGES=6)`). The 12-stage write
matches the existing Forge-authored bodies; ROM reference uses bare 6;
both load. Audition path (Task 3) is unblocked end-to-end.

Added a morph-trajectory audit to `capture_ir_to_cartridge.py`
(runs on the canonical packed u16 morph-first path, not float bilinear).
Three independently-validated metrics, each labeled by the failure mode
it catches:
- **Per-stage pole-frequency migration** across the 4 corners. A
  pole-identity swap (a stage slot holding different physical
  resonances at different corners) shows as a >20× migration ratio.
  Validated: injecting a stage-1↔stage-4 swap in one corner flags
  exactly stages 1 and 4 at 160× vs the clean 8.5× baseline. NOTE: a
  swap produces a *continuous* u16-lerp trajectory (the pole sweeps
  smoothly across the spectrum), so the discontinuity metric below
  does NOT catch swaps — the migration table is the swap detector.
- **Center gain sag**: broadband energy at M50/Q50 vs the corner mean.
  Flags <−6 dB (the "hole in the middle" Tyson flagged in the flight
  check — a resonance canceling mid-morph).
- **Discontinuity sweep**: spectral L2 step between consecutive M points
  along the Q0/Q1 edges. Catches genuine step jumps (ratio >4× median).

Open for next session:
1. Tyson does a real DAW capture: bounce
   `tools/make_dirac.py --out captures/dirac.wav` through a mixer
   chain at four M/Q states (e.g., Speaker Knockerz: 808 sub bus +
   tube saturation + tone-control plugin at the four positions).
2. Run `python tools/capture_ir_to_cartridge.py --name "..." --dry
   captures/dirac.wav --wet-m0-q0 ... [etc]`. Read the per-corner
   null and packed-null numbers. Expected: −30 to −50 dB raw at
   each corner; packed loss depends on the chain's pole Q content.
3. Drop the cartridge into `tools/player.html` (and eventually the
   JUCE player) and audition the morph across the M/Q surface.
4. df2 forge plugin (the mixer-channel JUCE wrap that subprocesses
   into `capture_ir_to_cartridge.py`) and df2 player sample-import
   slot are JUCE workstreams — not blocking the audition test.

---

## Session note (2026-05-21) — UI abstraction second opinion

No runtime, cartridge, topology, or authoring-pipeline code changed.

Tyson clarified that choosing the four musical corners is not the hard
part: he can pick the states directly ("Ah to Ee", etc.). The UI problem
should therefore be framed around preserving actor identity, auditing the
in-between morph surface, and making the result recordable/auditionable,
not around helping the tool choose the four endpoints.

Second-opinion direction:
- First surface: browser-based capture/audition dashboard with a large
  recordable z-plane view, morph/Q scrub pad, response overlay, and
  actor/role trajectory diagnostics.
- Direct pole/zero editing is valuable as a camera/debug view, but should
  not be the first authoring primitive for body creation. The first
  authoring primitive is "capture or select four corners, then verify
  the morph."
- Resonance/role handles are the practical edit surface: Root, Body,
  Mouth, Scar, Edge, Rip. Z-plane points remain visible so the truth is
  never hidden.
- Browser/WebGPU or WebGL is the right first visual stack for content and
  iteration. Native Rust/wgpu belongs later if the forge/player workflow
  needs a packaged app or DAW-facing surface.
- Stability should be hard-constrained for poles and audited for gain,
  center sag, excessive migration, and discontinuities.

---

## Session note (2026-05-21) — browser morph-audition tool + architecture pivot

Code changed: `tools/morph_audition.html` (new). `tools/player.html`
left untouched. No runtime / cartridge / topology / Rust / JUCE code
changed.

**Built `tools/morph_audition.html`** — first browser morph-audition
surface. Hero z-plane canvas (poles ✕, zeros ○, per-actor trajectory
trails, eased live M/Q marker), response curve, M/Q pad, four-corner
readouts, six named-actor lanes (Root/Body/Mouth/Scar/Edge/Rip), and a
live audit panel (unstable pole ≥1, actor-swap migration >20×, center
sag >6 dB, morph-edge discontinuity >4×, output peak >0.95).

Fixed the audition oracle to be runtime-faithful:
- MORPH-FIRST packed-u16 interp (A=M0_Q0, B=M100_Q0, C=M0_Q100,
  D=M100_Q100; edge0=lerp(A,B,m), edge1=lerp(C,D,m), out=lerp(e0,e1,q)).
  player.html was Q-first.
- lerpU16 now int16-WRAPS (matches minifloat.rs / coefficient_field_
  bakeoff.py); player.html clamped.
- c4 packs as encode(c4/4), unpacks as 4·decode (the COMBINE_K scale
  player.html dropped).
- Verified vs Python: corner recovery within minifloat grid (~1e-4);
  300k random lerp cases match the numpy reference exactly.

Replaced the click-prone audio path. player.html rebuilt 6 IIRFilterNodes
on every pad move → reset each high-Q resonator's state → continuous
click storm ("playing destroys it"). New engine is a single AudioWorklet
cascade that holds state and *ramps* coefficients (~6 ms) on M/Q change —
no node rebuild, no reset. It runs the cascade at the E-mu rate
(39062.5 Hz) for ALL bodies via linear resampling, so the host clock
(44.1/48 k) no longer warps the response. All frequency-domain math now
uses 39062.5 Hz. Validated offline: filtered gain matches the response
curve within 0.03 dB through 3 kHz (≈2 dB linear-resampler rolloff near
8 kHz), identity pitch test −0.03 dB, output tanh-limited + finite-guarded.

UI vocabulary: the 6 pieces are surfaced as named actors only — "stages"
and "slots" purged from the surface (a fixed abstracted budget, not
individually-designed filters; Tyson's framing).

**Architecture pivot — confirmed by Tyson (supersedes JUCE-frontend +
Python-backend forge):**
- The Forge (authoring) is a LOCAL WEB TOOL: HTML + WebGL (GPU-rendered
  z-plane / response / spectrogram), with the DSP engine AND the ARMA
  fitter compiled from Rust to WebAssembly. The ARMA solve runs in a
  background worker, never on the audio thread (a real-time ARMA solve
  would spike CPU and drop buffers).
- The shipping df2 plugin is a thin JUCE wrapper around the SAME Rust
  core (trench-core). One core, two frontends (Wasm Forge, JUCE plugin)
  → zero math-translation error.
- Python ARMA (`capture_ir_to_cartridge.py`: Prony + Steiglitz-McBride,
  already null-test-validated) becomes the REFERENCE to port into Rust,
  not the shipping engine.
- GPU/WebGL for the visual layer is mandatory.

Consequence: morph_audition.html reimplements the oracle/cascade in JS —
a validated throwaway. Under the confirmed path that JS DSP is replaced
by the Wasm core and the 2D canvas upgraded to WebGL. Because the JS
oracle was checked against minifloat.rs, the Rust/Wasm port has a
confirmed behavioral target.

Next step (recommended): port Prony/StMcB + tf2sos factorization +
minifloat pack into trench-core as `fit_corner(ir, sr) -> packed words`,
unit-tested against the Python output (same IR → same kernels within
tolerance / equal null depth). That one Rust function is the seam that
serves both the Wasm Forge and the JUCE shipping plugin.

---

## Session note (2026-05-21, later) — architecture LOCKED: Pure Rust standalone .exe

Supersedes the Wasm-split block immediately above. After evaluating a
third proposal, Tyson locked the Forge as a **standalone Rust .exe** —
no Wasm, no HTML/JS, no JUCE for the authoring tool:

- **Forge = standalone .exe** built with **eframe + egui** (GPU-rendered
  immediate-mode UI). It links `trench-core` directly (same process, no
  marshaling), so the audition shows the exact runtime oracle. The ARMA
  fitter is ported into Rust and runs off the audio thread.
- **nih-plug is NOT used for the Forge.** It is reserved for the eventual
  shipping df2 *player* (VST3/CLAP), which would reuse `trench-core` + the
  same egui UI. The Forge itself only needs to be a .exe.
- One Rust core (`trench-core`) underneath everything → zero
  math-translation boundary. This is why this path beats the Wasm split:
  the JS oracle in `morph_audition.html` needed 3 fixes to match
  minifloat.rs; a single Rust DSP removes that class of bug entirely.

Action started this session:
- New `forge/` crate (sibling to trench-core, path-dep, `packed_interp`
  feature; NO root workspace, so the existing juce-shell cargo build is
  untouched). `forge/src/main.rs` is an eframe app that loads a cartridge
  and draws the z-plane (poles ✕ / zeros ○, six named actors) from
  `Cartridge::from_json` → `PackedCorners::interpolate` — the real core.
- Build kicked off (`cargo build` in forge/). cpal audio and the
  capture→ARMA-fit→corner loop are the next two tasks.

`tools/morph_audition.html` remains a valid throwaway audition prototype;
its validated JS oracle behavior is the behavioral target the Rust path
already satisfies natively.

Latest session log: `SESSION_LOG/2026-05-21.md`.

---

## Session note (2026-05-22) — Forge upload-to-corner extraction loop

Tyson locked the standalone Rust Forge loop to "upload a transient, see
the response and residual, click a corner." The app now wires that loop
around the existing `trench_core::lpc::fit_corner` fitter instead of the
temporary mock result path.

- `forge/src/main.rs` now auto-detects upload onset, opens a Hann fit
  window (50–200 ms exposed by position/length sliders and draggable
  waveform markers), runs the existing six-actor Rust fit, reflects and
  clamps fitted pole radii into `[0.5, 0.9985]`, sorts stages by pole
  frequency, and re-normalizes the corner peak through `c4`.
- Forge synths an impulse response back from the fitted kernel and
  reports a gain-matched residual. Current UI gate: `≤ -24 dB` green,
  `>-24 dB` yellow review but assignable, `>-8 dB` or non-finite red and
  blocked.
- The fitted response, six pole/zero actor points, DF2T C++ arrays, and
  residual badge update live as the fit window moves.
- The first authoring loop is now **two anchors**: assign `LOW A`, assign
  `HIGH B`, drag the packed A→B morph preview, and audition that path on
  the existing Forge noise audition engine. The response plot overlays A,
  B, and the current packed preview.
- Runtime format stays four-corner. C/D assignment is now hidden under
  Advanced as the optional hidden axis; the primary preview duplicates
  A/B across that axis until those corners have a job.
- Capture conditioning remains tucked under Advanced: 16-bit
  zero-dither truncation and the internal fit/output rate. Core upload
  loading stays WAV/`hound` at this step.
- **UI correction:** the technical extraction instrument is not the
  product surface. Forge now opens as a dead-simple high-end body maker:
  two anchor tiles (`LOW SOUND`, `HIGH SOUND`), one living shape canvas,
  one Morph rail, `Play`, `Save`, and `Reset`.
- The app handles onset/fit/residual mechanics invisibly. Messy or failed
  fits open a plain slice picker; the residual number, z-plane, C++
  arrays, hidden corners, and rate controls live behind `Inspect`.
- `forge/Cargo.toml` adds `egui_plot` for plot viewports and `rfd` for
  the file-load button.

Latest session log: `SESSION_LOG/2026-05-22.md`.

---

## Session note (2026-05-21, night) — TRENCH Forge built end-to-end

`forge/` is now a working standalone authoring `.exe`. Capture → fit →
four-corner morph → audition → export, all native Rust.

- **Fitter** `trench-core/src/lpc.rs`: Levinson-Durbin LPC + Durand-Kerner
  rooting → poles; spectral-valley zeros → pole-zero biquads (the notches,
  not just peaks). Analysis 22.05 kHz / order 14 / ≤10 kHz so the air/RIP
  actor can fill. `normalize_corner_peak` now `pub`. Tests pass.
- **Model: four INDEPENDENT corners** (drop any sound on any corner). The
  2-endpoint+derived-cavity model was scrapped — it was the degenerate
  (Q-duplicated) tier; P2K bodies are 4 distinct 60-byte banks. The engine's
  bounded-u16 interpolation guarantees a stable, continuous morph between any
  four, so corners can be completely different (verified:
  `forge_cartridge_roundtrip` test — finite/stable across the surface).
- **DEPTH + WILD dials**: depth pushes poles+zeros toward the unit circle
  (gentle→Ear-Bender rails); wild reorders morph-end stages (cross-spectrum
  migration = the Ear-Bender tear). Ear Bender = depth + migration on the
  same 6-actor budget, NOT a fancier engine (confirmed from
  `ref/heritage/Ear_Bender.csv`: +78 dB poles, −68 dB notches, stages tear
  20 Hz→14 kHz across corners).
- **Audio** `forge/src/audio.rs`: cpal, multi-format (f32/i16/u16/i32),
  cascade at 39062.5 via linear resampling, ramped coeffs (click-free).
  NEEDS Tyson ear-check — built, not audibly verified here.
- **UI**: sound-space only (no z-plane/EMU/DSP). Hero = THE SHAPE + named
  actors + crude **aliased** stepped "reactor" live trace (egui feathering
  off). M/Q pad filled with morph terrain. SAVE writes compiled-v1 to
  `~/Documents/TRENCH/authoring_slot.json` (player hot-reload slot).

Open: **VST3 player**. juce-shell can't build here (no JUCE submodule / no
MSVC). Path = nih-plug (pure Rust); it processes the DAW's audio (no source
needed) and loads the slot the Forge writes. Attempted as a stretch this
session — see session log for outcome.

Latest session log: `SESSION_LOG/2026-05-21.md`.
