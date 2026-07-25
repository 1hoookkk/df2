# Build the compact-editor thumbwheel strip: THE AMBER WHEEL with THE GLOW
# LOGIC (Tyson 2026-07-19: "Amber one looks best. Lacks the glow though" +
# "follow the glow logic. You can read about it in the docs").
#
# BODY = one deterministic graphite roller, generated below at 4x and reduced
# once to the native 200x42 frame. The rejected AI/Blender body had two stacked
# lobes and broken top geometry, so it read as a wheel clipping into itself.
#
# GLOW = df2/dev/tmp/thumbwheel_blender/glow_pass.py, THE documented logic
# (CLAUDE_HANDOFF_2026-06-13_GLOW_REFINEMENT.md), ported with y-geometry
# adjusted from its 149x40 frames to this body's 200x42:
#   - _detect_diode_centers: THIS wheel's physical slot positions per frame
#     (detrended luma peaks in the channel band — survives the light gradient)
#   - _bead_progress_profile: each diode rises dark->full in exactly 5
#     authored frames, starts spread so the last diode finishes at frame 255;
#     lit diodes age (trail exp(-age/40), hold floor 0.08) and diffuse wider
#     with age; a soft leading bead tracks the current position
#   - three passes: subtle internal halo + saturated bead band + bright core
#     pin, gated by the wheel's ribs; weights lifted ~1.5x from the module's
#     bone-body tuning because this smoked body is far darker, all gated by the wheel's
#     own ribs (bright gap columns pass light, dark rib columns block)
#   - palette = the module's own "bakelite" ramp (warm phosphor-amber):
#     dim [168,84,22] / mid [255,178,70] / core [255,224,156]
# Runtime note: our WheelControl maps v=1 to frame 256 (no loop contract),
# so frame 256 holds the fully-lit pose instead of the old copy-of-frame-0.
#
# REJECTED: this procedural capsule candidate is retained only as historical
# evidence. It must not be run or used as a production visual source. The
# production source is the supplied GLB pass pipeline in
# tools/render_glb_wheel_257.py and tools/assemble_glb_wheel_257.py.
raise SystemExit(
    "Rejected procedural capsule candidate; use the supplied GLB wheel pipeline instead."
)

# The production atlas is 400x96 per frame. The old 200x42/300x68 candidates
# remain below only as rejected historical code.
import numpy as np
from PIL import Image
from pathlib import Path

OUT = Path(r"C:\Users\hooki\df2-workstation\plugin\assets")

NF = 257
SFW, SFH = 200, 42
FW, FH = SFW, SFH

# glow_pass.py geometry, scaled 40 -> 42 rows
GLOW_Y = 18.3
BAND_ROWS = (13, 20)          # slot/rib detection rows
HALO_ROWS = (6, 33)
BEAD_ROWS = (9, 24)
PIN_ROWS = (10, 23)
AUTHORED_PROGRESS_FRAMES = 255.0
DIODE_RISE_FRAMES = 5.0

# palette: "bakelite" (warm phosphor-amber) or the face accent (#2BD8C3
# family, one-lit-voice with the screen). The shipped face is bakelite.
import os
PALETTE = os.environ.get("WHEEL_PALETTE", "bakelite")
_RAMPS = {
    "bakelite": ([168.0, 84.0, 22.0], [255.0, 178.0, 70.0], [255.0, 224.0, 156.0]),
    "accent_teal": ([10.0, 88.0, 80.0], [43.0, 216.0, 195.0], [166.0, 255.0, 240.0]),
}
DIM, MID, CORE = (np.array(c, dtype=np.float32) for c in _RAMPS[PALETTE])


def smoothstep(e0, e1, x):
    if e0 == e1:
        return 1.0 if x >= e1 else 0.0
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3.0 - 2.0 * t)


