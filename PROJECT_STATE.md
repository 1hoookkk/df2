# PROJECT_STATE — df2 / TRENCH·FORGE authoritative state map

Single-source state for a fresh session that already knows the doctrine (CLAUDE.md / AGENTS.md). Every nontrivial claim is graded **OBSERVED / INFERRED / UNKNOWN / REJECTED**. Where a verification pass contradicts a mapper, the stale handoff, or memory, **the verification wins and is labeled.**

---

## 1. Orientation

df2 (product name **TRENCH**) is a destructive morphing-filter FX plugin (808s, bass, vocals, drums, bus) whose product sound is an **aggressive, moving, resonant 12th-order Z-plane filter driven through AGC → Mackie saturation → QSound**. A "body" is one filter *type*: **240 bytes = 4 corners × 6 second-order sections × 5 packed u16 minifloat words**, where 6 sections = 12 poles (each section a pole-pair + zero-pair). The current active task is **Law Author**: `small law source → six root-domain stages → packed .body240 → trench_core audit`. The doctrine ladder is unified, no contradictions: **Tyson's instruction > AGENTS.md > CLAUDE.md > live code/tests > fresh measurements** (CLAUDE.md line 5: AGENTS.md wins on conflict). (OBSERVED — confirmed across all doctrine files + git history; latest commit `9b77e26f Lock Law Author forge baseline`.)

---

## 2. The runtime object & engine

### 240-byte body (OBSERVED)
Layout = **corner-major, stage-major, little-endian u16**: 4 corners × 6 stages × 5 words × 2 bytes = 240 exactly. Corner order is **morph-first**: `C0=M0_Q0, C1=M100_Q0, C2=M0_Q100, C3=M100_Q100`. On-disk `.body240` files are raw 240 bytes and interchangeable with JSON `packedWords` cartridges (the 50 reference `.bin` variants are each exactly 240 bytes — OBSERVED).

### Minifloat codec (OBSERVED, bit-exact)
`trench-core/src/minifloat.rs` is the canonical encoder/decoder (E-MU/MSVC decompiled `FUN_1802c3d40`):
- `decode(u16)→f64`: `u=word+1`; `e=(u>>12)&0xF`, `m=u&0xFFF`; denormal `e==0 → m/4096·2^-15`, normal `(m+4096)/8192·2^(e-15)`. Maps `[0,65535]→[0.0,1.0]`.
- `encode(f64)→u16`: inverse, `encode(decode(w))==w` on the grid.
- `lerp_u16(a,b,frac)`: **integer i16-wrapping lerp, NOT float lerp** — `diff·frac` cast i32→i16 wrap, then add. This is the hardware interpolation and is why **morph-first vs Q-first differ**.

### Kernel & biquad transforms (OBSERVED)
- words→kernel: `c0=4·d0+d1, c1=d1, c2=4·d2+d3, c3=d3, c4=4·d4` (COMBINE_K=4.0).
- kernel→DF2T biquad: `b0=c4, b1=(c0-2)·c4, b2=(1-c1)·c4, a1=c2-2, a2=1-c3`.

### Morph-then-Q interpolation (OBSERVED)
`PackedCorners::interpolate(morph,q)`: per word, morph-lerp the two Q-edges first (`edge0=lerp(C0,C1,morph)`, `edge1=lerp(C2,C3,morph)`), then Q-lerp the edges (`lerp(edge0,edge1,q)`), then decode. Order matters because `lerp_u16` is nonlinear.

### DF2T cascade (OBSERVED)
`trench-core/src/cascade.rs`: 12 stages (6 active + 6 passthrough), per-sample coefficient ramping, difference equation `y=b0·x+w1; w1=b1·x−a1·y+w2; w2=b2·x−a2·y`. Matches Rossum reference to ±1e-12 dB (in-suite tests). Non-finite state flushes the stage and sets a sticky `unstable` flag. Pole radius from `[a1,a2]`: disc `a1²−4a2`; complex pair → `√a2`.

