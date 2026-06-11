# RECIPES — the authoring cookbook

Every frequency in this book is **table-pulled or measured — never invented**.
Each section says where its numbers come from:

- **MEASURED** — published acoustic measurements (Peterson & Barney 1952, Klatt 1980)
  or our own measurements through the shipped engine.
- **PHYSICS** — computed from standard acoustics (tube series, Helmholtz, beam/plate modes).
- **CLEAN-ROOM LAW** — structure (bounds, motion laws) extracted from the P2K references;
  no coefficients, no bytes.
- **AUTHORED** — our own design vocabulary, built by ear in the spirit of the
  clean-room study. Original values, not measurements — labeled so.

Full data lives in `tables/*.json`; this page is the working summary.

---

## 1. The math (textbook)

A body = 4 corners × 6 second-order sections. Every section is a **pole pair +
zero pair — always both**. The cascade is **serial**: sections multiply, so dB
curves **add**. Engine sample rate **SR = 39 062.5 Hz**.

**Bandwidth → pole radius** (the one formula you need):

```
r = exp(−π · B / SR)          B = bandwidth in Hz
Q = f / B                     acoustic definition
Q ≈ 1 / (2(1 − r))            quick radius → Q estimate
```

| B (Hz) | r       | character (from the tables' own guidance) |
|-------:|---------|--------------------------------------------|
| 8      | 0.99936 | ringing metal (engine caps ~0.9985–0.9992)  |
| 25     | 0.99799 | damped metal                                |
| 55     | 0.99559 | tight vowel F1                              |
| 90     | 0.99279 | vowel F2                                    |
| 150    | 0.98801 | vowel F3                                    |
| 250    | 0.98009 | Klatt's constant B4                         |
| 400    | 0.96834 | broad body resonance                        |

Forge clamps: freq 30 Hz – 16 kHz · pole r ≤ 0.9992 · zero r ≤ 0.9995 · gain −26…+12 dB.

**The serial-cascade laws** (why recipes work):
- A zeroless section's rolloff buries the whole chain — every section flat-ended.
- The foundation is a **flat-topped low shelf** (lows held, flat above so the
  formants ride hot) — NOT a lowpass.
- **Section index is the morph pairing** (S_i ↔ S_i across corners) — sacred.
  Don't rank-swap formants between frames.

---

## 2. Vowels — MEASURED (Peterson & Barney 1952, adult male)

`tables/vowel_formants.json`. Place one resonant section per formant; F1+F2
carry the identity, F3 adds presence. r from the bandwidths via §1.

| vowel | as in  | F1  | F2   | F3   | B1 | B2  | B3  |
|-------|--------|-----|------|------|----|-----|-----|
| iy    | beet   | 270 | 2290 | 3010 | 55 | 90  | 120 |
| ih    | bit    | 390 | 1990 | 2550 | 60 | 95  | 130 |
| eh    | bet    | 530 | 1840 | 2480 | 65 | 100 | 140 |
| ae    | bat    | 660 | 1720 | 2410 | 70 | 105 | 150 |
| aa    | father | 730 | 1090 | 2440 | 80 | 90  | 160 |
| ao    | bought | 570 | 840  | 2410 | 70 | 80  | 160 |
| uh    | but    | 640 | 1190 | 2390 | 80 | 90  | 150 |
| uw    | boot   | 300 | 870  | 2240 | 55 | 75  | 140 |
| uu    | book   | 440 | 1020 | 2240 | 65 | 85  | 140 |
| er    | bird   | 490 | 1350 | 1690 | 65 | 95  | 120 |

Voice scaling (rule of thumb, same file): female ×1.16, child ×1.25.

**Morph pairs that talk** (same file): `oo→ee` (F2 flies 870→2290 — the classic
glide) · `ah→ee` (open→bright) · `oo→ah` (closed→open) · `ee→ah` (bright→open).

**Klatt 1980 reference voice** — MEASURED (`tables/klatt_1980_formants.json`,
JASA 67(3); Mullen 2006 PhD as the second calibration):

| IPA | as in        | Klatt F1 | F2   | F3   | F4   | Mullen F1 | F2   | F3   | F4   |
|-----|--------------|----------|------|------|------|-----------|------|------|------|
| a   | bard/father  | 700      | 1220 | 2600 | 3300 | 673       | 1097 | 2457 | 3464 |
| e   | bed/bet      | 490      | 1720 | 2520 | 3300 | 542       | 1690 | 2456 | 3511 |
| o   | bought       | 540      | 1100 | 2300 | 3300 | 615       | 990  | 2465 | 3408 |
| u   | boot         | 350      | 1250 | 2200 | 3300 | 342       | 1067 | 2219 | 3342 |

**Klatt bandwidths** (`tables/klatt_1980_bandwidths.json`, Table I/II/III) —
Klatt vowels are ALL-POLE in cascade; **F4 = 3300 / B4 = 250 Hz held constant
across vowels** ("little decrement in output sound quality") — license to park
a fixed presence section:

| vowel     | B1  | B2  | B3  |
|-----------|-----|-----|-----|
| i (ee)    | 52  | 200 | 400 |
| a (ah)    | 130 | 70  | 160 |
| u (oo)    | 72  | 105 | 110 |
| m (nasal) | 40  | 200 | 200 |
| n (nasal) | 40  | 300 | 300 |

Nasal pole/zero (Table I): nasal pole fixed at **270 Hz, BW 100**; non-nasal
speech cancels it with a zero at the same 270 Hz. To nasalize a vowel: shift F1
up ~100 Hz and place the zero at mean(F1+100, 270) — a pole-zero-pole split
that ducks F1. Nasal murmur character = WIDEN B2/B3, not extra poles.

---

## 3. Tubes — PHYSICS (c = 343 m/s)

`tables/tube_resonances.json`.

```
open-open  (flute):     f_n = n·c/2L         full harmonic series
closed-open (clarinet): f_n = (2n−1)·c/4L    odd harmonics, hollow, octave lower
```

| tube         | f1 (Hz) | partials (Hz)                    |
|--------------|---------|----------------------------------|
| open 50 cm   | 343     | 343 686 1029 1372 1715 2058      |
| open 25 cm   | 686     | 686 1372 2058 2744 3430 4116     |
| open 18 cm   | 953     | 953 1906 2858 3811 4764 5717     |
| open 10 cm   | 1715    | 1715 3430 5145 6860 8575         |
| closed 50 cm | 172     | 172 515 858 1201 1544 1887       |
| closed 25 cm | 343     | 343 1029 1715 2401 3087          |
| closed 18 cm | 476     | 476 1429 2381 3334 4287          |

Recipe: one section per partial, equal r (tube modes share damping). **Morph =
change the length** (slide the whole series) or open↔closed (harmonics appear/vanish).

---

## 4. Struck metal — PHYSICS (beam/plate modal theory)

`tables/metallic_modes.json`. Metal partials are **inharmonic** — that IS the
metallic sound. Multiply a ratio row by your fundamental.

| object       | ratios                                        | worked example (Hz) |
|--------------|-----------------------------------------------|---------------------|
| free bar     | 1 · 2.756 · 5.404 · 8.933 · 13.34 (glockenspiel — the 2.76× first overtone IS the clang) | ×440 → 440 1213 2378 3931 5870 |
| clamped bar  | 1 · 6.267 · 17.55 · 34.39 (tine/thumb-piano — huge gaps → pure ping) | ×220 → 220 1379 3861 7566 |
| free plate   | 1 · 1.73 · 2.33 · 2.65 · 3.5 · 3.93 · 4.81 (cymbal — dense → shimmer wash) | ×600 → 600 1038 1398 1590 2100 2358 2886 |
| bell         | 0.5 · 1 · 1.2 · 1.5 · 2 · 2.5 · 2.67 · 3 · 4 (hum prime **tierce** quint nominal… — the 1.2× minor-third tierce is why bells sound faintly sad) | prime 500 → 250 500 600 750 1000 1250 1335 1500 2000 |
| gong         | 1 · 1.52 · 2 · 2.41 · 2.78 · 3.33 · 4.06 · 5.1 (no clear pitch, blooms upward) | ×300 → 300 456 600 723 834 999 1218 1530 |

Q guidance (same file): ringing metal B ≈ 8 Hz → r ~0.9994 (cap at engine max),
damped B ≈ 25 → r ~0.998, dead thud B ≈ 90. Morph pairs: muted→ringing bell
(partial emphasis crossfade), bar→plate (sparse clang → dense shimmer).

---

## 5. The seven families — `tables/family_intents.json`

A body = (family, **home intent → away intent**). The morph becomes a *named*
move ("ah → ee"), never a random shape change. Slots align index-for-index, so
any two intents in a family morph cleanly.

| family   | slots                                   | provenance |
|----------|------------------------------------------|------------|
| vocal    | F1 F2 F3 — ee ih eh ae ah aw uh oo uu er | **MEASURED** (Klatt 1980) |
| cavity   | fundamental · 2nd mode · scoop notch · upper mode — wine_bottle 119 Hz, beer_bottle 163, plastic_jug 100, mason_jar 715, tin_can 1591, stone_pipe 143, bathtub 107 | **PHYSICS** (Helmholtz + pipe/room modes, dimensions in file) |
| resonant | low/mid/hi/top mode + scoop — iron_ring, glass_ring, brass_bell, single_scream… | **AUTHORED** |
| knock    | knock · body · grit · scoop · tear — soft_knock, snapping_punch, deep_chest… | **AUTHORED** |
| comb     | 2 peaks + 4 notches — low_wide_comb, chambered_phaser, flanger_tail… | **AUTHORED** |
| cut      | body_low · body_mid · scoop · tear_lo · tear_hi — single_tear, high_razor… | **AUTHORED** |
| violence | body · scream · scoop · tear · top_notch — chainsaw, drill_squeal, acid_303… | **AUTHORED** |

AUTHORED = our clean-room design vocabulary, original values steered by ear —
keep them honest by auditioning, not by treating them as measurements.

---

## 6. P2K vocal law — CLEAN-ROOM LAW

`tables/p2k_vocal_law.json` (structure decoded from 5 reference bodies through
the shipped DLL; no coefficients carried):

- Stage-1 "throat" pole lives at **200–580 Hz**.
- **One deep zero (r 0.9–1.0) beside each formant pole** — the anti-resonance
  canyon is part of the vocal recipe, not an option.
- Motion law = **slide**: log-slide the whole constellation under morph;
  never rank-swap formants.

---

## 7. The iconic corridor — MEASURED through the shipped engine

From the iconic-15 ROM decodes via `evaluate_body` (the rebuilt audit — the
gates that pass 15/15 real bodies):

- max pole radius **0.985–0.988**
- response span **40–120 dB**
- **Q bloom 6–34 dB** (secondary-contrast-rms) — Q is a co-leader, not subtle:
  Talking Hedz +17.7 dB peak / 6.3 rms · Meaty Gizmo +32.8 / 33.9 ·
  Early Rizer ≈ +13 · Ace ≈ +15
- **anchor + mover**: most sections hold; ONE leader pole and ONE leader zero
  each travel **1–5.6 octaves** under morph
- low body held as a flat-topped shelf throughout (E-mu's law: high resonance
  **without losing bass power**)

**Q-axis radius mapping** — MEASURED from the RE corpus
(`tables/q_radius_table.json`, 45 of 512 table indices observed over 252
stages). The Q axis is a radius schedule, top-heavy:

| q index | 0      | 5      | 10     | 15    | 20    | 25    | 30    | 40~44 | 55    | 70    | 104   |
|---------|--------|--------|--------|-------|-------|-------|-------|-------|-------|-------|-------|
| radius  | 0.9863 | 0.9829 | 0.9734 | 0.958 | 0.937 | 0.910 | 0.878 | ~0.76 | 0.654 | 0.489 | 0.124 |

Index 0 (r 0.9863) carries 132 of the corpus hits — the iconic bodies live at
the top of this schedule, consistent with the 0.985–0.988 corridor above.

---

## 8. Worked recipes (the forge seeds follow these)

1. **Vowel glide** — pick a talking pair from §2 (say `oo→ee`). S1 = low anchor
   ~134 Hz, locked. S2–S4 = F1–F3 at the home vowel (low frame) and away vowel
   (high frame), r from bandwidths, zero ~4× each pole (the §6 canyon). Q100
   corners: shrink (1−r) by ~⅓.
2. **Tube stretch** — §3 row, one section per partial, morph slides every
   partial by the same ratio (length change).
3. **Metal strike** — §4 ratios × a fundamental on the 12-TET grid; high r;
   morph to a different object's ratios (bar→plate) for the shimmer dissolve.
4. **Resonant LP sweep** — 3 stacked poles at the cutoff (staggered r so the
   corner is resonant, not unstable), zeros parked at 14 kHz, cutoff travels
   110 Hz → 3.5 kHz under morph. The leader move from §7.
5. **Notch comb / phaser** — zeros at odd multiples of f0 (deep, r 0.99),
   near-allpass poles just below each zero; morph slides f0 (e.g. 220→880 Hz).
6. **Bass-safe anything** — whatever the upper sections do, S1 stays a
   flat-topped low shelf. Check the plot: lows flat, not tilted.

Judge on the plot first (it IS the engine — 0.0000 dB match), confirm by ear
through the full AGC → saturation → QSound chain.
