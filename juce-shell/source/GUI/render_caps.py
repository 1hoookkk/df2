"""
DF-II UI control sprite renderer.

Procedural 2D geometry, deterministic, rasterized to PNG at 2x source.
Per project rule: never Blender, never AI image gen for moving UI parts.

Outputs (all 2x source pixel sizes; runtime scales 0.5 large / 0.4463 default):
  assets/images/morph_shuttle_cap_2x.png       (70 x 38)
  assets/images/q_shuttle_cap_2x.png           (70 x 38, slightly meaner)
  assets/images/type_shuttle_cap_2x.png        (50 x 24)
  assets/images/long_rail_insert_2x.png        (455 x 108)
  assets/images/type_rail_insert_2x.png        (596 x 61)
  Source/GUI/_preview_*_4x.png                 supersample previews
  Source/GUI/_composite_test.png               full chassis composite test

Run:   python Source/GUI/render_caps.py
"""

from __future__ import annotations
import os, json, random
from PIL import Image, ImageDraw, ImageFilter, ImageChops

GUI_DIR  = os.path.dirname(os.path.abspath(__file__))
ROOT     = os.path.dirname(os.path.dirname(GUI_DIR))
ASSETS   = os.path.join(ROOT, "assets", "images")
LAYOUT   = json.load(open(os.path.join(GUI_DIR, "chassis_layout.json")))

# ============================================================================
# Palette — cool graphite ABS / Bakelite per v1 spec
# Linear-ish sRGB tuples (PIL works in sRGB directly)
# ============================================================================

P = {
    # MORPH cap — aged ivory phenolic Bakelite, tuned slightly warm to harmonize
    # with the copper chassis but cooler than chassis itself (separate but kin).
    "morph_top":      (212, 196, 160),   # warm cream catching light at top
    "morph_mid":      (184, 162, 122),   # transition into accumulated grime
    "morph_bot":      (140, 118,  86),   # aged dirty bottom
    "morph_rib_hi":   (232, 218, 180),   # crisp rib-top highlight (decades-polished)
    "morph_rib_mid":  (200, 178, 138),
    "morph_rib_lo":   ( 78,  56,  32),   # shadowed rib underside / groove

    # Q cap — same Bakelite family, dirtier / more aged
    "q_top":          (188, 170, 134),   # already dimmer than MORPH top
    "q_mid":          (158, 136, 100),
    "q_bot":          (112,  92,  64),
    "q_rib_hi":       (208, 192, 154),
    "q_rib_mid":      (170, 148, 110),
    "q_rib_lo":       ( 60,  42,  22),

    # Edges / details
    "edge_grime":     ( 90,  63,  34),   # rich brown rim wear
    "mold_seam":      ( 50,  34,  20),   # darker brown seam line
    "notch":          ( 31,  20,  16),   # deep dark cut

    # Rail bed — stays cool/dark to contrast cream cap
    "rail_bg_top":    ( 10,  11,  10),
    "rail_bg_bot":    (  3,   4,   3),
    "rail_gunmetal":  ( 58,  63,  60),
    "rail_endstop":   ( 24,  26,  24),
    "rail_scrape":    ( 42,  46,  43),
    "rail_grime_cyan":( 28,  60,  45),
}

# ============================================================================
# Helpers
# ============================================================================

def lerp(a, b, t): return a + (b - a) * t
def lerp_rgb(c1, c2, t):
    return tuple(int(round(lerp(c1[i], c2[i], t))) for i in range(3))

def vertical_gradient(size, stops):
    """stops = [(t in [0,1], (r,g,b)), ...]. Returns RGB image."""
    w, h = size
    col = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t <= t1:
                local = (t - t0) / max(1e-9, (t1 - t0))
                col.putpixel((0, y), lerp_rgb(c0, c1, local))
                break
        else:
            col.putpixel((0, y), stops[-1][1])
    return col.resize((w, h), Image.NEAREST)

def horizontal_gradient(size, stops):
    """Like vertical_gradient but horizontal."""
    w, h = size
    row = Image.new("RGB", (w, 1))
    for x in range(w):
        t = x / max(1, w - 1)
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t <= t1:
                local = (t - t0) / max(1e-9, (t1 - t0))
                row.putpixel((x, 0), lerp_rgb(c0, c1, local))
                break
        else:
            row.putpixel((x, 0), stops[-1][1])
    return row.resize((w, h), Image.NEAREST)

def rounded_rect_mask(size, radius):
    w, h = size
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1),
                                        radius=int(radius), fill=255)
    return m