### Canonical owner + FFI surface (OBSERVED)
**One owner: trench-core (Rust).** `ffi.rs` exposes stateless `trench_packed_decode/encode/interpolate/probe` and stateful `trench_engine_create/prepare/load_body_bytes/load_cartridge/process_block`. `engine.rs` wraps dual cascades + AGC + Mackie desk slam (pre-cascade) + DC blocker (post) + QSound. Engine internal rate = **39062.5 Hz**. Raw-bytes audition routes through the *same* `Cartridge::from_body_bytes → PackedCorners` path as JSON — no separate DSP path.

### Duplicate kernel copies & parity status (THE TABLE)
| Copy | Role | Parity vs trench-core | Verdict |
|---|---|---|---|
| `trench-core/src/minifloat.rs` + `cascade.rs` | **CANONICAL** | n/a (owner) | OBSERVED |
| `pyruntime/trench_ffi.py` | ctypes FFI delegation | bit-exact: decode 65536/65536, encode 250008 exact, interpolate `max|diff|=0.000e+00`, probe 0.000e+00 (`python -m pyruntime.ffi_parity`) | **OBSERVED — bit-identical** |
| `forge-web-wasm/src/lib.rs` → `forge_web_wasm.wasm` | WASM author/pack; same Rust trench-core recompiled to wasm32, plus `stage_biquad`/`biquad_to_words` pack helpers | **0.0140 dB worst corner** (M100_Q100), median ~0.010, threshold 0.5 — reproduced via `dev/tmp/emu_tensioning/parity_test.py` | **OBSERVED 0.0140 dB** |
| `forge-web/js/packed.js` | JS **plot-only** mirror (decodeWord/lerpU16/stageWordsToKernel/kernelToBiquad/wordsAt/packedDb) | claimed "0.0000 dB"; **algebraically identical** to minifloat.rs line-by-line (decode, COMBINE_K=4, kernelToBiquad), JS uses `Math.fround` to emulate Rust f32 | **see §5 — the dB number is unverified-by-execution (INFERRED); the algebraic identity is OBSERVED** |
| `pyruntime/packed_interp.py` | Python reference fallback; raises if Rust absent (refuses silent substitute) | delegates to FFI | OBSERVED |
| `Cartridge::interpolate_legacy_stages` | f64 bilinear for pre-packed JSON | never fires for shipping bodies | OBSERVED (dormant) |
| several `tools/*.py` (`coefficient_field_bakeoff.py:119`, `make_targets.py:31`, `x3_fixed_class_cleanroom.py:88`, `breed_corners.py:47`) | own `decode`/`lerp_u16` | **NOT FFI-delegated** — exploratory tools have private reimplementations | **REJECTED claim "all shipped tools delegate"** (these are exploratory, not on the law-author/scorer path) |

WASM binary is in sync with `lib.rs` (identical mtime 2026-06-07 20:11:38, both 309 KB, rebuilt after the `MAX_RADIUS=0.999999999999999` refactor). (OBSERVED)

---

## 3. The authoring method

**Poles are FIT, never invented; zeros are HAND-AUTHORED.** (OBSERVED across doctrine + tools.)

