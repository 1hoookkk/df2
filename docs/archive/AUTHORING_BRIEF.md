# AUTHORING BRIEF — what I am authoring, and the control I need over it

*For an engineer to decode into a grounded surface/workflow. Raw DSP, literal. Biological
terms are the **control metaphor only** (the over-learned vocal-tract gesture), never a naming
taxonomy. Section roles are defined by **ablation**, not by anatomical label.*

---

## 1. The artifact

A *body* is one 12th-order Z-plane filter: **6 cascaded second-order sections**, each carrying
a complex-conjugate **pole pair** `(r, θ)` and a complex-conjugate **zero pair** `(r_z, θ_z)`,
with `θ = 2π·f/SR`, `SR = 39062.5 Hz`.

- Pole radius `r` sets resonance sharpness: `Q ≈ 1/(2(1−r))`; stability requires `|p| < 1`.
- Zero radius/angle set the depth and frequency of a **spectral null** (anti-resonance).
- **Both pole and zero are mandatory in every section.** A zeroless section is a broken section
  (all-pole stacks roll off −12 dB/oct each → a −236 dB crater; the flat-ending zero is the fix).
- Storage: 4 *corners* × 6 sections × 5 packed minifloat words = **240 bytes**. Output artifact.

## 2. The body is two postures plus a pressure rule

Author two endpoint pole-zero sets over the same 6 section indices:

- **Frame A** and **Frame B**. Section *i* in A is pinned to section *i* in B — the pairing is
  **fixed and sacred**. Cascade order *within* a corner is free (`H(z)=∏Hₖ(z)` commutes).
- **Q** scales pole radius toward the unit circle.
- The 4 corners are exactly the 2×2: `C0 = A·loQ`, `C1 = B·loQ`, `C2 = A·hiQ`, `C3 = B·hiQ`.

## 3. Two continuous controls play it (orthogonal)

- **Morph** = angular articulation. Interpolates A→B **in packed minifloat-code space**, which is
  **geometric / logarithmic**: a pole 400→4000 Hz passes ~1274 Hz at Morph 0.5, not linear 2200.
  **All travel is reasoned in octaves/semitones, never linear Hz.** (OBSERVED, 0.0000 dB faithful.)
- **Q** = radial pressure / effort. Drives every pole `r → ~1.0`, simultaneously deepening the
  zero nulls. Extends impulse-response decay time: a damped open cavity → a high-Q reflective pipe.

Morph slides every pole/zero along its own A→B path; Q pushes every pole radially toward the rim.

## 4. THE PRODUCT IS THE TRAJECTORY, NOT THE ENDPOINTS

The first-class authored object is the **path each of the 6 sections travels from A to B** — its
pole arc in `(r, θ)` and its zero arc — and how that path tightens under Q. Endpoints alone are two
still frames; the audible product is the **coherent motion between them**. The ear tracks motion
coherence (a resonance sliding, a constriction tightening), not static EQ states.

## 5. What makes it iconic, in DSP terms (no labels — these are roles found by ablation)

- A dominant section is a **leader**: its pole sweeps **multi-octave** across morph (reference ROM
  decode: +4.09 oct, 578→9826 Hz). One dominant gliding leader — not a democracy of 1-oct wiggles.
- One or two sections move **contrary** and **cross** the leader mid-morph (a rising pole meeting a
  falling pole = the formant-crossing "talk"; mimics an F1/F2 crossover).
- A **foundation** subset holds low energy (<~500 Hz) with near-zero motion and **uncut gain**, and
  must survive high Q without clipping or mutating into a whistle — *high resonance without losing
  bass power*.
- The remaining sections carry **hand-placed zeros**: poles add resonant material, zeros carve
  anti-resonant voids. OBSERVED: fitted pole-sets already match the reference corpus on morph/span/
  scream; the **only** missing dimension vs. the 50 reference types is **zero placement and zero
  motion** — the nulls are the character, and they are hand-authored.

**Role is defined by ablation**: mute a section and judge the *driven* output. Mute collapses
identity → foundation/leader. Mute changes nothing → waste, replace it.

## 6. Pole provenance

Pole frequencies seat on **real resonances** — vocal-tract formants F1–F4, tube/Helmholtz cavity
modes, modal-shell metallics, measured rails (`tables/`) — offered as **snap targets**. Hand
authoring is free to leave them but defaults onto real physics. Zeros are placed by hand and ear.
*(This reconciles "complete hand authoring" with "do not invent poles": the hand lands on real
rails by default.)*

## 7. The judgment loop — three coupled views, closed through the product chain

The bare cascade is a diagnostic only; **the driven sound is the thing.**

1. **Z-plane canvas (author the anatomy).** Drag 6 pole pairs + 6 zero pairs in `(r, θ)` on real
   snap rails; set each section's **A→B trajectory** as a visible arc/vector; set its Q-tightening.
