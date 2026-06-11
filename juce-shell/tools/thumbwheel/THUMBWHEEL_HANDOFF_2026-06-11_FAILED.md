# Thumbwheel handoff — 2026-06-11 — GOAL FAILED, THINK DIFFERENTLY

Supersedes `THUMBWHEEL_FINAL_HANDOFF_2026-06-08.md` and
`THUMBWHEEL_STRUGGLE_HANDOFF_2026-06-08.md` (keep them for context only).

## Verdict

Tyson's final words this session: **"There's gaps at the top too… consider the
goal failed and for the next chat to think differently."**

~20 visual iterations across three rendering methods all failed the same way:
the wheel keeps reading as **assembled bits** (bricks, teeth, tracks, clumps,
disconnected segments, gaps) instead of ONE solid tactile thumbwheel you want
to spin. Do not iterate parameters on the current pipeline. Change the method.

## The goal (unchanged)

A horizontal hardware thumbwheel in the two black wells (Morph, Q), bone-white
plastic ABS, inviting a left-right drag. One continuous body seen through the
slot; fins are carved interruptions; broad fixed light; dark mechanical
aperture in the middle; cyan glow INTERNAL behind that mask (hot bead + short
uneven trail, position tracks value, fades as it travels); the surface visibly
spins under coherent fixed lighting when dragged. It must sit in the well with
real depth (lip overhang, contact shadow, faceplate cast shadow).

Reference images (re-read these before doing anything):
- `juce-shell/tools/thumbwheel/reference_bone_wheel.png` — THE target material
  (Tyson's own generated render, clean to ship; 1916x821, wheel at
  rows ~235-545, purple glow on its right side — use the clean left 2/3).
- `C:\Users\hooki\OneDrive\Pictures\Screenshots\BITMAP4331_1_{mid,detail}.png`
  and `roller_frames_17px.png` — E-mu behavior reference (reference-only).

## HARD-WON runtime facts — keep these, they are verified

1. **True well opening is 149 x 40 editor px** (measured from
   `df2_panel_shadow.png` dark region: morph opening x=44.3 y=242.2 w=148.0
   h=40.1; q similar). The editor's well rect constant (35.5 tall) is WRONG —
   any frame sized to it leaves uncovered black bands ("doesn't fit the well").
2. **Asset contract now**: `assets/ui/thumbwheel_runtime_strip_129_149x40.png`,
   19221x40, 129 frames, crop x = frame*149, frame 0 == frame 128
   byte-identical, both glowless. Editor constants 149/40 in
   `PluginEditor.cpp`; it clips to the frame (`dstInt`), not the stale well
   rect, and draws 1:1.
3. **JUCE drawImage opacity bug (was THE invisible killer)**: `drawImage` is
   modulated by the leftover Graphics colour alpha; the shadow pass before it
   left alpha 0.07 → the wheel rendered at 7% brightness for MONTHS of
   attempts. Fixed with `g.setOpacity(1.0f)` in `drawThumbwheelFrame`. Keep it.
4. **PIL ImageDraw REPLACES pixels** (no alpha blending) on RGBA images —
   semi-transparent fills punch low-alpha holes that show the black well
   through the art. Soft elements must be drawn on separate layers and
   `alpha_composite()`d.
5. **Verification loop that works**: generator `--preview` composites single
   frames into the real panel art (judge there, never on a white background);
   `capture_standalone.py <exe> <out> [--keep]` PrintWindow-captures the real
   plugin (`--keep` leaves it open for Tyson); `capture_running.py` attaches
   to a live window (pick the 362x562 one — the FORGE web window also matches
   "TRENCH"). Numeric check: captured well luma must EQUAL strip luma.
6. Build: kill TRENCH first (a running standalone locks the exe → LNK1104),
   then `cmake --build juce-shell\build --config Release --target
   TRENCH_Standalone --parallel 1`. BinaryData regenerates from assets/ui
   automatically.
