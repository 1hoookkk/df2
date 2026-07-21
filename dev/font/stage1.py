# TRENCH Stamp — stage 1: three stylistic directions, specimen sheets only.
# Hand-authored glyph skeletons (no tracing of any existing font), stroked and
# rendered per-direction. Coordinates: y 0=baseline, 70=cap, 50=x-height,
# 72=ascender, -20=descender. Each glyph: (advance, [strokes]); stroke=[(x,y)..].
import math, random, os
from PIL import Image, ImageDraw

def arc(cx, cy, rx, ry, a0, a1, n=14):
    return [(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a)))
            for a in [a0 + (a1 - a0) * i / n for i in range(n + 1)]]

# ---------------- skeleton library (shared vocabulary, per-direction reshaping) --
def caps(w):
    """Uppercase skeletons at base width scale w (cap=70)."""
    G = {}
    def s(*pts): return list(pts)
    G['A'] = (46, [s((2,0),(23,70)), s((44,0),(23,70)), s((10,24),(36,24))])
    G['B'] = (44, [s((6,0),(6,70)), arc(20,52,17,18,90,-90)+[(6,34)], [(6,34)]+arc(21,17,19,17,90,-90)+[(6,0)], s((6,70),(20,70)), s((6,0),(21,0))])
    G['C'] = (44, [arc(26,35,21,35,58,302)])                       # terminals angle inward
    G['D'] = (46, [s((6,0),(6,70)), [(6,70),(22,70)]+arc(22,35,20,35,90,-90)+[(6,0)]])
    G['E'] = (40, [s((6,0),(6,70)), s((6,70),(38,70)), s((6,40),(30,40)), s((6,0),(38,0))])  # mid arm short+high
    G['F'] = (40, [s((6,0),(6,70)), s((6,70),(38,70)), s((6,38),(29,38))])
    G['G'] = (46, [arc(26,35,21,35,55,300), s((36,5),(36,26)), s((36,26),(22,26))])  # open G, bar meets arc
    G['H'] = (46, [s((6,0),(6,70)), s((40,0),(40,70)), s((6,39),(40,39))])  # bar above centre
    G['I'] = (22, [s((11,0),(11,70)), s((4,70),(18,70)), s((4,0),(18,0))])
    G['J'] = (36, [s((28,70),(28,14)), arc(17,14,11,14,0,-180)])
    G['K'] = (44, [s((6,0),(6,70)), s((40,70),(6,28)), s((18,38),(41,0))])
    G['L'] = (38, [s((6,0),(6,70)), s((6,0),(36,0))])
    G['M'] = (54, [s((5,0),(8,70)), s((8,70),(27,26)), s((27,26),(46,70)), s((46,70),(49,0))])  # compact M
    G['N'] = (48, [s((6,0),(6,70)), s((7,68),(24,36),(41,4)), s((42,0),(42,70))])  # hand-cut diagonal (bent)
    G['O'] = (50, [arc(25,35,20,35,0,360)])
    G['Q'] = (50, [arc(25,35,20,35,0,360), s((33,10),(46,-6))])    # short external tail
    G['P'] = (44, [s((6,0),(6,70)), [(6,70),(21,70)]+arc(21,52,18,18,90,-90)+[(6,34)]])
    G['R'] = (46, [s((6,0),(6,70)), [(6,70),(20,70)]+arc(20,53,17,17,90,-90)+[(6,36)], s((22,36),(38,0))])  # short abrupt leg
    G['S'] = (42, [arc(23,52,16,17,40,215)+arc(20,17,17,17,55,-125)])
    G['T'] = (46, [s((1,70),(45,70)), s((23,0),(23,70))])          # broad softened top
    G['U'] = (48, [[(7,70),(7,16)]+arc(24,16,17,16,180,360)+[(41,70)]])
    G['V'] = (46, [s((3,70),(23,0)), s((43,70),(23,0))])
    G['W'] = (60, [s((3,70),(14,0)), s((14,0),(30,48)), s((30,48),(46,0)), s((46,0),(57,70))])
    G['X'] = (44, [s((4,70),(40,0)), s((40,70),(4,0))])
    G['Y'] = (44, [s((3,70),(22,34)), s((41,70),(22,34)), s((22,34),(22,0))])
    G['Z'] = (42, [s((5,70),(38,70)), s((38,70),(4,0)), s((4,0),(39,0))])
    for k,(adv,st) in G.items():
        G[k] = (adv*w, [[(x*w,y) for x,y in stroke] for stroke in st])
    return G

