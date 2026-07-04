# STATE.md

**This file is the live cache.** If it disagrees with the repo, fix it before
new work. Previous contents (May-era morph-interp state) superseded in full —
see git history of this file if needed.

Last updated: 2026-07-04, end of the sound-probe session.

---

## Shipped / installed right now
- Wheel: `proper_wine_deltas_257_298x80.png` (GLB sculpt + wine broad-bloom
  lamp + softened gaps/satin) — installed as the runtime strip, in the
  standalone and BOTH VST3 dirs. Seat: kSeat 1.00 / kSeatCY 0.50 on TRUE rects.
- Friend demo: `dist/TRENCH_DEMO_2026-07-04.zip` is THE one to distribute
  (03a/b/c superseded — 07-04 adds the rebuilt SRC island).
- Demo contents: 3 real P2K presets (Meaty Gizmo, Talking Hedz, Lucifers Q),
  5D button (QSound RE, nulls −30 dB vs reference), no dev tools.

## CLEAN THREAD — stage-anatomy study (start FRESH, minimal context)
Tyson called the prior session's analysis context-poisoned. A fresh session
does this with ONLY these facts: bodies = 240-byte packed files
(ref/p2k_variants/<name>/variant_0_*.bin = 4 corners x 6 stages x 5 u16 LE).
Pipeline (the ONLY legal one): words -> pyruntime.packed_interp.packed_bilinear
(corner dict keys "A","B","C","D", calls the real trench-core lerp_u16 via FFI)
-> kernel_to_biquad -> H_i(z), SR 39062.5. Plot convention (approved): six
thin stage curves + bold cascade product, dB vs log-Hz, white background, at
M0Q0/M100Q0/M0Q100/M100Q100/M50Q50. Reference script:
scratchpad stages_clean.py from 2026-07-04 (copy into tools/ if kept).
Goal of the study: understand the ROM stage grammar (roles, movers, zero
placement) to inform the 4 ship bodies. Do NOT carry over any other claim
from the 07-03/07-04 sessions without re-deriving it from packed words.

## NEXT SESSION — the simplification pass (medium depth, Tyson 2026-07-04)
Question on the table: "what am I overcomplicating — wrap it minimal, simple
but complex, modern and mature." The proposed shape, to be circled (not
swallowed whole) next session:
- THE LOOP: everything is intent → evidence → build → gate → listen → law.
- TWO living docs only: STATE.md (what is) + LAWS.md (what must be). All other
  docs = dated write-once artifacts, never consulted as truth (digest proved
  the corpus was mostly stale: docs/AUTHORING_CORPUS_DIGEST.md).
- ONE authoring path (morph_designer lineage), the other four retired from the
  mental map. One repo boundary question: fold trench-filters wells in or out?
- LAWS THAT COMPILE: convert the codifiable half of LAWS.md into one gate
  command (ladder span, island null, 240B/Schur/copy-risk, true-scale cell) —
  `trench probe|author|audit|render|ship` as the entire command surface.
- GUARD: simplification rides ALONGSIDE the ship stations, never blocks them.
  Station 1 (plugin leveler) and station 2 (bodies) stay the critical path.

## SOUND INVESTIGATION (2026-07-04) — "why isn't the sound there"
- FILTERS CLEARED. The chain was convicted, in layers:
- ISLAND FIXED (commit 24bbb1d9): old SRC was bare Lagrange, NO anti-aliasing
  — measured −17.5 dBc fold spurs, −6.5 dB @18k, 10.8 ms UNREPORTED latency
  (dry/wet combing). Now: 200-tap windowed-sinc + 19.3 kHz anti-fold guard +
  honest latency (735 vs 736 measured). Spurs −99 dBc, flat to 17k.
  Acceptance test: juce-shell/tests/IslandNullTests.cpp. 29/29 Catch2 green.
- AUDITION-CHAIN VOICING LAW (Tyson verdict on real material, "I like 3"):
  slam 0.15 + AGC cut cap 8 dB (debug knobs in trench-core engine.rs).
  The harness "awake chain" (agc 4.0 + slam 0.6) is a 24 dB brick-wall
  leveler — never render auditions through it again.
- OPEN CASE — plugin-chain leveler: the SHIPPING config (clean input, agc
  drive 1.0, slam 0.25 post) levels ~13.5 dB of 24, and the span SURVIVES
  slam=0 + saturation-off + AGC cap individually. Culprit UNIDENTIFIED.
  Next session: run probe_sound_chain's calibrated battery against the exact
  plugin config, walk the 13.5 dB home stage by stage. Do NOT tune blind.
