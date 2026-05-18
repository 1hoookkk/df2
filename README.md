# df2

An audio plugin built on the E-mu Z-plane filter architecture: 12-stage
DF2T biquad cascade with 4-corner bilinear interpolation. Rust runtime,
JUCE wrapper.

This is a frame-bank project. Bodies are assembled from a curated library
of static filter states measured from real E-mu material under a Clean
Room rule. Authoring is gated by null-test validation, not by proxy
metrics.

## Start here

Read in order:

1. **`CLAUDE.md`** — operating rules, session protocol.
2. **`SPEC.md`** — frozen math and cartridge format.
3. **`FRAME_BANK.md`** — strategy, capture methods, validation gate.
4. **`BODIES.md`** — the 4 shipping bodies with audible targets.
5. **`STATE.md`** — current project state (live, maintained by Claude).

## Layout

```
df2/
├── CLAUDE.md              Operating rules
├── SPEC.md                Frozen math + format
├── FRAME_BANK.md          Frame strategy + Clean Room rule
├── BODIES.md              4 shipping body audible targets
├── STATE.md               Live state cache
├── README.md              This file
├── SESSION_LOG/           Append-only session history
│   └── README.md
├── trench-core/           Rust runtime (frozen, patent-faithful)
├── juce-shell/            JUCE plugin wrapper
├── tools/                 Authoring + validation tools
│   ├── compile_raw.py     Body JSON → compiled-v1 cartridge
│   └── null_test.py       Validation gate
├── ref/                   Read-only reference material
│   ├── canonical/         164 wet renders for internal null tests
│   ├── p2k_skins/         33 P2K coefficient JSONs (captured)
│   ├── x3_displays/       X3 screenshot oracles
│   └── morphlp_zero_table.json   MorphLP RE data
├── vault/                 Authored material
│   └── _frames/           Authored frames (the bank)
└── dev/                   Scratch / WIP, gitignored
    └── tmp/
```

## Workflow

```
ref/ (measured) ──► tools/ ──► vault/_frames/ ──► compile_raw.py
                                                       │
                                                       ▼
                                                  cartridge JSON
                                                       │
                                                       ▼
                                                  JUCE plugin
                                                       │
                                                       ▼
                                                  null_test.py
                                                       │
                                                       ▼
                                                  audition by ear
                                                       │
                                                       ▼
                                                     ship
```

## Validation gate

Every body must pass `tools/null_test.py` against reference E-mu wet
renders at ≤ −60 dB null depth at all 4 corners and at midpoint M/Q
positions, before audition by ear.
