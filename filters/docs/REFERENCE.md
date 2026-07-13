# REFERENCE — measured facts, calibrations, paths

Hard numbers established this session. Everything here is OBSERVED (file/probe/decode)
unless tagged. Don't re-derive — and don't regress the gotchas.

## Baseline-Q calibration (Talking Hedz P2k_013, decoded @ 39062.5)
The reference for the **damped baseline** policy. Low-Q (Q0) corners:
```
C0 M0_Q0 / C1 M100_Q0 :  pole r 0.935–0.997,  bandwidth 38–830 Hz,  Q ~2–17
C2/C3 (Q100)          :  r 0.999+,  bw 8–46 Hz,  Q 24–836   <- razor only at the Q extreme
```
=> a musical authored frame sits at r≈0.95–0.99 (bw 100–660 Hz). The DVTD rails are
capped to **r≤0.990** to match. The rigid 3D-printed DVTD tracts fit at the unit
circle (max-Q) if unconstrained — that is the artifact the cap removes.

## Type-3 split-code freq compression (probe-pinned)
df2 `pyruntime/heritage_coeffs.py:190` (compiler) and ghidra
`ref/ghidra_extracts/morphdesigner_types.md:84`:
```
if freq_value > 0xDB(219) and gain_offset < 0:        # Type 3, families 0..1, w2 only
    freq_value = (((freq_value-220)*(gain_offset+32))>>5) + 220
```
- trigger packed_freq ≥ 118; **resonant Hz ≈ 7152 @ 39062.5** (8788 @ 48k).
- below trigger: identical. Above: emitted freq pulled toward 220 (deeper cut →
  harder pull; a full cut pins the top to the trigger freq).
- COMPILE-time only. `trench-core/src/hedz_rom.rs` (runtime) has no such code.
- Matters for any high-freq cut/notch lane authored as Type 3 (fricative zeros,
  distortion notches). df2 probe: `df2/dev/tmp/type3_compression/probe.py`.

## Runtime decode / AGC (verified, df2 trench-core)
- `lerp_u16` (minifloat.rs:89): `(diff*frac) as i32 as i16` then +a — i16-wraps, no
  clamp. Large endpoint deltas zipper mid-morph; coeff-space interp misses it.
- AGC (agc.rs:48): `idx = (agc_gain_state * |sample|) & 0xF`; table
  `[1.0001,1.0001,0.996,0.990,0.920,0.500,0.200,0.160,0.120×8]`, sqrt'd at higher SR.
  Drive-dependent ducking; this is "the character."
- SR-family freq: `freq_value=(scale*byte)>>7+base`, base[18,18,4,1] scale[220,220,200,177].
  Same byte → different Hz across families. 44.1k & 48k share table.
- **REJECTED**: per-lane gain↔freq coupling (the `shift` is global macro-position,
  default 0); padding sentinel colors (it decodes to flat +0.0002 dB unity).

## dvtd_rails.py knobs
```
SR_TARGET=39062.5  FIT 100–10000Hz  N 18p/14z  SK 5 iters
delay=IR-onset only   FLOOR_DB=-25   BASELINE_MAX_R=0.990 (tunable)
gate: floored formant-band(100–5000) RMS ≤ 6 dB = OK   (POOR = HF-ripple/notch residual, inspect plot)
output: out/dvtd_rails/{dvtd_rails_trench_runtime.json, contact_sheet.png, plots/, authoring_candidates.json}
also: research_48k/ (NOT runtime-native)
```
Result: 44 rails, ~11 clean / 33 elevated-but-formant-correct, ~5.8 non-min-phase
zeros/rail (the antiformant info P2K never had), 1 unstable pole flagged.

## Data
`data/vocal/dvtd/` = 44 measured VVTFs (Dresden Vocal Tract Dataset, Birkholz et al.,
figshare s/5b81026892f7b39b429e — 3D-printed tracts, magnitude+phase). 2 subjects ×
22 models (8 tense + 7 lax vowels, schwa, + l/f/s/ʃ/ç/x). 17.9 MB; the 1.1 GB zip is
deliberately not copied.

## Paths back to df2 (canonical — for authoring)
```
kernel   df2/pyruntime/heritage_coeffs.py, packed_interp.py  | df2/trench-core (Rust, FFI owner)
ROM 50   df2/bodies/rom/P2k_*.json
refs     df2/ref/ghidra_extracts/morphdesigner_types.md, runtime_hacks.md
type3    df2/dev/tmp/type3_compression/probe.py
```

