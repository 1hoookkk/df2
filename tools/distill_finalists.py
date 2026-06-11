#!/usr/bin/env python3
"""distill_finalists — turn a big QD archive into the N bodies that STAND.

"Out of 100k results, only 20 stand." NOT top-N-by-score (you'd get N identical
screamers) and NOT diversity on raw dB curves (amplitude-biased — the violent
bodies dominate and the subtle talkers never get picked). Instead: FARTHEST-POINT
diversity on the STANDARDISED metric vector (maxR, span, morph, secondary, peaks,
valleys, zero-motion — each z-scored so every axis counts equally), anchored on
the strongest body, with a per-specialist cap so no single type floods the set.
This makes maxR .987 (talker) vs .9996 (screamer) a real separating axis, so the
20 span the whole range: talkers, movers, bass, screamers.

Regenerates each cell's body from its genome, writes body240 + cart.json + an
808-through-the-engine clip + a one-page audition. The EAR picks the keepers.

    python tools/distill_finalists.py <run_dir> [N=20] [cap=3]
"""
from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pyruntime import trench_ffi
from src.architectures.trajectory_program import ProgramGenome, StageTrajectory
from src.utils.body240 import compiled_payload, raw_from_words, words_from_kernels

SR_RESP = 39062.5
RESP_FREQS = np.geomspace(40.0, 18000.0, 64)
SR_AUDIO = 44100
POSITIONS = [("HOME", 0.0, 0.0), ("MORPH", 1.0, 0.0), ("TENSION", 0.0, 1.0),
             ("MORPH+TENSION", 1.0, 1.0), ("MIDDLE", 0.5, 0.5)]
CORNER_COLS = {"HOME": "#2ec4ff", "MORPH": "#ffd23e", "TENSION": "#ff6b6b", "MORPH+TENSION": "#9b8cff"}
# the axes that distinguish a talker from a screamer from a bass body
METRIC_KEYS = ["max_pole_radius", "endpoint_span_db_mean", "morph_contrast_rms_db",
               "secondary_contrast_rms_db", "center_response_peaks",
               "center_response_valleys", "median_zero_motion_octaves"]


def genome_from_dict(d) -> ProgramGenome:
    stages = tuple(StageTrajectory(**s) for s in d["stages"])
    return ProgramGenome(family=d["family"], seed=int(d["seed"]),
                         stages=stages, specialist=d.get("specialist"))


def body_of(cell) -> bytes:
    return raw_from_words(words_from_kernels(genome_from_dict(cell["genome"]).corner_kernels()))


def metric_vec(m) -> np.ndarray:
    return np.array([float(m.get(k, 0.0)) for k in METRIC_KEYS], dtype=np.float64)


def corner_db(body: bytes, m: float, q: float) -> np.ndarray:
    pr = trench_ffi.packed_probe(body, float(m), float(q))
    w = 2.0 * np.pi * RESP_FREQS / SR_RESP
    z1 = np.exp(-1j * w); z2 = z1 * z1
    h = np.ones_like(z1)
    for (b0, b1, b2, a1, a2) in pr["biquad"]:
        h = h * (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.abs(h) + 1e-12)


def synth_noise(dur: float = 3.6, seed: int = 0) -> np.ndarray:
    """White noise — broadband excitation so the swept resonance rings out clearly."""
    n = int(SR_AUDIO * dur); t = np.arange(n) / SR_AUDIO
    x = np.random.default_rng(seed).standard_normal(n)
    env = np.minimum(1.0, t / 0.04) * np.minimum(1.0, (dur - t) / 0.12)
    return (0.5 * x * env).astype(np.float64)


