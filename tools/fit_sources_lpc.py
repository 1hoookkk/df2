"""Source fitter (tracked, promoted from dev/tmp): LPC order-12 on REAL audio ->
12 poles = 6 conjugate pairs, every section a real resonance, no filler/waste.
LSF computed for stability/ordering proof. Writes forge-web/data/sources.js.

"The biggest gap is waste poles and zeros" — so this fits all 12 and flags any
degenerate (near-DC / near-Nyquist / low-radius) pole as waste instead of shipping it.
"""
import sys, json, math
from pathlib import Path
ROOT = Path(r"C:\Users\hooki\df2"); sys.path.insert(0, str(ROOT))
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SR = 39062.5
PACK = ROOT / "dev/tmp/arma_source_pack"
CONET = PACK / "wav/conet_5_dashes.wav"

def levinson(r, order):
    a = np.zeros(order + 1); a[0] = 1.0; e = r[0]
    for i in range(1, order + 1):
        acc = r[i] + sum(a[j] * r[i - j] for j in range(1, i))
        if e <= 0: break
        k = -acc / e; an = a.copy()
        for j in range(1, i): an[j] = a[j] + k * a[i - j]
        an[i] = k; a = an; e *= (1 - k * k)
    return a

def lpc(x, order=12, preemph=0.97):
    x = x - np.mean(x)
    pe = max(0.0, min(0.999, preemph))
    x = np.append(x[0], x[1:] - pe * x[:-1]) * np.hanning(len(x))   # pre-emphasis flattens tilt -> poles land on resonances
    r = np.correlate(x, x, "full")[len(x) - 1:][:order + 1]
    if r[0] <= 0: return None
    return levinson(r, order)

def lsf(a):
    """line spectral frequencies — must be strictly increasing in (0,pi) for a stable, well-spread fit."""
    p = len(a) - 1
    A = np.r_[a, 0.0]; B = A[::-1]
    P, Q = A + B, A - B
    ang = lambda poly: sorted(abs(np.angle(z)) for z in np.roots(poly) if z.imag >= -1e-9)
    w = sorted(v for v in (ang(P) + ang(Q)) if 1e-3 < v < math.pi - 1e-3)
    return w

def poles_from_lpc(a):
    pr = [(abs(z), abs(np.angle(z))) for z in np.roots(a) if z.imag > 1e-6]
    pr.sort(key=lambda t: t[1])                      # by frequency, low -> high
    return pr

def crank_radius(r, k):
    """k in [0,1]: push a pole toward the rim for sharper resonance. k=0 = as measured."""
    k = max(0.0, min(1.0, k))
    return max(0.55, min(0.9992, 1.0 - (1.0 - r) * (1.0 - 0.78 * k)))

def lsf_radius(f_hz, ls, fallback_r):
    """Q from adjacent LSF pair spacing — a tight pair = a sharp resonance (r -> 1)."""
    if not ls: return fallback_r
    w = 2 * math.pi * f_hz / SR
    below = [v for v in ls if v <= w]; above = [v for v in ls if v >= w]
    if below and above:
        spacing = max(1e-4, above[0] - below[-1])     # radians between the bracketing pair
        bw = spacing * SR / (2 * math.pi)
        return max(0.55, min(0.9992, math.exp(-math.pi * bw / SR)))
    return fallback_r

RAILS = [98, 194, 270, 390, 530]                     # measured foundation anchors (clean-room)
FOUND = max(0, min(5, int(sys.argv[1]) if len(sys.argv) > 1 else 3))   # default foundation sections; 0 = all 12 to source
F_MULT = [1.0, 1.9, 3.6, 6.0, 9.5]; F_R = [0.80, 0.84, 0.80, 0.76, 0.72]
F_G = [1.1, 1.0, 0.9, 0.85, 0.8]; F_NAME = ["sub", "body", "cap", "upper", "top"]
def snap_anchor(f):
    f = max(60.0, min(530.0, f))
    return min(RAILS, key=lambda r: abs(math.log2(r / f)))

