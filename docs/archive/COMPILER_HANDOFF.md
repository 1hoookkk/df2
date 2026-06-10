# df2 — Compiler Handoff (paste as the opening message of a new chat)

Read this, then `docs/superpowers/specs/2026-06-09-surface-cooptimizer.md`, then memory
`closed-loop-compiler-works`. Work in place in `C:\Users\hooki\df2`. Momentum over ceremony.
**Measure, don't theorize.** Tyson owns the ear; Claude drives everything else. Mark evidence
(OBSERVED / INFERRED / UNKNOWN).

## THE DIRECTION (this session's pivot — full send)
Stop generating-and-hoping. Build the **closed loop**:
```
intent / law / reference  →  TARGET SURFACE dB(f, Morph, Q)
  →  SYNTHESIZE (optimize (θ,r) corners against the TRUE packed runtime)
  →  VERIFY (stability · surface RMS/p95/max · ceiling)
  →  AUDITION (engine renders) → CORPUS (dir + report.json) → iterate
```
The human designs **targets and gates**; the system proposes bodies you approve/reject/steer.
The **manual editor is a repair tool, not the center** — the bench is the inspector. Resist the
"DSP-OS" sprawl (no ML/genetic/plugin-export/query-DB — YAGNI). Staging V1→V4 is in the spec.

## THE BREAKTHROUGH (OBSERVED — it works)
The compiler **re-hit a real Early Rizer's whole 5×5 Morph×Q surface** from nothing but its surface:
fit `(θp, rp, θz, rz, g)` per section across all 4 corners, **fitting the TRUE `packed_probe`** (NOT a
surrogate). First pass: **2.4 dB RMS, stable, 108 s.** The body it finds is a *different, messier*
pole/zero realization than the real (magnitude fitting is non-unique) — sounds close, isn't the same
machine. That's fine for ORIGINALS; for COPIES use the atlas (below).

## LOCKED TECHNICAL TRUTHS (OBSERVED this session)
- **Coordinate = `(θ, r, g)`**: angle θ = frequency (Morph moves it), radius r = sharpness (Q moves it),
  conjugate twin implicit, stability = `r < 1`. The right authoring unit: 6 resonances + 6 notches.
- **Fit the TRUE runtime, no surrogate.** The minifloat word-lerp **interior is NOT continuously
  interpolable** — interp-kernel AND interp-biquad diverge ~19–23 dB on the morph interior (corners
  match bit-exact). The "magic in the middle" lives in the u16 lerp. So the optimizer fits `packed_probe`
  with a numerical Jacobian.
- **Reproduction is FREE.** `body_from_params(params_from_body(real))` is **byte-identical** (0.000 dB)
  for healthy bodies. The atlas IS the copy — the optimizer was overkill for reproduction. **Optimizer =
  ORIGINALS engine.**
