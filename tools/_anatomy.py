"""Pole/zero anatomy of a single body at one (M,Q) frame.

Each biquad stage's poles and zeros are extracted EXACTLY from its kernel
coefficients via `kernel_to_biquad` and root-finding on the resulting biquad
numerator/denominator. Output:
- a per-stage table (freq, radius for each pole and zero)
- an annotated response plot with pole triangles (up, red) and zero triangles
  (down, blue), sized by how prominently they ring
"""
from __future__ import annotations
import json, math, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pyruntime import trench_ffi as ff
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db

AUTH_SR = 39062.5
FREQS = np.logspace(math.log10(20), math.log10(16000), 1024)


def kernel_to_biquad(c0, c1, c2, c3, c4):
    """Exact conversion (matches trench-core/src/minifloat.rs::kernel_to_biquad)."""
    return c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, c2 - 2.0, 1.0 - c3


def _quadratic_roots(a, b, c):
    """Roots of a·z² + b·z + c, returning complex magnitude + freq angle pairs.
    For a stable biquad with conjugate roots we just need radius + angular freq."""
    if abs(a) < 1e-15:
        return []
    disc = b * b - 4.0 * a * c
    if disc < 0:
        # complex conjugate pair: z = (-b ± j√|disc|) / (2a)
        r_sq = c / a
        r = math.sqrt(max(r_sq, 0.0))
        # real(z) = -b/(2a); angle = acos(real/r)
        if r > 1e-12:
            cos_theta = (-b) / (2.0 * a * r)
            cos_theta = max(-1.0, min(1.0, cos_theta))
            theta = math.acos(cos_theta)
        else:
            theta = 0.0
        return [{"radius": r, "angle": theta}]
    else:
        # real roots — sit on the real axis (theta = 0 if positive, pi if negative)
        sq = math.sqrt(disc)
        z1 = (-b + sq) / (2.0 * a)
        z2 = (-b - sq) / (2.0 * a)
        out = []
        for z in (z1, z2):
            out.append({"radius": abs(z), "angle": 0.0 if z >= 0 else math.pi})
        return out


def per_stage_anatomy(body, m=0.0, q=0.0):
    rows = ff.packed_interpolate(body, m, q)  # 6 kernel-form stages
    stages = []
    for i, c in enumerate(rows):
        b0, b1, b2, a1, a2 = kernel_to_biquad(*c)
        poles = _quadratic_roots(1.0, a1, a2)        # z² + a1·z + a2
        zeros = _quadratic_roots(b0, b1, b2)          # b0·z² + b1·z + b2
        stages.append({
            "stage": i + 1,
            "biquad": {"b0": b0, "b1": b1, "b2": b2, "a1": a1, "a2": a2},
            "poles": poles, "zeros": zeros,
        })
    return stages


def _angle_to_hz(angle: float) -> float:
    return angle * AUTH_SR / (2.0 * math.pi)


def _approx_peak_height_db(radius: float) -> float:
    """For a single-stage 2nd-order biquad, peak height of a high-Q resonance
    near the unit circle is ~ 20·log10(1/(1-r)) — useful for plot marker sizing."""
    r = min(0.9999, max(0.0, radius))
    return 20.0 * math.log10(1.0 / (1.0 - r))


def print_table(stages, label=""):
    print(f"\n  {label}")
    print(f"  {'stage':>5} {'poles (freq Hz / radius)':<46} {'zeros (freq Hz / radius)':<46}")
    print(f"  {'-'*5} {'-'*46} {'-'*46}")
    for s in stages:
        p_strs = [f"{_angle_to_hz(p['angle']):>6.0f}Hz r={p['radius']:.4f}" for p in s["poles"]]
        z_strs = [f"{_angle_to_hz(z['angle']):>6.0f}Hz r={z['radius']:.4f}" for z in s["zeros"]]
        print(f"  {s['stage']:>5}   {' · '.join(p_strs):<44}   {' · '.join(z_strs):<44}")


