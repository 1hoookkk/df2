# CLAUDE.md — df2 working contract

df2 is a destructive morphing filter FX plugin (808s, bass, vocals, drums, bus). The goal is a
product that sounds expensive, violent, distinctive — not academic emulation. **Tyson owns** taste,
product feel, body keep/kill, sellability. **Claude drives everything else** — code, builds, git,
files, DSP, plots, tests, cleanup — with safe defaults, surfacing only taste/product calls.

## The body is a filter type
A body = **240 bytes = 4 corners × 6 second-order sections × 5 packed words**. It IS one **12th-order
Z-plane filter type** (12 poles = 6 sections). E-mu's 50 "P2K" entries are filter **types**, not
presets — order 2→12, where order = number of sections. The complex/iconic ones (TalkingHedz,
LucifersQ, MegaSweepz) are all 12th-order = full six sections; the simple LP/HP ones are low-order and
fill few sections (not broken — just low order). The 50 are **reference/study only** (clean-room).

A df2 preset = an **original 12th-order filter type** = **Frame A + Frame B + a Q-rule**:
- **Morph** (the `Freq` knob) interpolates Frame A → Frame B in packed-word space.
- **Secondary / Q** is the per-type character knob (resonance / body-size / notch-depth / EQ-gain,
  depending on the type) — it scales both frames.
- Corners: `C0 = A·loQ, C1 = B·loQ, C2 = A·hiQ, C3 = B·hiQ`.
- **Section index is the morph pairing** (section i ↔ section i across corners) — sacred. Cascade
  order *within* a corner is free (`H(z)=∏Hₖ(z)` commutes).
- **Every section is a pole+zero pair — always both.** Zeros are first-class and mandatory; a
  zeroless resonator is the "stages look wrong" bug.

## Do not invent poles
Every pole traces to a **real resonance**. Sources, in order of leverage:
1. **LPC capture** of a real sound (its resonances → poles). The forge fitter does this.
2. **Physical models** — vocal-tract / tube / modal acoustics; the model's modal frequencies *are*
   the poles, its anti-resonances *are* the zeros. Use the `physical-corners` skill.
3. **Measured tables** — vowel formants, the Hz rails (`tables/family_intents.json`).
4. **Clean-room study** of the 50 real filter types — learn the grammar (section roles, peak vs
   shelf, Q behavior), author originals in that spirit. Copy no coefficients, names, or bytes.

**Never** random / procedural / singularity-field / novelty-search generation, and never invented or
unsnapped placement. This supersedes the procedural `CORNER_QUARRY_TRUTH.md` mining direction.

## Frames and mining
The unit of value is the **frame** (six sections frozen into one filter posture — a vowel, a tube, a
metal shell, a comb). A preset is a **pairing** of two frames + a Q-rule, so a quarry of strong frames
makes presets cheap (every pairing is a body). Mine frames from the real sources above. Keep a **fixed
6-section budget** so any two frames morph (index i → index i); each frame carries a loQ→hiQ scale so
Secondary works on any pairing. A frame earns its place by being a coherent thing the ear recognizes —
never random.

## Forge v1 = picker + player
`forge-web` (webview, small files) is the surface. v1 does **not** edit sections. It pairs two mined
frames and plays the result:
- **Two frames side by side** (Frame A | Frame B, each its endpoint response plot).
- **A smaller full-cascade response** below — the live packed-runtime curve at the current Morph/Q.
- **Morph + Q sliders, play** — audition through the drive chain.
- **Frame quarry strip** — mini-plots sorted low→high by spectral centroid; click to load A or B.
- **Save** = `.body240`.
Section-level editing (`Freq · Shelf(LP↔peak↔HP) · Gain± · Q` → always pole+zero) is deferred to
vNext; the zero-mandatory fix lands in the frame *compiler*, not a v1 UI. Human picks keep/kill by
plot and ear; AI never approves a finished body.

## Plot == engine
**Proven OBSERVED:** forge-web's `packed.js` reproduces the shipped engine to **0.0000 dB**. The plot
does not lie — a body that looks wrong *is* wrong. The magnitude-response plot is the judgment
surface; lead with plots, ear confirms last. Author and plot the same coeffs the engine runs.

