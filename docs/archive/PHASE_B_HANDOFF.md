# TRENCH·FORGE — Phase B Handoff (paste as the opening message of a new chat)

Read `AGENTS.md`, `CLAUDE.md`, and your memory first; they govern. Work in place in
`C:\Users\hooki\df2`. Momentum over ceremony. Verify with the engine — plot==engine,
measure don't theorize. Tyson owns taste/ear; Claude drives everything else.

**READ FIRST — E-mu reference study (clean-room: learn the grammar, copy nothing):**
- `C:\Users\hooki\Downloads\EMU Dillusion_PeakShelfMorph_Tutorial_WEB.pdf` — E-mu's own
  peak/shelf/morph tutorial. Directly the typed-section vocabulary + how the morph between
  peak/shelf states is meant to work. Read it before designing `section_biquad`.
- `C:\Users\hooki\Downloads\emu-mophatt-manual.pdf` — Mo'Phatt manual (the Z-plane morphing
  filter family). Study the filter-type taxonomy and morph behavior.
Study behavior/grammar only; ship original bodies, never copied coefficients/names/tables.

---

## THE PRODUCT (locked this session — don't re-litigate)
**Ship the df2/TRENCH plugin with a small bank of HAND-DESIGNED iconic presets.**
The Forge / design surface is Tyson's **private internal bench — it is NOT shipped.**
The customer performs presets with **two controls: Morph (FilFreq) + Q (FilRes)**, through
the drive chain (AGC → Mackie slam → QSound; QSound optional). v1 = **4–7 iconic presets**.
Everything below exists to let Tyson **hand-design** those few bodies fast, by ear.

## PHASE B GOAL — CORRECTED (read this; the typed-recipe plan is REJECTED)
Build a **six-slot pole-zero FRAME author**, NOT a six-typed-filter-recipe author.

**REJECTED:** `typed card = product body`. Typed PEAK/NOTCH/shelf are safe DSP *primitives /
safety helpers* only. As the whole authoring model they hide the real structure and produce
"a lowpass with EQ bumps" — magnitude-shaping bands, not six meaningful pole-zero actors.

**The real model (OBSERVED in `dev/tmp/rom_poles_zeros.csv` — 350 decoded rows, 7 reference
bodies):** a body = **6 stages, each an explicit signed pole-pair + zero-pair**, paired into
**Frame A → Frame B** with **stage identity preserved across corners** (slot i ↔ slot i, sacred).
What makes a body iconic is **MOTION + Q-PRESSURE**, not the family label. Example, Tb-Or-Not-Tb:
S1 pole sweeps **578 → 9826 Hz = +4.09 octaves** (the leader); S2 falls −0.47 (contrary);
S3 radius rides **0.96 → 1.000 at Q100** (the scream). The candidates failed because they had
~1-octave wiggles and EQ bumps — timid motion, no Q-pressure.

**Slot budget:** 12 poles = **3 foundation slots (6 poles) + 3 fitting slots (6 poles)**.
**Foundation is ABLATION-DEFINED**, not "low shelf by label" — a foundation is any lane whose
mute **collapses body identity** (it can be sub pressure, a clustered formant body, a high
brace/air lane, a pole-zero cancellation that shapes hollowness, or a near-unit-circle zero
lane for phase/canyon). Discover it by ablation, never assign it by name.

**The gates (ALIVE/MOVING/CLEAN) are hygiene only — NOT the selector.** They prove "not broken
DSP," not "good preset." Select by **driven audio + lane ablation + Tyson's ear**, never by the
Bode plot (plot = crater/sub/instability diagnostic only).

Then hand-design the iconic preset bank with Tyson and bake it into the plugin's factory bank.

---

## WHAT'S DONE (Phase A — verified this session, bit-identical)
**One-owner compiler.** `trench-core/src/compiler.rs` is the single owner of the forward
compile (`stage_biquad`, `biquad_to_words`, `pack_body`). FFI export `trench_compile_body`
(in `trench-core/src/ffi.rs`). The Python author server (`tools/forge_author_server.py`)
and the WASM (`forge-web-wasm/src/lib.rs`) both **call it** — their local copies are deleted.
`pyruntime/trench_ffi.py` has `compile_body()` (lazy `_compile_ok` guard). `packed.js` stays
decode/plot-only. **Proven:** WASM == Python == trench-core, **hamming 0** over 240 bytes
incl. the radius drift zone. This also fixed a latent drift (WASM clamped radius to
0.999999999999999, Python to 0.9999 — now one `MAX_RADIUS`).

