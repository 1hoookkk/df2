"""TRENCH FACTORY — generator prototype (Phase 3, throwaway python).

Compose whole 6-stage x 4-corner bodies from the traced alphabet
(desk/letters.json), gate through the packed runtime, render through the
SHIPPED engine (pink noise, AGC only) so the EAR can judge. This is the first
audible proof that the letters make real sound.

Grammar honored:
- stage 6 = FOUNDATION always (33/33 law).
- other lanes sampled from the letter census; some MOVE (pole travels home->away).
- the LEDGER: per-stage DC sampled from the letter's measured dc distribution
  (median max +57 dB across the ROM) -> the drama, not flat normalization.
- Q100 corners = same centers, radii bloomed toward the rim (derived-Q, safe,
  centers invariant per CLAUDE.md 6).

Run:  python -m tools.factory_generate [count] [seed]
Out:  dev/tmp/factory/audition.html + wavs + miniplots
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

from pyruntime import packed_interp as pi
from pyruntime import trench_ffi
from src.utils.packed_runtime import evaluate_body

SR = 39062.5
OUT = os.path.join("dev", "tmp", "factory")
os.makedirs(OUT, exist_ok=True)
RIM = 0.9988

LETTERS = json.load(open(os.path.join("desk", "letters.json"), encoding="utf-8"))["letters"]
# lanes 1-5 draw from these; FOUNDATION is reserved for stage 6.
BODY_LETTERS = [n for n in LETTERS if n not in ("FOUNDATION", "PAD")]
WEIGHTS = np.array([LETTERS[n]["lanes"] for n in BODY_LETTERS], dtype=float)
WEIGHTS /= WEIGHTS.sum()


def _draw(dist, rng, log=False):
    lo = dist["p25"]
    hi = max(dist["p75"], lo * 1.0001 if lo > 0 else dist["p75"])
    if log and lo > 0:
        return float(np.exp(rng.uniform(np.log(lo), np.log(hi))))
    return float(rng.uniform(lo, hi))


def _biquad(fp, rp, name, letter, rng):
    """A stage biquad at pole (fp, rp) with the letter's zero + LEDGER gain."""
    wp = 2 * np.pi * fp / SR
    a1, a2 = -2 * rp * np.cos(wp), rp * rp
    if name == "REALROOT" and letter.get("real_zero_v"):
        v1, v2 = _draw(letter["real_zero_v"], rng), _draw(letter["real_zero_v"], rng)
        nb1, nb2 = -(v1 + v2), v1 * v2
    elif name in ("RESON",) or not letter.get("zero_f"):
        nb1, nb2 = 0.0, 0.0
    elif name == "FOUNDATION":
        fz, rz = _draw(letter["zero_f"], rng, log=True), 1.0
        wz = 2 * np.pi * fz / SR
        nb1, nb2 = -2 * rz * np.cos(wz), rz * rz
    else:
        ratio = _draw(letter["zero_ratio"], rng, log=True) if letter.get("zero_ratio") else 1.0
        fz = min(SR * 0.49, max(25.0, fp * ratio))
        rz = min(0.999, max(0.2, _draw(letter["zero_r"], rng)))
        if name == "CROWN":
            rz = min(0.849, rz)
        wz = 2 * np.pi * fz / SR
        nb1, nb2 = -2 * rz * np.cos(wz), rz * rz
    # LEDGER: hit a DC target sampled from the letter's measured dc distribution
    target_db = _draw(letter["dc"], rng) if letter.get("dc") else 0.0
    target = 10 ** (np.clip(target_db, -24.0, 60.0) / 20.0)
    den_dc, num_dc = 1 + a1 + a2, 1 + nb1 + nb2
    if abs(num_dc) < 1e-3:  # zero kills DC -> anchor the target at the pole band
        b0 = target * abs(den_dc)
    else:
        b0 = target * den_dc / num_dc
    return [b0, b0 * nb1, b0 * nb2, a1, a2]


def _words(bq):
    b0, b1, b2, a1, a2 = bq
    if abs(b0) < 1e-12:
        b0 = 1e-6
    c0, c1 = b1 / b0 + 2.0, 1.0 - b2 / b0
    return tuple(int(w) for w in pi.coeffs_to_words(c0, c1, a1 + 2.0, 1.0 - a2, b0))


def _bloom(rp):
    return min(RIM, 1.0 - (1.0 - rp) * 0.45)


def compose(rng) -> dict:
    """One body: 6 lanes x 4 corners of packed words -> corner dict A,B,C,D."""
    lanes = []
    for s in range(6):
        if s == 5:
            name = "FOUNDATION"
        else:
            name = str(rng.choice(BODY_LETTERS, p=WEIGHTS))
        letter = LETTERS[name]
        fh = _draw(letter["pole_f"], rng, log=True) if letter.get("pole_f") else 800.0
        mover = rng.random() < letter.get("mover_frac", 0.0)
        travel = _draw(letter["pole_travel_oct"], rng) if (mover and letter.get("pole_travel_oct")) else 0.0
        fa = float(np.clip(fh * (2 ** (travel * rng.choice([-1, 1]))), 40.0, SR * 0.45))
        rp = min(0.9970, max(0.5, _draw(letter["pole_r"], rng))) if letter.get("pole_r") else 0.9
        # four corners: home / away x Q0 / Qbloom (centers held under Q)
        home_q0 = _biquad(fh, rp, name, letter, rng)
        away_q0 = _biquad(fa, rp, name, letter, rng)
        home_q1 = _biquad(fh, _bloom(rp), name, letter, rng)
        away_q1 = _biquad(fa, _bloom(rp), name, letter, rng)
        lanes.append((home_q0, away_q0, home_q1, away_q1))
    corners = {}
    for ci, key in enumerate("ABCD"):
        corners[key] = [_words(lanes[s][ci]) for s in range(6)]
    return corners