def render_sweep(body: bytes, src: np.ndarray) -> np.ndarray:
    """Continuous Morph sweep 0->1->0 through the shipped engine (Q held) — the
    gesture: you hear the peak GLIDE between its two landing notes, not a held ring."""
    n = len(src); nb = max(1, (n + 511) // 512); half = nb // 2
    morph = np.concatenate([np.linspace(0.0, 1.0, half), np.linspace(1.0, 0.0, nb - half)])
    q = np.full(nb, 0.70)
    raw = trench_ffi.engine_render_automated(
        body, morph.tolist(), q.tolist(), src.astype(np.float32).tobytes(), SR_AUDIO, block=512,
        agc_enabled=True, spatial_mode=2, saturation_enabled=True)   # AGC + Mackie, QSound OFF (2=Off)
    y = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    pk = float(np.max(np.abs(y)))
    if pk > 1e-9:
        y = y / pk * 0.9
    return y


def write_wav(path: Path, x: np.ndarray) -> None:
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR_AUDIO); w.writeframes(pcm.tobytes())


def plot_body(curves: dict[str, np.ndarray], path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(4.2, 2.0), facecolor="#0a0c0b")
    for name, col in CORNER_COLS.items():
        y = curves[name]; ax.semilogx(RESP_FREQS, y - float(np.max(y)), color=col, lw=1.2)
    ax.set_xlim(40, 18000); ax.set_ylim(-60, 4); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#1c2722")
    ax.set_title(title, color="#8aa", fontsize=7)
    fig.tight_layout(pad=0.2); fig.savefig(str(path), dpi=110, facecolor="#0a0c0b"); plt.close(fig)


def farthest_point(z: np.ndarray, specialists: list[str], objs: np.ndarray, n: int, cap: int) -> list[int]:
    """Anchor on the strongest body, then greedily add the body maximising the
    minimum z-space distance to the chosen set, never exceeding `cap` per specialist."""
    start = int(np.argmax(objs))
    chosen = [start]; counts = {specialists[start]: 1}
    mind = np.linalg.norm(z - z[start], axis=1); mind[start] = -1.0
    while len(chosen) < min(n, len(z)):
        j = int(np.argmax(mind))
        if mind[j] < 0:
            break
        sp = specialists[j]
        if counts.get(sp, 0) >= cap:
            mind[j] = -1.0
            continue
        chosen.append(j); counts[sp] = counts.get(sp, 0) + 1
        mind = np.minimum(mind, np.linalg.norm(z - z[j], axis=1)); mind[j] = -1.0
    return chosen


