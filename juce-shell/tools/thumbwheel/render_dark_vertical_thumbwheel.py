#!/usr/bin/env python3
"""Render a high-res TRENCH thumbwheel front mask and runtime-light previews.

Repo guide contract:
- the moving violet light is not baked as a line in the strip;
- the strip is the molded ABS/smoked front surface, with alpha/transmission;
- runtime draws the light behind the strip, so the wheel reveals it through the
  body and inter-rib clearances as the value turns.

The output path keeps the legacy filename because TrenchThumbwheel loads that
BinaryData symbol. The actual strip is 129 frames of 384 x 56 px.
"""

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


FRAMES = 129
FRAME_W = 384
FRAME_H = 56
AA = 3

SLOT = (4, 4, 6, 255)
UV_DIM = (118, 86, 206)
UV_CORE = (188, 158, 255)


def clamp(v, lo=0, hi=255):
    return max(lo, min(hi, int(round(v))))


def mix(a, b, t):
    return tuple(clamp(a[i] * (1.0 - t) + b[i] * t) for i in range(3))


def smoothstep(edge0, edge1, x):
    if edge0 == edge1:
        return 0.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def s(v):
    return int(round(v * AA))


def tooth_colour(x, y, w, h, idx, lower):
    tx = x / max(1, w - 1)
    ty = y / max(1, h - 1)
    vertical = math.exp(-((ty - (0.74 if lower else 0.26)) / 0.52) ** 2)
    left = math.exp(-((tx - 0.15) / 0.20) ** 2)
    crown = math.exp(-((tx - 0.46) / 0.44) ** 2)
    right = math.exp(-((tx - 0.96) / 0.20) ** 2)
    face_bulge = math.sin(math.pi * max(0.0, min(1.0, ty)))

    v = 44 + 126 * vertical + 18 * face_bulge
    v += 30 * left + 16 * crown
    v -= 42 * right
    grain = (math.sin((x + idx * 19) * 0.027) + math.sin((y + idx * 7) * 0.041)) * 1.6
    return (
        clamp(v + grain),
        clamp(v + 4 + grain),
        clamp(v + 1 + grain),
    )


def paste_tooth(base, box, idx, lower=False):
    x0, y0, x1, y1 = [s(v) for v in box]
    w = max(1, x1 - x0)
    h = max(1, y1 - y0)

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=s(3.8), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(s(0.22)))

    seg = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    seg_px = seg.load()
    mask_px = mask.load()
    for y in range(h):
        ty = y / max(1, h - 1)
        crown_opacity = math.exp(-((ty - (0.82 if lower else 0.18)) / 0.42) ** 2)
        for x in range(w):
            m = mask_px[x, y]
            if m == 0:
                continue
            r, g, b = tooth_colour(x, y, w, h, idx, lower)
            # Caps and lip-facing surfaces are more opaque. Bodies are slightly
            # translucent so the runtime UV field is embedded inside the wheel.
            alpha = (144 + 78 * crown_opacity) * (m / 255.0)
            seg_px[x, y] = (r, g, b, clamp(alpha))

    base.alpha_composite(seg, (x0, y0))


