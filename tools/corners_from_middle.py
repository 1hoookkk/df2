#!/usr/bin/env python3
"""corners_from_middle.py — invert the authoring. Declare the MIDDLE; derive the
4 corners. The runtime's morph center (M50/Q50) is the AVERAGE of the 4 corners,
so the 4 corners are just the middle spread along two damage directions:

    C00 = mid - Vm - Vq      C10 = mid + Vm - Vq
    C01 = mid - Vm + Vq      C11 = mid + Vm + Vq      (average == mid, exact)

Vm = spread*(morph_damage - mid),  Vq = spread*(q_damage - mid).
Math lives in the real corner coeffs (4 x 6 stages x 5 = 120 u16 words = the
240-byte ROM). This builds in the decoded coeff domain (= the live runtime's
c-domain bilinear); packed-u16 morph is the faithful path (approved, not wired).

  python tools/corners_from_middle.py
  python tools/corners_from_middle.py --middle siren --morph speaker_knockerz --q cul_de_sac --spread 0.6
  python tools/corners_from_middle.py --list
"""
from __future__ import annotations
import argparse, importlib.util, math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def _load(name, rel):
    s = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
pc = _load("physical_corners", Path(".claude/skills/physical-corners/physical_corners.py"))
w  = _load("weapons", Path("tools/weapons.py"))

SR, PASS = w.SR, w.PASS


def weapon_corner(name):
    specs, peak = w.WEAPONS[name]
    return w.corner(specs, peak, hot=1.0, edge=1.0)        # 6 stages x [c0..c4]


def clamp_stable(c):
    """Keep the biquad pole pair strictly inside the unit circle."""
    c = c[:]
    a2 = min(0.9997, max(-0.9997, 1 - c[3]))
    a1 = c[2] - 2
    lim = (1 + a2) - 1e-4
    a1 = max(-lim, min(lim, a1))
    c[2], c[3] = a1 + 2.0, 1 - a2
    return c


def combine(mid, dm, dq, spread):
    """mid/dm/dq: 6x5 corners -> the four corners, exact average == mid."""
    def lin(a, b, c, d):  # a*mid + b*Vm + c*Vq  (elementwise over 6x5)
        out = []
        for s in range(6):
            row = []
            for k in range(5):
                vm = spread * (dm[s][k] - mid[s][k])
                vq = spread * (dq[s][k] - mid[s][k])
                row.append(mid[s][k] + b * vm + c * vq)
            out.append(clamp_stable(row))
        return out
    C00 = lin(1, -1, -1, 0)
    C10 = lin(1, +1, -1, 0)
    C01 = lin(1, -1, +1, 0)
    C11 = lin(1, +1, +1, 0)
    return [C00, C10, C01, C11]


def resonances(c6):
    fr = []
    for s in c6:
        if s == PASS:
            continue
        a1, a2 = s[2] - 2, 1 - s[3]
        r = math.sqrt(max(a2, 0))
        if r > 1e-6 and abs(-a1 / (2 * r)) <= 1:
            fr.append(int(round(math.acos(-a1 / (2 * r)) * SR / (2 * math.pi))))
    return sorted(fr)


def center(corners):
    return [[sum(corners[i][s][k] for i in range(4)) / 4 for k in range(5)] for s in range(6)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--middle", default="siren")
    ap.add_argument("--morph", default="speaker_knockerz", help="Morph-axis damage direction")
    ap.add_argument("--q", default="cul_de_sac", help="Q-axis damage direction")
    ap.add_argument("--spread", type=float, default=0.6)
    ap.add_argument("--boost", type=float, default=1.6)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        print("palette:", "  ".join(w.WEAPONS)); return
    for n in (a.middle, a.morph, a.q):
        if n not in w.WEAPONS:
            print("unknown:", n, "\ntry --list"); return

    mid = weapon_corner(a.middle)
    corners = combine(mid, weapon_corner(a.morph), weapon_corner(a.q), a.spread)

    print(f"\nMIDDLE = {a.middle}   Morph->{a.morph}   Q->{a.q}   spread={a.spread}")
    labels = ["C00 (M0_Q0)", "C10 (M100_Q0)", "C01 (M0_Q100)", "C11 (M100_Q100)"]
    for lbl, c in zip(labels, corners):
        print(f"  {lbl:<16} {resonances(c)}")
    print(f"  {'declared middle':<16} {resonances(mid)}")
    print(f"  {'realized center':<16} {resonances(center(corners))}")
    # exactness check (before/after the stability clamp)
    cen = center(corners)
    dev = max(abs(cen[s][k] - mid[s][k]) for s in range(6) for k in range(5))
    print(f"  center vs declared middle: max coeff deviation = {dev:.2e}"
          + ("  (exact)" if dev < 1e-9 else "  (clamp moved a pole)"))

    slot = pc.write_cartridge(corners, f"mid_{a.middle}", boost=a.boost)
    print(f"\nwrote -> {slot}\n  dead-center = {a.middle}; Morph -> {a.morph}, Q -> {a.q}")


if __name__ == "__main__":
    main()
