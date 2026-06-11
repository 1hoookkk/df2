# TRENCH Thumbwheel Final Handoff

Date: 2026-06-08

This handoff supersedes:

- `juce-shell/tools/thumbwheel/ROLLER_SESSION_HANDOFF_2026-06-01.md`
- `juce-shell/tools/thumbwheel/thumbwheel_geometry_spec.json`

Those files contain useful context, but their wording is now too ambiguous. The
dangerous ambiguity is this: "visible fins" or "selected top ridges" can be
misread as "draw bright individual fin caps." That produces bubbles, beads,
chain links, or a toy/cartoon grille. Do not follow that interpretation.

## Current Runtime Truth

Work in the actual plugin runtime. Do not make a mockup.

Primary files:

- `juce-shell/source/PluginEditor.cpp`
- `juce-shell/source/PluginEditor.h`
- `juce-shell/tools/thumbwheel/render_raw_85x11_strip.py`
- `juce-shell/assets/ui/thumbwheel_strip_129_85x11.png`
- `juce-shell/assets/ui/thumbwheel_runtime_strip_129_149x36.png`
- `juce-shell/assets/ui/df2_panel_shadow.png`

The plugin draws the panel first, then draws one frame from the runtime
thumbwheel strip into the existing black wells. The invisible sliders/hit
targets drive Morph and Q. Do not reintroduce visible JUCE sliders.

Hard strip contract:

- 129 frames, indexed `0..128`
- raw frame size: `85x11`
- raw strip size: `10965x11`
- runtime frame size: `149x36`
- runtime strip size: `19221x36`
- frame `0` has no glow
- frame `128` must be byte-identical to frame `0` and have no glow
- no separate JUCE cyan glow overlay
- no panel, well, or frame redraw

Required validation commands:

```powershell
python juce-shell\tools\thumbwheel\render_raw_85x11_strip.py
cmake --build juce-shell\build --config Release --target TRENCH_Standalone --parallel 1 -- /nodeReuse:false /v:minimal
```

After building, capture the real standalone window with `PrintWindow`, not
`CopyFromScreen`. `CopyFromScreen` previously captured stale chat screenshots and
caused a false feedback loop.

## Reference Authority

Use this order of authority. These paths were verified present on
2026-06-08. The E-mu/X3 files are reference-only unless Tyson explicitly makes
a provenance decision to use source-derived pixels. Shipping output should be a
production-original render.

### Machine-Readable Reference Manifest

```json
{
  "reference_manifest_version": 1,
  "verified_on": "2026-06-08",
  "source_policy": {
    "emu_bitmaps": "reference_only",
    "shipping_asset": "production_original",
    "do_not_ship": "source-derived E-mu pixels, remasters, recolors, crops, or traced bitmap cells unless explicitly approved"
  },
  "primary_user_screenshots": [
    {
      "path": "C:\\Users\\hooki\\OneDrive\\Pictures\\Screenshots\\Screenshot 2026-03-01 025054.png",
      "role": "whole plugin UI context; match panel fit, faceplate depth, well scale, and material compatibility"
    },
    {
      "path": "C:\\Users\\hooki\\OneDrive\\Pictures\\Screenshots\\BITMAP4331_1_mid.png",
      "role": "main E-mu behavior reference; broken top light, dark middle aperture, internal cyan cells, and short uneven tail"
    },
    {
      "path": "C:\\Users\\hooki\\OneDrive\\Pictures\\Screenshots\\BITMAP4331_1_detail.png",
      "role": "close material/light reference; irregular sparse highlights, dark occluders, and non-cartoon bitmap grit"
    },
    {
      "path": "C:\\Users\\hooki\\OneDrive\\Pictures\\Screenshots\\roller_frames_17px.png",
      "role": "low-height frame logic; what must survive when the thumbwheel is tiny and raster-limited"
    },
    {
      "path": "C:\\Users\\hooki\\OneDrive\\Pictures\\Screenshots\\roller_start.png",
      "role": "start/no-glow reference; fixed body, fixed lighting, no pasted cyan"
    }
  ],
  "emu_bitmap_corpus": [
    {
      "path": "C:\\Users\\hooki\\do-it\\BITMAP4332_1.bmp",
      "role": "exact E-mu/X3 129-frame thumbwheel source strip for measurement only",
      "dimensions": "10965x11",
      "frame_size": "85x11",
      "frame_count": 129,
      "sha256": "CE9470878A8CE0745E8DDF5A59E5B706C69316370A239853F5DC268AD8F1F906"
    },
    {
      "path": "C:\\Users\\hooki\\do-it\\emu-x3-bitmap-dump",
      "role": "full recovered E-mu/X3 bitmap dump; use for context and measurement, not direct shipping pixels"
    },
    {
      "path": "C:\\Users\\hooki\\do-it\\BITMAP4613_1.bmp",
      "role": "E-mu/X3 bitmap-dump provenance/style context; not the thumbwheel behavior source"
    }
  ],
  "secondary_user_comparisons": [
    {
      "path": "C:\\Users\\hooki\\df2\\dev\\tmp\\selector_fixed_open.png",
      "role": "useful dark display/slot material direction; avoid turning the wheel into a band, Oreo, or clean pill"
    },
    {
      "path": "C:\\Users\\hooki\\.gemini\\antigravity\\brain\\72c0cc85-b299-472e-a787-308a1779a9d3\\.tempmediaStorage\\media_72c0cc85-b299-472e-a787-308a1779a9d3_1780827956192.png",
      "role": "user-supplied visual comparison for panel fit/material direction"
    }
  ],
  "derived_analysis_artifacts": [
    {
      "path": "dev\\tmp\\thumbwheel_reference_study",
      "role": "local crops/edge studies derived from references; useful for analysis but lower authority than the original screenshots and E-mu bitmap"
    },
    {
      "path": "dev\\tmp\\thumbwheel_runtime_check",
      "role": "runtime/reference comparison crops; use for visual audit after rebuilding and PrintWindow capture"
    }
  ]
}
```

