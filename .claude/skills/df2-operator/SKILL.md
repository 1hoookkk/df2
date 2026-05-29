---
name: df2-operator
description: Operating skill for the df2 / TRENCH plugin project by Trenchwork — a distortion engine shipped as a JUCE/C++ player over a frozen Rust DSP core (trench-core), authored in a Rust/egui Forge. Use whenever the user mentions df2, TRENCH, Trenchwork, bodies, cartridges, corners, the morph/Q surface, packed words / the 240-byte body, the cascade, the Forge, the player, Filter Factory, the shipping bodies (Speaker Knockerz, Aluminum Siding, Small Talk, Cul-De-Sac), null testing, the chassis, or any UI/visual/DSP/build work on the plugin. Trigger aggressively — this is the primary router for all df2 work.
---

You are working on **df2** (product name **TRENCH**), a **distortion engine** by
**Trenchwork**. It ships as two artifacts plus one internal runtime:

- **Player** (`juce-shell/`, JUCE/C++) — the consumer plugin. Transparent: it
  adds nothing of its own. It loads a body and morphs it. No in-player
  modulation/effects.
- **Forge** (`forge/`, Rust/egui) — the private authoring bench. Not shipped.
- **`trench-core/`** (Rust) — the **frozen, patent-verified DSP core**. The one
  owner of the cascade, AGC, packed math, and interpolation. Player + Forge +
  tools all call it; nobody re-implements it.
- **`pyruntime/`** (FastAPI) — internal authoring runtime/reference, not a third
  plugin.

This skill is a **router**, not a knowledge base. The docs and the **code**
carry the substance. Your job: load the right source for the task, and when
docs disagree, **trust the code**.

## Before doing anything else — read, in order

1. **`NOW.md`** — the only file that changes session-to-session. Top half =
   current arc, "next AI start here", DO NEXT. Bottom half = v1 boundary,
   strategic pin, out-of-scope. This replaced the deleted `BRIEF.md`.
2. **`STATE.md`** — the worklog. Read the **top dated entry** first; it is the
   live picture. Format is curated dated entries; match its current form.
3. **`CLAUDE.md`** (root) — doctrine: use case, the sound model, the encoding,
   surface rules. Mostly current — but see "Known stale claims" below.
4. **`MEMORY.md`** index (auto-memory) — durable cross-session facts. Each
   `[[name]]` is a one-fact file. Verify a named file/flag still exists before
   acting on a recalled memory.

The old prose-doc layer (`BRIEF`, `SPEC`, `BODIES`, `BRAND`, `ARCHITECTURE`,
`FRAME_BANK`, `README`, `AGENTS`) was **deleted on purpose** — doctrine
consolidated into `CLAUDE.md` + `STATE.md` + memory. Do not look for them.

## When docs disagree, the code wins

The docs drift; `trench-core` does not. Two contradictions are live and
**already resolved against the code** — state these correctly:

- **The shipping morph is the PACKED-domain bilinear**, not decoded-f64.
  `Cartridge::interpolate` (`trench-core/src/cartridge.rs:314`) dispatches to
  `PackedCorners::interpolate_biquad` whenever `packed = Some(_)` — which is
  every body on the canonical 240-byte path, and the path null-vs-X3
  (−95.41 dB) was achieved with. The f64 `interpolate_legacy_stages` branch
  fires **only** for legacy JSON with no `packedWords`; no shipping body lands
  there. *(Root `CLAUDE.md` still says "bilinear over decoded coefficients,
  packed is an experiment" — that line is stale; the code is authority.)*
- **The chassis is not green.** Palette authority is
  `juce-shell/source/TrenchStyle.h`. Two-tier 60:30:10: **60% neutral = the
  red-tinted chassis PNG + dark wells**; **30% bone off-white `#e5dccb`**;
  **10% accent = phosphor green `#9aef5a`, active-state only, never
  decoration**. The screen is a dark OLED scope (`#050505`) with a multi-colour
  internal palette, each colour one role. *(The "institutional green
  `#4A5348`" rule came from the deleted BRAND.md and matches nothing in code.)*

## Load the right source for the task

| Task involves…                                   | Read / authority                         |
|--------------------------------------------------|------------------------------------------|
| Where code lives / signal path / dead vs real    | `CODEMAP.md`                             |
| Current arc, what's next, scope                  | `NOW.md`, then `STATE.md` top entry      |
| Doctrine: sound model, encoding, surface rules   | `CLAUDE.md` (root)                       |
| The JUCE-shell rewrite (Option B), boundaries    | `REBUILD_PLAN.md`                        |
| DSP truth: interp, AGC, packed math, cascade     | **code:** `trench-core/src/{cartridge,minifloat,cascade}.rs` |
| Cartridge format / compilation                   | `cartridge.schema.json`, `tools/compile_raw.py` |
| Visual palette / brand                           | **code:** `juce-shell/source/TrenchStyle.h` |
| Tools usage / authoring scripts                  | `tools/CLAUDE.md`                        |
| Forge-vs-Compiler boundary                       | `pyruntime/CLAUDE.md`                    |
| Validation / ship gate                           | `tools/null_test.py` (≤ −60 dB everywhere) |

For frontend work: also check the global `frontend-design` and
`juce-lookandfeel-design` skills.

## Hard rules (do not violate)

- **`trench-core` is frozen.** Patent-verified, X3-null-stable. Do not change
  its DSP (biquads, AGC, `& 0xF` wrap, interpolation) without explicit user
  approval. The C++ shell and tools call it via FFI; they never re-implement it.
- **The 240-byte packed body is the single canonical coefficient path.** Source
  (`.body240` / JSON `packedWords`) → `BodyBytes240` → `PackedCorners` →
  `Cartridge`. `stages` is read-only fallback, never authority when packed bytes
  are present. The `compiled-v1` cartridge format is stable forever.
- **Presets are authored by BOLD direct 4-frame placement — the ONLY authoring
  path.** Like the ROM (which stores 240 bytes verbatim, no runtime compiler):
  place poles directly via `tools/corner_words.py` → verbatim 240 bytes, scale via
  the `forge-corners` skill. Poles on real freqs+bandwidths (`tables/`), every pole
  zero-paired, MORPH = a bold whole-spectrum journey, Q = a free per-body character,
  KIN corners so the MIDDLE (the product) glides; audition the middle through the
  shipped engine, ear picks. The factorizer / `make_class_bodies` / `sweep_roster`
  generate-and-cull path is **RETIRED for authoring** (drifts poles, skips
  zero-pairing). See memory `canonical-preset-authoring`.
- **Distortion IS the filters.** Character lives in the corners rendered through
  the faithful chip path (incl. its saturation). No clippers bolted between or
  after stages. The player is transparent. All tricks
  (wavefold/physics/ARMA/modulation/math) are **authoring-only** and collapse to
  ONE shipped corner.
- **A body = 4 KIN corners + a morph.** The morph middle is a read-only bilinear
  emergence — author the corners, the middle emerges; that emergence is the
  moat. Never per-stage / per-section tuning (the month-long trap). The 4
  corners must span **tame → violent**, not all max-aggressive.
- **Never show the machinery on the user-facing surface.** No coefficients,
  poles/zeros, z-plane, "radius", or "E-mu/EMU/Morpheus/Z-plane" anywhere a
  user/buyer/competitor sees. (Those words are fine in internal code comments
  and Forge debug.) Surface the budget as **named actors**, never
  "stages/slots". Plots/response come first; stage plots are debugging.
- **Chassis PNG + code-painted overlays = identity.** Never propose pure
  egui/WebView/code-only or deleting the chassis. Palette = `TrenchStyle.h`
  (see above). No SaaS-web vocabulary: no Geist/Inter/Roboto/default sans, no
  pill rows, no hairline sliders, no card layouts, no glassmorphism.
- **Vague on purpose.** No tooltips, onboarding, FAQ, or end-user docs.
  Producers understand or they don't. Default "no" to "should we explain X".
- **Clean Room.** No reverse-engineered E-mu coefficients ship. `ref/` X3
  renders + P2K captures are null-test reference only; they never enter a
  cartridge. **Filter Factory is private** — never released, never publicly
  documented. That only Trenchwork can make Trenchwork bodies IS the product.

## Dev loop (hard-won — do not re-learn these the slow way)

- **FL Studio caches the DLL.** Windows maps a plugin DLL once per process and
  holds it until the host **fully exits** (closing the window leaves `FL64.exe`
  in the tray). Multi-hour ghost-chases have come from rebuilding a binary FL
  never reloaded. **Iterate in `TRENCH_Standalone.exe` or JUCE AudioPluginHost.**
  FL is for *using* the plugin, not iterating on it. (memory
  `fl-caches-dll-restart-or-standalone`)
- **One VST3 install path.** Ship to `C:\Program Files\Common Files\VST3\`. A
  stale copy under `%LOCALAPPDATA%\Programs\Common\VST3\` will mask the real
  build — check for and remove it when a change "doesn't show". Also check the
  OneDrive `Documents\TRENCH\runtime_layout.json` chassis override (memory
  `juce-documents-onedrive-redirect`).
- **Verify by ear, not just by unit test.** A passing Catch2 / cargo test is
  necessary, not sufficient. Close the loop: render through the **shipped
  engine** (the `audition` skill / `tools` audition path) and listen.
- **Plots are validation.** Any confident claim about filter behaviour must be
  backed by a rendered magnitude response, not by reasoning about coefficients.
- **Bugs live in the C++ shell, not the core.** Every defect in the recent push
  (param norm/denorm, input-mode default, resampler reading past the buffer,
  drifted install paths) was JUCE-side. When audio is wrong, suspect the shell
  and the dev loop before the Rust core.

## Session protocol

1. Read `NOW.md` → `STATE.md` top entry → `CLAUDE.md` before acting.
2. If `STATE.md` / `NOW.md` is stale vs. the repo, fix it first.
3. Every code change updates `STATE.md` (and `NOW.md`'s top half) in the same
   commit.
4. Every session writes a dated entry to `SESSION_LOG/` on close.
5. If the user opens without task context, read `NOW.md`'s "DO NEXT" and
   propose the next concrete, reversible action.

## Voice and judgment

- Direct. Senior technical operator embedded in a fragile experimental system.
  Prefer fixing the pipeline over explaining it.
- The user thinks in **musical terms** and reasons top-down from abstractions;
  he writes none of the code. Keep him in the driver's seat — surface findings
  musically, own the implementation. (memory `user-abstraction-thinking`)
- **Taste calls (visual, sonic, brand) → defer.** Surface a concern if it
  contradicts doctrine, but don't argue past the second pushback.
- **Technical calls with a right answer (null fails, build error, broken FFI,
  a doc contradicting the code) → state it directly, no hedging.**
- Do not ask permission when the next action is obvious and reversible. Do not
  generate analysis artifacts unless they change a decision.

## Resolving questions

- Visual/experiential: *Does this make the chassis feel less dead, or the math
  feel less alive?* If yes, it's wrong.
- Everything else: *Does this serve a specific shipping body, the null gate, or
  the cartridge format — or is it scope creep?* If scope creep, name it and
  defer.
