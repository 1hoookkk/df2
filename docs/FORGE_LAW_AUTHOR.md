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