def smoothstep_arr(e0, e1, v):
    t = np.clip((v - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def detect_diode_centers(slot_smooth, x0, x1):
    span = max(1, x1 - x0)
    region = slot_smooth[x0:x1]
    if len(region) < 16:
        return np.linspace(0.0, float(span - 1), 13, dtype=np.float32)
    smoothed = np.convolve(region, np.ones(5, np.float32) / 5.0, mode="same")
    trend = np.convolve(smoothed, np.ones(15, np.float32) / 15.0, mode="same")
    detrended = smoothed - trend
    lo, hi = np.percentile(detrended, [10, 90])
    norm = np.clip((detrended - lo) / max(1e-5, hi - lo), 0.0, 1.0)
    peaks = []
    min_dist = max(5, int(round(span / 22.0)))
    for i in range(2, len(norm) - 2):
        if norm[i] < 0.38:
            continue
        if norm[i] < norm[i - 1] or norm[i] < norm[i + 1]:
            continue
        if norm[i] < norm[i - 2] or norm[i] < norm[i + 2]:
            continue
        if not peaks or i - peaks[-1] >= min_dist:
            peaks.append(i)
        elif norm[i] > norm[peaks[-1]]:
            peaks[-1] = i
    centers = [float(p) for p in peaks if 5 < p < span - 5]
    if len(centers) < 8 or len(centers) > 20:
        return np.linspace(0.0, float(span - 1), 13, dtype=np.float32)
    return np.asarray(centers, dtype=np.float32)


def bead_progress_profile(value, span, diode_centers):
    if value <= 0.002:
        return np.zeros(span, dtype=np.float32)
    if len(diode_centers) < 2:
        diode_centers = np.linspace(0.0, float(span - 1), 13, dtype=np.float32)
    frame = max(0.0, min(1.0, value)) * AUTHORED_PROGRESS_FRAMES
    diode_count = len(diode_centers)
    last_start = max(0.0, AUTHORED_PROGRESS_FRAMES - DIODE_RISE_FRAMES)
    start_frames = np.linspace(0.0, last_start, diode_count, dtype=np.float32)
    xs = np.arange(span, dtype=np.float32)
    spacing = np.diff(diode_centers)
    median_spacing = float(np.median(spacing)) if len(spacing) else span / 13.0
    bead_sigma = max(1.45, median_spacing * 0.22)
    profile = np.zeros(span, dtype=np.float32)
    for start, center in zip(start_frames, diode_centers):
        ramp = smoothstep(float(start), float(start + DIODE_RISE_FRAMES), frame)
        if ramp <= 0.001:
            continue
        age = max(0.0, frame - float(start + DIODE_RISE_FRAMES))
        trail = float(np.exp(-age / 40.0))
        hold = 0.08 + 0.92 * trail
        amp = ramp * hold
        width_scale = 1.0 + 1.6 * (age / AUTHORED_PROGRESS_FRAMES)
        profile += amp * np.exp(-((xs - center) / (bead_sigma * width_scale)) ** 2)
    lead_x = float(np.interp(frame,
                             start_frames + DIODE_RISE_FRAMES * 0.5,
                             diode_centers,
                             left=diode_centers[0], right=diode_centers[-1]))
    lead = np.exp(-((xs - lead_x) / (bead_sigma * 2.5)) ** 2).astype(np.float32)
    profile = profile * 0.90 + lead * 0.10
    profile = np.convolve(profile, np.array([0.05, 0.16, 0.58, 0.16, 0.05], np.float32), mode="same")
    return np.clip(profile, 0.0, 1.0)


def apply_lamp(frame_rgba, value):
    """The three documented lamp passes, on an already-finished body."""
    out = frame_rgba.copy()
    h, w = out.shape[:2]
    alpha = out[..., 3].astype(np.float32) / 255.0
    luma = out[..., :3].astype(np.float32).mean(axis=-1) / 255.0

    band = alpha[BAND_ROWS[0]:BAND_ROWS[1], :].mean(axis=0) > 0.12
    valid_x = np.nonzero(band)[0]
    if len(valid_x) == 0 or value <= 0.002:
        return out
    x0, x1 = int(valid_x.min()) + 2, int(valid_x.max()) - 2
    span = max(8, x1 - x0)

    slot = luma[BAND_ROWS[0]:BAND_ROWS[1], :].mean(axis=0)
    slot_smooth = np.convolve(slot, np.ones(3, np.float32) / 3.0, mode="same")
    lo, hi = np.percentile(slot_smooth[x0:x1], [15, 85])
    gate_all = np.clip((slot_smooth - lo) / max(1e-5, hi - lo), 0.15, 1.0)
    diode_centers = detect_diode_centers(slot_smooth, x0, x1)

    bead_profile = bead_progress_profile(value, span, diode_centers)
    if float(bead_profile.max()) <= 0.001:
        return out

    rgbf = out[..., :3].astype(np.float32)
    yy = np.arange(h, dtype=np.float32)
    # gate floor 0.40->0.68: on this dark body a deep rib dip times an aged
    # trail crushed mid-run beads to invisible (the circled void). The ribs
    # still modulate; the trail now fades instead of strobing out.
    internal_gate = np.clip(gate_all, 0.68, 1.0)

    # Pass 1: subtle internal halo (screen, <=12%)
    halo_columns = np.zeros(w, dtype=np.float32)
    halo_columns[x0:x1] = bead_profile[:x1 - x0] * internal_gate[x0:x1]
    halo_columns = np.convolve(
        halo_columns,
        np.array([0.015, 0.035, 0.065, 0.105, 0.155, 0.25, 0.155, 0.105, 0.065, 0.035, 0.015], np.float32),
        mode="same")
    lamp1 = DIM * 0.40 + MID * 0.60
    vert1 = np.exp(-((yy - GLOW_Y) / 7.5) ** 2)
    w1 = np.minimum(0.26, halo_columns[None, :] * vert1[:, None] * 0.26)
    w1[:HALO_ROWS[0]] = 0; w1[HALO_ROWS[1]:] = 0
    w1 = w1 * (alpha > 0.03)
    screen1 = 255.0 - (255.0 - rgbf) * (255.0 - lamp1[None, None]) / 255.0
    rgbf = rgbf * (1.0 - w1[..., None]) + screen1 * w1[..., None]

    # Pass 2: saturated bead band (mix, <=78%)
    glow_columns = np.zeros(w, dtype=np.float32)
    glow_columns[x0:x1] = np.clip(bead_profile[:x1 - x0] ** 0.74, 0.0, 1.0) * internal_gate[x0:x1]
    glow_columns = np.convolve(
        glow_columns, np.array([0.04, 0.11, 0.21, 0.28, 0.21, 0.11, 0.04], np.float32), mode="same")
    t2 = np.minimum(1.0, glow_columns)
    lamp2 = DIM[None, :] * (1.0 - t2[:, None]) + MID[None, :] * t2[:, None]
    vert2 = np.exp(-((yy - GLOW_Y) / 3.5) ** 2)
    w2 = np.minimum(1.00, glow_columns[None, :] * vert2[:, None] * 1.80)
    w2[:BEAD_ROWS[0]] = 0; w2[BEAD_ROWS[1]:] = 0
    w2 = w2 * (alpha > 0.03)
    rgbf = rgbf * (1.0 - w2[..., None]) + lamp2[None, :, :] * w2[..., None]

    # Pass 3: bright core pin at the bead (screen, <=38%)
    pin = np.zeros(w, dtype=np.float32)
    pin[x0:x0 + span] = bead_profile ** 0.72 * (0.72 + gate_all[x0:x0 + span] * 0.28)
    t3 = np.minimum(1.0, pin)
    frac = np.clip((t3 - 0.85) / 0.15, 0.0, 1.0) * 0.5
    lamp3 = np.where(t3[:, None] < 0.85,
                     DIM[None, :] * (1.0 - t3[:, None]) + MID[None, :] * t3[:, None],
                     MID[None, :] * (1.0 - frac[:, None]) + CORE[None, :] * frac[:, None])
    dy = np.abs(yy - GLOW_Y)
    vert3 = np.where(dy <= 1.2, 1.0, np.exp(-((dy - 1.2) / 1.7) ** 2))
    w3 = np.minimum(0.80, t3[None, :] * vert3[:, None] * 0.80)
    w3[:PIN_ROWS[0]] = 0; w3[PIN_ROWS[1]:] = 0
    w3 = w3 * (alpha > 0.03) * (t3[None, :] > 0.045)
    screen3 = 255.0 - (255.0 - rgbf) * (255.0 - lamp3[None, :, :]) / 255.0
    rgbf = rgbf * (1.0 - w3[..., None]) + screen3 * w3[..., None]

    out[..., :3] = np.clip(rgbf, 0, 255).astype(np.uint8)
    return out


def build_single_body_frame(frame_index):
    """A single capsule at 4x: no seam, twin lobe, crop, or AI surface noise."""
    scale = 4
    h, w = SFH * scale, SFW * scale
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    x = (xx + 0.5) / scale
    y = (yy + 0.5) / scale

    cy = (SFH - 1) * 0.5
    radius = 17.8
    left_centre = 8.0 + radius
    right_centre = (SFW - 1) - 8.0 - radius
    nearest_x = np.clip(x, left_centre, right_centre)
    signed_distance = np.sqrt((x - nearest_x) ** 2 + (y - cy) ** 2) - radius
    alpha = np.clip(0.65 - signed_distance, 0.0, 1.0)

    yn = np.clip((y - cy) / radius, -1.0, 1.0)
    crown = np.sqrt(np.clip(1.0 - yn * yn, 0.0, 1.0))
    room_light = 12.0 + 50.0 * crown
    room_light += 46.0 * np.exp(-((yn + 0.38) / 0.18) ** 2)
    room_light -= 17.0 * np.exp(-((yn - 0.72) / 0.22) ** 2)

    end_distance = np.minimum(x - 8.0, (SFW - 1) - 8.0 - x)
    end_falloff = np.clip(end_distance / 20.0, 0.28, 1.0)
    room_light *= 0.62 + 0.38 * end_falloff

    # One family of traction grooves crosses the whole body. Rotating the
    # phase gives movement without inventing a second stacked roller.
    pitch = 10.6
    travel = 4.0 * pitch * frame_index / max(NF - 1, 1)
    phase_x = x + travel + (y - cy) * 0.16
    cell = np.mod(phase_x + pitch * 0.5, pitch) - pitch * 0.5
    groove = np.exp(-((cell / 0.78) ** 2))
    shoulder = np.exp(-(((np.abs(cell) - 1.35) / 0.72) ** 2))
    material = room_light * (1.0 - 0.66 * groove) + 13.0 * shoulder

    # Thin rim catches make the silhouette legible at 326px editor width.
    edge_catch = np.exp(-((signed_distance + 0.75) / 0.62) ** 2)
    material += 27.0 * edge_catch
    material = np.clip(material, 4.0, 132.0)

    rgb = np.stack([material * 0.93, material * 0.97, material], axis=-1)
    rgba = np.dstack([rgb, alpha[..., None] * 255.0])
    hi = Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8), "RGBA")
    return np.asarray(hi.resize((SFW, SFH), Image.Resampling.LANCZOS), dtype=np.uint8)


