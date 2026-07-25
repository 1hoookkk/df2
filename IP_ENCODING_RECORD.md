# TRENCH — Encoding & Interpolation Record

**Purpose:** a locked, source-referenced statement of what the shipping runtime
actually stores and interpolates, for review by patent counsel against
US 10,514,883 B2 claim 1.

**Repository:** `df2-workstation`, branch `ui/five-point-cleanup`
**Commit at time of writing:** `07ae504c23035b27e636adda4bb7a0faff3c703a`
**Date:** 2026-07-25

> **Correction notice.** An earlier informal description of this encoding —
> stating that word[2] holds a pole frequency and word[3] a pole radius — was
> **wrong**. It described the output of an authoring helper
> (`geometry_from_words`), not the stored data. That error was circulated before
> being caught. This document supersedes it. Everything here is verified against
> source and by executing the shipping library. **Independent verification by
> counsel is still required; do not rely on this document alone.**

---

## 1. What is stored

A body is 240 bytes: 4 corners × 6 stages × 5 little-endian `u16` words.
Corner order is fixed: `M0_Q0`, `M100_Q0`, `M0_Q100`, `M100_Q100`.

Per stage, for a pole at angular frequency ω and radius r
(`trench-core/src/stage_law.rs:44`, `words_from_roots`):

```
c2 = 2 − 2·r·cos(ω)
c3 = 1 − r²
word[2] = encode( (c2 − c3) / 4 )   =  (1 − 2·r·cos ω + r²) / 4
word[3] = encode( c3 )              =  (1 − r²)
```

The zero pair uses the identical scheme in `word[0]` / `word[1]`.
`word[4]` is a scale term (b0).

Expressed in biquad coefficients, with `a1 = −2·r·cos ω` and `a2 = r²`:

```
word[2] = (1 + a1 + a2) / 4     ← a function of BOTH a1 and a2
word[3] = (1 − a2)              ← a function of a2 only
```

`word[2]` is the denominator polynomial evaluated at DC, scaled. **The stored
quantities are nonlinearly-coded affine functions of the biquad coefficients.**

**No frequency value is stored.** Frequency does not exist in the packed data.
It is *recovered* at decode time from both words jointly
(`stage_law.rs:152`, `pair_geometry`):

```
q      = 1 − decode(word[3])
c      = 4·decode(word[2]) + decode(word[3])
p      = c − 2
r      = √q                    ← from word[3] alone
cos ω  = −p / (2r)             ← from BOTH words
```

`encode` / `decode` are a piecewise-logarithmic 16-bit code
(`minifloat.rs:4`).

---

## 2. Verification performed

### 2a. Encode side — sweep one variable, observe the words
Through `trench_stage_words_from_roots` in the shipping library:

| pole Hz (radius fixed 0.90) | word[2] | word[3] |
|---|---|---|
| 200 | 30306 | 55377 |
| 500 | 32818 | 55377 |
| 1000 | 37123 | 55377 |
| 2000 | 43570 | 55377 |
| 4000 | 51115 | 55377 |
| 8000 | 58595 | 55377 |

`word[3]` is **constant** across a 40:1 frequency sweep.

| radius (frequency fixed 1000 Hz) | word[2] | word[3] |
|---|---|---|
| 0.50 | 49362 | 63487 |
| 0.70 | 43946 | 61521 |
| 0.90 | 37123 | 55377 |
| 0.95 | 35756 | 51445 |
| 0.99 | 35397 | 42080 |

Both words move with radius.

### 2b. Decode side — real shipping bytes
Source: `plugin/presets/bodies/bruh.body240`, corner `M0_Q0`, stage 1.
Stored words `[31228, 55292, 64253, 51452, 53490]`, decoding to
pole 15274.3 Hz r=0.9499, zero 357.2 Hz r=0.9014.
Perturbing one word at a time (−1500 counts):

| perturbed | Δ frequency | Δ radius |
|---|---|---|
| word[2] (pole) | −3024.15 Hz | **+0.000000** |
| word[3] (pole) | −207.51 Hz | +0.011972 |
| word[0] (zero) | −287.24 Hz | **+0.000000** |
| word[1] (zero) | +194.23 Hz | +0.025043 |

**Radius is a pure function of a single word. Frequency is a function of both.**
There is no word from which frequency can be recovered alone. The asymmetry is
identical for the pole pair and the zero pair.

### 2c. Interpolation path
The only runtime path is:

```
FilterEngine::set_parameters        engine.rs:372
  → Cartridge::interpolate          cartridge.rs:164
    → PackedCorners::interpolate_biquad   minifloat.rs:170
      → PackedCorners::interpolate        minifloat.rs:162
        → interpolate_words               minifloat.rs:147   ← bilinear lerp on the u16 CODE VALUES
        → stage_words_to_kernel           minifloat.rs:62    ← decode
      → kernel_to_biquad                  minifloat.rs:76    ← decode to [b0,b1,b2,a1,a2]
```

Interpolation is a bilinear lerp of the stored `u16` code values across the four
corners. Nothing in the runtime interpolates a frequency, a radius, or any
decoded quantity. Repo test `interpolate_words_is_the_exact_source_of_decoded_interpolation`
(`minifloat.rs:603`) asserts this.

**Disclosed for completeness:** `set_parameters` applies two optional
*post-decode* transforms — `snap_stage_to_key` (KEY SNAP) and
`transpose_conjugate_pair` (pitch ratio). These operate on already-decoded
coefficients in a frequency-aware way, *after* interpolation. They are product
features, both default-off, and are not part of the interpolation path — but
they are frequency-aware code and counsel should be aware of them.

---

## 3. Relevance to US 10,514,883 B2, claim 1

The limitation at issue:

> "...by interpolating encoded values of a plurality of frequency responses,
> **a frequency and a resonance of each frequency response being encoded
> independently**; determine one or more filter coefficients based on decoding
> the interpolated encoded values..."

On the facts above: resonance is encoded independently (recoverable from one
word); **frequency is not encoded at all** and is recoverable only from both
words jointly. Whether that satisfies a conjunctive limitation is a claim
construction question for counsel, not an engineering conclusion.

Noted for counsel, not asserted as a legal position: the scheme is structurally
of the same family as the **expired** US 5,170,369 (Rossum / E-mu, assigned to
Creative Technology, filed 1990-08-29, issued 1992-12-08), which log-codes a
magnitude term `B2'` and the difference `B1'−B2'`, interpolates
`C(x) = Ca + x(Cb − Ca)` at the compressed representation level, and decodes
afterwards. `'369` describes its own coding as *"approximating"* logarithmic
frequency and resonance control.

---

## 4. Open items for counsel

1. Claim construction of "encoded independently" — does it require both
   quantities, and does it describe storage or controllability?
2. Doctrine of equivalents, including prior-art ensnarement by `'369`.
3. Prosecution history of `'883`: whether "encoded independently" was added by
   amendment or argued in remarks (estoppel), and continuity/continuation status.
4. Full text of `'369` (only excerpts reviewed here).
5. **Provenance of this encoding scheme** — whether it was derived independently
   or informed by reverse-engineering work. This is a factual question for the
   author to answer, and it is separate from the patent question. It is recorded
   here as open, not answered.

---

## 5. How to reproduce

```
cargo build --release                     # produces target/release/trench_core.dll
```
Then drive `trench_stage_words_from_roots` (roots order: pole_hz, pole_r,
zero_hz, zero_r, scale) and `trench_stage_roots_from_words` against
`plugin/presets/bodies/*.body240`. Both are exported in
`trench-core/src/ffi.rs`.
