# Clean-room authoring brief — replacing the E-mu-derived ship presets

**Date:** 2026-07-25 · **Audit:** `dev/tmp/ship_provenance.json`

## Why this exists

**Corrected 2026-07-25.** A first audit of this scored *response distance* and
reported several presets as "byte-identical". That was wrong twice over: it
compared only the two Q0 poses (so the Q corners were invisible), and it labelled
a zero distance as byte identity. It produced a false headline in both
directions. The scoring approach is abandoned. What follows uses byte-exact
comparison of each authored 60-byte CORNER against every corner of 137 known
E-mu-derived reference bodies (69 heritage Morph Designer XML compiles, 33
P2K/ROM corpus bodies, 35 ROM-fitted archetypes) - 529 distinct reference
corners. No thresholds, no scoring, no judgement calls.

### Result

| verbatim E-mu corners | presets |
|---|---|
| 4 / 4 | 7 |
| 3 / 4 | 2 |
| 2 / 4 | 1 |
| 1 / 4 | 1 |
| 0 / 4 | 34 |

**All five ear-approved signature presets contain verbatim E-mu corner data:**

| ship preset | verbatim | detail |
|---|---|---|
| Bruh | **4/4** | all four corners are `P2k_028_bass_o_matic`, with M100_Q0 and M0_Q100 **swapped** |
| Fable | 3/4 | `P2k_003_millennium` x3, plus `P2k_001_megasweepz` M100_Q100 |
| Low Pass Pressure | 3/4 | `Low Pass Pleasure` (heritage XML) |
| Speaker Knockerz | 2/4 | `P2k_000_ace_of_bass` Q0 pair; Q100 corners not in the index |
| Bass Time | 1/4 | `P2k_028_bass_o_matic` M0_Q100 |

Bruh is the instructive case: a corner permutation copies 100% of the data while
moving the response far enough that a distance metric called it unrelated at
8.8 dB. Similarity scoring cannot see this. Byte comparison can.

The seven 4/4 presets are the heritage workhorses (Super Lo Pass, Steep 8 Pole,
Complex BP 1, Twin Peaks, Rezzy LP 1, Voxxy LP 1) plus Bruh.

This breaks the notebook's locked "no ROM-derived bodies ship" rule.

### Limits of this method - read before relying on it

Corner indexing detects **verbatim** corners only. A corner edited by even one
word will not match, so **0/4 does not prove originality** - it proves no
corner was copied unaltered. Detecting derived-then-modified corners is a
different and harder problem, and it is not solved here.

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
1. **zero verbatim corners** against the reference index - the only criterion
   here that is a fact rather than a judgement,
2. certify PASS at 25×25, maxR < 0.9999,
3. all four corners authored - Q must not be a dead axis,
4. passes the ear on real material, level-matched.

There is deliberately no distance threshold. A distance gate rewards perturbing
a copied body until it scores far enough away, which is the micro-shift dodge
with a number attached. Provenance is a fact about how a body was MADE, and the
only honest record of that is the authoring recipe plus the corner check above.

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

No preset in the ship set is currently both ear-approved and free of verbatim
E-mu corners. The 34 presets with 0/4 verbatim corners have not passed the ear;
the 5 that passed the ear all carry E-mu data. Closing that gap is the work.