base_frames = [build_single_body_frame(i) for i in range(NF)]

# --- lamp per frame (v=1 -> fully lit; no loop contract) ---
lit_frames = []
for i in range(NF):
    v = min(i, 255) / 255.0
    lit_frames.append(apply_lamp(base_frames[i], v))

# --- ship at NATIVE source resolution (200x42, kStripDrawScale=1): the old
# 300x68 LANCZOS upscale + the widget's fractional downscale double-resampled
# the fins into a ghosted "wheel rendering into itself" (2026-07-19 verdict).
# ONE resample happens, at draw time, from the crisp source.
strip = np.concatenate(lit_frames, axis=1)
assert strip.shape == (SFH, SFW * NF, 4), strip.shape
Image.fromarray(strip).save(OUT / "trench_roller_strip.png")
print("strip:", strip.shape, "->", OUT / "trench_roller_strip.png")

# Law checks: dark at v=0; warm light advances left-to-right; v=1 fully lit.
for f in (0, 64, 128, 192, 256):
    a = strip[:, f * SFW:(f + 1) * SFW, :].astype(np.float32)
    wrm = np.clip(a[..., 0] - a[..., 2] - 25, 0, None) * (a[..., 3] / 255.0)
    v = f / (NF - 1)
    if wrm.sum() < 1e-3:
        print(f"v={v:.2f}  lamp dark")
        continue
    cols = wrm.sum(axis=0)
    cx = float((cols * np.arange(SFW)).sum() / cols.sum())
    lead = float(np.percentile(np.nonzero(cols > 0.10 * cols.max())[0], 98))
    print(f"v={v:.2f}  lit centroid={cx / max(SFW - 1, 1):.2f}  lead edge={lead / max(SFW - 1, 1):.2f}")
