# TRENCH·FORGE — Studio Handoff (transitional prompt for a fresh session)

Paste this whole file as the opening message of a new Claude session. It is
self-contained. Read `AGENTS.md` and `CLAUDE.md` first; they win on any conflict.

---

## MISSION
Finish **TRENCH·FORGE**, a Law-Author studio that designs **iconic, P2K-style
morphing-filter FX presets** for the df2/TRENCH plugin (a $49 destructive filter
FX, aggressive "Ken Carson distortion" target). v1 ships **4–7 iconic presets**.
The studio exists and renders; the job is **genuine end-to-end functionality**:
pick fit poles → hand-design zeros (with a live score) → audition the real chain →
**bake an audited session through trench_core** → the body plays identically in
the JUCE plugin.

Work in place in `C:\Users\hooki\df2`. Momentum over ceremony. Verify with the
commands at the bottom — do not claim done without them.

## RUNTIME TRUTH (locked, do not re-litigate)
- A body = **240 bytes = 4 corners × 6 sections × 5 packed u16 words**.
  Corners: `M0_Q0, M100_Q0, M0_Q100, M100_Q100`.
- **6 sections = 12 poles** (each section is a conjugate **pole pair**) + a
  **zero pair** per section. "How many poles" = 12.
- **Morph** (FilFreq) interpolates A→B; **Q/Secondary** = pole **radius**
  broad→sharp. Engine bilinearly interpolates the **packed words** (morph first,
  then Q). Q must NOT move frequency; Morph moves frequency.
- `plot == engine` to 0.0000 dB (`forge-web/js/packed.js` mirrors trench_core).
  The packed-runtime magnitude is the only truth. The audition chain adds
  **AGC → Mackie slam → QSound** (nonlinear) — label it; the linear plot does not
  include it.
- **Parity is proven:** the studio packs through WASM `forge_pack_params`, whose
  math matches trench_core decode to **0.0140 dB** (`dev/tmp/emu_tensioning/parity_test.py`).
  So a body saved in the browser plays identically in the JUCE plugin.

## THE METHOD (locked this session)
- **Poles are FIT, never invented.** LPC(12) of real audio, or measured
  formant/rail tables. Split per body: **~6 poles to a FOUNDATION** (measured
  rails 98/194/270/390/530 Hz, DC-pinned body, held across morph) **+ ~6 poles to
  the SOURCE** (LPC fit / vowel formants). The split is a knob (`FOUND`, default 3
  foundation sections). **All 12 poles used — zero passthrough/waste.**
- **Zeros are HAND-AUTHORED** by the user — the character. Studio starts with
  **zeros OFF**; the user drags them onto poles. Each zero adds a canyon.
- **DC-pin every all-pole section:** `gain = (1 − 2r·cosθ + r²)/(1 − r²)` pins it
  to 0 dB at DC. This is the fix for the **+56 dB low-end mountain** (the bug was
  `gain=1` on stacked low resonators). Already added to `studio.js` (`dcpin`) and
  `tools/forge_generate_corners.py`.
- **Q is musical, per-lane**, NOT a global slam to max radius. Foundation lanes:
  hi-Q ≈ lo-Q+0.03 (stay weight-bearing). Source lanes: sharpen to ~0.99; one
  "tear" lane nears the rim (~0.9985–0.9992).

## SCORING — CRACKED (this is the engine; reuse it, don't reinvent)
- The real scorer is `src/utils/packed_runtime.py` **`evaluate_body(body, grid_steps)`**
  → metrics + `objective`. Reference = the 50 P2K types:
  `dev/tmp/production_authoring/extreme_qd_v1_final/reference_aggregate.json`
  (morph 24.8, secondary 17.1, endpoint 83.7, center 108.6, peaks/valleys 3.5,
  max_pole_radius 0.9989).
- **Objective** = `0.32·endpoint + 0.28·center + 1.10·morph + 0.85·secondary +
  3.5·(peaks+valleys) + 14·ceiling_occupancy + 7·zero_motion`.
- **Gates:** stable+finite (incl. off-grid interior), `0.998 ≤ max_r < 0.9999`,
  center_span > 74, endpoint/morph/secondary > 0.95×reference, **peaks ≥ 3,
  valleys ≥ 3**, zero_motion > 0.35.
- **KEY FINDING:** generated **pole-sets already BEAT the 50 on morph, scream
  (max_r ~0.999) and span.** The only failing axes are **peaks / valleys /
  zero-motion = the ZEROS = the hand-authored canyons.** So the poles are right;
  the iconic complexity is the zeros the user designs. (A clean 6-pole LP scores
  huge morph + good Q but fails peaks/valleys/zero-motion — confirms it.)

## FILE MAP
- `forge-web/studio.html` + `forge-web/js/studio.js` — THE studio. Loads
  `data/sources.js`, packs via WASM `forge_pack_params`, plots via `packed.js`,
  plays via `forge-worklet.js`, SAVE downloads `.body240`. Poles DC-pinned, zeros
  start OFF.
- `forge-web/js/packed.js` — plot==engine decode/lerp/`packedDb` (+ `wordsFromBytes`,
  `hexFromWords`, `bytesFromHex`, `downloadText`).
- `forge-web/js/forge-worklet.js` — WASM engine audio (AGC+Mackie+QSound). Msgs:
  `{body}`, `{params:{morph,q,agc,slam,wide}}`, `{playing}`, `{src}` (0 saw/1
  noise/2 808/3 voice); posts `{ready}`, `{level,peak}` (the FLOODED meter).
