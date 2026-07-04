# LAWS.md — verdict-forged rules of the TRENCH project

A law gets minted ONE way: a verdict from Tyson's eye/ear, or a measurement,
survives contact with the build. No law from theory. Each entry: the law, the
evidence that forged it, how to apply. Violating a law = regression, not taste.

CLAUDE.md is the constitution (the engineering contract). This file is case
law — it grows every session. When a law matures, it graduates into CLAUDE.md.

---

## I. THE EYE (UI law)

**L1 — True scale or it didn't happen.**
Every UI asset is judged at its FINAL screen pixel size first (wheel ≈ 194×45).
Feature floor ~4 px: identity-carrying detail smaller than that does not exist.
*Forged:* the pitch wheel passed 12 blowup contact sheets and was rejected on
sight in the live build, unturned (2026-07-03).

**L2 — The funk is the design.**
Scale-native artifacts (the GLB sculpt's melted chunky fins, born from an 11px
screenshot) are the reason an asset reads at tiny size. Never "clean up" an
asset that works; cleanliness authored at render scale dies at screen scale.
*Forged:* six synthesized wheels (procedural 3D, drawn 2D ×3, resampled real
frame) all lost to the funky sculpt (2026-07-03).

**L3 — Contact sheet → verdict → install. In that order, always.**
Nothing overwrites a runtime asset or ships in a build before the eye approves
the contact artifact (true-scale cell first, then blowup, then a drag GIF for
motion objects).
*Forged:* documented in three prior AI failure reports; violated and re-proven
the hard way in the same night.

**L4 — Measure the art, never trust a rect.**
Layout rects come from measuring the actual panel art (lum thresholds at the
actual openings) — the two wells genuinely differ (98 vs 106 px tall). "It
doesn't sit right" is a measurement bug until proven otherwise.
*Forged:* every seating complaint traced to rects spanning the outer bezel
instead of the inner openings (2026-07-03).

**L5 — Light behaves or it leaves.**
Glow is embedded and occluded by geometry (band through the fin gaps, X3 law:
dark at rest, travels with value, broken by ribs). Any glow that reads as a
painted layer, a stripe, needles, or "stuck progress at rest" is wrong.
*Forged:* verdict chain — "glow sucks" (needles), "pasted on" (wash),
"red when the bar isn't progressing" (static ember), "more like a band" (final).

**L6 — One physical object.**
No fake layers: no painted seats, boxes, bars, or shadows that read as separate
graphic objects. The panel art owns material and bezel; code draws ink and
light only. (Constitutional — CLAUDE.md §0.0/§0.1.5 — restated here because
three different agents have violated it three different ways.)

## II. THE EAR (DSP law)

**L7 — The verification gradient points the finger.**
When something feels wrong, suspect the LEAST-verified subsystem first. The
filters were the most-verified thing in the project and were innocent; the
resampler nobody had ever null-tested was guilty.
*Forged:* "what if it's not the filters" → island convicted, filters cleared
(2026-07-04).

**L8 — Null-test or it isn't real.**
A reverse-engineered or rebuilt stage earns "real" by nulling against its
reference (QSound RE: −30 dB; island rebuild: acceptance test with measured
spurs/flatness/latency). Feelings don't certify DSP; residuals do.

**L9 — Dynamics are sacred.**
Any always-on stage that levels program dynamics (input range in >> output
range out) is a defect, not character. Character = nonlinearity + ducking
that BREATHES with the material. The ladder test (−24…0 dBFS in, RMS out) is
the detector: a flat output line is a conviction.
*Forged:* the awake chain ironed 24 dB of input to 0.6 dB out; that flatness
IS the "sound isn't there" feeling (2026-07-04).

**L10 — Voice on real material only.**
No voicing/A-B decision on test tones or pink noise — real breaks, bass,
mixes, loudness-matched. Test signals measure; music decides.
*Forged:* Tyson couldn't pick from synthetic hits ("honestly i don't know");
picked instantly on a real break ("I like 3") (2026-07-04).

