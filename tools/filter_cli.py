#!/usr/bin/env python3
"""filter-cli — the geometry-IR inspector/compiler front door.

  python -m tools.filter_cli validate x.geometry.json
  python -m tools.filter_cli pack     x.geometry.json [out.body240]
  python -m tools.filter_cli plot     x.geometry.json [--out plot.png]
  python -m tools.filter_cli diff     a.geometry.json b.geometry.json
  python -m tools.filter_cli decode   x.body240 [out.geometry.json]

pack delegates to trench-core's body-from-geometry (THE compiler; grid-certifies
stability). This script never packs bytes itself.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "filters" / "geometry.schema.json"
COMPILER = ROOT / "target" / "release" / "body-from-geometry.exe"
RUNTIME_SR = 39062.5
CORNERS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]


def load(path):
    d = json.loads(Path(path).read_text())
    errs = []
    corners = d.get("corners")
    if not isinstance(d.get("name"), str) or not d.get("name"):
        errs.append("name: required non-empty string")
    if not (isinstance(corners, list) and len(corners) == 4):
        errs.append("corners: need exactly 4 (M0_Q0, M100_Q0, M0_Q100, M100_Q100)")
    else:
        for ci, c in enumerate(corners):
            if not (isinstance(c, list) and len(c) == 6):
                errs.append(f"corners[{ci}]: need exactly 6 stages")
                continue
            for si, s in enumerate(c):
                for k in ("pole_hz", "pole_r", "zero_hz", "zero_r", "scale"):
                    if not isinstance(s.get(k), (int, float)):
                        errs.append(f"corners[{ci}][{si}].{k}: missing/not a number")
                if isinstance(s.get("pole_r"), (int, float)) and not (0 <= s["pole_r"] < 1.0):
                    errs.append(f"corners[{ci}][{si}].pole_r={s['pole_r']}: outside [0,1)")
                if isinstance(s.get("pole_hz"), (int, float)) and not (0 <= s["pole_hz"] <= RUNTIME_SR / 2):
                    errs.append(f"corners[{ci}][{si}].pole_hz={s['pole_hz']}: outside [0, {RUNTIME_SR/2}]")
    if errs:
        for e in errs:
            print("INVALID:", e)
        sys.exit(1)
    return d


def stage_response(s, freqs):
    # one DF2 stage magnitude from authoring vars, at the runtime rate
    wp = 2 * math.pi * s["pole_hz"] / RUNTIME_SR
    wz = 2 * math.pi * s["zero_hz"] / RUNTIME_SR
    rp, rz, k = s["pole_r"], s["zero_r"], s["scale"]
    out = []
    for f in freqs:
        w = 2 * math.pi * f / RUNTIME_SR
        z = complex(math.cos(-w), math.sin(-w))
        num = (1 - rz * complex(math.cos(wz), math.sin(wz)) * z) * \
              (1 - rz * complex(math.cos(-wz), math.sin(-wz)) * z)
        den = (1 - rp * complex(math.cos(wp), math.sin(wp)) * z) * \
              (1 - rp * complex(math.cos(-wp), math.sin(-wp)) * z)
        out.append(k * abs(num) / max(abs(den), 1e-12))
    return out


def corner_db(corner, freqs):
    mags = [1.0] * len(freqs)
    for s in corner:
        r = stage_response(s, freqs)
        mags = [m * x for m, x in zip(mags, r)]
    return [20 * math.log10(max(m, 1e-9)) for m in mags]


def mfdec(w):
    u = w + 1
    if u == 65536: return 1.0
    if u == 1: return 0.0
    e = (u >> 12) & 0xF; m = u & 0xFFF
    return (m / 4096.0 if e == 0 else (m + 4096.0) / 8192.0) * 2.0 ** (e - 15)


def root_pair(dm, dr):
    q = 1.0 - dr; c = 4.0 * dm + dr; p = c - 2.0
    if p == 0 and q == 0:
        return ("deg", 0.0, 0.0)
    disc = p * p - 4 * q
    if disc < 0:
        r = math.sqrt(q)
        return ("conj", math.acos(max(-1.0, min(1.0, -p / (2 * r)))) / (2 * math.pi) * RUNTIME_SR, r)
    sq = math.sqrt(disc)
    return ("real", (-p + sq) / 2, (-p - sq) / 2)


def cmd_decode(args):
    raw = Path(args[0]).read_bytes()
    if len(raw) != 240:
        sys.exit(f"not a body240 ({len(raw)} bytes)")
    words = [int.from_bytes(raw[i:i+2], "little") for i in range(0, 240, 2)]
    corners, warn = [], 0
    for c in range(4):
        stages = []
        for st in range(6):
            w = words[(c * 6 + st) * 5:(c * 6 + st) * 5 + 5]
            z = root_pair(mfdec(w[0]), mfdec(w[1]))
            pl = root_pair(mfdec(w[2]), mfdec(w[3]))
            stage = {"pole_hz": 0.0, "pole_r": 0.0, "zero_hz": 0.0, "zero_r": 0.0,
                     "scale": 4 * mfdec(w[4])}
            if pl[0] == "conj": stage["pole_hz"], stage["pole_r"] = round(pl[1], 4), pl[2]
            elif pl[0] == "real": stage["pole_real_roots"] = [pl[1], pl[2]]; warn += 1
            if z[0] == "conj": stage["zero_hz"], stage["zero_r"] = round(z[1], 4), z[2]
            elif z[0] == "real": stage["zero_real_roots"] = [z[1], z[2]]; warn += 1
            stages.append(stage)
        corners.append(stages)
    out = Path(args[1]) if len(args) > 1 else Path(args[0]).with_suffix(".geometry.json")
    name = Path(args[0]).stem
    out.write_text(json.dumps({"name": name, "decodedFrom": Path(args[0]).name,
                               "corners": corners}, indent=1))
    print("wrote", out, f"({warn} real-root lanes flagged)" if warn else "(all conjugate/off)")


def cmd_validate(args):
    d = load(args[0])
    print(f"OK: {d['name']} — 4 corners x 6 stages, in range")


def cmd_pack(args):
    load(args[0])
    out = Path(args[1]) if len(args) > 1 else Path(args[0]).with_suffix("").with_suffix(".body240")
    if not COMPILER.exists():
        sys.exit(f"compiler missing: {COMPILER}\nbuild: cargo build --release -p trench-core --bin body-from-geometry")
    r = subprocess.run([str(COMPILER), args[0], str(out)], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    sys.exit(r.returncode)


def cmd_plot(args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    d = load(args[0])
    out = None
    if "--out" in args:
        out = args[args.index("--out") + 1]
    freqs = [20 * (10 ** (i / 199 * 3)) for i in range(200)]  # 20 Hz .. 20 kHz log
    fig, ax = plt.subplots(figsize=(10, 5))
    for name, corner in zip(CORNERS, d["corners"]):
        ax.semilogx(freqs, corner_db(corner, freqs), label=name)
    ax.set_title(d["name"])
    ax.set_xlabel("Hz"); ax.set_ylabel("dB"); ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    out = out or str(Path(args[0]).with_suffix("").with_suffix(".png"))
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print("wrote", out)


def cmd_diff(args):
    a, b = load(args[0]), load(args[1])
    changed = 0
    for ci, (ca, cb) in enumerate(zip(a["corners"], b["corners"])):
        for si, (sa, sb) in enumerate(zip(ca, cb)):
            for k in ("pole_hz", "pole_r", "zero_hz", "zero_r", "scale"):
                if not math.isclose(sa[k], sb[k], rel_tol=1e-9, abs_tol=1e-12):
                    print(f"{CORNERS[ci]} stage{si} {k}: {sa[k]:g} -> {sb[k]:g}  (d {sb[k]-sa[k]:+g})")
                    changed += 1
    print("identical" if changed == 0 else f"{changed} values changed")


def main():
    cmds = {"validate": cmd_validate, "pack": cmd_pack, "plot": cmd_plot, "diff": cmd_diff, "decode": cmd_decode}
    if len(sys.argv) < 3 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(2)
    cmds[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
