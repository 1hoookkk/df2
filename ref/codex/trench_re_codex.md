# TRENCH Z-Plane Filter Architecture — Verified Findings
## NotebookLM Source Document — March 2026

Everything below was proven through Ghidra decompilation, Cheat Engine memory capture, or code validation. No outside frameworks. No analogies. Only what was found in the binary.

---

## The Pipeline

The Z-Plane filter runs as a strict 4-function pipeline inside EosAudioEngine.dll:

1. **FUN_1802c6590** (Compiler) — Takes 6-byte stage descriptors, produces four banks of encoded uint16 quintuplets.
2. **FUN_1802c3d40** (Interpolator) — Bilinear interpolation across four corner banks. Morph controls one axis, Q controls the other.
3. **FUN_1802c3600** (Decoder) — Converts interpolated uint16 quintuplets into five floating-point coefficients per stage: c0, c1, c2, c3, c4.
4. **FUN_1802c1550** (Render Kernel) — Executes a 6-stage serial biquad cascade using those floats.

---

## The Render Kernel

Proven via Ghidra decompilation of FUN_1802c0ad0 and FUN_1802c1550. The biquad form is proprietary to Dave Rossum. It is not Direct Form I, not Direct Form II, not DF2T. Per-sample, per-stage math:

```
temp = input + s1*c3 - s0*c2
s0_new = s0 * 2.0 + temp - s1
s1_new = s0_old
output = (s0*c0 + temp - s1*c1) * c4
```

The 2.0 constant lives at DAT_18065a314. Coefficients interpolate per-sample, not per-block. CPhantomRTFilter constructor confirms 6 stages. Stage output feeds directly into the next stage input — cascade topology proven, no parallel summing found anywhere in the binary.

---

## The Compiler (FUN_1802c6590)

Each stage is defined by a 6-byte descriptor. Layout:

```
[type, radius_A, Q_offset_A, radius_B, Q_offset_B, pad]
```

- Byte 0 (type): 0=off, 1=normal, 2=shelf, 3=special/vocal
- Bytes 1-2: Low-morph endpoint pair (grouped by morph corner, not by parameter type)
- Bytes 3-4: High-morph endpoint pair
- Byte 5: Padding or unknown

The compiler reads these from the preset object at param_2 + 0x20 through 0x43 (36 bytes total for 6 stages).

Type branches change how the compiler calculates the encoded uint16 output:
- **Type 1 (Normal):** Standard resonator math.
- **Type 2 (Shelf):** Shelf filter scaling.
- **Type 3 (Special/Vocal):** Applies byte-domain frequency compression before the frequency lookup. When Morph is fully negative (-32), any frequency byte above 0xDB is forced to 220. This creates a divergence where the intended UI frequency differs from the realized pole placement — the "split-code hack." This is what gives vocal filters stable anchor points at extreme morph positions.

Inactive stages receive the bypass sentinel: uint16 value -8192, which decodes to unity-gain identity coefficients.

---

## The Q-Law

The Q-law is not a separate function. It is the bilinear interpolation itself.

The compiler pre-builds four corner banks: M0_Q0, M100_Q0, M0_Q100, M100_Q100. At runtime, FUN_1802c3d40 interpolates between all four. Q selects position on one axis, Morph selects the other. The radius at any Q value is the interpolated result — not a standalone algebraic mapping.

This interpolation happens on the raw uint16 values before they are decoded to float. The non-linearity of the uint16 encoding means the interpolation path differs from what you would get interpolating in the float domain. This contributes to the specific character of the morph behavior.

Empirical Cheat Engine captures confirmed Q-to-radius movement:
- Q 0%: radius approximately 0.887
- Q 50%: radius approximately 0.951
- Q 100%: radius approximately 0.980

These values are the output of the 4-corner surface interpolation, not a standalone formula.

---

## Two Separate Filter Systems

These must not be conflated:

**MorphDesigner filters:** The Morph Designer authors 2 logical corners (low morph, high morph). The compiler duplicates them into 4 runtime banks. This makes the Q axis degenerate — bank0 equals bank2, bank1 equals bank3. The morph surface is effectively 1D. MorphDesigner is one of 5 computed filter classes where the Q knob has zero effect on the coefficients.

