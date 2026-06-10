# FORGE — Design Brief v2
### The authoring surface for packed Z-plane bodies. Single source for the visual mockup.

Supersedes brief v1 and the Tier-3 sections of `DESIGNER_UX.md` (layout, color, hierarchy, glyphs). Tier-1 invariants and Tier-2 measured defaults from that spec are absorbed here unchanged and are cited as constraints, not restated as design opinions. Everything below binds to verified code paths: `packed.js` (plot==engine, 0.000000 dB null vs `trench_core`), the 168-param `compile_body` path, the 17×17 packed audit, and `/keep`.

---

## 1. The object the UI renders

A body is six second-order sections. Each section, per corner: `[on, pole_hz, pole_r, gain, zero_on, zero_hz, zero_depth]`, where `zero_depth` is the zero-pair radius r_z (0..MAX_RADIUS, not dB — UI displays dB, converts before packing). Four corners: C0 = low·Q0, C1 = high·Q0, C2 = low·Q1, C3 = high·Q1. The runtime interpolates morph-first then the secondary axis, linearly on log-encoded coefficient words. Corners are bit-exact to any continuous model; interiors diverge from continuous predictions by up to ~20 dB. Consequence: every curve on screen is computed through the packed interpolator, never from root-domain math. The plot is the engine or it is nothing.

Hard limits (format + compiler, never softened in UI): poles r_p ∈ [0.5, 0.9992]; zeros r_z ∈ [0, 0.9995]; conjugate pairs only; per-frame gain packed linear [0.05, 4.0] — displayed −26.0 to +12.0 dB; `zero_on = 1` always (the all-pole branch rolls off −12 dB/oct — corner-collapse bug; "no notch" = zero masked on the pole or at low r_z).

Measured corridor (50 reference bodies, 193 sections): maximum |H| across reference surfaces measures 33–44 dB. Under morph, median pole travel 1.27 oct vs zero travel 0.73 oct; 20% of zeros fully parked vs 6% of poles. Under the secondary axis, median pole radius change +0.0061 (to the rim, r ≈ 0.999), median zero radius change +0.0000 — the numerator is secondary-invariant across the entire reference set. These numbers set defaults and scales throughout this document; no constant below is invented.

---

## 2. Interaction model

**Edit from anywhere; weights visible. Notches park until split. Audition in motion. Audit is ambient. Bank is the only terminal verb.**

There are no edit modes and no frame-arming gate. An edit at surface point (x, y) distributes to the four corners by the bilinear basis (1−x)(1−y), x(1−y), (1−x)y, xy. Docking the playhead at a morph extreme is the special case where one pair of weights goes to 1 — clean single-frame editing falls out of the same rule. During any non-docked drag, the live corner weights are displayed (the two dock caps and the Sharpen extremes glow in proportion to the basis), so the author always sees where the gesture lands. Center authoring (§7) is the equal-weight case plus per-section deltas.

The playhead is always audible through the shipped chain (filter → AGC → Mackie saturation, SpatialMode::Off — identical to the plugin default). Ride keeps morph moving by default. The audit grid recomputes continuously in idle time; KEEP is a lit lamp, not a request.

---

## 3. The surfaces

One shared log-frequency axis, 20 Hz–20 kHz, fixed framing (no persistent zoom; held-key magnifier only). Two stacked surfaces share it.

**The Curve.** |H(f)| at the current (morph, sharpen) point, computed by `packed.js` per frame. Fixed dB scale **−36 to +48** — sized so the 44 dB corridor ceiling and a −26 dB frame-gain floor both fit without rescaling. The measured corridor is drawn as a band: hairlines at +33 and +44 dB, labeled CORRIDOR at the right edge in label type. The audit's actual failure threshold (taken from the audit config, never hardcoded in UI) renders as a third, slightly brighter rule. The Curve is the editing surface: handles live here.

