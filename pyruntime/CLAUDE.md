# pyruntime

Python authoring runtime for TRENCH bodies. FastAPI service.

## Two pipelines — do not conflate

### THE FORGE (forward-looking)
Direct pole-zero synthesis for original TRENCH bodies.
- `target.py` — sonic table targeting, morph/bell/electronic/composite builders
- `macro_compile.py` — Actor-based slot compiler (SINGLE macro, pressure behaviors)
- `stage_math.py` — freq/radius/gain → StageParams
- `zero_law.py` — proved ContourFamily vocabulary
- `encode.py` — StageParams → kernel-form EncodedCoeffs (float32, matches Rust)
- `analysis.py` — morph trajectory distance, midpoint audit gate, body profiling
- `forge_roll.py`, `forge_session.py` — batch generation

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
- Compiler code must NEVER import from `macro_compile.py` or `target.py`
- `api.py` imports both but the call chains are separate (different endpoints)
- If you're adding a new endpoint, know which pipeline it belongs to

## Key modules

| Module | Pipeline | Role |
|---|---|---|
| `target.py` | Forge | Sonic table → BodySpec (morph, bell, electronic, composite) |
| `macro_compile.py` | Forge | Actor slots → 4-corner CornerArray |
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

**Forge:** `/morph-target`, `/composite-target`, `/target`, `/analyze`, `/suggest`, `/sift/*`
**Compiler:** `/designer`, `/designer/response`, `/designer/render`, `/designer/live`
**Shared:** `/response`, `/export`, `/bake`, `/render`, `/vault`, `/splice`, `/sonic-tables`, `/live-response`
