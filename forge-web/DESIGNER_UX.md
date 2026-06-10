# Filter Designer — UX spec (v2: the plot IS the editor)

`forge-web/filter-designer.html` (current, typed-card surface) → `forge-web/plot-editor.html`
(v2, this spec). Served by `python tools/forge_author_server.py 8141`.

**Contexts (in priority order):**
1. **Internal dev tool** — Tyson authoring production bodies; the judging surface.
2. **On camera** — short-form recordings (9:16 Reels/Shorts). The tool's look is marketing.
3. **Pipeline demo** — designer → KEEP → plugin (Forge Audition hot-reload) → FL Studio.

## Evidence state (verified 2026-06-10, all OBSERVED by execution)

- `packed.js` (browser plot) vs `trench_core packed_probe` (shipped DLL):
  **max |diff| = 0.000000 dB** over 6 (morph,Q) points × 200 freqs.
  Harness: `python tools/plot_engine_null.py` (PASS gate < 1e-4 dB). This upgrades the
  previously-INFERRED `plot == engine` claim (PROJECT_STATE.md §5.1) to OBSERVED.
- WASM `forge_pack_typed` == DLL `compile_body_typed`: byte-identical (0 diff).
- WASM `forge_pack_params` (168-param pole/zero path) == DLL `compile_body`: byte-exact.
- Audition chain in WASM = filter → AGC → Mackie saturation, `SpatialMode::Off`.
  **This MATCHES the shipped plugin's default** (`PluginProcessor.cpp`: `kSpatialOff`;
  QSound engages only via the 5D toggle). Do NOT enable QSound in the audition without
  also defaulting it in the plugin — the judge chain must equal the product chain.
  (Root CLAUDE.md's "QSound on by default" line is stale vs live code — flagged.)

## v2 architecture (Tyson 2026-06-10)

**The magnitude response plot is the editor, not a display.** Direct manipulation;
the table is demoted to an inspector for the selected section.

```
+--------------------------------------------------------------+
| MAIN CANVAS  |H(f)| dB vs log f                              |
|   - spectrum analyzer behind (post-chain FFT, low alpha)     |
|   - frame A ghost (blue dashed) + frame B ghost (orange)     |
|   - live morph/Q trace (green, brightest — hero rule)        |
|   - X handles = pole pairs   O handles = zero pairs          |
|     blue X/O sit on frame A, orange X/O on frame B           |
+--------------------------------------------------------------+
| INSPECTOR (selected section only)                            |
|   pole: f Hz · radius r     zero: f Hz · radius r_z          |
|   gain · enabled · which frame the handle belongs to         |
|   SECTION STRIP: per-section mini plot |Hₖ(f)| at current    |
|   morph/Q (the cascade = sum of these in dB); click selects  |
+--------------------------------------------------------------+
| TRANSPORT                                                    |
|   Morph — Q — sweep — play — source — drive — meter          |
|   name — KEEP (audit verdict inline) — KILL                  |
+--------------------------------------------------------------+
```

**Zero-handle defaults (measured, 2026-06-10, all 50 reference bodies / 193 sections):**
- Under Morph: median pole-pair travel 1.27 oct vs zero-pair 0.73 oct; 20% of zero
  pairs fully parked (<0.15 oct) vs 6% of poles. Anchor-grid extremes: cruz_pusher
  5/6 zeros parked + 3.0 oct leader, fuzzi_face 5/6, dj_alkaline 4/6.
- Under the Q axis: median pole radius +0.0061 (→ rim, r≈0.999 hot), median zero
  radius change **+0.0000 — the numerator is Q-invariant.** Q is a pole-radius-only
  control in the reference set.
- Therefore: **O handles boot PARKED** (frame A = frame B, linked, one handle shown;
  explicit unlink to make a zero travel) and **never respond to the Q axis**.
  X handles boot free (independent A/B). The dominant reference construction —
  a pole trajectory crossing a stationary transmission zero — is the zero-effort
  gesture; a traveling zero is a deliberate act.

**Morph×Q surface map (steal from the atlas viewer / bench):**
An N×N (5×5 default) heat grid of max |H| dB over the (morph, Q) surface, computed
through the packed runtime. Click a cell → jump morph/Q there; the live trace and
audio follow. Reading it:
- **Dark cell amid bright** = interior pole-zero cancellation — a (morph,Q) point
  where a pole trajectory sits ON a transmission zero (observed: radio_craze, one
  black cell mid-surface; lucifer_s_q bottom-left).
- **Dark column/row** = an endpoint frame that collapses (dj_alkaline: morph=100%
  column black — frame B is the quiet end of the gesture).
- **Gradient toward a corner** = where the bloom lives (millennium: brightens
  toward high Q).
This is the map of the emergent interior — events invisible from the two endpoint
curves. Recompute lazily (rAF idle), 17×17 on demand for the KEEP audit (same grid).

**Interaction grammar (Pro-Q lineage, two-frame extension):**
- Drag X horizontally = pole frequency; vertically = pole radius
  (r mapped so handle height tracks the local |H| contribution).
- Drag O horizontally = zero frequency; vertically = zero radius r_z
  (deeper notch as r_z → 1).
- Each section owns 2 X and 2 O handles (frame A pair, frame B pair).
  Section index is the morph pairing — A↔B handles of one section are linked visually.
- Wheel on a handle = the orthogonal fine axis (X: radius, O: r_z).
- Click selects → inspector shows numbers; double-click a number to type.
- Quantize modes apply to handle drags: measured-resonance table / 12-TET in key / off.

**Naming (heritage, 2026-06-10):** the two coefficient frames are the **low morph frame**
and **high morph frame** — E-mu's own terms (Dillusion Peak/Shelf Morph tutorial). The
morph knob is the filter's cutoff-like control sweeping low→high. Supersedes "Frame A/B".

**Section model (general SOS — first-class zeros, foundation of v2):**
Every section = pole pair + zero pair, independently placed:
`H_k(z) = g·(1 − 2 r_z cosω_z z⁻¹ + r_z² z⁻²) / (1 − 2 r_p cosω_p z⁻¹ + r_p² z⁻²)`
- **Per-frame gain (g_low ≠ g_high) is REQUIRED**, not optional: the documented
  Peak/Shelf reece patch rides −24 dB (low frame) → +1.5 dB (high frame) — a 25.5 dB
  level gesture inside the sweep. The 168-param path already carries gain per corner;
  the v2 inspector exposes it per frame. (The v1 typed card's single shared gain is a
  known limitation.)
- **Section vocabulary is sufficient (OBSERVED):** stage-level comparison of iconic
  presets vs the simple templates (dev/tmp/p2k_template_foundation_stages) shows ZERO
  exact packed-row reuse but 6–11 response-equivalent stages (<1 dB RMS) per iconic
  body — same standard second-order shapes, freshly compiled per preset. Iconic-ness
  lives in placement, pairing, per-frame gain, and pole-through-zero interactions,
  not in exotic section types.
- Maps to the EXISTING `compile_body` 168-param path: per corner per section
  `[on, pole_hz, pole_r, gain, zero_on, zero_hz, zero_depth]`.
- **`zero_depth` is the zero-pair RADIUS r_z, a 0..MAX_RADIUS scalar — NOT dB**
  (`compiler.rs stage_biquad`: `nb1 = −2·r_z·cosω_z`). The UI may DISPLAY depth in dB
  but must convert before packing.
- **Zero-mandatory:** `stage_biquad`'s all-pole branch rolls off −12 dB/oct (the known
  corner-collapse bug). The v2 surface always places a zero per section (`zero_on=1`);
  "no notch" = park the zero near the pole (masked) or at low r_z, never `zero_on=0`.