**P2K and sealed factory presets:** These have genuinely distinct 4-corner coefficient banks. The morph surface is truly 2D (Morph x Q). The 33 P2K filter skins were decoded directly from the DLL rdata section — 6 stages, 4 corners, 10 bytes per stage per corner, 240 bytes per preset. All 33 produce audio through the TRENCH engine with zero crashes and zero NaN.

---

## Talking Hedz

Talking Hedz is a sealed factory preset. It is P2K skin index 13 (hardware code 144). Its name string lives at RVA 0x1FF5DA8 in the DLL resource table (type=6, id=51, lang=1033). It cannot be opened in the Morph Designer. Its 36-byte stage descriptor is embedded somewhere in the binary — the exact static memory location has not yet been found.

The caller chain feeding the descriptor into the compiler was traced: FUN_1802a6770 then FUN_1802a75a0 then FUN_1802ce160 then FUN_1802c0150. FUN_1802c0150 writes the preset pointer to param_1+0x20. The origin of that pointer (which static data address it references) is the missing link.

What is known from runtime observation:
- The Morph Designer screenshot showed Stage 1 as Off — Talking Hedz uses 5 active stages. [UNVERIFIED — coefficient data shows all 6 stages non-trivial at all 4 corners. "Off" may be a UI label, not a coefficient state.]
- Runtime coefficient memory addresses shift on every X3 restart (dynamic pointer structure).
- P2K coefficients compute on the stack only — no persistent heap storage. Cheat Engine float scans after Q changes returned zero results.

---

## Sample Rate

The P2K hardware computes coefficients at 39,062.5 Hz (10 MHz divided by 256). This is a deliberate character decision by Dave Rossum, not an optimization artifact. All reference coefficient data is normalized to this rate. [SCOPE: This is the coefficient domain, not the audio execution rate. EmulatorX and TRENCH both run at the host sample rate and warp coefficients from this domain.]

At higher host sample rates, the binary applies conditional sqrt compensation via the 18 sqrt operations found at address 0x2BEE20. The logic: raw values at 44.1 kHz, single sqrt at 88.2 kHz and above, double sqrt at 176.4 kHz and above.

P2K static tables at 39,062.5 Hz are the authoritative coefficient source. Cheat Engine captures from X3 running at 44,100 Hz were demoted because X3 applies its own sqrt warping that changes the values.

---

## The Oscillator Tables Are Not Filter Tables

CPhantomBandLimitedTable was initially hypothesized to contain Q damping tables for the morph filter. This was disproven through full-chain tracing in Ghidra. It contains polyphase SINC resampler kernels consumed by CPhantomRTOscillator (vtable offset 0x130) for anti-aliasing during pitch shifting. Seven source tables select frequency bands by pitch threshold and apply 8-tap FIR filtering.

CPhantomCoarseTable: 128 entries mapping MIDI semitones to frequencies.
CPhantomFineTable: 401 entries for sub-semitone pitch interpolation.

All oscillator infrastructure. The morph filter Q-law does not use any of these tables.

---

## P2K Coefficient Format

The proven encode formula for P2K cartridges:
```
b0 = 1 + val1
b1 = a1 + val2
b2 = r squared - val3
a2 = r squared
```

The DSP core achieved 0.990 to 0.9998 correlation across all reference comparisons when validated. All 33 P2K filters were converted to engine format and tested: RMS levels range from -5.6 dB to -26.7 dB, morph sweeps are smooth, zero instability detected.

---

## The Open Question: Stage 0 Type Byte

The single highest-priority unknown is: what is Stage 0's type byte in the Talking Hedz preset?

If Type 2 (shelf): standard algebraic scaling applies to Stage 0.
If Type 3 (special/vocal): the split-code frequency compression hack applies to Stage 0, meaning the body stage of Talking Hedz is subject to the same Nyquist-area anchoring as the vocal formant stages.

Two paths to resolve this:
1. Trace FUN_1802c0150 or FUN_1802a3A80 in Ghidra to find the static data address storing the Talking Hedz 36-byte descriptor. Read byte 0 directly.
2. Implement both Type 2 and Type 3 for Stage 0 in the TRENCH engine, run RMS error against existing runtime capture data, and let the audio discriminate.

Path 2 is cheaper. Path 1 is definitive.

