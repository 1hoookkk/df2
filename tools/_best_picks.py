"""One-shot: pull the top pick from each family in an analyzed sweep, print + write best.html."""
import json, os, html as H, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sw = ROOT / "dev" / "tmp" / "sweep" / "roster_intent_0528"
fam_dir = sw / "families"

picks = []
for fp in sorted(fam_dir.glob("*.json")):
    d = json.loads(fp.read_text(encoding="utf-8"))
    sl = d.get("shortlist", [])
    if sl:
        picks.append((d, sl[0]))

print("=== THE BEST (top of each family's analyzer-ranked shortlist) ===\n")
for d, c in picks:
    h = c.get("home_intent", "?"); a = c.get("away_intent", "?"); mi = c.get("mid_intent")
    third = c.get("third_state"); tr = c.get("trajectory", {}); s = c.get("summary", {})
    if mi and third:
        mid_lbl = f"-> [{mi}] ->"
    elif mi:
        mid_lbl = f"-> ~{mi} ->"
    else:
        mid_lbl = "-> mush ->"
    print(f"  {d['name']:<9}  {h} {mid_lbl} {a}   ({c['name']})")
    print(f"             motion={s.get('moves_on_morph_hz')}Hz  mono={tr.get('monotonicity')}  mid-dist={c.get('mid_distance_db')}dB")
    print(f"             {c['keep_cmd']}\n")

rows = []
for d, c in picks:
    cdir = Path(c["dir"])
    rel = os.path.relpath(cdir, sw).replace(os.sep, "/")
    h, a, mi = c.get("home_intent"), c.get("away_intent"), c.get("mid_intent")
    third = c.get("third_state"); tr = c.get("trajectory", {}); s = c.get("summary", {})
    if h and third and mi:
        intent = f'<span class="intent three"><b>{H.escape(h)}</b> &rarr; <b>{H.escape(mi)}</b> &rarr; <b>{H.escape(a)}</b></span>'
    elif h:
        lbl = mi if mi else "mid"
        intent = f'<span class="intent">{H.escape(h)} &rarr; <i>{H.escape(lbl)}</i> &rarr; {H.escape(a)}</span>'
    else:
        intent = '<span class="intent random">random</span>'
    rows.append(f"""<section class="cand">
<header><div><h2>{H.escape(d['name'])} · {intent}</h2>
<p class="meta">motion {s.get('moves_on_morph_hz')}Hz · monotonicity {tr.get('monotonicity')} · mid distance {c.get('mid_distance_db')}dB</p></div>
<div class="vote"><button data-vote="KEEP">KEEP</button><button data-vote="MAYBE">MAYBE</button><button data-vote="REJECT">REJECT</button></div></header>
<img class="resp" loading="lazy" src="{rel}/response.png">
<div class="clips">
  <label>HOME<span>M0 Q0</span><audio controls preload="none" src="{rel}/m0_q0.wav"></audio></label>
  <label>AWAY<span>M100 Q0</span><audio controls preload="none" src="{rel}/m100_q0.wav"></audio></label>
  <label>TIGHT HOME<span>M0 Q100</span><audio controls preload="none" src="{rel}/m0_q100.wav"></audio></label>
  <label>TIGHT AWAY<span>M100 Q100</span><audio controls preload="none" src="{rel}/m100_q100.wav"></audio></label>
  <label>MIDDLE<span>M50 Q50</span><audio controls preload="none" src="{rel}/midpoint.wav"></audio></label>
  <label>Morph sweep<span>motion</span><audio controls preload="none" src="{rel}/morph_sweep.wav"></audio></label>
</div>
<code>{H.escape(c['keep_cmd'])}</code>
</section>""")

doc = f"""<!doctype html><meta charset="utf-8"><title>the best — one per family</title>
<style>
body{{margin:0;background:#080a0a;color:#eee9dc;font:14px/1.5 system-ui,Segoe UI,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 18px}}
h1{{font-size:28px;margin:0 0 6px}} h2{{font-size:21px;margin:0 0 4px;color:#9fe7c6}}
.meta{{color:#a4aaa2;margin:0 0 5px;font:12px ui-monospace,Consolas,monospace}}
.intent{{color:#9fe7c6;font:13px ui-monospace,Consolas,monospace;background:#0e1a16;border:1px solid #2a3d34;border-radius:4px;padding:2px 7px;margin-left:6px}}
.intent.three{{color:#cfe9dc;background:#10271b;border-color:#3a6e52}}
.intent.random{{color:#a4aaa2;background:#101010;border-color:#2a2a2a}}
.intent i{{color:#a4aaa2}}
.cand{{border:1px solid #20342d;background:#0d1110;border-radius:8px;padding:14px;margin:14px 0}}
header{{display:flex;gap:16px;align-items:flex-start;justify-content:space-between}}
.vote{{display:flex;gap:8px}}
button{{background:#151a18;color:#eee9dc;border:1px solid #405247;border-radius:5px;padding:7px 10px;cursor:pointer}}
img.resp{{display:block;width:100%;max-width:780px;border-radius:6px;margin:10px 0;border:1px solid #18221d}}
.clips{{display:grid;grid-template-columns:1fr 1fr;gap:9px 16px;margin-top:10px}}
label{{display:block;color:#f1d76a;font:12px ui-monospace,Consolas,monospace}}
label span{{color:#79827b;margin-left:8px}} audio{{display:block;width:100%;margin-top:4px}}
code{{display:block;white-space:pre-wrap;color:#81d4ff;background:#070908;border:1px solid #18221d;border-radius:5px;padding:8px;margin-top:10px}}
</style>
<main><h1>the best — one per family</h1>
<p class="meta">analyzer-ranked top pick per family from roster_intent_0528. The middle is a mathematical consequence of the corners — '[x]' = actual middle landed near a named third state; '~x' = close-ish; 'mid' = nothing named; 'mush' = no match.</p>
{''.join(rows)}
</main>"""
(sw / "best.html").write_text(doc, encoding="utf-8")
print(f"wrote: {sw / 'best.html'}")