2. **Magnitude-response curve (the eye verifies the shape).** The **aggregated cascade** dB-vs-Hz
   curve, **bit-faithful to the engine (plot==engine, 0.0000 dB)**, morphing live as Morph/Q move.
   The eye localizes what the ear can't place: HF crater, sub-bass pile-up, instability/clip. This
   is a **diagnostic**, not the auditioning judge — you cannot read Mackie harmonic folding off it.
3. **Driven audio + clip meter (the ear judges the product).** Real material (808 / reese / saw /
   vocal) through **AGC → Mackie saturation → QSound**, **Morph auto-sweeping** ("the morph is the
   loop"), a post-drive level meter flagging overload (FLOODED on clip). **The ear leads; the eye
   confirms; the z-plane is the map.**

Plus: **per-section solo/mute while it plays**, so each section's job is audible in the moment
(live ablation, not a batch pass).

## 8. The biological control argument (why this surface, not a parameter grid)

Sound is an ear sense, and the human already operates a morphing resonant filter — the vocal tract.
A vowel/mouth gesture (moving formants, opening/closing a resonant cavity, constricting toward a
shout) is the **most over-learned continuous controller a person owns**. Map the authoring gesture
to it: the two morph endpoints are two vocal-tract postures, **Morph is the articulation between
them, Q is the constriction/pressure** that sharpens the resonances toward a scream. The ear is the
first judge of motion and bite; the eye is the second.

## 9. The act, repeatedly and fast, by hand

Place/drag 6 pole pairs and 6 zero pairs in `(r, θ)`; set their A→B trajectories as visible paths;
sweep Morph and Q as continuous gestures while real audio plays through the full chain; solo/mute
any section to hear its job; read the engine-faithful magnitude curve as it morphs; keep the ones
the ear picks. Output is the 240-byte body.

**Goal: 4–7 original P2K-class filter types — big multi-octave motion, real Q-pressure (r→~1.0),
hand-carved nulls.** The Forge is a private authoring bench; only the bodies ship, played by the
customer through two knobs (Morph + Q) and the drive chain.

---

## 10. The collapsed model — fit poles, carve zeros (LOCKED)

**OBSERVED (`tools/fit_sources_lpc.py`):** "LPC order-12 on REAL audio → 12 poles = **6 conjugate
pairs**, every section a real resonance; LSF computed for stability/ordering proof." So the body is
**6 lanes**, not 12 stages, and not a 3+3 foundation/fitting split. Each lane carries:

```
pole_hz, pole_radius, zero_hz, zero_radius, gain
```

- **Poles = the foundation body. Fit, read-only.** LPC(12) → 6 conjugate pole pairs seated on real
  resonances; **LSP/LSF informs each lane's radius/Q** (tight LSF pair = high Q) and proves the
  morph stays stable/monotonic (it is *why* the formants glide clean instead of hopping). LSP is
  **not** a second six lanes — it shapes the radius of the same six.
- **Zeros = the only authoring act.** OBSERVED: fitted pole bodies already PASS the gates (v1
  `vowel/rez/tearbass`: alive/moving/clean, maxr ~0.999, 1.5–2.7 oct) and already beat the 50 on
  span/motion. The **only** gap vs the real P2K (reference morph-motion **13.7 dB** vs candidate
  **3.16 dB**, canyon observations sparse/null) is the **zeros** — the hand-carved anti-resonance
  canyons between and beside the formants. That is the whole job.
- **Bass law holds:** the lowest lane's zero stays banished (broad shelf, sub booms uncut) while Q
  cranks the upper lanes — high resonance without losing bass power.

Each zero **rides with its lane's pole across morph** (the canyon tracks its formant); author once,
it follows. Body = 4 corners × 6 PZ lanes → `.body240` → `trench_core packed_probe` / driven audition.

## 11. The surface — self-contained, everything in-surface (LOCKED)

One screen, no scripts, no backend juggling. Four operations, in order:

1. **Fit foundation.** Open a `.wav` → LPC(12) + LSF → **6 read-only pole lanes** drawn as the live
   engine-faithful curve (foundation + gliding formants). Poles are not hand-edited.
2. **Carve zeros.** Click the curve to drop a zero ●; drag = its Hz, scroll = its depth/radius.
   Zeros are the only editable object. Each binds to its lane and tracks that pole under morph.
3. **Audition.** Morph + Q sliders drive both the curve **and** real audio through **AGC → Mackie →
   QSound**, morph auto-sweeping ("the morph is the loop"), a post-drive meter flagging FLOODED clip.
4. **Save.** Write `.body240` (+ cartridge / audition slot for the plugin hot-reload).

Everything else — corners C0–C3, foundation locks, the 24-cell matrix, the score panel — is either
**derived by the engine** or tucked behind one "more/audit" toggle. On screen: **the curve, the
zeros, Morph, Q, play, save.** Output: 4–7 original P2K-class bodies, ear-picked.
