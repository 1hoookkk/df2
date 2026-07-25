# Clean-room authoring brief — replacing the E-mu-derived ship presets

**Date:** 2026-07-25 · **Audit:** `dev/tmp/ship_provenance.json`

## Why this exists

A measured provenance audit of the 45 shipping presets against 137 known
E-mu-derived reference bodies (69 heritage Morph Designer XML compiles, 33
P2K/ROM corpus bodies, 35 ROM-fitted archetypes) found:

| verdict | count |
|---|---|
| **byte-identical to an E-mu reference** | **9** |
| close (1.7–4.0 dB response distance) | 6 |
| unrelated to any reference | 30 |

Three of the five ear-approved signature presets are in the byte-identical set:

| ship preset | is | source |
|---|---|---|
| Fable | `P2k_003_millennium` | **ROM** |
| Speaker Knockerz | `P2k_000_ace_of_bass` | **ROM** |
| Low Pass Pressure | `Low Pass Pleasure` | E-mu factory XML |
| Bass Time | 4.90 dB from `P2k_028_bass_o_matic` | borderline — review |
| Bruh | 8.80 dB from anything | **genuinely original** |

This breaks the notebook's locked rule that no ROM-derived bodies ship.

## What "clean room" can and cannot mean here

**Cannot:** a formal clean room is a wall between someone who studies the
original and someone who implements from a written spec. That wall cannot be
built retroactively by people who have already seen the bytes.

**Can:** a filter's frequency response is a *fact*, and facts are not
copyrightable. Measuring what a body does, writing it down behaviourally, and
authoring an original body that does the same job with our own tools is
legitimate independent creation.

**The line:** do not fit to the original's curve. A body that lands a hair from
the source is the "micro-shift IP dodge" this repo already deleted once. Author
toward the *character*; verify the result sits far from the source in the data.

**Acceptance gate for a replacement:**
1. response distance from the source body **≥ 6 dB** (Bruh sits at 8.8 dB),
2. certify PASS at 25×25, maxR < 0.9999,
3. all four corners authored — Q must not be a dead axis,
4. passes the ear on real material, level-matched.

## The briefs

Measured behaviour only — corner, slope, resonance, and how they travel across
MORPH and Q. No coefficients, no pole coordinates. These are targets for
character, not curves to fit.

### 1. Replaces **Fable** (was `millennium`)
A bass resonance that climbs into the low mids as MORPH opens, with Q adding a
separate upper peak.

| pose | peak | at | −3 dB corner | slope |
|---|---|---|---|---|
| M0 Q0 | +12.3 dB | 59 Hz | 100 Hz | −13 dB/oct |
| M100 Q0 | +8.0 dB | 856 Hz | 1076 Hz | — |
| M0 Q100 | +2.8 dB | 1281 Hz | 2220 Hz | −25 dB/oct |
| M100 Q100 | +13.3 dB | 2715 Hz | 426 Hz | −15 dB/oct |

Character: aggressive low-pass. Resonant peak travels **59 Hz → ~860 Hz** across
MORPH. Q relocates the emphasis upward rather than simply sharpening it —
the Q100 peak lands ~2.7 kHz. Roughly 12–15 dB/oct skirt.

### 2. Replaces **Speaker Knockerz** (was `ace_of_bass`)
Q is the entire story. Nearly flat with Q down; a hard low bloom with Q up.

| pose | peak | at | −3 dB corner | slope |
|---|---|---|---|---|
| M0 Q0 | −1.9 dB | 20 Hz | 100 Hz | −6 dB/oct |
| M100 Q0 | 0.0 dB | 20 Hz | 880 Hz | −22 dB/oct |
| M0 Q100 | +13.3 dB | 86 Hz | 127 Hz | −14 dB/oct |
| M100 Q100 | +19.2 dB | 868 Hz | 1230 Hz | −5 dB/oct |

Character: **Q0 is essentially unprocessed** (peak ≤ 0 dB) — the preset does
nothing until Q is raised, then blooms **+13 to +19 dB**. Bloom centre moves
86 Hz → 868 Hz with MORPH. This is the sub/bass knock. The flat Q0 pose is the
design, not a fault.

### 3. Replaces **Low Pass Pressure** (was `Low Pass Pleasure`)
Mid-forward resonant low-pass with a very large Q bloom.

| pose | peak | at | −3 dB corner | slope |
|---|---|---|---|---|
| M0 Q0 | +5.7 dB | 769 Hz | 1247 Hz | −13 dB/oct |
| M100 Q0 | +12.4 dB | 521 Hz | 834 Hz | −13 dB/oct |
| M0 Q100 | +23.5 dB | 845 Hz | 1333 Hz | −13 dB/oct |
| M100 Q100 | +24.5 dB | 535 Hz | 868 Hz | — |

Character: peak parked in the **520–850 Hz** band at every pose; MORPH lowers it
slightly, Q drives it from **+6 dB to +24 dB**. Consistent ~12–13 dB/oct skirt.
The identity is the fixed mid-band emphasis with an enormous Q range.

## Also outstanding

The other 6 byte-identical and 6 close bodies (Complex BP 1, Rezzy LP 1,
Steep 8 Pole, Super Lo Pass, Twin Peaks, Voxxy LP 1, Low to High Pass,
Wah Wah 1/2, Lo Pass Slicer, Low Pass Pleasure, Steep Hi Pass) are all heritage
XML compiles. Same treatment applies, but they are workhorses rather than ear
picks — the roster decision (which survive, under what names) comes first.

Bass Time at 4.90 dB deserves a closer look before it is called original.
