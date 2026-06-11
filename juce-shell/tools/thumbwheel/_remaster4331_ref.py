#!/usr/bin/env python3
"""REFERENCE-ONLY remaster of E-mu BITMAP4331 into bone-white + ultraviolet, to
show the TARGET look in our colours. Source-derived -> NEVER shipped; this is the
clean-room comparison surface only. The authored generator must reproduce this
character with original pixels.
"""
from pathlib import Path
from PIL import Image

HERE = Path(__file__).parent
OUT = HERE / "_preview"
SRC = Path(r"C:\Users\hooki\do-it\emu-x3-bitmap-dump\BITMAP4331_1.bmp")

FRAMES, SFW, SFH = 129, 85, 16
FACE_W, FACE_H = 96, 28  # 2x tall face for the scene

BONE = {"deep": (62, 61, 58), "shadow": (108, 107, 103), "base": (170, 170, 165),
        "mid": (206, 206, 201), "high": (236, 235, 230)}
UV_CORE = (233, 224, 255)
UV_DIM = (150, 132, 198)
PANEL = (196, 186, 166)
SLOT = (24, 22, 26)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def lerp(a, b, t):
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def bone(v):
    v = clamp(v, 0, 255)
    if v < 88:
        return lerp(BONE["deep"], BONE["shadow"], v / 88.0)
    if v < 150:
        return lerp(BONE["shadow"], BONE["base"], (v - 88) / 62.0)
    if v < 200:
        return lerp(BONE["base"], BONE["mid"], (v - 150) / 50.0)
    return lerp(BONE["mid"], BONE["high"], (v - 200) / 30.0)


def luma(r, g, b):
    return 0.299 * r + 0.587 * g + 0.114 * b


def is_cyan(r, g, b):
    return g > r + 14 and b > r + 14 and (g > 45 or b > 45)


def remap(r, g, b):
    y = luma(r, g, b)
    body = bone(36 + y * 2.25)          # lift dark grey -> bone-white, keep structure
    if is_cyan(r, g, b):
        chroma = max(r, g, b) - min(r, g, b)
        inten = clamp((y - 26) / 150.0, 0, 1) * clamp(chroma / 130.0, 0, 1)
        uv = lerp(UV_DIM, UV_CORE, clamp(inten * 1.4, 0, 1))
        return lerp(body, uv, clamp(inten * 1.7, 0, 1))
    return body


def remastered_face(norm, src):
    i = int(round(norm * (FRAMES - 1)))
    x0 = round(i * src.width / FRAMES)
    frame = src.crop((x0, 0, x0 + SFW, SFH))
    px = frame.load()
    out = Image.new("RGB", (SFW, SFH))
    op = out.load()
    for y in range(SFH):
        for x in range(SFW):
            op[x, y] = remap(*px[x, y])
    return out.resize((FACE_W, FACE_H), Image.Resampling.NEAREST)


def scene(face, S=4):
    mx, my = 8, 7
    CW, CH = (FACE_W + 2 * mx) * S, (FACE_H // 2 + 2 * my) * S
    # note: face is 2x tall; show at S/2 vertical effective by using S for width and S for height on FACE_H
    CH = (FACE_H + 2 * my) * S
    canvas = Image.new("RGB", (CW, CH), PANEL)
    cv = canvas.load()
    fx, fy = mx * S, my * S
    fw, fh = FACE_W * S, FACE_H * S
    for yy in range(CH):
        for xx in range(CW):
            if (fx - S) <= xx < (fx + fw + S) and (fy - S) <= yy < (fy + fh + S):
                ty = (yy - (fy - S)) / (fh + 2 * S)
                cv[xx, yy] = lerp((12, 11, 14), SLOT, ty * ty * (3 - 2 * ty))
            elif (fx - 3 * S) <= xx < (fx + fw + 3 * S):
                if (fy - 3 * S) <= yy < (fy - S):
                    cv[xx, yy] = lerp(PANEL, (236, 228, 212), 0.6)
                elif (fy + fh + S) <= yy < (fy + fh + 3 * S):
                    cv[xx, yy] = lerp(PANEL, (118, 110, 96), 0.6)
    canvas.paste(face.resize((fw, fh), Image.Resampling.NEAREST), (fx, fy))
    crown = Image.new("RGBA", (fw, max(1, S // 2)), (255, 250, 240, 60))
    canvas.paste(crown, (fx, fy), crown)
    sh = Image.new("RGBA", (fw + 2 * S, 3 * S), (0, 0, 0, 130))
    canvas.paste(sh, (fx - S, fy + fh - S), sh)
    return canvas


def main():
    src = Image.open(SRC).convert("RGB")
    norms = [0.0, 0.3, 0.6, 0.9, 1.0]
    cells = [scene(remastered_face(n, src), S=3) for n in norms]
    gap = 10
    W = sum(c.width for c in cells) + gap * (len(cells) - 1)
    H = max(c.height for c in cells)
    sheet = Image.new("RGB", (W, H), (70, 70, 74))
    x = 0
    for c in cells:
        sheet.paste(c, (x, 0)); x += c.width + gap
    sheet.save(OUT / "ref_target_remaster.png")
    print("wrote _preview/ref_target_remaster.png (REFERENCE ONLY, not shipped)  norms:", norms)


if __name__ == "__main__":
    main()
