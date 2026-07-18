"""GOD-TIER UTILITIES — four bodies, one discipline (the De-Esser recipe).

Every body: pole radius FIXED across Q (predictable ring), zero radius moves.
Q0 pose = exact pole-zero cancellation (flat, 0.0000 dB), Q100 = full action.
MORPH slides the frequency set coherently (log-encoded chord slide).

  HUM SURGEON     5 true notches on the mains comb. M0 = 60/120/.../300 (US),
                  M100 = 50/100/.../250 (EU). Tight (BW ~ f/12). STATIC:
                  hum is constant, Q is the depth dial, no react.
  DE-MUDDER       3 notches in the mud. M0 = 150/250/400, M100 = 300/450/700.
                  Q ~ 4. Baked react.
  DE-HARSHER      3 notches on the ice-pick band. M0 = 2.2/3.2/4.5k,
                  M100 = 3/4.3/6k. Q ~ 8. Baked react.
  PRESENCE RISER  3 resonators (poles proud of receding zeros) at the
                  intelligibility band. M0 = 1.8/2.6/3.6k, M100 = 2.5/3.6/5k.
                  React pushes presence on loud lines. Baked react.

Gates per body, packed runtime only: Q0 flatness, action depth/lift at Q100,
out-of-band preservation, morph-pose frequency landing. Stability 25x25 via
body-from-geometry. Numbers, not adjectives.
"""
from __future__ import annotations
import json, math, subprocess, sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path("C:/Users/hooki/df2")
WS = Path("C:/Users/hooki/df2-workstation")
OUT = WS / "dev/tmp/bytes_fix"
BIN = WS / "target/release/body-from-geometry.exe"
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "pyruntime"))
sys.path.insert(0, str(OUT))
from fix_bodies import FREQS
from build_all_archetypes import packed_db

SR = 39062.5
IDENT = {"pole_hz": 0.0, "pole_r": 0.0, "zero_hz": 0.0, "zero_r": 0.0, "scale": 1.0}


def resp_at(hz, rz, rp, z):
    w = 2 * math.pi * hz / SR
    b = abs(1 - 2 * rz * math.cos(w) * z + rz * rz * z * z) if False else None


def mag_at(hz, r, zpoint):
    """|1 - 2 r cos(w) z + r^2 z^2| at real z (1 = DC, -1 = Nyquist)."""
    w = 2 * math.pi * hz / SR
    return abs(1 - 2 * r * math.cos(w) * zpoint + r * r * zpoint * zpoint)


def norm_scale(hz, rz, rp, at_nyquist=False):
    z = -1.0 if at_nyquist else 1.0
    return mag_at(hz, rp, z) / mag_at(hz, rz, z)


def r_of_q(hz, q_factor):
    return math.exp(-math.pi * hz / (q_factor * SR))


def stage(hz, rp, rz, scale):
    return {"pole_hz": hz, "pole_r": rp, "zero_hz": hz, "zero_r": rz, "scale": scale}


def notch_body(freq_sets, q_factor, norm_nyq=False):
    """corners: [M0_Q0, M100_Q0, M0_Q100, M100_Q100]; freq_sets = (m0, m100)."""
    corners = []
    for q_on in (False, False, True, True):
        m_set = freq_sets[len(corners) % 2]
        stages = []
        for hz in m_set:
            rp = r_of_q(hz, q_factor)
            rz = 1.0 if q_on else rp
            sc = norm_scale(hz, rz, rp, norm_nyq) if q_on else 1.0
            stages.append(stage(hz, rp, rz, sc))
        stages += [dict(IDENT)] * (6 - len(m_set))
        corners.append(stages)
    return corners


def riser_body(freq_sets, rp, rz_on):
    corners = []
    for q_on in (False, False, True, True):
        m_set = freq_sets[len(corners) % 2]
        stages = []
        for hz in m_set:
            rz = rz_on if q_on else rp
            sc = norm_scale(hz, rz, rp) if q_on else 1.0
            stages.append(stage(hz, rp, rz, sc))
        stages += [dict(IDENT)] * (6 - len(m_set))
        corners.append(stages)
    return corners