- **Corners are CONTROLS, the interior is the DELIVERABLE.** The runtime stores only 4 corners; everything
  you hear sweeping is the lerp between them. Design the surface; let the corners fall out (don't design
  corners — and you can't "optimize the middle alone": the middle is derived from the corners).
- **Z-plane lineage** = Dave **Rossum** (E-mu co-founder), patents US5170369 / US10514883 — NOT Massie.

## BUILT THIS SESSION
- **Compiler:** `src/compiler/{rootspace, surface_target, surface_forward, encode, surface_fit, compile_surface}.py`.
  `compile_surface(target, name, out_dir)` → `.body240 + .report.json + .surface.npy + .response.png`.
- **The bench** = THE surface: `forge-web/bench.html` (built by `forge-web/build_bench.py`). All 50 P2K
  decoded + authored + compiled bodies; **response (per-stage overlay) + z-plane (numbered S1–S6) + safety
  strip (stable·maxR·maxdB·ceiling) + clickable 5×5 Morph×Q map + numbers + audio**, live, plot==engine,
  self-contained (double-click). Scans `dev/tmp/compiler/` as the corpus. *Supersedes the ~20 scattered
  html surfaces.*
- **Atlas:** all 50 P2K decoded to the real format (4 corners × 6 sections pole/zero + words):
  `dev/tmp/p2k/atlas/P2K_atlas.{md,json}` + 50 miniplots. The known-structure source for copies.
- Spec: `docs/superpowers/specs/2026-06-09-surface-cooptimizer.md`.

## EXPERIMENTS (ran loose, subagent-driven; findings folded)
- **B (FIXED):** gain floor `LO[4] 0.02→0.001` in `surface_fit.py` — 0.02 clamped low-output bodies
  (FuzziFace `b0≈0.0025`) +18 dB/section, making them unfittable. Applied.
- **C (FOLDED):** pole-radius commit penalty `REG_W=0.5` in `surface_fit.py` — pushes poles out of the
  mushy r≈0.65 band → cleaner, more morph-predictable structure at **equal-or-better** accuracy
  (1.83→1.74, committed poles 8→12). Applied.
- **A (mild):** interior-weighted loss helps average interior RMS ~20% but makes the worst-case *max*
  slightly worse — squared loss chases medium residuals, not the outlier peak. Not folded. To cut the
  *max* you'd need an L∞/IRLS objective.
- **E (structural):** more `max_nfev` does nothing (150→400 identical); the local 8–17 dB spikes are a
  **non-convex seeding** problem (more restarts help) + the coverage gaps below, NOT compute.
- **D (DONE — the key finding):** coverage sweep, surface RMS by family:
  `early_rizer(LPF) 1.8 · millennium(LPF) 2.9 · megasweepz(LPF) 2.9 · lucifer_s_q(REZ) 3.1 ·
  talking_hedz(VOW) 4.2 · fuzzi_face(DST deep-null) 9.5`. **The optimizer is strong on POLE-dominated
  filters (LPF, dense-REZ — its home turf) and weak/broken on ZERO-dominated ones (VOW interior 25 dB;
  DST 118 dB local — BREAKS).** Root cause (OBSERVED): **a magnitude-only objective has ~no gradient at
  the bottom of a deep null** — moving a zero r=0.999→0.95 barely changes RMS, so the fit *cannot pull
  zeros onto the circle.* The interior (M50Q50) error climbs monotonically with zero-dependence. **This
  quantitatively proves "poles fit, zeros hand": the optimizer literally can't place zeros, so for
  zero-heavy types the zeros MUST be seeded (from the atlas) or carved by ear — `frozen_zeros` is not
  optional, it's required.** (`exp_d_sweep.py`, `exp_d_results.json`.)

## OPEN CEILING TO RAISE (the highest-leverage fix)
- **Real-root coverage gap:** `(θ,r)` forces a complex-conjugate pair, so it **cannot spell a section
  with REAL (on-axis) poles/zeros.** LucifersQ doesn't round-trip even unclipped (5.2 dB). Extend the
  `(θ,r,g)` ↔ biquad map (`src/compiler/rootspace.py`) with a real-root case (θ=0/π) so the optimizer can
  represent the FULL vocabulary, not just conjugate-pair bodies. This raises the ceiling for everything.

## NEXT (the payoff)
1. **`surface_target.from_law(...)`** — macro controls ("violent high-mid scream, climbs with Morph, sub
   capped +3 dB, two moving notches") → a target surface. Then `compile_surface` synthesizes an ORIGINAL,
   run with `frozen_zeros` so the ear drags the notches while the optimizer holds the pole skeleton. **This
   closes the loop end-to-end for new bodies — the actual product.**
2. Fix the real-root coverage gap (above).
3. Read D's coverage table; validate the C regularizer didn't regress other families.
4. Build the bank: a few Laws → compile → bench → Tyson's ear keeps 4–7.

## TRAPS / STYLE
- The EAR is the judge; plot==engine (0.0000 dB) is the eye. Magnitude is the judge (not phase).
- Verify pasted AI claims through the engine; keep the kernel, flag the contamination. (This session: the
  "DSP-OS" vision — right loop, but resist building the database/genetic/ML/export sprawl.)
- Don't reinvent: trench-core is the one runtime owner; the bench reuses `forge-web/js/packed.js`.
- Background subagents that run slow fits tend to PUNT (background their work + return without numbers) —
  run slow experiments yourself via background bash with file redirection.
