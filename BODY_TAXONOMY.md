# BODY_TAXONOMY.md — df2 / TRENCH

The canonical vocabulary for df2 bodies: the **corner-picker axes** and the **four
Materials** that cover the full sonic spectrum. Pick a Material (the physics), place it on
the X/Y picker (the trajectory), and the generator builds the whole 6-section corner. One
language for the GEN menu, the SHAPE atlas, and the asset set.

> Source: distilled from a NotebookLM pass on the E-mu Z-plane library (2026-05-31).
> **Four corrections are baked in** where that source drifts from our real engine — see
> "Guardrails". The code is the authority; this is the naming + intent layer.

---

## The corner picker (X / Y)

Every corner sits at a point on a 2D physical map (code: `brightness` / `openness` in
`forge/src/corner_library.rs` + `generators.rs`). This is a **relabel** of what's already
there — no math change, better metaphor:

- **X — MASS / SIZE.** Left = **massive & thick** (low frequencies, big resonant body).
  Right = **tiny & thin** (high frequencies, small body). *(= spectral centroid /
  `brightness`.)*
- **Y — ENERGY / AIRFLOW.** Bottom = **choked & muted** (closed, damped). Top = **ringing
  & screaming** (open, high-Q). *(= resonance prominence / `openness`.)*

UI task: relabel the SHAPE atlas axes to **MASS/SIZE × ENERGY/AIRFLOW**.

---

## The four Materials

Pick the structure by its physical material. Each Material = one generator engine + a body
set + a clean-room study reference + a visual language.

| Material | Physics | Behaviour | Engine (`generators.rs`) |
|---|---|---|---|
| **FLESH & BREATH** | soft flexible tube (throat/mouth) that changes shape | moving formant clusters (vowels, dipthongs); HF left flat for breath; nasal anti-resonance notches | `vowel_corner` ✅ |
| **WOOD & METAL** | rigid hollow chamber, fixed dimensions (guitar body, bell, soundboard, bar) | fixed modal frequencies; "play position" shifts the gain/bandwidth of static peaks, not the freqs | `physical_corner` ✅ |
| **MIRRORS & GLASS** | reflective room, waves colliding with themselves | evenly-spaced peaks + deep notches; sliding zeros across poles = comb/flange/phase shred; odd↔even harmonic | `comb` / `phase_shear` ✅ |
| **SILICON & WIRE** | analog circuit pushed to the brink of failure | stacked LP poles (24/36 dB brickwall), aggressive Q at cutoff, pole radius to the edge, internal overdrive | `overdrive` / `kinematic` ✅ |

### FLESH & BREATH — the voice
- **Members:** vowels A · E · I · O · U, dipthong sweeps, nasal.
- **Morph (X):** throat muscles, Ah → Oo. **Transform (Z):** nasal anti-resonance depth
  (the "tear").
- **Study refs (clean-room — ship originals):** TalkingHedz (/u/→/i/ "oui"), VowelSpace,
  AUParaVow.
- **Asset language:** vocal-tract cutaways.

### WOOD & METAL — static resonant bodies (objects AND instruments)
- **Members:** Tube · Bell · Plate · Cavity · Bottle · Bar · Shell · String · Reed · Brass
  · Membrane · Pipe. *(Objects and instruments are the same engine — static modal bodies.)*
- **Morph (X):** play position — bow bridge→fingerboard, pick position — shifts gain
  emphasis across **fixed** modes, never the frequencies.
- **Study refs:** AcGtrRs, PianoSndBrd, Cymbal Cube.
- **Asset language:** object / instrument body cutaways (the jet-engine-cutaway style).

### MIRRORS & GLASS — combs, flangers, phase
- **Members:** Comb · Flange · Phaser · Odd/Even harmonic shifter.
- **Morph (X):** slide the zeros across the poles (phase-cancellation tear).
  **Transform (Z):** notch depth.
- **Study refs:** Deep Combs, Odd-Ev Hrm, Flange7.4, KlangKling.
- **Asset language:** cold mirror/glass/alien geometry.

### SILICON & WIRE — analog destruction
- **Members:** Overdrive · Acid (303) · Scream · Crush · LP24 / LP36 brickwall.
- **Morph (X):** cutoff sweep. **Transform (Z):** push pole radius to the morph-stable
  brink + drive into internal distortion (SLAM at runtime — not unstable poles).
- **Study refs:** Bassbox 303, TB-or-not-TB, AcidRavage, Lucifer's Q, EarBender, FuzziFace.
- **Asset language:** melting / heat-stressed circuit & metal, glowing red.

**Signature heroes** (cross-Material exemplars, not their own family): TalkingHedz (Flesh),
Lucifer's Q (Silicon), EarBender (Flesh × Silicon).

---

## Guardrails — these correct the source material

1. **6 biquads, not 14.** The shipped engine is `NUM_STAGES = 6` (12 poles). E-mu's
   MorphDesigner showed LP + 6 EQ (7 sections / 14 poles); df2 is the 6-section descendant.
   Map each Material into 6 sections; **no 7th HF shelf** without a frozen-core change +
   re-null.
2. **Whole corners, never manual section-assignment.** The user picks a **Material + a
   corner position**; the generator clusters/stacks the sections internally. There is **no
   "assign the 6 slots" UI** — that is the per-stage authoring trap (the month-long loop).
   Four distinct whole corners is the contract; the middle emerges.
3. **The morph middle is a read-only consequence.** Author the corners; the middle (the
   product, the moat) emerges. No "set the middle" control.
4. **Clean-room.** The E-mu preset names + coefficients are **study references only** —
   study the behaviour, ship **original** bodies in the spirit. Never an E-mu name on a
   user-facing surface; never copied coefficients in a shipped body.
5. **Z = shape, SLAM = drive.** Silicon & Wire's "internal distortion" is the runtime
   SLAM/AGC, not unstable poles; radius caps at the morph-stable brink (~0.999).

---

## Maps onto code (mostly free)

- **FLESH & BREATH** → `vowel_corner` (exists; add the 5 cardinal vowels + dipthong).
- **WOOD & METAL** → `physical_corner` (exists; INSTRUMENT = new modal ratio sets — String
  harmonic series, Membrane Bessel modes, Reed/Brass — fed to the same engine).
- **MIRRORS & GLASS** → `comb` / `phase_shear` (exist).
- **SILICON & WIRE** → `overdrive` / `kinematic` (exist).

Refactor: collapse the 16-member `Architecture` enum into **`Material` (4) × member**, group
the GEN menu by Material.

---

## Assets

4 Materials = 4 visual languages, one isolated cutaway/chip per member (≈ 20 total). The
Material reads at a glance. Slots into the SHAPE atlas as section headers + the GEN menu.

## Next

1. Lock this taxonomy.
2. Refactor `Architecture` → Material families; relabel picker axes (MASS/SIZE ×
   ENERGY/AIRFLOW).
3. Generate the asset set, one Material at a time.
