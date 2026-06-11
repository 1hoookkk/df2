#!/usr/bin/env python3
"""morph_q_grid.py — see each body across the MORPH 0-100 x Q 0-100 grid.

Every cell is the cascade response at that (morph, q), computed through the
SHIPPED trench_core.dll (`packed_probe`) — no re-ported DSP, the plot is the
engine. Unstable cells (pole radius >= 1) are flagged red.

  python tools/morph_q_grid.py <dir_or_glob> [--n 5] [--out dev/tmp/morph_q_grid]
  python tools/morph_q_grid.py forge/recipes/auto
"""
import sys, math, glob, html, os
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pyruntime.trench_ffi import packed_probe  # shipped-DLL truth

SR = 39062.5
F_LO, F_HI = 20.0, SR / 2.0
NF = 280
FREQS = np.exp(np.linspace(math.log(F_LO), math.log(F_HI), NF))
W = 2 * np.pi * FREQS / SR
Z1, Z2 = np.exp(-1j * W), np.exp(-2j * W)
DB_LO, DB_HI = -30.0, 36.0


def cascade_db(biquads):
    total = np.zeros(NF)
    for (b0, b1, b2, a1, a2) in biquads:
        num = b0 + b1 * Z1 + b2 * Z2
        den = 1.0 + a1 * Z1 + a2 * Z2
        total += 20.0 * np.log10(np.maximum(np.abs(num / den), 1e-12))
    return total


def grid_for(body_bytes, n):
    steps = np.linspace(0.0, 1.0, n)
    cells = {}
    for q in steps:
        for m in steps:
            p = packed_probe(body_bytes, float(m), float(q))
            cells[(round(m, 3), round(q, 3))] = (
                cascade_db(p["biquad"]),
                p["max_pole_radius"] >= 1.0 or p["nonfinite_mask"] != 0,
            )
    return steps, cells


def plot_body(name, body_bytes, n, out_png):
    steps, cells = grid_for(body_bytes, n)
    fig, axes = plt.subplots(n, n, figsize=(2.0 * n, 1.7 * n), sharex=True, sharey=True)
    xticks = [100, 1000, 10000]
    for qi, q in enumerate(steps):            # rows: q=100 on top, q=0 bottom
        for mi, m in enumerate(steps):
            ax = axes[n - 1 - qi][mi]
            db, bad = cells[(round(m, 3), round(q, 3))]
            ax.semilogx(FREQS, db, color="#d6443a" if bad else "#15140f", lw=1.1)
            ax.set_xlim(F_LO, F_HI); ax.set_ylim(DB_LO, DB_HI)
            ax.axhline(0, color="#ddd7ca", lw=0.6, zorder=0)
            ax.set_xticks(xticks); ax.set_xticklabels([])
            ax.tick_params(length=0); ax.set_yticks([])
            ax.set_facecolor("#faf8f3")
            for s in ax.spines.values(): s.set_color("#cbc5b8"); s.set_linewidth(0.6)
            if qi == n - 1:
                ax.set_title(f"M {int(round(m*100))}", fontsize=8, color="#8b857a", pad=3)
            if mi == 0:
                ax.set_ylabel(f"Q {int(round(q*100))}", fontsize=8, color="#8b857a", rotation=0, ha="right", va="center", labelpad=14)
    fig.suptitle(name, fontsize=12, color="#15140f", x=0.02, ha="left", weight="bold")
    fig.tight_layout(rect=[0.02, 0, 1, 0.97])
    fig.savefig(out_png, dpi=110, facecolor="#f1eee8")
    plt.close(fig)


def _ranked_jobs(csv_path, top):
    """Ranked jobs from a score_target_browser_runs ranking.csv, in rank order."""
    import csv as _csv
    jobs = []
    with open(csv_path, newline="") as fh:
        for row in _csv.DictReader(fh):
            rep = ROOT / row["report"]
            cand = row["candidate"]
            body = rep.parent / f"{cand}.body240"
            label = f"#{int(float(row['rank'])):02d}  {row['run']}  {cand}"
            jobs.append({
                "label": label,
                "body": body,
                "rank": row["rank"],
                "score": row["score"],
                "tier": row["tier"],
                "template": row["template"],
                "run": row["run"],
                "candidate": cand,
                "provenance": row.get("provenance", ""),
                "report": rep,
                "moves_on_morph_hz": row.get("moves_on_morph_hz", ""),
                "q_relocate_hz": row.get("q_relocate_hz", ""),
                "packed_drift_db": row.get("packed_drift_db", ""),
                "character_score": row.get("character_score", ""),
            })
            if top and len(jobs) >= top:
                break
    return jobs


def _plain_jobs(files):
    return [
        {
            "label": f.stem,
            "body": f,
            "rank": "",
            "score": "",
            "tier": "",
            "template": "",
            "run": "",
            "candidate": f.stem,
            "provenance": f.stem,
            "report": None,
            "moves_on_morph_hz": "",
            "q_relocate_hz": "",
            "packed_drift_db": "",
            "character_score": "",
        }
        for f in files
    ]


def _rel(path, start):
    return Path(os.path.relpath(path, start)).as_posix()


def _audio_players(job, out):
    if not job.get("report"):
        return ""
    cdir = job["report"].parent
    clips = [
        ("m0_q0.wav", "Home"),
        ("m100_q0.wav", "Morph"),
        ("m0_q100.wav", "Q"),
        ("m100_q100.wav", "Morph + Q"),
        ("midpoint.wav", "Middle"),
        ("morph_sweep.wav", "Morph sweep"),
        ("q_sweep.wav", "Q sweep"),
        ("diagonal_sweep.wav", "Diagonal sweep"),
    ]
    cells = []
    for fname, label in clips:
        path = cdir / fname
        if path.exists():
            cells.append(
                f'<label>{html.escape(label)}'
                f'<audio controls preload="none" src="{html.escape(_rel(path, out))}"></audio></label>'
            )
    return "<div class='audio'>" + "\n".join(cells) + "</div>" if cells else ""


