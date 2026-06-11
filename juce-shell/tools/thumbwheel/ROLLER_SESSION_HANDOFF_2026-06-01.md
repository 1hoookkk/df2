# TRENCH Horizontal Thumbwheel: Session Handoff

Date: 2026-06-01

## Immediate Mission

Restore a detailed E-mu/X3-style horizontal thumbwheel illusion for the Morph
and Q controls. Keep the runtime interaction and internal moving-light model,
but replace the current simplified white-slat bitmap with a richer low-resolution
surface derived from measured reference behavior.

The current shipping bitmap is a regression. It is too smooth, too bright, and
too low-detail. It reads as two white horizontal strips inside a socket rather
than a tactile molded ABS thumbwheel protruding from the chassis.

## Source Hierarchy

Use this order of authority:

1. Real Emulator X3 source strip:
   `C:\Users\hooki\do-it\BITMAP4332_1.bmp`
2. Full recovered X3 bitmap dump:
   `C:\Users\hooki\do-it\emu-x3-bitmap-dump`
3. User-provided screenshots of the real X3 roller and the earlier TRENCH
   roller appearance.
4. Repo-local generator:
   `juce-shell/tools/thumbwheel/render_thumbwheel_filmstrip.py`
5. Current shipping asset:
   `juce-shell/assets/ui/native_strip_129_96x14.png`

Reference strip facts:

| Field | Value |
|---|---:|
| Source file | `BITMAP4332_1.bmp` |
| Source dimensions | `10965 x 11 px` |
| Frame count | `129` |
| Source frame size | `85 x 11 px` |
| Source SHA256 | `CE9470878A8CE0745E8DDF5A59E5B706C69316370A239853F5DC268AD8F1F906` |

The E-mu bitmap is the visual-behavior oracle. It may be inspected, measured,
and remastered for comparison. Do not accidentally ship copied source pixels
unless that provenance decision is made explicitly.

## Required Visual Read

This is one horizontal thumbwheel rotating around a left-to-right axle.

The visible surface is a flat bitmap illusion of a projecting mechanical wheel:

- Warm off-white molded ABS plastic shell.
- Low-resolution E-mu-era raster shading.
- Fine horizontal wrapped-surface detail.
- Narrow straight horizontal marks only.
- Dark recessed central clearance.
- Top and bottom occlusion from the slot lips.
- End rolloff so the surface does not read as a flat rectangle.
- Lower contact shadow and cast shadow so the wheel appears seated but
  protruding.
- Visible surface texture remains detailed even when no internal light is
  present.

It must not read as:

- two white slats;
- a fluorescent tube;
- a progress bar;
- a flat painted band;
- a vertical drum;
- a grille of vertical teeth;
- a modern vector gradient;
- a clean photoreal 3D control.

## Internal Light Behavior

The light source belongs behind the ABS surface, not on top of it.

Required behavior:

- Frame `0` is fully unlit.
- Frame `128` is fully unlit.
- Frames `1..127` may show internal light.
- The light moves left to right with the parameter value.
- There is barely any glow ahead of the current value.
- A short, restrained tail fades behind the current value.
- The light is revealed only through the dark central clearance and limited
  seam transmission.
- The ABS body remains readable over the light.
- The effect must not become a broad symmetric bloom or pasted-on highlight.

Current session color decision:

- Global secondary accent: ultralight violet.
- Roller internal light: same ultralight-violet family.
- Warm off-white ABS surface remains the primary roller material.

Current style tokens:

```cpp
accent()    = 0xffe5dcff
accentDim() = 0xff9f8fc8
```

## Runtime Component Contract

Runtime control:

`juce-shell/source/TrenchThumbwheel.h`

Current behavior:

- Loads `native_strip_129_96x14.png` from JUCE `BinaryData`.
- Crops one of `129` horizontal frames.
- Maps normalized parameter value to `round(norm * 128)`.
- Draws cast shadow before the bitmap.
- Draws directional ultralight-violet internal light before the bitmap.
- Draws the semi-transparent bitmap over that light.
- Draws lower contact shadow after the bitmap.
- Uses left-right mouse drag and mouse-wheel interaction.
- Ends parameter gesture safely on mouse-up or destruction.

Current component placement:

`juce-shell/source/PluginEditor.cpp`

```cpp
morphBounds(w, h).expanded(6, 3).withTrimmedBottom(-4)
qBounds(w, h).expanded(6, 3).withTrimmedBottom(-4)
```

The wheel component intentionally extends beyond the measured faceplate well so
the wheel can appear to project from the recess.

Earlier measured live geometry before the latest enlargement:

| Control | Layout well | Component | Painted face |
|---|---:|---:|---:|
| Morph | `119 x 25` | `123 x 29` | `121 x 27` |
| Q | `120 x 27` | `124 x 31` | `122 x 29` |

The latest bounds add another `4 px` width and roughly `3 px` height over that
iteration.

## Generator Contract

Repo-local renderer:

`juce-shell/tools/thumbwheel/render_thumbwheel_filmstrip.py`

Shipping output:

| Field | Value |
|---|---:|
| Frame count | `129` |
| Native frame size | `96 x 14 px` |
| Native strip size | `12384 x 14 px` |
| Upscaled frame size | `384 x 56 px` |
| Upscale method | nearest-neighbour |
| Shipping strip SHA256 after this session | `8129A4A92E948E7E41B64EAADDF7273FF47FA547920F9ABDD6E1EF1AD2F21055` |

The native `14 px` frame height is the critical constraint. Every row must earn
its place. Fine detail must be authored at native resolution, not painted later
as large runtime rectangles.

## What Changed This Session

### Recovered References

- Restored the Emulator X3 bitmap dump under
  `C:\Users\hooki\do-it\emu-x3-bitmap-dump`.
- Identified `C:\Users\hooki\do-it\BITMAP4332_1.bmp` as the exact `129`-frame
  X3 thumbwheel strip.
- Restored the blank teal logarithmic-grid source:
  `C:\Users\hooki\do-it\BITMAP4613_1.bmp`.

### UI Wiring

- Replaced invisible Morph and Q slider hit areas with visible
  `TrenchThumbwheel` components.
- Added the visible body-selection strip.
- Kept separate numeric readout components.
- Moved numeric readouts closer to the wheel controls.
- Enlarged wheel component bounds repeatedly so they protrude beyond the wells.

### Roller Rendering

- Added runtime cast shadow and lower contact shadow.
- Added runtime internal light drawn underneath the bitmap mask.
- Gated internal light off for frames `0` and `128`.
- Changed the light from a symmetric bloom to a directional source with a
  narrow leading edge and short trailing fade.
- Removed a post-bitmap catchlight overlay after it made the roller read as
  painted-on white bars.
- Changed the session accent from peach/coral to ultralight violet at the
  user's request.

### Bitmap Generator Regression

The generator was simplified into a fixed fourteen-row profile:

```python
ROW_LUMA
ROW_ALPHA
ROW_PHASE
```

This solved one narrow problem: it removed leaning marks and vertical grille
artifacts.

It also removed too much surface information:

- only a few broad horizontal brightness zones remain;
- the top and bottom ABS lips became smooth white bars;
- the dark clearance is too uniform;
- the aliased bitmap-era fragments are mostly gone;
- the wheel lacks the dense local shading that makes the source look
  mechanical;
- the surface animation is too subtle to imply wrapped movement;
- the enlarged control exposes the lack of detail more clearly.

Do not polish this by adding more runtime overlays. Fix the native bitmap rows.

## Next Pass

Work from the real `85 x 11` X3 frames as a measurement reference before
touching runtime code again.

1. Extract representative source frames: `0`, `1`, `32`, `64`, `96`, `127`,
   and `128`.
2. Inspect each native row and record:
   - horizontal highlight rows;
   - dark seam rows;
   - center-clearance rows;
   - alpha/transmission rows;
   - end-rolloff width;
   - frame-to-frame pixel changes.
3. Build a denser `96 x 14` row model with several narrow transitions instead
   of two broad bands.
4. Preserve straight horizontal marks. Add detail using row-local aliasing,
   mottled shading, and measured end rolloff, not vertical dividers.
5. Keep runtime lighting behind the bitmap. Do not add post-bitmap glow or
   large catchlight rectangles.
6. Compare a native-resolution contact sheet and a live standalone screenshot
   before accepting the result.

## Acceptance Checklist

- Wheel visibly projects beyond the recess.
- Lower shadow seats the wheel into the panel.
- ABS body has detailed low-resolution surface structure while unlit.
- No broad white-slat read.
- No vertical grille read.
- No leaning marks.
- No painted-on highlight layer.
- Internal violet light is mostly behind the surface.
- Almost no light appears ahead of the value.
- Only a short tail remains behind the value.
- Frames `0` and `128` are unlit.
- Source strip remains exactly `129` frames.
- Shipping strip remains exactly `12384 x 14 px`.
- Build embeds the updated PNG into JUCE `BinaryData`.

## Build Note

The standalone memory-maps the shipping PNG. Stop all visible `TRENCH`
standalone instances before copying a regenerated asset into:

`juce-shell/assets/ui/native_strip_129_96x14.png`

Then rebuild and launch:

```powershell
& C:\Users\hooki\df2\juce-shell\build-standalone.ps1 -Launch
```