**The Field.** Frequency × morph, morph 0 at bottom to 1 at top, rendered at the current sharpen value: ~240 morph slices × ~480 log-spaced bins, each slice run through the packed interpolator (log-word path, clamps and all), magnitude mapped to the calibrated heat ramp (§16). Recompute on gesture frames, debounced to display rate; full sweep is the per-frame Curve evaluation in a loop — a few ms in a worker. The Field is where the reference fingerprints become visible: an always-on resonator reads as a uniformly bright field; a frame that collapses reads as a black morph-extreme column; a corner bloom reads as a gradient; a pole trajectory crossing a parked zero reads as an isolated dark cell. Identity lives in the journey; the Field is the identity portrait — banked bodies thumbnail as Fields, not curves.

**Heat is absolute.** The ramp is calibrated to the corridor — the same dB always maps to the same luminance, across all bodies, forever. Never autoscaled. A timid body must *look* cold next to lucifer_s_q.

**The headroom spine.** 20 px gutter on the Field's left edge: per-slice max |H| against the corridor band and audit threshold. Interior gain events show as a flare at an exact morph altitude before the audit names them.

**The navigator.** The morph×sharpen scalar map (max |H| per cell) survives from `DESIGNER_UX.md`, demoted to a small square in the right rail: 5×5 lazy, refined toward 17×17 in idle — the same grid the audit consumes. Click a cell to jump (morph, sharpen); audit failures plot here and on the spine/Field at their coordinates. It is the atlas view, not the perception surface.

**The spectrum layer.** Post-chain FFT as a heat-tinted fill under the Curve's truth line. On during audition and record; auto-suppressed while a handle is held, so source energy is never read as filter shape. Never drawn in the Field.

---

## 4. Handles and gestures

Handles are the realized response features at the current (morph, sharpen) point — no X/O glyphs, no resident dual-frame clouds. Selection reveals structure: the section's low-frame and high-frame feature positions and the path between them, as marks on the Curve and a highlighted trajectory thread in the Field.

| Gesture | Target | Parameter | Range / behavior |
|---|---|---|---|
| Drag peak horizontally | pole pair | `pole_hz` | rails apply (§6); bilinear-distributed to corners |
| Drag peak vertically | pole pair | `pole_r` | hard stop at 0.9992 with rim hatch — no rubber-banding |
| Drag notch horizontally | zero pair | `zero_hz` | parked zeros move in both frames at once |
| Drag notch vertically | zero pair | `zero_depth` (r_z) | displayed dB, packed as radius; stop at 0.9995 |
| Selected feature: gain stem, vertical | section | per-frame `gain` | −26.0…+12.0 dB; other frame's stem ghosted behind, so the gain *gesture* (e.g. the documented −24 → +1.5 dB ride) is readable as a pair |
| Hold + split a parked notch | zero pair | unlink low/high `zero_hz`/`zero_depth` | the deliberate act; until then one handle, frame-linked |
| Scroll / shift on held handle | same | fine adjust | 1/10 rail step |
| Double-click any shown value | same | typed entry | dev affordance; stays |
| Drag playhead / Field | — | morph | Ride resumes on release |
| Sharpen rail | per-section `pole_r` at Q1 corners | secondary axis | numerator untouched (measured default); Field re-sweeps live |

Topology labels (`resonant SOS`, `pole-zero resonator`, `near-allpass`, …) come from the locked classifier in `capture_compiler.py` (pole bands rim ≥0.995 / resonant ≥0.930 / frame ≥0.750; zero bands rim_notch ≥0.985 / antiresonant ≥0.900 / counterweight ≥0.700; placement local ≤0.35 oct, remote >1.25 oct). They appear in the inspector as readback only — derived, never chosen, never a quality judgment.

---

## 5. Defaults and overrides (the measured layer)

Zeros boot parked: low frame = high frame, linked, one handle. Zeros boot secondary-invariant. Both are Tier-2 measured defaults — one gesture to override, never a cage. A secondary-responsive zero is in-format, stable, and territory no reference used: the inspector exposes it as an explicit toggle flagged OFF-CORRIDOR (informational tint, not fault red). Pole radius is shared across frames per secondary endpoint by default; per-frame radius is the inspector override. Sections carry a visible anchor/voice state on their handles (§7): anchors take edits into M only (Δ = 0 — scaffold shelves and parked zeros boot as anchors), voices carry motion.

