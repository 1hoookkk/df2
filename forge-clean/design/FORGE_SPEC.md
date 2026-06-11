# Forge Spec — v2

**Main · Capture · Generate · Cut · Bake.**

Forge is an **acoustic compiler**, not an EQ editor. In **Main** you place poles by ear; **Capture**
and **Generate** fill Main with poles (from real audio / from math); **Cut** chooses the zeros; the
compiler welds and bakes a legal **4-corner × 6-row × 240-byte** body. You never hand-draw poles and
zeros at once — that's mud.

> **Non-hallucination rule:** every mode carries a `→ source` tag. No source in the repo / measured
> data / firmware decode → it does not go in. Provenance, not vibes.

---

## Aesthetic

**High-end 2008 pro-software, dark.** Machined dark panels, crisp tabular readouts, real (subtle)
bevels and inset screens — the tasteful end of that era's audio/creative suites, not flat-2020 and
not cartoon-skeuomorphic. The **phosphor response curve is the hero** (the old-forge instrument Tyson
approved: `OneDrive/.../Screenshot 2026-05-30/31 *`). Precision instrument, restrained.

---

## What a body actually is

A body = **six kin lanes × four corner-snapshots**, baked to **240 bytes** (log-domain minifloat coefficients).

- **Corner** (`M0/Q0`, `M1/Q0`, `M0/Q1`, `M1/Q1`) = a **full sound shape** — a complete 6-row pole/zero cascade.
- **Lane / row** = *how* that shape is built (one pole + its Cut). Six, fixed.
- **M / Q** = **travel between full shapes**, not knobs on one filter. M = the move (constellation log-shifts); Q = freq-locked stress.
- **The middle is emergent, never authored.** The player blends **per row, per word, in packed minifloat (log) space**:
  `out[i] = lerp( lerp(A[i],B[i], M), lerp(C[i],D[i], M), Q )`, then decodes to a biquad
  (`pyruntime/packed_interp.py` `packed_bilinear`). It is **not** averaging two sounds and **not** lerping in Hz —
  it's a log-domain blend of coefficients. And the lerp **wraps, not clamps** (i16 truncation in `lerp_u16`) — a big
  enough jump *folds* to a wild value. That log-travel + the wrap **are** the accident / beauty / damage of the middle.
- **The hidden law — correspondence.** Row `i` only ever blends with row `i` (slot 3 of HOME meets slot 3 of AWAY and
  nobody else). The four corners **cannot be unrelated**: each lane needs a **coherent 4-corner trajectory (kin)** or
  its solo journey tears the middle apart. Kin lanes = the morph glides instead of mushes — and the emergent glide is the moat.
- **What you author:** **six per-lane trajectories** — where each pole sits, how it travels across the corners, and its
  Cut. You never author the middle; the player log-lerps it for you.
- **Two axes only.** Morpheus's *Morph (X)* = **M**; *Transform (Z)* = **Q** (named per Material below). **No third axis** —
  the 8-corner cube (two M×Q planes, z-crossfaded; the *same* per-slot lerp) stays a study object, not a ship surface.

---

## How you work — hand, ear, real-time

You work entirely by **hand and ear**. Grab a pole, drag it until the vowel sounds right — "Ah" into
"Oo" — you never read Hz. Pick a **Cut** from a dropdown, sweep the mod-wheel (M / Q), listen. Too
harsh? Drop F3 a hair. 100% acoustic result, zero arithmetic in your head.

