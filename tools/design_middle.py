#!/usr/bin/env python3
"""design_middle.py — design the MORPH MIDDLE backwards. The corner design is the
damage. The runtime interpolates coefficients linearly; this searches corner pairs
until the c-domain morph (exactly what the runtime does) makes the middle do what
you ask, then writes the hot-reload slot with MORPH sweeping A->B (Q parked).

  python tools/design_middle.py hole --at 0.5     # the resonance gets cancelled in the center
  python tools/design_middle.py leap --at 0.5     # the resonance rushes through a narrow zone

Behaviors (only what's actually achievable — verified by the magnitude response):
  hole  a moving ZERO crosses a static resonance and cancels it at --at -> a real
        magnitude dropout in the middle, tall and alive at both ends. (You can't kill
        a pole from the middle — proven; the hole has to come from the numerator.)
  leap  resonant throughout, but the frequency covers most of its span in a narrow
        zone (a hair-trigger sweep). NOTE: single-pole cliffs sit near the band edges,
        so --at biases it but the report tells you where it truly lands.
"""
from __future__ import annotations
import argparse, importlib.util, math, random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "physical_corners", ROOT / ".claude" / "skills" / "physical-corners" / "physical_corners.py")
pc = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(pc)   # type: ignore

SR     = 39062.5
TWO_PI = 2 * math.pi
PASS   = [2.0, 1.0, 2.0, 1.0, 1.0]
GRID   = [30.0 * (18000.0 / 30.0) ** (i / 127) for i in range(128)]
WGRID  = [TWO_PI * f / SR for f in GRID]


def kc(fp, rp, fz=None, rz=0.0, gain=1.0):
    """Pole (fp,rp) + optional zero (fz,rz) -> df2 kernel form [c0..c4]."""
    a1 = -2 * rp * math.cos(TWO_PI * fp / SR)
    a2 = rp * rp
    if fz:
        thz = TWO_PI * fz / SR
        b0, b1, b2 = gain, -2 * rz * math.cos(thz) * gain, rz * rz * gain
    else:
        b0, b1, b2 = gain, 0.0, 0.0
    return [2 + b1 / b0, 1 - b2 / b0, a1 + 2.0, 1 - a2, b0]


def interp(cA, cB, t):
    return [cA[i] + (cB[i] - cA[i]) * t for i in range(5)]


def peak_mag(c):
    return max(pc._section_mag(c, w) for w in WGRID)


def pole_freq(c):
    a1, a2 = c[2] - 2, 1 - c[3]
    r = math.sqrt(max(a2, 0.0))
    disc = a1 * a1 - 4 * a2
    if disc < 0 and r > 1e-9:
        return math.acos(max(-1.0, min(1.0, -a1 / (2 * r)))) * SR / TWO_PI, r, True
    return None, r, False


# ── HOLE: a zero sweeps onto a static resonance and cancels it at t_star ─────────
def hole_sections(P):
    fp, rp, fzA, fzB, rz = P
    return kc(fp, rp, fzA, rz), kc(fp, rp, fzB, rz)

def hole_sample():
    return [10 ** random.uniform(2, 3.6), 0.99,                  # pole freq, sharp
            10 ** random.uniform(1.6, 4.2), 10 ** random.uniform(1.6, 4.2),  # zero A, zero B
            random.uniform(0.93, 0.999)]                          # zero radius

def hole_perturb(P):
    fp, rp, fzA, fzB, rz = P
    return [max(80, min(4000, fp * math.exp(random.gauss(0, .1)))), rp,
            max(40, min(16000, fzA * math.exp(random.gauss(0, .12)))),
            max(40, min(16000, fzB * math.exp(random.gauss(0, .12)))),
            max(0.9, min(0.999, rz + random.gauss(0, .01)))]

def hole_score(P, t_star):
    cA, cB = hole_sections(P)
    p0, p1, pt = peak_mag(interp(cA, cB, 0.0)), peak_mag(interp(cA, cB, 1.0)), peak_mag(interp(cA, cB, t_star))
    if p0 < 2.0 or p1 < 2.0:
        return -1e18                       # both ends must be a real resonance
    return min(p0, p1) - 5.0 * pt          # tall ends, deep dip at t_star


