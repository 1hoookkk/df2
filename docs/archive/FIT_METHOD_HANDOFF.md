# df2 — Fit-Method Handoff (paste as the opening message of a new chat)

Read `AGENTS.md`, `CLAUDE.md`, and memory `iconic-corridor-and-the-bent-audit` first. Work in place
in `C:\Users\hooki\df2`. Momentum over ceremony. **Measure, don't theorize** — that was this
session's biggest lesson. Tyson owns the ear; Claude drives everything else. Mark evidence
(OBSERVED / INFERRED / UNKNOWN).

## THE PRODUCT (unchanged)
Ship df2/TRENCH — a destructive morphing filter FX plugin (808s, bass, vocals) — with **4–7
hand-picked iconic P2K-class presets**. Customer plays them with two knobs (Morph + Q/Drive) through
**AGC → Mackie → QSound**. The Forge is Tyson's private bench; only bodies ship. AI never approves a
body — the ear does.

## THE LOCKED METHOD (this session's resolution — don't re-litigate)
A body = **6 biquads** (12th order · 4 corners · 240 bytes). Make them by **fitting real audio**, not
hand-placing poles:
```
real audio / a Dirac IR  →  LPC/LSP (poles) or ARMA (poles + ZEROS/cavities)  →  6 biquads
        →  CHOOSE a foundation (palette)  →  pack via the trench-core compiler  →  Rust engine
```
- **Dirac impulse responses are the cleanest fit source** — flat excitation, so the recording *is* the
  resonances; **ARMA mines the cavities** (the notches all-pole LPC of vowels could never make).
- **The foundation is a CHOICE, not a computation.** Palette: `none · sub shelf · low hump · 808 ·
  tube`. Tyson picks the bottom by ear. Computing "the right" foundation failed every time
  (re-introduced the sub-mountain). OBSERVED.
- **Don't hand-author the cascade.** It's serial `H(z)=∏Hₖ` — sections *multiply*: a low resonator's
  inherent gain piles up = sub mountain; an unpinned/zeroless section craters. Fixes: **DC-pin every
  section** (`(1−2r·cosθ+r²)`, as `_actor_kernel` does) + **flat-ended sections + a shelf/peaking
  foundation** (not a lowpass that buries the character).

## THE BREAKTHROUGH (the bent audit — root cause of months of tail-chasing)
**OBSERVED:** the production gates were fantasy (Q≥12 dB, maxR≥0.998, median zero-travel) and
rejected **0/50** real iconic bodies. The QD search optimized that wrong target for months. Rebuilt
the gates from the **iconic-15 corridor** → **15/15 pass** (`configs/model/smoke.yaml`,
`src/utils/packed_runtime.py`). **Lesson: validate the ruler against ground truth first — a gate that
rejects Talking Hedz is bent; the ear disagreeing with the audit IS the bug report.**
Measured iconic recipe: maxR **0.985–0.988** · span 40–120 dB · **Q contrast 0.3–1 dB (Q barely
moves)** · **anchor+mover** (one leader pole + one leader canyon each travel **1–5.6 oct**) · held
shelf body. The motion is the **Morph leader sweep, not Q**.

## TALKING-HEDZ STRUCTURE (decoded clean-room, P2k_013)
A **crossing pair** (two mouth formants splitting from a common Hz = the "talk") + **2 held sharp bite
anchors** + a **moving broad body** + an air kill. NOT a parallel vowel glide. The body *breathes*
(its low-mid sweeps ~25 dB across morph).

## CONCLUSION — the key open claim (INFERRED)
The real iconic P2K were **made by humans fitting real recordings** (LPC/ARMA System Identification on
vowels/tubes/metal), curated + trajectory-paired, then compiled to packed ROM. **Not** hand-shaped in
the Morph Designer (a different/later front-end), **not** an algorithm. The corridor describes the
*result*, not the process; the search proposes candidates, Tyson's ear picks.

## BUILT THIS SESSION
- **`/fitbody` endpoint** (`tools/forge_author_server.py`): `{samples, sr, foundation}` → ARMA
  character (`arma_weapons`, poles+zeros) under a chosen foundation → 240-byte body hex. Tested.
  **Restart the server to use it:** `python tools/forge_author_server.py 8137`.
- **`forge-web/voice.html` + `js/voice-fit.js`** (REWRITTEN): drop a .wav/IR or record a vowel → POST
  to `/fitbody` → body → play/save. Foundation dropdown. **The hand-rolled JS LPC/pack (which cratered
  to −66 dB) is deleted** — the browser only captures + plays; Python does the math (the powerful tool).
- Corridor gates + `_vowel_program` + `_rbj_peaking` in `src/architectures/trajectory_program.py`.
- Proof scripts in `dev/tmp/`: `lpc_lock.py` (audio→LPC→6 biquads), `ir_weapon/ir_hump/foundation_palette`
  (IR fits + the foundation choices), `bass_shaper`, `oo_ee`, `hedz_arch`.
- `CLAUDE.md` + `AGENTS.md` updated (corridor law, Q-is-subtle, serial-cascade/shelf, human-authored
  conclusion). Memory: `iconic-corridor-and-the-bent-audit`.

## TRAPS / STYLE
- The **EAR is the judge**; `plot==engine` (0.0000 dB) is the eye, the driven sound is the truth.
- **Measure, don't theorize** — every big miss was a guess (bent audit, sub mountain, JS pack bug).
  Instrument the boundaries (a working reference + a broken one → compare).
- **Don't reinvent in browser JS** — call the proven Python owners (trench-core compiler,
  `fit_sources_lpc`, `arma_weapons`). One owner per job.
- **6 biquads. Always.** Never 7, never 12.

## NEXT
- Verify `/fitbody` live (restart server → drop an IR → listen).
- **Two-IR morph:** fit A and B, pair them → the body moves.
- Build the bank: fit 4–7 real sources/IRs, pick foundations, audition through the drive chain, keep.

## THE QUESTION TO CLOSE
**Does this path — LPC/ARMA System-ID of real recordings/IRs → poles+zeros → a chosen foundation →
6 biquads → the drive chain — actually align with how the real ROM P2K filters were made?**
We INFERRED it (the System-ID argument + the Klatt/LPC/ARMA papers in the archive + the decodes), but
never *proved* it against the ROM bytes. Pressure-test it: decode the real P2K, check whether their
poles/zeros/foundations look like LPC/ARMA fits of real sources, and whether this method + the corridor
actually reproduce the iconic grammar — or whether the real designers did something we're still missing.