# ============================================================================
# Asymmetric body silhouette — rounded rect, lower-right shoulder bump,
# off-center witness notch CUT into the bottom edge.
# ============================================================================

def asymmetric_body_mask(W, H, scale, shoulder=True, notch_offset_x=-8):
    """
    Build a single L-mode mask for the cap silhouette:
      - main rounded rect
      - small lower-right shoulder protrusion (subtle asymmetry)
      - witness notch cut into the lower edge, off-center (default left)
    """
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    # Main body
    d.rounded_rectangle((0, 0, W - 1, H - 1),
                        radius=int(6 * scale), fill=255)

    # Lower-right shoulder bump — adds an extra 2-3 px protrusion at lower-right
    if shoulder:
        bump_w = int(9 * scale)
        bump_h = int(3 * scale)
        bx = W - bump_w - int(3 * scale)
        by = H - int(scale * 0.5)   # touches bottom edge of body
        d.rounded_rectangle(
            (bx, by - bump_h, bx + bump_w, by + bump_h - 1),
            radius=int(scale * 0.8), fill=255
        )

    # Witness notch — cut OUT of the body bottom (fill 0 subtracts)
    nw = int(5 * scale)
    nh = int(3 * scale)
    nx = (W - nw) // 2 + int(notch_offset_x * scale * 0.5)
    ny = H - int(nh * 0.7)
    d.rounded_rectangle(
        (nx, ny, nx + nw, ny + nh + int(scale * 2)),  # extend below for clean cut
        radius=max(1, int(scale * 0.5)), fill=0
    )

    return m

# ============================================================================
# Generic cap renderer — used for MORPH (5 ribs), Q (5 ribs darker), TYPE (3 ribs)
# ============================================================================