- **Pole sources:** LPC(12) of real audio (`tools/fit_sources_lpc.py` → `forge-web/data/sources.js`), vowel formants (Peterson-Barney, Klatt), measured Hz rails, physical models. Each pole traces to a real resonance.
- **Foundation + source split:** each fit gives 6 sections = **3 foundation** (fixed-Hz body anchors, held across morph, DC-pinned, low hi-Q lift so they stay weight-bearing) + **3 source actors** (morph-traveling poles `pf→pfB`, sharpening on Q). Foundation Hz seen in `sources.js` (270/513/972) and fitter (98/194/270/390/530) — both present; INFERRED these are two source variants, not a conflict.
- **DC-pin:** section gain `(1−2r·cosθ+r²)/(1−r²)` (a.k.a. `(1−r²)·gain` in the no-zero WASM branch) kills the +56 dB low-end mountain from stacked resonators. (OBSERVED in `lib.rs` `stage_biquad`.)
- **Zeros:** per-section conjugate pairs `(zero_hz, zero_depth)`, gain-normalized for unity DC. ALL-POLE (zero banished) is the rule for vowels; DC/Nyquist zeros REJECTED. Zeros are the authoring dimension dragged on the curve. (OBSERVED per forge-web/CLAUDE.md tested-this-session laws.)
- **Musical Q:** `Q≈1/(2(1−r))`; secondary scales both frames; hot corridor radius `[0.998, 0.9999]`.

### Scorer (OBSERVED — `src/utils/packed_runtime.py::evaluate_body`, imports cleanly)
Probes a Morph/Q grid + interior via `trench_ffi.packed_probe`. Objective:
```
0.32·endpoint_span_db + 0.28·center_span_db
+ 1.10·morph_contrast_rms_db + 0.85·secondary_contrast_rms_db
+ 3.5·(center_peaks + center_valleys)
+ 14.0·ceiling_occupancy_fraction + 7.0·median_zero_motion_octaves
```
**Gates** (`tools/forge_generate_corners.py`): stable & finite; `0.998 ≤ max_pole_radius < 0.9999`; `center_span_db > 74`; endpoint/morph/secondary contrasts `> 0.95×` the P2K-50 reference medians; `peaks ≥ 3 && valleys ≥ 3`; `median_zero_motion_octaves > 0.35`. Weights are **empirically tuned to the 50, not first-principles** (INFERRED — no calibration provenance in source).

### KEY FINDING (OBSERVED, substantiated)
**Pole-sets already BEAT the 50 on morph / scream / span; the only failing axis is ZEROS = hand-authored canyons (peaks/valleys/zero-motion).** Reference envelope (`reference_aggregate.json`, 12 bodies, metrics-only, every cited number matches file): endpoint_span 83.75 dB, center_span 108.60 dB, morph_contrast 24.81 dB, secondary_contrast 17.14 dB, center_peaks/valleys 3.5 median, max_pole_radius 0.99890.

---

## 4. The surfaces & how they connect

### forge-web studio (what it ACTUALLY is now)
`forge-web/studio.html` + `js/studio.js` (THE studio; `zedit.html` is the legacy surface) is a **curve-diamond authoring instrument**, not the lane-roller spec. (OBSERVED.)
- Left rail: source picker (10 LPC sources from `data/sources.js`). Center: Frame A/B tabs + live Bode canvas. Right: Morph×Q control + drive/source/play + RMS meter.
- Pack path: WASM `forge_pack_params()` writes 240 bytes; `packed.js` decodes them **plot-only**; no JS encode in the authoring path. (OBSERVED.)
- Audio: `forge-worklet.js` runs WASM `forge_engine_*` on the worklet thread at 39062.5 Hz (resampled to host), excitations saw/noise/808/voice, real AGC+Mackie+QSound, makeup gain, RMS metering.
- Live readouts: **only** a stability pill (`max r 0.xxxxxx` / `UNSTABLE`) + morph/Q numerics. No objective/gate/peaks/valleys display.
- SAVE: `studio.js:363-367` builds hex and `downloadText(... .body240)` — **local download only, never POSTs `/bake`.** (OBSERVED.)

### Python bake/score server (OBSERVED — `tools/forge_author_server.py`, port 8130)
Serves `forge-web/` static + one POST endpoint **`/bake`** (any other path → 404; **no `/score` endpoint exists**). `/bake` packs lanes via `stage_biquad → biquad_to_words → trench_ffi.encode` (Python mirror of `lib.rs`, parity 0.014 dB), audits via `trench_ffi.packed_probe` over a 17×17 grid (PASS if stable & max_r<1), and writes a session folder `dev/tmp/forge_visual_author/<slug>_<stamp>/` containing `law_source.json, fitted_lanes.json, body.body240, cartridge.json, audit.json, response.png, workbench.html`. Asserts `len(body)==240`. `law_author.py` is the CLI twin of this path.

