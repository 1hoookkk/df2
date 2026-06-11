"""Bulk-generate 4-corner bodies, SCORE each against the real 50 P2K types, gate,
rank, and render auditions. Scoring is the engine: objective + gates calibrated to
ref/p2k reference_aggregate (the 50's measured distribution). The ear picks the top.

  python tools/forge_generate_corners.py [N]
Outputs dev/tmp/forge_corners/<run>/: top bodies (.body240), auditions (.wav),
scores.json, audition.html.
"""
import sys, json, math, random, datetime
from pathlib import Path
ROOT = Path(r"C:\Users\hooki\df2"); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import numpy as np
from scipy.io import wavfile
from scipy.signal import find_peaks
import forge_author_server as S          # parity-proven pack + audit
from pyruntime import trench_ffi as t
from src.utils.packed_runtime import evaluate_body   # the REAL scorer (metrics comparable to the 50)
SR = 39062.5; TAU = 2 * math.pi
clampHz = lambda f: max(40.0, min(SR * 0.47, f))

# ---- reference: the 50 P2K types (beat their distribution) ----
REF = json.loads((ROOT / "dev/tmp/production_authoring/extreme_qd_v1_final/reference_aggregate.json").read_text())
FREQS = np.geomspace(60, 16000, 160)

def load_js(path, var):
    txt = (ROOT / path).read_text(encoding="utf-8")
    return json.loads(txt[txt.index("["):txt.rindex("]") + 1])
SOURCES = load_js("forge-web/data/sources.js", "SOURCES")
FRAMES = load_js("forge-web/data/frames.js", "FRAMES")   # vowel triangle + p2k rails (A/B endpoints)

def L(role, pf, pfB, pr, prHi, g, zah, zad, zbh, zbd):
    return dict(role=role, on=True, pf=clampHz(pf), pfB=clampHz(pfB), pr=pr, prHi=prHi, gain=g,
                zA=dict(hz=clampHz(zah), depth=zad, on=zad > 0.02), zB=dict(hz=clampHz(zbh), depth=zbd, on=zbd > 0.02))

F_MULT = [1.0, 1.9, 3.6]
def dcpin(pf, r):                                  # gain that pins this all-pole section to 0 dB at DC
    th = TAU * clampHz(pf) / SR
    return max(0.03, min(4.0, (1 - 2 * r * math.cos(th) + r * r) / max(1e-4, 1 - r * r)))
def build_lanes(src, rng):
    secs = src["sections"]
    found = [s for s in secs if "foundation" in s.get("role", "")]
    actors = [s for s in secs if "foundation" not in s.get("role", "")]
    anchor = rng.choice([98, 194, 270, 390, 530])
    lanes = []
    if found:
        for i, s in enumerate(found):
            pf = anchor * F_MULT[min(i, 2)]; pr = 0.78 + 0.03 * i
            lanes.append(L("foundation", pf, pf, pr, min(0.90, pr + 0.03), dcpin(pf, pr), pf * 6, 0, pf * 6, 0))
    else:
        lanes.append(L("foundation sub", anchor, anchor, 0.80, 0.83, dcpin(anchor, 0.80), anchor * 6, 0, anchor * 6, 0))
    nA = 6 - len(lanes)
    for j, s in enumerate(actors[:nA]):
        pf = s["pf"]; away = clampHz(pf * rng.uniform(1.5, 3.0)); tear = (j == nA - 1)
        pr = rng.uniform(0.80, 0.88)
        prHi = rng.uniform(0.9985, 0.9992) if tear else rng.uniform(0.988, 0.994)
        lanes.append(L("tear" if tear else "actor", pf, away, pr, prHi, dcpin(pf, pr) * (1.6 if tear else 1.0),
                       pf * rng.uniform(1.4, 1.9), rng.uniform(0.30, 0.60), pf * rng.uniform(0.5, 0.7), rng.uniform(0.35, 0.62)))
    while len(lanes) < 6:
        lanes.append(L("actor", 1500, 2500, 0.82, 0.99, dcpin(1500, 0.82), 2400, 0.4, 1000, 0.5))
    return lanes[:6]