- Corners from the four handle sets: C0=A·Q₀, C1=B·Q₀, C2=A·Q₁, C3=B·Q₁ where Q axis
  scales pole radius (per-section r at Q₀ and Q₁).
- KEEP routes through `/keep` with the 168-param payload; server recompiles via DLL
  `compile_body`, nulls vs browser `packWithCore` bytes, 17×17 audit, bank artifacts.

**Generators (kept from v1, write into the section model):**
seeds · vowel formant pairs (Peterson-Barney F1/F2, Q from Klatt BW) · modal series
(tube harmonics / inharmonic ratios × f0) · LPC formant fit. All set pole pairs;
zeros default masked (on the pole) until dragged away — the unmask gesture.

## Enhancements (resequenced 2026-06-10)

| # | item | status |
|---|---|---|
| E8 | general SOS sections (first-class zeros) | **PREREQUISITE — the v2 section model** |
| E11 | plot-as-editor handles (X/O, two-frame) | **PREREQUISITE — the v2 surface** |
| E1 | spectrum analyzer behind the plot | v2 launch feature (the money shot) |
| E3 | undo/redo (snapshot per committed edit) | v2 launch feature |
| E2 | WebMIDI (morph/Q/drive + selected handle) | after v2 ships |
| E4 | loudness-matched audition (BS.1770) | after v2 ships |
| E5 | vector fitting capture (poles AND zeros) | after E8 (needs independent zeros) |
| E6 | draw-the-target fit | after E5 |
| E9 | record mode (9:16 reflow, big handles) | before first shoot |
| E10 | pipeline legibility (KEEP moment, ?body= param) | before first shoot |
| E7 | morph-interior optimization (differentiable) | own project; bank ≥ 3 entries first |

Verification criteria per item as in v1 of this spec; in addition every v2 keep runs
the compile_body byte-null and `tools/plot_engine_null.py` stays green in any session
that touches packed.js or the compilers.

## Boot behavior

Fresh default template every time (no autosave restore — Tyson 2026-06-10).
Undo (E3) provides in-session safety; the bank provides permanence.