def lows(w):
    """Lowercase skeletons, relaxed (x-height 50, asc 72, desc -20)."""
    G = {}
    def s(*pts): return list(pts)
    G['a'] = (42, [arc(21,25,15,25,0,360), s((36,50),(36,0))])
    G['b'] = (42, [s((6,0),(6,72)), arc(21,25,15,25,0,360)])
    G['c'] = (38, [arc(21,25,15,25,50,310)])
    G['d'] = (42, [s((36,0),(36,72)), arc(21,25,15,25,0,360)])
    G['e'] = (40, [arc(20,25,15,25,15,325), s((5,27),(35,27))])
    G['f'] = (26, [[(22,66)]+arc(15,62,8,9,80,180)+[(7,0)], s((1,48),(21,48))])
    G['g'] = (42, [arc(21,25,15,25,0,360), s((36,50),(36,-6)), arc(21,-6,15,14,0,-160)])
    G['h'] = (42, [s((6,0),(6,72)), arc(21,32,15,18,178,0)+[(36,0)]])
    G['i'] = (16, [s((8,0),(8,50)), s((8,62),(8,64))])
    G['j'] = (18, [s((11,50),(11,-8)), arc(3,-8,8,10,0,-120), s((11,62),(11,64))])
    G['k'] = (40, [s((6,0),(6,72)), s((34,50),(6,20)), s((15,29),(35,0))])
    G['l'] = (16, [s((7,72),(7,8)), arc(12,8,5,8,180,270)])
    G['m'] = (62, [s((6,0),(6,50)), arc(18,34,12,16,178,2)+[(30,0)], [(30,32)]+arc(43,34,12,16,178,2)+[(55,0)]])
    G['n'] = (42, [s((6,0),(6,50)), arc(21,32,15,18,178,2)+[(36,0)]])
    G['o'] = (42, [arc(21,25,15,25,0,360)])
    G['p'] = (42, [s((6,-20),(6,50)), arc(21,25,15,25,0,360)])
    G['q'] = (42, [s((36,-20),(36,50)), arc(21,25,15,25,0,360)])
    G['r'] = (28, [s((6,0),(6,50)), arc(17,36,11,14,178,40)])
    G['s'] = (36, [arc(19,37,12,13,40,215)+arc(17,13,13,13,55,-125)])
    G['t'] = (26, [s((9,66),(9,8)), arc(15,8,6,8,180,300), s((1,50),(20,50))])
    G['u'] = (42, [[(6,50),(6,16)]+arc(19,16,13,16,180,360), s((36,50),(36,0))])
    G['v'] = (38, [s((3,50),(19,0)), s((35,50),(19,0))])
    G['w'] = (56, [s((3,50),(13,0)), s((13,0),(27,34)), s((27,34),(41,0)), s((41,0),(51,50))])
    G['x'] = (38, [s((4,50),(34,0)), s((34,50),(4,0))])
    G['y'] = (38, [s((3,50),(19,2)), s((35,50),(13,-20))])
    G['z'] = (34, [s((4,50),(30,50)), s((30,50),(3,0)), s((3,0),(31,0))])
    for k,(adv,st) in G.items():
        G[k] = (adv*w, [[(x*w,y) for x,y in stroke] for stroke in st])
    return G

