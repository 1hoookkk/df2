# SHIP TODO — what actually gets df2 to a shippable v1

Ordered by leverage. The #1 gap is **content** (iconic original presets), not code.
Updated 2026-05-30 (overnight).

## 1. CONTENT — the real blocker (this is what you said you need)
- [ ] **Author 4+ iconic original bodies** worth $99–149. Two reliable paths proven:
  - **Vowels (Path A):** Klatt formant journeys + cranked radius + slot-registered
    movers (ah→ay→ee works). Genuinely original.
  - **Synths/bass (Path C):** splice/transpose iconic ROM frames into original
    constellations (iconic genetic material → iconic result). Drive via SLAM.
  - The v1 LINEAR engine can't *scream* (needs in-loop saturation — see §5); for now
    the synth character comes from the constellation + AGC/SLAM drive, like the refs.
- [ ] Ear-curate the overnight audition batch → mark KEEP, bake keepers into the roster.
- [ ] Fill the v1 four: Speaker Knockerz · Aluminum Siding · Small Talk · Cul-De-Sac
  (or rename to whatever the keepers become).

## 2. FX COMPLETENESS — mandatory for a DAW insert (cheap, high-impact)
- [ ] **Parameter smoothing** (1-pole on Morph/Q/output) — without it, DAW automation
  zippers and clicks. Non-negotiable before ship.
- [ ] **Wet/dry parallel mix** — a destructive filter needs the dry blend. Most-used
  control on this kind of FX. Add to params + UI.
- [ ] **Stereo** — confirm true L/R processing (two cascades), not mono-summed.
- [ ] *(opt-in, off by default)* Envelope follower → Morph/Q; side-chain in; synced LFO.
  These make it react on arbitrary audio. Transparent at defaults.

## 3. UI
- [x] Faceplate `df2_brushed` measured + wired (invisible well sliders + Morph/Q readouts).
- [x] Editor a touch bigger (divisor 4.0 → 3.4).
- [ ] Confirm faceplate seats correctly in a host at the new size; check readout legibility.
- [ ] Decide final chassis (df2_brushed vs df2_canonical) and lock it.

## 4. CLEANUP / REPO
- [ ] Delete dormant `Cvsd` + `SpatialMode::Trench` from trench-core, re-run null gate.
- [ ] Ear-verify the resampler fix in Standalone/AudioPluginHost (unit-verified only).
- [ ] Commit the in-flight working tree (editor, faceplate variant, layout) — currently
  dirty/uncommitted. Confirm provenance first.
- [ ] Gut CODEMAP §dead files + the 12 MB zip.

## 5. ENGINE v2 (bigger track — only if the pivot is greenlit)
- [ ] In-loop `tanh` saturation in a ZDF/TPT filter = the scream a linear filter can't
  make (prototype proved it: `dev/tmp/zdf_proto/scream_*.wav`). 64-bit + 4× oversample.
- [ ] This **retires X3 null parity** and requires re-deriving every body. From-scratch
  DSP project — do NOT start without an explicit go; v1 ships first.

## SHIP GATE (don't ship until)
- [ ] 4 bodies baked, each auditioned across the SLAM drive ladder on real 808/reese.
- [ ] Stability/null pass on every shipped body.
- [ ] Automation smooth (no zipper), wet/dry present, stereo correct.
- [ ] Faceplate seats in a real host (not just Standalone).
