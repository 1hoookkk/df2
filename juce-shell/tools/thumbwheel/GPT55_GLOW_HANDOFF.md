# GPT-5.5 handoff — thumbwheel glow (2026-06-11)

You are picking up ONE task: **the internal cyan glow of the df2/TRENCH plugin
thumbwheel**. The wheel itself is solved and approved — do not touch the wheel,
the rig, the layout, or the asset contract. Claude's glow attempt was rejected
by Tyson as "very very wrong"; design the glow properly.

## The product goal (Tyson's spec, stable across sessions)

A horizontal hardware thumbwheel (bone-white plastic, organic sculpted fins,
dark mechanical aperture channel around the equator) sits in a black well on
the plugin faceplate. Behind that dark middle channel lives a **cyan glow**:

- a **hot bead** whose horizontal position tracks the parameter value
  (left = 0, right = max),
- a **short uneven trail** behind it that **fades as it travels**,
- the glow is **INTERNAL** — light from inside the wheel, seen through the
  channel's gaps and kissing the fin edges; never a sprite painted on top,
- frames 0 and 128 are **glowless** (asset contract below).

Reference images (READ THESE FIRST):
- `juce-shell/tools/thumbwheel/reference_bone_wheel.png` — Tyson's own target
  render. The glow there (right side, violet/cyan) is the look to match: a hot
  core INSIDE the channel, asymmetric falloff, lighting the channel walls and
  the inner faces of nearby fins, NOT washing out over the outer fin fronts.
- `C:\Users\hooki\OneDrive\Pictures\Screenshots\BITMAP4331_1_{mid,detail}.png`
  — E-mu hardware behavior reference.
- X3 module screenshots (Tyson posted 2026-06-11): cyan/teal accent culture of
  the host UI.

## What was wrong with Claude's attempt (Tyson's rejection)

Claude placed two emissive spheres (bead + tail) at y=-0.92 inside the channel
and rendered through Cycles. Result at `dev/tmp/thumbwheel_blender/test_glow.png`:
a white-hot blown core with a generic radial bloom — reads as an overexposed
lamp in front of the wheel, not as light living inside the mechanism. Likely
failure ingredients to fix or replace wholesale:
- emission strength blows out to white (loses ALL cyan in the core),
- spill lights the outer fin fronts (breaks the "behind the aperture" read),
- symmetric round bloom (reference is asymmetric, channel-shaped, gated by
  the fin gaps),
- no unevenness — the trail is a smooth capsule, the reference trail flickers
  with the hole pattern.

## The working pipeline you are dropping into

Everything runs. Wheel = Tyson's own sculpted mesh `geometry_0` (325k tris,
textured: Image_0 albedo 2048², Image_1 ORM) living in his OPEN Blender 5.0
instance, reachable over the Blender-MCP addon socket (localhost:9876).

- `juce-shell/tools/thumbwheel/_blender.py` — socket driver:
  `python _blender.py scene` · `python _blender.py code <file.py|->`
- `dev/tmp/thumbwheel_blender/rig_tyson.py` — builds scene **WheelRigT**:
  linked dup of geometry_0 ("WheelT", scale 2.0/2.0/2.67 → diameter 2.0 wide,
  0.55 tall), black world, area key (260W, 2.6m, top-front 34°) + weak fill,
  ortho camera scale 2.0, 0.5° tilt, Cycles GPU (OPTIX RTX 4060) 32 samples,
  596×160 output (exactly 4× the 149×40 well). Contains Claude's rejected
  glow emitters (GlowBeadT/GlowTailT spheres + GlowCyanT emission material) —
  replace freely.
- `dev/tmp/thumbwheel_blender/render_chunk_tyson.py.tmpl` — render loop
  template (`__START__`/`__END__` substituted per 16-frame chunk; full 360°
  over 128 frames so frame 128 pose == frame 0; skips existing files; sets
  bead x = lerp(-0.88, +0.88, i/128) and strength envelope
  `260·sin(π·t)^0.6` — zero at both ends).
- `dev/tmp/thumbwheel_blender/assemble_strip.py` — 128 renders → Lanczos
  149×40 → 19221×40 strip at
  `juce-shell/assets/ui/thumbwheel_runtime_strip_129_149x40.png`
  (slot 128 = byte copy of slot 0; validates). Old strip backed up at
  `dev/tmp/thumbwheel_blender/old_strip_backup.png`.
- `dev/tmp/thumbwheel_blender/preview_panel.py` — composites a test frame
  into the real panel art at editor scale; judge there, never on white.
- Build: kill any running TRENCH first (exe lock), then
  `cmake --build juce-shell\build --config Release --target TRENCH_Standalone --parallel 1`
  (BinaryData regenerates from assets/ui). Capture:
  `python juce-shell/tools/thumbwheel/capture_standalone.py <exe> <out.png> --keep`.

## Hard constraints (do not violate)

1. **Asset contract:** 129 frames, 149×40 each, frame 0 == frame 128
   byte-identical, both glowless. Editor maps value→frame 1:1.
2. The glow must be **baked into the frames** (it tracks value, frame tracks
   value — 1:1). No JUCE-side sprite.
3. Wheel geometry, material, lighting, camera, fit: **approved, frozen.**
4. Judge composited into the panel at 1:1 — Tyson catches every artifact.
   One verdict per change; don't stack tweaks.

## Directions worth considering (yours to choose)

- Light the channel, not the camera: emitter fully inside the channel with
  the fins gating it; clamp the core with a non-blowing exposure (e.g. lower
  strength + cyan-tinted falloff via blackbody-free emission, or composite a
  screen-space cyan curve in the compositor with proper hue preservation).
- Asymmetric trail: chain of small emitters with decaying strength (and
  jittered y/z) rather than one capsule — gives the uneven hole-gated flicker.
- Compositor pass: render glow on a separate view layer and grade it cyan
  with highlight rolloff (prevents white clipping by construction), then
  composite under/through the wheel layer's channel mask.
- Check every candidate at 149×40 — the hot core is ~4 px there; what reads
  as "blown" at 596 wide may read as "dead" at 149. Tyson judges at 1:1.

## Verify loop

1. Edit rig/template → `python _blender.py code dev/tmp/thumbwheel_blender/rig_tyson.py`
2. Render a single test frame at t≈0.7, composite with `preview_panel.py`
   (point FRAME at your test png), read `preview_zoom.png` AND the 1:1.
3. Only after Tyson approves the still: render 128, assemble, build, capture.
