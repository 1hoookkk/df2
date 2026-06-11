#!/usr/bin/env python3
"""Bake two recessed-well shadows onto df2_brushed.png (Morph + Q roller wells)
so each roller sits in a carved recess. Writes a SEPARATE *_shadowed.png for
review; the real faceplate is only swapped after approval. Also composites the
bone+UV target roller into each well for the preview.
"""
from pathlib import Path
from PIL import Image, ImageFilter

HERE = Path(__file__).parent
CHASSIS = HERE.parent.parent / "source" / "Assets" / "chassis_variants" / "df2_brushed.png"
OUT_PNG = HERE / "_preview" / "df2_brushed_shadowed.png"

# roller well rects (chassis-pixel space, from df2_brushed.layout.json)
WELLS = [("morph", 135, 703, 406, 86), ("q", 135, 879, 407, 91)]


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def smooth(t):
    t = clamp(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(len(a)))


def find_interior(px, x0, y0, w, h):
    """Bounding box of the TRANSPARENT cutout interior inside a well rect."""
    minx, miny, maxx, maxy = 10**9, 10**9, -1, -1
    for yy in range(y0, y0 + h):
        for xx in range(x0, x0 + w):
            if px[xx, yy][3] < 40:
                minx, miny = min(minx, xx), min(miny, yy)
                maxx, maxy = max(maxx, xx), max(maxy, yy)
    if maxx < 0:
        return None
    return minx, miny, maxx, maxy


# recessed slot floor: dark at top (occluded by upper lip) -> a touch lifted and
# light-caught at the bottom lip. Neutral, faintly cool to flatter the UV glow.
TOP_DARK = (16, 15, 18)
BOT_FLOOR = (40, 38, 42)
BOT_CATCH = (96, 92, 86)   # lower inner lip catches room light


def bake_well(img, x0, y0, w, h):
    px = img.load()
    interior = find_interior(px, x0, y0, w, h)
    if interior is None:
        print(f"  WARN: no interior found at {x0},{y0}")
        return
    ix0, iy0, ix1, iy1 = interior
    iw, ih = (ix1 - ix0 + 1), (iy1 - iy0 + 1)
    for yy in range(iy0, iy1 + 1):
        v = (yy - iy0) / max(1, ih - 1)            # 0 top .. 1 bottom
        # vertical recess gradient
        col = lerp(TOP_DARK, BOT_FLOOR, smooth(v))
        # bottom inner lip light catch (last ~12%)
        if v > 0.86:
            col = lerp(col, BOT_CATCH, smooth((v - 0.86) / 0.14))
        # strong top inner shadow (first ~16%)
        topk = 1.0
        if v < 0.16:
            topk = 0.55 + 0.45 * smooth(v / 0.16)
        for xx in range(ix0, ix1 + 1):
            if px[xx, yy][3] >= 40:
                continue  # leave the opaque bevel frame intact; fill only the cutout
            u = (xx - ix0) / max(1, iw - 1)
            # side vignette: darken left/right inner walls
            side = 1.0
            edge = min(u, 1.0 - u)
            if edge < 0.07:
                side = 0.62 + 0.38 * smooth(edge / 0.07)
            k = topk * side
            c = tuple(int(ch * k) for ch in col)
            px[xx, yy] = (*c, 255)
    # soft drop shadow on the faceplate just below the well (cast by the
    # protruding roller). Blend dark onto the existing brushed metal.
    sh_h = 9
    for yy in range(iy1 + 1, min(img.height, iy1 + 1 + sh_h)):
        t = (yy - iy1) / sh_h
        a = (1.0 - t) * 0.42
        for xx in range(ix0 - 2, ix1 + 3):
            if 0 <= xx < img.width:
                r, g, b, al = px[xx, yy]
                px[xx, yy] = (int(r * (1 - a)), int(g * (1 - a)), int(b * (1 - a)), al)
    print(f"  baked well interior {ix0},{iy0} {iw}x{ih}")


def composite_roller_preview(img):
    """Drop the bone+UV target roller into each well so the recess reads in
    context. Reference-only preview (uses the remastered 4331 face)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("rem", HERE / "_remaster4331_ref.py")
    rem = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rem)
    src = Image.open(rem.SRC).convert("RGB")
    faces = {"morph": rem.remastered_face(0.42, src), "q": rem.remastered_face(0.0, src)}
    orig = Image.open(CHASSIS).convert("RGBA")  # detect wells before they were filled
    opx = orig.load()
    for name, x0, y0, w, h in WELLS:
        interior = find_interior(opx, x0, y0, w, h)
        if not interior:
            continue
        ix0, iy0, ix1, iy1 = interior
        iw, ih = (ix1 - ix0 + 1), (iy1 - iy0 + 1)
        # roller overhangs the recess slightly (protrudes): margin negative
        mh = 2
        rw, rh = iw + 4, ih - 2 * mh + 6
        face = faces[name].resize((rw, rh), Image.Resampling.NEAREST).convert("RGBA")
        img.alpha_composite(face, (ix0 - 2, iy0 + mh - 3))


def main():
    img = Image.open(CHASSIS).convert("RGBA")
    print("baking shadows:")
    for name, x0, y0, w, h in WELLS:
        bake_well(img, x0, y0, w, h)
    img.save(OUT_PNG)
    print(f"wrote {OUT_PNG}")
    # preview crop (no roller) and with roller composited
    img.crop((90, 650, 820, 1010)).save(HERE / "_preview" / "faceplate_shadowed_bare.png")
    prev = img.copy()
    composite_roller_preview(prev)
    prev.crop((90, 650, 820, 1010)).save(HERE / "_preview" / "faceplate_shadowed_rollers.png")
    print("wrote preview crops")


if __name__ == "__main__":
    main()