def digits(w):
    G = {}
    def s(*pts): return list(pts)
    G['0'] = (46, [arc(23,35,16,34,0,360)])                        # narrow oval, no slash
    G['1'] = (46, [s((10,54),(23,70)), s((23,70),(23,0)), s((10,0),(37,0))])
    G['2'] = (46, [arc(22,52,16,17,170,-15)+[(31,38),(6,0)], s((6,0),(40,0))])  # firm base
    G['3'] = (46, [arc(22,52,15,17,160,-80), arc(22,18,17,18,105,-160)])
    G['4'] = (46, [s((30,70),(6,22)), s((6,22),(40,22)), s((30,52),(30,0))])    # open, blunt bar
    G['5'] = (46, [s((36,70),(10,70)), s((10,70),(8,40)), [(8,40),(20,46)]+arc(23,23,16,22,80,-90)+[(6,6)]])
    G['6'] = (46, [[(34,68)]+arc(28,40,19,30,120,182), arc(23,21,16,21,0,360)])
    G['7'] = (46, [s((6,70),(40,70)), s((40,70),(16,0))])
    G['8'] = (46, [arc(23,51,13,15,0,360), arc(23,17,17,18,0,360)])            # unequal bowls
    G['9'] = (46, [arc(23,47,16,20,0,360), [(38,50)]+arc(19,28,20,29,-8,-65)])
    G['.'] = (20, [s((10,2),(10,5))])
    G['%'] = (56, [arc(13,56,9,11,0,360), arc(43,13,9,11,0,360), s((8,0),(48,70))])
    G['('] = (24, [arc(30,30,18,44,120,240)])
    G[')'] = (24, [arc(-6,30,18,44,60,-60)])
    G['_'] = (40, [s((2,-8),(38,-8))])
    G[' '] = (26, [])
    G['·'] = (20, [s((10,26),(10,29))])
    for k,(adv,st) in G.items():
        G[k] = (adv*w, [[(x*w,y) for x,y in stroke] for stroke in st])
    return G

# ---------------- directions ---------------------------------------------------
DIRECTIONS = {
    1: dict(name='ONE - NARROW AND DRY',      capw=0.86, loww=0.90, stroke=6.4,
            swell=1.06, jitter=1.0, widthvar=0.06, track=3.2, cap='round'),
    2: dict(name='TWO - SOFT AND INK-SWOLLEN', capw=0.97, loww=1.02, stroke=9.2,
            swell=1.42, jitter=1.9, widthvar=0.12, track=4.2, cap='round'),
    3: dict(name='THREE - DENSE AND BLUNT',    capw=1.02, loww=1.05, stroke=12.6,
            swell=1.00, jitter=0.9, widthvar=0.05, track=5.0, cap='round'),
}

def glyphset(d):
    g = {}
    g.update(caps(d['capw'])); g.update(lows(d['loww'])); g.update(digits((d['capw']+d['loww'])/2))
    return g

def jit(rng, amp):
    return rng.uniform(-amp, amp)

def draw_text(img, draw, text, x, y, size, d, glyphs, ink, seed_extra=0):
    """Render text at baseline y (PIL coords: y grows down). size = cap height px."""
    scale = size / 70.0
    for ci, ch in enumerate(text):
        if ch not in glyphs:
            ch = ch.upper() if ch.upper() in glyphs else ' '
            if ch not in glyphs: ch = ' '
        adv, strokes = glyphs[ch]
        rng = random.Random(hash((ch, ci, seed_extra)) & 0xffffffff)
        base_lw = d['stroke'] * scale
        jamp = d['jitter'] * scale
        dy_g = jit(rng, 0.8) * scale          # baseline variation
        for st in strokes:
            if not st: continue
            lw = max(1.0, base_lw * (1.0 + jit(rng, d['widthvar'])))
            pts = [(x + (px + jit(rng, d['jitter'])) * scale,
                    y - (py + jit(rng, d['jitter'])) * scale + dy_g) for px, py in st]
            draw.line(pts, fill=ink, width=int(round(lw)), joint='curve')
            r_end = lw * 0.5 * d['swell']
            for ex, ey in (pts[0], pts[-1]):
                draw.ellipse([ex - r_end, ey - r_end, ex + r_end, ey + r_end], fill=ink)
            r_mid = lw * 0.5
            for ex, ey in pts[1:-1]:
                draw.ellipse([ex - r_mid, ey - r_mid, ex + r_mid, ey + r_mid], fill=ink)
        x += (adv + d['track']) * scale
    return x