### JUCE plugin player (OBSERVED)
`juce-shell/` — VST3 + Standalone, JUCE 8.0.13, links `trench_core.lib`, auto-installs to `C:\Program Files\Common Files\VST3\TRENCH.vst3`. Signal: host → `FixedRateTrenchIsland` (Lagrange SRC to 39062.5) → `TrenchDspBridge` → `trench_engine_process_block`. Params Body/Morph/Q/Slam/5D/Output via APVTS; Morph/Q raw 0..1 (no /100); AGC always on, drive `4.0+slam·4.0`; body switch is async on message thread with PL-3 safe-state bypass. **Authoring hot-reload:** 400 ms timer polls `~/Documents/TRENCH/authoring_slot.json` mtime and reloads the cartridge **only when the audition body is selected, and only in the diagnostics build** (shipping `timerCallback` returns early). PluginEditor.cpp/h are modified-not-committed: live packed-body magnitude curve (192-pt sweep 40 Hz–18 kHz) replacing the old hand-pinned trace, plus thumbwheel sprite + readouts. (OBSERVED — UI-only, not a DSP change.)

### End-to-end wiring
`law source / lanes → (WASM pack | Python pack, parity 0.014 dB) → 240-byte body → trench_core probe/audit → .body240 → JUCE player (or studio worklet) plays it identically.` The **studio→server hop is the broken link**: SAVE downloads instead of POSTing `/bake`.

---