## Storage layers — the "same" P2K filter exists in 4 representations (2026-07-03)
Never conflate them; name the layer in every claim.
```
1 HW firmware ROM   pointer tables -> COMPILED coeff tuple frames + sentinels @39062.5
                    (OBSERVED: df2/dev/tmp/rom_rip/*_deep_scan.json — Planet Phatt/Orbit).
                    No parametric source ships. bodies/rom ("rom-decoded"), ref/presets,
                    corridor + copy-risk refs all descend from THIS layer.
2 X3/MorphDesigner  the PARAMETRIC layer: 6-byte type records (type 1-3 ONLY, type 0
                    skipped) + vendor XML -> EmulatorX.dll compiler -> packed u16 words.
                    SR families 44.1/48/96/192k — host rates, not 39062.5.
                    Exposes Morph live + Q on some filters (Tyson, in-app).
3 p2k_skins         decoded per-stage {a1,r,val1..3} JSON (trenchwork_*); baked via
                    stage_to_kernel; XML compiler deliberately NOT involved.
4 df2/TRENCH canon  compiled-v1 240-byte packed words @39062.5 through trench_ffi.
```
Bites: type-0 active in ROM frames but unexpressible in X3 grammar => corpora NOT
interconvertible (heritage replay = separate job, banned from authoring). X3
"TalkingHedz" ≠ P2k_013 (partly explains the unresolved 2026-03 parity null in
trench_re_vault). Same freq byte ≠ same Hz across families. **X3 captures validate the
shared packed-runtime MATH (lerp legs, Q-axis motion), never hardware bytes** — the
right target: TRENCH ships the math + original bodies, no layer's bytes.

## Manual facts (Mo'Phatt pp.106-135, Morpheus pp.90-92 + ref section — primary sources)
- **Q was note-on-only on ALL E-mu hardware** (both manuals, verbatim). The Q-axis
  interior was never heard as a sweep, never QA'd as motion. X3 software exposes Morph
  live + Q on some filters => a measured Q-axis reference IS capturable. TRENCH live-Q =
  novel territory; fast-Q-sweep is THE §11.5 gate.
- Morpheus = 8-corner cubes (Morph × FreqTracking × Transform2); P2K flattened to 4.
  FreqTracking (whole-body transpose/key-track) survives as the global `shift` vestige —
  candidate free third macro (UNKNOWN if runtime exposes it live; one probe).
- Authored-intent corrections: MeatyGizmo "filter INVERTS at mid-Q"; DJAlkaline "Q SHIFTS
  ring frequency"; BassOMatic "Q goes to distortion at max"; EarBender = WAH class.
  Taxonomy LPF/HPF/BPF/EQ+/EQ-/VOW/PHA/FLG/REZ/WAH/DST/SFX; order column 02-12 =
  voice-count tradeoff. Morpheus ref section ≈200 per-filter prose move descriptions =
  legal move curriculum (behavior, zero bytes).
- Zeros census (all 50 ROMs, 2216 zeros via trench_ffi): 40% unit-circle notch, 36% gain
  shaping, 13% DC, 11% pole-paired EQ, **0.0% non-min-phase** (wells: 732 past r=1.02).
  P2K presets = hand-authored parametrics, machine-compiled; zeros structural by
  construction. The measured antiformants are material P2K never had.

## Source wells inventory (surface-forge/data/, ~5 GB)
Raw datasets stay at their canonical location (too big to vendor); tools + extracted
rails live HERE. Small wells vendored locally: DVTD vocal (17.9 MB), one SONICOM SOFA (2.7 MB).

| well | size | feeds filter | readiness |
|---|---|---|---|
| vocal/dvtd | 1.1G | Vowel/Morph | ✅ done — `out/dvtd_rails/` (44 rails) |
| hrtf/ (sonicom+4) | 1.1G | Bright multi-res (DJ Alkaline) | ✅ done — `out/hrtf_rails/` (48 dirs, 1 subject) |
| circuit/ (SPICE+WDF) | 24M | Fuzz/Distortion (FuzziFace) | ⚙️ needs SPICE/WDF sim → FRF |
| modal/ (neural resonator) | 108M | Q-bloom/Violent (Meaty/Lucifer) | ⚙️ run generator → FRF |
| simulators/k-wave | 246M | tube/cavity/drum | ⚙️ simulate → FRF |
| phononic/ (metamaterial) | 93M | exotic notch lattices | ⚙️ |
| aeroacoustic/ | 2.3G | wildcard spectra | ⚙️ |

The fitter is the general engine: anything yielding a complex FRF (measured SOFA,
SPICE sim, k-wave cavity, modal strike) → `fit_one`/`fit_model` → rails. Adding a
well = produce its FRFs + a thin front-end (see `hrtf_rails.py` as the template).

## HRTF rails (done) — `tools/hrtf_rails.py`, `out/hrtf_rails/`
SONICOM P0001 FreeFieldComp, 48 directions (12 az × 4 el, left ear), HRIR→rfft(pad
2048)→FRF, ITD removed via IR-onset (real, 0.5–1.3 ms, scales with azimuth),
band 200 Hz–16 kHz @ sr 39062.5. Result: **48/48 OK** (RMS 0.5–5.9 dB — HRTF is
smoother than the rigid tract), **598 non-min-phase zeros = real pinna notches** (the
material). nmp-many is correct here (HRTFs are genuinely non-minimum-phase), unlike
vowels where all-nmp was the delay bug.

## Shared fit core
`dvtd_rails.py` owns the SK fit math + `baseline_cap()`; `hrtf_rails.py` imports them
(no duplicate kernel). `baseline_cap` caps **resonant** poles only (hz>60) to
BASELINE_MAX_R and renorms by **median dB** across band — a near-DC structural pole
(HRTF low-freq rolloff, z≈1) must NOT be capped or the baseline collapses ~18 dB
(found + fixed on az000_el+30).
