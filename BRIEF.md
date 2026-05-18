# df2 — Project Brief

The orientation document. Read this first. CLAUDE.md tells you *how* to
work; this file tells you *what the project is*.

---

## What it is

A filter plugin built on the E-mu Z-plane filter architecture: 12-stage
DF2T biquad cascade with 4-corner bilinear interpolation across a
Morph × Q surface. Rust DSP core, JUCE C++ shell, wgpu rendering.

Bodies (named filter characters) are authored once and ship as cartridges
that load into the plugin. v1 ships with four bodies. Cartridges become
the recurring revenue stream.

The runtime is frozen and patent-verified. The work going forward is
authoring bodies, building the JUCE shell, building the visualization,
and shipping.

---

## Who it's for

Underground producers, sound designers, beat makers. The kind of person
who uses Renoise, Ableton, Bitwig, or Reaper. The kind of person who
follows specific scenes — experimental electronic, underground hip-hop,
ambient, noise, sound-art adjacent genres. The kind of person who buys
plugins from boutique developers because of their character, not their
feature list.

**Not** bedroom EDM producers. **Not** audiophiles. **Not** engineers.

If a producer needs the plugin explained, they're not the audience. The
plugin filters its own audience through opacity.

---

## The discipline

> *Vague on purpose. Dead chassis, live math.*

See BRAND.md for the full visual and verbal discipline. The short version:
no tooltips, no onboarding, no feature lists, no FAQ, no documentation
for outsiders. Clarity is reserved for function and transaction. Meaning
stays vague. Trust is built through audio quality and aesthetic
consistency.

---

## The four shipping bodies (v1)

| Name              | Sonic character           | Q-axis label |
|-------------------|---------------------------|--------------|
| Speaker Knockerz  | Bass / cone breakup       | CONE         |
| Aluminum Siding   | Mid-scoop / metallic edge | STRESS       |
| Small Talk        | Vocal / formant           | CAVITY       |
| Cul-De-Sac        | Comb / enclosed resonance | COMB         |

Each body has authored audible targets in BODIES.md. The validation gate
is null-test against reference E-mu wet renders at ≤ −60 dB null depth.

---

## The brand structure

| Name              | Role                            | Status                       |
|-------------------|---------------------------------|------------------------------|
| **Trenchwork**    | Maker (the company)             | Public                       |
| **df2**           | The plugin product              | Public; ships commercially   |
| **Filter Factory**| Private authoring tool          | Never released; for Tyson only |
| **1hook**         | Music producer identity         | Separate from Trenchwork     |

Filter Factory is private infrastructure — visible in content, never
released. The fact that only Trenchwork can produce Trenchwork bodies
is the moat.

---

## Where the project is right now

The runtime is correct, the docs are in place, the architecture is
locked. What's outstanding (see STATE.md for live detail):

- Carry trench-core and reference data from the old trench/ repo
- Build the JUCE C++ shell wrapping the Rust core (~5% of total codebase)
- Integrate wgpu rendering into the JUCE window for the visualization
- Author the four shipping bodies and pass the null gate
- Build out cartridge loading
- Ship v1

The first validation milestone is: render any df2 body through the JUCE
shell, null against one canonical wet, confirm the pipeline produces a
measurable null depth. After that, the work is authoring bodies against
the audible targets in BODIES.md.

---

## Hard constraints

- **Clean Room rule.** No reverse-engineered E-mu coefficients ship in
  df2. The X3 wet renders and P2K skin captures are reference material
  for the null test only — they do not appear in any cartridge.
- **Filter Factory is private.** Never released. Never publicly
  documented as a tool that exists for others to use.
- **Cartridge format is `compiled-v1`.** Stable forever. Cartridges
  purchased today must work in df2 a year from now without re-authoring.
- **The chassis is institutional green** `#4A5348`. Never drift toward
  grey, olive, or military green. This is the single committed weird
  element; nothing else competes with it for distinctiveness.

---

## The validation gate

A body ships when:
1. It passes `tools/null_test.py` against reference wets at ≤ −60 dB
   null depth at all 4 corners and at midpoint M/Q positions
2. It hits the audible target described in BODIES.md (auditioned by ear,
   subjective gate)

Both gates. Neither is sufficient alone.

---

## What the project is not

- Not a vintage emulation marketed as "the sound of the X3"
- Not a feature-comparison plugin competing with FabFilter or Soothe
- Not an educational tool — producers are not taught how to use it
- Not a community platform — no Discord, no forum, no user forum
- Not a subscription product — cartridges are one-time purchases
- Not multi-platform-for-its-own-sake — desktop DAW plugins first; mobile/tablet may follow later but is not a v1 goal

---

## The resolving question for any decision

> *Does this make the chassis feel less dead, or the math feel less alive?*

If yes, it's wrong. If no, it's allowed.

Everything in the project descends from that question. When in doubt,
ask it.