def make_mask_frame():
    img = Image.new("RGBA", (FRAME_W * AA, FRAME_H * AA), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    # Soft full-body underform: a translucent rounded cylinder beneath the
    # tooth blocks. This supplies the protruding mass without baking the moving
    # light into the strip.
    body = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bp = body.load()
    for yy in range(body.height):
        yn = yy / max(1, body.height - 1)
        crown = math.exp(-((yn - 0.30) / 0.22) ** 2)
        belly = math.exp(-((yn - 0.67) / 0.26) ** 2)
        centre_dip = math.exp(-((yn - 0.50) / 0.12) ** 2)
        for xx in range(body.width):
            xn = xx / max(1, body.width - 1)
            edge = min(xn, 1.0 - xn)
            edge_fade = smoothstep(0.00, 0.08, edge)
            shade = 34 + 92 * crown + 62 * belly - 42 * centre_dip
            alpha = (50 + 56 * (crown + belly) - 34 * centre_dip) * edge_fade
            bp[xx, yy] = (clamp(shade), clamp(shade + 3), clamp(shade), clamp(alpha))
    img.alpha_composite(body.filter(ImageFilter.GaussianBlur(s(0.35))))

    # Smoked central clearance: dark, but not opaque, so the light is behind it.
    d.rounded_rectangle((s(8), s(19.0), s(FRAME_W - 8), s(37.6)),
                        radius=s(5.0), fill=(3, 4, 5, 132))

    # Top and bottom occluding slot lips belong to the wheel silhouette.
    d.rectangle((0, 0, s(FRAME_W), s(4.2)), fill=(0, 0, 0, 245))
    d.rectangle((0, s(FRAME_H - 4.0), s(FRAME_W), s(FRAME_H)), fill=(0, 0, 0, 250))
    d.line((0, s(4.6), s(FRAME_W), s(4.6)), fill=(26, 27, 26, 210), width=s(1.2))
    d.line((0, s(FRAME_H - 6.2), s(FRAME_W), s(FRAME_H - 6.2)), fill=(3, 3, 3, 225), width=s(1.4))

    pitch = 24
    tooth_w = 15.6
    margin = 12
    x = margin
    idx = 0
    while x < FRAME_W - margin:
        wobble = ((idx % 5) - 2) * 0.14
        paste_tooth(img, (x + wobble, 5.2, x + tooth_w + wobble, 27.2), idx, lower=False)
        paste_tooth(img, (x - wobble * 0.55, 28.8, x + tooth_w - wobble * 0.55, 50.8), idx, lower=True)

        # Semi-transparent sidewalls/openings. The runtime light leaks through
        # these as shaped apertures, not as a pasted center-line highlight.
        wall_x = s(x + tooth_w - 0.8)
        d.rounded_rectangle((wall_x, s(18.6), wall_x + s(2.5), s(37.8)),
                            radius=s(1.4), fill=(2, 3, 4, 112))
        x += pitch
        idx += 1

    # Specular crown and lower belly shadow: small, surface-bound cues that make
    # the wheel feel like it is projecting toward the viewer.
    d.rounded_rectangle((s(14), s(6.2), s(FRAME_W - 14), s(10.2)),
                        radius=s(2.0), fill=(242, 242, 235, 38))
    d.rounded_rectangle((s(16), s(45.0), s(FRAME_W - 16), s(49.8)),
                        radius=s(2.4), fill=(18, 18, 18, 58))

    # End rolloff makes the cylinder recede at both ends.
    edge = Image.new("L", img.size, 0)
    ep = edge.load()
    for yy in range(edge.height):
        for xx in range(edge.width):
            x_native = xx / AA
            e = min(x_native, FRAME_W - 1 - x_native)
            fade = 1.0 - smoothstep(0.0, 15.0, e)
            ep[xx, yy] = clamp(170 * fade)
    dark = Image.new("RGBA", img.size, (0, 0, 0, 155))
    img = Image.composite(dark, img, edge)

    return img.resize((FRAME_W, FRAME_H), Image.Resampling.LANCZOS)


def back_light(norm, width=FRAME_W, height=FRAME_H):
    """Preview the C++ runtime light field behind the translucent mask."""
    img = Image.new("RGBA", (width, height), SLOT)
    if norm <= 0.0 or norm >= 1.0:
        return img

    px = img.load()
    lx = (0.06 + 0.84 * norm) * (width - 1)
    lead = width * 0.040
    tail = width * 0.155
    pitch = width / 16.0

    for y in range(height):
        yn = y / max(1, height - 1)
        upper = math.exp(-((yn - 0.38) / 0.24) ** 2)
        lower = math.exp(-((yn - 0.62) / 0.24) ** 2)
        center = math.exp(-((yn - 0.50) / 0.18) ** 2)
        vy = 0.45 * center + 0.34 * (upper + lower)
        if vy <= 0.01:
            continue

        for x in range(width):
            dx = x - lx
            hx = max(0.0, 1.0 - dx / lead) if dx >= 0 else max(0.0, 1.0 - (-dx) / tail)
            if hx <= 0.0:
                continue

            rib = 0.74 + 0.26 * math.cos((x / pitch) * math.tau)
            inten = (hx ** 1.30) * vy * rib
            if inten <= 0.012:
                continue

            col = mix(UV_DIM, UV_CORE, min(1.0, inten * 1.55))
            base = px[x, y]
            k = min(0.76, inten * 1.25)
            px[x, y] = (
                clamp(base[0] * (1.0 - k) + col[0] * k),
                clamp(base[1] * (1.0 - k) + col[1] * k),
                clamp(base[2] * (1.0 - k) + col[2] * k),
                255,
            )
    return img.filter(ImageFilter.GaussianBlur(0.35))


def composite(frame, norm):
    out = Image.new("RGBA", (FRAME_W, FRAME_H), (13, 13, 15, 255))
    d = ImageDraw.Draw(out, "RGBA")
    d.rounded_rectangle((1, 3, FRAME_W - 2, FRAME_H - 3), radius=10,
                        fill=(1, 1, 2, 255))
    d.rounded_rectangle((4, 5, FRAME_W - 5, FRAME_H - 7), radius=8,
                        fill=(4, 4, 6, 255))

    # Shadow first: this is what sells the wheel as a raised object sitting in
    # the slot rather than a flat bitmap pasted inside it.
    d.rounded_rectangle((8, 9, FRAME_W - 8, FRAME_H - 2), radius=8,
                        fill=(0, 0, 0, 112))
    d.rectangle((10, FRAME_H - 8, FRAME_W - 10, FRAME_H - 3), fill=(0, 0, 0, 105))

    out.alpha_composite(back_light(norm))
    out.alpha_composite(frame)

    d = ImageDraw.Draw(out, "RGBA")
    d.rounded_rectangle((16, 5, FRAME_W - 16, 9), radius=2,
                        fill=(255, 255, 246, 42))
    d.rectangle((10, FRAME_H - 7, FRAME_W - 10, FRAME_H - 4), fill=(0, 0, 0, 92))
    return out


def make_strip(frame):
    strip = Image.new("RGBA", (FRAME_W * FRAMES, FRAME_H), (0, 0, 0, 0))
    for i in range(FRAMES):
        strip.alpha_composite(frame, (i * FRAME_W, 0))
    return strip


def make_contact(frame):
    norms = [0.0, 0.08, 0.20, 0.36, 0.50, 0.64, 0.80, 0.92, 1.0]
    cols = 3
    gap = 12
    rows = math.ceil(len(norms) / cols)
    sheet = Image.new("RGBA", (cols * FRAME_W + (cols - 1) * gap,
                               rows * FRAME_H + (rows - 1) * gap),
                      (18, 18, 18, 255))
    for n, norm in enumerate(norms):
        cell = composite(frame, norm)
        sheet.alpha_composite(cell, ((n % cols) * (FRAME_W + gap),
                                     (n // cols) * (FRAME_H + gap)))
    return sheet


def make_plugin_size_preview(frame):
    norms = [0.0, 0.08, 0.20, 0.36, 0.50, 0.64, 0.80, 0.92, 1.0]
    cols = 3
    gap = 10
    preview_w, preview_h = 384, 56
    sheet = Image.new("RGBA", (cols * preview_w + (cols - 1) * gap,
                               3 * preview_h + 2 * gap),
                      (18, 18, 18, 255))
    for n, norm in enumerate(norms):
        cell = composite(frame, norm)
        tiny = cell.resize((96, 14), Image.Resampling.LANCZOS)
        preview = tiny.resize((preview_w, preview_h), Image.Resampling.BICUBIC)
        sheet.alpha_composite(preview, ((n % cols) * (preview_w + gap),
                                        (n // cols) * (preview_h + gap)))
    return sheet


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="juce-shell/assets/ui/native_strip_129_96x14.png")
    parser.add_argument("--contact", default="dev/tmp/dark_vertical_thumbwheel_contact.png")
    parser.add_argument("--preview", default="dev/tmp/dark_vertical_thumbwheel_plugin_size_preview.png")
    parser.add_argument("--mask", default="dev/tmp/dark_vertical_thumbwheel_mask.png")
    args = parser.parse_args()

    out = Path(args.out)
    contact = Path(args.contact)
    preview = Path(args.preview)
    mask = Path(args.mask)
    for path in (out, contact, preview, mask):
        path.parent.mkdir(parents=True, exist_ok=True)

    frame = make_mask_frame()
    strip = make_strip(frame)
    strip.save(out)
    make_contact(frame).save(contact)
    make_plugin_size_preview(frame).save(preview)
    frame.save(mask)

    print(f"wrote {out.resolve()} {strip.width}x{strip.height}")
    print(f"contact {contact.resolve()}")
    print(f"preview {preview.resolve()}")
    print(f"mask {mask.resolve()}")


if __name__ == "__main__":
    main()