def render_cap(name, target_w, target_h, body_stops, rib_stops,
               rib_count=5, scale=8, asym_shoulder=True, notch_offset=-8):
    W, H = target_w * scale, target_h * scale
    rng = random.Random(hash(name) & 0xffffffff)

    # 1. Body silhouette (with asymmetric shoulder + notch cut)
    body_mask = asymmetric_body_mask(W, H, scale,
                                     shoulder=asym_shoulder,
                                     notch_offset_x=notch_offset)
    body_grad = vertical_gradient((W, H), body_stops)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rgba = body_grad.convert("RGBA"); rgba.putalpha(body_mask)
    img.alpha_composite(rgba)

    # 2. Ribs — laid out with body breathing-room margins
    rib_x_inset = int(7 * scale)
    rib_y_top   = int(5.5 * scale)
    rib_y_bot   = H - int(7 * scale)   # leave room for notch + bottom margin
    rib_gap     = max(2, int(1.4 * scale))
    rib_total   = rib_y_bot - rib_y_top
    rib_h       = (rib_total - (rib_count - 1) * rib_gap) // rib_count

    last_rib_bottom_y = rib_y_top
    for i in range(rib_count):
        y0 = rib_y_top + i * (rib_h + rib_gap)
        y1 = y0 + rib_h
        x0, x1 = rib_x_inset, W - rib_x_inset
        rw, rh = x1 - x0, y1 - y0

        rib_grad = vertical_gradient((rw, rh), rib_stops)
        rib_mask = rounded_rect_mask((rw, rh), radius=int(rh / 2.4))
        rib_rgba = rib_grad.convert("RGBA"); rib_rgba.putalpha(rib_mask)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        layer.paste(rib_rgba, (x0, y0), rib_rgba)
        layer.putalpha(ImageChops.multiply(layer.split()[3], body_mask))
        img.alpha_composite(layer)

        # Soft cast-shadow under each rib (where rib meets body floor)
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle(
            (x0 + 2, y1, x1 - 2, min(H, y1 + max(1, scale // 2))),
            radius=int(rh / 4), fill=(0, 0, 0, 130))
        sh = sh.filter(ImageFilter.GaussianBlur(radius=max(1, scale * 0.3)))
        sh.putalpha(ImageChops.multiply(sh.split()[3], body_mask))
        img.alpha_composite(sh)
        last_rib_bottom_y = y1

    # 3. Mold seam — vertical thin line, ends ABOVE last rib bottom (no tailing)
    seam = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cx = W // 2
    seam_top = int(3 * scale)
    seam_bot = last_rib_bottom_y - max(1, scale // 2)
    ImageDraw.Draw(seam).line(
        [(cx, seam_top), (cx, seam_bot)],
        fill=(*P["mold_seam"], 130), width=max(1, scale // 4))
    seam.putalpha(ImageChops.multiply(seam.split()[3], body_mask))
    img.alpha_composite(seam)

    # 4. Asymmetric edge grime — heavier on left side & lower edge
    grime = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grime)
    edge_t = int(5 * scale)
    for d in range(edge_t):
        a = int(95 * (1 - d / edge_t) ** 1.4)
        gd.rounded_rectangle(
            (d, d, W - 1 - d, H - 1 - d),
            radius=max(1, int(6 * scale - d * 0.6)),
            outline=(*P["edge_grime"], a), width=1)
    grime = grime.filter(ImageFilter.GaussianBlur(radius=max(1, scale * 0.4)))
    grime.putalpha(ImageChops.multiply(grime.split()[3], body_mask))
    img.alpha_composite(grime)

    # 5. Heavier asymmetric grime patch — random dark blots, biased lower-left
    splotch = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(splotch)
    for _ in range(rng.randint(6, 10)):
        # bias positions toward lower-left for asymmetry
        cx_g = int(rng.gauss(W * 0.35, W * 0.2))
        cy_g = int(rng.gauss(H * 0.7, H * 0.15))
        r = rng.randint(int(2 * scale), int(5 * scale))
        a = rng.randint(40, 90)
        sd.ellipse((cx_g - r, cy_g - r, cx_g + r, cy_g + r),
                   fill=(*P["edge_grime"], a))
    splotch = splotch.filter(ImageFilter.GaussianBlur(radius=max(1, scale * 0.6)))
    splotch.putalpha(ImageChops.multiply(splotch.split()[3], body_mask))
    img.alpha_composite(splotch)

    # 6. Worn rib-top scuff streaks (short broken)
    scuffs = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sc = ImageDraw.Draw(scuffs)
    for i in range(rib_count):
        y0 = rib_y_top + i * (rib_h + rib_gap)
        y_top = y0 + max(1, int(rib_h * 0.18))
        for _ in range(rng.randint(2, 4)):
            sx0 = rng.randint(rib_x_inset + int(2 * scale),
                              W - rib_x_inset - int(8 * scale))
            sx1 = sx0 + rng.randint(int(2 * scale), int(7 * scale))
            sc.line([(sx0, y_top), (sx1, y_top)],
                    fill=(*P["morph_rib_hi"], 90), width=max(1, scale // 4))
    scuffs.putalpha(ImageChops.multiply(scuffs.split()[3], body_mask))
    img.alpha_composite(scuffs)

    # Save preview + final
    preview_path = os.path.join(GUI_DIR, f"_preview_{name}_4x.png")
    img.save(preview_path)
    final = img.resize((target_w, target_h), Image.LANCZOS)
    final_path = os.path.join(ASSETS, f"{name}_2x.png")
    final.save(final_path)
    print(f"  {name:32s} -> {target_w:3d}x{target_h:3d}  {final_path}")
    return final_path

# ============================================================================
# Specific cap configurations
# ============================================================================

def render_morph_cap(scale=8):
    # MORPH is the hero control — rendered larger than Q
    return render_cap(
        "morph_shuttle_cap", 282, 126,
        body_stops=[(0.0, P["morph_top"]), (0.5, P["morph_mid"]), (1.0, P["morph_bot"])],
        rib_stops=[(0.0, P["morph_rib_hi"]), (0.25, P["morph_rib_mid"]),
                   (1.0, P["morph_rib_lo"])],
        rib_count=5, scale=scale, asym_shoulder=True, notch_offset=-8,
    )

def render_q_cap(scale=8):
    return render_cap(
        "q_shuttle_cap", 200, 108,
        body_stops=[(0.0, P["q_top"]), (0.5, P["q_mid"]), (1.0, P["q_bot"])],
        rib_stops=[(0.0, P["q_rib_hi"]), (0.25, P["q_rib_mid"]),
                   (1.0, P["q_rib_lo"])],
        rib_count=5, scale=scale, asym_shoulder=True, notch_offset=+8,  # mirror notch right
    )

def render_type_cap(scale=8):
    # Tiny indexed shuttle — 3 ribs, smaller, no shoulder (too small to read)
    return render_cap(
        "type_shuttle_cap", 50, 24,
        body_stops=[(0.0, P["morph_top"]), (0.5, P["morph_mid"]), (1.0, P["morph_bot"])],
        rib_stops=[(0.0, P["morph_rib_hi"]), (0.25, P["morph_rib_mid"]),
                   (1.0, P["morph_rib_lo"])],
        rib_count=3, scale=scale, asym_shoulder=False, notch_offset=-4,
    )

# ============================================================================
# Rail inserts — dark charcoal trough behind the moving cap
# ============================================================================

def render_long_rail_insert(scale=4):
    """For MORPH/Q slots. Authored at Q slot interior (455 x 108)."""
    target_w, target_h = 455, 108
    W, H = target_w * scale, target_h * scale
    rng = random.Random(101)

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # Background trough — vertical gradient, slightly darker at the rear (top)
    bg = vertical_gradient((W, H), [
        (0.00, P["rail_bg_top"]),    # top is rear wall (deeper)
        (0.50, (6, 7, 6)),
        (1.00, P["rail_bg_bot"]),
    ])
    bg_rgba = bg.convert("RGBA")
    # Slightly rounded outer mask so rail doesn't spill past the slot
    rail_mask = rounded_rect_mask((W, H), radius=int(2 * scale))
    bg_rgba.putalpha(rail_mask)
    img.alpha_composite(bg_rgba)

    d = ImageDraw.Draw(img)

    # Two hairline gunmetal rails — one upper, one lower
    rail_y_upper = int(H * 0.22)
    rail_y_lower = int(H * 0.78)
    rail_thick = max(1, int(scale * 0.6))
    rail_alpha = 130
    rail_color = (*P["rail_gunmetal"], rail_alpha)
    # Inset rails so end stops can sit at the very edges
    rail_inset = int(6 * scale)
    d.line([(rail_inset, rail_y_upper), (W - rail_inset, rail_y_upper)],
           fill=rail_color, width=rail_thick)
    d.line([(rail_inset, rail_y_lower), (W - rail_inset, rail_y_lower)],
           fill=rail_color, width=rail_thick)

    # End stops — small vertical bars at extreme left + right
    stop_w = max(2, int(scale * 1.0))
    stop_h = int(H * 0.55)
    stop_y = (H - stop_h) // 2
    for x in (int(2 * scale), W - int(2 * scale) - stop_w):
        d.rounded_rectangle((x, stop_y, x + stop_w, stop_y + stop_h),
                            radius=int(scale * 0.4),
                            fill=(*P["rail_endstop"], 200))

    # Faint horizontal scrape marks — ~6 short streaks at low alpha
    scrape = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrape)
    for _ in range(8):
        y = rng.randint(int(H * 0.3), int(H * 0.7))
        x0 = rng.randint(int(W * 0.1), int(W * 0.4))
        x1 = x0 + rng.randint(int(W * 0.05), int(W * 0.25))
        a = rng.randint(20, 55)
        sd.line([(x0, y), (x1, y)], fill=(*P["rail_scrape"], a),
                width=max(1, scale // 3))
    img.alpha_composite(scrape)

    # Cyan-green grime deep at REAR wall (top of trough), very subtle
    grime = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grime)
    for _ in range(rng.randint(5, 9)):
        cx_g = rng.randint(int(W * 0.1), int(W * 0.9))
        cy_g = rng.randint(int(H * 0.05), int(H * 0.2))   # near top = "rear wall"
        r = rng.randint(int(2 * scale), int(5 * scale))
        a = rng.randint(15, 35)
        gd.ellipse((cx_g - r, cy_g - r * 0.4, cx_g + r, cy_g + r * 0.4),
                   fill=(*P["rail_grime_cyan"], a))
    grime = grime.filter(ImageFilter.GaussianBlur(radius=max(1, scale * 0.7)))
    img.alpha_composite(grime)

    preview_path = os.path.join(GUI_DIR, "_preview_long_rail_insert_4x.png")
    img.save(preview_path)
    final = img.resize((target_w, target_h), Image.LANCZOS)
    final_path = os.path.join(ASSETS, "long_rail_insert_2x.png")
    final.save(final_path)
    print(f"  long_rail_insert                 -> {target_w:3d}x{target_h:3d}  {final_path}")
    return final_path

def render_type_rail_insert(scale=4):
    """For TYPE slot. Smaller, shallower trough, with 4 detent scars."""
    target_w, target_h = 596, 61
    W, H = target_w * scale, target_h * scale
    rng = random.Random(202)

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bg = vertical_gradient((W, H), [
        (0.00, P["rail_bg_top"]),
        (1.00, P["rail_bg_bot"]),
    ])
    bg_rgba = bg.convert("RGBA")
    rail_mask = rounded_rect_mask((W, H), radius=int(2 * scale))
    bg_rgba.putalpha(rail_mask)
    img.alpha_composite(bg_rgba)

    d = ImageDraw.Draw(img)

    # Single hairline rail (TYPE is shallower)
    rail_y = int(H * 0.5)
    rail_inset = int(8 * scale)
    rail_thick = max(1, int(scale * 0.5))
    d.line([(rail_inset, rail_y), (W - rail_inset, rail_y)],
           fill=(*P["rail_gunmetal"], 110), width=rail_thick)

    # 4 internal detent scars — tiny vertical micro-grooves at 0/33/66/100
    # NOT bright marks — these are debossed, slightly darker than bed
    detent_count = 4
    scar_inset = int(8 * scale)
    usable_w = W - 2 * scar_inset
    for i in range(detent_count):
        x = scar_inset + int(i * (usable_w / (detent_count - 1)))
        # Tiny vertical micro-mark, slightly darker
        scar_h = int(H * 0.35)
        scar_y = (H - scar_h) // 2
        scar_w = max(1, int(scale * 0.4))
        d.rounded_rectangle(
            (x - scar_w // 2, scar_y, x + scar_w // 2 + 1, scar_y + scar_h),
            radius=0, fill=(0, 0, 0, 160))

    # End stops — tiny
    stop_w = max(1, int(scale * 0.7))
    stop_h = int(H * 0.5)
    stop_y = (H - stop_h) // 2
    for x in (int(2 * scale), W - int(2 * scale) - stop_w):
        d.rounded_rectangle((x, stop_y, x + stop_w, stop_y + stop_h),
                            radius=int(scale * 0.3),
                            fill=(*P["rail_endstop"], 180))

    # Very subtle scrape marks (less than long rail)
    scrape = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrape)
    for _ in range(4):
        y = rng.randint(int(H * 0.3), int(H * 0.7))
        x0 = rng.randint(int(W * 0.1), int(W * 0.5))
        x1 = x0 + rng.randint(int(W * 0.05), int(W * 0.2))
        a = rng.randint(15, 35)
        sd.line([(x0, y), (x1, y)], fill=(*P["rail_scrape"], a),
                width=max(1, scale // 4))
    img.alpha_composite(scrape)

    preview_path = os.path.join(GUI_DIR, "_preview_type_rail_insert_4x.png")
    img.save(preview_path)
    final = img.resize((target_w, target_h), Image.LANCZOS)
    final_path = os.path.join(ASSETS, "type_rail_insert_2x.png")
    final.save(final_path)
    print(f"  type_rail_insert                 -> {target_w:3d}x{target_h:3d}  {final_path}")
    return final_path

# ============================================================================
# Phosphor display, TYPE text strip, value cell digits
# (X3 layout hierarchy with our DF-II material identity — slide-shuttle metaphor,
#  NOT chrome roller. Display becomes the XY performance surface in JUCE.)
# ============================================================================

PHOSPHOR = {
    "screen_top":   ( 12,  34,  32),   # dark teal CRT glass top
    "screen_mid":   (  6,  20,  19),
    "screen_bot":   (  3,  10,  10),
    "grid_minor":   ( 24,  68,  62),
    "grid_major":   ( 38, 100,  92),
    "curve":        ( 95, 220, 200),   # phosphor cyan/teal
    "curve_glow":   ( 95, 220, 200),
    "stress_cyan":  ( 95, 220, 200),
    "stress_magenta":(220,  95, 195),
    "text_dim":     ( 70, 160, 145),
    "text_bright":  (130, 230, 210),

    "glass_top":    ( 12,  14,  14),   # value cell smoked glass
    "glass_bot":    (  3,   4,   4),
    "digit":        (118, 148, 138),   # muted phosphor — not neon
    "digit_dim":    ( 70, 100,  92),

    "label_glass_top": ( 11,  13,  13),
    "label_glass_bot": (  3,   4,   4),
    "label_text":      (130, 158, 148),   # restrained, lab-instrument grey-green
    "label_text_dim":  ( 80, 105,  98),
}

CONSOLA       = r"C:\Windows\Fonts\consola.ttf"
CONSOLA_BOLD  = r"C:\Windows\Fonts\consolab.ttf"
COMMIT_BOLD   = os.path.join(ROOT, "assets", "fonts", "CommitMono-Bold.otf")
COMMIT_REG    = os.path.join(ROOT, "assets", "fonts", "CommitMono-Regular.otf")

def safe_font(path, size):
    from PIL import ImageFont
    try: return ImageFont.truetype(path, size)
    except Exception:
        try: return ImageFont.truetype(CONSOLA, size)
        except Exception: return ImageFont.load_default()

def render_main_display(scale=2):
    """DF2 phosphor screen — dark teal CRT, hard aliased grid, sample filter curve."""
    target_w, target_h = LAYOUT["display"]["bbox"]["w"], LAYOUT["display"]["bbox"]["h"]
    W, H = target_w * scale, target_h * scale
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # Screen background — dark teal gradient
    bg = vertical_gradient((W, H), [
        (0.0, PHOSPHOR["screen_top"]),
        (0.6, PHOSPHOR["screen_mid"]),
        (1.0, PHOSPHOR["screen_bot"]),
    ])
    rgba = bg.convert("RGBA")
    rgba.putalpha(255)
    img.alpha_composite(rgba)

    d = ImageDraw.Draw(img)

    # Hard aliased grid — minor every 1/16, major every 1/4
    minor_x = 16; minor_y = 8
    major_x = 4;  major_y = 2
    for i in range(1, minor_x):
        x = int(W * i / minor_x)
        col = PHOSPHOR["grid_major"] if (i % (minor_x // major_x) == 0) else PHOSPHOR["grid_minor"]
        d.line([(x, 0), (x, H)], fill=(*col, 200), width=max(1, scale // 2))
    for i in range(1, minor_y):
        y = int(H * i / minor_y)
        col = PHOSPHOR["grid_major"] if (i % (minor_y // major_y) == 0) else PHOSPHOR["grid_minor"]
        d.line([(0, y), (W, y)], fill=(*col, 200), width=max(1, scale // 2))

    # Outer frame line (just inside the screen border)
    d.rectangle([(scale, scale), (W - scale - 1, H - scale - 1)],
                outline=(*PHOSPHOR["grid_major"], 240), width=max(1, scale // 2))

    # Sample filter curve — TALKING HEDZ-ish formant shape (low-mid bump + 2 high notches)
    import math
    curve_pts = []
    for x in range(W):
        u = x / W
        # log-ish freq axis 0..1
        bump1 = 0.45 * math.exp(-((u - 0.18) * 12) ** 2)         # low formant
        bump2 = 0.32 * math.exp(-((u - 0.58) * 18) ** 2)         # mid resonance
        notch = -0.25 * math.exp(-((u - 0.82) * 22) ** 2)        # high notch
        baseline = 0.5 - 0.2 * u                                  # gentle slope down
        v = baseline + bump1 + bump2 + notch
        v = max(0.05, min(0.95, v))
        y = int(H * (1 - v))
        curve_pts.append((x, y))

    # Glow under-stroke (thicker, lower alpha)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.line(curve_pts, fill=(*PHOSPHOR["curve_glow"], 110),
            width=max(2, scale * 2))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(1, scale * 1.2)))
    img.alpha_composite(glow)

    # Hard curve (thin aliased)
    d.line(curve_pts, fill=(*PHOSPHOR["curve"], 255), width=max(1, scale))

    # Tiny TYPE/body label upper-left inside screen
    f_label = safe_font(COMMIT_BOLD, max(9, scale * 7))
    d.text((scale * 6, scale * 4), "BODY 01 // SPEAKER KNOCKERZ",
           fill=(*PHOSPHOR["text_bright"], 235), font=f_label)
    f_small = safe_font(COMMIT_REG, max(8, scale * 6))
    d.text((scale * 6, scale * 4 + scale * 9), "DF2  6/12",
           fill=(*PHOSPHOR["text_dim"], 220), font=f_small)

    # Stress markers in upper right (sparse cyan/magenta)
    d.ellipse((W - scale * 10, scale * 4, W - scale * 4, scale * 10),
              fill=(*PHOSPHOR["stress_cyan"], 200))
    d.ellipse((W - scale * 18, scale * 4, W - scale * 12, scale * 10),
              fill=(*PHOSPHOR["stress_magenta"], 160))

    # Faint scanline overlay
    scan = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scan)
    for y in range(0, H, max(2, scale)):
        sd.line([(0, y), (W, y)], fill=(0, 0, 0, 25), width=1)
    img.alpha_composite(scan)

    preview_path = os.path.join(GUI_DIR, "_preview_main_display_2x.png")
    img.save(preview_path)
    final = img.resize((target_w, target_h), Image.LANCZOS)
    final_path = os.path.join(ASSETS, "main_display_2x.png")
    final.save(final_path)
    print(f"  main_display                     -> {target_w:3d}x{target_h:3d}  {final_path}")
    return final_path

def render_type_label_strip(scale=4):
    """Flat dark glass strip for TYPE — small restrained body-name label, no scanlines."""
    target_w, target_h = LAYOUT["type_slot"]["bbox"]["w"], LAYOUT["type_slot"]["bbox"]["h"]
    W, H = target_w * scale, target_h * scale
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    bg = vertical_gradient((W, H), [
        (0.0, PHOSPHOR["label_glass_top"]),
        (1.0, PHOSPHOR["label_glass_bot"]),
    ])
    rgba = bg.convert("RGBA")
    mask = rounded_rect_mask((W, H), radius=int(scale * 1.5))
    rgba.putalpha(mask)
    img.alpha_composite(rgba)

    d = ImageDraw.Draw(img)

    # Small index — flush-left, narrow, dim
    f_idx = safe_font(COMMIT_REG, max(9, int(H * 0.30)))
    idx_text = "01"
    ibox = d.textbbox((0, 0), idx_text, font=f_idx)
    ih = ibox[3] - ibox[1]
    d.text((scale * 12, (H - ih) // 2 - ibox[1]),
           idx_text, fill=(*PHOSPHOR["label_text_dim"], 220), font=f_idx)

    # Body name — small caps, slightly brighter than index but restrained
    # Generous gap (90px @ scale=4) between index and name — they should not crowd
    f_name = safe_font(COMMIT_REG, max(10, int(H * 0.34)))
    name_text = "SPEAKER  KNOCKERZ"   # double-spaced for letterspacing illusion
    nbox = d.textbbox((0, 0), name_text, font=f_name)
    nh = nbox[3] - nbox[1]
    d.text((scale * 90, (H - nh) // 2 - nbox[1]),
           name_text, fill=(*PHOSPHOR["label_text"], 235), font=f_name)

    # No dropdown arrow visible at rest — JUCE can show it on hover.
    # No scanlines.

    preview_path = os.path.join(GUI_DIR, "_preview_type_label_strip_4x.png")
    img.save(preview_path)
    final = img.resize((target_w, target_h), Image.LANCZOS)
    final_path = os.path.join(ASSETS, "type_label_strip_2x.png")
    final.save(final_path)
    print(f"  type_label_strip                 -> {target_w:3d}x{target_h:3d}  {final_path}")
    return final_path

def render_value_cell(name, digits, scale=4):
    """Flat dark glass cell with small restrained numerals. No glow, no scanlines."""
    target_w, target_h = LAYOUT["morph_cell"]["bbox"]["w"], LAYOUT["morph_cell"]["bbox"]["h"]
    W, H = target_w * scale, target_h * scale
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    bg = vertical_gradient((W, H), [
        (0.0, PHOSPHOR["glass_top"]),
        (1.0, PHOSPHOR["glass_bot"]),
    ])
    rgba = bg.convert("RGBA")
    mask = rounded_rect_mask((W, H), radius=int(scale * 2))
    rgba.putalpha(mask)
    img.alpha_composite(rgba)

    d = ImageDraw.Draw(img)
    # Smaller, restrained — about 38% of cell height, monospace regular not bold
    f = safe_font(COMMIT_REG, max(14, int(H * 0.38)))
    bbox = d.textbbox((0, 0), digits, font=f)
    tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
    tx = (W - tw) // 2 - bbox[0]; ty = (H - th) // 2 - bbox[1]
    d.text((tx, ty), digits, fill=(*PHOSPHOR["digit"], 220), font=f)

    preview_path = os.path.join(GUI_DIR, f"_preview_{name}_4x.png")
    img.save(preview_path)
    final = img.resize((target_w, target_h), Image.LANCZOS)
    final_path = os.path.join(ASSETS, f"{name}_2x.png")
    final.save(final_path)
    print(f"  {name:32s} -> {target_w:3d}x{target_h:3d}  {final_path}")
    return final_path

def add_active_glow_to_rail(rail_path, value_0_1, side="left"):
    """Composite a cyan active-segment glow onto a rail insert PNG showing
    travel up to value_0_1. side='left' fills from left edge; 'right' from right."""
    rail = Image.open(rail_path).convert("RGBA")
    W, H = rail.size
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    fill_w = int(W * value_0_1)
    if side == "left":
        x0, x1 = 0, fill_w
    else:
        x0, x1 = W - fill_w, W
    # Gradient stripe — cyan core, fading toward the ends
    stripe_h = int(H * 0.55)
    sy = (H - stripe_h) // 2
    for dx in range(x1 - x0):
        t = dx / max(1, (x1 - x0) - 1)
        # bright in middle, dim at edges
        local_alpha = int(110 * (1 - abs(2 * t - 1) ** 2))
        gd.line([(x0 + dx, sy), (x0 + dx, sy + stripe_h)],
                fill=(*PHOSPHOR["curve"], local_alpha), width=1)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=2))
    rail.alpha_composite(glow)
    return rail

# ============================================================================
# Composite test — drop all assets onto the chassis at correct positions
# ============================================================================

def composite_test():
    """Render the full chassis with rail inserts + caps at default positions."""
    chassis_src = os.path.join(ASSETS, "df2_chassis_2x.png")
    chassis = Image.open(chassis_src).convert("RGBA")
    Cw, Ch = chassis.size
    print(f"\ncomposite test on {os.path.basename(chassis_src)} ({Cw}x{Ch})")

    def paste(img_path, x, y, w, h, scale_to=True):
        layer = Image.open(img_path).convert("RGBA")
        if scale_to and (layer.size != (w, h)):
            layer = layer.resize((w, h), Image.LANCZOS)
        chassis.alpha_composite(layer, (x, y))

    # Slot interior dimensions and positions from layout
    L = LAYOUT
    # Type slot (use new chassis values from chassis_layout if present)
    ts = L["type_slot"]["trough"] if "trough" in L["type_slot"] else L["type_slot"]
    ms = L["morph_slot"]["trough"] if "trough" in L["morph_slot"] else L["morph_slot"]
    qs = L["q_slot"]["trough"] if "trough" in L["q_slot"] else L["q_slot"]

    # 1. TYPE = label strip (replaces TYPE rail+shuttle); display overlay; rail inserts for MORPH/Q
    paste(os.path.join(ASSETS, "type_label_strip_2x.png"),
          ts["x0"], ts["y0"], ts["w"], ts["h"])
    # Display intentionally NOT composited — chassis's deep-black slot is the screen,
    # JUCE will draw live curve/grid/telemetry at runtime

    # MORPH/Q rail inserts — no cyan glow stripe (the cap is the indicator)
    cap_specs = L["caps_src_px"]
    morph_val = cap_specs["morph"]["default_value"]
    q_val     = cap_specs["q"]["default_value"]
    paste(os.path.join(ASSETS, "long_rail_insert_2x.png"),
          ms["x0"], ms["y0"], ms["w"], ms["h"])
    paste(os.path.join(ASSETS, "long_rail_insert_2x.png"),
          qs["x0"], qs["y0"], qs["w"], qs["h"])

    # 2. MORPH cap at 54%
    cw, ch = cap_specs["morph"]["w"], cap_specs["morph"]["h"]
    cx = ms["x0"] + int(morph_val * (ms["w"] - cw))
    cy = ms["y0"] + (ms["h"] - ch) // 2
    paste(os.path.join(ASSETS, "morph_shuttle_cap_2x.png"), cx, cy, cw, ch, scale_to=False)

    # 3. Q cap at 31%
    cw, ch = cap_specs["q"]["w"], cap_specs["q"]["h"]
    cx = qs["x0"] + int(q_val * (qs["w"] - cw))
    cy = qs["y0"] + (qs["h"] - ch) // 2
    paste(os.path.join(ASSETS, "q_shuttle_cap_2x.png"), cx, cy, cw, ch, scale_to=False)

    # 4. Value cells — flat dark glass with bitmap digits
    mc = L["morph_cell"]["bbox"]
    qc = L["q_cell"]["bbox"]
    paste(os.path.join(ASSETS, "value_cell_morph_2x.png"),
          mc["x0"], mc["y0"], mc["w"], mc["h"])
    paste(os.path.join(ASSETS, "value_cell_q_2x.png"),
          qc["x0"], qc["y0"], qc["w"], qc["h"])

    # TYPE shuttle cap removed — TYPE is now a flat text strip per X3 hierarchy

    out = os.path.join(GUI_DIR, "_composite_test.png")
    chassis.save(out)
    print(f"  composite -> {out}")
    return out

# ============================================================================
if __name__ == "__main__":
    os.makedirs(ASSETS, exist_ok=True)
    print("rendering DF-II UI control sprites...")
    render_morph_cap(scale=8)
    render_q_cap(scale=8)
    render_long_rail_insert(scale=4)
    # render_main_display intentionally not called — display content is drawn
    # live by JUCE at runtime, not baked into a static PNG
    render_type_label_strip(scale=4)
    render_value_cell("value_cell_morph", "54", scale=4)
    render_value_cell("value_cell_q",     "31", scale=4)
    composite_test()
    print("done.")
