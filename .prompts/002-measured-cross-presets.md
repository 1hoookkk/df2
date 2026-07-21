# Author new TRENCH bodies — the ROM stage logic, worn by measured sources

## The idea (one line)
Take the ROM's stage logic — **4 independently authored corners × 6 serial lanes, Q as its own authored scene** — and populate every corner from a **measured source**. The Morph axis crosses **two different measured objects**; the Q axis is a **second authored scene** of the same objects (damped → resonant). Real recorded objects wearing the E-mu authoring anatomy.

## What to deliver
6–10 new bodies like the shipped heroes (Acid Vox, Tube Shout, Violent Acid to Drill…). Creative, surprising pairings. Each gated, named under a TRENCH name, added to the roster, built + installed for Tyson's ear (keep/kill). Do NOT auto-promote — build a keep/kill contact sheet (4-corner + morph-sweep response plots, per body) and let the ear decide.

## Hard laws (do not violate)
1. **4 corners, all authored:** M0_Q0, M100_Q0, M0_Q100, M100_Q100. Q100 is a **second authored pose, NEVER derived**. Q corners may be a radius increase (BLOOM) but each must be authored/measured independently — no compiler-derived Q.
2. **Stage law = raw SCALE=b0.** Compile through `trench-core` (`stage_law::words_from_geometry` / the `coeffs_to_words` path). Do NOT use the legacy DC-normalizing `stage_biquad` gain — it flattens the resonant crown by up to 21.73 dB (pinned test in `stage_law.rs`). Raw b0 is what carries gain budget.
3. **Format:** 240 bytes = 4 corners × 6 stages × 5 u16 words, authored at 39062.5 Hz. `trench-core` is the ONLY compiler/kernel — do not write a second one (AGENTS.md).
4. **Bound the crowns:** every corner's peak (max dB of its packed-runtime response) must sit **≤ +27 dB** (ROM corner-crown law). If a body runs hot, trim with a single **body-wide SCALE multiplier** applied to all 4 corners — it's a pure vertical shift (proven: SCALE = b0 scales a section's whole numerator, so it moves level only, never crown-vs-floor contrast, never tuning). Keeps morph relationships intact.
5. **Stable + clean:** every packed pole radius < 1 (target max ~0.995, hard edge 0.9997), 0 unstable / 0 nonfinite on a ≥17×17 Morph×Q grid. No E-mu names, bytes, coefficient rows, or preset names in the branch (study evidence only).

## What "interesting" means (the creative brief)
- **Contrast the two morph objects:** tiny→huge, dry→cavernous, plucked→struck. e.g. Kalimba → mine cave, Steel Pan → tunnel, Violin body → China cymbal, Ukulele → upright-bass body, Glockenspiel → tunnel-entrance.
- **Give Q a real scene** (a named verb per METHOD.md): BLOOM (radii → ~0.999, centers hold), SPREAD (cluster fans apart), SCREAM (one lane parks low + hot), FLIP (register change). Prefer authoring Q from the **resonant measurement** where the pool provides one (China-Cymbal-Contact-Damped/-Resonant, Violin-Body-Dampened/-Resonant, mine-site 1way/2way).
- **Carry gain budget, don't flatten:** the flat trap is six equal-radius lanes filling the floor. Author a **dominant crown + deep notches** (zeros near the unit circle carve the valleys — an ear-safe lever that never touches the formant poles). Floor ≈ 0 dB, one voice on top.

## Data sources (grounded)
- **Measured source pool — 186 fitted candidate bodies + matching renders:**
  `out/candidates_partial_20260720_2103/bodies/*.body240` (+ `audio/*.wav`). ACTOR__ = one measured object each: China Cymbal, Glockenspiel, Kalimba, Steel Pan, Soprano/Concert Ukulele, Violin body (damped+resonant), Winter upright bass, tunnels a–f (1way/4way), mine-site 1/2 (1way/2way), ortf rooms. Use these corners as source poses; cross two objects across Morph.
- **Authoring model + generator:** `filters/docs/METHOD.md` (8-lane alphabet, 6-letter word twice, 4 corners, 2 knobs, Q verbs), `filters/generator/build_interesting_presets.py` + `candidate_table.csv` (a working "interesting recut" generator — extend, don't rebuild), `filters/archetypes/ARCHETYPES.md`, `filters/rails`, `filters/tables`.
- **ROM-grade finished refs + corner banks (copy-risk targets, study only):** `C:\Users\hooki\df2\desk\finishing` (REF_007/013/018), `desk\sheets\siblings_of_the_best`, `desk\corners`, `desk\bank\v1`.
- **Raw measured IRs (if you need to fit fresh corners):** `wav-source-library/measured_objects` + `tools/build_measured_object.py` (ir_to_tf → `trench_ffi.fit_corner_from_magnitude` → `coeffs_to_words` → `raw_from_words`).

## Toolchain (verified working this session)
- Python runtime FFI: add `C:/Users/hooki/df2` and `C:/Users/hooki/df2/pyruntime` to path → `from pyruntime import trench_ffi` (has `decode`, `encode`, `compile_body`, `engine_render`, `packed_probe`). `pyruntime.packed_interp`: `words_to_coeffs`, `coeffs_to_words`, `kernel_to_biquad`.
- Decode a body's stage geometry (matches `stage_law.rs`): read 240 bytes → per 5-word stage, `pair_geometry` for pole/zero (conj/real/degen), `scale = 4·decode(w4)`.
- Per-corner response: product of 6 stage biquads' |H(e^jω)| over 30–19200 Hz; **budget = max − median dB**; **crown = max dB** (the +27 ceiling metric).
- Roster: append `TRENCH_PRESET("Display Name", "body_stem", "LIBRARY")` lines to `plugin/presets/PresetRoster.inc` (currently the 19 curated heroes; NO FILTER is injected separately — don't list it). Give clean display names with spaces (prettyBodyName leaves them intact; it only strips ALL-CAPS_ prefixes).
- Bodies go in `plugin/presets/bodies/<stem>.body240` (globbed + baked at build).
- Build + install: `powershell -ExecutionPolicy Bypass -File tools\build_install_vst3.ps1` (parks the old DLL if FL holds it; FL must be fully restarted to pick up).

## Verify before claiming (Tyson judges by plot)
For every body: a big dB-vs-log-Hz sheet — 4 corners + 21-pose morph sweep — from the **packed runtime** (not design math). Confirm: crowns ≤ +27, floor ≈ 0, stable/finite on the grid, copy-risk clear vs nearest ROM ref (≥ ~6 dB per-corner distance). Then the ear decides keep/kill. One change per verdict; show the result.
