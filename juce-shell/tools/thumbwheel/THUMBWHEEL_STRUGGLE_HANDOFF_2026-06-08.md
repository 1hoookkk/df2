# Thumbwheel Render — Struggle Handoff (2026-06-08, session 2)

Read `THUMBWHEEL_FINAL_HANDOFF_2026-06-08.md` first for the asset contract and
reference manifest. This file is the honest log of a session that **kept missing
the look** so you don't repeat the same misses. Tyson's live reaction is the
authority, above the older handoff text.

## TL;DR

- The renderer is `juce-shell/tools/thumbwheel/render_raw_85x11_strip.py` — a
  **procedural PIL renderer** (no Blender). It is the active path.
- It produces the two shipping strips, baked into the standalone via BinaryData:
  - `juce-shell/assets/ui/thumbwheel_strip_129_85x11.png` (raw, 10965×11)
  - `juce-shell/assets/ui/thumbwheel_runtime_strip_129_149x36.png` (19221×36)
- Current state: **3D-rounded vertical grip ribs** on a flat top-lit disc, with
  a cyan value bead that scrolls. Closest yet, NOT signed off.
- **Working tree is dirty and UNCOMMITTED.** The renderer + both PNGs are
  modified. Nothing committed this session.
- Tyson's mood by the end: frustrated, asked "is this impossible?" The honest
  answer given: no — procedural can get there, but trial-and-error against an
  unseen mental image is slow; the reliable escape is a true 3D Blender render.

## The loop you must not repeat

Every attempt below was rendered, built into the standalone, captured with
`capture_standalone.py` (PrintWindow), and **rejected by Tyson**. Each miss cost
a full ~1–2 min build. Do not keep guessing blind — see "What actually helped".

1. **Fin-pattern-first comb** (inherited). Evenly spaced `cuts[]` ≈ one
   screen-width period. → reads as tire / chain / cells / bubbles. Rejected
   (this was the starting violation the prior handoff already named).
2. **Body-first + irregular jittered grooves.** Still a placed series of
   grooves on a bright body. → "still reads as cells."
3. **Continuous fractal-noise carve** (from-scratch rewrite). Soft irregular
   dark interruptions, no grid. Structurally clean but → **"too dark !!!"** at
   real plugin size (read as a dark slot, not a lit insert).
4. **Brighter palette + lift body luma.** Fixed the darkness (core body luma
   40→96). → **"looks like trash, should look like you want to spin it left to
   right."** (Flat striped band, no tactility.)
5. **Convex roller / cylinder cross-section + scrolling ridges.** Gave it
   spin-feel and depth. → **"reads as horizontal drums; should look almost like
   flat disks."** (Convex bulge = drum = wrong.)
6. **Flat three-band disc: bright rectangular caps / dark mid-seam / grey
   lower face, segmented.** Matched the reference structure on paper. → **"looks
   like scales / reptile skin."** The horizontal mid-seam crossing the vertical
   rib gaps made a 2-D tile grid.
7. **Single vertical stripe per rib, no seam.** Killed the grid. → **"looks
   like shit, it's just striped."** Symmetric bright-center/dark-gap = flat
   painted stripes, no depth.
8. **3D-rounded ribs (current).** Each rib shaded as a half-cylinder lit from
   upper-left: highlight on the left flank, crest specular glint, dark right
   flank, dark occlusion valley between ribs. Off-centre asymmetry = raised
   ridge, not a flat stripe. Tyson picked this direction via AskUserQuestion.
   Awaiting verdict.

### The contradiction to hold in your head
- **Not a drum/cylinder** (attempt 5 rejected) — it must read FLAT.
- **Not flat stripes** (attempt 7 rejected) — it must have ridge depth.
- **Not a tile grid** (attempt 6 rejected) — only ONE division axis (vertical
  rib gaps); no horizontal seam.
- Resolution = a **flat disc face whose vertical ribs are individually
  3-D-rounded** (per-rib highlight/shadow), lit from one angle. That is attempt
  8 / the current code.

## What actually helped (do this first)

**Look at the real reference pixels.** Tyson's instruction "check the
references" was the turning point — I had been building from the handoff *text*,
not the images. Upscale and actually view:

- `C:\Users\hooki\OneDrive\Pictures\Screenshots\roller_start.png` — clearest.
- `C:\Users\hooki\OneDrive\Pictures\Screenshots\roller_frames_17px.png` — the
  tiny/low-height read (what survives at plugin size).
- `C:\Users\hooki\OneDrive\Pictures\Screenshots\BITMAP4331_1_mid.png` /
  `_detail.png`.
