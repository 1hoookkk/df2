#!/usr/bin/env python3
"""weapons.py — a PALETTE of violent FILTER shapes (the distortion IS the filters).

A cartridge morphs across exactly 4 corners. So "more filters" = a library of
weapon shapes you assemble from. Two are the kept NAMES — Speaker Knockerz and
Cul-De-Sac — anchored at corner 1 (M0_Q0) and corner 4 (M100_Q100). The rest are
unnamed filter options you can drop into the morph; rename any keeper later.

Three "wrong math" levers, all stable by construction (poles capped at 0.99985):
  EDGE POLES   — radius toward 1 (high Q) = screaming near-self-oscillation.
  FOLDOVER     — SR is 39062.5, so a pole asked for at 39 kHz wraps to ~62 Hz
                 (SR-f); anything past Nyquist 19.5 kHz mirrors back down.
  DEAD NOTCH   — zero_depth -> 1.0 = zero on the unit circle = infinite null.
The corners stay LINEAR (runtime + null untouched); the metallic foldover comes
from these bright screamers driving the existing output saturation with no
oversampling at 39 k.

  python tools/weapons.py --list
  python tools/weapons.py                                   # default assembly
  python tools/weapons.py --corners speaker_knockerz razor siren cul_de_sac
  python tools/weapons.py --edge 2.5 --hot 1.3 --boost 2.2  # crank the violence
"""
from __future__ import annotations
import argparse, importlib.util, math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "physical_corners", ROOT / ".claude" / "skills" / "physical-corners" / "physical_corners.py")
pc = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(pc)   # type: ignore

SR   = 39062.5
PASS = [2.0, 1.0, 2.0, 1.0, 1.0]
RADIUS_CAP = 0.99985            # poles never reach the unit circle -> never blows up


def section(f, q=20.0, gain=1.0, zero_f=None, zero_depth=0.0):
    """One section, df2 kernel form. f>Nyquist wraps (foldover). zero_depth->1 = dead notch."""
    bw = f / max(q, 1e-3)
    radius = min(math.exp(-math.pi * bw / SR), RADIUS_CAP)
    th = 2 * math.pi * f / SR
    a1, a2 = -2 * radius * math.cos(th), radius * radius
    if zero_f:
        zr = min(zero_depth, 1.0)
        thz = 2 * math.pi * zero_f / SR
        b0, b1, b2 = gain, -2 * zr * math.cos(thz) * gain, zr * zr * gain
    else:
        b0, b1, b2 = gain, 0.0, 0.0
    return [2 + b1 / b0, 1 - b2 / b0, a1 + 2.0, 1 - a2, b0]


def _peak(secs):
    peak = 1e-9
    for i in range(220):
        f = 30.0 * (19000.0 / 30.0) ** (i / 219.0)
        w = 2 * math.pi * f / SR
        m = 1.0
        for k in secs:
            m *= pc._section_mag(k, w)
        peak = max(peak, m)
    return peak


def corner(specs, target_peak, hot, edge):
    secs = [section(f=s["f"], q=s.get("q", 20) * edge, gain=s.get("gain", 1.0),
                    zero_f=s.get("zero_f"), zero_depth=s.get("zero_depth", 0.0)) for s in specs]
    while len(secs) < 6:
        secs.append(PASS[:])
    active = [s for s in secs if s != PASS]
    if active:
        g = ((target_peak * hot) / _peak(secs)) ** (1.0 / len(active))
        for s in secs:
            if s != PASS:
                s[4] *= g
    return secs


