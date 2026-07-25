# Hypothesis Brief — what makes an E-mu body good, and how to make our own

**Written:** 2026-07-25 · **Commit:** see `git log` for this file
**Status:** hypothesis with one experiment awaiting Tyson's ear. Not a proven method.

Read this before authoring bodies, judging bodies, or writing any similarity
metric. It exists to stop the next session re-deriving what was measured here,
and to stop it repeating three specific mistakes made on the way.

---

## 1. The question

Tyson: *"E-mu presets are just perfect and I'm not sure how."* Our own authored
bodies keep failing his ear. 34 of the 45 ship presets contain zero verbatim
E-mu data; none of those 34 has passed his ear. All 5 that have passed contain
verbatim E-mu corner data. So the gap is not tooling — we can emit certified
bodies all day. We did not know what E-mu's data has that ours lacks.

## 2. Measured facts (trust these)

Populations: **E-mu** = 102 bodies (69 heritage Morph Designer XML compiles +
33 P2K/ROM corpus). **Ours** = the 34 ship presets with zero verbatim E-mu
corners. **CAVL** = 21 measured-cavity bodies (real acoustic objects).
All measured through the shipping runtime (`trench_packed_probe`), medians.

| | E-mu | ours | CAVL raw |
|---|---|---|---|
| highest crown dB | 29.8 | **34.1** | 60.7 |
| lowest crown dB | **0.5** | 11.4 | 28.4 |
| crown range across corners | 29.0 | 25.5 | 34.2 |
| **crown travel (octaves)** | **5.3** | 2.6 | 1.9 |
| **Q bloom dB** | **24.1** | **0.0** | 19.7 |
| pole spacing, adjacent (oct) | 0.41 | 0.95 | — |
| pole morph travel (oct) | 1.4 | 0.84 | — |
| broadband (real-pair) rows of 24 | 4 | 1 | — |
| all six stages active, every corner | 100% | 100% | 100% |
| bodies with a corner under +3 dB | **75.5%** | 29.4% | **0%** |

### What these say

1. **Crown HEIGHT is not the signature.** Ours peak *higher* (34.1 vs 29.8).
   Do not chase taller peaks.
2. **Crown range is not the signature either.** CAVL has the widest range
   (34.2) and is the least musical set in the repository.
3. **The floor is a signature.** Three quarters of E-mu bodies have a corner
   under +3 dB — a rest pose. Under a third of ours do; no CAVL body does.
4. **Travel is the other signature.** Their crown moves **5.3 octaves** across
   the four corners. Ours 2.6, CAVL 1.9.
5. **Our Q axis is absent, not weak.** Median bloom exactly 0.0 dB across all
   34. Measured real-object data supplies 19.7 dB for free — this is the
   strongest argument for authoring from measurement.
6. **Structure follows the preset's job.** `Bass Shaper` uses 8 broadband rows
   of 24 (it *shapes*, so it is built from shelves). `bassbox303` uses 0 (a
   cavity, so pure resonance). `bass tracer`, `millennium`, `ace of bass` are
   23/24 resonant. The name is the spec; structure was chosen to serve it.
   Our 34 are all 23 resonant / 1 broadband — i.e. **one generic transform run
   34 times.** That is why tweaking frequencies never rescued them.

## 3. The hypothesis

> An E-mu body is **one voice that starts at nothing, blooms, and travels.**
> Six poles clustered tightly enough (~0.4 oct) to act as a single steep
> resonance; a corner near 0 dB to depart from; ~24 dB of Q bloom; and a crown
> that relocates ~5 octaves across the macro square. Character comes from the
> pole/zero geometry of a real physical system; contrast and level are authored
> on top. Our bodies fail because they are a tall static peak with a dead Q
> axis and no rest position — a tone control, not a voice.

### Sub-hypothesis, inferred but NOT tested — flagged because it matters

Crown travel is **5.3 octaves** while individual pole frequencies travel only
**1.4 octaves**. Those cannot both be one resonance sliding. The likely
mechanism is that **different stages dominate at different corners** —
dominance cross-fades between poles parked at different frequencies, rather
than one pole sweeping. If true, authoring "travel" means designing which
stage wins at each corner (contrary/opposing motion), not sliding a filter.
This would explain the "Contrary" family names. **Untested. Test it before
building on it.**

## 4. The experiment run (awaiting verdict)

Target: does level framing alone turn a measured body into a keeper?

- Source `CAVL_beer_bottle_to_bathtub.body240` (real cavity measurements).
- Rewrote **only the SCALE words** (word index 4 of each stage) via the
  shipping encoder, per corner, to land inside E-mu's −3..+27 dB band with a
  rest pose. Every pole and zero byte-identical to the measurement.
