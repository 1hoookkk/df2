# Filter Designer — UX spec

`forge-web/filter-designer.html`, served by `python tools/forge_author_server.py 8141`.

**Contexts (in priority order):**
1. **Internal dev tool** — Tyson authoring production bodies; the only judging surface.
2. **On camera** — Tyson records himself using it (Instagram Reels / Shorts / TikTok,
   mostly 9:16 vertical crops). The tool's look IS marketing material.
3. **Pipeline demo** — the recorded arc runs designer → KEEP → plugin (Forge Audition
   slot hot-reload) → FL Studio. Every step must be visually legible to a viewer.

## Design principles

- **Textbook DSP labels only.** Magnitude response, biquad section, f_c, Q₀/Q₁,
  peaking EQ, notch, formants F1/F2, modal frequencies. No invented metaphors.
- **The magnitude response plot is the hero.** Biggest element, always engine-true
  (|H| computed from the same packed words the plugin runs; 0.0000 dB match proven).
- **Engine-true or absent.** No feature may display anything the shipped engine
  doesn't produce. Verification through `trench_core` before a feature ships.
- **One screen.** No scrolling during a take. 920 px column today; record mode (E9)
  reflows for vertical crop.
- **Every keep is auditable.** KEEP = compile → null vs DLL → 17×17 stability audit
  → bank artifacts. Failure states must be visible and honest on camera.

## Current state (shipped, verified)

| area | feature |
|---|---|
| plot | live \|H\| dB vs log f; frame A/B endpoint ghosts (dashed blue/orange); engine-exact |
| morph/Q | sliders + hands-free triangle sweep (4 s period); Q axis interpolates Q₀→Q₁ geometrically |
| sections | 6 biquads: type, f_c A/B, gain, Q₀, Q₁; checkbox enable |
| value boxes | drag both axes (f_c 1 oct/96 px log, gain 1 dB/6 px, Q log), shift = fine, wheel = grid step, click = type; fill bars show position in range |
| quantization | f_c → measured-resonance table, or 12-TET in selected key/scale (peaking + bandpass only), or off |
| generators | seeds (8, level-calibrated); vowel formant pair F1/F2 (Peterson-Barney + Klatt BW); modal series (tube harmonics, inharmonic bar/plate/bell ratios × f0); LPC formant fit from audio file |
| audition | source (saw/noise/808/voice) through AGC → saturation → QSound; drive control; level meter |
| bank | KEEP: compile_body_typed null vs browser WASM bytes → 17×17 audit → desk/bank/v1/ (.body240 + cart + png + BANK.md row) → Documents/TRENCH/bodies/ + live Forge Audition slot. KILL → desk/KILLS.md |
| persistence | autosave cards to localStorage; restore on load |

## Enhancements

### E1 — Real-time spectrum analyzer (tier 1)
Post-chain output spectrum rendered behind the magnitude response; optional input
(pre-filter) spectrum as a dimmer layer.
- FFT 4096, Hann, ~30 fps, exponential decay ≈ 0.85/frame; log-f remap to the plot's
  axis; ~−90..0 dBFS mapped to plot height.
- Filled area, low alpha (≤ .25) under the |H| line. The response curve stays the
  brightest object (hero rule).
- Toggle in the curve panel caption. ON by default — it's the money shot on camera:
  source harmonics visibly pushed through notches during a sweep.
- Verify: sine at f → single ridge at f; ridge attenuates by the plotted |H(f)| dB
  within ±1 dB.

### E2 — WebMIDI control (tier 1)
Physical knobs for the on-camera workflow (hands on hardware > mouse).
- Web MIDI API; "MIDI learn": click a control, turn a knob, bound. Map targets:
  morph, Q axis, drive, selected section's f_c A, f_c B, gain, Q₀, Q₁.
- Mapping persisted to localStorage; indicator chip when a device is connected.
- CC 0–127 → parameter range via the same log/linear laws as drag.
- Verify: scripted MIDI message moves the slider and repacks (plot changes).

### E3 — Undo/redo (tier 1)
- Snapshot the 6-card state on every committed change (change event, not per drag
  frame); ring buffer ≥ 100 states in memory, persisted tail in localStorage.
- Ctrl+Z / Ctrl+Shift+Z. Status line shows depth ("undo 12/40").
- Verify: 50 random edits, 50 undos → byte-identical packed body to start.