def main(run_arg: str, n: int, cap: int) -> int:
    run = Path(run_arg).resolve()
    cells = json.loads((run / "archive_checkpoint.json").read_text())["cells"]
    print(f"loaded {len(cells)} archive cells from {run.name}")

    items = []  # (body, cell)
    mvecs, objs = [], []
    for cell in cells:
        try:
            body = body_of(cell)
        except Exception:  # noqa: BLE001
            continue
        items.append((body, cell))
        mvecs.append(metric_vec(cell["metrics"]))
        objs.append(float(cell["metrics"].get("objective", 0.0)))
    mvecs = np.asarray(mvecs); objs = np.asarray(objs)
    z = (mvecs - mvecs.mean(0)) / (mvecs.std(0) + 1e-9)            # equal weight per axis
    specialists = [c["genome"]["specialist"] for _, c in items]
    print(f"regenerated {len(items)} bodies; farthest-point on z-scored metrics, cap {cap}/specialist")

    picks = farthest_point(z, specialists, objs, n, cap)

    out = run / f"finalists_{n}"
    out.mkdir(parents=True, exist_ok=True)
    src = synth_noise()
    rows = []
    for rank, idx in enumerate(picks, 1):
        body, cell = items[idx]
        slug = f"stands_{rank:02d}_{cell['genome']['specialist']}"
        words = words_from_kernels(genome_from_dict(cell["genome"]).corner_kernels())
        (out / f"{slug}.body240").write_bytes(body)
        (out / f"{slug}.cart.json").write_text(json.dumps(compiled_payload(slug, 1.0, words), indent=2))
        write_wav(out / f"{slug}.wav", render_sweep(body, src))
        curves = {name: corner_db(body, m, q) for name, m, q in POSITIONS}
        m = cell["metrics"]
        plot_body(curves, out / f"{slug}.png",
                  f"{slug}  span{m.get('endpoint_span_db_mean',0):.0f} "
                  f"morph{m.get('morph_contrast_rms_db',0):.0f} maxR{m.get('max_pole_radius',0):.4f}")
        rows.append((rank, slug, m))
        print(f"  #{rank:02d} {slug:<38} obj={objs[idx]:6.1f} "
              f"span={m.get('endpoint_span_db_mean',0):3.0f} morph={m.get('morph_contrast_rms_db',0):3.0f} "
              f"sec={m.get('secondary_contrast_rms_db',0):4.1f} maxR={m.get('max_pole_radius',0):.4f}")

    cards = []
    for rank, slug, m in rows:
        maxr = float(m.get("max_pole_radius", 0.0)); sec = float(m.get("secondary_contrast_rms_db", 0.0))
        tag, col = ("TALKER", "#5bef6f") if maxr < 0.99 else (("SCREAMER", "#e8533a") if sec >= 28 else ("MOVER", "#ffd23e"))
        cards.append(
            f'<div class=row><div class=hd><span class=rk>#{rank:02d}</span>'
            f'<span class=nm>{slug}</span><span class=tag style="color:{col};border-color:{col}">{tag}</span></div>'
            f'<div class=met>span <b>{m.get("endpoint_span_db_mean",0):.0f}</b>dB · morph <b>{m.get("morph_contrast_rms_db",0):.0f}</b>dB · '
            f'secondary <b>{sec:.1f}</b>dB · maxR <b>{maxr:.4f}</b></div>'
            f'<div class=body><audio controls preload=none src="{slug}.wav"></audio>'
            f'<a href="{slug}.png" target=_blank><img class=plot src="{slug}.png" loading=lazy></a></div></div>')
    html = (
        "<!doctype html><meta charset=utf-8><title>the " + str(len(picks)) + " that stand</title>"
        "<style>body{background:#0b0f0e;color:#cdd;font:13px ui-monospace,monospace;margin:0;padding:22px 26px}"
        "h1{color:#5bef6f;font-size:18px;margin:0 0 4px}.sub{color:#789;margin:0 0 16px}"
        ".row{border:1px solid #1c2722;border-radius:7px;margin:9px 0;padding:10px 12px;background:#0d1311}"
        ".hd{display:flex;align-items:center;gap:10px;margin-bottom:4px}.rk{color:#566}.nm{color:#eaf;font-size:14px;font-weight:600}"
        ".tag{font-size:10px;border:1px solid;border-radius:4px;padding:1px 6px}.met{color:#8aa;margin-bottom:7px}.met b{color:#cfe9df}"
        ".body{display:flex;gap:14px;align-items:center}audio{height:30px;width:360px}"
        ".plot{height:96px;border:1px solid #1c2722;border-radius:4px}</style>"
        f"<h1>the {len(picks)} that stand</h1>"
        f"<p class=sub>distilled from {len(items)} survivors of <b>{run.name}</b> — farthest-point diversity on "
        f"z-scored metrics (cap {cap}/specialist). Each clip = a continuous Morph sweep 0→1→0 (Q .7) on "
        f"white noise (AGC, no QSound) — the peak rings out and glides between its two landing notes. The EAR picks.</p>"
        + "".join(cards))
    (out / "stands.html").write_text(html, encoding="utf-8")
    print(f"\nwrote {len(picks)} finalists -> {out}")
    print(f"open: {out / 'stands.html'}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    run_dir = args[0] if args else "dev/tmp/production_authoring/overnight_corridor_01"
    n_keep = int(args[1]) if len(args) > 1 else 20
    cap = int(args[2]) if len(args) > 2 else 3
    raise SystemExit(main(run_dir, n_keep, cap))
