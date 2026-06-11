# Morph Designer Type Grammar

Source: `EmulatorX.dll`, `FUN_1802c6590`.

This is a direct static extraction of the Morph Designer class compiler. The
descriptive type names are shorthand; the packed-word formulas are the oracle.

## Input Layout

The compiler reads six records from `param_2 + 0x20`. Each record is six bytes:

| Offset | Meaning |
| --- | --- |
| `+0` | type ID |
| `+1` | endpoint A frequency |
| `+2` | endpoint A gain |
| `+3` | endpoint B frequency |
| `+4` | endpoint B gain |
| `+5` | unused by this compiler |

Only type IDs `1..3` compile. Type `0` and values above `3` are skipped.

## Shared Values

The sample-rate family index is read from `param_1 + 0x0c`.

```text
base  = [18, 18, 4, 1]       # DAT_1806d7510
scale = [220, 220, 200, 177] # DAT_1806d7520

shift = -32 + trunc((runtime.frequency + runtime.gain) * 63.0)
freq  = ((scale[family] * frequency_byte) >> 7) + base[family]
gain  = clamp(((signed gain_byte - 0x40) >> 1) + shift, -32, 31)
rad   = ((freq * 0x7c) >> 8) + 0x76
```

The gain bytes in the vendor XML corpus stay inside `0..127`, but the DLL load
is signed.

## Type 1

```text
w0 = freq << 8
w1 = clamp(rad + gain, 0, 255) << 8
w2 = freq << 8
w3 = clamp(rad - gain, 0, 255) << 8
w4 = 0xe000
```

## Type 2

For families `0..1`:

```text
w0 = 0xec00
w1 = 0xff00
w2 = freq << 8
w3 = clamp(rad - gain, 0, 255) << 8
w4 = (freq + 0xf5) << 8
```

For families `2..3`:

```text
w0 = 0xe100
w1 = 0xf000
w2 = freq << 8
w3 = clamp(rad - gain, 0, 255) << 8
w4 = freq << 8
```

## Type 3

For all families:

```text
w0 = base[family] << 8
w1 = (((base[family] * 0x7c) >> 8) + 0x96) << 8
```

For families `0..1`, only emitted `w2` receives the split-code compression:

```text
emitted_freq = freq
if freq > 0xdb and gain < 0:
    emitted_freq = (((freq - 0xdc) * (gain + 0x20)) >> 5) + 0xdc

w2 = emitted_freq << 8
w3 = clamp(rad - gain, 0, 255) << 8
w4 = ((freq - 18) * -12 - 8192) & 0xffff
```

`w3` and `w4` use the uncompressed `freq`. For families `2..3`, there is no
split-code compression and `w4 = 0xe000`.

## Runtime Rows

Endpoint A is written to `runtime + 0x2c0` and `runtime + 0x338`. Endpoint B is
written to `runtime + 0x2fc` and `runtime + 0x374`. The historical Q axis is
therefore collapsed.

When four or more valid rows compile, the runtime row count is forced to six
and missing rows are padded with `DAT_1806d7500`:

```text
[0xdfff, 0xffff, 0xdfff, 0xffff, 0xe000]
```

## Shared Runtime Decode

`FUN_1802c3d40` clamps both morph controls to `0..1`, performs bilinear
interpolation in packed `u16` space, and truncates each interpolation leg before
the next leg.

`FUN_1802c3600` then decodes the five minifloat words and recombines them:

```text
c0 = 4 * decode(w0) + decode(w1)
c1 = decode(w1)
c2 = 4 * decode(w2) + decode(w3)
c3 = decode(w3)
c4 = runtime_scale * decode(w4)
```

`FUN_1802c0150` initializes `runtime_scale` at `object + 0x2a8` to `4.0`.
This fifth-word scale is universal runtime decode behavior, not a Type 3 rule.

## Ghidra Anchors

| Address | Meaning |
| --- | --- |
| `0x1802c6650` | validate type ID `1..3` |
| `0x1802c6792` | Type 2 branch |
| `0x1802c67fe` | Type 3 branch |
| `0x1802c6878` | Type 3 endpoint A split-code compression |
| `0x1802c68a1` | Type 3 endpoint B split-code compression |
| `0x1802c6968` | write compiled endpoint banks |
| `0x1802c6a5c` | pad missing rows |
| `FUN_1802c3d40` | clamp and interpolate packed corner words |
| `FUN_1802c3600` | decode and recombine packed words |
| `FUN_1802c0150` | initialize runtime fifth-word scale to `4.0` |
