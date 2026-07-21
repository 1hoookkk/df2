# TRENCH wheel-render recovery failure — 2026-07-20

Status: **REJECTED**

This document records the failed wheel-render experiment so it is not
mistaken for a usable recovery state.

## User-visible failure

The supplied capture shows both horizontal wheel wells rendered as nearly
solid black recesses. The authored roller silhouette, angled user-facing ribs,
front-side shadow, and travelling cyan packet are not readable. Only a thin
vertical cyan/grey seam remains near the centre of each well.

Evidence:

`C:\WINDOWS\TEMP\codex-clipboard-0fe17b8f-2c89-440d-8b46-523bca4d49aa.png`

This fails the approved wheel reference. A valid result must show the compact
black roller itself, with its oblique ribs and centre shadow visible, while
keeping Q at `0.0` completely unlit.

## Candidate that must not be promoted

The failed pass changed the wheel path to:

- preserve the supplied `BITMAP4331_2.bmp` frames at native `85x16`;
- embed `128` usable frames, excluding the duplicate wrap frame;
- scale the native frame in `WheelControl`;
- use `lowResamplingQuality` for a crisp nearest-style conversion;
- remove the software crown/highlight wash.

The relevant candidate files are:

- `plugin/assets/trench_roller_strip.png`
- `plugin/source/ui/WheelControl.h`
- `dev/build_raw_wheel_strip.py`

The Release FaceShot target did build successfully at:

`build\TRENCH_FaceShot_artefacts\Release\TRENCH_FaceShot.exe`

Build success is not visual success. The supplied capture rejects this
candidate, so it must not be called restored, crisp, or product-ready.

## Observed versus inferred

### OBSERVED

- The well becomes visually black.
- The wheel face is lost.
- A narrow vertical seam remains.
- The result does not preserve the reference wheel angle or readable glow.
- The failure affects both Morph and Q wells.

### INFERRED

- The current raster/draw contract is not preserving the horizontal filmstrip
  frame when converting the native bitmap into the live aperture.
- Nearest-style resampling is not an acceptable recovery strategy for this
  source and aperture combination.
- Removing the authored/physical highlight treatment without replacing the
  missing face contrast leaves the wheel unreadable.

These inferences require a fresh built screenshot and source-frame probe before
they become implementation law.

## Recovery boundary

Do not solve this by adding a rectangle, a painted cyan line, or a procedural
tooth field. Do not recolour the faceplate. The next candidate must be judged
against the supplied raw bitmap and the wheel references at the actual editor
scale, with:

1. the full roller silhouette seated inside the existing well;
2. the user-facing angled ribs and dark centre/front shadow visible;
3. the glow packet following value horizontally rather than collapsing into a
   vertical seam;
4. Morph `0.0` and Q `0.0` unlit, with no residual seam;
5. Morph around `50.8` showing the reference mid-strip orientation;
6. Morph `100.0` landing on the real terminal glow frame;
7. no new software rectangle around either well.

The beige faceplate, graph, readouts, labels, amount-side shadow, and top
controls are outside this failure unless a new comparison proves otherwise.

## Next-session note

Continue the wheel grind from this failure state. This wheel has proven harder
to recreate faithfully than recreating the original P2K ROM filters: treat the
wheel raster, angle, seating, and glow as the active recovery problem, not as a
small finishing detail.