## 5. VERIFIED STATE TABLE

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | `plot == engine` to **0.0000 dB** (packed.js vs engine) | **INFERRED (downgraded from OBSERVED)** | No runnable JS-vs-Rust harness exists (`forge-web/**/*test*` → none). The 0.0000 dB is a doc assertion (forge-web/CLAUDE.md:12, root CLAUDE.md:72) + screenshot match. **What IS OBSERVED:** packed.js is algebraically line-identical to minifloat.rs (decode, COMBINE_K=4, kernelToBiquad), so 0 dB is expected but not executed. |
| 2 | WASM pack == trench_core decode to **0.014 dB** | **OBSERVED** | `parity_test.py` reproduced: corners 0.0059/0.0072/0.0133/0.0140 dB, "PARITY OK". 0.0140 = worst corner, not median (~0.010). Mirror lives in `dev/tmp/` (scratch, not CI); encode half uses real `trench_ffi.encode`. |
| 3 | Python FFI is bit-identical to shipped Rust | **OBSERVED** | `python -m pyruntime.ffi_parity`: decode 65536/65536 exact, encode 250008 exact, interpolate `max|diff|=0.000e+00`, probe 0.000e+00, masks 4050/4050. "FFI parity: PASS". |
| 4 | `law_author.py` runs and emits all required artifacts | **OBSERVED** | `--preset hedz_like_anchor_canyons` → VERDICT PASS; emits law_source.json (192 B), .body240 (**exactly 240 B**), cartridge.json (9109 B), audit.json (PASS), plot_sheet.png (246 KB), + stages.json/packed-body-v1.json. 4 corners × 6 stages × 6 packedWords confirmed. |
| 5 | `src/utils/packed_runtime` importable; is THE scorer | **OBSERVED** | imports clean; exposes `evaluate_body, analyze_body, state_metrics, gate_failures, trench_ffi`. |
| 6 | SAVE → `/bake` wired | **REJECTED (still open)** | `studio.js:363-367` = `downloadText` only; no `fetch('/bake')`. Server `/bake` exists but is uncalled by the browser. |
| 7 | Live score / gates in UI | **REJECTED (not present)** | Only stability pill + morph/Q/max-r. Grep `objective|gate|evaluate|score|peaks|valleys` → no matches in studio.js. |
| 8 | Six role-lane / range-roller / 4-corner telemetry / waste-meter UX built | **REJECTED (not built)** | UX is curve-diamond drag + Morph×Q pad (pad hidden via CSS). Grep `roller|thumbwheel|waste|telemetry` → no matches. The handoff's lane spec is entirely absent. |
| 9 | `/score` endpoint on server | **REJECTED** | `do_POST` 404s anything != `/bake`; no `evaluate_body` in the server. |
| 10 | `reference_aggregate.json` numbers (24.8/17.1/83.7/108.6/3.5/0.9989) | **OBSERVED** | All match exactly; policy=aggregate_metrics_only, 12 bodies, no coefficients. |
| 11 | 50 P2K reference types on disk | **OBSERVED** | 50 `P2k_000..P2k_049` dirs, 4×240-byte `.bin` each; 50 `.bin` in `ref/presets/`. |
| 12 | The "33" reference count | **REJECTED** | No grouping of 33 exists. On-disk = 50 dirs, 48 lines in `study_best_of_best/exact_packed_bodies.jsonl`. Origin of "33" unknown/stale. |
| 13 | Authoring tables present | **OBSERVED, one exception** | Present: family_intents.json (8 families, Hz pins, "_schema: no EMU refs"), vowel_formants, klatt_1980_formants/bandwidths, q_radius_table (declared 512 / observed 45), tube_resonances, metallic_modes, p2k_vocal_law. **MISSING: `target_templates.json`** (cited in MEMORY but absent). |
| 14 | All shipped tools delegate to FFI (no Python minifloat reimpl) | **REJECTED (partial)** | law_author/scorer/server delegate, but `tools/{coefficient_field_bakeoff,make_targets,x3_fixed_class_cleanroom,breed_corners}.py` carry private decode/lerp. They are exploratory, off the canonical path. |
| 15 | `canonical_parity.rs` substantiates engine vs Python WAVs | **OBSERVED (but not runnable)** | The null test is `#[ignore]` — "requires absent old-repo canonical_audio corpus". Its −274..−303 dB nulls are comments, not produced. parity_test.py is the live proof. |
| 16 | JS syntax valid (studio/worklet/packed) | **OBSERVED** | `node --check` exit 0 ×3. |

---

## 6. THE REAL REMAINING WORK (priority order)

**Proven-open (all three are the FORGE_STUDIO_HANDOFF gaps, re-confirmed):**

1. **Wire SAVE → `/bake`** — `forge-web/js/studio.js:363-367`. Replace `downloadText` with `fetch('/bake', {POST, JSON: {name, foundation, lanes}})`; `state.sections[]` already has the lane shape (`{on,pf,pfB,pr,prHi,gain,zA,zB,role}`). Server side already done. (Highest leverage; smallest change.)

2. **Live score + gates in the studio** — `forge-web/js/studio.js` (UI) + need a scoring source. Either add a `/score` endpoint wrapping `evaluate_body` to `tools/forge_author_server.py`, or port the objective + gate thresholds to JS. Surface objective number + per-gate PASS/FAIL (esp. peaks/valleys/zero-motion, since those are the failing axis). This closes the feedback loop on the KEY FINDING.

3. **Six role-lane / telemetry / waste-meter UX** — `forge-web/js/studio.js` + `studio.html`. Replace curve-diamond drag with six pole-pair lanes (thumbwheels: pole-Hz travel, zero-Hz travel + depth, radius), a C0–C3 telemetry strip, and a waste meter flagging unauthored poles/zeros. Largest rebuild; lowest urgency vs the score loop.

**Hygiene (proven-open, blocks reproducibility):**

4. **Commit untracked load-bearing files** — `forge-web/studio.html`, `forge-web/js/studio.js`, `forge-web/data/sources.js`, `trench-core/tests/{audition_p2k_favourites,qsound_primary_fixture}.rs`, `tables/p2k_vocal_law.json`. `data/sources.js` untracked breaks the fit→author repro chain.

