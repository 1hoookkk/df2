# Working Forge — P2K authoring method (validated)

This is the authoring law for the working forge (`forge-web/`, the `zedit.html`
z-plane editor on the WASM engine). Everything here was tested through the
shipped engine this session; claims are graded **OBSERVED / INFERRED / REJECTED**.
The doctrine in the repo-root `CLAUDE.md` still governs — this is the *how*.

## The object
- A body = **240 bytes = 4 corners × 6 sections × 5 minifloat words**.
  Corners: `M0_Q0, M100_Q0, M0_Q100, M100_Q100`.
- Runtime bilinearly interpolates the **packed u16 words** (morph-first, then Q).
- **plot == engine to 0.0000 dB** (OBSERVED). The magnitude plot is the judge.

## Hard-won laws (OBSERVED this session)
1. **Replay is solved; authoring is the work.** The engine reproduces the real
   E-mu hardware exactly (Early Rizer screenshots matched). It's a faithful
   *player* of real bytes — making *our* bytes sound that good is the open job.
2. **The plot is the judge; scalar metrics are provisional.** `bodyVsMid` (low
   band − 800–3000 Hz mid) **lies** on wild types — when the mid band is empty it
   reads +60 dB that isn't real. Validate every number against the curve.
3. **Character lives in the MORPH INTERIOR, not the corners.** Interpolation is
   in packed-coefficient space, so the interior is not a blend of the corner
   curves (the E-mu "magic in the middle"). **Judge with corners-2×2 + a Q=100
   morph sweep**, never corners alone.
4. **Stages don't matter as roles.** The cascade is a commuting product
   `H=∏Hₖ` → stage **order is free**; **no stage has a fixed musical role** (a
   slot low at M0 can be midrange at M100). Only the **morph-pairing** (section i
   across corners) and **per-section pole+zero content** matter.
5. **Q = pole radius (sharpness). Morph = pole/zero FREQUENCY placement.** Both
   axes act; "Q cranks the radius" is the whole story for the secondary axis.
6. **Do not invent poles — use our tables** (`tables/`): `klatt_1980_formants`,
   `klatt_1980_bandwidths` (radius = `exp(-π·BW/SR)`), `q_radius_table`,
   `vowel_formants`, `family_intents`, `metallic_modes`, `tube_resonances`,
   `p2k_vocal_law`.

## Zero placement — the crux (all TESTED)
- **DC zeros (0 Hz): REJECTED for bodies.** N stacked DC zeros = a high-pass that
  annihilates the foundation. (Gemini's "lock zeros to DC" killed the body.)
- **Nyquist zeros (the very end): REJECTED for formants.** N stacked Nyquist
  zeros = a low-pass that buries the formants. (Strong held body, dead vowel.)
- **Anti-formant zeros near the pole:** weaken/over-cut the actors in cascade.
- **ALL-POLE (zero banished → pure resonator): USE THIS for vowels.** Klatt
  vowels are all-pole; the cascade's natural downward tilt **is** the body, and
  formants are clean bumps on the tilt. No uniform zero rule survives a cascade —
  banish the zero unless you specifically want a notch.
- Real P2K bodies *do* carry zeros, but **per-section and varied (mined)**, never
  a uniform rule. (TalkingHedz zeros: 347, 1113, 2014 Hz — anti-formants, mined.)

## Foundation / body
- Body = the low end of the all-pole tilt (+ optional low pole, held across corners).
- **Per-corner gain** pins ~60 Hz to 0 dB; **distribute it over all 6 lanes
  (`gain ^ 1/6`)** so no single lane's minifloat underflows. (OBSERVED bug: dumping
  the whole scalar on one lane → `b0≈0` → encoder fails.)

## The two interior "magic" primitives (VERIFIED in-engine)
- **Zero unmasking** — zero sits exactly on its pole in one corner (flat/masked);
  slide the zero away in the other corner → a peak **erupts from flat** mid-morph.
  Clean, reliable. (OBSERVED: 0.0 → +13 dB as the zero slid 1500→100 Hz.)
- **Pole collision** — two actors swap frequencies across corners → they cross
  mid-morph → a spike at the crossing frequency; **size scales with pole radius**
  (+6.5 dB at r0.88, +14 dB at r0.97). The "tearing" accent.
- **Travel = the verb; collision = punctuation.** The iconic E-mu *sweep* is one
  actor (or a parallel block) with large morph-frequency travel; collisions are
  occasional accents, not the mechanism.

## Topology recipes (by family — use the tables for the numbers)
- **VOWEL / ACOUSTIC** (TalkingHedz, MultiQVox): foundation held; 3–5 formant
  poles from Klatt tables; **all-pole (zeros banished)**; keep `f1<f2<f3` — never
  cross; morph glides between two vowels; Q sharpens. Radius from bandwidths.
- **SWEPT / ANALOG** (Early Rizer): one **leader pole** with large morph-frequency
  travel = the audible sweep; optional stacked low-radius follower poles for a
  steeper slope; Q sharpens. (Its "rizer" is travel, not collision.)
- **SCREAMER / TRANSIENT** (LucifersQ, EarBender): **no separate ruleset** —
  REJECTED the "screamer class" theory by control test (the clean vowel scores
  higher on peak gain, radius, and center-spike than the screamers). Same
  architecture; the violence is **wild actor layout** (inharmonic, wide leaps) +
  collisions for accent + high radius driving the saturation.

## The tool & next step
- `zedit.html` — z-plane drag editor (orange X = poles, green O = zeros, per
  corner), engine-faithful Bode, morph/Q, **save .body240**, play through AGC.
  Served at `localhost:8130`. Zero-unmask = drag O onto X then off in the other
  corner; collision = swap two poles across corners; body = a low X with its O
  banished.
- **Next: a Fitter backend** so you stop wrestling 12 variables by hand:
  - *Audio fit* — wrap `tools/fit_two_audio_arma.py`: drop a vowel WAV → snap
    poles/zeros to its real formants+bandwidths.
  - *Macro-shape fit* — `scipy.optimize.least_squares` against a declared target
    curve (e.g. "36 dB/oct LP @ 800 Hz"), with guardrails (radius ≤ 0.98, lane 6
    held at the foundation). Returns pole/zero positions → UI snaps them.
  - Wire as a small FastAPI/Flask endpoint behind an "Auto-Fit Target" button;
    hand-drag only to add dirt / set a collision.