- Result: corners +2.0 / +8.0 / +25.0 / +27.0 dB, Q bloom **23.0 dB**
  (E-mu median 24.1), certify PASS maxR 0.99890, **0 non-SCALE bytes changed**,
  **0/4 verbatim E-mu corners**.
- Artefacts: `dev/tmp/experiment/` (bodies + `plots.html`),
  renders in `dev/tmp/audition/A_ORIGINAL_*`, `B_FRAMED_*`.

### Pre-registered prediction (recorded before the verdict)

Framing fixes the **floor**, not the **travel** — SCALE is gain and cannot move
a pole's frequency, so that body's crown still travels only 1.9 octaves.
Expected: better at rest, the bloom lands, **but the sweep still feels short**.
If that is what Tyson reports, the hypothesis is half-confirmed and the next
move is geometry, not level. If the sweep already feels right, the travel
number matters less than claimed and this brief is wrong about it.

## 4b. THE SOURCE OF TRUTH — `C:\Users\hooki\trench-filters` (read-only)

**Tyson: "trench-filters is key."** He is right, and most of §2–§3 above was
re-derived by measurement when it was already written down here. Read this
directory before authoring anything.

`data/tables/family_intents.json` states the method verbatim:

> *"Body-level INTENT tables. Every generated body picks a HOME intent and a
> different AWAY intent from its family's pool; the morph becomes a NAMED
> transformation (e.g. 'ah -> ee'), not a random shape change."*

**7 families, ~7 named intents each, every frequency from real physics** — not
invented:

| family | template | slots | intents |
|---|---|---|---|
| vocal | bright_vowel | F1 F2 F3 | 10 vowels (ee, ih, eh, ae, ah, aw, uh, oo, uu, er) |
| cavity | bottle_cavity | fundamental, second_mode, scoop_notch, upper_mode | wine_bottle, beer_bottle, plastic_jug, mason_jar, tin_can, stone_pipe, bathtub |
| resonant | small_metal_shell | low/mid/hi/top mode, scoop_notch | iron_ring, glass_ring, brass_bell, single_scream, panel_rattle, tight_cluster, copper_sheet |
| knock | knock | knock, body, grit, scoop_notch, tear | soft_knock, snapping_punch, deep_chest, bright_tear, gritty_mids, popping_top, boxed_knock |
| comb | broken_comb | 2 peaks + 4 notches | low_wide_comb, mid_tight_comb, high_sparse_comb, chambered_phaser, phasing_sweep, dense_low_comb, flanger_tail |
| cut | razor_shell | body_low, body_mid, scoop_notch, tear_lo, tear_hi | single_tear, multi_fracture, low_carve, high_razor, twin_tear, broad_cut, mid_fracture |
| violence | violence | body, scream, scoop, tear, top_notch | chainsaw, drill_squeal, glass_shatter, iron_plate, wolf_howl, bee_swarm, acid_303 |

