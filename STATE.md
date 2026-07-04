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
M0Q0/M100Q0/M0Q100/M100Q100/M50Q50. TOOL (committed): `tools/plot_stages.py
<body> [--mode per_stage|overlay|both]` -> dev/tmp/stage_plots/.
First findings (re-derive, don't trust): Talking Hedz grammar = fixed crown
(st1, ~9.5k) / big mover (st2, 950->200 Hz + 0->+19 dB shelf) / two traveling
formants (st3, st4=bump-notch) / anchor (st5, ~4.5k) / FOUNDATION (st6:
DC +54 dB gain bank paying back the others' -5..-6 dB normalization; hot
source pole 200 Hz->1.8 kHz r.991-.999; TRUE unit-circle zero r=1.000 exactly,
travelling 6.4k->17.3k; Q tightens poles, zeros untouched). Authorship verdict:
hand-designed knobs (Morph Designer UI: shapes/freq/gain, two frames, Q law),
machine-compiled to quantized bytes — same model as our morph_designer path.
Goal of the study: the full stage-grammar dossier (Meaty, Lucifers, then the
16) to inform the 4 ship bodies. Do NOT carry over any other claim from the
07-03/07-04 sessions without re-deriving it from packed words.

MEATY + LUCIFERS dossier (2026-07-04, OBSERVED via plot_stages + the exact
pole/zero extractor `tools/stage_anatomy.py`, same legal pipeline):
- FOUNDATION stage-6 is now 3/3 universal: TRUE r=1.0000 unit-circle zero at
  every corner of every body so far (Meaty 10.9k/11.1k/9.4k/18.0k, Lucifers
  6.7k/6.9k/18.0k/8.8k), low hot pole + big DC gain bank (Meaty +47.6/+50.6 dB
  at M100; Lucifers +63.2 dB at M0Q100). Lucifers M0Q0 st6 has REAL poles
  (+0.753, +0.021) and M100Q100 st2 has REAL zeros — the real-root channel is
  live in ROM verbatim words (compile_body cannot express it; VERBATIM path).
- PARKED letters confirmed: Meaty M0Q0 = ONE sub letter (st1 pole 59 Hz,
  DC +70.8 dB → the lone +12 dB bump at 59 Hz) + four parked near-cancelling
  pole-zero pads (st2-5, all 10-16 kHz, flat -12..-14 dB) + foundation. A
  6-lane word can be a 1-letter word; the pads pay the gain ledger.
- THE Q FINDING (feeds METHOD.md's open Q100 radius law): for BOTH bodies the
  Q100 corners are NOT center-invariant pressure derivations of Q0. Meaty M0:
  zeros st2-5 IDENTICAL Q0→Q100 (10566/13401/14391/16287, same radii) but
  poles RELOCATE and pin to r≈.9996 (10329→2377, 12893→10349, 13615→16822,
  14670→13482); st1 flips 59 Hz sub → 13.5k razor ("inverts at mid-Q" is
  literally the Q axis crossfading two different photographs). Lucifers M0:
  Q100 is a wholly different frame — the violent ascending comb (poles 1377/
  2282/3250/4139 Hz at r .9867-.9986, each with a zero just below, +25 dB
  spikes) that doesn't exist at Q0. So in the ROM iconics, Secondary is a
  SECOND AUTHORED AXIS (zeros largely held, poles re-posed), not a global
  radius/gain offset. None of the three candidate Q laws (painter 0.35 QLINK /
  manual global-offset / hybrid) produces these corners. CLAUDE.md §6's
  "Secondary never moves centers" describes OUR morph_designer contract, not
  the ROM's observed practice — the contract needs a verdict: keep the safer
  derived-Q law for ship bodies, or allow authored Q frames (Tyson's call).
- Middles are alive (the product): Meaty M50Q50 +35 dB crown at 2.2k;
  Lucifers M50Q50 +39 dB at 1.8k with a chained descent. Sheets in
  dev/tmp/stage_plots/.

CIRCUIT RAILS CORRECTION (2026-07-04 late, OBSERVED): trench-filters
out/circuit_rails/circuit_rails.json pole centers are LPC ARTIFACTS — the
complex "resonant ladder" (3238/4323/5999... Hz) does not exist in the
circuit. The ANALYTIC tube-screamer TF (circuit_frf.py law, component-verbatim)
has only real roots: DC unit zero + 15.6Hz pole (input coupling), mid-hump
zero 155-230Hz vs pole 720Hz (bark 13.3->15.9dB with drive; DIES at hot bias,
r~.998 pole/zero collapse), near-Nyq C4 corner descending with drive. Circuit
morphs that are real: DRIVE (bark grows + top closes) and BIAS (voice lives/
dies). Do not source pole centers from circuit_rails.json; use the analytic
roots (see sheets/FUZZ_E_SCREAMER.json, FUZZ_F_STARVED.json). Fuzz Q policy:
hot-at-rest razors can't meet the 5.7dB Qbloom floor (radius cap) — fuzz
Secondary = tone/canyon motion per the manual, exception documented.

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
