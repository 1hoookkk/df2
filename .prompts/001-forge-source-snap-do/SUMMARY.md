# SUMMARY

## One-Liner

Implement a verified Forge source inventory and make `SNAP` the main authoring action, replacing the broken `TABLE` mental model.

## Version

v1

## Key Findings

- The highest-leverage Forge action is source snapping, not per-corner editing.
- `TABLE` should disappear as UI language; verified bodies belong under `START`, and landmarks belong under `SNAP`/`OVERLAY`.
- A fresh 17x17 packed-runtime probe over the named `.body240` folders passed for all bodies; the report is `dev/tmp/source_snap_body240_probe_summary_17x17.json`.
- Provenance still matters: Law Author, Physical Mountains, Klatt, and exact verified skeletons should rank above demo/proof/study bodies.
- Corner-library, ARMA, synthetic captures, and screamer/P2K material are overlay/study material until promoted through the same packed-body gate.

## Files Created

- `.prompts/001-forge-source-snap-do/001-forge-source-snap-do.md`
- `.prompts/001-forge-source-snap-do/SUMMARY.md`
- `dev/tmp/forge_source_snap_inventory/SOURCE_SNAP_SYNTHESIS.md`

## Decisions Needed

- Whether to store the canonical source inventory under `forge-gpu-painter/assets/`, `forge/recipes/source_inventory.json`, or `data/forge_sources/`.
- Whether experimental runtime-stable demo bodies appear under `START > Experimental` or remain hidden until manually promoted.

## Blockers

- None for the first implementation. The current packed-probe gate is sufficient to start.

## Next Step

Run the prompt in `001-forge-source-snap-do.md` to build the source inventory and wire `START`, `SNAP`, and `OVERLAY` around it.