**Also live:** in-studio `/fit` (open audio → LPC/LSP fit, `tools/fit_sources_lpc.py`
parameterized: preemph, crank, qsource), the desktop studio (`forge-web/studio.html` +
`js/studio.js`) and a minimal **mobile editor `forge-web/m.html`** — all pack through the
one compiler. Server endpoints: `/bake` `/score` `/fit`; `/bake` also writes the JUCE
audition slot (`~/Documents/TRENCH/authoring_slot.json`) so the plugin hot-reloads.

## KEY DSP FINDINGS (proven this session — the heart of Phase B)
1. **The morph is LOGARITHMIC by construction.** It lerps the packed minifloat *codes*, so
   a pole 400→4000 Hz passes through ~1274 Hz at morph 0.5 (geometric, not linear 2200).
   **Author all travel in octaves/semitones.** (Vowel candidate glides +0.25 oct per
   quarter-morph — exact log.)
2. **The corner-collapse crater is the ALL-POLE section SHAPE** (constant numerator →
   −12 dB/oct, six stacked → −236 dB). It is **NOT** the minifloat (round-trips < 0.01 dB).
   **Fix: every section is pole+ZERO (flat-ended). A zeroless section is the bug** — this is
   already CLAUDE.md law; the studio violated it by defaulting actor zeros OFF.
   Isolation proof: zeros control the crater (87↔236 dB); survival changes spread by 0 dB.
3. **The "massive sub" is THREE stacked low sections** piling low energy. `dcpin` pins DC
   only (→ HF crater). Companion zeros above the foundation poles turn them into low-shelves
   that stack (→ sub mountain, sub−mid +16 dB, measured). The cure is **the right section
   TYPE (one low-shelf for the sub, not three resonators) + per-lane gain budget.**
4. **"Died" = no dominant hot resonance.** The drive chain needs a hot high-Q peak to bite.
   Dead candidates measured peak −6 / −42 dB; alive ones +13 dB. Bandpass-0dB + negative-gain
   canyons = passive = dead.
5. **The iconic structure** (decoded Talking Hedz, memory `talking-hedz-structure`): a few
   FIXED **anchor** poles + **1–2 hot high-Q crossers** (one rises ~200→1700, one falls
   ~900→200, crossing mid-morph = the talk/tear) + **Q tightens** all toward ~0.999. ONE
   dominant gliding leader — not a democracy of peaks (those *hop*) and not all-pole.

## THE ACTUAL PHASE B WORK (the frame author)
1. **Build a six-slot pole-zero FRAME author.** A frame = 6 slots, each an explicit signed
   `(pole_hz, pole_r, zero_hz, zero_r)`. A body = **Frame A + Frame B + a Q rule**, slot i
   pinned to slot i across all 4 corners. Corners: `C0=A·loQ, C1=B·loQ, C2=A·hiQ, C3=B·hiQ`.
   Morph slides A→B in packed/log space (proven log); **Q raises radius/pressure toward the
   rim and exposes the zero canyons.** Author with **big motion** (multi-octave leaders, like
   the +4-oct ROM leader) and **real Q-pressure** (radius → ~1.0 at Q100), not timid wiggles.
2. **Quarry the raw material from REAL pole-zero structure, clean-room** — study, never copy:
   - `dev/tmp/rom_poles_zeros.csv` — 350 decoded rows, 7 reference bodies; the truth of how
     real designer bodies distribute pole+zero per slot and how much they MOVE / Q-press.
   - `CORNER_QUARRY_TRUTH.md` — the right raw material is a **complete signed pole-zero
     divisor**, not named filter types or response-only cards.
   - `P2K_FAMILY_REVERSE_ENGINEERING.md` — iconic = motion + Q-pressure, not family label.
   - `### Permanent Master Acoustic Dictionary.txt` — acoustic TARGET dictionary (vocal
     formants, instrument bodies, combs, metallics, aggressive resonance). Targets, not
     coefficient truth.
   - The **fitter** (`/fit`, `fit_corner_arma`, formant/modal/rail `tables/`) supplies real
     fitted pole-zero slots for the **3 fitting slots**. **Never invent poles.**