### E4 — Loudness-matched audition (tier 1)
Constant integrated loudness (ITU-R BS.1770 / LUFS) on the audition output so a Q or
gain increase can't win keep/kill by being louder.
- Short-term LUFS estimate in the worklet; slow AGC (≥ 400 ms window) trimming output
  to −16 LUFS target; toggle ("level match") for when raw level IS the point.
- Verify: +12 dB section gain change settles back to target ±1 LU within 2 s.

### E5 — Vector fitting capture (tier 2)
Upgrade the audio-capture path from all-pole LPC to full rational fit.
- Gustavsen–Semlyen vector fitting on the Welch PSD of the dropped audio → stable
  poles AND zeros, order ≤ 12 → 6 general SOS.
- Server-side (`/fit` gains `method: "vectfit"`); falls back to LPC.
- Depends on E8 (general SOS rows) to receive independent zeros.
- Verify: fit a known synthetic H(z) (random stable 12th-order), reconstruction
  error < 1 dB RMS over 40 Hz–16 kHz.

### E6 — Draw-the-target fit (tier 2)
Sketch a magnitude curve on the plot; solve sections to realize it.
- Pencil mode per frame (draw A, draw B); freehand polyline → smoothed target.
- Solve: weighted least squares over log-f grid (AAA rational approximation or
  Levenberg–Marquardt on SOS parameters), stability constrained (|p| < 0.9992).
- Show residual honestly: target as ghost line + RMS error in dB in the caption.
- Verify: draw a curve matching a known body's |H| → solver returns ≤ 2 dB RMS.

### E7 — Morph-interior optimization (tier 3, own project)
Choose the emergent middle instead of discovering it.
- The interpolation law is fixed and known: linear on log-encoded (minifloat)
  coefficient words, C(x) = C_A + x(C_B − C_A). Implement it differentiably
  (straight-through estimator over the minifloat quantizer).
- Pose: targets at morph = {0, 0.5, 1} (each a drawn or referenced |H|) → gradient
  solve for frames A and B jointly.
- Out of designer scope until the bank has entries (this is the trap if built early).
- Verify: 3-target synthetic problem reaches < 3 dB RMS at all three morph points
  through the REAL packed runtime (not the surrogate).

### E8 — General SOS row mode (tier 2; unlocked by the Talking Hedz analysis)
The 7 RBJ prototypes weld the zero pair to the pole pair. Real P2K sections place
them independently (pole pair (θ_p, r_p), zero pair (θ_z, r_z) unrelated).
- Per-row toggle: "general SOS" expands the row to pole f_c A/B + Q₀/Q₁ AND zero
  f_c A/B + depth (dB). Maps to the EXISTING `compile_body` 168-param path
  (`packWithCore` in pack-core.js — already byte-nulled vs the DLL).
- KEEP must route through `compile_body` when any row is general (null check stays).
- Verify: a general-SOS body's browser bytes == DLL `compile_body` bytes; 17×17 audit.

### E9 — Record mode (camera)
One keypress (`R`) reflows for capture:
- Plot height ×1.6; font 13 → 15 px; fill bars brighten; status line hides.
- 9:16 safe area: column narrows to ~520 px, panels stack with the plot on top,
  morph/Q sliders directly beneath (the two things a viewer must see move).
- Cursor halo (CSS) so the pointer reads at phone size; slider thumbs enlarged.
- Sweep period selectable 2/4/8 s (2 s reads better in a 15-second reel).
- No layout shift during interaction (no reflow on status text changes).
- Verify: 1080×1920 screenshot — all six rows + plot + transport legible.

### E10 — Pipeline legibility on camera
The recorded arc: seed → shape → sweep → KEEP → plugin plays it → FL.
- KEEP success state becomes a visible moment: brief full-card flash with the body
  name + "PASS · max |p| 0.99" (1.5 s, then back). No modal, no click-through.
- The Forge Audition slot already hot-reloads in the plugin — document the two-window
  OBS layout (designer left, FL with TRENCH right) in this file once first recorded.
- A `?body=<slug>` URL param to reload any banked body for retakes.

## Sequencing

1. E1 + E2 + E3 (one session; all client-side except nothing)
2. E4 (worklet change, then re-verify meter behavior)
3. E8 → E5 → E6 (each unlocks the next; E8 first because it's free at the compiler)
4. E9 + E10 before the first recorded session
5. E7 as its own project once `desk/bank/v1/BANK.md` has ≥ 3 rows

Every enhancement lands with its verification step run and shown, same as everything
else in this repo: no claim without engine output.
