"""Author the Journey — the canonical TRENCH authoring primitive.

A body = a few VOICE LINES. Each voice is one formant/peak that travels from a
HOME frequency to an AWAY frequency across the Morph. You author the lines; the
DSP (radius by dB-height, soft inside-circle zeros, registration) is handled here.

Two laws (see memory canonical-preset-authoring):
  * REGISTRATION — each voice keeps its stage slot in both corners, so the morph
    SLIDES it smoothly (a real intermediate) instead of jumping.
  * SIMPLICITY — <=6 voices, one pole each, no competing poles in a band.

Q axis = the resonance dial (Q0 = the body's natural voice, Q100 = cranked).

Usage:
    from tools.author_journey import Voice, author
    author("oo_to_ee", [
        Voice("body", 190, 190, height_db=22),
        Voice("F1",    300, 270, height_db=30),
        Voice("F2",    870, 2290, height_db=36),   # the defining sweep
        Voice("F3",   2240, 3010, height_db=32),
    ], q_crank_db=10)
-> writes <out>/<name>.body240 + <name>.cart.json, returns the 240 bytes.
"""
from __future__ import annotations
import math, struct, json, os
from dataclasses import dataclass

from tools.corner_words import notch, pas, corner_words, CORNER_LABELS

AUTH_SR = 39062.5
RMAX = 0.9965

def _r_from_db(height_db: float) -> float:
    """Pole radius from a target resonant-peak height in dB (the perceptual/log
    placement: h ~ 20*log10(1/(1-r))). 26dB->0.95, 34dB->0.98, 40dB->0.99."""
    return min(1.0 - 10.0 ** (-max(height_db, 1.0) / 20.0), RMAX)

@dataclass
class Voice:
    name: str
    home_hz: float
    away_hz: float
    height_db: float = 32.0      # resonance height (pole radius, log domain)
    zero_db: float = 12.0        # paired-notch depth (soft, inside-circle zero)
    zero_below_semis: float = 6.0  # zero sits this far below its pole

def _stage(freq: float, height_db: float, zero_db: float, zsemis: float):
    r = _r_from_db(height_db)
    zf = freq * (2.0 ** (-zsemis / 12.0))
    zr = _r_from_db(zero_db)                 # zero INSIDE the circle (soft dip), not on it
    return notch(freq, r, -0.05, zf, zr)

def _corner(voices, side: str, q01: float, q_crank_db: float):
    """side in {'home','away'}; q01 in {0,1}. Q lerps pole height by q_crank_db."""
    stages = []
    for v in voices:
        f = v.home_hz if side == "home" else v.away_hz
        h = v.height_db + q_crank_db * q01          # Q = resonance dial
        stages.append(_stage(f, h, v.zero_db, v.zero_below_semis))
    while len(stages) < 6:
        stages.append(pas())
    return stages[:6]

def build_bytes(voices, q_crank_db: float = 10.0) -> bytes:
    if len(voices) > 6:
        raise ValueError("max 6 voices (one pole per stage)")
    corners = {
        "M0_Q0":     _corner(voices, "home", 0.0, q_crank_db),
        "M100_Q0":   _corner(voices, "away", 0.0, q_crank_db),
        "M0_Q100":   _corner(voices, "home", 1.0, q_crank_db),
        "M100_Q100": _corner(voices, "away", 1.0, q_crank_db),
    }
    raw = bytearray()
    for label in CORNER_LABELS:
        for st in corner_words(corners[label]):
            raw += struct.pack("<5H", *[int(w) & 0xFFFF for w in st])
    assert len(raw) == 240
    return bytes(raw)

def to_cartridge(name: str, body240: bytes, boost: float = 1.0) -> dict:
    kf = []
    for ci, label in enumerate(CORNER_LABELS):
        words = []
        for s in range(6):
            off = (ci * 6 + s) * 10
            words.append(list(struct.unpack_from("<5H", body240, off)))
        m = 0.0 if "M0" in label else 1.0
        q = 0.0 if "Q0" in label else 1.0
        kf.append({"label": label, "morph": m, "q": q, "boost": boost, "packedWords": words})
    return {"format": "compiled-v1", "name": name, "sampleRate": AUTH_SR,
            "authoring_sample_rate_hz": AUTH_SR, "stages": 6,
            "cornerOrder": list(CORNER_LABELS), "keyframes": kf}

