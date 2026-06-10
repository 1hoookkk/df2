# df2 — PRESET LOOP HANDOFF

Paste this whole file as the opening message of a new Claude session. It is
self-contained. Read the repo `CLAUDE.md` and `AGENTS.md` first; they govern. This
handoff is the live state and the plan as of 2026-06-10.

---

## THE GOAL (one thing)

Ship **4–7 P2K-style morphing-filter presets worth paying for** for the df2 plugin
(a $49 destructive Z-plane morph filter — 808s, bass, vocals, breaks; "expensive,
violent, distinctive"). **The plugin is FROZEN.** It already builds, loads bodies,
and runs the real engine. No plugin/UI/feature work until the presets exist — that's
the comfortable-tractable trap that has kept this project's preset bank EMPTY after
months. The presets ARE the product. Nothing else matters right now.

## THE DEAL — who does what (the core realization, do not forget)

**Claude is a deaf maker. Tyson is the ear.** Proven this session: every body Claude
generated/matched/composed FAILED Tyson's bar (the reference-siblings were "not
complex enough"; the null-grammar came out flatter still; the search makes
"corridor-passing" = competent, not iconic). Root cause: **Claude cannot hear** — it
reasons on the magnitude curve, but "worth paying for" is an aesthetic judgment that
lives in the ear, and the numeric proxies are broken (see SCORER below). So:

- **Claude** = tireless, structurally-literate generator. Floods *aimed* candidates
  (right family, real frequencies, scaffold+voices, stable) at scale. Drives all code,
  builds, audits, banking. Plateaus at "promising"; cannot reach "worth money" alone.
- **Tyson** = the discriminator. Producer, self-taught from ZERO DSP/coding into this
  — has real intuition (he spotted the held-zero anchor-grid by eye). His ear catches
  the alive ones and says *why*; that steers the next flood. He KEEPS the keepers.

**The loop:** Claude floods the right neighborhood → Tyson's ear catches the 3 that
are alive + tells why → Claude floods around those → Tyson KEEPs the worth-money ones.
Generator + discriminator, and the discriminator must hear. This is a functional
requirement, not flattery.

**Hand-make vs audition (resolved 2026-06-10):** auditioning Claude's floods ALONE is
the weaker bet — you cannot curate in quality the generator can't produce, and the
floods proved competent-not-iconic. The stronger path is **hand-shaping with Tyson's
ear INSIDE the making loop** (make→hear→adjust→hear, aimed at an intention) — that's
how E-mu made all 50. So the real move is the hybrid: **Claude seeds a strong starting
body (right move, scaffold+voices, real rails); Tyson hand-shapes it alive by ear; KEEP.**
The flood is a head start, not a lottery — quality gets MADE in the shaping, not FOUND
in the pile. BUT: don't over-conclude this from the armchair — the only real test is
Tyson's ear, which hasn't run yet. **Make ~3 by hand, audition a handful of floods,
let the ear say which path is real, then follow it.** Don't perform false confidence in
this no-ground-truth space (a recurring Claude failure here — see HOW TO WORK below).

## THE IMMEDIATE BUILD (the only thing to build — keep it lean)

The project never closes the loop at the END: the gap between "I like this" and "it's
a finished, shippable preset" is full of code (compile, 17×17 audit, name, bank, wire
to roster) that a producer can't/won't touch. **Close that gap with ONE button.**

