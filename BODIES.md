# BODIES.md

The 4 shipping bodies. Audible targets only. Names are normative;
specific corner assignments and frame IDs live in `STATE.md` and the
authored body JSON.

Each body has a motion sentence. Before authoring, the sentence must be
writable and true. The validator (null test) confirms math; the sentence
confirms intent.

---

## Speaker Knockerz

**Sonic identity**: sub-harmonic resonator, blown speaker cone cry.
Heavy, physical, lower than the speakers can comfortably reproduce.
Sub-bass never disappears, even at maximum morph.

**Motion sentence**: "the cone strains harder as morph rises, the cry
sharpens as Q tightens."

**Audible failure modes**:
- Loses the sub below 60 Hz at any morph/Q position → fail
- Becomes a generic lowpass sweep at high morph → fail
- Q has no audible effect → fail (Q-axis-degenerate)

**Frequency band targets**:
- M0: heavy fundamental at 40–60 Hz, slow rumble texture
- M100: cone breakup at 80–120 Hz with sharp harmonic spike
- Q controls how "torn" the cry sounds — soft pillow at Q0,
  serrated rip at Q100

---

## Aluminum Siding

**Sonic identity**: brittle treble stressor, crystalline metal under
strain. Permanent mid-scoop around 1 kHz — vocal range is dead so the
high content stays exposed.

**Motion sentence**: "the metal stresses past its yield point as morph
rises, the shatter intensifies as Q sharpens."

**Audible failure modes**:
- 1 kHz scoop disappears at any position → fail
- Becomes a generic highpass sweep → fail
- Sounds like ordinary EQ brightness → fail (no character)

**Frequency band targets**:
- M0: dull silver, present highs but no edges
- M100: shatter point, peaks at 6–12 kHz becoming painful
- Q controls how "torn" the metal feels — surface stress at Q0,
  cracking at Q100

---

## Small Talk

**Sonic identity**: biomechanical vocal cavity. Exactly two dominant
formants active at all times. The thing the user hears is "speech-like
but not speech."

**Motion sentence**: "the mouth opens from yawn to shriek as morph
rises, the throat tightens as Q rises."

**Audible failure modes**:
- More than two dominant formants present → fail (not vocal)
- Fewer than two dominant formants present → fail (not vocal)
- Formants don't move with morph → fail (no motion)
- Q audibly changes the vowel rather than the cavity → fail (Q-axis violation)

**Frequency band targets**:
- M0: low formant pair around 500/1500 Hz (Yawn → Open Ah)
- M100: tight formant pair around 300/2800 Hz (Bite → Shriek)
- Q controls cavity size, not vowel identity

---

## Cul-De-Sac

**Sonic identity**: thick tube that fractures into a comb matrix.
Constant low-level root hum holds the floor; everything else is
fracture pattern on top.

**Motion sentence**: "the iron pipe rusts and bulges as morph rises, the
fracture comb tightens as Q rises."

**Audible failure modes**:
- Root hum disappears at any position → fail
- Comb structure absent at high morph → fail
- Sounds like a flanger or phaser sweep → fail (wrong character)

**Frequency band targets**:
- M0: dark tube resonance at 100–250 Hz, dull body
- M100: comb teeth across 500 Hz–8 kHz with deep notches
- Q controls comb density — wide-spaced at Q0, dense at Q100

---

## Discipline

- Every body assigns a body-specific Q-axis label in shipping UI
  ("Cone," "Stress," "Cavity," "Comb" — not "Q").
- Every body must pass null test at all 4 corners against its reference
  material before shipping.
- A body that "almost works" doesn't ship. The sonic identity is
  binary: either the listener recognizes the body within 5 seconds or
  it fails.
