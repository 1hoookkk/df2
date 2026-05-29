# STATE

What exists. What's broken. What's next. Update on every code change.

---

## Now — 2026-05-28 · late (read this first)

**STRATEGIC POSITION:** Tyson is exhausted and asking for a fresh-eyes audit of
the whole plugin codebase (he wants a GPT prompt for an in-depth review — that
prompt is in the conversation transcript and proposes 3 options: surgical
fixes / JUCE shell rewrite preserving Rust core / full rewrite). My honest
read: Option B (JUCE-shell-only rewrite, keep `trench-core`) is the right call
— every bug found today lives in the JUCE C++ shell; the Rust core, AGC table,
240-byte format, and X3 null parity are all verified-clean.

**WHAT SHIPPED THIS SESSION:**
- 7 originals baked into the player roster: **Voice Walk** (Klatt vowel),
  **Mason Tube** (physical Helmholtz), **Knock Burst** (808),
  **Metal Scream** (resonant), **Phaser Slide** (comb), **Cut Edge** (cut),
  **Maul** (insane direct-biquad). Plus Razor Shell from morning. Carts in
  `juce-shell/assets/cartridges/`. VST3 rebuilt + installed to Program Files.
- `tools/sweep_roster.py` extended with `wild` (random-then-structured-chaos),
  `insane` (direct biquad design — bypasses factorizer, every pole+zero
  hand-placed at audible high radii), `analyze_sweep` (mid-intent + trajectory
  smoothness on every body), and the `_normalize_corner_peak` helper that
  targets a configurable AGC sweet spot (+22–28 dB peaks).
- `tools/_anatomy.py` — exact per-stage pole/zero extraction via the kernel→
  biquad math (`b0=c4, b1=(c0-2)c4, b2=(1-c1)c4, a1=c2-2, a2=1-c3`) and root-
  finding. Annotated plots with red ▲ poles, blue ▼ zeros, radius labels.
- `tools/gen_vocal_v2.py` — Klatt-formant-pinned direct-biquad vocals (5
  named vowel-pair morphs), AGC-engaged. Loads picks into Forge Audition slot.
- `tables/physical_models.py` — Helmholtz + closed/open pipe + Donnell shell
  + rectangular cavity room-mode formulas. Real physics for cavity intents.
- `tables/family_intents.json` extended: Klatt vocals (10 vowels),
  physics-modelled cavities (7 objects with dim receipts), violence intents
  (chainsaw / drill_squeal / glass_shatter / iron_plate / wolf_howl /
  bee_swarm / acid_303 with freq maps in the descriptions).

**CRITICAL JUCE-SHELL BUGS FOUND TODAY:**
1. **Body strip writing NORMALIZED 0..1 to a parameter expecting DENORMALIZED
   0..N** — `TrenchBodyStrip::setIndex` at line 107 called `convertTo0to1`
   before `setValueAsCompleteGesture`. JUCE renormalised again → every click
   collapsed to index 0 or 1. **Fixed in place**. Every other control in the
   codebase calls `toDenorm()` correctly — this was a one-off, and a strong
   signal the param contract is fragile.
2. **Input mode default = SLAM** (`TrenchParameters.cpp:39-40`), `slamDrive
   = 0.35` → 12.6 dB of pre-cascade desk-drive saturation on EVERY body by
   default. Producer expectation is clean-unless-cranked. This was the cause
   of "Neon Vane sounds completely distorted" — Neon Vane was fine; the
   *input stage* was hot.
3. **Latent display-only bug in `TrenchResponseDisplay.cpp` lines 14-17 +
   441**: hardcoded `kBodyNames[4]` and `bodyIndex() % 4`. The on-screen
   "BODY 013–016" identity readout cycles through 4 numbers regardless of
   which of the 54 bodies is selected. Cosmetic only (the strip name reads
   from the real roster), but misleading.