def build_vowel_lanes(fa, fb, rng):
    """Frame A -> Frame B vowel morph: 3 held foundation + 3 formant actors whose
    poles glide A->B and carry anti-formant zeros (valleys + zero motion)."""
    anchor = rng.choice([98, 194, 270, 390, 530])
    lanes = []
    for i in range(3):
        pf = anchor * F_MULT[i]; pr = 0.78 + 0.03 * i
        lanes.append(L("foundation", pf, pf, pr, min(0.90, pr + 0.03), dcpin(pf, pr), pf * 6, 0, pf * 6, 0))
    fA = sorted([fa["f1"], fa["f2"], fa["f3"]]); fB = sorted([fb["f1"], fb["f2"], fb["f3"]])
    gapA = [math.sqrt(fA[0] * fA[1]), math.sqrt(fA[1] * fA[2]), fA[2] * 1.7]   # notches BETWEEN/above formants = valleys
    gapB = [math.sqrt(fB[0] * fB[1]), math.sqrt(fB[1] * fB[2]), fB[2] * 1.7]
    for k in range(3):
        pf, away = fA[k], fB[k]; pr = rng.uniform(0.90, 0.94)             # resonant enough to peak at mid-Q
        prHi = rng.uniform(0.991, 0.997) if k == 2 else rng.uniform(0.989, 0.995)
        lanes.append(L("formant", pf, away, pr, prHi, dcpin(pf, pr),
                       clampHz(gapA[k]), rng.uniform(0.84, 0.95), clampHz(gapB[k]), rng.uniform(0.84, 0.95)))  # deep canyons
    return lanes[:6]

def resp(body, m, q):
    pr = t.packed_probe(body, m, q); out = np.empty(len(FREQS))
    for k, f in enumerate(FREQS):
        s = 0.0
        for b0, b1, b2, a1, a2 in pr["biquad"]:
            w = TAU * f / SR; c, sn, c2, s2 = math.cos(w), math.sin(w), math.cos(2 * w), math.sin(2 * w)
            nr, ni = b0 + b1 * c + b2 * c2, -(b1 * sn + b2 * s2); dr, di = 1 + a1 * c + a2 * c2, -(a1 * sn + a2 * s2)
            s += 20 * math.log10(max(1e-12, math.hypot(nr, ni) / max(1e-12, math.hypot(dr, di))))
        out[k] = s
    return out
rms = lambda x: float(np.sqrt(np.mean(x * x)))

def score(body):
    m = evaluate_body(body, 9)                       # the REAL production scorer (metrics match the 50's reference)
    passed = (m["stable"] and m["finite"] and not m["grid_unstable_rows"] and not m["interior_unstable_rows"]
              and 0.998 <= m["max_pole_radius"] < 0.9999
              and m["center_span_db"] > 74 and m["endpoint_span_db_mean"] > 0.95 * REF["median_endpoint_span_db"]
              and m["morph_contrast_rms_db"] > 0.95 * REF["median_morph_contrast_db"]
              and m["secondary_contrast_rms_db"] > 0.95 * REF["median_secondary_contrast_db"]
              and m["center_response_peaks"] >= 3 and m["center_response_valleys"] >= 3
              and m["median_zero_motion_octaves"] > 0.35)
    return dict(obj=round(m["objective"], 1), morph=round(m["morph_contrast_rms_db"], 1),
                sec=round(m["secondary_contrast_rms_db"], 1), center=round(m["center_span_db"], 1),
                endpoint=round(m["endpoint_span_db_mean"], 1), peaks=int(m["center_response_peaks"]),
                valleys=int(m["center_response_valleys"]), maxr=round(m["max_pole_radius"], 4),
                zmot=round(m["median_zero_motion_octaves"], 2), passed=bool(passed))

# ---- generate + score against the 50 ----
N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
random.seed(7); rng = random
cands = []
for i in range(N):
    if FRAMES and rng.random() < 0.65:                 # vowel A->B morph (complexity: peaks+valleys+zero motion)
        fa, fb = rng.choice(FRAMES), rng.choice(FRAMES)
        if fa is fb: continue
        lanes = build_vowel_lanes(fa, fb, rng); srcname = f"{fa['label']} -> {fb['label']}"
    else:
        src = rng.choice(SOURCES); lanes = build_lanes(src, rng); srcname = src["name"]
    body, _ = S.pack(lanes)
    try: sc = score(body)
    except Exception: continue
    cands.append(dict(src=srcname, body=body, sc=sc))
