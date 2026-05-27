# pyruntime/legacy — retired stage-first generators (quarantine)

Quarantined 2026-05-27. These modules built bodies the **stage-first** way —
assigning per-stage semantic roles (Actor → slot → stage: Foundation / Mass /
Throat / Bite / Air / Scar) as the generation primitive. That is the rejected
trap: stages are bookkeeping/indexing only, and the real design target is the
**full cascade frequency response** over the Morph×Q surface. The forward path
is the response-first desk (`pyruntime/desk_compile.py` → `forge_fit.py`,
served at `/desk/*`).

**Nothing in the live app imports these.** They are kept for reference/revival,
not execution. Their internal imports still reference the old `pyruntime.*`
paths (e.g. `from pyruntime.macro_compile import ...`) — if you revive one,
repoint those to `pyruntime.legacy.*`. Imports break loudly by design.

## Quarantined here
- `macro_compile.py` — Actor→slot→stage compiler (the core of the trap).
- `target.py` — sonic-table → Actor-slot specs (fed macro_compile).
- `forge_batch.py` — hardcoded per-stage stitch/notch "iconic bodies".
- `forge_optimize.py` — pymoo NSGA2 body search over the stage-first space.
- `forge_roll.py` — random-collision generator + yes/no preference learning.
- `forge_session.py` — terminal-driven render/splice/collide CLI.
- `preset_audit.py` — audits the per-stage-role schema.
- `slammed_dark_bright_belch.py` — an Actor-slot recipe (was pyruntime/recipes/).

## Entangled stage-first utilities NOT moved yet (need a sever first)
These are still imported by KEPT code, so moving them would break the live app
or keep-tools. Sever the dependency, then quarantine:
- `pyruntime/stage_roles.py` + `preset_schema.py` ← `pyruntime/body.py` (legacy import path).
- `pyruntime/zero_law.py` ← `pyruntime/designer_compile.py` (Compiler uses `ContourFamily`).
- `pyruntime/stage_math.py` ← `tools/corner_words.py` (uses `resonator_with_zero`/`zero_forced_offset`).
- `pyruntime/forge_joint.py` ← `tools/capture_to_cartridge.py`.
- `pyruntime/minifloat.py` ← `tools/coefficient_field_bakeoff.py`, `tools/corner_migration_gate.py`
  (superseded by `packed_interp.py`; the gate uses it intentionally as the OLD reference).
