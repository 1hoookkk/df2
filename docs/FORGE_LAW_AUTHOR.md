# Forge Law Author

Law Author is the current Forge/manual-authoring target.

```text
law_source.json
  -> four corners of six root-domain stages
  -> packed .body240 + compiled cartridge JSON
  -> trench_core audit + plots
```

## Non-Negotiables

- Six packed stages total per corner. No hidden seventh stage.
- "Foundation" means a law-level envelope or a stage role, not an extra runtime
  block.
- Every stage exposes pole Hz, pole radius, zero Hz, zero radius, and gain.
- Stage identity is preserved across the four corners.
- Packed runtime output is the authority.

## Controls

Law Author starts with a small control set:

| Control | Meaning |
| --- | --- |
| `anchor_hz` | Low/body resonance target. |
| `anchor_gain_db` | Low/body prominence at rest. |
| `tilt_db` | High-band restraint relative to body. |
| `canyon_depth` | Zero/notch pressure between ridges. |
| `q_crank` | Secondary/Q radius increase and contrast amount; Q pressure may drive a pole radius to `0.9999`. |
| `morph_spread` | How far pole/zero frequencies move over Morph. |
| `density` | How many mid/high ridges are emphasized. |

Family-report conversion uses `section-law-v1` instead of only scalar knobs.
Each law still compiles to six runtime stages, but each section carries measured
authoring fields:

| Field | Meaning |
| --- | --- |
| `fc_hz` | Pole/ridge center frequency. |
| `gain_db` | Intended ridge or canyon pressure. Positive values bias pole-dominant ridges; negative values bias zero-dominant cuts. |
| `bw_oct` | Resting bandwidth in octaves. |
| `zero_offset_oct` | Zero position relative to `fc_hz`. Remote offsets are legal and expected. |
| `morph_oct` | Morph-axis frequency travel. |
| `zero_morph_oct` | Independent zero travel over Morph. |
| `q_weight` | How strongly Secondary/Q cranks this section toward the radius rim. |

Optional section-law-v1 full-fidelity radius fields:

| Field | Meaning |
| --- | --- |
| `pole_radius_by_corner` | Optional object keyed by `M0_S0`, `M1_S0`, `M0_S1`, `M1_S1` or packed aliases `M0_Q0`, `M100_Q0`, `M0_Q100`, `M100_Q100`. Overrides the compiler's shared pole-radius law at that corner. |
| `zero_radius_by_corner` | Same as above for zero radius. |

If those objects are absent, Law Author keeps the compact shared-radius law:
one resting radius per section plus Secondary/Q pressure. If they are present,
the corner value is authority. This locks the direction as per-frame/per-corner
capable; shared radius is only a convenience input, not a runtime rule.

## Compile Shape

The compiler emits exactly six lanes:

1. low/body anchor
2. low-mid mover
3. mid formant
4. upper-mid bite
5. high formant / air restraint
6. canyon or counterweight

Those labels are editable authoring roles. They are not proof that reference
bodies used the same roles.

## Topology Classifier

Topology labels are audit/readback labels only. They help review a packed body;
they do not choose the runtime topology, which is always six packed stages.

Pole radius bands:

| Band | Rule |
| --- | --- |
| `rim_pole` | `pole_r >= 0.995` |
| `resonant_pole` | `0.930 <= pole_r < 0.995` |
| `frame_pole` | `0.750 <= pole_r < 0.930` |
| `damped_pole` | `pole_r < 0.750` |

Zero radius bands:

| Band | Rule |
| --- | --- |
| `rim_notch` | `zero_r >= 0.985` |
| `antiresonant_zero` | `0.900 <= zero_r < 0.985` |
| `counterweight_zero` | `0.700 <= zero_r < 0.900` |
| `weak_zero` | `zero_r < 0.700` or no complex zero |

Zero placement uses `zero_offset_oct = log2(zero_hz / pole_hz)`:

| Placement | Rule |
| --- | --- |
| `local` | `abs(zero_offset_oct) <= 0.35` |
| `above` | `0.35 < zero_offset_oct <= 1.25` |
| `below` | `-1.25 <= zero_offset_oct < -0.35` |
| `remote_above` | `zero_offset_oct > 1.25` |
| `remote_below` | `zero_offset_oct < -1.25` |

