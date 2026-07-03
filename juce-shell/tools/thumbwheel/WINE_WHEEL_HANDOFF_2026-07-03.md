# WINE WHEEL — APPROVED SPEC (Tyson, 2026-07-03) — SHIPPING WHEEL

Tyson approved this exact look from a contact sheet and said **this wheel ships**.
Do not redesign anything. Do not build custom wheels. Execute the recipe.

## The approved look (settled by Tyson's reference screenshots)

- The wheel is the REAL 3D sculpt render — **full thumbwheel silhouette seated
  inside the well** (rounded ends visible, well surround visible). NEVER crop,
  zoom, reframe, or redraw it. (Cropping the caps was explicitly rejected:
  "the framing is not right at all".)
- Lamp = **wine**, broad soft bloom through the fins — NOT thin needle lines,
  NOT pink, NOT teal, NOT a wash that lights the whole wheel.
- Approval artifact: scratchpad `broad_wine_contact.png` (frames 64/128/218).

## Source asset (do not regenerate)

`C:\Users\hooki\df2\dev\tmp\thumbwheel_blender\proper_violet_glow_257_298x80.png`
— 257 frames, 298x80 each (76586x80 total). Fins travel left-right (measured).
Baked teal-green lamp to be replaced by the wine pass below.

## The approved per-frame recipe (from the accepted contact sheet, verbatim)

```python
GLOW = [164, 38, 60]; CORE = [214, 92, 112]          # wine family
lamp  = clip(G - R, 0)                                # baked lamp is green-dominant
base  = [R, G - lamp, min(B, max(R, G - lamp))]       # lamp removed, body untouched
L     = lamp as L-image
bloom = GaussianBlur(L, 7.0); halo = GaussianBlur(L, 16.0); glint = GaussianBlur(L, 1.2)
e     = clip(bloom*2.6 + halo*1.6 + glint*0.55, 0, 255) / 255
col   = GLOW*(1 - e*0.5) + CORE*(e*0.5)
rgb   = clip(base + col * e * 1.5 * alpha, 0, 255)    # alpha = A/255
```

Alpha channel passes through unchanged. Process all 257 frames.

## Install + build + verify (the proven loop)

1. Output strip 76586x80 → copy over
   `C:\Users\hooki\df2\juce-shell\assets\ui\thumbwheel_runtime_strip_129_149x40.png`
   (filename is historical; WheelControl derives frame count from width/298).
2. Kill `TRENCH`/`FL64` processes. Delete
   `juce-shell\build-ninja\juce_binarydata_Assets` and any `Assets.lib` under
   `build-ninja` (forces BinaryData recompile).
3. Prepend `C:\Users\hooki\.cargo\bin` to PATH, then
   `pwsh -NoProfile -File juce-shell\build-standalone.ps1 -Diagnostics`.
   A transient first failure (link lock) is known — retry once.
4. Launch `juce-shell\build-ninja\TRENCH_artefacts\Release\Standalone\TRENCH.exe`,
   wait ~10s, capture 1:1 via PrintWindow (powershell.exe 5.1, EnumWindows by
   pid, PrintWindow flag 2 — working script:
   `C:\WINDOWS\TEMP\claude\C--Users-hooki-df2\ba72697c-acef-42ef-bbd0-9c3fe73fd301\scratchpad\cap_existing.ps1`).
5. Leave the standalone OPEN. Send Tyson the capture. STOP — no VST3 build
   until he approves the standalone shot.

## Already-fixed context (keep, do not revert)

- `UiLayout.h`: wells re-measured to the INNER slot openings —
  morphWheel (120,682,422,120), qWheel (119,870,424,123).
- `WheelControl.h`: kSeat 1.00 (flush in the inner opening), clip radius 0.20*h.
- Backup of the pre-session strip:
  `juce-shell\assets\ui\thumbwheel_runtime_strip_129_149x40.png.melted_glb.bak`.

## Hard rules (from CLAUDE.md + failure docs — they are binding)

- One change per pass; verify in a REAL build capture, never a mock.
- Contact sheet / build shot goes to Tyson for verdict; his eye is the gate.
- No fake layers, no painted seats/shadows behind the wheel.
- The wheel does NOT roll up/down. Fins travel left-right. It is a horizontal
  thumbwheel seen from the front — full silhouette.