4. **Two VST3 install paths drifted out of sync** — `Program Files\Common
   Files\VST3\TRENCH.vst3` (fresh, today's build) and
   `%LOCALAPPDATA%\Programs\Common\VST3\TRENCH.vst3` (stale, earlier today's
   build). FL may scan either. Delete the LOCALAPPDATA copy to remove
   ambiguity, or always copy both.

**THE ACTUAL ROOT CAUSE of "presets don't work / Neon Vane distorted":**
**FL Studio had been running continuously since May 25 19:05 — 3 days — and
was holding the old DLL in memory the entire conversation.** Every rebuild
today landed on disk correctly; FL just never reloaded. Multi-hour debug
session was chasing ghosts in a binary that wasn't even loaded. The fix is
killing `FL64.exe` in Task Manager (closing the FL window leaves the process
running in tray) and reopening FL fresh.

**DEV-WORKFLOW LESSON LEARNED:** Use `TRENCH_Standalone.exe` or JUCE
AudioPluginHost while iterating on plugin code. FL is for *using* the
plugin in a real session, not for fast-iteration dev — Windows maps DLLs
once per process and they stay in memory until the host fully exits.

**DOCTRINAL INSIGHTS:**
- Engine ceiling is **12 poles + 12 zeros per corner** (4 corners × 6 biquads
  × 2 poles + 2 zeros each, packed in 240 bytes). Going higher requires
  engine V2 (new format + break X3 parity).
- **AGC table at indices 4–7 (mults 0.92 / 0.50 / 0.20 / 0.16) is where the
  E-mu character lives.** Filter peaks need to reach ~+22 to +28 dB to drive
  the AGC into those zones. Below ~+15 dB the AGC is asleep and the body
  sounds clinical/dry. The `& 0xF` wrap fires above ~+24 dB → adds chaos
  gating character.
- **Mud is broad-Q low-freq peaks, NOT narrow ones**. A razor 300 Hz pole at
  r=0.997 is a tonal ring (clean character). A 200–500 Hz wide hump from a
  low-Q pole is mud. The fix is the BALANCE RULE — low-mid peak must be
  matched by an equal-or-louder mid+treble peak — not capping low-freq Q
  (which makes everything smooth and dull).
- **The factorizer wastes zeros at the origin when the target curve has no
  notches.** Wild-mode bodies had all 12 zeros parked at r=0 (inactive),
  body was pole-only → buzzy without cutting character. The fix is either
  (a) target curves with deep notches that force the fitter to commit zeros
  at audible radii, or (b) bypass the factorizer with direct biquad design
  (the `insane` mode does this).

**OUTSTANDING / DO NEXT:**
- Tyson needs to kill `FL64.exe` and reopen FL to actually load today's
  work. Then audition the 7 originals (Voice Walk, Maul, etc.) in the body
  strip and the Klatt-direct vocals via Forge Audition swap.
- A "runtime error" was reported but never described — diagnosis pending.
- Tyson is leaning toward a code rebuild. The audit prompt (in conversation)
  is ready to paste into a fresh AI session.
- The latent `TrenchResponseDisplay` display bug is still present and worth
  a small fix.

---

## 2026-05-28 · evening

**FILTER TYPE CARDS = the producer front door. A body is a named FILTER TYPE, not
a corner bank.** Tyson's synthesis from the Morpheus/P2K screenshots: producers
choose a *named morphing machine*, move Morph, move Q — they never design corners,
responses, or poles. This is a REFRAME + front door over the proven Target Browser,
not a new engine. No DSP invented.

- **`tools/filter_type_cards.json`** — 6 v1 cards (Speaker Knockerz=EQ_BOOST/RESONANCE,
  Small Talk=VOWEL, Razor Shell=EQ_CUT/PHASER, Aluminum Siding=RESONANCE/FLANGER,
  Cul-De-Sac=BPF/RESONANCE, Glass Throat=VOWEL/RESONANCE/HYBRID). Each card = plain job +
  what Morph does + what Q does + avoid + an existing `target_templates` archetype + an
  optional reference inspiration. Internal class taxonomy (LPF HPF BPF EQ_BOOST EQ_CUT
  VOWEL PHASER FLANGER RESONANCE WAH DISTORTION SPECIAL_FX HYBRID) is **inspiration only —
  never product-facing**.
- **`tools/make_class_bodies.py`** — THE producer command. `--class EQ_CUT --campaign
  razor_shell --count 64 --seed 1001` → generates whole 4-corner bodies via
  `target_browser.generate`, culls broken, publishes survivors to `bodies/generated/`,
  writes a **purely musical** card-framed `audition.html` (card header + "Candidate NN" +
  KEEP/MAYBE/REJECT; NO freqs/poles/coeffs/stages on the surface — leak-checked). `--keep`
  saves body240 + cart + keep.json. `--reference [slug]` routes through the brief path.
  **Verified: 51/64 survived, 51 presets published, page DSP-clean.**
- **`tools/reference_brief.py`** — reference→ORIGINAL bodies. Loads a `bodies/rom/P2k_*.json`
  reference, extracts a musical BRIEF (body mass, identity, fracture, Morph/Q motion, midpoint,
  failure modes — **behaviour only, never coefficients/names**), widens it into a template
  family, generates, hard-culls, and **rejects candidates too close to the reference** (corner+
  midpoint curve distance, exact-freq clones). audition.html carries a REFERENCE A/B preview
  (preview-only, never shipped) + response images. `--keep` saves body240+cart+brief+gate+
  notes+response.png. Fix landed: brief analysis is **band-limited (60–10.5 kHz)** or it picks
  the Nyquist-edge resonance as the "identity" (it called an 11.5 kHz spike DJ Alkaline's voice).

**PLAYER SHIPS IT:** first filter-type-card body baked into the roster —
`juce-shell/assets/cartridges/razor_shell_v1.json` ("Razor Shell", EQ_CUT/PHASER,
gate-clean cand_03; packedWords-only, loads via the canonical packed path,
`cartridge.rs:223`). Roster row added after the verified-usable `neon_vane` boot
default. **TRENCH VST3 rebuilt Release (exit 0)**, `razor_shell_v1_json` confirmed in
the binary, installed to `C:\Program Files\Common Files\VST3\TRENCH.vst3` (51 MB).

**OVERNIGHT BOLD SWEEP (roster_0528) — ran, merged, waiting on ears.** Six family
subagents (Vocal/Cavity/Resonant/Knock/Comb/Cut) ran `tools/sweep_roster.py` in
parallel. **Bold twin-anchor:** HOME and AWAY are INDEPENDENT skeleton draws —
genuinely different corners (~32 dB apart on test), AWAY hotter so HOME→AWAY spans
tame→violent. This replaces the timid base→shift→sharpen (which made 4 near-copies
and a dead morph) — Tyson's call: "E-mu had presets with 4 completely different
corners." 3 seeds × 64 = 192/family → **900 survivors / 1152, all stable** (no pole
radius ≥ 1). **Knock rebuilt** (his correction: 808 = knock+grit, NOT low boost; sub
is the source's job) — pedestal-cull is STRUCTURAL (0 sub-dominant survivors via the
`low_rolloff` hard gate). Merged to ONE queue:
`dev/tmp/sweep/roster_0528/audition.html` — 16 shortlisted/family (96 total), soft
pre-sort (advisory-clean + motion, NOT a verdict), DSP-clean surface, per-family
`.md` analyses. Survivors also published to `bodies/generated/gen_<family>_s700X_NN.bin`
(Factory list is flooded — audition.html is the curation surface). NEXT = ears →
KEEP → per-body `make_class_bodies --keep` cmd shown on each card.

**TRAP REJECTED (contamination vigilance):** a pasted "topology-locked morphing / fixed stage
roles (stages 1-2=body, 3-4=bite, 5-6=air), pin poles to bands" theory = the stage-authoring
trap doctrine forbids (stages are bookkeeping, no roles). NOT built. KIN is already structural:
every generated body's 4 corners grow from ONE feature skeleton (M0_Q0=base, others=morph/
sharpen of it), so they glide by construction — and the runtime never morphs *between two
presets*, so the "interpolate two ROM presets → mush" problem doesn't exist here. The ear is
still the boss; the avoided step is **curation**, not more generators.

