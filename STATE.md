# STATE

What exists. What's broken. What's next. Update on every code change.

---

## Now — 2026-05-26 · later (read this first; supersedes below)

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
