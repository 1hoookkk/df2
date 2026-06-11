# Closed-Loop Body Compiler — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]` checkboxes.

**Goal:** Stop hand-designing filters. Build the closed loop where the human designs **targets and gates** and the system proposes bodies you approve / reject / steer:

```text
intent / reference / law  →  TARGET SURFACE  dB(f, Morph, Q)
   →  SYNTHESIZE   (optimize (θ,r) corners against the TRUE runtime)
   →  VERIFY       (stability · surface RMS/p95/max · ceiling)
   →  AUDITION     (batch renders through the drive chain: sweeps, 808, noise)
   →  CORPUS       (body + spec + target + params + metrics + renders + tags)
   →  iterate
```

The **manual editor is NOT the center** — it's a repair/inspection tool inside the loop (the bench already is it). The center is `spec → surface → synthesize → verify → audition → archive`.

**Synthesis engine:** optimize in the physical pole/zero coordinate `(θ, r)` — angle = frequency, radius = sharpness. Each section `(θp, rp, θz, rz, g)`; conjugate twin implicit. Co-optimize all **4 corners jointly**. **Fit the TRUE packed runtime** (`packed_probe`) — quantization and the morph-interior "magic" are *inside* the thing we optimize, so there is no surrogate to drift. Stability = `r < 1` bounds. Optimizer owns poles + radii + gain + stability + packing; **zeros free for the ear** (optionally frozen).

> **OBSERVED (this session):** the minifloat word-lerp interior is **not** reproducible by continuous kernel- or biquad-interpolation (both diverge ~19–23 dB on the morph interior; corners match bit-exact). Only the real packed runtime is faithful. So we fit the real runtime, period.

**Tech stack:** Python, numpy, `scipy.optimize.least_squares` (numerical Jacobian). Reuse: `pyruntime.trench_ffi` (`packed_probe`), `pyruntime.packed_interp` (`coeffs_to_words`), `src.utils.packed_runtime` (`evaluate_body`), `src.utils.body240` (`CORNER_ORDER`, `raw_from_words`, `compiled_payload`), `pyruntime.trench_ffi.engine_render*` (audition). Inspector: `forge-web/bench.html`.

## Scope & staging — build the loop, not a DSP operating system

The loop is the system; a "filter research OS" (query DB, genetic/ML search, CLAP/VST export, CPU/denormal/modulation metrics, spectrogram video, A/B-null suites) is how we never ship. Full send on the loop, staged:

- **V1 (this plan): verification-first compiler.** target surface → `.body240` + `.report.json` + `.surface.npy` + `.response.png` + audition `.wav`s. Establishes truth. No GUI.
- **V2: corpus browser** = the existing **bench** pointed at `dev/tmp/compiler/` (it already scans it). A folder of bodies + their `report.json` *is* the corpus.
- **V3: manual repair** = the bench stage-rack made editable (zedit already drags poles on the WASM engine). Repair, not design.
- **V4: generator wizard** = thin "law → N candidates → rank → audition → promote" over V1.

**Out of scope now (YAGNI):** ML/DDSP, genetic search, plugin export, CPU/denormal metrics, video, the searchable query DB. Corpus = a directory + JSON until search actually hurts.

---

## Design (fixed before tasks)