---

## CPhantomBatman (Bat Phaser)

Bat Phaser is hardware filter type 66 (0x42,00h). It is NOT a Z-Plane morph surface. It is a dedicated firmware class with its own vtable at 0x1806d6030, its own ROM coefficient tables, and its own coefficient format. It does not pass through the Z-Plane compiler/decoder pipeline (FUN_1802c6590 / FUN_1802c3600).

### Coefficient Format

Batman ROM tables use **signed Q14 fixed-point** (i16 / 16384). This is different from the Z-Plane uint16 minifloat encoding used by P2K skins and MorphDesigner presets. The previous decode failure (values ~0.01–0.4) was caused by two compounding errors: reading from the wrong base address (Ghidra decompiler folded a +0x1E pointer offset into the DAT reference) and applying the wrong numeric format (minifloat instead of Q14).

### ROM Table Layout

The coefficient loader FUN_1802c5620 references a true base address of **0x1806d6CC0** (not DAT_1806d6cde as shown in the decompiler output — the decompiler merged `base + 0x1E` into a single symbol).

Each sample-rate block is 0x50 (80) bytes for the 2-stage loader, or 0x78 (120) bytes for the 3-stage loaders. Within each block, the layout per stage is 40 bytes = 4 groups of 5 u16 values (20 shorts). The 4 groups are 4 interpolation corners, each holding one biquad's coefficients [b0, b1, b2, a1, a2].

Sample rate indexing (stored at object offset 0xC):

| Sample Rate | Index |
|---|---|
| 44100 | 0 |
| 48000 | 1 |
| 96000 | 2 |
| 192000 | 3 |

### Vtable Structure

The Batman vtable at 0x1806d6030 contains 4 groups of 4 slots each. Slot 1 in each group is a coefficient loader function:

| Slot | Function | ROM Base | Stride | Stages | Stage Count |
|---|---|---|---|---|---|
| 1 | FUN_1802c5620 | 0x1806d6CC0 | 0x50 | 2 | 2 |
| 5 | FUN_1802c5710 | 0x1806d6E00 | 0x78 | 3 | 3 |
| 9 | FUN_1802c57F0 | 0x1806d6FE0 | 0x78 | 3 | 3 |
| 13 | FUN_1802c58D0 | 0x1806d71C0 | 0x78 | 3 | 3 |

All four loaders share the same copy structure — only the ROM base, stride, and loop count differ. Each writes a stage count to offset 0x420 in the runtime object.

### Filter Chain

The master filter factory (FUN_1802ae650) constructs Batman as a filter chain: a fixed **CPhantomLP2Pole** (2-pole lowpass) followed by the Batman ROM stages. Total pole count is 2 + (2×2) = 6 poles for loader 0, or 2 + (3×2) = 8 poles for loaders 1–3.

### Verified Response

Loader 0, corner A, decoded as Q14, produces a phaser notch at approximately 10 kHz with 39 dB of rejection. The response recovers above and below the notch. This is consistent with the expected Bat Phaser behavior observed in Emulator X3.

```
Stage 0 corner A: b0=0.515  b1=0.030  b2=0.577  a1=-1.985  a2=-0.493
Stage 1 corner A: b0=1.015  b1=0.030  b2=0.953  a1=-1.985  a2=-0.493
```

### Fixed-Point Format Split

The 4 loaders use two different fixed-point scales:

| Loader | Sample Rate | Format | Divisor | Stages |
|---|---|---|---|---|
| 0 | 44100 Hz | Q14 | 16384 | 2 |
| 1 | 48000 Hz | Q14 | 16384 | 3 |
| 2 | 96000 Hz | Q15 | 32768 | 3 |
| 3 | 192000 Hz | Q15 | 32768 | 3 |

Higher sample rates use Q15 for more fractional precision near the unit circle. The 4 vtable groups correspond to sample rate bands, not filter modes. At 44.1 kHz the filter is 2-stage (4-pole from ROM + 2-pole fixed LP = 6-pole). At 48 kHz and above it becomes 3-stage (6-pole from ROM + 2-pole fixed LP = 8-pole) to maintain the analog prototype response at higher rates.

### Verified Cascade Response (Corner A, ROM stages only, no LP2Pole)