## The drive chain is the product
**AGC → Mackie saturation → QSound** is on by default and IS the product sound. **AGC is always on**
(no plain/driven split). Author and judge through the full chain, never the bare cascade.

## One owner per job
Packed-body/morph math lives in **trench-core**; Python, forge, and tools call it via FFI. forge-web
packs through **WASM trench-core** (the same encoder the DLL uses); `packed.js` is the plot-only
mirror to police. Don't add an N+1th copy. Exploratory tools labeled exploratory; canonical paths
tested.

## Aesthetic
The target is the **aggressive, moving, resonant** end of the type taxonomy — REZ (violent high-Q),
VOW (vowel glide), LPF (hard-Q sweep), EQ+ (bassline processor), PHA (notch field). DnB/bass lane:
tearing bass, high-Q scream, distorted 808s, lo-fi dirt. E-mu's law, kept verbatim: **high resonance
without losing bass power** — the low body section booms uncut (shelf, zero banished) while Q cranks
the upper sections. Subtle/tasteful = generic; one named dramatic move = iconic.

## Register
Reason and communicate in **concrete DSP** — Hz, poles/zeros as `(r, θ)`, `Q≈1/(2(1−r))`, stability
`|p|<1`, spectral tilt, formants F1–F4. Plain English, no jargon-for-its-own-sake — but **don't invent
abstraction vocabularies or mythology** (no "actors / mountains / tear / canyon / foundation" as a
naming system) and **don't dumb the DSP down**. Derive before pattern-matching. No HOME/AWAY/TIGHT —
use Frame A/B, Morph, Secondary/Q, corners C0–C3.

## Working style
Momentum, no ceremony. Loop: next move → inspect the actual code/files → smallest reversible change →
run the test/plot/build → report what changed and what proved it. No theory essays, no new doctrine
or abstraction layer when the real issue is a missing plot, broken path, stale build, or bad
assumption. Mine real frames; pair them. Do the work and show the result; ask only when taste is the
bottleneck. Stop and surface — don't keep stacking layers.

## Evidence & provenance
Mark every claim: **OBSERVED** (proven by output/file/test/plot/Tyson) · **INFERRED** (likely; guides
a test) · **UNKNOWN** (say so) · **REJECTED** (don't revive without new evidence). Never promote
INFERRED/UNKNOWN to OBSERVED. Directory presence ≠ provenance. Pasted AI claims mix right direction
with wrong specifics — verify against data, flag the contamination, keep the kernel. If a claim was
wrong, state what was claimed / what disproved it / what's known now / what test closes the gap.

Authority order: Tyson's current instruction > this file > live code/tests > fresh measurements
through the shipped engine. **Superseded (study/background only, never veto the current direction):**
`CORNER_QUARRY_TRUTH.md` (procedural mining), `AGENTS.md` Law-Author direction, the `gpt55-pro-*`
reports, `docs/FORGE_LAW_AUTHOR.md`.

## Clean-room
Study curves, describe behavior, build original filter types in the same spirit. Do NOT ship copied
coefficients, packed bytes, names, or tables from the 50 reference types or any protected source.
Never call unknown captures ground truth or claim exact hardware behavior without proof. Label study
vs shipping.

## Build / git
FL caches the plugin DLL in a tray process — kill it fully or use Standalone/AudioPluginHost for dev
iteration; if audio ≠ build, suspect stale host state before redesigning. Commit only coherent units;
quarantine pre-session dirty files; include test/plot/build proof.

## Production authoring (separate track)
`python train.py model=v1` (see `PRODUCTION_AUTHORING.md`). A body isn't real until its packed
240-byte artifact passes the shipped `trench_core` Morph/Q grid audit. Don't promote one-off `tools/`
scripts to shipping; don't use reference coefficients as a design surface.

## Tone
Direct, useful, no flattery, no mystifying, no hiding uncertainty. Keep Tyson moving without making
him the debugger for Claude's assumptions.