- Probe harnesses (all committed): trench-core/tests/{probe_sound_chain,
  probe_agc_variants, probe_real_material}.rs; renders in dev/tmp/sound_probe/
  (probe.html, agc_variants/index.html, real_material/ break A/Bs).
- Envelope-follower fix from 07-03 (4ms/140ms time constants) is in all builds.

## Commits tonight (branch codex/rational-manifold-prototype)
- f3e70454 wine thumbwheel ship (strip, WheelControl, Theme, UiLayout, handoff)
- 7486177a display trace sub-pixel/CRT + label shadow + readout aging
- 0b0d27e6 TYPE popup navy skin, MOVE glass parity, ship VST3 sans diagnostics
- 8357bf20 wheel material deltas (gaps/satin; trench ember later removed)
- e4c2c0e7 wells re-measured to INNER openings: morph (120,691,422,98), q (119,873,424,106)
- 8580e3e8 friend demo: roster + FiveDTag
- bc92d2ca pitch wheel + demo fixes (Lucifers Q bake, envelope time constants)
- 818c377a REVERT pitch wheel → approved wine wheel

## Hard-won laws (violate = regression)
- Wheel = HORIZONTAL thumbwheel, ribs travel LEFT-RIGHT. Never a drum/scroll.
- Judge UI at TRUE SCREEN SCALE (wheel ≈ 194×45 px). Feature floor ~4 px.
  Contact sheets carry an unscaled true-size cell FIRST. Then a drag GIF.
- Contact sheet → Tyson approves → ONLY THEN install/build.
- GLB sculpt = source of truth (ancestor = ~11px UI screenshot, archived at
  `dev/tmp/thumbwheel_blender/SOURCE_OF_TRUTH_original_ui_screenshot.png`).
  Don't fix the funk — the funk is the design.
- Lamp law: X3 measured envelope (`x3_lamp_envelope.npy`) — dark at BOTH ends,
  grows in from left, widens/peaks mid. Ruby/wine family. No glow at rest.
- Release VST3 = build WITHOUT -Diagnostics (rig/lab are compile-gated).

## Open threads (priority order)
1. SHIP BODIES — the final phase. 4 intents proposed (Alkaline/FuzziFace/
   LucifersQ/Meaty rebuilt on measured wells; HRTF+DVTD rails done, circuit+
   modal sims pending). AUDIT FIRST: paste
   `C:\Users\hooki\trench-filters\AUDIT_SHIP_BODIES_PROMPT.md` into a fresh chat.
2. Wheel book still open. Gemini folder-dig prompt written (orientation
   screaming + Step-0 reference-proof gate). Best on-disk candidates per the
   true-scale sheet: `frames_glow_129` (amber head+ember trail, 88/129 frames —
   finish render + recolor to wine), `retired_129_backup`, oxblood
   `frames_spin_129`/`x3travel` bodies. Survey: `_asset_survey/CATALOG.md`.
3. Modulation feel: buffer-dependence FIXED (4 ms / 140 ms). Still open:
   push is up-only from the wheel position (pins at high morph) and per-body
   depths are generic for the P2K bodies. Test: morph low, Modulation on, drums.
4. Dead [1][2] pager chips baked into the glass art — paint out or re-enable.
5. HiDPI host-scale captures (125/150/200%) never actually verified.
6. `source/ui/` only partially tracked (FaceplateView/RigPanel/AuthorView etc.
   untracked) — a fresh clone will not build. Fold into next commit.
7. Prior-session uncommitted work: PluginProcessor/Editor extras, trench-core
   QSound, RigPanel/AuthorView, forge-web, docs.

## Key artifacts
- Trophy wall: `dev/tmp/thumbwheel_blender/CLAUDE_FAILURE_REPORT_2026-07-03.md`
  (+ Codex/Gemini siblings). Read before ANY wheel work.
- Pitch wheel preserved: `pitchwheel_final.blend` +
  `tools/thumbwheel/package_pitchwheel.py`.
- Wheel pipeline (tracked): `juce-shell/tools/thumbwheel/{apply_wine_glow_257,
  wine_wheel_deltas, package_pitchwheel}.py`, `WINE_WHEEL_HANDOFF_2026-07-03.md`.
- Build/verify loop: kill TRENCH/FL64 → on asset change nuke
  `build-ninja/juce_binarydata_Assets` + Assets.lib →
  `build-standalone.ps1 [-Diagnostics] [-Target TRENCH_VST3]` (retry once on
  transient LNK1104) → PrintWindow capture (powershell 5.1, scratchpad
  `cap_existing.ps1`) → judge at 1:1.