def text_width(text, size, d, glyphs):
    scale = size / 70.0
    wsum = 0
    for ch in text:
        if ch not in glyphs:
            ch = ch.upper() if ch.upper() in glyphs else ' '
            if ch not in glyphs: ch = ' '
        wsum += (glyphs[ch][0] + d['track']) * scale
    return wsum

def specimen(dirno):
    d = DIRECTIONS[dirno]; glyphs = glyphset(d)
    W, H = 1240, 1560
    img = Image.new('RGB', (W, H), (238, 234, 224))
    dr = ImageDraw.Draw(img)
    ink = (28, 25, 20)
    y = 70
    dr.text((40, 18), 'TRENCH STAMP - DIRECTION %s' % d['name'], fill=(120, 112, 98))
    rows = [
        ('ABCDEFGHIJKLM', 56), ('NOPQRSTUVWXYZ', 56),
        ('abcdefghijklm', 56), ('nopqrstuvwxyz', 56),
        ('0123456789 . %', 56),
        ('TRENCH', 96), ('TYPE  MORPH  Q', 40), ('MODULATION', 40),
        ('68.0  30.0  100.0', 44),
        ('Talking Hedz', 36), ('three_layer_metal_bell', 26),
        ('DRUM LOOP INTO DRUM MELODY', 26),
        ('HAMBURGEFONTSIV', 32), ('TRench trench TRENCH', 32),
        ('IIII llll 1111 0000 OOOO', 32),
    ]
    for text, size in rows:
        y += int(size * 1.15)
        draw_text(img, dr, text, 48, y, size, d, glyphs, ink, seed_extra=dirno)
        y += int(size * 0.42)
    # small-size legibility strip
    for size in (9, 10, 11, 12, 14, 16):
        y += int(size * 1.5) + 8
        draw_text(img, dr, 'MORPH 68.0 MODULATION TYPE Q', 48, y, size, d, glyphs, ink, seed_extra=dirno + size)
    out = 'dev/font/specimens/direction%d.png' % dirno
    img.save(out)
    return out

def mockup(dirno, face_path='trench_face.png'):
    d = DIRECTIONS[dirno]; glyphs = glyphset(d)
    img = Image.open(face_path).convert('RGB').resize((700, 1080), Image.LANCZOS)
    dr = ImageDraw.Draw(img)
    ink = (16, 14, 11)
    plate = (200, 191, 169)
    # patch over the existing labels (rects from UiLayout source space x 2)
    for x0, y0, x1, y1 in [(76, 52, 242, 84), (73, 94, 136, 142),
                            (79, 440, 382, 470), (79, 566, 382, 596)]:
        dr.rectangle([x0, y0, x1, y1], fill=plate)
    def centred(text, cx, ybase, size, col=ink):
        w = text_width(text, size, d, glyphs)
        draw_text(img, dr, text, cx - w / 2, ybase, size, d, glyphs, col, seed_extra=dirno)
    draw_text(img, dr, 'TRENCH', 80, 80, 24, d, glyphs, ink, seed_extra=dirno)
    draw_text(img, dr, 'TYPE', 76, 134, 17, d, glyphs, ink, seed_extra=dirno)
    centred('MORPH (%)', 230, 466, 17)
    centred('Q (%)', 230, 592, 17)
    # readout digits (patch bone pill interiors) + Modulation tag on the glass
    dr.rectangle([416, 492, 526, 534], fill=(238, 233, 220))
    centred('68.0', 471, 528, 24)
    dr.rectangle([415, 618, 525, 658], fill=(238, 233, 220))
    centred('30.0', 470, 654, 24)
    dr.rectangle([104, 320, 310, 352], fill=(58, 84, 78))
    draw_text(img, dr, 'MODULATION', 122, 346, 14, d, glyphs, (214, 234, 224), seed_extra=dirno)
    out = 'dev/font/specimens/mockup%d.png' % dirno
    img.save(out)
    return out

if __name__ == '__main__':
    os.makedirs('dev/font/specimens', exist_ok=True)
    for n in (1, 2, 3):
        print(specimen(n), mockup(n))