---

## 2026-05-28 · parity ledger + factorizer proven

**PARITY LEDGER ~CLOSED + FACTORIZER PROVEN (bounded).** Two threads this session:

1. **Single-owner parity, two more locked.**
   - `AGC_TABLE` (the global compression curve) deduped: one Rust const
     (`trench-core/src/dsp/mod.rs`), exposed read-only via FFI
     `trench_agc_table`. `pyruntime/trench_ffi.py::agc_table()` reads it and
     **raises** if the core is missing (no Python mirror). The 4 tool copies
     (`verified_packed_audit`, `render_hedz`, `packed_gap_diagnosis`,
     `parity_null`) now read the canonical curve. Literal lives in ONE place.
   - **Forge `kernel_to_biquad` consolidated:** `forge/src/dsp.rs` no longer
     carries the formula — it delegates to `trench_core::minifloat::kernel_to_biquad`
     (kept the `&[f64;5]` wrapper so call sites are untouched). Packed interp was
     already gated both sides. Remaining triplication is now small.

2. **`fit_corner_from_magnitude` PROVEN — and characterized.**
   `trench-core/tests/factorizer_proof.rs` feeds it synthetic shapes + a real P2K
   ref's own M0_Q0 response (refit). Findings (artifacts: `dev/tmp/factorizer_proof/`,
   audition via `tools/prove_factorizer.py` SAW/TONE/PINK through the shipped engine):
   - **In-band (120–8 kHz) it reproduces a broad formant-envelope target tightly**
     (~2.3 dB RMS / ~5 dB max, stable). It WORKS for response-surface authoring.
   - **Top octave is unconstrained** → it parks a Nyquist-edge resonance (synthetic
     target: +66 dB spike at ~13.7 kHz). Out of the asserted band; audition decides.
   - **It is an ENVELOPE fitter, not a razor-ROM replicator** — refitting a real P2K
     body smooths its sharp poles/notches (~13 dB in-band). Expected & doctrinal.
   - Implication for a Target Browser: target broad formant/peak surfaces with rolled
     low end; derive boost AFTER shape; don't expect ROM-exact replication. **Open
     decision before the Browser: constrain the top-octave edge resonance, or let the
     ear gate it.**

