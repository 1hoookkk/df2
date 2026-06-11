# presets/ — canonical bodies (single source of truth)

Finished, shippable bodies (the KEEP / bake **output**) live here. This is the
**one** folder shared by:

- the **forge** — player mode / audition plays these, and
- the **df2 plugin** — preset selection ships these.

Both read the same files, so there is no drift between what gets authored and
what ships.

Distinct from `forge-clean/src/material/` — that is raw *starter* material going
*into* authoring; this is the finished output coming *out*.

Format: `.body240` raw 240-byte bodies, or JSON cartridges with `packedWords`
(loaded via `trench_core::Cartridge::from_body_bytes` / `Cartridge::from_json`).