- **Per-section params (5):** `[θp, rp, θz, rz, g]` → biquad `(b0,b1,b2,a1,a2)`: `a1=−2rp·cosθp, a2=rp², b0=g, b1=g(−2rz·cosθz), b2=g·rz²` → kernel for packing: `c0=b1/b0+2, c1=1−b2/b0, c2=a1+2, c3=1−a2, c4=b0` → `coeffs_to_words`.
- **Param tensor `P`:** `(4,6,5)`, 120 numbers. Bounds: `θ∈[2π·40/SR, π]`, `r∈[0.10, 0.99985]`, `g∈[0.02, 40]`.
- **Forward = the real runtime:** `P → words (4 corners) → body240 → packed_probe` on the grid → `mag_db`. Grid = 5×5 `(m,q)∈{0,.25,.5,.75,1}²`.
- **Loss:** `W(f)·(true_db − target_db)` over (gridpt×freq). Stability is enforced by the `r` bounds + the final 17×17 `evaluate_body` gate (no separate penalty needed — the bytes we optimize are the bytes that ship).
- **Hybrid:** `frozen_zeros` (per-section `(θz,rz)`, held across corners) → optimize poles + gain only; the ear drags zeros.
- **Acceptance:** re-hit a real P2K surface to RMS < threshold across the grid AND `evaluate_body` stable.

## File Structure
- `src/compiler/rootspace.py` — `(θ,r,g)` ↔ biquad (DONE).
- `src/compiler/surface_target.py` — `FREQS`, `GRID`, `surface_from_body`, `mag_db` (DONE).
- `src/compiler/encode.py` — `P → words → body240` (the packer).
- `src/compiler/surface_fit.py` — `fit_surface(target, seed, frozen_zeros)` against the true runtime.
- `src/compiler/compile_surface.py` — orchestrator + artifacts (body/report/surface/png/wav).
- `tests/compiler/test_*.py`.

---

## Task 1: rootspace (θ,r,g) — DONE
`src/compiler/rootspace.py` + `tests/compiler/test_rootspace.py` (round-trip < 1e-6). ✅ already implemented this session.

## Task 2: target surface — DONE
`src/compiler/surface_target.py` (`surface_from_body` via `packed_probe`; `FREQS`, `GRID`). ✅ already implemented; corner conversion verified bit-exact vs runtime.

## Task 3: the packer (P → body240)

**Files:** Create `src/compiler/encode.py`; Test `tests/compiler/test_encode.py`