def to_bytes(corners) -> bytes:
    out = bytearray()
    for k in "ABCD":
        for s in range(6):
            for w in corners[k][s]:
                out += int(w).to_bytes(2, "little")
    return bytes(out)


def gate(body_bytes) -> bool:
    try:
        r = evaluate_body(body_bytes, 5)
    except Exception:
        return False
    if not r.get("stable", False):
        return False
    # foundation present at stage 6 of corner A (unit-circle zero)
    cw = {k: [tuple(int(x) for x in np.frombuffer(body_bytes, "<u2").reshape(4, 6, 5)[ci, s])
              for s in range(6)] for ci, k in enumerate("ABCD")}
    b0, b1, b2, a1, a2 = pi.kernel_to_biquad(pi.packed_bilinear(cw, 0.0, 0.0)[5])
    return b0 != 0 and abs(b2 - b0) < 1e-9 * abs(b0)


def source(dur=2.6):
    np.random.seed(3)
    n = int(dur * SR)
    W = np.fft.rfft(np.random.randn(n))
    f = np.fft.rfftfreq(n, 1.0 / SR)
    f[0] = f[1]
    x = np.fft.irfft(W / np.sqrt(f), n=n)
    x = x / (np.max(np.abs(x)) + 1e-9)
    t = np.arange(n) / SR
    env = np.clip(np.minimum(t / 0.04, (dur - t) / 0.12), 0, 1)
    return (0.6 * x * env).astype(np.float32)


def render(body_bytes):
    import soundfile as sf  # noqa: F401 (imported for parity; not used inline)
    src = source()
    nb = max(1, (len(src) + 511) // 512)
    mpb = np.linspace(0.0, 1.0, nb).tolist()  # straight A->B sweep
    try:
        out = trench_ffi.engine_render_automated(body_bytes, mpb, [0.0] * nb, src.tobytes(),
                                                 sr=SR, block=512, saturation_enabled=False)
    except Exception:
        out = trench_ffi.engine_render_automated(body_bytes, mpb, [0.0] * nb, src.tobytes(), sr=SR, block=512)
    y = np.frombuffer(out, dtype=np.float32).copy()
    y = y / (float(np.max(np.abs(y))) or 1.0) * 0.9
    m = int(len(y) * 48000 / SR)
    return np.interp(np.linspace(0, len(y) - 1, m), np.arange(len(y)), y).astype(np.float32)


def resp(cw, m, q):
    rows = pi.packed_bilinear(cw, m, q)
    F = np.geomspace(30, SR * 0.49, 220)
    tot = np.zeros_like(F)
    for row in rows:
        b0, b1, b2, a1, a2 = pi.kernel_to_biquad(row)
        z = np.exp(-1j * 2 * np.pi * F / SR)
        h = (b0 + b1 * z + b2 * z**2) / (1 + a1 * z + a2 * z**2)
        tot += 20 * np.log10(np.maximum(np.abs(h), 1e-9))
    return F, tot


def miniplot(cw, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(4.6, 1.6), facecolor="#0a0c0b")
    M = np.linspace(0, 1, 90)
    F = np.geomspace(30, SR * 0.49, 220)
    img = np.array([resp(cw, m, 0.0)[1] for m in M]).T
    ax.pcolormesh(M, F, img, cmap="magma", shading="auto", vmin=-24, vmax=18)
    ax.set_yscale("log"); ax.set_ylim(60, SR * 0.49)
    ax.set_xticks([]); ax.set_yticks([]); ax.set_facecolor("#0a0c0b")
    fig.tight_layout(pad=0.15); fig.savefig(path, dpi=90, facecolor="#0a0c0b"); plt.close(fig)


def main():
    import soundfile as sf
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    rng = np.random.default_rng(seed)
    shipped = trench_ffi.engine_available()
    kept, tried = [], 0
    while len(kept) < count and tried < count * 40:
        tried += 1
        corners = compose(rng)
        b = to_bytes(corners)
        if len(b) == 240 and gate(b):
            kept.append((corners, b))
    cards = []
    for i, (corners, b) in enumerate(kept):
        wav = os.path.join(OUT, f"cand_{i}.wav")
        sf.write(wav, render(b), 48000)
        miniplot(corners, os.path.join(OUT, f"cand_{i}.png"))
        cards.append(f'<div class=c><b>candidate {i}</b><br><img src="cand_{i}.png" width=460>'
                     f'<br><audio controls preload=none src="cand_{i}.wav"></audio></div>')
    page = ("<!doctype html><meta charset=utf-8><title>factory audition</title>"
            "<style>body{background:#0a0c0b;color:#cfe9df;font:14px monospace;margin:24px;max-width:560px}"
            "h2{color:#e0a856}.c{margin:10px 0;padding:8px;background:#14181a;border-radius:6px}"
            "audio{width:100%;margin-top:4px}img{display:block;border-radius:4px}</style>"
            "<h2>TRENCH FACTORY — first audible proof</h2>"
            f"<small>{'SHIPPED engine, pink noise, AGC only, straight A->B morph' if shipped else 'PYTHON FALLBACK'}. "
            f"{len(kept)}/{tried} composed bodies passed the floor (stable + foundation).</small>"
            + "".join(cards))
    open(os.path.join(OUT, "audition.html"), "w", encoding="utf-8").write(page)
    print(f"kept {len(kept)}/{tried} (engine {'SHIPPED' if shipped else 'FALLBACK'})")
    print("open:", os.path.abspath(os.path.join(OUT, "audition.html")))


if __name__ == "__main__":
    main()