### Human Reading Of The References

The references do not describe a cylinder, clean pill, chain, tire tread, Oreo
band, or row of LEDs. They describe a horizontal thumbwheel surface seen through
a dark slot.

`BITMAP4331_1_mid.png`, `BITMAP4331_1_detail.png`, and `BITMAP4332_1.bmp`
show the key logic: the body stays mechanically dark; sparse fixed highlights
reveal the protruding wheel; dark carved/occluding geometry breaks the middle;
cyan sits behind that mask as a broad moving internal halo with a smaller hot
core and a short uneven rolloff. The cyan is not drawn on top.

`roller_frames_17px.png` and `roller_start.png` are the guardrails for frame
motion: fixed well/body lighting and the visible material texture must remain
fixed. The moving read comes from the recessed cyan halo travelling behind the
dark aperture/mask. If any aperture/mask variation moves, it must be secondary
occlusion on that halo, not a scrolling body texture. Frame `0` and frame `128`
must have no glow and must be identical.

`selector_fixed_open.png` is only a secondary comparison. Its dark aperture
style was closer to the plugin, but the final wheel must not become a flat band
or sandwich silhouette.

## Correct Visual Model

Read order must be:

1. Existing black recessed well from `df2_panel_shadow.png`.
2. One continuous horizontal thumbwheel body.
3. Molded bone-white / dirty ABS plastic surface.
4. Fins/grooves carved into that body.
5. Dark central mechanical aperture.
6. Cyan internal emitter behind the aperture.
7. Faceplate contact/cast shadow that makes the wheel protrude.

The critical correction:

```text
The wheel is one continuous body.
Fins are carved dark interruptions and occluders.
Fins are NOT separate lit objects.
Do not light each fin cap.
```

If every fin receives its own highlight, the result reads as bubbles. If the
marks become diagonal slashes, the result reads as a tread or stylized grille.
If the body becomes too white and smooth, the result reads as a cartoon/toy.

## Geometry Rules

The wheel is a tactile horizontal spinning thumbwheel. It should invite a
left-right drag.

Author the renderer from these rules:

- continuous low horizontal ABS roller first
- dark end rolloff so it does not become a flat rectangle
- top and bottom surfaces protrude into the well
- central black aperture interrupts the body
- fins are spread across the surface as shallow vertical/near-vertical carved
  grooves and dark occluding interruptions
- fins can overlap toward the center through shadow/mask behavior
- fins must not become evenly repeated bright caps
- fins must not become diagonal slashes
- fins must not become fine comb teeth
- fins must not become blocky stone/tile cells
- keep coarse low-res bitmap-era irregularity

The movement illusion is created primarily by the cyan halo moving behind the
dark aperture while the body/material stays visually stable. Fixed lighting and
the wheel's visible material texture must not scroll. Do not make the whole
thumbwheel surface slide sideways with the parameter.

## Material Rules

Target material:

```text
dirty bone-white ABS plastic, matte, slightly aged, not glossy.
```

Material must sit naturally on the beige/grey plugin faceplate. It should be
lighter than the dark well but not bright toy white.

Do:

- use warm grey/beige shadow valleys
- use diffuse top-down lighting
- use low-contrast molded curvature
- use small irregular dirt/noise
- preserve a dark central aperture

Do not:

- use orange/copper
- use shiny chrome
- use pure white plastic
- use per-fin shiny dots
- use bubble-like circular caps
- use cartoon/vector highlights

## Lighting Rules

There are two separate light systems.

### 1. Fixed Material Light

Fixed relative to the well. It is the light that reveals the ABS shape.

It should be:

- broad
- top/down directional
- broken irregularly by the surface
- strongest on selected surface regions, not on every fin
- separate from cyan

It must not:

- repeat identically per fin
- move with the parameter
- form a long horizontal chrome line
- make each fin a bulb

### 2. Internal Cyan Emitter

The cyan is inside the wheel, behind the dark aperture/mask.

It should be:

- a wide recessed halo field behind the aperture
- a smaller hot current core/bead cluster inside that halo
- a short-to-medium uneven tail fading behind the current value
- broken by aperture/fins/mask
- slightly recessed/lower than the material highlights
- broad enough to sell motion at real plugin size, not just a tiny indicator
  dot

Measurement guardrail from the reference read, used as behavior guidance rather
than copied pixels:

- native halo footprint should feel roughly `20-26 px` wide at `85x11`
- strongest rows are the middle aperture rows, especially around row `5`
- hot core is smaller than the halo; the halo is what carries motion

It must not:

- be pasted on top of the wheel
- become a full-width horizontal line
- become evenly spaced LED dots
- collapse into a tiny isolated vertical bead
- light every fin cap
- appear in frame `0` or frame `128`

## Shadow / Depth Rules

The wheel must look physically installed and protruding from the existing well.
The faceplate shadow must match the wheel depth.

Draw the faceplate/well shadow in `PluginEditor.cpp` before the roller frame:

- tight contact shadow immediately under the bottom of the wheel
- soft cast shadow down/right on the faceplate
- subtle dark occlusion under the top lip
- side/end rolloff shadows at the left and right ends
- same depth treatment for Morph and Q
- no generic rounded rectangle outline shadow
- no shadow that reads disconnected from the wheel material

The shadow should explain that the wheel is raised enough to be grabbed/spun
but still seated inside the existing black well.

## What Went Wrong In The Current Loop

The renderer drifted through these bad reads:

- dark metal strip: did not fit the faceplate/material language
- horizontal shine: read as UFO/saucer
- vertical bright fin caps: read as bubbles
- bright ABS: read as cartoon/toy
- slanted grooves: read as diagonal grille/tread
- repeated cells: read as chain links or LED beads

The root gap was treating fins as visible objects. The correct approach is to
treat the body as continuous and the fins as carved/masked interruptions.

## Implementation Algorithm

Recommended renderer order:

1. Draw continuous dirty bone ABS body with end rolloff and alpha falloff.
2. Add top/bottom rounded surface shading with broad diffuse light.
3. Cut dark central aperture into the middle.
4. Apply fixed or lightly varying aperture/mask interruptions without making
   the body texture scroll.
5. Add only broad fixed material highlight islands.
6. Add broad moving cyan halo behind aperture/mask.
7. Add smaller hot core inside the halo.
8. Re-apply occluders so cyan is broken and internal.
9. Add contact/end shadows in the strip.
10. Draw faceplate contact/cast shadow in `PluginEditor.cpp`.
11. Draw the runtime strip frame 1:1 inside the existing well.

Important inversion:

```text
Do not start by drawing fins.
Start by drawing the roller body, then cut fins into it.
```

## Acceptance Checklist

Machine checks:

- raw strip is exactly `10965x11`
- runtime strip is exactly `19221x36`
- raw frame `0` bytes equal raw frame `128`
- runtime frame `0` bytes equal runtime frame `128`
- standalone builds successfully
- runtime capture uses `PrintWindow`

Visual checks at real plugin size:

- reads as one horizontal tactile thumbwheel
- invites left-right drag/spin
- fits inside existing `df2_panel_shadow.png` well
- wheel appears seated and protruding
- faceplate shadow matches wheel depth
- material reads dirty bone ABS, not cartoon white
- fins read as carved/masked interruptions
- no bubbles
- no slanted grille
- no chain/tank tread
- no vertical drum/cylinder
- no clean pill
- no two white rails
- no continuous black center line
- no continuous cyan line
- body/material texture does not visibly slide sideways with the parameter
- cyan is internal and masked
- cyan reads as a broad recessed halo with a smaller hot core, not a tiny bead

If any visual check fails, do not keep tuning color. Return to the geometry
rules above.