3. **FACTORIZER BENCH = the anti-slop scoreboard** (`tools/factorizer_bench.py`,
   frozen `tools/factorizer_battery.json`). One command: fit each frozen target via
   FFI → pack → measure the SHIPPED (packed-decoded) in-band residual + stability →
   render SAW/TONE/PINK → scoreboard table with **delta vs the previous run** +
   `audition.html`/`overlay.png`/`scoreboard.json`/`history.jsonl`. Headline = mean
   in-band RMS over the 6 'primary' broad-shape targets. **Baseline = 6.335 dB.**
   The fitter is now FFI-exposed (`trench_fit_corner_from_magnitude` →
   `trench_ffi.fit_corner_from_magnitude(curve, sr)`; thin wrapper, no new DSP) — same
   rail a Target Browser rides. Rule: no fitter change ships unless the headline drops
   on the frozen battery AND the ear signs off; the fit stays DUMB (taste lives in the
   curve, never in fitter heuristics — that's the rejected treadmill).
   Bench surfaced weak spots to attack one-at-a-time (measured, not guessed):
   `two_formant_vox` 13.5 dB and `nasal_mid`/`scooped_2band` ~8 dB are the worst;
   `bright_lead` 0.56 dB and `three_formant_vox` 2.9 dB are clean. NOTE: the fitter is
   sensitive to target SAMPLING (same shape, 160-pt smooth vs 256-pt piecewise = 2.3 vs
   5.4 dB), so the battery freezes the exact sampling — compare deltas, not absolutes.

4. **TARGET BROWSER LOCKED AS THE MAIN AUTHORING LOOP.** `tools/target_browser.py`
   now supports the producer command form:
   `python -m tools.target_browser --template razor_shell --count 32 --seed 1001`.
   `tools/target_templates.json` now carries the seven production archetypes:
   `bright_vowel`, `bottle_cavity`, `broken_comb`, `small_metal_shell`, `vocal_bell`,
   `razor_shell`, `speaker_knocker`. Flow: pick template -> generate N whole
   4-corner bodies -> hard-cull broken candidates only -> render survivor audio
   (M0_Q0, M100_Q0, M0_Q100, M100_Q100, midpoint, Morph sweep, Q sweep, diagonal
   sweep) -> write `audition.html` with KEEP/MAYBE/REJECT, notes, and one-line
   `--keep` commands -> publish survivor `.bin` bodies to `bodies/generated/`.
   Keeper promotion preserves body/cart/seed/template/gate/notes in
   `dev/tmp/keepers/`. Exact verified run: `razor_shell` seed 1001 count 32 produced
   29/32 survivors, wrote `dev/tmp/target_browser/razor_shell_s1001/audition.html`,
   and published 29 `bodies/generated/gen_razor_shell_s1001_NN.bin` presets. Manual
   DRAW/WAV/corner/pole/P2K workflows are quarantine/debug unless Target Browser is
   blocked. Ear chooses; advisory scores do not.

---

## Now — 2026-05-26 · evening

**FORGE FITTER MADE HONEST + EXPORT PUT ON THE CANONICAL PACKED PATH.** The live fit
was a fixed-band spectral peak picker mislabelled (in `forge/AUDIT.md`) as "ARMA". Now
explicit, honestly-named modes — the fit is a STARTING POINT, not the boss:
- `dsp::FitMode` { **SpectrumPeak** (default, = old `formant_fit`, behaviour unchanged),
  **VoiceLpc** (pre-emphasis tilt-removal → order-14 LPC vocal tract; `lpc::fit_corner_conditioned_pe`),
  **Arma** (`arma::fit_corner_arma` called directly, not just fallback) }. `dsp::fit_window_mode`.
  `F` key / `FIT·<mode>` strip button cycle + re-fit loaded sources in place (A/B by ear).
- **Export authority fixed (the urgent rot):** `export_json` now emits **`packedWords`**
  (6×5 u16) as authority + `stages` as readback only; `save` also writes `authoring_slot.body240`
  (exactly 240 bytes). A loaded 240-byte body is preserved as `PackedCorners` and exported
  VERBATIM (no decode→repack). Tests: `export_goes_through_canonical_packed_path`,
  `loaded_240_byte_body_exports_verbatim`. `trench-core::lpc` now owns one `realize_poles_zeros`.
- **`aaa.wav` regression** (`cargo test -p trench-forge --bin trench-forge voice_regression -- --ignored`)
  → `dev/tmp/forge_voice_regression/` (source + 3 fit WAVs ×2 takes, level-matched for ear A/B,
  raw loudness in `comparison_report.json` + `audition.html`). **PROVEN why voice felt broken:**
  spectrum_peak misses the vowel (resid 33.7 dB, wastes poles at 188/211 Hz f0 mud); voice_lpc
  matches the envelope (10.7 dB) but renders near-silent — `top-6-by-radius` selection in `lpc.rs`
  picks HF hiss (6–9 kHz) over F1/F2 on a consumer mic (pre-emph 0.97→0.5 barely moved it); arma
  is loudest/decent (9.8 dB) but has 3–5 dB packed quantization drift. Fix direction = formant-region
  pole biasing + the log-grid nudge surface (fitter proposes, human relocates poles onto F1/F2 by ear).
- Full trace + stale-doc callouts: **`dev/tmp/forge_first_principles_audit.md`**. No UI redesign,
  no per-stage/Actor/BodySpec path, runtime + packing math untouched.

---

## 2026-05-26 · later (superseded above)

**240-BYTE PACKED BODY IS NOW THE SINGLE CANONICAL COEFFICIENT PATH.** One path:
`source (.body240 / JSON packedWords / packed-body-v1) → BodyBytes240 → PackedCorners → Cartridge/runtime`.
- `trench-core`: `PackedCorners::{from_body_bytes (strict 240, rejects ≠240), to_rom_bytes}` + `BODY_BYTES=240`;
  `Cartridge::from_body_bytes(name,bytes,boost)` + a private `from_packed(…)` assembler that derives the runtime
  DF2T fallback rows from the packed words (so `corners` can never disagree with `packed`; packed stays authority).
- `Cartridge::from_json` now serializes `packedWords` → the exact 240-byte layout → the SAME constructor.
  **`stages` are fallback/readback only — never coefficient authority when packed bytes are present.** Legacy
  stages-only bodies still load unchanged.
- FFI `trench_engine_load_body_bytes(engine,*u8,len)` (rejects ≠240, ret −4); JUCE `loadCartridgeBytes(…)` → the
  SAME runtime loader (NOT a special DSP path). Roster JSON and live audition bytes end in ONE PackedCorners path.
- Tools: `author_body.py --raw-out name.body240` (exactly 240 bytes); `teleport_stress.py --body` takes raw OR JSON.
- Proof: 7 Rust tests (`tests/body_bytes_canonical.rs`) — raw==JSON at 4 corners + midpoint, bogus `stages` ignored,
  partial/mixed/non-240 rejected, `interpolate(0.5,0.5)` bit-identical. `cargo test -p trench-core` all green;
  JSON-vs-raw teleport reports byte-identical.

**CORNER BENCH — `tools/corner_bench.py` (the poke-hear-keep loop).** Makes the bytes playable clay: load a body,
poke ONE packed `u16` word (`--corner/--row/--word/--delta`, wraps faithfully per `lerp_u16`), re-render by ear.
- Writes `dev/tmp/corner_bench/`: `current.body240` + `current.cart.json`, `sweep_slow{,_original}.wav` (slow
  Morph×Q Lissajous), 3 teleport WAVs, `audition.html` (audio FIRST, then hex table + mutation history + stability
  counters), `report.json`, session `history.json`. `--save-keeper NAME` → `dev/tmp/keepers/NAME.{body240,cart.json}`.
- Reuses the `teleport_stress` signal path (sounds like the runtime). Sound-first; no stage/Actor/BodySpec/LPC path.
- Verified: one word moves the WAV; JSON==raw before mutation; clean numerator poke = `nonfinite=0 / unstable=0 /
  max_r=0.980`; keeper writes 240 bytes + 4-corner packed cart. (memory `corner-bench-instrument`)

**FIRST CUT AT THE CAN OF WORMS — trench-core now owns decode+interpolate; Python calls it.** The packed math was
reimplemented in Python (`packed_interp.py`) + Rust runtime + Rust forge + ~30 tools, with no single owner — the
"haunted" drift where the bench and the plugin can judge different versions of the same corner (memory
`packed-math-triplicated`). Step 1 done:
- `trench-core` FFI: `trench_packed_decode(word)` + `trench_packed_interpolate(bytes,len,morph,q,out[30])` (kernel
  form, morph-first — the SAME `PackedCorners::interpolate` the player ships; morph/q cast to f32 like the runtime).
- `pyruntime/trench_ffi.py` — ctypes binding (prefers release dll, graceful fallback, skips stale builds missing the
  symbols). `packed_interp.packed_bilinear` now delegates to the core when present, pure-Python as fallback only.
- `corner_bench.py` prints `interp -> trench-core [..dll]` and has `--require-core`.
- **Proof: Python-reference vs Rust-core = BIT-IDENTICAL** across 8670 coeffs / 289 (m,q) points; bench renders
  end-to-end through the FFI, stability unchanged (max_r 0.980, CLEAN). Rust test `ffi_interpolate_matches_in_process`.
- **Still triplicated:** the Rust forge (`forge/src/dsp.rs`) and the ~30 tools' other math; response/render not yet
  behind the core. Next: route `kernel_to_biquad`/response + the forge through the same owner.

**FRONT-DOOR PITCH LOCKED (memory `trench-front-door-pitch`): "controlled destruction / stable machine for unstable
sounds."** Sell the feeling, hide the 240 bytes. Verbs not params (Morph = drag open · Q = pull tight · Teleport =
tear through · Slam = hit harder · 5D = widen the wreckage); bodies named as materials under stress (Glass Throat,
Rust Choir, Wire Mouth…); UI = industrial containment; killer demo = screaming audio, calm counters. **Next concrete
move:** seed the roster with material-named keeper bodies via the bench (poke → hear → `--save-keeper`).

