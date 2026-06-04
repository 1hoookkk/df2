# df2 Forge v1 — Filter-Type Authoring & v1 Preset Set

Date: 2026-06-04
Status: design (approved direction; next step = implementation plan)

## One sentence

A df2 "preset" is an original **12th-order Z-plane filter type** — a 6-section
pole/zero body morphing between two frames — and v1 ships 4–7 of them plus the
minimal Forge to author and audition them.

## What we proved this session (the ground under this spec)

- **The plot is faithful.** forge-web's `packed.js` plotter reproduces the
  shipped-engine response of a real reference body to **0.0000 dB** across the
  band. The plot does not lie; a body that looks wrong *is* wrong. OBSERVED.
- **The 50 reference bodies are filter TYPES, not presets.** E-mu's Mo'Phatt
  chart lists 50 Z-plane filter types (EOS had 21; P2K expanded to 50). Every
  `P2k_NNN` we decoded IS one of those types. OBSERVED (Mo'Phatt manual p.133–134).
- **Order = sections.** Order 2→12; "higher order = more sections." 12th order
  = 12 poles = **6 biquad sections = df2's six stages.** The iconic types are all
  12th-order; the simple LP/HP types are low-order and legitimately fill few
  sections (not broken). OBSERVED.
- **Two axes, per E-mu's own UI.** `Freq = Morph` (interpolates Frame A→B),
  `Q/Resonance = Secondary` (character + drive, meaning set per type). The
  Peak/Shelf Morph tutorial spells out the programmable form. OBSERVED.
- **Every section has a zero.** Reference bodies: 6 poles, 6 zeros, always. Our
  current model makes the zero optional (`cut off` → bare resonator) — that is
  the "our stages look wrong" bug. To fix.

## Core model

A body = **4 corners × 6 sections × 5 packed words = 240 bytes.**

- Corner order (fixed): `C0=M0/S0, C1=M100/S0, C2=M0/S100, C3=M100/S100`.
- **Morph** interpolates C0↔C1 and C2↔C3. **Secondary/Q** interpolates those.
- So a body = **Frame A + Frame B + a Q-rule**:
  - Frame A = C0 (low-Q) ; Frame B = C1 (low-Q)
  - C2 = Frame A · high-Q ; C3 = Frame B · high-Q (derived by the Q-rule)
- A **frame** = a cascade of 6 sections (order irrelevant within a corner; index
  i is the morph pairing across corners — index is sacred, cascade order is free).

## The section primitive (the "stage", fixed)

Replace "pole + optional cut" with E-mu's parametric section. Every section is:

```
Section = { freqHz, shelf, gainDb, q }
  freqHz : position (cutoff / center / boundary — meaning set by shelf)
  shelf  : −64 = lowpass … 0 = peak … +63 = highpass   (continuous filter character)
  gainDb : boost (+) or cut (−)
  q      : sharpness / width  (low = broad EQ, high = resonant formant)
```

- Compiles to a **pole/zero biquad — always both**. Boost = pole dominates zero;
  cut = zero dominates pole; shelf offset = pole/zero spacing. **Zeros are never
  optional** — this is the structural fix for the stages.
- `shelf` (peak↔shelf) is the human form of pole–zero spacing we reverse-
  engineered: peak (zero near pole) = sharp formant; shelf (zero far) = broad
  body. One knob.
- Pack path unchanged: section → biquad → WASM trench-core encode → 240 bytes.
  The packed runtime is shipping truth; the plot is drawn from it.

## Frames and mining

The unit of value is the **frame** (6 sections frozen into one posture). A preset
is a pairing of two frames + a Q-rule. Frames are mined, never random:

1. **Capture (LPC)** — record a real resonant thing → 6-section frame off real
   resonances. (The fitter already exists.) Highest leverage.
2. **Physical/measured** — vowel formants, tube/bottle/modal physics from
   `tables/family_intents.json`. Deterministic, no recording.
3. **Study the references (clean-room)** — decode the 50 types to learn frame
   grammar (section roles, peak vs shelf, Q ranges); author originals in that
   spirit. Learn the shape, copy no coefficients or names.

Constraints that keep frames morphable: **fixed 6-section budget**; each frame
carries a **loQ→hiQ scale** so Secondary works on any A/B pairing.

## Forge v1 UI

- **Hero**: the packed-runtime magnitude plot (Morph/Q live), four corner ghosts,
  selected-section pole+zero handles.
- **Frame quarry strip**: a horizontal bank of **mini-plots**, one per frame,
  **sorted low→high by spectral centroid**. Click a tile = Frame A, click another
  = Frame B → instant body in the hero. The strip is the picker (retires the
  template dropdown).
- **Section editor** (selected section): `Freq · Shelf(LP↔peak↔HP) · Gain± · Q`.
- **Audition**: through the shipped drive chain, **AGC always on** (one sound,
  not a plain/driven split). Plot judges first, ear confirms.
- **Save** = `.body240` (shipping truth) + an editable `.df2forge.json` source.
- Behind **More**: raw words / decoded biquad / 5×5 audit grid / hash. Diagnostics
  only.

## v1 preset set (original 12th-order filter types)

Drawn from the user's own taste cluster (all 12th-order, aggressive families) and
each defined by a **Morph move** + a **Q behavior** (from the reference vocabulary).
Clean-room originals — no copied coefficients or names.

| # | working name | type | Morph (Frame A → B) | Q / Secondary |
|---|---|---|---|---|
| 1 | (REZ) violent scream | REZ | hold position, rim pole | Q = the scream-bite; danger band by design |
| 2 | (VOW) vowel glide | VOW | open vowel → close-front vowel | Q = mouth size / adds peaks |
| 3 | (LPF) hard-Q sweep | LPF | bank slides low → high | Q = laser-sharpen the sweep |
| 4 | (EQ+) bassline processor | EQ+ | bass-boost → bright belch (808) | Q = bite/drive, keep sub power |
| 5 | (PHA) notch gargle | PHA | shift a notch field | Q = notch depth |
| 6 | (BPF) contrary rip | BPF | two bands cross in the midrange | Q deepens the cross into a tear |

Ship **6** (drop or add by ear). Each is a frame pairing + Q-rule, authored in the
Forge, packed, auditioned, kept/killed by ear.

Property every preset must hold (E-mu's law, verbatim): **high resonance without
losing bass power** — the body section booms uncut (shelf, zero banished) while Q
cranks the upper sections.

## What exists vs v1 work

- Built (OBSERVED): WASM trench-core pack; faithful `packed.js` plot; the 4×6
  editor; LPC fitter; audition page.
- v1 work: (a) **section primitive** = Freq/Shelf/Gain/Q → always pole+zero (the
  fix); (b) **frame quarry** = mine + mini-plot strip sorted by centroid; (c) the
  **6 preset types** authored through (a)+(b).

## Non-goals (the failure modes we already hit)

- No MD-style freq+gain descriptor model (proven it can't reach P2K).
- No zeroless sections (violates the law; causes "stages look wrong").
- No per-section authoring of all 4 corners independently — author 2 frames + Q.
- No template taxonomy / archetype mythology; no AI selecting or blessing a body.
- No new abstraction layer when the work is mine-frames + author-pairings.

## Verification

- Every export = exactly 240 bytes, corner order C0–C3, finite, stable across a
  5×5 Morph/Q packed grid (worst pole radius < 1).
- Plot==engine holds (re-assert the 0.0000 dB check in CI on a fixture body).
- Each of the 6 presets: packs, runs (not edge/bad), and the morph performs its
  named move on the plot; ear confirms through the AGC chain.
- A captured-vs-reference sanity check: LPC an "ooh"+"aah", align, pack, and put
  its plot beside a reference vowel type — trajectory shape should land.
