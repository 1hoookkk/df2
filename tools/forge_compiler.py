"""forge_compiler — high-level musical params -> physics-rail snapping -> 240-byte body.
Every macro is a concrete action on a real rail (no invented shapes):
  anchor_hz    : foundation pole (bass body), pole+zero shelf (representable)
  morph_spread : how far formant poles travel along the rail (Frame A -> Frame B)
  canyon_depth : zero notch depth between rail anchors (the articulation; zeros = character)
  tilt_db      : spectral tilt across the formant gains (low vs high emphasis)
Q is the radius axis (loQ derived broad from the hiQ frames). Vocal family first;
tube/metal rails drop into RAILS the same way.
"""
import sys, math
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.author_lanes import biquad_to_kernel
from pyruntime.packed_interp import coeffs_to_words
SR = 39062.5; NY = SR/2

# ---- physics rails (real anchors) ----
RAILS = {
    "vocal": {  # Klatt/Peterson-Barney formants F1..F5 (Hz) — the rail anchors
        "ah": [730, 1090, 2440, 3300, 3850], "ee": [270, 2290, 3010, 3300, 3850],
        "oo": [300, 870, 2240, 3300, 3850], "eh": [530, 1840, 2480, 3300, 3850],
        "ae": [660, 1720, 2410, 3300, 3850], "uh": [640, 1190, 2390, 3300, 3850],
    },
}


def _rbj_peak(f, Q, gain_db):
    w = 2*math.pi*min(f, NY*0.98)/SR; A = 10**(gain_db/40); al = math.sin(w)/(2*Q)
    return ((1+al*A)/(1+al/A), (-2*math.cos(w))/(1+al/A), (1-al*A)/(1+al/A),
            (-2*math.cos(w))/(1+al/A), (1-al/A)/(1+al/A))


def _dc_flat(b0, b1, b2, a1, a2):
    s = (1+a1+a2)/(b0+b1+b2) if abs(b0+b1+b2) > 1e-12 else 1.0
    return b0*s, b1*s, b2*s, a1, a2


def _shelf(ph, pr, zh, zr, g):                 # broad pole+zero low shelf = bass body
    wp = 2*math.pi*ph/SR; wz = 2*math.pi*zh/SR
    return g, -2*zr*g*math.cos(wz), zr*zr*g, -2*pr*math.cos(wp), pr*pr


def _w(bq): return coeffs_to_words(*biquad_to_kernel(*bq))


def _stage_words(Fa, Fb, anchor_hz, tilt_db, canyon_depth, morph_spread, q, m):
    """one corner: m=0 Frame A, m=1 Frame B; q=0 broad, q=1 sharp.
    6 sections = foundation shelf + 5 (formant pole + its adjacent canyon zero)."""
    n = len(Fa)
    F = [Fa[i]*((Fb[i]/Fa[i])**(m*morph_spread)) for i in range(n)]       # formant travel along the rail
    rows = [_w(_shelf(anchor_hz, 0.6, anchor_hz*5.5, 0.5, 1.6))]          # foundation (bass body)
    pr = 0.90 + 0.085*q                                                   # Q -> pole radius (sharpness)
    zr = 0.55 + 0.44*canyon_depth                                         # canyon depth -> zero radius
    for i in range(n):
        ph = F[i]
        cz = math.sqrt(F[i]*F[i+1]) if i < n-1 else min(NY*0.9, F[i]*1.5)  # canyon above this formant
        wp = 2*math.pi*min(ph, NY*0.98)/SR; a1 = -2*pr*math.cos(wp); a2 = pr*pr
        wz = 2*math.pi*min(cz, NY*0.98)/SR; b1 = -2*zr*math.cos(wz); b2 = zr*zr
        bq = _dc_flat(1.0, b1, b2, a1, a2)                               # flat baseline (DC=0 dB)
        t = 10 ** ((-tilt_db * (i/(n-1))) / 20.0)                         # spectral tilt: high formants quieter
        rows.append(_w((bq[0]*t, bq[1]*t, bq[2]*t, bq[3], bq[4])))
    return rows[:6]


def compile_body(family="vocal", intent_a="ah", intent_b="ee",
                 anchor_hz=110.0, tilt_db=6.0, canyon_depth=0.6, morph_spread=1.0):
    rail = RAILS[family]; Fa = rail[intent_a]; Fb = rail[intent_b]
    args = (Fa, Fb, anchor_hz, tilt_db, canyon_depth, morph_spread)
    corners = {"M0_Q0": _stage_words(*args, 0.0, 0.0), "M100_Q0": _stage_words(*args, 0.0, 1.0),
               "M0_Q100": _stage_words(*args, 1.0, 0.0), "M100_Q100": _stage_words(*args, 1.0, 1.0)}
    # corner order for packing: M0_Q0, M100_Q0, M0_Q100, M100_Q100  (q here: name _Q0=broad, _Q100=sharp)
    order = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
    import struct
    out = bytearray()
    for lab in order:
        for row in corners[lab]:
            for word in row:
                out += struct.pack("<H", int(word) & 0xFFFF)
    return bytes(out)


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="ah"); ap.add_argument("--b", default="ee")
    ap.add_argument("--anchor", type=float, default=110.0); ap.add_argument("--tilt", type=float, default=6.0)
    ap.add_argument("--canyon", type=float, default=0.6); ap.add_argument("--spread", type=float, default=1.0)
    ap.add_argument("--out", default="dev/tmp/compiled.body240")
    a = ap.parse_args()
    body = compile_body("vocal", a.a, a.b, a.anchor, a.tilt, a.canyon, a.spread)
    Path(a.out).write_bytes(body); print(f"{len(body)} bytes -> {a.out}")
