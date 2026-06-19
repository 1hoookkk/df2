# Pristine Preset Stack

This is the keep/move rule for evidence-grade mountain/canyon preset work.
`recipes/laws` and `recipes/three_layer_acoustic_forge` are the source-truth
folders. Everything else is evidence, calibration, candidate output, or final
bank material.

## Source Truth

- `recipes/laws/`
  - Keep compact clean-room laws only.
  - A law must compile to six runtime lanes and pass packed `trench_core` audit.
  - Current approved seeds are listed in `recipes/pristine_preset_stack.json`.
- `recipes/three_layer_acoustic_forge/cleanroom_three_layer_acoustic_recipe.json`
  - Keep the canonical Anatomy + Articulation + Survival recipe here.
  - Six pole lanes plus six zero lanes, no copied protected bytes or endpoint
    tables.
- `recipes/three_layer_acoustic_forge/generated/`
  - Candidate recipe outputs from clean tables.
  - They may teach and audition, but are not final bank entries.

## Mathematical Ingredients

- `tables/morph_designer_type_primitives.json`
  - Three primitive Morph Designer moves from the static extract and pasted
    research note:
    - Type 1: local pole+zero peak/notch tear.
    - Type 2: moving pole with high/Nyquist-side zero for cliffs.
    - Type 3: moving pole with low zero for sub cuts.
- `tables/exact_skeletons.json`
  - Exact filter skeletons; useful for lawful slopes and transition geometry.
- `tables/q_radius_table.json`
  - Radius calibration range only. Do not copy exact reference behavior as a
    product body.
- `tables/tube_resonances.json`, `tables/metallic_modes.json`,
  `tables/vowel_formants.json`, `tables/klatt_1980_*.json`,
  `tables/family_intents.json`
  - Physical/table rails for non-random pole placement.
- `filter_cards/`
  - Bake/probe support path, not a reference vault.

## Evidence Only

- `ref/heritage/`, `ref/heritage_forge/`
  - Heritage/template study and gesture evidence. Never product bytes.
- `ref/presets/`, `ref/p2k_variants/`, `ref/p2k_skins/`
  - P2K study corpus. Mine patterns and aggregate rails only.
- `ref/x3_menu/`, `ref/ghidra_extracts/`, `ref/millennium.kernels.json`
  - Decode/type/runtime evidence.
- `ref/patents/`, `ref/morpheus_authoring_doctrine.md`, `ref/codex/`,
  `ref/canonical/`, `ref/batman/`
  - Context and provenance evidence.
- `ref/inputs/`
  - Audition/capture input material.

## Final Bank

- `desk/bank/v1/BANK.md`
  - A body enters only after packed audit, rendered plot/audio, and Tyson keep
    verdict.

## Reject

- Random pole/zero clouds.
- Pole-only bodies.
- Hidden seventh stages.
- Copied protected bytes, coefficient rows, endpoint curves, names, or preset
  tables.
- Rendered artifacts in source-truth folders: `.body240`, `.wav`, `.png`,
  `.html`, or `__pycache__`.

## Good Preset Test

A good P2K-or-better seed has a protected low/body foundation, one or two
obvious moving actors, first-class zero canyons or remote counterweights, and
Secondary/Q pressure that changes radius/depth/gain without frequency drift.
The midpoint must matter. The packed audit must report 240 bytes, zero unstable
rows, and zero nonfinite rows before listening.

Run:

```powershell
python tools/audit_pristine_preset_stack.py --compile
```
