# CODEMAP

Where everything lives, how the shipping path connects, and what is real
vs. dead vs. scratch. Companion to `CLAUDE.md` (doctrine), `STATE.md`
(worklog), `NOW.md` (current arc), `REBUILD_PLAN.md` (the rewrite).
The **code** is always the authority; this map points you at it.

---

## The three trees + the repo

| Tree            | What it is                                                        | Language |
|-----------------|-------------------------------------------------------------------|----------|
| `trench-core/`  | **The frozen DSP core.** The one owner of the cascade, AGC, packed math, interpolation. Everything calls it via FFI. | Rust |
| `juce-shell/`   | **The player.** Consumer plugin: loads a body, morphs it, draws the chassis + screen. Transparent. | C++/JUCE |
| `forge/`        | **The authoring bench.** Private. Draw/fit/audition corners → export a body. Not shipped. | Rust/egui |
| `pyruntime/`    | Internal authoring runtime/reference (FastAPI). Not a third plugin. | Python |
| `tools/`        | ~100 authoring/audition/validation scripts. The wild west (see §5). | Python |
| `bodies/`       | The cartridge library. `rom/` = references; `generated/` ≈ 2000 search outputs; loose `.cart.json`/`.body240`. | data |
| `ref/`          | X3 wet renders + P2K skins. **Null-test reference only — never ships** (Clean Room). | data |
| `tables/`       | Authoritative reference data (Klatt formants, tube/metal modes, physical models). | data/py |
| `dev/tmp/`      | Scratch. ~31k files, ~3 GB (arma_source_pack audio). Gitignored under `dev/`. | scratch |
| `SESSION_LOG/`  | Dated session entries (written on close). | docs |
| root `*.md`     | `CLAUDE.md` · `STATE.md` · `NOW.md` · `REBUILD_PLAN.md` · this file. | docs |

---

## The shipping signal path (the minimum honest runtime)

This is the whole consumer audio path. Everything else is compiled out by
default (no `TRENCH_PLAYER_EXTRAS` / `TRENCH_PLAYER_DIAGNOSTICS` macro is set).

```
host audio
  → PluginProcessor::processBlock            juce-shell/source/PluginProcessor.cpp:146
      • safe-state: if !lastLoadOk → silence  (:160)   ← PL-3 bypass
      • pull morph/q from APVTS               (:172)
  → FixedRateTrenchIsland::process           dsp/FixedRateTrenchIsland.cpp:43
      • host SR ↔ 39062.5 Hz Lagrange SRC     (:73, :84)
  → TrenchDspBridge::process                  dsp/TrenchDspBridge.h:75
      • trench_engine_process_block (FFI)     → trench-core/src/ffi.rs:305
  → FilterEngine::process_block              (Rust)
      • Cascade::set_targets(morph,q) → PackedCorners::interpolate_biquad
        (PACKED-domain bilinear — the shipping morph; minifloat.rs:276)
      • AGC + chip saturation + & 0xF wrap    (all in Rust; agc.rs / cascade.rs)
  → output makeup gain (dB, 20 ms smoothed)   PluginProcessor.cpp:254
host audio out
```

**Shipping params:** `body`, `morph`, `q`, `output`, + `inputMode`
(OFF/SLAM/EOS). `slamDrive`, `fiveD`, `teleport*` are `#ifdef
TRENCH_PLAYER_EXTRAS` and absent in shipping (`TrenchParameters.cpp:53-96`).

**The character lives in the Rust core, not the shell.** The shell adds only
SRC + one user output gain. Confirmed: the f64 decoded-bilinear path
(`interpolate_legacy_stages`) is legacy-only; no shipping body uses it.

---

## Player components (`juce-shell/source/`)

**Live in the shipping editor** (`PluginEditor.cpp`):
- `TrenchResponseDisplay.{h,cpp}` — the central OLED **screen** (anatomy in §4).
- `TrenchThumbwheel.h` + `TrenchValueBox.h` — Morph & Q rollers + LCD readouts.
- `TrenchBodyStrip.h` — the TYPE strip; cycles bodies via `TrenchBodyRoster.h`.
- `TrenchChassisGlass.h` — glass/scanline overlay (painted last).
- `TrenchChassisLayout.h` — region rects, chassis PNG load, Documents override.
- `TrenchStyle.h` — **palette authority** (chassis tier + OLED tier) + fonts.
- `PluginProcessor.{h,cpp}` · `parameters/TrenchParameters.{h,cpp}` ·
  `dsp/FixedRateTrenchIsland.{h,cpp}` · `dsp/TrenchDspBridge.h` ·
  `dsp/TrenchCleanBody.h` (the `clean_audio` gate + baked Neon Vane body).

**Diagnostics-only** (compiled out by default): `TrenchFxPane.h`,
`TrenchViewSwitch.h`, the audition hot-reload timer, `TeleportEngine.h`.

**Separate target:** `capture_vst/` = the `TRENCH_CAPTURE` DAW tap, not the player.

### Dead / stray in the player (safe-to-remove candidates — verify, then cut)
- `dsp/TalkingHedzBodies.h` + `dsp/TrenchMorphFilter.h` — a C++ reimpl of the
  packed decoder/morph. **Duplicates the Rust core** (the triplication hazard);
  not in the build, included only by each other. → delete.
