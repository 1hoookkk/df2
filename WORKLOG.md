# DF2 Worklog — session direction tracker

Chronological record of where each session started, how the direction moved, what
got decided, and the next move. This is a **thread-keeper, not authority**:
`CLAUDE.md` and `gpt55-pro-report-coefficient-forge-spec.md` remain the contract
and the Forge model. Nothing here overrides them or becomes doctrine. Append one
entry per session; newest on top; keep it tight.

## 2026-06-12 — Thumbwheel glow alignment and visual contract resolved

**Started:** Fix the key failure where the thumbwheel glow was warped, misplaced, or rendered as a flat neon stripe.

**Resolved:**
- **Alignment & Centering**: Physically centered the glow path to `y = 21.5` in the scaled `152x40` frame (matching the physical slot of the 3D wheel).
- **Smooth Tapering Trail**: Replaced the flat neon stripe with an elliptical bead (hot white core + soft cyan halo) and a tapering signal trail that narrows and decays exponentially to the left (`sigma_y` dynamically scales based on horizontal distance).
- **Detail Integration**: Switched from a binary luma gate to soft screen-blend overlay, ensuring that underlying textures and tooth shadows remain visible rather than being overwritten.
- **Contract Adhered**: Frame `0` is glowless; frames `1..126` move smoothly; frame `127` is glowless; frame `128` is a byte-copy of frame `0`.
- **Handoff Updated**: Documented the solved state in `HANDOFF.md`.

---

## 2026-06-02 — Vocal bodies cracked: real-voice LPC skeleton

**Started:** verify the pasted P2K "grammar" analysis, then author 4 original bodies.

**Verified:** the analysis is real — re-counted the hard claims against
`ref/p2k_variants/study_best_of_best/llm_clarity_pack.json` (lane-6 edge zero 45/45,
7/9 equal-gain, Deep Bouche 14/30 local zeros — all exact). P2K bytes stay
**study-only** (clean-room; never ship their coefficients).

**Direction locked (Tyson, this session):**
- Authoring = a small offline **generator palette** that writes editable 4-corner
  bodies, then vanishes. Runtime stays ordinary `.body240`. ~6 generators, not 50.
- **Don't spray roots.** Generate a 6-**row program** (each lane a role:
  FOUNDATION / WINDOW / COUNTERWEIGHT / EDGE-CAP / SLOPE / SCAR), derive roots from
  relationships, vary only lawful knobs.
- **Four-corner law:** one program → M0/S0 rest, M1/S0 transformed, M0/S1
  pressured-rest, M1/S1 pressured-transformed.
- **Ruthless 5×5 gate.** Hard rejects: unstable/nonfinite, flat-or-bland corner
  (nothing to load), anonymous middle (no event), too-hot middle. Vocal-shape
  heuristics (parallel sweep, foundation drift, cluster collapse, uniform-radius
  Secondary, static motion) = warnings unless strict.
- **Batch into a folder. No Forge GUI integration.** Learning loop = `ledger.jsonl`
  (program + gate metrics + envelope score + verdict) + a P2K envelope ruler +
  chat verdicts.
- **Plots for Tyson = response CURVES (dB vs log-freq), not spectrograms.** Numbers are mine.
- **Corners must be musical and never load flat.**
- **Vocal axis law:** Morph slides the vowels (formant FREQ, log/Bark). Secondary =
  **Q crank, frequency LOCKED** (like Talking Hedz "Q to .999") — not a freq move.
  Some bodies use body/weight on Secondary instead; default is Q.
- **Hedz richness:** all 6 lanes are sharp resonators; the zeros do the tilt + cap
  (double duty). Don't waste a lane on a broad shelf — that's why ours had only 4 peaks.
- **AGC = the E-mu character, DEFAULT ON everywhere.** The 16-row `BASE_AGC_TABLE`
  (`trench-core/src/dsp/mod.rs`, read via `trench_agc_table`, driven by
  `agc_enabled`/`set_agc_drive`) must be engaged in BOTH capture and forge — never
  audition a bare filter. (Tyson: "dont proceed without agc being default.")