def fit(clip, sr_in, name, group, found=None, preemph=0.97, crank=0.0, qsource="lpc"):
    """`found` sections to a measured-rail foundation + (6-found) sections of LPC source
    = 12 poles, no filler. Split is the knob: more `found` = heavier body.
    preemph = spectral tilt of the fit; crank = push source poles toward the rim;
    qsource = 'lpc' (root radius) or 'lsp' (radius from LSF pair-spacing)."""
    found = FOUND if found is None else max(0, min(5, int(found)))
    if sr_in != SR: clip = resample_poly(clip, int(SR), int(sr_in))
    n_src = 6 - found
    a = lpc(clip, 2 * n_src, preemph) if n_src > 0 else None
    ls = lsf(a) if a is not None else []
    waste = 0; char = []
    for (r, ang) in (poles_from_lpc(a)[:n_src] if a is not None else []):
        f = ang * SR / (2 * math.pi)
        r_use = lsf_radius(f, ls, r) if qsource == "lsp" else r
        r_use = crank_radius(r_use, crank)
        if r < 0.55 or f < 80 or f > SR * 0.47: waste += 1
        char.append(dict(on=1, role="source actor", pf=round(max(80.0, min(SR * 0.47, f)), 1),
                         pr=round(max(0.55, min(0.9992, r_use)), 4), g=1.0))
    while len(char) < n_src:                          # LPC gave too few pairs -> flagged waste
        waste += 1; char.append(dict(on=1, role="source actor", pf=1200.0 * (len(char) + 1), pr=0.7, g=1.0))
    anchor = snap_anchor(min((char[0]["pf"] * 0.4) if char else 194.0, 270.0))   # body sits LOW, under the source
    found_secs = [dict(on=1, role=f"foundation {F_NAME[i]}", pf=round(anchor * F_MULT[i], 1),
                  pr=F_R[i], g=F_G[i]) for i in range(found)]
    secs = found_secs + char                          # body first, then source
    stable = (n_src == 0) or (len(ls) >= 2 * n_src - 1 and all(ls[i] < ls[i + 1] for i in range(len(ls) - 1)))
    return dict(name=name, group=group, sections=secs, waste=waste, lsf_stable=bool(stable), anchor=anchor,
                poles=" ".join(f"{s['pf']:.0f}@{s['pr']:.3f}" for s in secs))

def load(path):
    sr, x = wavfile.read(str(path)); x = x.astype(np.float64)
    if x.ndim > 1: x = x.mean(axis=1)
    return sr, x / (np.max(np.abs(x)) or 1)

# real vowel audio (conet number-station voice) at the steady nuclei found earlier
CONET_VOWELS = [("vowel oo", 181.1), ("vowel ah", 180.5), ("vowel uh", 11.2), ("vowel er", 146.2),
                ("vowel eh", 79.0), ("vowel ih", 99.4), ("vowel ae", 119.2), ("vowel ee", 206.1)]
ARMA = [("tunnel", "wav/openair_innocent_railway_tunnel_entrance.wav", 2.0),
        ("reactor hall", "wav/openair_r1_nuclear_reactor_hall_r1_omni_48k.wav", 3.0),
        ("vlf whistler", "wav/inspire_7purewhist.wav", 2.0)]

def main():
    sources = []
    print(f"{'source':16} {'waste':>5} {'lsf':>6}  poles (Hz@radius)")
    sr, cx = load(CONET)
    for name, at in CONET_VOWELS:
        s0 = int(at * sr); clip = cx[s0:s0 + int(0.14 * sr)]
        f = fit(clip, sr, name, "vowel (lpc12)")
        if f: sources.append(f); print(f"{name:16} {f['waste']:>5} {('ok' if f['lsf_stable'] else 'BAD'):>6}  {f['poles']}")
    for name, rel, at in ARMA:
        p = PACK / rel
        if not p.exists(): continue
        sr2, ax = load(p); s0 = int(at * sr2); clip = ax[s0:s0 + int(0.30 * sr2)]
        f = fit(clip, sr2, name, "captured (lpc12)")
        if f: sources.append(f); print(f"{name:16} {f['waste']:>5} {('ok' if f['lsf_stable'] else 'BAD'):>6}  {f['poles']}")

    clean = [s for s in sources if s["waste"] == 0]
    print(f"\n{len(sources)} sources fit; {len(clean)} with zero waste poles")
    out = [{k: s[k] for k in ("name", "group", "sections")} for s in sources]
    (ROOT / "forge-web/data/sources.js").write_text(
        "// LPC(12) real-audio fits — 12 poles each, no filler. tools/fit_sources_lpc.py\n"
        "window.SOURCES = " + json.dumps(out, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"exported {len(out)} sources -> forge-web/data/sources.js")

if __name__ == "__main__":
    main()