Each intent carries a `describe` string and, for cavity, the actual physics
(`wine_bottle`: "Helmholtz 119 Hz (V=0.75L, neck d=1.85cm L=6.0cm) + body modes
357/1072 Hz (closed-pipe, L=24.0cm)").

Supporting tables in the same directory: `vowel_formants.json`,
`klatt_1980_formants.json`, `klatt_1980_bandwidths.json`, `metallic_modes.json`,
`tube_resonances.json`, `q_radius_table.json`, `p2k_vocal_law.json`,
`morph_designer_type_primitives.json`, `exact_skeletons.json`.
Measured source data in `data/{vocal,modal,circuit,hrtf,phononic,aeroacoustic}`
(modal alone: 268 files of material resonances). Pre-built rails in
`out/{modal,hrtf,dvtd,circuit,phononic}_rails`.

### The diagnosis this produces

The 21 `CAVL_*` bodies in our pool **are** cavity-family HOME→AWAY pairs —
`beer_bottle_to_bathtub` is two intents from that table. So:

> **The intent→geometry generator already works. The framing law measured in
> §2 was never applied to its output.** Correct physical character, correct Q
> bloom (19.7 dB), but a 28 dB floor and 1.9 octaves of crown travel.

The method is therefore: **intent table (HOME→AWAY) supplies geometry →
framing supplies floor, bloom and contrast.** Do not rebuild the first half.

**Boundaries (from `workstation-worktree-layout`):** trench-filters is
read-only evidence. Use its DATA and intent tables. Do **not** import its
compiler code, its `METHOD.md` as executable law, its lane alphabet, or its
radius caps. `out/x3_bank_rip/` is E-mu ROM evidence — study only, never ship.

## 5. Three metrics that FAILED today — do not rebuild them

Every one of these looked reasonable and produced a confidently wrong answer.

1. **Median of |H| over a log grid, used as a level estimate**
   (`computeBodyMakeupDb`). For a lowpass the median sits in the stopband, so
   it read bass-heavy bodies as quiet and boosted them **+12 dB into clipping**.
   It made level parity *worse*: spread 14.5 → 27.5 dB, 20/45 pinned at the
   clamp. Deleted. **Level must be MEASURED through the chain**, and note 34%
   of corner renders pin the limiter, where output stops tracking coefficients
   entirely (prediction spread 26 dB on the pinned set vs 5.5 dB elsewhere).
2. **Response-distance scoring for provenance.** Compared only the two Q0
   poses (so Q was invisible), removed a constant offset, and labelled a zero
   distance as byte identity. It called `Bruh` "unrelated at 8.8 dB" when
   `Bruh` is a complete ROM body with two corners **permuted**. Replaced by
   byte-exact corner matching. **A permutation copies 100% of the data and
   moves the response a long way — similarity scoring cannot see this.**
3. **Harmonic-series fit of pole frequencies.** Degenerate: with the
   fundamental free to go low enough, any set of frequencies fits. Scored
   `millennium` at 0 cents error with f0 = 10 Hz. Meaningless.

**The pattern:** every failure was an invented composite score. Every finding
that survived scrutiny was a byte count, a peak level, or a hash. Prefer facts
with units. Be suspicious of anything you had to name.

## 6. Other traps, already paid for

- **Never gate on a distance threshold.** "Must be ≥ N dB from the source"
  rewards perturbing a copy until it passes — the micro-shift IP dodge, which
  this repo has now deleted twice. Provenance is how a body was *made*.
- **Plots render the design, never the audio.** Coefficient-drawn curves cannot
  see level, crest, or the desk. The gain budget survived because every plot
  looked clean. `FILTER_NOTEBOOK` §"plot is blind to post-cascade".
- **No generate-then-cull batches.** ~40 rule-synthesised bodies died to the
  ear once already. One body, proven, then scale.
- **Corner-verbatim matching detects VERBATIM only.** 0/4 does **not** prove
  originality — only that nothing was copied unaltered. Derived-then-edited
  corners are undetected; no method here solves that.
- **A near-flat corner is not a bug.** `ace_of_bass` is essentially
  unprocessed at Q0 by design. Reading it as broken and "fixing" it destroys
  the preset.

## 7. Constraints the work sits inside

- **No ROM-derived bodies ship** (locked). Currently violated: 11 ship presets
  carry verbatim E-mu corners, including all five ear picks
  (`Bruh` 4/4, `Fable` 3/4, `Low Pass Pressure` 3/4, `Speaker Knockerz` 2/4,
  `Bass Time` 1/4). See `CLEANROOM_BRIEF.md`.
- **A frequency response is a fact; facts are not copyrightable.** Measuring
  what a body does and authoring an original toward that character is
  legitimate. Shipping their coefficients is not. Do not fit to their curve.
- **US 10,514,883** (Rossum, active to 2038) reads on the engine except
  arguably the "frequency and resonance encoded independently" limitation —
  our words are affine functions of the biquad coefficients, with no stored
  frequency. See `IP_ENCODING_RECORD.md`. Not settled; counsel required.

## 8. Next moves, in order

1. **Get the verdict on `B_FRAMED`.** Everything below depends on it.
2. **Apply framing to the existing 21 CAVL bodies** — the geometry is already
   right (§4b); they need only the floor. Cheapest possible win if step 1 lands.
3. **Test the dominance sub-hypothesis** (§3): is E-mu's 5.3-octave crown
   travel produced by pole movement or by stage dominance cross-fading?
   Measure which stage carries the peak at each corner across the 102 bodies.
   This decides how "travel" gets authored.
4. **Run the intent generator on the other 6 families** (knock, resonant, cut,
   comb, violence, vocal) with framing applied from the start. `knock` is the
   Speaker Knockerz family and the obvious first target for Tyson's language.
5. Author replacements for the five ear picks, so the roster stops carrying
   verbatim E-mu corners.
6. Give the 15 remaining dead-Q presets a real Q axis or cut them.

**One body at a time to the ear. Never a batch.** ~40 rule-synthesised bodies
already died that way once.

## 9. If you read only one thing

The method was never missing. `trench-filters/data/tables/family_intents.json`
has held it the whole time: name the job, pick HOME and AWAY from real physics,
let the morph be a named transformation. What was missing is the framing —
a rest pose near 0 dB, ~24 dB of Q bloom, and crown travel — and that is what
§2 measured. This session's contribution is the framing numbers and the
knowledge that the generator's output was never framed. Everything else here
already existed and was re-derived at cost. Check trench-filters and the
notebook before deriving anything.