- **PIVOT — the forge IS the play + authoring surface.** Earlier "no Forge GUI
  integration / batch to a folder" is superseded: Tyson loads, plays, judges, and
  authors in the forge-clean GUI; the fit feeds it; zeros are designed there.

**Breakthrough:** Tyson + GPT extracted his **real voice** (aa/eee) as a 12th-order
LPC pole skeleton resampled to 39062.5 Hz, with radius-crank as the Secondary
(`r_cranked = 1 − 0.25·(1−r)`, angle/freq fixed). Built `voice_aa_eee`, rendered
through the **shipped engine** (AGC+saturate). Source files in `C:\Users\hooki\Downloads\`.

**Built:** `tools/author_lanes.py` (root→packed-words, round-trip 0.016 dB, reuses
canonical `coeffs_to_words` FFI — no forked packed math). Workspace
`dev/tmp/grammar_bodies/`: `row_program.py` (roles+gate), `batch.py` (variation+
ledger+envelope), `musical.py` (real formants + collision trick), `hedz_style.py`
(6 sharp resonators), `voice_body.py` (his voice).

**Forge build-out (forge-clean) — now the play + authoring surface:** loads
`.body240` into editable lanes (`ForgeBody::from_body240` → `PackedCorners::corner_kernel`);
preset list via `presets_dir()` (CWD-independent). **Real-time streaming audio**
(`audition::MorphStream`): one continuous stream reads MORPH/Q live + runs
`FilterEngine::process_block` per 256-block — smooth sweeps, no restart, AGC on by
default. **Design-your-own-zeros:** ZERO SURGERY authors a zero on a bare/fitted pole.
**AUTO** button ping-pongs MORPH 0→1→0 (~5 s each way). Built + relaunched clean.

**ARMA zeros bug FIXED (Tyson/Sonnet):** `trench-core/src/arma.rs:569` was DELETING
valid numerator zeros after solving — the recurring "ARMA drops a cancelling zero"
that flattened fits (zeros-first-class violated). Removed; quarry routed through
bounded packable-domain `pyruntime/quarry_fit.py`; `tools/fit_two_audio_arma.py` fixed.
nmr_cyclohexane 25.83→5.26 dB; 12/12 packed stable; phonetic /i/1.89 /u/1.06 /a/0.96
/sh/1.73 dB RMS. Verified (cargo test -p trench-core, 30 py tests, 17×17 smoke
maxR 0.9916). **RELEASE DLL still stale** — TRENCH.exe locks it; Python FFI fitters
use the old fitter until `cargo build --release -p trench-core` is rerun lock-free.

**Capture/fit (Sonnet):** `capture_to_cartridge.py` + `pyruntime/capture_compiler.py`
+ proof pack (28+11 tests). Provenance MEASURED/INFERRED/AUTHORED. **Caveat:** its
audition uses bare `render_kernel` (scipy sosfilt, NO AGC) — route through
`engine_render` (16-row AGC) before trusting. All-pole; zeros are authored.

**Status / next move:** rebalance voice body toward the throat; AUTO+PLAY ear test
pending; rebuild release DLL so the fixed fitter reaches the Python tools + plugin.
Forge roadmap (all AGC-default): (1) academic overlays (Bark/ERB/mel/Peterson-Barney)
for pole/zero placement; (2) cheats/runtime-hacks (collision, radius-overshoot,
Nyquist-edge) as insert selections; (3) fit-import (poles→lanes→author zeros; fork:
handoff vs in-forge FIT button, lean handoff).

**Dev gotchas:** `forge-clean.exe` AND `TRENCH.exe` hold `trench_core.dll` → kill
before rebuilding or you get LNK1104 (`taskkill //F //IM <name>`). `cargo` is on
PATH only in the Bash tool, not PowerShell.

**Open questions:** does the voice body sound like a voice by ear? secondary-axis
palette per preset (PRESSURE/OPEN/DAMAGE/ALT-ROUTE/FOCUS/RING/WEIGHT); batch size per
generator; promote `author_lanes` + row-program from `dev/tmp/` → `tools/`; UI-too-
abstract pass (needs Tyson's old-forge reference).