cands.sort(key=lambda c: (-int(c["sc"]["passed"]), -c["sc"]["obj"]))
npass = sum(c["sc"]["passed"] for c in cands)
print(f"{N} generated, {npass} pass the 50-type gates (ranked by objective)")
print(f"{'#':>3} {'pass':>4} {'obj':>6} {'morph':>6} {'Q':>5} {'center':>7} {'maxr':>7} {'pk/vl':>6} src")
for r, c in enumerate(cands[:12]):
    s = c["sc"]; print(f"{r+1:>3} {('Y' if s['passed'] else '.'):>4} {s['obj']:>6} {s['morph']:>6} {s['sec']:>5} {s['center']:>7} {s['maxr']:>7} {str(s['peaks'])+'/'+str(s['valleys']):>6} {c['src']}")

# ---- THE PLOTS: ranked contact sheet (4 corners each) ----
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
out = ROOT / f"dev/tmp/forge_corners/run_{stamp}"; out.mkdir(parents=True, exist_ok=True)
top = cands[:12]
fig, axes = plt.subplots(3, 4, figsize=(16, 9), facecolor="#0a0c0b")
for ax, c in zip(np.array(axes).ravel(), top):
    for m, q, col in ((0, 0, "#5ba35a"), (1, 0, "#e09a2e"), (0, 1, "#7aa7ff"), (1, 1, "#e8533a")):
        ax.semilogx(FREQS, resp(c["body"], m, q), lw=1.1, color=col)
    s = c["sc"]; ec = "#2ec16b" if s["passed"] else "#444b57"
    ax.set_xlim(60, 16000); ax.set_xticks([]); ax.set_yticks([]); ax.set_facecolor("#0c0f0e")
    for sp in ax.spines.values(): sp.set_color(ec); sp.set_linewidth(2 if s["passed"] else 1)
    ax.set_title(f"{'PASS · ' if s['passed'] else ''}obj {int(s['obj'])} · M{s['morph']} Q{s['sec']} · r{s['maxr']} · {s['peaks']}/{s['valleys']}",
                 color="#cfe9df", fontsize=8)
    ax.text(0.02, 0.05, c["src"], transform=ax.transAxes, color="#697384", fontsize=7)
for ax in np.array(axes).ravel()[len(top):]: ax.axis("off")
fig.suptitle(f"forge corners ranked vs the 50  —  {npass}/{N} pass  (green = pass)  ·  A.broad  B.broad  A.sharp  B.sharp",
             color="#9fe7c6", fontsize=12)
fig.tight_layout(); sheet = out / "ranked_corners.png"; fig.savefig(str(sheet), dpi=110, facecolor="#0a0c0b"); plt.close(fig)

# ---- audition top 4 (saw, bar-synced morph loop, Q rising) ----
n = int(4 * (60 / 150) * 4 * SR)
saw = ((2 * (np.mod(np.cumsum(np.full(n, 55.0)) / SR, 1)) - 1) * 0.5).astype("<f4").tobytes()
blk = 512; nb = (n + blk - 1) // blk; prog = np.arange(nb) / max(1, nb - 1)
for r, c in enumerate(top[:4]):
    nm = f"corner_{r+1:02d}_obj{int(c['sc']['obj'])}"
    (out / f"{nm}.body240").write_bytes(c["body"])
    wet = t.engine_render_slam(c["body"], list(prog), list(0.25 + 0.7 * prog), saw, slam_drive=0.45, five_d=0.25, sr=SR, block=blk)
    y = np.frombuffer(wet, dtype="<f4").astype(np.float64); pk = np.max(np.abs(y)) or 1
    wavfile.write(str(out / f"{nm}.wav"), int(round(SR)), np.int16(np.clip(y / pk * 0.97, -1, 1) * 32767))
(out / "scores.json").write_text(json.dumps([{**c["sc"], "src": c["src"]} for c in cands], indent=2))
print(f"\nPLOTS -> {sheet}")