def _keep_command(job):
    if not job.get("report"):
        return ""
    run_dir = job["report"].parents[1]
    return f"python -m tools.target_browser --keep {run_dir.as_posix()} {job['candidate']} --notes \"keeper\""


def _card(stem, job, out):
    score_line = ""
    if job.get("score"):
        score_line = (
            f"<b>score</b> {html.escape(str(job['score']))} · "
            f"<b>tier</b> {html.escape(str(job['tier']))} · "
            f"<b>morph</b> {html.escape(str(job['moves_on_morph_hz']))} Hz · "
            f"<b>Q shift</b> {html.escape(str(job['q_relocate_hz']))} Hz · "
            f"<b>packed drift</b> {html.escape(str(job['packed_drift_db']))} dB"
        )
    cmd = _keep_command(job)
    report = ""
    if job.get("report"):
        report = f"<a href='{html.escape(_rel(job['report'], out))}'>report</a>"
    return f"""
<section class="card" id="{html.escape(stem)}">
  <header>
    <div>
      <h2>{html.escape(job['label'])}</h2>
      <p class="prov">{html.escape(job.get('provenance', ''))}</p>
      <p class="metrics">{score_line}</p>
      <p class="links">{report}</p>
    </div>
    <button onclick="navigator.clipboard && navigator.clipboard.writeText({html.escape(repr(cmd))})">copy keep</button>
  </header>
  <img src="{html.escape(stem)}.png" loading="lazy" alt="{html.escape(job['label'])} morph Q grid">
  {_audio_players(job, out)}
  {f'<code>{html.escape(cmd)}</code>' if cmd else ''}
</section>"""


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = dict(a[2:].split("=", 1) if "=" in a else (a[2:], True) for a in sys.argv[1:] if a.startswith("--"))
    n = int(opts.get("n", 5))

    if opts.get("ranking"):
        out = ROOT / opts.get("out", "dev/tmp/morph_q_grid_ranked")
        out.mkdir(parents=True, exist_ok=True)
        jobs = _ranked_jobs(ROOT / opts["ranking"], int(opts.get("top", 20)))
    else:
        src = args[0] if args else "forge/recipes/auto"
        out = ROOT / opts.get("out", "dev/tmp/morph_q_grid")
        out.mkdir(parents=True, exist_ok=True)
        p = (ROOT / src)
        files = sorted(p.glob("*.body240")) if p.is_dir() else [Path(x) for x in glob.glob(str(ROOT / src))]
        jobs = _plain_jobs(files)

    if not jobs:
        print("no bodies to plot"); return

    entries = []
    for i, job in enumerate(jobs):
        label = job["label"]
        body = job["body"]
        if not body.exists():
            print(f"missing {body}"); continue
        b = body.read_bytes()
        if len(b) != 240:
            print(f"skip {label}: {len(b)} bytes"); continue
        run_slug = f"_{job['run']}" if job.get("run") else ""
        stem = f"{i:03d}{run_slug}_{body.stem}"
        plot_body(label, b, n, out / f"{stem}.png")
        entries.append((stem, job))
        print(f"plotted {label}")

    cards = "\n".join(_card(s, job, out) for s, job in entries)
    idx = out / "index.html"
    idx.write_text(
        "<!doctype html><meta charset=utf-8><title>morph x q grid</title>"
        "<style>"
        "body{background:#080a09;color:#e8eee9;font-family:system-ui,Segoe UI,sans-serif;margin:0}"
        "main{max-width:1280px;margin:0 auto;padding:22px 18px 64px}"
        "h1{font-size:22px;margin:0 0 8px}.note{color:#a9b5ae;margin:0 0 18px}"
        ".card{background:#101512;border:1px solid #2b3b33;margin:0 0 28px}"
        "header{display:flex;justify-content:space-between;gap:16px;padding:13px 14px;border-bottom:1px solid #2b3b33}"
        "h2{font-size:18px;margin:0 0 4px;color:#9be8bd}.prov,.metrics,.links{margin:3px 0;color:#aeb8b1}"
        ".metrics b{color:#f0dc91;font-weight:600}.links a{color:#7dd8ff}button{height:34px;background:#17201b;color:#e8eee9;border:1px solid #496052;border-radius:4px;padding:0 10px}"
        "img{width:100%;display:block;background:#f1eee8}.audio{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;padding:12px 14px;border-top:1px solid #2b3b33}"
        "label{font-size:12px;color:#f0dc91}audio{display:block;width:100%;margin-top:4px}code{display:block;margin:0;padding:10px 14px;color:#8fd8ff;background:#070908;border-top:1px solid #2b3b33;white-space:pre-wrap}"
        "@media(max-width:900px){.audio{grid-template-columns:1fr}header{display:block}button{margin-top:10px}}"
        "</style>"
        f"<main><h1>MORPH 0-100 &times; Q 0-100 &mdash; {len(entries)} bodies</h1>"
        "<p class='note'>Shipped engine grid, ranked order. Each card has the response surface, audio, report, and keep command.</p>"
        f"{cards}</main>"
    )
    print(f"\n{len(entries)} bodies -> {idx}")


if __name__ == "__main__":
    main()