- `forge-web/wasm/forge_web_wasm.wasm` — trench_core in WASM. **Param order per
  section** (for `forge_pack_params`, 6×4 sections): `[on, pole_hz, pole_r, gain,
  zero_on, zero_hz, zero_depth]`. Rebuild only if you touch Rust:
  `cargo build --release --target wasm32-unknown-unknown` then copy
  `forge-web-wasm/target/wasm32-unknown-unknown/release/forge_web_wasm.wasm` →
  `forge-web/wasm/forge_web_wasm.wasm`.
- `forge-web/data/sources.js` ← `tools/fit_sources_lpc.py` (LPC(12) fit sources;
  vowels 6+6, openair IRs 12-pole; `FOUND` knob; waste-flagged).
- `forge-web/data/frames.js` ← `tools/build_frame_bank.py` (Peterson-Barney vowel
  triangle + P2K clean-room rails, low→high by F2 — Frame A/B endpoints).
- `tools/forge_author_server.py` — **Python backend**: serves `forge-web/` AND a
  **`POST /bake`** endpoint that emits a full audited session through trench_core:
  `dev/tmp/forge_visual_author/<session>/` with `target.json fitted_lanes.json
  law_source.json body.body240 cartridge.json audit.json response.png
  workbench.html`. Parity-proven pack mirrors `forge-web-wasm/src/lib.rs`. Verified
  baking PASS, max_r 0.996, 0/289 unstable.
- `tools/forge_generate_corners.py` — bulk generate (mix vowel A→B morphs + LPC
  sources) → **score with `evaluate_body` vs the 50** → ranked **plot contact
  sheet** + auditions. Run: `python tools/forge_generate_corners.py 60`.
- `src/utils/packed_runtime.py` / `src/utils/terrain_metrics.py` — the scorer.

## WHAT WORKS
- Studio renders: source rail, curve (poles L1–L6, draggable zeros), Frame A/B,
  Morph/Q sliders, drive/source/play/meter, save. DC-pinned poles, zeros off.
- WASM pack + plot + worklet audio path (mirrors the proven `forge.js`).
- Python bake server produces a full trench_core-audited session.
- Bulk generator + real scorer + ranked plot sheet.
- Parity (WASM == shipped) proven.

## WHAT'S BROKEN / THE END-TO-END GAP (the actual job)
1. **SAVE is not end-to-end.** It only downloads body bytes. Wire SAVE to
   `fetch('/bake', {POST, body: JSON of the 6 lanes})` against
   `tools/forge_author_server.py`, and **run the studio FROM that server**
   (`python tools/forge_author_server.py` → `http://localhost:8130/studio.html`),
   not `python -m http.server`. Then SAVE emits the full audited session.
2. **No live score.** As the user designs zeros, show the **live objective +
   gate status vs the 50** (morph/Q/center/peaks/valleys/zero-motion, PASS/FAIL
   per gate) in the UI. The user must SEE the gates close as they carve canyons.
   (Port the metric formulas from `src/utils/packed_runtime.py` to JS, or call
   `/score` on the server.)
3. **The authoring UX the user actually asked for is not built.** He wants
   **six role lanes** with **range rollers** (thumbwheels): per lane — Pole Hz
   travel (home◄►away), Zero Hz travel (home◄►away + depth), Pole Radius (loQ◄►hiQ)
   — plus a **read-only 4-corner telemetry strip** (C0–C3 pole/zero/r), an
   **active/WASTE status per lane**, and a **waste meter** flagging every
   unauthored pole/zero. Separate Morph and Q sliders (NO 2D pad). Zero editing
   coarse and forgiving, role-aware. This replaces the current curve-diamond drag.
4. **Foundation/body must be obvious and first-class** (L1–L3), audibly holding
   the sub while actors morph; UI says "**6 pole-pair lanes = 12 poles**".

## DEFINITION OF DONE
1. Studio served from the Python server; **SAVE bakes the full session through
   trench_core** (body240 + cartridge + law_source + audit + response.png).
2. **Live score vs the 50** updates as zeros are designed; gates show PASS/FAIL.
3. Six **role lanes** with range rollers + 4-corner telemetry + **waste meter**;
   no silently-bypassed lane; "12 poles" stated.
4. Q is musical (doesn't destroy the sound; doesn't move frequencies); foundation
   stays weight-bearing.
5. The user can hand-author a body whose live score **passes the 50-type gates**,
   audition it on 808/saw/voice, and save an audited artifact that plays
   identically in the JUCE plugin.

## VERIFICATION (must pass; show output)
```
node --check forge-web/js/studio.js
node --check forge-web/js/forge-worklet.js
python tools/forge_author_server.py        # then open http://localhost:8130/studio.html, design, SAVE
python tools/forge_generate_corners.py 60  # ranked plot sheet + scores vs the 50
python tools/law_author.py --preset hedz_like_anchor_canyons --out dev/tmp/law_author/golden_hedz_like
```

## CLEAN-ROOM + HYGIENE
- Study the 50 P2K types' **behavior** (rails, roles, the scream/foundation law);
  author originals. **Never** ship copied coefficients, packed bytes, names, or
  tables. P2K material in `ref/` is study-only.
- Do NOT stage reference bins, ROM dumps, gpt55 reports, or generated bulk. Session
  output lives in gitignored `dev/tmp/`. `tools/` is the tracked, promoted home.
- The 6-preset lineup uses clean-room names (808 Tear / Talking Mouth / Millennium
  Bank / Lucifer Cut / Klub Acid / Ear Comb are working labels, not preset copies).

## FIRST MOVES (suggested)
1. Run the server + `forge_generate_corners.py`; read the ranked plot sheet to
   confirm the scorer + pole sets. 2. Wire SAVE→/bake and confirm a session folder
   appears + audits PASS. 3. Add live score to the studio. 4. Build the six
   role-lane + range-roller + waste-meter UI. 5. Iterate to a passing, auditioned,
   baked preset. Surface taste calls to the user; drive everything else.