- [ ] **Step 1 — failing test** (a real body's params re-pack to a body whose *corners* match it < 0.3 dB):

```python
import numpy as np
from pathlib import Path
from src.compiler.surface_forward import params_from_body   # already exists
from src.compiler.surface_target import surface_from_body, FREQS, GRID
from src.compiler.encode import body_from_params
ROOT = Path(__file__).resolve().parents[2]

def test_repack_corners_match():
    body = (ROOT/"ref/presets/P2k_002_early_rizer.bin").read_bytes()
    P = params_from_body(body)
    rebuilt = body_from_params(P)
    a = surface_from_body(body); b = surface_from_body(rebuilt)
    corners = [0, 4, 20, 24]                    # the 4 stored corners in GRID
    assert np.sqrt(np.mean((a[corners]-b[corners])**2)) < 0.3
```

- [ ] **Step 2 — run, expect FAIL.**
- [ ] **Step 3 — implement:**

```python
"""Pack (θ,r,g) params -> the 240-byte body the runtime ships."""
import numpy as np
from pyruntime.packed_interp import coeffs_to_words
from src.compiler.rootspace import params_to_biquad
from src.utils.body240 import CORNER_ORDER, raw_from_words

def _kernel(bq):
    b0, b1, b2, a1, a2 = bq
    return (b1/b0+2.0, 1.0-b2/b0, a1+2.0, 1.0-a2, b0)

def words_from_params(P):
    return {CORNER_ORDER[ci]: [tuple(int(v) for v in coeffs_to_words(*_kernel(params_to_biquad(P[ci][s]))))
                               for s in range(6)] for ci in range(4)}

def body_from_params(P) -> bytes:
    return raw_from_words(words_from_params(P))
```

- [ ] **Step 4 — run, expect PASS** (proves the (θ,r,g)→packed round-trip holds at the corners; the interior is whatever the runtime makes of it — which is the point).
- [ ] **Step 5 — commit:** `git add src/compiler/encode.py tests/compiler/test_encode.py && git commit -m "feat(compiler): pack (θ,r,g) params -> body240"`

## Task 4: fit against the true runtime

**Files:** Create `src/compiler/surface_fit.py`; Test `tests/compiler/test_surface_fit.py`

- [ ] **Step 1 — failing test** (a synthetic single sweeping/sharpening resonance is reproduced, stable):

```python
import numpy as np
from src.compiler.surface_target import FREQS, GRID, surface_from_body
from src.compiler.surface_fit import fit_surface
from src.compiler.encode import body_from_params
from src.utils.packed_runtime import evaluate_body

def test_fit_reaches_low_residual_and_stable():
    tgt = np.zeros((len(GRID), len(FREQS)))
    for gi,(m,q) in enumerate(GRID):
        fc = 300*(1200/300)**m; sharp = 0.20-0.10*q
        tgt[gi] = 14*np.exp(-((np.log2(FREQS/fc))**2)/(2*sharp**2))
    P = fit_surface(tgt, seed=0, n_restarts=2)
    body = body_from_params(P)
    a = surface_from_body(body); n=lambda x:x-x.max(1,keepdims=True)
    assert np.sqrt(np.mean((n(a)-n(tgt))**2)) < 7.0
    assert evaluate_body(body, 17)["max_pole_radius"] < 1.0
```

- [ ] **Step 2 — run, expect FAIL.**
- [ ] **Step 3 — implement** (forward = the real runtime; numerical Jacobian; peak-seeded; vectorise `mag_db` over freqs for speed):

```python
"""Co-optimize 4 corners in (θ,r,g) against the TRUE packed runtime surface."""
import math, numpy as np
from scipy.optimize import least_squares
from scipy.signal import find_peaks
from pyruntime import trench_ffi
from src.compiler.surface_target import FREQS, GRID
from src.compiler.encode import body_from_params
from src.architectures.trajectory_program import AUTHORING_SR as SR

LO = np.array([2*math.pi*40/SR, 0.10, 2*math.pi*40/SR, 0.10, 0.02])
HI = np.array([math.pi, 0.99985, math.pi, 0.99985, 40.0])
_W = 2*np.pi*FREQS/SR
_C = np.stack([np.cos(_W), np.sin(_W), np.cos(2*_W), np.sin(2*_W)], 0)   # (4, nf)

def _surface(body):                              # vectorised true-runtime surface
    out = np.empty((len(GRID), len(FREQS)))
    c, sn, c2, s2 = _C
    for gi,(m,q) in enumerate(GRID):
        acc = np.zeros(len(FREQS))
        for (b0,b1,b2,a1,a2) in trench_ffi.packed_probe(body, float(m), float(q))["biquad"]:
            nr, ni = b0+b1*c+b2*c2, -(b1*sn+b2*s2); dr, di = 1+a1*c+a2*c2, -(a1*sn+a2*s2)
            acc += 20*np.log10(np.maximum(1e-12, np.hypot(nr,ni)/np.maximum(1e-12, np.hypot(dr,di))))
        out[gi] = acc
    return out

def _seed(target, rng):
    P = np.empty((4,6,5))
    for ci, gi in enumerate((0,4,20,24)):
        y = target[gi]-target[gi].max(); idx,_ = find_peaks(y, prominence=2.0)
        pk = list(FREQS[idx[np.argsort(y[idx])[::-1]]][:6]) if len(idx) else list(FREQS[::40][:6])
        pk += [FREQS[-1]]*(6-len(pk))
        for s in range(6):
            fp = float(pk[s])*(2.0**rng.normal(0,0.05))
            P[ci,s] = [2*math.pi*np.clip(fp,40,SR*0.49)/SR, 0.95, 2*math.pi*fp/SR, 0.85, 1.0]
    return P

def fit_surface(target, seed=0, frozen_zeros=None, n_restarts=2, max_nfev=2500):
    rng = np.random.default_rng(seed)
    free = np.ones((4,6,5), bool)
    if frozen_zeros is not None: free[:,:,2:4] = False
    lob = np.broadcast_to(LO,(4,6,5))[free]; hib = np.broadcast_to(HI,(4,6,5))[free]
    best, bestc = None, np.inf
    for _ in range(n_restarts):
        base = _seed(target, rng)
        if frozen_zeros is not None:
            base[:,:,2] = frozen_zeros[:,0]; base[:,:,3] = frozen_zeros[:,1]
        def resid(x):
            P = base.copy(); P[free] = x
            return (_surface(body_from_params(P)) - target).ravel()
        x0 = np.clip(base[free], lob+1e-6, hib-1e-6)
        sol = least_squares(resid, x0, bounds=(lob,hib), method="trf", x_scale="jac",
                            diff_step=1e-3, max_nfev=max_nfev)
        if sol.cost < bestc:
            P = base.copy(); P[free] = sol.x; best, bestc = P, sol.cost
    return best
```

- [ ] **Step 4 — run, expect PASS.** (Numerical Jacobian over 120 params is the slow part; if too slow, drop the optimization grid to 3×3 and verify on 5×5, or freeze zeros.)
- [ ] **Step 5 — commit:** `git commit -am "feat(compiler): fit (θ,r,g) corners against the true runtime"`

## Task 5: compile + verify + artifacts (the verification-first compiler)

**Files:** Create `src/compiler/compile_surface.py`; Test `tests/compiler/test_compile_surface.py`

- [ ] **Step 1 — failing tests** (the V1 outputs exist + stable; THE PROOF: re-hit a real P2K):

```python
import numpy as np
from pathlib import Path
from src.compiler.compile_surface import compile_surface
from src.compiler.surface_target import surface_from_body
ROOT = Path(__file__).resolve().parents[2]

def test_compiles_and_emits_artifacts():
    tgt = surface_from_body((ROOT/"ref/presets/P2k_002_early_rizer.bin").read_bytes())
    r = compile_surface(tgt, "probe", ROOT/"dev/tmp/compiler/probe")
    d = ROOT/"dev/tmp/compiler/probe"
    for ext in (".body240",".report.json",".surface.npy",".response.png"):
        assert (d/("probe"+ext)).exists()
    assert r["stable"] is True

def test_reproduces_real_p2k_surface():
    real = (ROOT/"ref/presets/P2k_002_early_rizer.bin").read_bytes()
    r = compile_surface(surface_from_body(real), "early_rizer_repro", ROOT/"dev/tmp/compiler/early_rizer")
    assert r["stable"] is True
    assert r["surface_rms_db"] < 7.0
```

- [ ] **Step 2 — run, expect FAIL.**
- [ ] **Step 3 — implement** (fit → pack → verify on the true runtime → metrics → emit body/report/surface/png + an 808 audition through the engine). Metrics: `surface_rms_db`, `surface_p95_db`, `surface_max_db`, `max_pole_radius`, `max_response_db`, `ceiling` (max_response_db > 30), `stable`. Render audio with `trench_ffi.engine_render(body, 0.5, 0.5, source, SR)`.
- [ ] **Step 4 — run, expect PASS** (the proof < 7 dB is the break-free moment).
- [ ] **Step 5 — commit:** `git commit -am "feat(compiler): verification-first compile — re-hit real P2K, emit artifacts"`

## Task 6: corpus = the bench
- [ ] `forge-web/build_bench.py` already scans `dev/tmp/compiler/**/*.body240`. After a compile, re-run it; open the bench, put the repro next to the real, judge by eye/ear/safety-strip. Commit.

---

## Done criteria
- Proof green: a real P2K surface re-hit to RMS < 7 dB, stable, on the bench next to the real.
- Then: `surface_target.from_law(...)` (macro controls → target curves) for **originals**, run with `frozen_zeros` so the ear drags the notches while the optimizer holds the skeleton. That closes the loop end-to-end.