- `C:\Users\hooki\do-it\BITMAP4332_1.bmp` — the actual 129×(85×11) E-mu strip.

They are tiny (≈11–17px tall); open with `Image.open(...).resize(...,NEAREST)`
at 6–8×. Windows paths only (git-bash `/c/...` paths fail in Python here).

**What the references actually show:** a FLAT ribbed wheel face (not a drum).
A row of irregular bright rib tops, thin dark valleys between ribs, a darker
lower body, and the cyan/indicator as an internal cell at one x-position. The
ribs are coarse and irregular, bitmap-era. E-mu pixels are **reference-only** —
ship a production-original render (dirty bone ABS), not their bytes.

## Current renderer map (`render_raw_85x11_strip.py`)

- `ROW_FACE[11]` — flat top-lit vertical luma gradient (bright rows 1–3 →
  dark bottom). **No** dark mid-seam (a seam re-creates the reptile grid).
- `SEG = 6.5`, `NSEG = 14`, `SCROLL = SEG*NSEG` — rib width / count / scroll
  travel. `NSEG` integer ⇒ frame 0 == frame 128 (seamless loop) and `% NSEG`
  on hashes wraps cleanly.
- Per-rib 3-D shading (in `render_frame`): `ang=(u-0.5)π`,
  `diffuse=max(0,cos(ang+0.66))` (highlight left of crest),
  `spec=exp(-((u-0.30)/0.085)²)` (crest glint),
  `occ=smoothstep(0,gapw,edge_u)` (valley between ribs). Tune these for
  highlight strength / contrast / valley depth.
- `rib_cap(idx)` — per-rib brightness variation (some dim ribs).
- Cyan bead: `is_glow`, `tip = 3 + (frame/127)*(85-6)`, rows 3–7, hot+lead+tail,
  broken by `occ`. No glow on frame 0 / 128.
- `material_rgb` — dirty bone-ABS palette (brightened this session). Per Tyson:
  **if a visual check fails, fix geometry, not colour.**

### Likely tuning knobs if attempt 8 is "almost"
- Ridge contrast/depth: the `0.16 + 0.98*diffuse` and `0.26 + 0.74*occ` floors.
- Highlight position/asymmetry: the `+0.66` light angle and `u-0.30` spec
  centre. More asymmetry = rounder/more 3-D.
- Rib count/width: `SEG` (smaller = more ribs). `NSEG` controls spin speed.
- Coarseness: it may be too smooth/clean vs the gritty reference — add bitmap
  grit / irregular rib widths.

## Build + see loop (the only ground truth)

```powershell
python juce-shell\tools\thumbwheel\render_raw_85x11_strip.py
cmake --build juce-shell\build --config Release --target TRENCH_Standalone --parallel 1 -- /nodeReuse:false /v:minimal
python juce-shell\tools\thumbwheel\capture_standalone.py "juce-shell\build\TRENCH_artefacts\Release\Standalone\TRENCH.exe" "dev\tmp\thumbwheel_inplugin_capture.png"
```

- The strip is baked into BinaryData at build time, so **you must rebuild** to
  see a strip change in-plugin. Kill any running `TRENCH` first.
- Capture with **PrintWindow** (the helper already does). Never CopyFromScreen
  (stale-screenshot false-feedback trap, per the prior handoff).
- Always crop+zoom the wheel region (`img.crop((20,178,180,288))`) — at native
  362×562 the wheels are tiny and a contact sheet hides the real read.
- A 6× NEAREST contact sheet of frames [0,1,48,96,127] on a dark-well bg is the
  fast pre-build sanity check before paying for a build.

## Hard contract (don't break)

- 129 frames; raw 10965×11 (85×11/frame); runtime 19221×36 (149×36/frame).
- Frame 0 == frame 128, byte-identical, no glow (asserts in `render()` enforce
  size + identity — they have passed every attempt).
- No visible JUCE sliders, no panel/well redraw, no separate cyan overlay.

## Recommendation for next session

If attempt 8 (3-D ribs) still doesn't land after a couple of cheap knob turns,
**stop tuning the PIL renderer and switch to a true 3-D Blender render.** Tyson
declined it once for speed, but procedural keeps converging slowly because the
depth is faked per-pixel. A modeled disc + grip ridges + one light + baked
129-frame spin removes the guesswork. Assets exist to start from:
`juce-shell/tools/thumbwheel/_preview/blender/thumbwheel_work.blend`, and the
`thumbwheel-render` skill points at a Blender pipeline.

Above all: **render → build → PrintWindow → show Tyson, let him judge by eye.**
He is the only acceptance test. Do not declare it done from a contact sheet.