BODIES = {
    "DEMO_hum_surgeon": notch_body(
        ([60, 120, 180, 240, 300], [50, 100, 150, 200, 250]), 12.0, norm_nyq=True),
    "DEMO_de_mudder": notch_body(([150, 250, 400], [300, 450, 700]), 4.0),
    "DEMO_de_harsher": notch_body(([2200, 3200, 4500], [3000, 4300, 6000]), 8.0),
    "DEMO_presence_riser": riser_body(([1800, 2600, 3600], [2500, 3600, 5000]),
                                      rp=0.92, rz_on=0.75),
}


def idx(hz):
    return int(np.argmin(np.abs(FREQS - hz)))


fails = []
fig, axes = plt.subplots(2, 2, figsize=(15, 9))
for ax, (name, corners) in zip(axes.flat, BODIES.items()):
    gpath = OUT / f"{name.lower()}.geometry.json"
    gpath.write_text(json.dumps({"name": name, "corners": corners}, indent=1))
    bpath = OUT / f"{name}.body240"
    res = subprocess.run([str(BIN), str(gpath), str(bpath)], capture_output=True, text=True)
    print(f"\n== {name}: {res.stdout.strip() or res.stderr.strip()}")
    if not bpath.exists():
        fails.append(f"{name}: compile failed"); continue
    body = bpath.read_bytes()

    flat = max(np.max(np.abs(packed_db(body, m, 0.0))) for m in (0.0, 0.5, 1.0))
    print(f"   Q0 flatness (M 0/50/100): max |dB| = {flat:.4f}")
    if flat > 0.1: fails.append(f"{name}: Q0 not flat ({flat:.3f})")

    centers_m0 = [s["pole_hz"] for s in corners[0] if s["pole_hz"] > 0]
    centers_m1 = [s["pole_hz"] for s in corners[1] if s["pole_hz"] > 0]
    for m, centers in ((0.0, centers_m0), (1.0, centers_m1)):
        db = packed_db(body, m, 1.0)
        vals = [db[idx(hz)] for hz in centers]
        tag = "M0 " if m == 0 else "M100"
        print(f"   {tag} Q100 at {[f'{h:g}' for h in centers]}: "
              + " ".join(f"{v:+.1f}" for v in vals) + " dB")
        if "riser" in name:
            if min(vals) < 3.0: fails.append(f"{name}: weak lift at {tag} ({min(vals):.1f} dB)")
        else:
            if max(vals) > -12.0: fails.append(f"{name}: shallow at {tag} ({max(vals):.1f} dB)")
    # out-of-band preservation at Q100/M0
    db = packed_db(body, 0.0, 1.0)
    if "hum" in name:
        guard = np.max(np.abs(db[FREQS >= 1000]))
        between = db[idx(90)]
        print(f"   1k+ preservation: {guard:.2f} dB | 90 Hz (between notches): {between:+.2f} dB")
        if guard > 0.3: fails.append(f"{name}: 1k+ disturbed ({guard:.2f})")
    elif "mudder" in name:
        guard = np.max(np.abs(db[FREQS >= 2000]))
        print(f"   2k+ preservation: {guard:.2f} dB")
        if guard > 0.5: fails.append(f"{name}: 2k+ disturbed ({guard:.2f})")
    elif "harsher" in name:
        lo = np.max(np.abs(db[FREQS <= 800]))
        air = np.max(np.abs(db[FREQS >= 9000]))
        print(f"   <=800 preservation: {lo:.2f} dB | 9k+ air: {air:.2f} dB")
        if max(lo, air) > 0.5: fails.append(f"{name}: band leakage ({lo:.2f}/{air:.2f})")
    else:
        lo = np.max(np.abs(db[FREQS <= 500]))
        print(f"   <=500 preservation: {lo:.2f} dB")
        if lo > 1.0: fails.append(f"{name}: low leakage ({lo:.2f})")

    for m, style in ((0.0, "-"), (1.0, "--")):
        for q, color, lw in ((0.0, "0.6", 1), (0.5, "#3a8", 1), (1.0, "#d33", 2)):
            ax.semilogx(FREQS, packed_db(body, m, q), style, color=color, lw=lw)
    ax.set_xlim(30, 19200); ax.set_ylim(-35, 12)
    ax.grid(True, which="both", alpha=0.3)
    ax.set_title(f"{name}  (solid M0, dashed M100; grey Q0 / green Q50 / red Q100)")

fig.tight_layout(); fig.savefig(OUT / "utilities_tf.png", dpi=110)
print(f"\nplot -> {OUT / 'utilities_tf.png'}")
print("GATES:", "ALL PASS" if not fails else "FAIL:\n  " + "\n  ".join(fails))