| Frequency | 44.1k (2stg) | 48k (3stg) | 96k (3stg) | 192k (3stg) |
|---|---|---|---|---|
| 100 Hz | +0.2 dB | -4.8 dB | -5.4 dB | -26.7 dB |
| 1000 Hz | -0.2 dB | -5.4 dB | -5.6 dB | -26.7 dB |
| 5000 Hz | -8.6 dB | -12.4 dB | -8.9 dB | -25.4 dB |
| 10000 Hz | -39.2 dB | -19.5 dB | -14.6 dB | -22.1 dB |
| 20000 Hz | -10.5 dB | -33.2 dB | -25.0 dB | -11.8 dB |

### CPhantomLP2Pole (Fixed 2-Pole Stage)

The fixed LP in the Batman chain has its own ROM table and vtable.

- **Vtable:** 0x1806d5e50
- **Loader:** FUN_1802c4b80 (slot 1)
- **ROM base:** 0x1806d65E0
- **Stride:** 0x28 (40 bytes per sample rate entry)
- **Stages:** 1 (writes stage count = 1 at offset 0x420)
- **Format:** Q15 (i16 / 32768)
- **Layout:** 4 groups of 5 shorts = 4 interpolation corners × 1 biquad

At 44100 Hz corner A: b0=-0.250, b1=-0.000, b2=+0.140, a1=-0.649, a2=+0.140. Produces a lowpass shape with ~13 dB passband attenuation. Gain is not separately compensated — the attenuation is part of the raw filter behavior (see Gain Compensation section). The full 6-pole cascade (Q15 LP2Pole + Q14 Batman 2-stage) produces a 47 dB phaser notch at 10 kHz with lowpass envelope.

### Interpolation Manifold

The 4 corner groups map to the same bilinear interpolation grid used by all E-mu filters:

| Corner | Offset | Position |
|---|---|---|
| A | 0x2C0 | Morph 0, Q 0 |
| B | 0x2FC | Morph 100, Q 0 |
| C | 0x338 | Morph 0, Q 100 |
| D | 0x374 | Morph 100, Q 100 |

Evidence: A↔C and B↔D share b0, b1, b2, a2 — differ only in a1 (pole position). This is the Freq/Morph axis. A↔B and C↔D differ in b0, b2, a1 — the numerator/zero shape changes. This is the Res/Q axis.

For MorphDesigner filters, the Q axis is degenerate (A=C, B=D — compiler duplicates). For P2K and factory presets including Batman, all four corners are genuinely distinct.

### Gain Compensation

Gain is NOT compensated between corners. The 19 dB spread across corners is the raw filter behavior at extreme parameter positions. A separate AGC (FUN_1802c04e0, 16-value table) handles overall envelope leveling but does not smooth the internal gain variation. The interpolation happens in the minifloat/fixed-point domain, producing non-linear coefficient movement in the float domain — this contributes to the specific character of the morph behavior.

### Clean-Room Boundary

The decoded ROM coefficients are reference measurements, not shipping assets. TRENCH must not ship coefficient-for-coefficient copies of these tables. The cartridge path is:

1. Measure the behavioral envelope (notch depth, frequency range, spectral tilt, corner shapes) from the decoded data.
2. Define high-level response goals from measurements and listening tests.
3. Author a new 3-stage/4-corner body by optimization or manual design inside the forge.
4. Keep original raw coefficients out of the shipping asset path.
5. Maintain a paper trail showing the shipping cartridge was authored from target behavior.

### Open Questions

- Whether the CPhantomLP2Pole in the chain uses its own ROM table or is parametrically computed from Freq/Res controls.
- Whether the vtable dispatch is purely sample-rate-based or if runtime parameter ranges can also select between loaders.

---

## What This Document Intentionally Excludes

The following topics are excluded because the data is either unvalidated or outside the scope of historical reconstruction:

- The forge (trench-forge): modern original filter generation, not historical truth
- Zero-placement statistics from P2K analysis: not independently verified for this document
- The preDecodeBlock at 0x0056D4A0: captured but functionally unvalidated
- ARMAdillo v-domain extraction values: captured but relationship to numerator unresolved
- Cartridge naming conventions, UI design, or brand identity
- Any framework, analogy, or methodology not found in the EosAudioEngine.dll binary