---

## 2026-05-26 · earlier (superseded above)

**Direction landed: the instrument is a RESPONSE MANIFOLD.** A body = a response
(poles/zeros/energy/centroid/notches/phase) compressed to a stable packed 240-byte
body; its map position = where that response sits relative to others (response-feature
distance). No semantic categories — meaning (vocal/metallic) emerges in the listener.
The 4-corner Morph×Q is the trivial 4-point manifold; the real thing is a cloud of
response-bodies, continuous traversal. The dumb runtime is a weighted packed-`u16`
interpolator (4-corner bilinear = N=4). **The make-or-break is EDGE COHERENCE** —
traversal between neighbours must glide (registered), not crossfade / mush / pedestal /
blow up. First manifold: `tools/response_map.py` → `dev/tmp/factory/response_manifold.png`
(PCA of 24 bodies; designed bodies cluster, random-search bodies splay as extremes,
keeper_04 = a far outlier, which is why it's novel).

**PLAYER FIXED END-TO-END (juce-shell builds; VST3 installed both folders):**
- Real body switching — `TrenchBodyRoster.h` (single source of truth); `ParamID::body`
  via APVTS listener + AsyncUpdater (load on message thread). Boots a real body, not the
  stale `sonic_tables` (P2k_013) debug cartridge (dropped from the load path).
- **Removed `TrenchAuthoringSlot` from the player** — its 500 ms hot-reload was hijacking
  the Body strip ("wrong preset"). ONE load path now: Body strip → roster → loadCartridge.
  A "Forge Audition" roster entry hot-reloads the slot ONLY when selected.
- **5D/QSound wired** — was INERT (engine defaulted `SpatialMode::Off`, pinned `fiveD=0.75`
  did nothing). Added `set_spatial_mode` bridge binding; force QSound; 5D = Off/Narrow/Wide/
  Full → `set_space`.
- **Output makeup param** (dB, end of processBlock). **Bit Depth removed** (fake).
  **Boost reverted 4.0→1.0** (4.0 was a blind constant; clipped the saturator).
- **FX pane + MAIN|FX switch** (`TrenchFxPane.h`, `TrenchViewSwitch.h`). MAIN = scope only.
- **Cube morph/Q fix** — the MORPH wheel drives `ParamID::q` (documented slot swap, LEFT
  AS-IS, sonically right); only the corner-bank cube axes flipped so MORPH reads horizontal.

**AUTHORING ANSWER (after the detour: AI-invented coeffs = basic):**
- Talking Hedz = real frequencies placed exactly + **anchors + 2 crossing formants (s1/s5
  swap) + Q tightens all radii → ~0.999** (decoded from `sonic_tables.json`). Reproduced as
  `corner_words.hedz_body()`.
- **The missing input was a TABLE OF REAL FREQUENCIES.** `tables/vowel_formants.json`
  (Peterson & Barney) existed; added `tables/tube_resonances.json` + `tables/metallic_modes.json`.
- **DC-gain root cause LOCKED:** DC gain ∝ `c4·(c0−c1)`, `c0−c1 = 4·decode(w0)`; a low pole +
  high radius ≈ 1/(1−r)². Keep **w0≈0** → no pedestal by math. `lp`/random words rebuild the
  pedestal; `bp` (pole + DC-nulling zero) doesn't.
- **Filter-type settled by render:** all-pole (LPC `1/A(z)`) = faithful but max-low-end (source
  tilt baked in); **parametric peaking-EQ = flat baseline + formant bumps** (the real E-mu
  stage). For LPC voice fits use `allpole_words`, NOT `bp`. Word vocabulary (`word_probe`):
  w0=low-end · w1=high notch · w2=pole position · w3=sharpness · w4=level.

**NEW TOOLING (all no-rebuild — the working loop):**
- `tools/corner_words.py` — recipe→verbatim packed-16 words: `bp` `edge` `pas` `formant`
  `hedz_body` `allpole_words` `peak_eq_words` `build_toml(_words)`.
- `~/.claude/skills/forge-corners/SKILL.md` — parallel subagents author whole bodies as
  packed words, anti-ceremony. Made 10 factory bodies (gong/anvil/razor/scream/bloom/
  ascension/talkbox/vowelshift/siphon/spectre) in `bodies/`.
- `tools/make_morph_player.py` → `dev/tmp/factory/morph_player.html` — morph player +
  **word-sculpting bench**: real `lerp_u16` packed morph, live response + audio, editable
  240-word grid (nudge→render→name), link-across-corners, save-back TOML.
- `tools/midpoint_search.py` — RNG packed words, score emergent middle, gate stability +
  no-pedestal on ALL corners. Produced **keeper_04** (Tyson loves it; `bodies/keeper_04.cart.json`).
- `tools/lpc_to_body.py` — record → `lpc_extract` → all-pole body → player (record 2 DIFFERENT
  vowels for a glide). `tools/response_map.py` — the manifold.

**OPEN (next):**
- **The solver/compiler gap (the real one):** target response / real source / desired glide →
  SOLVE packed words → render the ACTUAL packed morph → listen → adjust. Fit a target morph
  SURFACE (corners + interiors) to packed corners so the middle glides. Pieces exist (fit + gates).
- **Edge coherence** = the manifold's core: formalize no-pedestal/stability/registration as an
  edge validator.
- **Voice F1 mis-placement:** LPC put F1=406 on an "ah" (should ~730) — check window/pre-emph/order.
- **Ship keeper_04 + good factory bodies** into the C++ roster (bake to assets/cartridges + roster).
- Peaking-EQ formant gains should track real prominence (equal bumps over-boost weak highs).

**Caught-AI-overshoots THIS session:** blind `boost=4.0`; "fitting the noise floor" (extraction
was fine — bug was `bp` vs `allpole`); per-stage filter-type arguing (the gap is target→packed,
not which EQ). Gemini brief errors: "4 bytes/stage" (it's 10 = 5×`u16`); "zero-math runtime"
(AGC + `saturate` + DC-block + per-block ramp exist and ARE the character).

---

## 2026-05-25 (prior session — superseded above)

**Doctrine locked** (see memory): distortion IS the filters, AT RUNTIME (the faithful
chip path incl. its `saturate` stage). The player is **transparent** — adds no effects
of its own — but ships user **power-params** (Morph, Q, Drive, q_sharp). ALL tricks
(wavefold, state-mutilate, physics, ARMA, modulation) are **authoring-only** and
collapse to ONE shipped thing: a **corner**. The morph **MIDDLE is read-only** — the
bilinear avg of the 4 corners; you author corners, the middle emerges. A coherent
(non-mush) middle needs **KIN corners** (shared formant skeleton, like the ROM frames).

**Forge wells UNIFIED — five faucets, one folder-tree menu.** Any corner from any
source feeds the 4 wells: `fit` (WAV→ARMA) · `design` (weapons) · `physics`
(vowel/tube/bell) · `rom` (talking_hedz) · `heritage` (69 E-mu MorphDesigner XML →
M0/M100 kin pairs). Non-WAV sources baked as `*.corner.json` by `tools/bake_well_corners.py`
+ `tools/bake_heritage.py`; loaded direct via `forge_core::load_corner`. Dropdown =
recursive folder tree (`main.rs` `MenuNode`), not a ComboBox. Forge now **starts BLANK**
(press L for the starter bank), **snaps the puck onto a loaded corner** (work one at a
time), **eases the response curve**; `q_sharp` 0.6→0.3, puck opens M0/Q0 (was hot Q50).

**Fitter (ARMA) overhauled** (`trench-core/src/arma.rs`) — it's the right fitter
(poles AND zeros; LPC can't notch). Changes: energy-weight by source magnitude (kills
bright tilt), fit the SUSTAIN not the attack (`dsp.rs sustain_window`), **gate zeros
sitting on their pole** (<1/3 oct — stops cancelling peaks into notches), `RMAX`
0.995→0.999 (match talking_hedz's razor poles), and **cepstral-lifter target** (keep
low-quefrency formant envelope, drop the pitch comb — fixes low-pitched voices that
were pitch-locking). LPC `PRE_EMPH`→0. `tools/morph_inspector.py` = prospecting rig
(4 corners → emergent middle + trajectory heatmap → writes slot).

**Forge Rust speedrun fix (2026-05-25 follow-up):** live Forge fit is now musical-first:
cepstral envelope → one pole actor per broad band (50-200 / 200-600 / 600-1200 /
1200-2500 / 2500-5500 / 5500-12000), shallow leashed zeros (Q0 ≈ 0.34, Q100 max 0.60),
frequency-scaled Q ceiling (high actors cannot razor-scream like low formants), and
zeros follow generated morph shifts only lightly. UI now has a compact speedrun strip:
PLAY/STOP, SAW/TONE/PINK, level, NEW, BANK, PUSH. Dropped/captured WAVs are analysis
input only; Forge no longer replays the source as the audition signal. `PUSH` writes
the slot while keeping the cascade live; `NEW`/R/N/Esc clears Forge state, source mode,
and level fast. Exported compiled-v1 keyframes now carry heritage `boost = 4.0` instead
of 1.0.

**Trench Capture VST added:** separate JUCE target `TRENCH_CAPTURE_VST3`, product
`Trench Capture`. It is a pass-through DAW insert with one big red CAPTURE button,
A/B/C/D slot buttons, input meter/progress, and a six-band rough pole preview. It writes
`Documents/TRENCH/captures/latest_A.wav` etc. plus timestamped copies and JSON metadata.
This is only a DAW tap; Forge remains the real fitter/authoring surface.

**Audits (3 subagents, confirmed):** rate 39062.5 = 10 MHz/256 is correct; shipping
player + Forge resample around a fixed 39062.5 island (in tune) — but RAW trench-core
test renders are +2.1 semitones sharp. Q100 = an INDEPENDENT stored corner (Z-plane);
`sharpen_corner` is only an empty-slot seed. The talking_hedz high "sheen" pole (~9-10k)
comes from SPEECH consonants/sibilants, not a vowel — capture via "ssss" or design it.

**BROKEN / OPEN (next session, priority order):**
- **PLUGIN AUDIO TOO QUIET — DAW VERIFY NOW.** Forge-side slot export now uses
  `boost = 4.0`; if FL still reads too quiet, investigate player output level
  (AGC / `saturate` knee / makeup gain / `loadCartridge` parse log).
- **Non-noise Forge audition fixed** — SAW/TONE/PINK selector is in the
  speedrun strip; pink noise no longer has to be the judge.
- **Hot-reload "didn't update"** — slot write verified (Forge Ctrl+S → valid compiled-v1)
  and the watcher (`TrenchAuthoringSlot`, 500 ms modtime poll) is sound; likely masked by
  the too-quiet output, OR `loadCartridge` parse failed — check the plugin log.
- **Voice fitting needs a BRIGHT/PROJECTED studio source.** Phone eee was low/dark:
  formants 30-40 dB under the fundamental + HF hiss → fit chased body + noise, missed the
  mids. The lifter + banded musical fit works when formants are present. Bring open /a/,
  bright eee, + a sibilant for sheen. His voice is LOW (~107 Hz f0) — that's body, an asset.
- Remaining fitter cleanup: DAW/listening proof of the new banded fit; then dead-root
  prune only if the musical-first path still leaves empty actors.

**Content (separate concern, NOT the instrument):** `tools/spellcast*.py` = crude
generative terminal + `spellcast_render.py` (MP4) for reels. Not a faucet.

---

## 2026-05-24 (prior session)

**The df2 VST builds, runs, and the author→play loop works.** JUCE plugin in
`juce-shell/`; build scaffold (cmake/, modules/, assets/, JUCE junction → `C:\JUCE`)
was borrowed from `Trench/juce-shell` (df2 = canonical repo; fixes live in df2).
Build: `cmake -S juce-shell -B juce-shell/build -G "Visual Studio 17 2022"` then
`cmake --build … --config Release --target TRENCH_Standalone TRENCH_VST3`. The Release
VST3 auto-copy to `C:\Program Files\Common Files\VST3` needs admin (only "error");
install it manually from `build/TRENCH_artefacts/Release/VST3/` to
`%LOCALAPPDATA%\Programs\Common\VST3\`.

Fixed/changed this session:
- **Distortion FIXED** — restored the missing output saturation stage
  (`engine.rs` `saturate()`, gated by `saturation_enabled`). The AGC `& 0xf` index wrap
  is verified-faithful hardware (`FUN_1802c04e0`), NOT a bug — the regression was the
  absent output limiter. Output 18× → 1.0, 0% clip. (memory `df2-vst-distortion-root-cause`)
- **Default load = M0 / Q0 / Input OFF** (clean; `morph` default 0.729 → 0.0).
- **Bitmap rollers restored** (`TrenchThumbwheel.h` renders `native_strip_129_96x14.png`).
- **Chassis seated** via code overlay (`TrenchChassisGlass.h`: recess + glass + scanlines).
  The PNG chassis is the IDENTITY — reinforce with code only; never pure-code/egui/webview.
  (memory `df2-chassis-is-the-identity`)
- **240-byte ROM layout verified VERBATIM** (Ghidra `FUN_1802c3d40` + −95.41 dB null of the
  captured `CPhantomRTFilter+0x2C0` dump). HW morphs in PACKED u16 space; shipping
  `cartridge.rs::interpolate` is decoded-domain (−53 dB approx). Packed-domain switch
  approved, NOT yet wired.

**Corner-building is now PHYSICS-FIRST.** Primary factory = the `physical-corners` skill:
whole 4-corner bodies from acoustics (tract / tube / modal), no WAV, no fitting. WAVs are a
FLAVOR option in the Forge picker (pack curated: 104 noisy drums archived, NMR re-encoded).
Invoke in Claude Code: `/physical-corners` (e.g. preset `morph_worlds`), or shell:
`python .claude/skills/physical-corners/physical_corners.py --preset <name>` (`--list-presets`).
It writes `~/Documents/TRENCH/authoring_slot.json`; a running TRENCH hot-reloads within ~0.5 s
(the Forge's Save does the same).

GUARDRAILS (hard — see memory):
- **NO stage/section authoring or tuning** — the month-long hellish loop. 4 whole corners
  like the ROM is the entire contract. (memory `avoid-stage-authoring-loop`)
- Chassis PNG = identity; never show DSP/EMU vocab on the surface.

Next (all whole-corner): audition the physics palette by ear, reshape WHOLE presets; optional
one-shots — real Story area functions for canonical vowels; wire the packed-domain morph.

---

## Runtime (frozen)

- 12-stage DF2T cascade, 4-corner bilinear in c-domain.
- Null vs X3 reference @ M50/Q50: **−95.41 dB**. Verified.
- Auth SR 39062.5 Hz, runtime SR 44100 Hz.
- Cartridge format: `compiled-v1`. JSON. Stable.

Do not touch.

---

## Forge pipeline

| Stage              | File                                          | Status   |
|--------------------|-----------------------------------------------|----------|
| Source ingestion   | direct wav load in forge UI                   | works    |
| 16-bit resample    | inside `tools/lpc_extract.py`                 | works    |
| LPC extract        | `tools/lpc_extract.py`                        | works ✓  |
| Modal extract      | `tools/modal_extract.py`                      | **missing** |
| Fit corner         | logic exists in `forge_hedz_calibration.py` + `pyruntime/forge_fit.py` | **needs unification into `tools/fit_corner.py`** |
| Pack corner        | logic exists, no clean CLI                    | **needs `tools/pack_corner.py`** |
| Build cartridge    | `tools/bake_cartridge.py`                     | works |
| Audition morph     | `tools/morph_interp_demo.py` + `tools/player.html` | available |

**Naming reconciliation done.** `tools/build_cartridge.py` and
`tools/audition_morph.py` do not exist in this checkout. The existing
files above are the canonical ones.

---

## Forge UI  (Rust — `forge/`, eframe/egui, the running tool)

"FILTER FACTORY / SOURCE FIELD." `main.rs` is egui-only; the source→body
workflow lives in `forge_core.rs`; fit/response/Q-law math in `dsp.rs`;
ARMA + LPC fitters in `trench-core` (`arma.rs`, `lpc.rs`).
- Four corner cards named **HOME** (M0/Q0), **MORPH** (M100/Q0),
  **TENSION** (M0/Q100), **MORPH+TENSION** (M100/Q100). HOME is the identity
  anchor; the others inherit HOME's six actors (via `align_to_anchor`) then drift.
- Centre frequency scope + XY puck roaming Morph × Q through the packed-u16 interp.
- Q ruleset slider drives the "tension seed": an unloaded Q100 corner =
  `sharpen_corner(Q0)` — tighter pole radii + sharper zeros.

Fitter/pack state (2026-05-23): ARMA (poles+zeros) primary, LPC fallback; **both
now pack into the [0,4]/[0,1] minifloat box cleanly** (gain distributed across
stages, ARMA numerator zeros min-phase-reflected — fixed the −98 dB pack collapse).
Small Talk formant gate (`cargo test -p trench-forge small_talk_gate`): `ee` PASSES
via LPC (F1/F2/F3 + clean pack); `ah` partial (ARMA hits F1/F2, LPC hits F3).
**Next: joint refit of the four corners warm-started from the tension seed,
preserving actor identity (the body-authoring step 5) — not yet wired.**

UI is fine. Don't add features. Don't add Inspect.

(STATE's "Forge pipeline" table above and the prior "THE SHAPE / PERFORM / GIVE A
SOUND" description are a Python-tools authoring path; the live tool is the Rust
forge here. If the Python pipeline is meant to be the authoring path instead,
say so — otherwise these two should be reconciled.)

---

## Bodies

| Body              | Body TOML | Cartridge JSON | Auditioned | Null pass |
|-------------------|-----------|----------------|------------|-----------|
| Speaker Knockerz  | ✓         | ✓              | ☐          | ☐         |
| Aluminum Siding   | ☐         | ☐              | ☐          | ☐         |
| Small Talk        | ✓         | ✓              | ☐          | ☐         |
| Cul-De-Sac        | ☐         | ☐              | ☐          | ☐         |

Small Talk is the v0 pipeline shakedown (ah.wav + ee.wav, Tyson's voice
or synthetic vowels). The other three wait until v0 is proven on Small
Talk.

Existing body files:
- `bodies/small_talk.toml`
- `bodies/small_talk.cart.json`
- `bodies/speaker_knockerz.toml`
- `bodies/speaker_knockerz.cart.json`

---

## Shell / viz

- **JUCE C++ shell:** exists in `juce-shell/` with CMake, plugin source,
  parameters, GUI assets, and DSP bridge files.
- **JUCE response/viz:** source exists (`TrenchResponseDisplay*`).
- **wgpu render:** no current implementation in this checkout.
- **cxx FFI bridge:** not started.
- **trench-core:** present and testable in this checkout.

Further shell/viz and bridge work follows the first body audition.

---

## Reference material

- `ref/canonical/` — 2 files currently present.
- `ref/p2k_skins/` — 3 files currently present (reference only, never ship).
- `ref/x3_displays/` — not present in this checkout.
- `ref/ghidra_extracts/morphlp_zero_table.json` — MorphLP RE data.

**Clean Room rule applies.** Reference behaviour, not coefficients.

---

## Validation tools

- `tools/null_test.py` — the ship gate. Threshold ≤ −60 dB at every
  tested M/Q position. Audition by ear is final.

---

## Known caught-AI-overshoots from prior session

For reference only. Don't repeat:

- Conflating ARMAdillo temporal glide with packed-canonical bilinear morph.
- Regularization / penalty proposals in the fitter (contradicts P2K behavior).
- Treating every anatomical mapping as forbidden. Current
  `bodies/small_talk.toml` deliberately uses vocal anatomy as body-level
  vocabulary; the warning is only against ad hoc stage-level intervention
  that bypasses the source-first fitter.
- Premature ARMA extractor (LPC works; ARMA gated by synthetic notch test).
