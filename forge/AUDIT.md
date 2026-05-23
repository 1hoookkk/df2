# Filter Factory — First-Principles Audit

Audit of the standalone authoring app (`forge/`, the Filter Factory) and the
`trench-core` pieces it leans on. Written to make the machinery — and the
"black magic" — apparent, then build from there.

---

## 0. What it is, in one sentence

**Capture a sound → reduce it to 6 resonances (one "corner") → set two corners
as LOW and HIGH → morph between them in the frozen E-mu packed-coefficient space
→ audition → save a cartridge.**

Everything else is plumbing around that sentence.

---

## 1. The signal path — drop to sound, every transform

Trace one dropped WAV all the way through. `file:fn` shows where each step lives.

| # | Step | Where | Rate |
|---|------|-------|------|
| 1 | Load WAV → mono f64 | `dsp::load_wav_as_mono_f64` | source SR |
| 2 | Onset detect (energy/amplitude threshold, 1 ms pre-roll) | `dsp::detect_onset` | source SR |
| 3 | Take a 100 ms window from onset | `App::load_anchor_path` | source SR |
| 4 | Condition: Hann window (+ optional 16-bit truncation) | `dsp::condition_fit_window` | source SR |
| 5 | Extract a **stylised low-Q target**: smooth away FFT chatter, preserve broad tilt, keep 3–5 major landmarks below 8 kHz, important valleys, and a small high-band teeth/scar shape | `dsp::stylized_target_from_raw` | source SR |
| 6 | **Fit a 6-section ARMA cascade**: LPC pole/valley extraction seeds candidates, then coordinate descent refines pole frequency/radius and zero frequency/radius against the stylised target | `dsp::fit_corner_arma_from_window` | source SR → 39062.5 |
| 7 | After every candidate: stabilize, conform to packable range, normalize gain, encode with `PackedCorners::from_corner_data`, decode the same corner, then score the **post-pack** response against the stylised target | `dsp::score_post_pack_candidate` | 39062.5 |
| 8 | Score the parse: weighted residual, max pack drift, impossible-notch penalty, and formant-specific error against the strongest target peaks in the formant band | `dsp::detect_formant_peaks` / `dsp::formant_peak_error` | — |
| 9 | Result is Ready / Review / Blocked. Only Ready auto-assigns; Review stays visible for slice/fitter diagnosis | `FitQuality::can_assign` | — |
| 10 | Inspect reports raw source, stylised target, fit peaks/valleys, residual, post-pack residual, max pack drift, formant error, per-stage role/frequency/radius/zero, and review/block reason | `inspect::inspect_controls` | — |
| → | Result = one **CORNER**: 6 kernel biquads `[c0..c4]` | `ExtractionResults.corner` | — |
| 11 | Two corners (LOW, HIGH) → **packed u16 minifloat** words | `minifloat::PackedCorners::from_corner_data` | — |
| 12 | **Morph**: bilinear lerp of the packed words (morph→A/B & C/D, then Q) → decoded kernel corner | `minifloat::PackedCorners::interpolate` | — |
| 13 | Audition: DF2T biquad cascade on the audio thread, run at 39062.5 via linear resampling, coefficients ramped (click-free) | `audio::Voice::sample` | device SR ↔ 39062.5 |
| 14 | Save: `compiled-v1` JSON, 4 keyframes × 12 stages (A/B duplicated into C/D) | `App::export_two_anchor_body` | — |

---

## 2. The black magic (what's actually valuable, made explicit)

1. **The morph trajectory is the product.** The lerp at step 12 happens in the
   *packed u16 grid*, not in linear coefficient space. The bounded grid is what
   keeps every in-between point stable, and the *path* a sound takes between two
   corners is the un-copyable character. The corners are the cheap part; the
   middle is the magic.
2. **Six actors carry a whole sound.** Steps 5-6 compress the source envelope
   into 6 pole-zero actors. That budget *is* the instrument — not a limitation.
3. **The packable range is a hard contract** (steps 7-8). The frozen E-mu
   mechanism can only represent coefficients in a fixed range; anything outside
   decodes to garbage/silence. Authoring that ignores this produces corrupt
   cartridges. (This was the silent-morph bug — now fixed.)
