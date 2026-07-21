Continue TRENCH wheel/glow work in C:\Users\hooki\df2-workstation (a JUCE VST3
plugin). Read these three files in the repo root first — they record the same
day's prior dead ends and the current state, don't repeat what's already
failed:

- HANDOFF_20260720_NIGHT.md
- UI_WHEEL_FAILURE_20260720.md
- UI_RECOVERY_HANDOFF_20260720.md

## Goal

Reproduce the wheel look in the attached reference images: a light-grey /
silver machined ribbed roller body with a teal/cyan glow band traveling
through the gap cells as MORPH or Q increases. This is the "perfect wheel"
per direct user verdict on reference photos, and it is NOT what's currently
shipped (currently shipped is a similar-geometry wheel with a BLUE/cobalt
lamp instead of teal — see "Currently shipped" below).

## The raw material already exists — use it, don't re-render from scratch

C:\Users\hooki\df2\dev\tmp\roller_batch_az90\ contains a COMPLETE, proper
two-pass Blender render, already verified present and well-formed:

- `clean\f000.png` … `f256.png` — 257 frames, 792x176 RGBA, the wheel body
  alone (dark glossy machined material), no baked light. This is a body-only
  pass, not glowless-forever — it's meant to be composited with the glow
  pass below, not shipped as-is.
- `glow\f000.png` … `f256.png` — 257 frames, 792x176, matching frame numbers.
  This is a WHITE transmission/occlusion map: frame 0 is fully black
  (confirmed — dark at rest), frame 128 shows bright white light bleeding
  through a cluster of gap cells on the left portion of the strip with the
  wheel geometry correctly occluding the rest. This is the "light behind an
  occluding wheel" method, already proven elsewhere in this repo's history —
  composite it, don't re-derive the physical light-through-gaps method from
  scratch.

**Known risk, verify before committing to this batch**: this exact clean/
folder was previously flagged in this repo's history as having "unwanted
movement along the strip" — some kind of lateral geometry jitter across
frames, not visible from spot-checking 2-3 frames. Before using it, render a
full contact sheet of all 257 clean frames (or at minimum every 8th frame)
and scan for ribs/geometry shifting unnaturally frame to frame, not just
smoothly rotating. If it's actually broken, say so and stop — don't grade
over a broken geometry pass and call it fixed.

## Currently shipped, for reference

`plugin/assets/trench_roller_strip.png` (300x68 per frame x257) +
`plugin/source/ui/WheelControl.h` (`kStripFrameWidth=300`,
`kStripDrawScale=2`) is commit `aabd23be` ("pin recovered smoked-cobalt
clean baseline", 2026-07-16) — verified IP-clean this session, light-grey
body, BLUE lamp (not teal). This is the safe fallback if the az90 batch
doesn't pan out. Do not regress below this quality bar.

## Compositing method

Follow the envelope-gated method already proven in this repo (search prior
session logs / `x3_lamp_envelope.npy` if present under
`C:\Users\hooki\df2\dev\tmp\thumbwheel_blender\` for the measured X3
lamp-position envelope): tint the white glow-pass transmission map with the
target teal/cyan accent, gate its intensity by measured playhead position
per frame, and composite additively over the clean body. Keep the hot core
near-white (bleached), not flat-colour. Do not paint a rectangle, a straight
cyan line, or any procedural tooth field over the geometry — that failure
mode is explicitly banned in UI_WHEEL_FAILURE_20260720.md.

## Hard constraint — do not violate

Never use raw pixels from `C:\Users\hooki\do-it\emu-x3-bitmap-dump\*.bmp` as
a shipped product asset. That folder is measurement reference only. This
session found and fixed exactly this mistake once already (a prior pass had
literally cropped `BITMAP4331_2.bmp` frames into
`plugin/assets/trench_roller_strip.png`) — before calling any new wheel
asset done, verify its pixel dimensions don't exact-match any file in that
dump folder, the same way this session did:
```python
# compare candidate asset dimensions/pixels against every file in
# do-it\emu-x3-bitmap-dump\ before shipping — no exact size or pixel match allowed
```

## Colour verdict needed, don't guess silently

The currently-shipped wheel is blue; the target reference is teal. This
hasn't been resolved against the rest of the face (the curve/screen accent
is currently coral/brick, not teal or blue — see HANDOFF's "one lit voice"
open question). If you build the teal version, say clearly that this creates
a three-way colour question (wheel vs. curve vs. anything else lit) rather
than silently picking one and moving on.

## Integration + verification (mandatory, not optional)

1. Pack the final composited frames into a single horizontal strip PNG at
   `plugin/assets/trench_roller_strip.png`.
2. Update `kStripFrameWidth`/`kStripDrawScale` in
   `plugin/source/ui/WheelControl.h` to match the new frame width exactly —
   check the current committed values first, a mismatch renders a corrupted
   wheel, not a build error.
3. Build `TRENCH_FaceShot` (`cmake --build build --target TRENCH_FaceShot
   --config Release`) and run it — this is a headless console harness that
   renders the real `PluginEditor`, separate from the installed VST3.
4. Crop and zoom the rendered wheel at true 326x503 scale and visually
   compare against the reference images before claiming this works. A green
   build proves nothing about the visual result.
5. Do NOT install to `C:\Program Files\Common Files\VST3\TRENCH.vst3` — leave
   that for a human verdict on the FaceShot render first.