---

## 6. Rails

Two verified quantize grids constrain handle drags: the measured-resonance table (every drop lands on a physically measured resonance) and 12-TET-in-key (peaks land within ±1.3 cents of scale notes — in tune with the producer's track). Rails render as felt detents with transient tick marks that exist only while the finger is down; never resident gridlines. Default rail: measured-resonance table. Key selection for the 12-TET rail lives in the summonable source/setup strip, not on the main surface. Per the anchoring rule, rails constrain motion as well as position: Δ paths in center authoring step along the same grids — formant deltas along the vowel chart, pitched movers along the in-key grid, everything else along the resonance table. Rails and lawful paths are one mechanism.

---

## 7. Center authoring

Per section, in root domain: **M** (home sound at m50/q50 — pole f/r, zero f/r, gain), **Δmorph** (the move), **ΔQ** (the bloom). Corners derive as C(x,y) = M + (2x−1)·Δmorph + (2y−1)·ΔQ, compiled through the existing 168-param path. Anchors hold Δ = 0; voices move along lawful paths (§6).

Honesty requirement, always on while center authoring is live: the engine interpolates log-encoded words, so the realized m50/q50 response ≠ the authored M. The authored-M target renders as a thin ghost against the realized packed curve with the residual printed in dB next to the playhead (e.g. `M residual 3.2 dB`). If the residual matters, the closed-loop corner correction is offered as an explicit action — previously demonstrated at 2.65 dB across a full surface, but that run used the rogue encoder: **re-verify through `compile_body` before the button ships.** Until verified, the action is absent, not disabled.

---

## 8. Routes

Section re-pairing ships. The cascade commutes within a corner, the runtime pairs strictly by index, and the engine is floating-point — so permuting which low-frame section marries which high-frame section is a legal authoring-time operation applied before packing, leaving both endpoint responses untouched while transforming the interior. Long-press the morph axis: the Field dims to its six trajectory threads; drag a thread's top terminus onto a different high-frame feature; the Field previews the re-paired interior live through the packed runtime before commit. The ambient audit re-judges on commit. This is the only operation whose sole output is the interior, which is why it gets a mode and everything else doesn't.

---

## 9. Boot: the iron and the generators

Cold open is the fresh neutral iron, every time — no autosave restore (locked decision; undo is in-session safety, the bank is permanence). The iron: six modest sections spread across the band, low = high frames, zeros masked, gains 0 dB.

The iron is seedable. At boot only, a quiet seed row sits under the transport: **vowel** (Peterson-Barney F1/F2 pairs, Q from Klatt bandwidths), **modal** (tube harmonics / inharmonic ratios × f0), **fit** (LPC formant fit — drop any audio file, the iron is cast from it), **blank**. Generators write pole pairs into the section model; zeros stay masked until dragged away. The row vanishes at first edit and never appears mid-session. Seeding is a start-state, not an edit, and owns no resident UI.

---

## 10. Audition

The judge chain equals the product chain: filter → AGC → Mackie saturation, SpatialMode::Off. QSound stays out of the audition unless it ships on by default in the plugin — the two must never diverge. Ride is one control: shape (ramp / triangle / drift) and rate in a single drag, running by default, yielded to manual scrub and resumed on release. Sources: noise / loop / live input, in the summonable strip. Hold spacebar: filter bypass with the drive chain still in (AGC tempers the loudness bias now; BS.1770 matching remains E4, after v2 ships). Two monitor dots — input present, output clip — are the entire metering budget.

---

## 11. The secondary axis, named honestly

The transport's second axis is labeled from the preset's `secondary_target` cartridge field, because "Q = pole radius" is the reference convention, not a format rule. `packed` (default): label **SHARPEN**, behavior = C2/C3 from C0/C1 with pole radius scaled, numerator held. `free corners`: label **MOVE 2** — C2/C3 authored directly; the dock caps gain a second pair of weight indicators and the Field re-sweeps against whichever corner set the rail addresses. `slam`: label **DRIVE** — the rail routes to saturation input gain; the Field does not re-temper (the body is static along that axis) and the spectrum layer becomes the visible consequence instead. `packed+slam`: label **BOTH**. Morph taper (`linear` / `log_1p45`) is set at KEEP time with the name, not on the working surface — it changes the knob's feel in the plugin, not the body.

---

## 12. Audit and bank

The 17×17 packed audit never runs as an event. The navigator's grid refines coarse-to-fine in rAF idle, edits invalidate locally, and the lamp reports the standing verdict: **ember, breathing** — grid catching up to the last edit; **truth white, steady** — full grid passes; **fault red** — failures exist, plotted at their (morph, sharpen) cells in the navigator and at their morph altitudes on the spine and Field. Tap a red lamp for the fault list in plain language ("max |H| 47.1 dB at morph 0.62, sharpen 0.85 — section 4"), one line per fault, click to jump there.

KEEP: hold the lit lamp, type the name, choose taper, release. The pipeline is the existing one — `/keep`, server recompiles via DLL `compile_body`, nulls against the browser's `packWithCore` bytes, full 17×17, bank artifacts written, cartridge fields (`secondary_target`, `morph_taper`, category, notes) stamped. The Field at KEEP-time sharpen renders into the bank as the body's thumbnail. KILL exists but lives behind a hold on the body name, far from the lamp — destructive never sits adjacent to terminal.

The bank shelf pulls in from the bottom edge: Field thumbnails (absolute heat, so the shelf is comparable at a glance), name, category. Drag a banked body onto the workspace for a ghost — curve-only overlay on the Curve pane; the Field always belongs to the body being authored.

---

## 13. Summonable, not resident

The inspector is a dev overlay, key-held or pinned in dev mode: selected section only — `(f_p, r_p) (f_z, r_z) g_low g_high on topology anchor/voice per-frame-radius override secondary-zero override`. Numeric readouts elsewhere appear under touch and vanish on release: Hz, dB, 0–1 morph/sharpen. Coefficient words, radii-as-text, and packed bytes appear nowhere outside the inspector. The source/setup strip (audition source, key for the 12-TET rail, rail selection, dev toggles) pulls from the bottom edge with the shelf. The fault list appears from the lamp. The name field exists only during KEEP.

## 14. Must not exist

No pole-zero unit-circle plot — poles and zeros are gripped as the response features they create. No coefficient table as a resident band; no per-section mini-plot strip (selection highlighting carries identity in place). No type/topology pickers — the classifier reads, never writes. No phase or group-delay panes. No preset browser inside the authoring surface beyond the shelf. No toolbar, icon strip, panel chrome, or resizable splitters. No zoom buttons, no apply/render/preview, no save-as. No FFT behind the editor while a handle is held. No autoscaled heat, ever.

---

## 15. Record mode (E9 — before first shoot)

Subtraction, not reflow. 9:16 composition: Curve ≈ 25% height, Field ≈ 60%, Sharpen collapsed to a right-edge sliver, Ride and navigator hidden, lamp top-right, labels off, handles and the truth line at 2× weight. Frequency callout tags — record-mode only — auto-label the selected ridge and follow it through the Field (`1.6k` riding a moving ridge narrates the sweep without a voiceover). All sweeps precomputed at shoot resolution; the idle scheduler is suspended so nothing hitches on camera. The `?body=` param (E10) loads a body cold for repeatable takes; fresh-iron boot makes "blank to banked in sixty seconds" a repeatable format, and a seeded iron ("filter cast from this vocal") is the second format. The KEEP flash is the closing frame.

---

## 16. Color

| Token | Value | Role — exclusive |
|---|---|---|
| Void | `#0B0B0D` | Background |
| Iron | `#1A191C` | Dock caps at rest, rails, recessed structure |
| Hairline | `#56524C` @ 60% | Axes, corridor band, labels |
| Truth | `#F2EFE8` | The Curve; lit lamp; active numerals |
| Heat ramp | see calibration | Field magnitude only |
| Ice | `#8FE3F0` | All interaction: handles, selection threads, weight glows, grabbed playhead, Routes threads |
| Ember | `#C7741F` | Lamp while auditing; spine approaching threshold; OFF-CORRIDOR tint |
| Fault | `#E5483C` | Audit failures only, nowhere else |

**Ramp calibration (absolute, fixed for the product's life):** ≤ −12 dB → Void · 0 dB → `#341B4D` · +20 dB → `#8A3D2A` · +33 dB (corridor floor) → `#C7741F` · +44 dB (corridor ceiling) → `#F6E8C8`. Above +44 the ramp holds at hot white; the rim hatch (fine diagonal, Truth at 40%) overlays wherever `pole_r` sits at the 0.9992 clamp — riding the rim is the reference set's main event and is never silent. The ramp routes violet→amber, skipping red, so Fault keeps its monopoly.

## 17. Typography

One grotesk with true tabular figures (Söhne / Suisse Int'l; Inter for the mockup). No bold weights — hierarchy by size, luminance, case. Labels (LOW, HIGH, SHARPEN/MOVE 2/DRIVE, RIDE, CORRIDOR, BANK): 10 px caps, +8% tracking, Hairline. Touch values: 13 px tabular, Truth, producer units only. Fault lines: 13 px sentence case, plain language with coordinates. The name at KEEP: 28 px Truth — the one display moment.

---

## 18. Layout and the default mockup state

Reference canvas 1728 × 1080. Top: 56 px band, frequency ticks only. Curve pane ~300 px, full width minus rail: truth line, corridor band, threshold rule, spectrum layer ghosted off. Shared-axis hairline. Field ~560 px: dock caps as 28 px end bars (LOW bottom, HIGH top) that double as the corner-weight indicators during undocked drags; playhead with right-edge nub; headroom spine 20 px left. Right rail 72 px: monitor dots, secondary-axis rail (labeled per `secondary_target`), Ride, navigator square, lamp bottom-right with BANK beneath. Bottom edge: 2 px reveal hint for shelf + source/setup strip. Nothing else resident.

**Default state to draw:** mid-session, ten seconds before banking. Six sections; in the Field, ridges braid with one crossing at morph ≈ 0.45, a bloom toward the top under sharpen 0.8, one dark parked-zero channel cut diagonally by a pole trajectory leaving an isolated dark cell; the bloom's ridge cores carry the rim hatch. Playhead at morph 0.38, undocked; the Curve shows that slice with handles on its realized features. One section selected: its peak and parked notch marked in Ice, its low/high positions and Field thread highlighted, gain stem out with the other frame's stem ghosted at −24 dB / +1.5 dB. Spine flares ember near morph 0.6, under threshold. Navigator shows the bloom gradient with no fault cells. Ride runs a slow triangle. Lamp breathes ember. Two numerals under the selected peak: `1.84k  +11.2 dB`. One image; the whole model.

---

## 19. Implementation bindings and budgets

Curve and Field: `packed.js` only — one code path, so they cannot disagree; the plot==engine harness (`tools/plot_engine_null.py`, gate < 1e-4 dB) stays green in any session touching `packed.js` or the compilers. Field budget: 240 × 480 sweep ≤ 8 ms in a worker, single-channel texture through the ramp; gesture frames debounced to display rate. Rim hatch from compiler clamp flags, never UI-side math. Ambient audit: navigator grid 5×5 → 17×17 in idle, local invalidation, same grid KEEP consumes. KEEP: `/keep` → `compile_body` → byte-null vs `packWithCore` → 17×17 → bank + cartridge fields. Bilinear edit distribution and center authoring compile through the existing 168-param path — no engine change anywhere in this document. Generators: existing v1 generators writing the section model. Classifier: locked thresholds, readback only. E-sequence alignment: E8/E11 are this document's §1/§4; E1 is §3's spectrum layer; E3 undo ships at launch (snapshot per committed edit, invisible); E9/E10 are §15; E2 WebMIDI and E4 loudness after v2; E7 interior optimization stays its own project, bank ≥ 3 first.

Residual engineering items, tracked not designed around: re-verify closed-loop center correction through `compile_body` (§7); BS.1770 match (E4); WebMIDI map (E2).