3. **3 foundation slots + 3 fitting slots = 12 poles.** Foundation = ablation-defined (mute
   collapses identity), not low-shelf-by-label. Fitting slots = the moving fitted actors.
4. **Lane ablation is the waste test + the foundation finder.** Render the body, then re-render
   with each slot muted (S0..S5). A slot whose mute doesn't audibly/visibly change the **driven**
   output is **waste** — replace it. A slot whose mute collapses the body is a foundation.
5. **Select by driven audio + ear, not by Bode.** Render through AGC→Mackie on real loops
   (808/reese/saw/vocal) with the morph sweeping ("the morph is the loop"); QSound rendered
   **separately** (optional). The Bode plot is a hygiene diagnostic only (crater/sub/instability).
   ALIVE/MOVING/CLEAN gates = hygiene pass, then Tyson's ear picks keepers → bake into the
   factory bank.
6. **Typed sections stay as primitives/safety only** (`section_biquad` in `compiler.rs`,
   already implemented — RBJ family, flat-ended; formulas verified in `COMPILER_REWRITE_SPEC.md`
   §2). Use them to realize a shaping/foundation lane cleanly, NOT as the body model.
   The **survival** gain pass (`tools/three_layer_acoustic_forge.py`) is available if a frame's
   per-corner levels need budgeting — apply only where the driven render needs it, don't blanket it.

## FILES / TOOLS
- `COMPILER_REWRITE_SPEC.md` — the full verified spec (section formulas, one-owner plan,
  parity tests, implementation order, minifloat traps). **Read it.**
- `PROJECT_STATE.md` — verified state map of the whole project.
- `trench-core/src/compiler.rs` — the owner (Phase A done). `ffi.rs` `trench_compile_body`.
- `tools/three_layer_acoustic_forge.py` — the proven anatomy+articulation+**survival** system to port.
- `tools/forge_author_server.py` (`/bake /score /fit`, audition slot) · `src/utils/packed_runtime.py`
  (`evaluate_body` scorer + gates vs the 50) · `pyruntime/trench_ffi.py` (`compile_body`,
  `engine_render_slam`, `packed_probe`).
- `dev/tmp/make_v1_candidates.py` — candidate authoring + DRY/QSound render + measure.
  Recipes were just rewritten to the iconic structure (anchors + hot crossers); **not yet
  run/verified** — run it and check the alive/log/stable gate.
- `forge-web/studio.html`+`js/studio.js` (desktop), `forge-web/m.html` (mobile) — pack via the one compiler.
- `tables/` — real frequencies (do not invent poles).

## BUILD GOTCHAS (Windows)
- cargo: `C:\Users\hooki\.cargo\bin\cargo.exe`, **run from PowerShell** (git-bash `link.exe`
  shadows MSVC). wasm32 target installed.
- DLL: `cargo build --release -p trench-core` → `target\release\trench_core.dll`. **Kill any
  python holding it first** (`forge_author_server.py`, `serve_forgeweb.py`) or the link fails
  "Access is denied".
- WASM: `cargo build --release --target wasm32-unknown-unknown --manifest-path forge-web-wasm/Cargo.toml`
  → built artifact is `forge-web-wasm/target/wasm32-unknown-unknown/release/forge_web_wasm.wasm`
  (NOT the workspace target) → **copy** to `forge-web/wasm/forge_web_wasm.wasm`.

## VERIFY (show output)
```
python -c "from pyruntime import trench_ffi as t; print(t.compile_body([0.0]*168)[:0])"  # FFI binds
python dev/tmp/make_v1_candidates.py        # build/measure/render candidates; check alive/log/stable gate
python tools/forge_author_server.py         # serve; /bake /score /fit; studio + /m.html
# parity (after any compiler edit): rebuild DLL+wasm, confirm WASM==Python bytes hamming 0
```

## DOCTRINE / CONSTRAINTS
Clean-room (study the 50 P2K types' grammar; ship originals, no copied coeffs/names/bytes).
plot==engine is the judge. One owner per job (compiler = trench-core; don't add an N+1th copy).
Judge through AGC→Mackie slam on real material, never the bare filter. QSound optional/separate.
Do NOT ship the design surface. AI never approves a finished body — Tyson's ear confirms last.