7. The faceplate depth shadow (penumbra + contact core under the wheel
   footprint) lives in `drawFrontPanelShadows` / `drawWheelDepthShadow`.
   Tyson confirmed the shadows do NOT ruin it.

## What was tried and how each failed (do not repeat)

All in `tools/thumbwheel/render_thumbwheel_strip.py` (current file = method C):

- **A. Procedural per-pixel gradient fields** (bands + notch gaussians + light
  pools): every variant read as bricks / tank tracks / keyboard teeth / rocks
  / "hyper-real 3D render" / "too soft cartoon". Parameter tuning never
  converged across ~12 verdicts.
- **B. Facet painter** (explicit polygons per fin at 4x supersampling):
  "absolutely ruined" (PIL alpha-replace bug), then after the fix still
  "a silly thing" — crisp but graphic/toy-like.
- **C. Photo-derived** (texture/lighting separation from
  `reference_bone_wheel.png`: detail = photo / horizontal lowpass, scrolls;
  vertical row-light profile fixed; fins re-tiled to an exact 149px loop):
  best material so far ("good, polish it") but died on assembly artifacts:
  - vertical squash 309→27 rows aliases everything → "clumped together"
    (partially fixed by pre-blur + deepened aperture valley)
  - tile/stride mismatch → fin lattice phase jumps → "disconnected bits"
    (groove-aligned slicing helped but seams/gaps persisted)
  - "gaps at the top" — the caps don't connect to the well top; the slice
    rows carry the photo's own inter-fin gap and lip darkness, so the top
    edge reads as floating separate caps.

**The common failure**: synthesizing or re-assembling the wheel from parts at
27-40px tall produces visible part boundaries. The eye catches every joint.

## Think differently — directions for the next chat (pick ONE, commit)

1. **Render a real 3D wheel** (strongest candidate). A Blender MCP server is
   available in this environment (`mcp__blender__*`). Model an actual ribbed
   thumbwheel cylinder once, light it once (broad top light), camera through a
   slot mask, and render 129 frames by ROTATING the wheel exactly one fin
   pitch... no — rotate so frame 128 lands on an identical pose (fin count ×
   integer). Geometry, lighting, occlusion, corner rolloff, and coherent
   motion all come for free. Composite the cyan emitter as a small emissive
   object inside the barrel. Downscale renders to 149x40. No assembly, no
   seams, no per-pixel invention.
2. **Whole-image art, no re-synthesis**: have Tyson generate (he already makes
   these renders) a glow-free bone wheel image AT THE RIGHT ASPECT (slot
   ~5.3:1, e.g. 1590x430) so no squash/re-tiling is needed. Downscale the
   WHOLE image to 149x40 once. Motion = wrap-scroll the whole image
   horizontally (it only needs to be seamless at one wrap point — ask the
   image tool for a tileable wheel, or mirror-pad). Glow = the proven sprite
   pass. The 2026-06-11 session proved downscaled photo material looks right;
   it died only from slicing/re-assembly. Eliminate the assembly, not the
   photo.
3. If both fail, consider 2x-resolution strip + JUCE downscale-on-draw
   (highResamplingQuality) so the raster has room, or vector-draw in JUCE at
   paint time. Last resorts.

Also genuinely consider asking Tyson for ONE more reference: a straight-on,
glow-free, full-slot wheel image. He produces exactly what he wants with image
tools faster than parameter iteration can chase it.

## Working-with-Tyson notes from this session

- He judges IN CONTEXT at 1:1 — always composite into the panel art and build
  + capture before claiming anything. He catches every seam ("caught red
  handed").
- Leave the standalone OPEN after capture (`--keep`) — "don't just open it for
  one second."
- One verdict per change; don't stack three tweaks and ask which helped.
- His taste constants (stable across the whole session): bone-white clean ABS,
  fins as carved interruptions of ONE body, light pools not uniform glare,
  edge-to-edge with rolloff AT the ends (no inward vignette), strong internal
  glow with a small trail that fades along travel, real depth shadows.