Build the **lean end-to-end surface** — and ONLY this (do NOT build the full
"console"/stream-browser; that's more tooling before a preset exists, the exact trap):

1. The **Filter Designer** already exists and works: `forge-web/filter-designer.html`.
   Six typed sections (type · freq A → freq B · gain · Q), big Morph + Q, live audio
   through AGC→Mackie→QSound, engine-true curve. It compiles via the WASM binding
   `forge_pack_typed` → trench-core `pack_typed_body` (one owner; Python mirror is
   `trench_ffi.compile_body_typed`).
2. **DONE (2026-06-10): Load a seed** — dropdown on the designer, fed by `/seeds`
   (`forge-web/data/designer_seeds.json`: the 5 recipe moves on real rails, plus every
   banked body's typed source). Claude floods aimed candidates by appending to that JSON.
3. **DONE (2026-06-10): KEEP / KILL** — `/keep` on `tools/forge_author_server.py`
   recompiles the cards through DLL `compile_body_typed`, **nulls vs the browser WASM
   bytes** (free encoder-drift check on every keep), runs the 17×17 packed audit
   (FAIL = not banked), writes `desk/bank/v1/<slug>.{body240,cart.json,png}` + a
   `BANK.md` table row, drops the cart in `Documents/TRENCH/bodies/` and publishes the
   live **Forge Audition** slot (hear it in the plugin immediately). Verified end-to-end
   by a real browser click (artifacts byte-equal a fresh DLL recompile; smoke rows
   removed). `/kill` appends label + words to `desk/KILLS.md`. The named roster row
   still needs the per-keeper rebuild (BANK.md says so) — that's Claude's job after a
   verdict, not a button. **Serve: `python tools/forge_author_server.py 8141` → open
   `/filter-designer.html`** (plain http.server has no /keep backend).

Then **STOP building.** The 4–7 presets do not come from a better tool — they come
from Tyson doing reps on this surface. The surface only removes every non-taste
obstacle so his ear is the single variable.

## THE MODEL — how these filters actually work (don't re-derive)

- **A pole rings; a zero kills.** Pole = a resonant bump/peak. Zero = a notch/hole.
  That's the whole vocabulary. A body = 6 sections = 12 poles + 12 zeros.
- **The morph slides them between two frames.** Frame A and Frame B; Morph drags every
  pole/zero from its A position to its B position. (Rossum patent US5170369, verbatim:
  `C(x) = Ca + x(Cb − Ca)` on the **log-encoded** 16-bit coefficients. The minifloat
  IS that log-encoding. Our engine = the patent, proven.)
- **The middle is EMERGENT.** The filter at morph 0.5 is NOT the average of the two
  curves — it's a brand-new filter computed from halfway *coefficients*. You design the
  two endpoints; the interior is a consequence you can only DISCOVER by sweeping. The
  "magic in the middle." No continuous kernel reproduces it (the corners match
  bit-exact; the interior diverges 19–23 dB).
- **Scaffold + voices** (the construction pattern, confirmed from the references):
  - **Anchors** = roots that DON'T move: foundation low-shelf (held), air high-shelf
    (held), and **parked notches** (a fixed cut grid). e.g. dj_alkaline parks 4 zeros
    (4162/7042/14901/16848) while every pole sweeps.
  - **Voices** = roots that travel: 1–3 peaks / a lowpass leader, freq A ≠ freq B.
  - **Character = a ringing pole sliding across a fixed killing zero.** Aim a voice to
    sweep THROUGH a parked notch — that crossing is the tear/squelch/scream. Our flat
    bodies failed because they were all-voices-no-scaffold (nothing to cut against) or
    notches in dead bands (no voice crossing them).
- **Q = pole radius (sharpness/bloom), NOT frequency.** Morph moves frequency; Q
  sharpens. Real iconic bodies BLOOM 6–34 dB under Q (it's a co-leader, not subtle).

## THE RECIPE — how Claude should aim its floods

The **moves** (each lands on REAL frequencies — never invent poles):
- **TALK:** two Peaks on a vowel formant pair in Frame A → morph to another vowel in B.
- **SWEEP:** one Lowpass, freq A 7000 → freq B 1500 (the filter closing = the leader).
- **SCREAM:** a Peak in the tear band (~4130) with Q sharp, morphing.
- **BASS:** Low-shelf at 134 held (A=B), +6, movers riding above it.
- **ANCHOR-GRID:** 1–2 Notches parked (freq A = freq B) at cut rails (4130, 8250) +
  Peaks/LP sweeping THROUGH them.

The **good Hz** (real resonances, `docs/study/frequency_rails.csv` — TYPE THESE, not
round numbers):
- foundation/hold lows: **134, 200**
- mouth / vowel (the talk): **780, 1090, 1420**
- bite / presence: **2180, 2220, 2840**
- tear / scream edge: **3790, 4130, 4440, 5450**
- air (top): **8250, 16500**
- vowels (two peaks): ah **700+1090** · eh **530+1840** · ee **270+2290** · oo **300+870**

## SCORER — do NOT trust the objective to pick (proven inverted)

Measured all 50 references + our candidates: the objective scalar is **inverted** —
the boring factory templates score 3.5× HIGHER than the iconic references (151 vs 541),
because it rewards extremity (span/morph/Q/motion) and iconic ≠ extreme. The ONLY
metrics that separate iconic from plain: **every section carries a zero** (1.0 vs 0.77)
and **~half the zeros are local tears** (0.51 vs 0.12). The gate is a good FLOOR
(stable/finite/it-moves); the objective is a bent CEILING. The scorer literally cannot
tell Tyson's "flat" siblings from iconic — they match on every metric. **Only the ear
distinguishes.** Don't optimize the objective; use the gate as a floor, flood, let the
ear pick.

## ROSSUM METHOD (RE'd this session — `docs/study/rossum_method_RE.md`)

- The morph/engine = Rossum patent US5170369 (confirmed verbatim). Settled.
- The **Filter Designer** = the literal heritage E-mu tool: 6 typed designer-sections,
  two frames (low/high freq+gain per section), morph between. `pack_typed_body` is it.
- Complex iconic types (TalkingHedz, vowels, AceOfBass) were **hand-made by ear** —
  E-mu's own words: "creating the complex filtering is difficult and very time
  consuming, we created 50 and installed them in ROM." No algorithm to recover.
- **Peak/Shelf Morph** (Millennium type) is the ONE fully-documented parametric type
  (Dillusion tutorial): per frame {FREQ, SHELF=−64 LP↔0 shelf↔+63 HP, PEAK gain}. The
  DnB/reece bass workhorse. A clean-room original Peak/Shelf compiler is a strong
  optional path for the bass lane.

## TWO ENCODER PATHS (don't conflate — caused a 59 dB bug once)

- **CONSTRUCT** = `trench_ffi.compile_body` / `compile_body_typed` (pole/zero or typed
  designed in Hz). The GUI/designer path. Byte-identical to the WASM. ROM round-trip
  FAILS through it (subset space — no real-roots/baked-gains/r=1 zeros), so it CANNOT
  reproduce the references — that's expected, not a bug.
- **VERBATIM** = raw words (the QD search packs this way via `coeffs_to_words`; ROM
  storage). The references live here. Do NOT reroute the search through compile_body
  (it would re-level/clamp and orphan archived genomes). One design, one path, audit
  the bytes. (`docs/study` + memory `one-true-encoder-compile-body`.)

## ASSETS THAT EXIST

- **Filter Designer:** `forge-web/filter-designer.html` (+ `js/pack-core.js` `packTyped`,
  WASM `forge_pack_typed` in `forge-web-wasm/src/lib.rs`, rebuilt
  `forge-web/wasm/forge_web_wasm.wasm`). Serve: `python tools/forge_author_server.py 8141`
  (backend for seeds + KEEP/KILL; plain http.server serves the page but no banking).
  (To put on phone: cloudflared tunnel to that port — tunnels are ephemeral, re-create.)
- **The desk** (Tyson's only surface): `desk/` — `bank/v1/BANK.md` (the product ledger,
  currently EMPTY — that's the whole problem), `KILLS.md`, `sheets/` (judgment sheets).
- **Judgment sheets** (plot-first, on the desk): `wave1_harvest`, `wave2_corridor_qfix`,
  `wave3_clean` (note-landed, anti-random-peaks), `siblings_of_the_best`, `grammar_proof`.
  60+ candidates already made, NONE judged/kept yet.
- **Study (clean-room):** `docs/study/` — `P2K_atlas.{md,json}` (all 50 decoded),
  `frequency_rails.csv`, the row-vocabulary, the Rossum RE, the held-pole analysis.
- **Search:** `python train.py model=clean_wave_landed` (note-landed + rails + Q-cap +
  corridor gates — the musical wave) / `model=overnight` (corridor) / `model=smoke`
  (fast). Distill a run: `python tools/distill_finalists.py <run_dir> 20 2`.

## WHY THIS IS GENUINELY HARD (and what's already settled — don't reopen)

This is one of the hardest shapes of problem to point an AI at, and naming it keeps a
new chat from burning effort in the wrong place. **The target — "sounds worth paying
for" — is perceptual, and Claude can't hear.** The fitness function lives in a sense
Claude doesn't have; the inverted scorer is the symptom (the field has NO computable
measure of "good"). So Claude is reliable on the COMPUTABLE/VERIFIABLE half (engine,
nulls, structure, stability, floods) and must stay HONEST-uncertain on the PERCEPTUAL
half (which body is iconic) — that's Tyson's ear, always.

**Already settled — do NOT reopen these (they are verified, not perceptual):**
- **The engine.** Fully RE'd from the binary (Ghidra: `FUN_1802c3d40` = linear u16
  minifloat morph lerp) AND independently confirmed by Rossum's patent
  (`C(x)=Ca+x(Cb−Ca)` on log-encoded coeffs). Ported to trench-core, `plot==engine`
  0.0000 dB. **Do NOT open Ghidra again** — the player binary does not contain the
  authoring/design method (that was a human at E-mu's Filter Designer, by ear). The
  thing we still need is perceptual, not in the binary. Reopening Ghidra would be
  another comfortable-tractable detour away from the hard (ear) work.
- **The encoders nulled.** `compile_body` == WASM GUI byte-exact. **NEW: the typed
  designer compiler is nulled too** — WASM `forge_pack_typed` == DLL `compile_body_typed`,
  byte-identical (0 diff). The Filter Designer's browser bytes ARE what ships.

**Remaining verification is future, not now:** ~~the KEEP button's 17×17 audit path~~
(DONE 2026-06-10 — built + verified by a real browser-click keep; FAIL verdicts do not bank). The closed-loop compiler's old
Early-Rizer 2.65 dB fit "ran on the rogue encoder — re-verify through compile_body" IF
that surface-fit tool is ever used (it's NOT on the preset-loop critical path).

## CLEAN-ROOM + HOW TO WORK WITH TYSON

- **Clean-room:** study the 50's behavior; ship ORIGINALS in their spirit. NEVER copy
  coefficients, packed bytes, names, or tables. Buyers have never heard the source.
- **Tyson is a producer, self-taught from zero DSP/coding** — but he now understands
  IIR/cascade/the morph fundamentally. He is PAST the understanding phase and wants to
  MAKE. Don't ship-pressure when he's learning, but the call this session: build the
  lean loop, then he makes. **Lead with PLOTS** (he judges by the curve; "plot tells
  everything"). No DSP vocab on the surface. Momentum, no ceremony. Surface only
  taste/product calls; drive everything else with safe defaults.
- **Don't perform false confidence.** Tyson flagged Claude flip-flopping — confidently
  concluding, then walking it back. Some was honest evidence-updating (good); some was
  Claude overclaiming certainty it didn't have because Tyson asked it to "conclude."
  In this no-ground-truth domain: give your lean + your uncertainty, hold tactical
  positions provisionally, and be CONFIDENT only on the computable/verified half
  (engine, nulls, structure). The whiplash erodes trust. (Refines `claude-over-extrapolates`.)

## VERIFICATION (show output; don't claim done without it)

```
python -c "from pyruntime import trench_ffi; from src.utils.packed_runtime import evaluate_body; \
  b=trench_ffi.compile_body_typed([1,120,120,.7,.7,6,1, 0,780,2200,1.2,5,5,1, 0,1100,3000,1.2,5,4,1, \
  3,7000,1500,.7,2,0,1, 2,4000,900,1.5,4,0,1, 6,9000,9000,.7,.7,-4,1]); \
  print(evaluate_body(b,5)['stable'], len(b))"   # typed compiler works end-to-end
python -m http.server 8141 --directory forge-web   # then open /filter-designer.html
node --check forge-web/js/pack-core.js
node dev/tmp/typed_null.cjs                         # WASM typed bytes; null vs DLL = 0 (PASSED 2026-06-10)
```

## FIRST MOVES (new chat)

1. Read CLAUDE.md + AGENTS.md. Confirm the Filter Designer serves and compiles (above).
2. ~~Wire load-candidate + KEEP~~ **DONE 2026-06-10** (see THE IMMEDIATE BUILD). The lean
   loop is built and click-verified. Beware a stale `python -m http.server 8141` stealing
   the port from the real backend (it 404s /keep — kill it).
3. STOP building. Serve it (`python tools/forge_author_server.py 8141`, tunnel for
   phone), and run the loop with Tyson: Claude floods aimed candidates into
   `forge-web/data/designer_seeds.json` / Tyson shapes + sweeps + KEEPs. Fill
   `desk/bank/v1/` with 4–7 worth-money presets. The first kept body is the project
   turning over.
