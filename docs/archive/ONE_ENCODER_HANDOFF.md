# df2 — Handoff: one encoder is unified, now make the editor the authoring surface

Paste this as the opening message of a new chat. Read `CLAUDE.md` + `AGENTS.md` first, then memory
`one-true-encoder-compile-body`. Work in place in `C:\Users\hooki\df2`. Momentum, no ceremony.
**Measure, don't theorize. NULL everything.** Tyson owns the ear; Claude drives the rest.

## What is TRUE now (committed `dce44cb9`)

**There is ONE forward encoder: `pyruntime.trench_ffi.compile_body`** (the shipped trench-core
compiler; 168 params = 4 corners × 6 stages × `[on, pole_hz, pole_r, gain, zero_on, zero_hz,
zero_depth]`). It is **byte-identical to the forge-web WASM GUI** (240/240, 0.0000 dB) — proven by a
null test that caught a **59 dB divergence**: the old `src/compiler` + `sweep_roster` + ~30 tools
compiled via a rogue `pyruntime.packed_interp.coeffs_to_words` path that skipped the engine's gain
normalization. **`plot==engine` is true within a path but was false across paths until unified.**

- `src/compiler/encode.py` routes everything through `compile_body`: `body_from_params`,
  `body_from_kernels` (for fit-paths), `words_from_body`, and `null_vs_engine` (the gate).
- `tools/sweep_roster.py` (the magnitude-fit method, the violence A/B winner) now compiles via
  `compile_body` at both build sites. Result: violence **8/8 survive (was 5/8), all stable
  maxR 0.9990** (the rogue let quantization push poles to maxR>1.0); cand_04 PASS morph 36.7.
- `compile_body`'s gain normalization is a **pure per-corner LEVEL offset (shape preserved 0.1 dB,
  measured)** — per-section gain in a cascade is pure level `∏gₖ`, never shape — plus it **clamps
  poles inside the unit circle**. So routing any body through it can't change its sound (AGC is
  level-invariant) or its corridor verdict (span/morph are level-invariant); it only anchors level
  + guarantees stability. It is objectively the better path on every axis.
- **The gate, forever:** never trust a body-producing path until `null_vs_engine == 0`.
- Radius cap = **atlas-real 0.9994** (max 0.9997, p90 0.999, 42% of real poles exceed 0.986).
  `q_radius_table.json`'s 0.986 is the Q-table-INDEX radius, NOT a pole-radius cap.

## The editor (new this session) — `forge-web/editor.html`

A **4-corner pole/zero editor**, served from `forge-web/` (`python -m http.server 8137 --directory
forge-web`, open `editor.html`). Reuses `js/pack-core.js` (WASM `compile_body`) + `js/packed.js`
(plot==engine). Verified loading + packing in a real browser.
- **You edit 2 frames (HOME/AWAY); Q0 + the morph interior auto-derive** — `broaden()` for Q0, the
  engine interps the middle. Corner law: Q = pole radius, Morph = freq, zeros lock across Q.
- **Foundation presets** (`data/foundations.json`: 2-pole LP → peak-shelf morph) auto-derive the 4
  corners (each section carries `pole_hz_home/away` × `pole_r_q0/q1` × `zero_hz[home,away]`).
- **Overlays** (`data/formants.js`, `data/sources.js`, `data/p2k_overlay.js`): drop poles onto REAL
  resonances (formants / fitted sources / the 50 P2K) — never invent.
- **All-6-biquad view** below the response.

## Open threads
- **Rogue tail:** ~30 `author_*`/`corner_*` tools still call `coeffs_to_words`. Not active shipping
  paths; route via `encode.body_from_kernels` or quarantine as touched.
- **The "foundations are wrong" question is now answerable** — the GUI == engine, so what the editor
  shows IS what ships. (My earlier "+59 dB mountains" were the rogue encoder; the GUI normalizes.)
- **The product:** author + ship 4–7 iconic bodies through the now-trustworthy loop
  (table-driven / sweep_roster → corridor gate `smoke.yaml`, iconic-15 = 15/15 → audition → ear).
  cand_04 (`bee_swarm → chainsaw`, morph 36.7, PASS) is a keeper candidate.

## DEFINITION OF DONE (this phase)
1. **[ ] One encoder everywhere.** Audit every active body-producing path; each must satisfy
   `encode.null_vs_engine == 0` (or be quarantined with a one-line note). Prove it with a null sweep.
2. **[ ] Foundations verified in the editor.** Load each `foundations.json` preset; confirm its
   response matches its `dsp_identity` (2-pole LP = clean lowpass pinned to 0 dB, bandpass = a real
   passband, etc.). Fix the preset data where it doesn't. The editor is the judge (GUI == engine).
3. **[ ] Editor → corridor.** "Save" in the editor lands the `.body240` in the corpus AND shows the
   corridor verdict (`evaluate_body` + `gate_failures` on `smoke.yaml`); assert the saved body nulls
   byte-0 vs `compile_body`.
4. **[ ] One keeper end-to-end.** Pick a family + home→away, author/refine in the editor (or
   sweep_roster), pass the corridor, audition through the AGC→Mackie→QSound chain, Tyson keeps/kills
   by ear. The loop is trustworthy now — use it.

## Traps / style
- The EAR is the judge; the plot is the eye; **the null is the proof.** Don't assert `plot==engine`
  or "verified" — null it (byte-0 vs `compile_body`) and measure it.
- I over-extrapolate (one fact → sweeping verdict) — stay at the altitude of what's proven. This
  session: I cried "foundations have mountains" off the rogue encoder; the null corrected me.
- Methods are plural, ONE core. Don't add an N+1th encoder. Don't spawn a new "clean" folder.
