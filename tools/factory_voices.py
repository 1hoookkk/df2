"""TRENCH FACTORY — voice-space generator (the no-regret architecture).

A body is <=6 VOICES. Each voice is a letter tracing a JOURNEY: a home frame and
an away frame (pole center + radius), with its zero ratio-linked to the pole so
it travels coherently. The four packed corners are DERIVED from the voices:
  C0 = home / Q-relaxed   C1 = away / Q-relaxed
  C2 = home / Q-pressed   C3 = away / Q-pressed   (centers HELD under Q, §6)
Because every corner is the same continuous voice sampled at a frame, lane
correspondence is structural — the lift is free and the middle can't scramble.

The LEDGER is coordinated, not 24 independent draws: each moving voice is
normalized to a modest peak, the FOUNDATION carries the DC bank, and one global
trim keeps the cascade gain-managed (the +45 dB monsters are gone by design).

Run:  python -m tools.factory_voices [count] [seed]
Out:  dev/tmp/factory_voices/ (candidates_plot.png + audition.html + wavs)
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
OUT = os.path.join("dev", "tmp", "factory_voices")
os.makedirs(OUT, exist_ok=True)
RIM = 0.9985
FGRID = np.geomspace(30.0, SR * 0.49, 240)

LETTERS = json.load(open(os.path.join("desk", "letters.json"), encoding="utf-8"))["letters"]
BODY_LETTERS = [n for n in LETTERS if n not in ("FOUNDATION", "PAD")]
WEIGHTS = np.array([LETTERS[n]["lanes"] for n in BODY_LETTERS], dtype=float)
WEIGHTS /= WEIGHTS.sum()
RESONANT = {"CROWN", "CANYON", "RESON"}


def _draw(dist, rng, log=False):
    lo = dist["p25"]
    hi = max(dist["p75"], lo * 1.0001 if lo > 0 else dist["p75"])
    if log and lo > 0:
        return float(np.exp(rng.uniform(np.log(lo), np.log(hi))))
    return float(rng.uniform(lo, hi))


def _bloom(r):
    return min(RIM, 1.0 - (1.0 - r) * 0.45)


def _mag_db(bq, F):
    b0, b1, b2, a1, a2 = bq
    z = np.exp(-1j * 2 * np.pi * F / SR)
    h = (b0 + b1 * z + b2 * z**2) / (1 + a1 * z + a2 * z**2)
    return 20 * np.log10(np.maximum(np.abs(h), 1e-12))


def sample_voice(rng, stage_idx):
    """One voice: letter identity + a home/away journey + coherent zero + target level."""
    name = "FOUNDATION" if stage_idx == 5 else str(rng.choice(BODY_LETTERS, p=WEIGHTS))
    L = LETTERS[name]
    fh = _draw(L["pole_f"], rng, log=True) if L.get("pole_f") else 800.0
    mover = rng.random() < L.get("mover_frac", 0.0)
    travel = _draw(L["pole_travel_oct"], rng) if (mover and L.get("pole_travel_oct")) else 0.0
    fa = float(np.clip(fh * (2 ** (travel * rng.choice([-1.0, 1.0]))), 40.0, SR * 0.45))
    rbase = float(np.clip(_draw(L["pole_r"], rng), 0.5, 0.997)) if L.get("pole_r") else 0.9
    ra = float(np.clip(rbase * (1.0 + rng.uniform(-0.03, 0.03)), 0.5, 0.997))
    # zero identity sampled ONCE -> coherent across both frames
    ratio = _draw(L["zero_ratio"], rng, log=True) if L.get("zero_ratio") else 1.0
    zr = float(np.clip(_draw(L["zero_r"], rng), 0.2, 0.999)) if L.get("zero_r") else 0.0
    if name == "CROWN":
        zr = min(0.849, zr)
    elif name in ("CANYON", "SCOOP", "AIRCUT"):
        zr = max(0.85, zr)
    zf_band = _draw(L["zero_f"], rng, log=True) if L.get("zero_f") else None
    realv = None
    if name == "REALROOT" and L.get("real_zero_v"):
        realv = (_draw(L["real_zero_v"], rng), _draw(L["real_zero_v"], rng))
    # target level: foundation carries the bank; others sit modest
    if name == "FOUNDATION":
        bank = float(np.clip(_draw(L["dc"], rng) if L.get("dc") else 40.0, 22.0, 50.0))
        peak = None
    else:
        bank = None
        # resonant voices BLOOM (the drama); cut voices mostly carve near unity;
        # real-root sits between. These are the loud opposing gestures the ROM has.
        if name in RESONANT:
            peak = rng.uniform(12.0, 30.0)
        elif name == "REALROOT":
            peak = rng.uniform(0.0, 12.0)
        else:  # AIRCUT, SCOOP — carvers
            peak = rng.uniform(-2.0, 6.0)
    return {"name": name, "L": L, "fh": fh, "fa": fa, "rh": rbase, "ra": ra,
            "ratio": ratio, "zr": zr, "zf_band": zf_band, "realv": realv,
            "bank": bank, "peak": peak, "gain": 1.0}


def _num(voice, f_pole):
    name = voice["name"]
    if name == "REALROOT" and voice["realv"]:
        v1, v2 = voice["realv"]
        return -(v1 + v2), v1 * v2
    if name == "RESON" or voice["zr"] == 0.0 or not voice["L"].get("zero_f"):
        return 0.0, 0.0
    if name == "FOUNDATION":
        fz, rz = (voice["zf_band"] or 10000.0), 1.0
    else:
        fz, rz = float(np.clip(f_pole * voice["ratio"], 25.0, SR * 0.49)), voice["zr"]
    wz = 2 * np.pi * fz / SR
    return -2 * rz * np.cos(wz), rz * rz


def voice_biquad(voice, frame, pressed):
    """Biquad for a voice at a frame (home/away) and Q state (relaxed/pressed).
    Pressed blooms the radius; the CENTER is untouched (§6 invariant)."""
    f = voice["fh"] if frame == "home" else voice["fa"]
    r = voice["rh"] if frame == "home" else voice["ra"]
    if pressed:
        r = _bloom(r)
    wp = 2 * np.pi * f / SR
    a1, a2 = -2 * r * np.cos(wp), r * r
    nb1, nb2 = _num(voice, f)
    g = voice["gain"]
    return [g, g * nb1, g * nb2, a1, a2]


def set_gain(voice):
    """Compute the voice's gain ONCE from its home/relaxed frame -> applied to all
    four of its frames so the journey tracks level naturally."""
    voice["gain"] = 1.0
    base = voice_biquad(voice, "home", False)
    if voice["name"] == "FOUNDATION":
        dc = _mag_db(base, np.array([32.0]))[0]
        voice["gain"] = 10 ** ((voice["bank"] - dc) / 20.0)
    else:
        mx = float(np.max(_mag_db(base, FGRID)))
        voice["gain"] = 10 ** ((voice["peak"] - mx) / 20.0)


def _words(bq):
    b0, b1, b2, a1, a2 = bq
    if abs(b0) < 1e-12:
        b0 = 1e-6
    c0, c1 = b1 / b0 + 2.0, 1.0 - b2 / b0
    return tuple(int(w) for w in pi.coeffs_to_words(c0, c1, a1 + 2.0, 1.0 - a2, b0))


def compose(rng):
    """Sample voices, set coherent gains, derive the 4 corners, global-trim."""
    voices = [sample_voice(rng, s) for s in range(6)]
    # guarantee resonant content: every body needs voices that SING, not only
    # carve. If fewer than 2 of the 5 movers resonate, recast the quietest.
    res_idx = [s for s in range(5) if voices[s]["name"] in RESONANT]
    for s in range(5):
        if len(res_idx) >= 2:
            break
        if s not in res_idx:
            voices[s] = sample_voice(rng, s)
            while voices[s]["name"] not in RESONANT:
                voices[s] = sample_voice(rng, s)
            res_idx.append(s)
    for v in voices:
        set_gain(v)
    frames = [("home", False), ("away", False), ("home", True), ("away", True)]
    corner_bq = {k: [voice_biquad(voices[s], fr, pr) for s in range(6)]
                 for k, (fr, pr) in zip("ABCD", frames)}
    # NO absolute level cap — that is the ENGINE'S AGC job (it engages on hot
    # filter peaks by design; capping here just makes timid bodies). The
    # generator owns SHAPE (the coordinated per-voice ledger) and MOTION
    # (presence); the AGC owns level. (Tyson, 2026-07-05.)
    corners = {k: [_words(bq) for bq in corner_bq[k]] for k in "ABCD"}
    return corners, voices


def to_bytes(corners):
    out = bytearray()
    for k in "ABCD":
        for s in range(6):
            for w in corners[k][s]:
                out += int(w).to_bytes(2, "little")
    return bytes(out)


def gate(body_bytes):
    try:
        if not evaluate_body(body_bytes, 5).get("stable", False):
            return False
    except Exception:
        return False
    cw = {k: [tuple(int(x) for x in np.frombuffer(body_bytes, "<u2").reshape(4, 6, 5)[ci, s])
              for s in range(6)] for ci, k in enumerate("ABCD")}
    b0, b1, b2, a1, a2 = pi.kernel_to_biquad(pi.packed_bilinear(cw, 0.0, 0.0)[5])
    return b0 != 0 and abs(b2 - b0) < 1e-9 * abs(b0)


def presence(corners):
    """A floor, not taste: the body must actually DO something across the morph
    (contrast + audible peak). Rejects stable-but-silent duds before the ear."""
    cw = {k: corners[k] for k in "ABCD"}
    for m in (0.0, 0.5, 1.0):
        r = resp(cw, m, 0.0)
        if (float(r.max()) - float(r.min())) >= 14.0 and float(r.max()) >= 4.0:
            return True
    return False


def resp(cw, m, q):
    rows = pi.packed_bilinear(cw, m, q)
    tot = np.zeros_like(FGRID)
    for row in rows:
        b0, b1, b2, a1, a2 = pi.kernel_to_biquad(row)
        tot += _mag_db([b0, b1, b2, a1, a2], FGRID)
    return tot


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
    src = source()
    nb = max(1, (len(src) + 511) // 512)
    mpb = np.linspace(0.0, 1.0, nb).tolist()
    try:
        out = trench_ffi.engine_render_automated(body_bytes, mpb, [0.0] * nb, src.tobytes(),
                                                 sr=SR, block=512, saturation_enabled=False)
    except Exception:
        out = trench_ffi.engine_render_automated(body_bytes, mpb, [0.0] * nb, src.tobytes(), sr=SR, block=512)
    y = np.frombuffer(out, dtype=np.float32).copy()
    y = y / (float(np.max(np.abs(y))) or 1.0) * 0.9
    m = int(len(y) * 48000 / SR)
    return np.interp(np.linspace(0, len(y) - 1, m), np.arange(len(y)), y).astype(np.float32)


def plot(kept, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ms = [(0.0, "#2f6fd0"), (0.25, "#6a5acd"), (0.5, "#8a5a9a"), (0.75, "#c0563e"), (1.0, "#d02f2f")]
    rows = (len(kept) + 1) // 2
    fig, axes = plt.subplots(rows, 2, figsize=(11, 1.5 * rows + 1), facecolor="white", squeeze=False)
    for i, (cw, voices) in enumerate(kept):
        ax = axes[i // 2][i % 2]
        for m, col in ms:
            ax.semilogx(FGRID, resp(cw, m, 0.0), color=col, lw=1.5)
        ax.set_xlim(40, 19500); ax.set_ylim(-30, 54)
        ax.grid(True, which="both", color="#ececec", lw=0.6)
        ax.set_xticks([100, 1000, 10000]); ax.set_xticklabels(["100", "1k", "10k"])
        letters = " ".join(v["name"][:4] for v in voices)
        ax.set_title(f"candidate {i}   [{letters}]", fontsize=8.5, loc="left")
    for j in range(len(kept), rows * 2):
        axes[j // 2][j % 2].axis("off")
    fig.suptitle("TRENCH FACTORY (voice-space) — dB vs log Hz, morph home(blue)->away(red)", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    fig.savefig(path, dpi=110, facecolor="white")
    import matplotlib.pyplot as plt2
    plt2.close(fig)


def main():
    import soundfile as sf
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    rng = np.random.default_rng(seed)
    shipped = trench_ffi.engine_available()
    kept, tried = [], 0
    while len(kept) < count and tried < count * 60:
        tried += 1
        corners, voices = compose(rng)
        b = to_bytes(corners)
        if len(b) == 240 and gate(b) and presence(corners):
            kept.append((corners, voices))
    cards = []
    for i, (corners, voices) in enumerate(kept):
        sf.write(os.path.join(OUT, f"cand_{i}.wav"), render(to_bytes(corners)), 48000)
        letters = " · ".join(v["name"] for v in voices)
        cards.append(f'<div class=c><b>candidate {i}</b><br><small>{letters}</small>'
                     f'<br><audio controls preload=none src="cand_{i}.wav"></audio></div>')
    plot(kept, os.path.join(OUT, "candidates_plot.png"))
    page = ("<!doctype html><meta charset=utf-8><title>factory voices</title>"
            "<style>body{background:#0a0c0b;color:#cfe9df;font:14px monospace;margin:24px;max-width:560px}"
            "h2{color:#e0a856}.c{margin:10px 0;padding:8px;background:#14181a;border-radius:6px}"
            "audio{width:100%;margin-top:4px}small{color:#8a968f}</style>"
            "<h2>TRENCH FACTORY — voice-space bodies</h2>"
            f"<small>{'SHIPPED engine, pink, AGC only, straight A->B' if shipped else 'FALLBACK'}. "
            f"{len(kept)}/{tried} passed the floor. See candidates_plot.png for the curves.</small>"
            + "".join(cards))
    open(os.path.join(OUT, "audition.html"), "w", encoding="utf-8").write(page)
    print(f"kept {len(kept)}/{tried} (engine {'SHIPPED' if shipped else 'FALLBACK'})")
    print("plot:", os.path.abspath(os.path.join(OUT, "candidates_plot.png")))


if __name__ == "__main__":
    main()