def author(name: str, voices, q_crank_db: float = 10.0, boost: float = 1.0,
           out_dir: str = "dev/tmp/journeys") -> bytes:
    os.makedirs(out_dir, exist_ok=True)
    b = build_bytes(voices, q_crank_db)
    open(os.path.join(out_dir, f"{name}.body240"), "wb").write(b)
    json.dump(to_cartridge(name, b, boost),
              open(os.path.join(out_dir, f"{name}.cart.json"), "w"), indent=1)
    return b


if __name__ == "__main__":
    # Proof: oo -> ee, end to end (body + journey plot + audio).
    import numpy as np, wave
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    from pyruntime import trench_ffi

    voices = [Voice("body", 190, 190, 22), Voice("F1", 300, 270, 30),
              Voice("F2", 870, 2290, 36), Voice("F3", 2240, 3010, 32)]
    b = author("oo_to_ee", voices, q_crank_db=10)
    OUT = "dev/tmp/journeys"

    def pole_freqs(bb, m, q):
        out = []
        for c0, c1, c2, c3, c4 in trench_ffi.packed_interpolate(bb, m, q):
            a1, a2 = c2 - 2.0, 1.0 - c3
            if a2 > 0 and abs(a1) <= 2 * math.sqrt(a2):
                r = math.sqrt(a2); f = math.acos(max(-1, min(1, -a1 / (2 * r)))) * AUTH_SR / (2 * math.pi)
                if 30 < f < 19000: out.append(f)
        return sorted(out)

    ms = np.linspace(0, 1, 21)
    plt.style.use("dark_background"); fig, ax = plt.subplots(figsize=(8, 6))
    ax.set_facecolor("#050505"); ax.set_yscale("log"); ax.set_ylim(120, 6000); ax.set_xlim(0, 1)
    ax.grid(True, which="both", color="#1a2030", lw=0.4); ax.tick_params(colors="#5a605c")
    tracks = {}
    for m in ms:
        for i, f in enumerate(pole_freqs(b, m, 0.0)): tracks.setdefault(i, []).append((m, f))
    for pts in tracks.values():
        ax.plot([p[0] for p in pts], [p[1] for p in pts], "o-", color="#ffa838", ms=3, lw=1.5)
    ax.set_title("author_journey oo->ee — every voice sliding (registered)", color="#9aa096")
    ax.set_xlabel("Morph", color="#5a605c"); ax.set_ylabel("voice freq (Hz, log)", color="#5a605c")
    fig.tight_layout(); fig.savefig(f"{OUT}/oo_to_ee_journey.png", dpi=120, facecolor="#0a0a0c")

    def saw(s, f0=73):
        n = int(s * AUTH_SR); t = np.arange(n) / AUTH_SR
        x = sum(np.sin(2 * np.pi * f0 * h * t) / h for h in range(1, 40)); x *= 0.25 / np.max(np.abs(x))
        return x.astype("<f4").tobytes()
    src = saw(2.5); nb = max(1, (len(src) // 4) // 512)
    audio = trench_ffi.engine_render_automated(b, list(np.linspace(0, 1, nb)), [0.3] * nb, src)
    x = np.clip(np.frombuffer(audio, dtype="<f4"), -1, 1)
    with wave.open(f"{OUT}/oo_to_ee_journey.wav", "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(int(AUTH_SR))
        w.writeframes((x * 32767).astype("<i2").tobytes())
    print("voices @ M0/M50/M1:")
    for m in (0, 0.5, 1.0): print(f"  M{m}: {[round(f) for f in pole_freqs(b, m, 0)]}")
    print(f"WROTE {OUT}/oo_to_ee.body240 + journey.png + journey.wav")