5. **Quarantine scratch** — 35+ `gpt55-pro-*` files, Gemini prompt, `run_*.ps1`, root `*.png` (violate .gitignore line 29), `df2_context.zip`, `train.log`, `forge/`, `forge-clean/` → `dev/tmp/` or delete.

**Uncertain (verify before acting):**

6. Promote `parity_test.py` and `ffi_parity` into `trench-core/tests/` / CI so the 0.014 / 0.000 dB parities are guarded, not one-off. (INFERRED valuable.)
7. Add an executable packed.js-vs-engine dB assertion so claim #1 becomes OBSERVED rather than INFERRED. (INFERRED valuable.)

---

## 7. How to work here (hard rules)

- **Clean-room:** study the 50 P2K types for grammar (section roles, peak vs shelf, Q behavior, remote-zero patterns); **never ship copied coefficients, packed words, names, tables, or trajectories.** Author from real sources (LPC, formants, physical models, Hz rails). The law-author chain (intents/tables → law source → compile → audit) never touches reference coefficients. (OBSERVED-hardened across CLAUDE.md/AGENTS.md/cleanroom prompt.)
- **Plot == engine is the judge:** lead with the magnitude plot; a body that looks wrong *is* wrong; ear confirms last. Author and plot the same coeffs the engine runs.
- **One owner per job:** packed math = trench-core only. Don't add an N+1th codec. WASM = recompiled trench-core; packed.js = plot-only mirror to police; Python = FFI delegation. Exploratory tools may have private math but are labeled and off the canonical path.
- **Momentum, no ceremony:** next move → inspect real code → smallest reversible change → run the test/plot/build → report what changed and what proved it. No new doctrine/abstraction layers when the issue is a missing plot, broken path, or stale build. Stop and surface.
- **Read intent, not literally:** Tyson gives vibes/direction; build toward the end-feel, surface only taste/product calls. Don't turn each sentence into a literal verified feature with ceremony.
- **Verify pasted AI claims** through the shipped engine before trusting; flag contamination, keep the kernel.
- **Work in place:** df2 is the one folder; don't spawn a "clean" copy.
- **Evidence grades** on every claim; never promote INFERRED/UNKNOWN to OBSERVED; directory presence ≠ provenance.

---

## 8. Open questions / UNKNOWNs worth resolving next

1. **"33" vs 50/48** — where does the 33 count come from? On-disk says 50 types / 48 best-of-best. (Likely a stale planned roster; confirm or kill.)
2. **`target_templates.json`** — cited in MEMORY's "the-method" note but absent from `tables/`. Consolidated into `family_intents.json`, or genuinely missing? (Affects FORGE_LAW_AUTHOR references.)
3. **Foundation Hz set** — `sources.js` uses 270/513/972; `fit_sources_lpc.py` uses 98/194/270/390/530. Which is current/canonical, or are they two intentional variants? (INFERRED variants; verify.)
4. **Objective weight provenance** — the seven weights (0.32…7.0) and gate thresholds are tuned to the 50 with no recorded calibration. Are they frozen/justified, or still provisional?
5. **`ceiling_occupancy_fraction`** — defined as cells with `max_pole_radius ≥ 0.998` / total. Confirm this is intentional reward (keep poles hot), not an accidental clamp.
6. **packed.js 0 dB** — no executable proof (only algebraic identity + screenshot). Worth a one-shot numeric harness to upgrade INFERRED → OBSERVED.
7. **`law_author.py` output path** — AGENTS.md implies a required trench_core audit path; the tool writes under `--out parent/law_name`. Confirm which is canonical for the session-folder contract.
8. **canonical_parity.rs** is `#[ignore]` (corpus absent) — should the old `canonical_audio` corpus be restored to make engine-WAV nulls runnable, or is parity_test.py sufficient forever?