# ── LEAP: resonant throughout, frequency motion concentrated near t_star ─────────
def leap_sections(P):
    fA, rA, fB, rB = P
    return kc(fA, rA), kc(fB, rB)

def leap_sample():
    return [10 ** random.uniform(1.6, 4.2), random.uniform(0.9, 0.99985),
            10 ** random.uniform(1.6, 4.2), random.uniform(0.9, 0.99985)]

def leap_perturb(P):
    fA, rA, fB, rB = P
    return [max(40, min(16000, fA * math.exp(random.gauss(0, .12)))), max(.9, min(.99985, rA + random.gauss(0, .01))),
            max(40, min(16000, fB * math.exp(random.gauss(0, .12)))), max(.9, min(.99985, rB + random.gauss(0, .01)))]

def leap_score(P, t_star):
    cA, cB = leap_sections(P)
    fs = []
    for k in range(41):
        f, _, alive = pole_freq(interp(cA, cB, k / 40))
        if not alive:
            return -1e18                   # must stay resonant throughout
        fs.append(f)
    w = 0.08
    f_lo = pole_freq(interp(cA, cB, max(0.0, t_star - w)))[0]
    f_hi = pole_freq(interp(cA, cB, min(1.0, t_star + w)))[0]
    in_jump = abs(f_hi - f_lo)
    total = sum(abs(fs[k + 1] - fs[k]) for k in range(40))
    out_motion = total - in_jump
    return in_jump - 1.5 * max(0.0, out_motion)


BEHAVIORS = {
    "hole": (hole_sample, hole_perturb, hole_score, hole_sections),
    "leap": (leap_sample, leap_perturb, leap_score, leap_sections),
}


def search(behavior, t_star, tries, climb):
    sample, perturb, score, _ = BEHAVIORS[behavior]
    best, bP = -1e30, None
    for _ in range(tries):
        P = sample()
        s = score(P, t_star)
        if s > best:
            best, bP = s, P
    for _ in range(climb):
        P = perturb(bP)
        s = score(P, t_star)
        if s > best:
            best, bP = s, P
    return bP, best


def verify(behavior, P):
    cA, cB = BEHAVIORS[behavior][3](P)
    if behavior == "hole":
        print(f"\n  {'morph':<7} peak resonance (dB)")
        print("  " + "-" * 40)
        for k in range(11):
            db = 20 * math.log10(max(peak_mag(interp(cA, cB, k / 10)), 1e-6))
            bar = "#" * max(0, int(db))
            print(f"  {k/10:<7.2f} {db:6.1f}  {bar}")
    else:
        print(f"\n  {'morph':<7} resonance")
        print("  " + "-" * 40)
        prev = None; jumps = []
        for k in range(11):
            f, r, _ = pole_freq(interp(cA, cB, k / 10))
            if prev is not None:
                jumps.append((abs(f - prev), k / 10))
            print(f"  {k/10:<7.2f} {f:8.1f} Hz  @ r={r:.4f}")
            prev = f
        big = max(jumps)
        print(f"  -> biggest jump lands around morph {big[1]:.1f}")


def build_corner(c, peak=5.0):
    c = c[:]
    pk = peak_mag(c)
    c[4] *= peak / max(pk, 1e-9)
    return [c] + [PASS[:] for _ in range(5)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("behavior", choices=list(BEHAVIORS))
    ap.add_argument("--at", type=float, default=0.5)
    ap.add_argument("--tries", type=int, default=9000)
    ap.add_argument("--climb", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    if a.seed is not None:
        random.seed(a.seed)

    P, best = search(a.behavior, a.at, a.tries, a.climb)
    if P is None or best <= -1e17:
        print(f"no {a.behavior} found at t={a.at}; try a different --at or more --tries.")
        return
    print(f"\n{a.behavior.upper()} @ morph {a.at}   (score {best:.2f})")
    cA, cB = BEHAVIORS[a.behavior][3](P)
    verify(a.behavior, P)

    if a.no_write:
        print("\n(--no-write: nothing loaded)")
        return
    cor = [build_corner(cA), build_corner(cB), build_corner(cA), build_corner(cB)]
    slot = pc.write_cartridge(cor, f"middle_{a.behavior}", boost=1.6)
    print(f"\nwrote -> {slot}\n  sweep MORPH left->right to hear it (Q parked)")


if __name__ == "__main__":
    main()