Label precedence:

1. `neutral`: `damped_pole` plus `weak_zero`.
2. `local_tear`: `resonant_pole` or `rim_pole`, plus `antiresonant_zero` or
   `rim_notch`, with `local` placement.
3. `remote_counterweight`: `resonant_pole` or `rim_pole`, plus any
   `counterweight_zero`/`antiresonant_zero`/`rim_notch` at `remote_above` or
   `remote_below`.
4. `antiresonant_canyon`: `antiresonant_zero` or `rim_notch` without a strong
   local pole.
5. `resonant_ridge`: `resonant_pole` or `rim_pole`.
6. `broad_frame`: everything else above neutral.

OBSERVED: this split keeps Talking Hedz readable as local/remote tear plus rim
pressure, and Millennium readable as high local/remote canyons plus a low
rim/counterweight frame. The `0.93` pole and `0.90` zero cutoffs are deliberately
low enough not to miss the broad P2K rows; the `rim` bands identify the pressure
edge separately.

## Generator To SOS Mapping

Generators must emit the same six lane objects as hand-authored laws: pole Hz,
pole radius, zero Hz, zero radius, and gain. A generator may not write pole-only
stages with hidden zeros.

Default zero policies:

| Generator | Zero placement |
| --- | --- |
| `vowel` | Poles come from formant candidates. Zeros sit at inter-formant valleys: `sqrt(Fi * F(i+1))` for paired formants; the last active formant gets a high air/cap zero at `min(Fi * 1.65, sr * 0.47)`. If a nasal/antiformant source is explicit, that measured antiformant zero wins. |
| `modal` | Poles come from the modal series. Zeros sit between adjacent modes at geometric means to create troughs; the last mode gets a high counterweight zero. Modal zeros default to `counterweight_zero`, not `rim_notch`, unless the author asks for a canyon. |
| `LPC` | LPC is treated as all-pole evidence. For each pole pair, first search the fitted/source envelope for a stable valley between neighboring pole pairs; if found, place an `antiresonant_zero` there. If no valley is reliable, write a masked zero at the pole Hz with `zero_r <= 0.35` so the zero is visible but not pretending to be measured. |

All three policies are starting points only. Dragging or numerically editing the
zero is the unmask gesture; after that the explicit zero value is the source of
truth.

## Cartridge Behavior

Compiled cartridges may carry behavior metadata next to the packed body:

| Field | Values | Meaning |
| --- | --- | --- |
| `secondary_target` | `packed`, `slam`, `packed+slam` | `packed` maps the Q/Secondary control to the packed secondary interpolation axis. `slam` maps that control to Mackie/Slam drive and sends `q=0` to the packed body. `packed+slam` does both. Missing means `packed`. |
| `morph_taper` | `linear`, `log_1p45` | `linear` sends Morph through unchanged. `log_1p45` sends `pow(morph, 1.45)` to the packed body. Missing means `linear`. |
| `category` | string | Optional roster/grouping hint for UI/build tools. |

The byte contract does not change. These fields only describe how the player
maps user controls before calling packed interpolation.

## Audit

Each compile must run a packed-runtime audit over a Morph/Q grid and report:

- finite response
- stability / max pole radius
- Q/Secondary rim behavior: a legal body may intentionally reach `pole_r = 0.9999`
- anchor present at rest unless disabled
- high band not dominating the low/body band at rest
- canyon depth present without nonfinite response
- `.body240` byte length and cartridge round trip

## First Golden Command

```powershell
python tools/law_author.py --preset hedz_like_anchor_canyons --out dev/tmp/law_author/golden_hedz_like
```

Expected outputs:

- `law_source.json`
- `hedz_like_anchor_canyons.body240`
- `hedz_like_anchor_canyons.cartridge.json`
- `audit.json`
- `plot_sheet.png`

## Convert Family Reports

```powershell
python tools/convert_family_reports_to_laws.py
```

This reads aggregate contracts from
`dev/tmp/x3_p2k_family_browser/contracts/` and writes original
`family_*.json` laws under `recipes/laws/`. The converted laws are clean-room:
they use aggregate frequency bands and movement metrics, not reference bytes,
coefficient rows, endpoint curves, or preset tables.
