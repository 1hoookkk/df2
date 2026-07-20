# filters/ — the canonical filter workspace and legacy evidence

Everything that makes a TRENCH body, in one place. Consolidated 2026-07-13 from
three scattered locations. Nothing here is exhaust — the ~600 scratch dirs in
`df2/dev/tmp` and the 1,083 generated bodies in `production_authoring` were left
where they are on purpose.

## Current status

The 132 files under `bodies/` are retained legacy/quarantine material. They
remain available for provenance and historical comparison, but they are not a
current candidate source or a product-quality verdict. New candidates enter
through a separate artifact directory and are promoted only after packed
runtime proof and listening.

## What's here

| dir | what it is |
|---|---|
| `bodies/` | **Historical roster. 132 authored `.body240`.** Retained, not active product. |
| `generator/` | `build_interesting_presets.py` — the run that produced the 132 (2026-07-13). |
| `grammar/` | `typed_vowl` — the measured E-mu type grammar. THE stage logic. |
| `rails/` | Physics → pole/zero rails: modal, circuit, phononic, HRTF, DVTD, vowel-from-tables. |
| `archetypes/` | Archetype definitions + lineage/copy-risk record. |
| `tables/` | Measured law. **Frequencies are table-pulled, never invented.** |
| `gates/` | `copy_risk.py` — the clean-room distance gate. |
| `docs/` | METHOD, REFERENCE, PRIOR_ART_LEDGER. |

## The pipeline

```
tables/ + rails/          measured physics -> pole/zero rails
       |
       v
grammar/ (typed_vowl)     the stage grammar: which type, which lane
       |
       v
generator/                4 corners -> packed words -> 240 bytes
       |
       v
bodies/                   132 .body240   <- legacy/quarantine roster
       |
       v
trench-core (Rust)        packing, decode, bilinear morph/Q, cascade, engine
```

## Why the roster was moved

`bodies/` used to live **only** in `%USERPROFILE%\Documents\TRENCH\bodies` — the
folder `TrenchBodyRoster.h` reads at runtime. It was under no version control at
all. The historical roster is now in git, where it can be preserved without
being mistaken for the active candidate or shipping set.

Note the plug-in still *reads* from `Documents\TRENCH\bodies` at runtime. This
directory is the source of truth; that one is the working copy. Wiring the roster
to bake from here is an open decision, not done.

## Clean-room boundary — READ THIS

**No E-mu coefficients, packed words, or ROM bytes are in this tree.** Screened
on import; the screen is worth re-running if you add anything.

What IS here, and why it's safe:
- `tables/p2k_filter_q_behavior.json` — the **Proteus 2000 Owner's Manual**,
  pp. 105–107. The manufacturer's own published behavioural descriptions. Its own
  header says: *"Manufacturer's published behavioral descriptions only. No
  coefficients, no bytes."* Published documentation, not protected data.
- `archetypes/ARCHETYPES.md` — lineage notes naming which P2K preset each
  archetype was *studied against*, with the measured copy-risk distance
  (15–39 dB clear). This is a **defence document**: it evidences that the bodies
  are original and how far from prior art they measure.

The bodies themselves are original — 0 of 132 carry a P2K name, and all cleared
`copy_risk.py`. That is provenance evidence, not a keeper verdict.

## Provenance

- `rails/`, `archetypes/`, `docs/` ← `trench-filters` @ `7630976`
- `grammar/`, `tables/`, `gates/` ← `df2` (quarantined archaeological site)
- `bodies/` sha256 (concatenated, ordered) → `df8569a266f92d33…`

## Open seams

1. **The grammar is still Python.** `typed_vowl` is the measured type law and it
   lives only as a script. It needs to be in `trench-core` beside `stage_law.rs`.
   Until it is, the authoring law and the runtime law are two different codebases.
2. **`rails/` won't run from here yet.** The tools `sys.path`-insert `df2` and
   import `tools.author_body` / `tools.law_author`. They reference df2's kernel in
   place rather than copying it — which is *correct* (one owner), but it means
   this tree isn't self-contained.
3. **The packed encoder has more than one owner.** `trench-core` is canonical.
   `author_body.py` is the Python twin. They have disagreed before. This is the
   duplication to collapse — see `packed_math_dup_audit_*.md` in df2.
4. **Every ear-cull made before 2026-07-13 is suspect.** They were judged through
   an engine that clipped hot bodies into square waves (commit `440e6d16`). Culls
   made on the *curve* still stand; culls made on *feel* — "static", "lifeless",
   "too authored", "weak Q" — are void and worth re-auditioning.
