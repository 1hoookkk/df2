# Forge Cartridge Spec — `forge-cartridge-v1`

One file. It holds the **editable source** (acoustic logic) and the **baked bytes**
(the authority). No extra layer.

> The gap this closes: bodies were always orphan bytes with no recorded intent, so
> every tool re-derived its own version (the `[[packed-math-triplicated]]` haunt).
> Now the source that made the bytes lives *with* the bytes; anyone can re-bake and
> prove they match. Subordinate to `CLAUDE.md` / `AGENTS.md` — a data format, not doctrine.

```
.cartridge.json = {
  "recipe":    {...},        ← editable source; the bench reads this; runtime IGNORES it
  "keyframes": [...4 corners] ← baked packed words; THE authority; the player reads this
}
```

The 240 packed bytes (`keyframes[*].packedWords`) are the only ground truth — DLL-verified
structure (4 corners × 6 stages × 5 `u16`, morph-first bilinear lerp). The recipe is free
design. The runtime loader has no `deny_unknown_fields`, so adding `recipe` breaks nothing.

## Three layers (every lane)

| Layer | Question | Author sets | Field |
| --- | --- | --- | --- |
| **Anatomy** | where's the body? | the **pole** (moves with Morph) | `anatomy.pole_hz`, `anatomy.sharp` |
| **Articulation** | where's the cut? | the **zero**, defined **relative to the pole** | `articulation.cut` / `.zero` |
| **Survival** | is it surviving? | per-lane gain + machine-enforced legality | `survival.gain`, `constraints` |

Poles are the bones (the morph-stepped behavior moves *poles*, per the verified correction
in `morphlp_zero_table.json`). Zeros are the hand, authored as a **ratio of the pole** so the
relationship (tear/bite) holds when the pole slides. Zeros are mandatory and first-class.

## Recipe shape

6 lanes (fixed slots, low→high, so poles can cross) + 2 axes. You author **6 lanes once**;
the compiler derives all 4 corners — so they're **kin** (one skeleton → coherent middle).

```jsonc
"recipe": {
  "axes": {
    "morph":     { "low":"HOME","high":"AWAY", "slide_semitones": 7.0, "scale":"log" },
    "secondary": { "low":"OPEN","high":"TIGHT", "mode":"q_crank", "amount": 0.25 }
  },
  "lanes": [ /* exactly 6 */
    { "id":2, "role":"mouth", "label":"mouth dome",
      "anatomy":     { "pole_hz":1180, "sharp":0.97 },
      "articulation":{ "cut":"tear" },
      "survival":    { "gain":1.0 } }
  ],
  "constraints": { "max_radius":0.999, "unity_dc":true, "on_unstable":"reject" },
  "overrides": [ { "corner":"tight_away","lane":2,"set":{"sharp":0.998} } ]   // optional hand-nudges
}
```

**axes** — `morph` slides every pole `slide_semitones` HOME→AWAY (the vowel move).
`secondary` is `q_crank` (tighten radius, freq-LOCKED: `r' = 1 − amount·(1−r)`) | `weight` (scale gain) | `open`.
The 4 corners = base, +morph, +secondary, +both → labels `M0_Q0 / M100_Q0 / M0_Q100 / M100_Q100`.

**anatomy** — `pole_hz` (20..SR·0.49), `sharp` (radius 0.5..0.999).

**articulation** — a named cut (zero = ratio of pole), or `cut:"custom"` with
`zero:{ratio,depth,track}` and optional `morph_move` (zero ratio shifts HOME→AWAY = "the cut moving").

| cut | zero_hz | depth | character |
| --- | --- | --- | --- |
| `none` | — | — | pure resonator |
| `hug` | pole×0.667 | 0.60 | hollow under the pole |
| `tear` | pole×1.15 | 0.92 | bite just above |
| `sub_kill` | pole×0.25 | 0.85 | scoop below |
| `air_cap` | pole×4.0 | 0.60 | soft ceiling |
| `air_kill` | 12000 (abs) | 0.70 | hard top cap |

(These ratios are the implemented `Cut` rules in `forge/src/main.rs`.)

**survival** — `gain` is intent; the compiler still enforces `unity_dc` (50 Hz = +0 dB, never boost sub)
and rejects radius ≥ `max_radius` across the **whole Morph×Q grid** (not just the 4 corners).

## Bake — one owner, no second path

`recipe → forge::Part::biquad → trench_core::trench_packed_encode (canonical) → 240 bytes → keyframes`,
then load through the **shipped `trench_core.dll`** and run the Morph×Q survival gate. The runtime,
the bench plot, and the batch generator all consume **this one bake** — no tool re-derives bytes
its own way (that's the rule that keeps the recipe from becoming copy #31).

## 1,000 filters — `forge-batch-v1`

Vary lawful knobs from one base; never spray roots, never four unrelated corners. Deterministic from a seed.

```jsonc
{ "format":"forge-batch-v1", "seed":1337, "count":1000, "base":"mouth_ah.cartridge.json",
  "vary": {
    "axes.morph.slide_semitones": { "range":[4,12] },
    "lanes[1..4].anatomy.pole_hz":{ "jitter_pct":12, "log":true },
    "lanes[2].articulation.cut":  { "choices":["tear","hug","air_cap"] }
  },
  "gate":"survival" }   // only emit recipes whose bake passes the grid audit; ear curates survivors
```

## Not

- Not a coefficient editor (`c0..c4` never appear). Not an AI author (compiler guarantees *realizable*, not *good*).
- Not a fourth runtime format — bakes into the same `keyframes` the player already reads.
- Not per-stage busywork — 6 lanes + 2 axes, not 24 filters.

See `forge/recipes/forge-cartridge-v1.schema.json` and `forge/recipes/mouth_ah.cartridge.json`.