**The compile is real-time, not offline.** Every frame, while your hand moves, the runtime:
1. reads the placed **pole** positions (+ the Material's gain emphasis),
2. applies the chosen **Cut** to each actor,
3. converts to biquad kernel coeffs and **`encode()`s to minifloat words** — *that minifloat step **is**
   the log / `1-R` space; there is no separate "convert to log" pass*,
4. lerps the four corners (`lerp_u16`) and **stability-gates** (pole radius < 1 — not mystical "fold
   bifurcations", just the radius check),
5. serializes the **240-byte** body and pushes it to the audio thread.

This already runs live in `forge-clean/src/bench/mod.rs` (`compile()` + `sync_audio()` every frame).
**Do not build a 1990s offline batch compiler** — that was a CPU constraint, not a feature. Same math,
at the speed of thought.

---

## MAIN — the instrument

### Place
The 6 pole-actors on a **log-Hz × dB** canvas. Place and move by ear. Capped + placed → can't blow up.
`→ forge-clean/src/bench/mod.rs` (drag-pole + live audio already works), `→ generators.rs` (radius caps).

### Soft-snap (off by default)
| mode | snaps to | → source |
|---|---|---|
| **OFF** | free drag | — |
| **OCTAVE** | `20·2^k` grid | air rails measured octave-spaced in `dev/tmp/p2k_full_vocabulary/frequency_rails.csv` (8250→16500 = ×2) |
| **VOICE** | formant anchors | `tables/vowel_formants.json`, `tables/klatt_1980_formants.json`, `tables/klatt_1980_bandwidths.json` |
| **RAILS** | P2K landing zones | `dev/tmp/p2k_full_vocabulary/frequency_rails.csv` (measured through the shipped engine) |
| **Q / RADIUS** | radius rail | `tables/q_radius_table.json` (the study's single strongest table signal) |

### Move families (how the whole shape travels)
Measured, not invented `→ dev/tmp/p2k_full_vocabulary/skin_summaries.csv`:
**High-Bank Collapse** (25) · **Remote-Cut Violence** (13) · **Talking-Vowel Glide** (7) ·
**Shelf/Cliff Frame** (3) · **Comb/Phaser Field** (2).

### M / Q
- **M** = log-shift the whole constellation HOME→AWAY (coherent sweep, not a vowel swap). `→ generators.rs`.
- **Q** = freq-locked radius tighten = a stress verb (tighten / harder / hollower / torn), **not** "Morph 2".
  `→ p2k_full_vocabulary/report.md` ("Push is a stress move… not just Morph 2").

---

## CAPTURE — poles from real material
Drop a sound in, get its anatomy out. Every source is proven code:
| source | gives | → source |
|---|---|---|
| **LPC** | formant poles from a `.wav` | `tools/lpc_extract.py` → `lpc_to_body.py` (proven on a real /a/ this session) |
| **ARMA** | poles **and** zeros from audio | `tools/fit_two_audio_arma.py`, `trench-core/src/arma.rs`, FFI `trench_fit_corner_arma` |
| **CURVE** | fit a drawn / loaded magnitude | FFI `trench_fit_corner_from_magnitude` |

(Vocal skins like *Ooh→Eee*, *Talking Hedz*, *Deep Bouche* are real P2K presets:
`ref/p2k_variants/P2k_010/013/022…`.)

---

## GENERATE — poles from math, by Material
Pick a constellation; math drops all six poles, stable by construction. Four Material families.
**`✓` = live in `generators.rs` today · `○` = aspirational (not coded yet) · refs are clean-room study (ship originals).**

### FLESH & BREATH — the voice
- **Members:** Vowels A·E·I·O·U ✓ · dipthong sweeps ✓ · nasal ✓.
- **Morph X:** throat, Ah→Oo. **Transform Z:** nasal anti-resonance depth (the "tear").
- **→ source:** `generators.rs` `formant()` / `vowel_corner()` / `talking_hedz()`; `tables/vowel_formants.json`, `tables/klatt_1980_formants.json`.
- **Refs (study, clean-room):** TalkingHedz ✓ · VowelSpace · AUParaVow. **Asset:** vocal-tract cutaways.

### WOOD & METAL — static resonant bodies (objects = instruments, one engine)
- **Members:** Tube ✓ · Bell ✓ · Plate ✓ · Cavity ✓ · Bottle ✓ · Bar ✓ · Shell ✓ · String ○ · Reed ○ · Brass ○ · Membrane ○ · Pipe ○.
- **Morph X:** play position — shifts gain emphasis across **fixed** modes, never the frequencies.
- **→ source:** `generators.rs` `physical_corner()` / `Object` enum; `tables/tube_resonances.json`, `tables/metallic_modes.json`, `tables/physical_models.py`.
- **Refs (study):** AcGtrRs · PianoSndBrd · Cymbal Cube. **Asset:** jet-engine-cutaway body sections.

### MIRRORS & GLASS — combs, flangers, phase
- **Members:** Comb ✓ · Flange ○ · Phaser ○ · Odd/Even shifter ○. *(phase-shear math exists — `generators.rs` `allpass()`/`phase_shear()` — just not exposed as a family yet.)*
- **Morph X:** slide the zeros across the poles (phase-cancel tear). **Transform Z:** notch depth.
- **Refs (study):** Deep Combs · Odd-Ev Hrm · Flange7.4 · KlangKling. **Asset:** cold mirror / glass / alien geometry.

### SILICON & WIRE — analog destruction
- **Members:** Overdrive ✓ · Acid 303 ✓ · Lucifer's Q ✓ · EarBender ✓ · Destruction ✓ · Scream ○ · Crush ○ · LP24/LP36 ○.
- **Morph X:** cutoff sweep. **Transform Z:** push pole radius to the morph-stable brink + drive into **runtime SLAM** (not unstable poles).
- **→ source:** `generators.rs` `overdrive()` / `lucifers_q()` / `earbender()` / `kinematic()`.
- **Refs (real P2K variants):** Bassbox 303 (`P2k_006`) · TB-or-not-TB (`P2k_009`) · AcidRavage (`P2k_027`) · FuzziFace (`P2k_007`). **Asset:** heat-stressed circuit & metal, glowing red.

**Signature heroes** (cross-Material exemplars, not their own family): **TalkingHedz** (Flesh) · **Lucifer's Q** (Silicon) · **EarBender** (Flesh × Silicon).

---

## CUT — the zeros (chosen, never freehand)
A zero **is** a cut. You pick its behavior per actor (or globally); the compiler welds it onto the
placed pole, on rails, legal by construction:
| cut | placement | → source |
|---|---|---|
| **HUG** (sharpen) | 7 semis below pole | `tools/lpc_to_body.py` zero_role `local`; `generators.rs` `band()` S7 |
| **SUB KILL** | 2 oct below | `lpc_to_body.py` zero_role `remote_low` |
| **AIR CAP** | 2 oct above | `lpc_to_body.py` zero_role `remote_high` |
| **TEAR** | 2.2–5.5k cut band | measured tear rails in `frequency_rails.csv`; `generators.rs` `notch()` |
| **AIR KILL** | 8–18k, top lane | measured air-kill rails (S6) in `frequency_rails.csv` |
| **NEUTRAL** | parked / off | `lpc_to_body.py` zero_role `none` |
| **CUSTOM** | explicit Hz | `lpc_to_body.py` zero_role `custom` |

The firmware proves the Cut *is* the talk: MorphLP "talks" by **dissolving** its unit-circle notches
across morph. `→ ref/ghidra_extracts/morphlp_zero_table.json` + decoded `FUN_1802c59b0` / dispatcher.

---

## BAKE / PROVE
- Pack to **240 bytes** via minifloat `encode()` `→ pyruntime/packed_interp.py`.
- Audit **center + diagonal + stability** through the shipped runtime `→ FFI trench_packed_interpolate_stability`.
- Keep / kill by ear.

---

## Runtime truths — do NOT re-solve
- **Interpolation is already log-correct.** Shipped engine = **linear lerp on minifloat words**
  (`packed_interp.lerp_u16` / `PackedCorners::interpolate_biquad`). Words are minifloats (log-domain),
  so linear lerp **is** log interpolation. Do not rewrite to "octave interpolation."
- **240 bytes come from authoring**, not cubes `→ packed_interp.encode`. The E-mu cubes are **study
  only** (reading reference Lucifer's Q / Ear Bender shapes), off the critical path.
- **Legal by construction:** placed/capped poles stay stable; cuts chosen via rails stay legal.

## Dropped as hallucinated (for honesty)
- Gemini cartridge names *Acid Tear / Comb Dissolve / Nyquist Cap* — invented; replaced with measured families.
- Prototype `ANALOG` (ladder/diode/SEM/MS-20) + `INSTRUMENT` (reed/string/bowed/mallet) — placeholders,
  not in `generators.rs` or any reference set. Out until sourced.
- "Interpolate in octaves" / the "594-trajectory" claim — unverified; the engine already lerps minifloats.

---

## HANDOFF — for the build (fresh session, no prior context)

**Keep (works today):** `forge-clean` eframe app + engine adapter driving `trench_core::FilterEngine`
end-to-end (AGC → desk-slam → QSound), rodio live audio, `generators.rs`, `lpc_extract.py` /
`lpc_to_body.py`, `pyruntime/packed_interp.py`, the shipped FFI. The plumbing is real; only the UI is rebuilt.

**Build order (smallest proving slice first):**
1. **MAIN** canvas — draggable pole-actors on log-Hz + live audio (drag-pole exists; restyle to 2008-dark, add soft-snap Off/Voice/Rails).
2. **GENERATE** — wire `generators.rs` archetypes as a pole source (the 4 Material families).
3. **CAPTURE** — wire LPC as a pole source (drop wav → ghost poles).
4. **CUT** — the zero-behavior picker (`lpc_to_body` zero_roles + measured tear/air rails).
5. **BAKE / PROVE** — pack 240 bytes, audit center + diagonal + stability, keep/kill.

**Build methodology — single-owner UI, subagents only at the edges:**
- The Main canvas + render loop + app state is **one coherent author's job** (sequential). Do **not**
  fan parallel agents onto the egui app — they collide on the same files and produce an incoherent UI
  (the slop failure mode).
- Use subagents only for **bounded, independent prep** (extract the Cut rail table from
  `frequency_rails.csv`; pull Material members from `generators.rs`; build the theme palette) and for a
  **per-slice adversarial verify** against the non-hallucination rule + this spec.

**Non-negotiables:**
- Two axes (M × Q). No third axis.
- Don't rewrite interpolation — already linear-lerp-on-minifloat = log, parity-tested.
- 240 bytes from authoring (`encode`), not the E-mu cubes (study only).
- Every shipped mode traces to a `→ source`. No invented filter types until coded.
- Poles placed/capped + cuts on rails = legal by construction; the user can't author mud.