# ── the palette. (specs, target_peak). Only the first two are kept NAMES. ────────
WEAPONS = {
    # low-frequency MASS + a "39 kHz" pole that wraps to ~62 Hz (foldover knock)
    "speaker_knockerz": ([{"f": 55, "q": 9, "gain": 1.0}, {"f": 82, "q": 8, "gain": 0.95},
                          {"f": 110, "q": 12, "gain": 0.85}, {"f": 165, "q": 16, "gain": 0.6},
                          {"f": 220, "q": 18, "gain": 0.4}, {"f": 39000, "q": 7, "gain": 0.7}], 9.0),
    # choked COLLAPSE: edge screamers, everything else a dead notch
    "cul_de_sac":       ([{"f": 780, "q": 120, "gain": 1.0, "zero_f": 260, "zero_depth": 1.0},
                          {"f": 1180, "q": 140, "gain": 0.8, "zero_f": 420, "zero_depth": 1.0},
                          {"f": 1650, "q": 140, "gain": 0.5, "zero_f": 3200, "zero_depth": 0.999}], 11.0),
    # — unnamed filter options —
    "tar_pit":  ([{"f": 140, "q": 6, "gain": 1.0}, {"f": 280, "q": 7, "gain": 0.8},
                  {"f": 420, "q": 8, "gain": 0.6}, {"f": 600, "q": 9, "gain": 0.4}], 8.0),
    "razor":    ([{"f": 2400, "q": 60, "gain": 1.0}, {"f": 3600, "q": 70, "gain": 0.7},
                  {"f": 5200, "q": 70, "gain": 0.5}, {"f": 6800, "q": 60, "gain": 0.3}], 10.0),
    "siren":    ([{"f": 700, "q": 90, "gain": 1.0}, {"f": 1400, "q": 90, "gain": 0.8},
                  {"f": 2100, "q": 80, "gain": 0.4}], 10.0),
    "static":   ([{"f": 400, "q": 55, "gain": 1.0}, {"f": 800, "q": 55, "gain": 0.85},
                  {"f": 1200, "q": 55, "gain": 0.7}, {"f": 1600, "q": 55, "gain": 0.55},
                  {"f": 2000, "q": 55, "gain": 0.4}, {"f": 2400, "q": 55, "gain": 0.3}], 9.0),
    "vice":     ([{"f": 900, "q": 160, "gain": 1.0, "zero_f": 300, "zero_depth": 1.0},
                  {"f": 920, "q": 160, "gain": 0.9, "zero_f": 3000, "zero_depth": 1.0}], 11.0),
    "rust":     ([{"f": 200, "q": 70, "gain": 1.0}, {"f": 237, "q": 70, "gain": 0.8},
                  {"f": 301, "q": 75, "gain": 0.6}, {"f": 400, "q": 75, "gain": 0.45},
                  {"f": 503, "q": 80, "gain": 0.3}], 10.0),
    # LOW corner — BODY + a deep carved notch (the talking_hedz signature: rounded
    # low weight AND a hole above it that defines the body against the mids). Zeros
    # are first-class here, not an afterthought.
    "low_body": ([{"f": 60, "q": 1.8, "gain": 1.0}, {"f": 110, "q": 2.2, "gain": 0.92},
                  {"f": 190, "q": 2.6, "gain": 0.78}, {"f": 320, "q": 3.0, "gain": 0.58},
                  {"f": 520, "q": 3.0, "gain": 0.36, "zero_f": 900, "zero_depth": 0.99}], 8.0),
    # HIGH corner — BITE: sharp high-Q peaks, with deep notches carved BETWEEN and
    # BELOW them. The notches are what make teeth cut — they widen the gaps so the
    # peaks read as separate stabs instead of a bright wash.
    "high_bite": ([{"f": 2000, "q": 35, "gain": 0.8, "zero_f": 1200, "zero_depth": 0.98},
                   {"f": 2900, "q": 50, "gain": 1.0, "zero_f": 3500, "zero_depth": 0.97},
                   {"f": 4200, "q": 55, "gain": 0.8, "zero_f": 5000, "zero_depth": 0.97},
                   {"f": 5800, "q": 55, "gain": 0.55}, {"f": 7600, "q": 50, "gain": 0.35}], 11.5),
}
NAMED = {"speaker_knockerz", "cul_de_sac"}
DEFAULT = ["speaker_knockerz", "tar_pit", "siren", "cul_de_sac"]


def report(corners, names):
    print(f"\n{'corner':<20} resonances  (Hz @ pole-radius)")
    print("-" * 64)
    for nm, c in zip(names, corners):
        items = []
        for s in c:
            if s == PASS:
                continue
            a1, a2 = s[2] - 2, 1 - s[3]
            r = math.sqrt(max(a2, 0))
            if r > 1e-6:
                fr = math.acos(max(-1, min(1, -a1 / (2 * r)))) * SR / (2 * math.pi)
                items.append(f"{int(round(fr))}@{r:.4f}")
        print(f"{nm:<20} {'   '.join(items)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corners", nargs=4, metavar="W", default=DEFAULT,
                    help="4 weapon names for corners 1..4 (M0_Q0, M100_Q0, M0_Q100, M100_Q100)")
    ap.add_argument("--list", action="store_true", help="show the palette")
    ap.add_argument("--boost", type=float, default=1.8)
    ap.add_argument("--hot", type=float, default=1.0, help="overall violence")
    ap.add_argument("--edge", type=float, default=1.0, help="push pole Q toward the unit circle")
    a = ap.parse_args()

    if a.list:
        print("weapon palette:")
        for k in WEAPONS:
            tag = "  [NAME]" if k in NAMED else ""
            print(f"  {k}{tag}")
        print(f"\nkept names: {', '.join(sorted(NAMED))}")
        return

    bad = [w for w in a.corners if w not in WEAPONS]
    if bad:
        print("unknown weapon(s):", ", ".join(bad), "\ntry --list"); return

    corners = [corner(WEAPONS[w][0], WEAPONS[w][1], a.hot, a.edge) for w in a.corners]
    report(corners, a.corners)
    slot = pc.write_cartridge(corners, "weapons", boost=a.boost)
    print(f"\nwrote [{' -> '.join(a.corners)}]  (boost={a.boost}, hot={a.hot}, edge={a.edge})\n  -> {slot}")
    if "speaker_knockerz" in a.corners:
        print("note: SK's '39000 Hz' pole shows at ~62 Hz above — foldover by placement.")


if __name__ == "__main__":
    main()
