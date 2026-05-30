# Morpheus / Z-plane authoring doctrine (source-grounded reference)

Captured from the project NotebookLM (Rossum patents, ARMAdillo 1991, Klatt 1980,
Morpheus manual, Peterson-Barney) over the 2026-05-30 session. **This is the Morpheus
SYNTH reference architecture.** df2 is an INSERT FX, not a synth — so each preset-layer
item below is annotated with how it maps to df2 (or that it does NOT apply). When a
Morpheus concept contradicts df2's code, the code wins (df2 has no voices, no MIDI
note-on, no keyboard, no oscillators).

## The division of labor (the spine)
- **CORNER authoring = the LLM's job.** Author the 4 static acoustic postures (corner
  frames). Perceptual units, real tables, unity DC, fixed slots, poles cross. The engine
  interpolates between them. See the corner doctrine: memory `bass-no-sub-gain-unity-dc`
  + `tools/author_corner_library.py` + recipes #1-4 below.
- **PRESET authoring = the control wrapper** (instruments, ranges, modulation routing,
  envelopes). On a SYNTH this is huge; on df2 (insert FX) most of it collapses to the
  audio input + DAW automation + a few opt-in reactive modulators (OFF by default).

---

## A. CORNER doctrine (df2's actual job) — recipes #1-4
1. **Exact formants + cascade coupling.** Vowels: exact F1-F5 + empirical B1-B5
   (Peterson-Barney / Klatt; `tables/vowel_formants.json`, `klatt_1980_bandwidths.json`).
   Peak amplitude ∝ 1/Bw (halving Bw = +6 dB) — gain is DERIVED from bandwidth, never
   uniform. Coupling: two formants within ~200 Hz boost each other +3..+6 dB; widen Bw or
   it overloads. Bandwidth = physical energy loss (too narrow = metallic ring; too wide =
   raw buzz). Realize as flat-baseline PARAMETRIC PEAKING EQ (pole+zero), not all-pole.
2. **Fractional slopes (woody bodies).** Bode pole-zero interlacing: pole = -slope step,
   zero = +slope step; exponentially interlace zeros ~½ octave from poles for arbitrary
   dB/oct roll-off (e.g. -3 dB/oct pink). Already shipped: `voxbench` Spectral Tilt.
3. **Comb/flanger spacing.** Log-space notches by the golden ratio 1.61 from ~40 Hz so
   they hit harmonics one at a time as Morph sweeps (Flange3.4). `golden_comb()`.
4. **Unity DC gain (Rossum).** Force cascade DC (z=1) gain to EXACTLY 1.0 — sub passes at
   unity, no boost/choke, headroom safe under extreme sweeps. A bass body SHAPES the low
   end; it NEVER adds sub gain (the sub is the source's job). RBJ peaking EQ is unity-DC by
   construction; NEVER peak-normalise (scaling c4 drags DC off unity = the sub-gain bug).
5. **Distinct postures, not transposition.** Four corners = four different physical spaces
   ("remember the shape of your mouth for each vowel and interpolate"). Fixed stage slots +
   2 crossing movers (anchors + crossers, the Talking-Hedz s1/s5 swap) → the middle is an
   emergent collision, not one shape slid.

## B. PRESET doctrine (the Morpheus wrapper) + df2 mapping
**1. The "Clay" — instruments & layering.** Primary + Secondary sample layers, Key/Velocity
ranges, Transpose/Coarse/Fine, Double+Detune (2→4 voices).
→ **df2: N/A.** "Instrument" = the incoming audio track. No layers, voices, key/velocity
ranges, tuning, or Double+Detune (an insert FX has no oscillators/voices).

**2. The "Die" — filter selection & static offsets.** Pick 1 of 197 ROM Z-plane types per
layer; set **Filter Level** (drive into the filter → distortion hot-spots), **Morph Offset**
(resting morph point), **Freq-Tracking & Transform-2 offsets** (baseline tune/resonance).
→ **df2: APPLIES.** Filter Level = `slamDrive`/`inputMode` (SLAM). Morph Offset = `morph`
param default. Transform-2 offset = `q` param default. Frequency Tracking = NO df2 axis
(df2 is 2D Morph×Q only).

**3. Note-On modulation (the "strike").** Up to 10 patches at key-strike. RULE: **Freq
Tracking & Transform-2 change ONLY at note-on** (not while held). Standard: Key# →
Freq-Tracking (+064, key-track); Velocity → Transform-2 (harder = brighter/sharper).
→ **df2: APPLIES as OPT-IN reactive modulation, OFF by default.** No note-on/velocity, so:
Velocity→Transform-2 becomes **envelope follower → Q**; Key#→Freq-Tracking becomes a
**pitch tracker** (no axis yet) or DAW automation. (Modern DSP, NOT in the E-mu sources.)

**4. Real-time modulation (the "journey").** Up to 10 patches while held. RULE: **Morph is
the ONLY filter control continuously variable in real-time.** Patch mod-wheel/LFO/envelope
→ Morph (e.g. envelope sweeps ee→ah on a vocal corner).
→ **df2: APPLIES, maps flawlessly.** `morph` exposed as a VST param = DAW automation /
MIDI CC; plus df2's built-in free-run animator `teleport*` (the Function-Generator
equivalent), and an opt-in tempo-LFO/env-follower → Morph.

**5. Amplitude & contours (DCA + Function Generators).** Alternate-Volume AHDSR → DCA
(output volume); 8-segment Function Generators (time/level/shape/conditional jumps) as
erratic LFOs / sequencers animating Morph.
→ **df2: mostly N/A** (no per-note DCA envelope — it's an always-on insert; `output` =
makeup gain). The Function Generator ≈ a programmable Morph LFO (df2's `teleport`, opt-in).

## C. df2 actual parameters (the ground truth)
`morph` (Morph X) · `q` (Q / Transform-2) · `body` (preset/cartridge) · `output` (makeup) ·
`inputMode` (OFF/SLAM) · `slamDrive` (Filter Level) · `fiveD` (QSound) · `teleport*`
(free-run Morph/Q animator). **No** velocity, voices, layers, key-tracking axis, pitch
tracker, env-follower, or DCA envelope — those are the OFF-by-default FX-host layer that
CLAUDE.md plans, not shipped. df2 is transparent-by-default: every modulator ships OFF.