def render_anatomy(body, title, out_path, m=0.0, q=0.0):
    stages = per_stage_anatomy(body, m, q)
    rows = ff.packed_interpolate(body, m, q)
    db = cascade_response_db([EncodedCoeffs(*r) for r in rows], FREQS, AUTH_SR)

    fig, ax = plt.subplots(figsize=(9.2, 4.6), dpi=120)
    ax.semilogx(FREQS, db, lw=2.0, color="#cfe9dc", label="response at this (M,Q)")

    def _y_at(f_hz):
        return float(db[np.argmin(np.abs(FREQS - f_hz))])

    # POLES: red up-triangles
    for s in stages:
        for p in s["poles"]:
            f = _angle_to_hz(p["angle"])
            r = p["radius"]
            if not (30.0 <= f <= 16500.0):
                continue
            size = 40 + 600 * max(0.0, r - 0.75) ** 1.5
            alpha = max(0.35, min(1.0, r))
            ax.scatter([f], [_y_at(f) + 3], s=size, marker="^",
                       color=(1.0, 0.35, 0.35, alpha), edgecolor="white", linewidths=0.6, zorder=10)
            ax.annotate(f"s{s['stage']}\nr={r:.3f}", (f, _y_at(f) + 5),
                        fontsize=7, color="#ff9d9d", ha="center", va="bottom")

    # ZEROS: blue down-triangles
    for s in stages:
        for z in s["zeros"]:
            f = _angle_to_hz(z["angle"])
            r = z["radius"]
            if not (30.0 <= f <= 16500.0):
                continue
            size = 40 + 600 * max(0.0, r - 0.75) ** 1.5
            alpha = max(0.35, min(1.0, r))
            ax.scatter([f], [_y_at(f) - 3], s=size, marker="v",
                       color=(0.35, 0.7, 1.0, alpha), edgecolor="white", linewidths=0.6, zorder=10)
            ax.annotate(f"s{s['stage']}\nr={r:.3f}", (f, _y_at(f) - 5),
                        fontsize=7, color="#9dcdff", ha="center", va="top")

    ax.set_xlim(40, 16000)
    ax.set_ylim(-55, 35)
    ax.grid(alpha=0.16)
    ax.set_title(title, fontsize=14, color="#cfe9dc", pad=10)
    ax.set_xlabel("frequency (Hz)", color="#9aa")
    ax.set_ylabel("response (dB)", color="#9aa")
    ax.text(0.99, 0.97, "▲ pole (rings here)   ▼ zero (cuts here)",
            transform=ax.transAxes, ha="right", va="top", fontsize=9,
            color="#cfe9dc", family="monospace")
    ax.set_facecolor("#0c0f0e")
    fig.patch.set_facecolor("#0c0f0e")
    for sp in ax.spines.values():
        sp.set_color("#33433c")
    ax.tick_params(colors="#9aa", labelsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return stages


def main():
    # Demo on three bodies: a physics cavity, a violence pick, and a wild pick.
    OUT = ROOT / "dev" / "tmp" / "thumbs"
    OUT.mkdir(parents=True, exist_ok=True)

    samples = [
        ("Cavity — wine_bottle morph",
         "dev/tmp/target_browser/cavity_s8002/cand_51", "anatomy_cavity"),
        ("Wild — mid->low razor",
         "dev/tmp/target_browser/wild_s13002/cand_70", "anatomy_wild"),
        ("Reference — Talking Hedz",
         None, "anatomy_talking_hedz"),
    ]

    for title, cdir, out_stem in samples:
        if cdir is None:
            # Talking Hedz reference
            import json as _j
            d = _j.load(open(ROOT / "bodies/rom/P2k_013_talking_hedz.json"))
            kf = {k["label"]: k for k in d["keyframes"]}
            flat = []
            for lab in ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]:
                for w in kf[lab]["packedWords"]:
                    flat.extend(int(x) & 0xFFFF for x in w)
            body = struct.pack("<" + "H" * 120, *flat)
        else:
            cdir = ROOT / cdir
            body = (cdir / f"{cdir.name}.body240").read_bytes()
        stages = render_anatomy(body, title, OUT / f"{out_stem}.png", m=0.0, q=0.0)
        print_table(stages, label=title)


if __name__ == "__main__":
    main()