- `TrenchLookAndFeel.h` — in CMake but never `setLookAndFeel`'d. → wire up or cut.
- `TrenchAuthoringSlot.h` — the removed hot-reload class; dead. → cut.
- `TrenchShuttleControl.{h,cpp}` — compiled but never constructed (replaced by
  the thumbwheel). → cut.
- `TrenchStandaloneApp.cpp` — not in CMake; the Standalone uses JUCE's default
  window. → wire up or cut.
- `source/PluginProcessor.zip` (~12 MB) and `source/GUI/*` (stdout/stderr txt,
  preview PNGs, html studios) — build scratch checked into the source tree. → move out.

---

## 4. The central screen — what's actually drawn (the "garbage")

`TrenchResponseDisplay::paint` (`TrenchResponseDisplay.cpp:328`), a display-only
component pulling live coeffs over FFI each vblank. It stacks **eight layers**,
even in the clean shipping view:

1. **Multicolour grid** — blue verticals, red amp rules (+12/−12/−24/−36 dB),
   green 0 dB, magenta borders (baked image, `rebuildGridImage`).
2. **Magnitude trace** — thick white frequency-response curve. *The hero.*
3. **Output scope** — faint L/R waveform. *Off in clean mode.*
4. **Slam meters** — two chunky 48-segment L/R bars, top. **Wired to `slamDrive`,
   which is 0 in shipping → permanently inert decoration.**
5. **Sub-line** — cyan `M nnn Q nnn IN OFF ...` + magenta body name.
6. **Param bars** — three small M/Q/**S** segmented bars. **S is always dead.**
7. **Corner-bank pad** — 2-D pad with a `+` at (Morph, Q), four-colour edges.
8. **Vignette + occasional flicker.**

**Why it reads as garbage:** Morph and Q are shown **four times** (the chassis
thumbwheels+LCD, the param bars, the corner pad, the sub-line), and two whole
layers (slam meters, the S bar) are wired to a parameter that doesn't exist in
the shipping build. The hero — the response curve — competes with a Morpheus-era
multicolour grid and a pile of redundant readouts. A revamp = decide what the
screen is *for* (almost certainly: the response curve + minimal state), then
delete layers 3–7 rather than restyle them.

---

## 5. The core beyond the runtime, and the tools sprawl

**`trench-core/` carries far more than the shipping runtime.** Shipping needs
`cascade` · `minifloat` · `cartridge` · `engine` · `agc` · `ffi` · `response`.
The rest — `phantom_voice`, `motor`, `function_generator`, `qsound_spatial`,
`trench_matrix`, `cvsd_input`, `desk_drive`, `cluster`, `role` — are
authoring/experimental, and several (PhantomVoice, QSound, MorphDesigner) are
explicitly **out of scope this quarter** (`NOW.md`). Authoring fitters: `arma`
(poles+zeros), `lpc` (all-pole), `emu_resonator` (legacy Z-plane). 28 test files
guard null parity, packed math, and body-bytes canonicalization.

**`tools/` ≈ 100 scripts** — the biggest navigation fog. Canonical per job:
- **Generate bodies:** `make_class_bodies.py` (the producer front door) /
  `sweep_roster.py` (family batches) / `target_browser.py` (templates).
- **Audition through the shipped engine:** `render_audition.py` /
  `corner_bench.py` (poke-hear-keep). Test signal: `teleport_stress.py`.
- **Validate / null gate:** `null_test.py` (ship gate) / `parity_null.py` /
  `rust_cascade_parity.py`.
- **Pack / compile:** `corner_words.py` (→ packed u16) / `compile_raw.py` /
  `bake_cartridge.py`.
- **Judge shape:** `response_budget.py`.
- Everything else (`_thumb.py`, `_anatomy.py`, `forge_hedz_*`, `legacy/*`, the
  `*_rack*.py` reels) is one-off / exploratory / retired. **`legacy/` is the
  retired stage-first era — not imported by anything current.**

---

## 6. Repo state & hazards (as of forge-recovery)

- Branch `forge-recovery`, **14 commits ahead of `master`, 0 behind.**
- **`NOW.md` and `REBUILD_PLAN.md` are UNTRACKED** — the two most important live
  docs are not in git. So is much of `tables/`, `specs/`, `.claude/` config, and
  ~24 new body cartridges. **Work can be lost.** Highest-priority de-risk.
- **163 deletions staged but uncommitted** (mostly `dev/tmp/arma_source_pack`
  audio). Intent unclear until committed or reset.
- Build artifacts present but gitignored: `target/` (~3.3 GB),
  `juce-shell/build/` (~2.1 GB). `target_vst_static/` is **not** ignored.
- `dev/tmp/` (~31k files) is covered by the `dev/` gitignore rule.

> Before any git cleanup, re-verify state live (`git status`, `git check-ignore`)
> — these counts are a snapshot and git is the one place a wrong move bites.

---

## Pointers

- Doctrine: `CLAUDE.md` · Worklog: `STATE.md` · Current arc: `NOW.md`
- The rewrite: `REBUILD_PLAN.md` · Cartridge format: `cartridge.schema.json`
- Palette: `juce-shell/source/TrenchStyle.h` · Interp truth:
  `trench-core/src/cartridge.rs` + `minifloat.rs`
- Durable facts: the auto-memory `MEMORY.md` index
