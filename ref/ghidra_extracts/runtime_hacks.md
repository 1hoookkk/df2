# Runtime Special Cases

Source: `EmulatorX.dll`.

This note separates universal runtime behavior from class-specific coefficient
writers. The formulas and addresses are observed. Descriptive names are
shorthand.

## Packed Interpolation

`FUN_1802c3d40` clamps both live controls to `0..1`, then bilinearly
interpolates each packed `u16` word. Each intermediate leg truncates before the
next interpolation leg. The interpolation occurs before minifloat decode.

## Packed Decode

`FUN_1802c3600` has explicit sentinels:

```text
decode(0x0000) = 0.0
decode(0xffff) = 1.0
```

After decoding, it recombines:

```text
c0 = 4 * d0 + d1
c1 = d1
c2 = 4 * d2 + d3
c3 = d3
c4 = runtime_scale * d4
```

`FUN_1802c0150` initializes `runtime_scale` at `object + 0x2a8` to `4.0`.

## AGC Table Construction

`FUN_1802bfa10` copies the 16-float base AGC table into each live instance.

```text
sample_rate <= 65000:  value
65000 < sample_rate <= 130000: sqrt(value)
sample_rate > 130000: sqrt(sqrt(value))
```

## AGC Processing

`FUN_1802c04e0` keeps a running multiplier at `this + 0x08` and reads the live
16-float table at `this + 0x44`. The index wraps with `& 0x0f`; it does not
clamp. Mono uses the sample magnitude. Interleaved stereo uses the larger
channel magnitude and applies one shared gain update to both channels.

If the updated gain is below `1.0`, samples are multiplied by it. Otherwise the
running gain is reset to `1.0`.

The repo's `agc_drive` pre-scale is an authoring and audition control. It is not
part of the observed DLL path.

## Morph Designer Padding

`FUN_1802c6590` skips descriptor types outside `1..3`. If at least four valid
rows compile, it forces runtime row count to six and pads missing rows with:

```text
[0xdfff, 0xffff, 0xdfff, 0xffff, 0xe000]
```

## Adjacent Class Writers

The Type `1..3` Morph Designer grammar is not the only writer targeting the
corner banks.

`FUN_1802c59b0` writes a fixed three-row structure and duplicates both endpoints
across the Q axis. Its callers provide different fixed words or table-selected
profiles:

| Function | Observed special case |
| --- | --- |
| `FUN_1802c5d60` | fixed fallback words passed into the three-row writer |
| `FUN_1802c5e40` | chooses one of 16 six-word profiles using clamped live control |
| `FUN_1802c5f10` | chooses one of 16 three-word profiles and mirrors them |
| `FUN_1802c6020` | independent fixed three-row writer with signed spread controls, boundary folding, and radius clamps |

These are class-specific authoring grammars. They should be treated as separate
metrology targets rather than merged into the Morph Designer Type `1..3`
compiler.

## P2K Hedz ROM Bank

Talking Hedz is not produced by the Q-collapsed Morph Designer or generated X3
writers above. The provenance-bearing P2K target is the 240-byte packed ROM bank
at `ref/presets/P2k_013_talking_hedz.bin`.

Observed provenance:

```text
DAT_1806d762e + (skin_index * 4 + variant) * 0xf0
skin_index = 13
variant = 0
dat_index = 52
layout transposed by FUN_1802d3ce0
```

The current `trench-core/src/hedz_rom.rs` fixture mirrors those packed words and
`Cartridge::hedz_rom()` enters the packed interpolation path. The retired
MorphDesigner-derived float/golden fixture was Q-collapsed and must not be used
as Talking Hedz truth.
