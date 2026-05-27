# pyruntime

Python authoring runtime for TRENCH bodies. FastAPI service.

## Two pipelines — do not conflate

### THE FORGE (forward-looking) — response-first
The forward path is the **response-first desk**. You target the full cascade
magnitude (the whole-corner constellation over Morph×Q); stages are ONLY the
6-biquad factorization/bookkeeping. NEVER design stages individually.
- `desk_compile.py` — draw magnitude → cepstral min-phase → the real fitter →
  compiled-v1 cartridge → validate (packed Morph×Q stability) → audition
  (shipped engine via FFI) → live slot. Served at `/desk/*`.
- `forge_fit.py` — the fitter: phase-aware whole-cascade complex least-squares.
- `trench_ffi.py` + `packed_interp.py` — the single packed-math owner (FFI to
  trench-core); `ffi_parity.py` guards bit-parity.
- `analysis.py` — morph trajectory distance, midpoint audit gate, body profiling.
- `encode.py` — StageParams → kernel-form EncodedCoeffs (float32, matches Rust).

**Retired (stage-first, quarantined in `pyruntime/legacy/`):** `target.py`,
`macro_compile.py` (Actor→slot→stage), `forge_batch.py`, `forge_optimize.py`,
`forge_roll.py`, `forge_session.py`, `preset_audit.py` — they designed stages by
role, the rejected trap. `stage_math.py`, `stage_roles.py`, `preset_schema.py`,
`zero_law.py`, `forge_joint.py` remain in-tree only because kept code/tools still
import them (sever, then quarantine). See `pyruntime/legacy/README.md`.

**Rules:** No RBJ cookbook. Direct pole-zero only. Audit measures the actual
cascade response, not a theoretical model. Audio > Runtime > Source > Theory.

### THE COMPILER (backward-looking)
Heritage reconstruction for E-mu MorphDesigner XML.
- `designer_compile.py` — XML parsing, legacy 0-127 integer grid → coefficients
- `heritage_coeffs.py` — type1/2/3 firmware integer-domain recipes

**Rules:** Exists strictly to parse legacy data. Its output is raw data
for the Forge to target, not a textbook to derive from.

### THE BOUNDARY
The Compiler looks backward (how legacy hardware operated under 1999 constraints).
The Forge looks forward (bodies that bypass those limitations).

- Forge code must NEVER import from `heritage_coeffs.py` or `designer_compile.py`
- Compiler code must NEVER import from the retired generators (`pyruntime/legacy/*`)
- `api.py` imports both but the call chains are separate (different endpoints)
- If you're adding a new endpoint, know which pipeline it belongs to

## Key modules

| Module | Pipeline | Role |
|---|---|---|
| `desk_compile.py` | Forge | Draw→min-phase→fit→cartridge→validate→audition→live (`/desk/*`) |
| `forge_fit.py` | Forge | Whole-cascade phase-aware complex least-squares fitter |
| `trench_ffi.py` / `packed_interp.py` | Forge/Shared | Single packed-math owner (FFI to trench-core) |
| `analysis.py` | Forge | Midpoint audit, morph distance, body profiling |
| `designer_compile.py` | Compiler | MorphDesigner XML → CornerArray |
| `heritage_coeffs.py` | Compiler | Firmware integer recipes (type 1/2/3) |
| `encode.py` | Shared | StageParams → EncodedCoeffs (kernel-form) |
| `freq_response.py` | Shared | Cascade H(z) evaluation from EncodedCoeffs |
| `corner.py` | Shared | CornerArray, bilinear interpolation |
| `body.py` | Shared | Body struct, JSON I/O, vault loading |
| `splice.py` | Shared | P2K corner splice (RestToRest, etc.) |
| `render.py` | Shared | Audio render (pink noise through cascade) |
| `api.py` | Both | FastAPI endpoints (routes are pipeline-specific) |

## Audit gates

| Gate | Status | Location |
|---|---|---|
| Midpoint audit (morph trajectory spike) | Built | `analysis.py:midpoint_audit` |
| Frequency crowding | Built | `validator.py:_check_crowding` |
| Regime bounds (r < 1.0) | Built | `validator.py:_check_regime_bounds` |
| Degenerate surface (identical corners) | Built | `validator.py:_check_distinct_corners` |

## Verification

```bash
python -m pytest tests/test_api.py -v
```

## API routes by pipeline

**Forge (response-first):** `/desk`, `/desk/health`, `/desk/live`, `/desk/compile`, `/desk/validate`, `/desk/write-live`, `/desk/audition`, `/analyze`. `/` redirects to `/desk`.
**Compiler:** `/designer`, `/designer/response`, `/designer/render`, `/designer/live`
**Shared:** `/response`, `/export`, `/bake`, `/render`, `/vault`, `/splice`, `/live-response`, `/health`
**Retired (stage-first, removed 2026-05-27):** `/target`, `/morph-target`, `/composite-target`, `/sonic-tables`, `/suggest`, `/sift/*`, and the static UIs `/workbench`, `/forge`, `/sift`.