4. **Two clocks.** Authored at 39062.5 Hz (E-mu's 10 MHz ÷ 256); the sample-rate
   shift is baked into pole angles at fit time, never at runtime.

These four are the things a competitor can't copy by reading coefficients —
they're worth surfacing as the app's identity, not hiding.

---

## 3. Function audit — status

| Control / function | What it does | Status |
|---|---|---|
| `+ ADD SOUND` / LOAD FILE | File dialog → load → fit → auto-assign | **Works** |
| Drag-drop | Drops onto first empty end | **Works**, but can't target A vs B (no visible frames) |
| `CAPTURE` (DAW loopback) | `build_input_stream` on the default *output* device for WASAPI loopback | **Unverified / high-risk** — cpal loopback on an output device is fragile; likely the first thing that fails |
| Onset / 100 ms window | Auto-pick the fit region | **Works**, naive — first transient + fixed 100 ms; bad for non-steady material |
| Slice position + REFIT (Inspect) | Move the fit window, re-fit | **Works** |
| Auto-assign (spectral + formant gate) | Assign only if post-pack residual and formant lock are Ready | **Works** — Review no longer silently assigns |
| Morph rail | Lerp LOW↔HIGH | **Works** (after the gain-spread fix) |
| `PLAY` / `STOP` | Audition the morph | **Works but pink-noise only** — auditioning *your* loop is built in `audio.rs` (`set_sample`/`set_use_sample`) but never wired to the UI |
| `SAVE` | Write `compiled-v1` to `~/Documents/TRENCH/authoring_slot.json` | **Works**, but nothing consumes it yet (no player) — dead-ends |
| `RESET` | Clear everything | **Works** |
| `INSPECT` | Magnitude, z-plane, C++ export, waveform, hidden C/D corners, fit diagnostics | **Works** |
| Source overlay | Source spectrum ghost vs post-pack fit on the main stage | **Works** |
| Audio level | Fixed at 0.4 | No UI control |
| Scope buffer | Recent output samples for a live trace | Computed in `audio.rs`, **unused** |
| Corner inventory | Recall/reuse saved corners | **Not built** |
| Named actors | Surface the 6 resonances as Root/Body/Mouth/Scar/Edge/Rip | **Not built** — the magic is invisible |

---

## 4. Current fitter limits (first principles)

- **This is now a stylised post-pack ARMA fit, not final-answer LPC.** LPC only
  seeds the candidate stages; the accepted corner is the packed round-trip
  cascade that scores best against the simplified target.
- **A recording becomes a designed frame, not an FFT copy.** The styliser
  deliberately throws away chatter and preserves broad body/tilt, formant
  humps, valleys/anti-formants, upper-mid edge, and a few high teeth.
- **Program-material fitting is still envelope-only.** Without a clean impulse
  response, Forge sees the source spectrum, not a deconvolved transfer function.
  The low-Q target helps avoid raw-spectrum overfit, but analysis can still
  confuse source harmonics with true resonances.
- **The packed grid is the real ceiling.** If a good pre-pack candidate quantizes
  badly, it is rejected or downgraded because the saved result would not play
  that shape.
- **Review is not failure.** Review means the contour may be useful, but one
  diagnostic gate is not honest enough for automatic assignment. High scar
  teeth remain visible in diagnostics but do not count as required vowel
  formants.

---

## 5. Build-from-here (priority order)

1. **Diagnostics, continued** — source overlay is in; next: per-actor readout
   (the 6 poles as `freq / Q / gain`, ideally named), the onset/window drawn on
   the main stage, and the same source ghost inside Inspect. *Make the 6 actors
   visible — that's the magic surfaced.*
2. **Audit the dead/risky functions on the user's machine** — verify CAPTURE
   (loopback) actually records; wire **audition-your-own-sample** (the single
   biggest "it feels alive" win, code already present).
3. **Tighten the parse** — unify the two window selections (analyse exactly what
   the user sliced), expose order/region, consider attack-vs-steady choice.
4. **Inventory + named-actor authoring** — recall corners; edit the 6 actors
   directly as the primary surface.

---

*Frozen / not in scope to change: the `trench-core` runtime (`cascade` DF2T
math, `minifloat` packing, `cartridge` format) is patent-faithful and validated
by null test. The Forge must produce corners that live inside its contract, not
the other way around.*