**L11 — Audition-render voicing (current):** slam 0.15 + AGC cut cap 8 dB,
never the old awake chain (agc 4.0 + desk-slam 0.6 = brick-wall leveler).
*Forged:* Tyson's ear on DL_Classic Break, loudness-matched A/B (2026-07-04).

**L12 — Latency is reported or it's a bug.**
Any stage that delays audio tells the host exactly how much (measured, not
estimated — the test checks reported vs impulse-measured within samples).
*Forged:* the island hid 10.8 ms → silent comb filtering in every parallel
route the product was ever demoed in (2026-07-04).

## III. THE PROCESS (how sessions work)

**L13 — One verdict per change.** Never stack tweaks and ask which helped.
(Constitutional; still the most-violated law in the archive.)

**L14 — Two failures = change METHOD, not parameters.**
Parameter iteration past two failed verdicts is thrash. Change the method,
the tool, or the question.
*Forged:* seed doc law; proven again by teeth→grille→wires (2026-07-03).

**L15 — Get the failure in words before generating.**
One sentence from the director ("it's the corners, not the edges") outvalues
ten render passes. When a verdict is only "it's not right," extract the
dimension before touching anything.

**L16 — Decisions audit before execution.**
Before a build phase, a fresh context red-teams the plan (ruler-first: validate
the gates against known-good before trusting any gate). A finding that kills a
body before it's built is the win.
*Forged:* the ship-bodies audit prompt exists because confident wrong bodies
are the most expensive failure available (2026-07-03).

**L17 — Failure docs are trophies.**
Every failed campaign ends with a signed, dated, specific post-mortem next to
its predecessors. The wall is why the wheel gets harder to fail at.

**L18 — Prove the agent looked.**
Any delegated visual task starts with a mandatory proof-of-looking gate: the
agent describes the reference in specifics before proceeding, and every later
claim must cite it. No description, no session.
*Forged:* Gemini passed it and produced the convergent verdict; every agent
before the gate existed pattern-matched instead of looking (2026-07-04).

**L19 — Orientation must be screamed.**
The wheel is a horizontal thumbwheel; ribs and glow travel LEFT-RIGHT. Every
agent defaults to scroll-wheel/vertical-drum regardless of context. State it
first, in caps, and require it echoed back.
*Forged:* four different models made the identical error (documented 06-11,
06-14, 06-24, 07-03).

## IV. THE PRODUCT

**L20 — Ship builds are clean builds.**
Release binaries compile WITHOUT diagnostics: no rig, no lab, no dev roster,
no scanned bodies. The whitelist is explicit; a preset that isn't baked is a
preset that silently fails (Lucifers Q, 2026-07-03).

**L21 — The real presets never ship publicly.**
P2K bodies are the teacher manifold: private demos only. The public roster is
authored on measured wells with the copy-risk gate (~6 dB clear of all 50).

**L22 — Character stages must be defeatable in probes.**
Every nonlinear/level stage gets a debug toggle (default = stock, bit-exact)
so the chain can be decomposed when the sound drifts. A chain you can't take
apart is a chain you can't fix.
*Forged:* the AGC/slam/saturator decomposition was only possible because the
knobs were added mid-investigation (2026-07-04).

---

## Open cases (laws waiting to be forged)

- **The plugin-chain leveler** — shipping config levels ~13.5 dB; survives
  slam-0/sat-off/AGC-cap individually. Culprit unidentified. The law that
  comes out of this one sets TRENCH's shipped dynamics contract.
- **Per-voice context** — hardware struck filters per-note with envelopes; we
  stream. If layers keep nulling clean and it still isn't "there," the law
  will be about per-hit behavior as a product feature.
- **HiDPI** — no law yet; nobody has verified 125/150/200% in a real host.
