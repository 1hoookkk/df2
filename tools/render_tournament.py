#!/usr/bin/env python3
"""render_tournament — pink noise through every .body240 in a set of dirs, via
the SHIPPED engine (AGC + saturate), ONE continuous MORPH TRAVEL clip per body
(M0->M100 at Q0, return at Q100, Q-bloom at mid) — the interpolation is the
audition, automated per block through the shipped FFI.

Builds a progressive keep/kill + star-rank page (tournament.html) that narrows
to the winners. The EAR ranks — this only renders and lays out.

  python -m tools.render_tournament                # default dir list below
  python -m tools.render_tournament DIR [DIR ...]  # override
"""
from __future__ import annotations

import hashlib
import json
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent          # df2-workstation (output home)
DF2 = Path("C:/Users/hooki/df2")                        # engine FFI home
for p in (str(DF2), str(DF2 / "pyruntime")):
    if p not in sys.path:
        sys.path.insert(0, p)

from pyruntime import trench_ffi

SR = 44100
POSE_SEC = 0.6
GAP_SEC = 0.12
POSITIONS = [
    ("HOME", 0.0, 0.0),
    ("MORPH", 1.0, 0.0),
    ("TENSION", 0.0, 1.0),
    ("MORPH+TENSION", 1.0, 1.0),
    ("MIDDLE", 0.5, 0.5),
]

DEFAULT_DIRS = [
    "composed", "culdesac_100", "families", "cul_de_sac", "knockerz",
    "lpc_scream", "lpc_talker", "experiment_100_biquads_rich_quarry",
    "packed_interp_ab", "experiment_100_biquads_polyvowel", "typed_vowl",
    "body240_cascade_gate", "forge_sheet", "journeys_0705",
    "wizard_reverse_0705", "letters_v3_pack_0705",
]


def pink_noise(n, seed=1):
    """Paul Kellett pink filter over white noise -> -3 dB/oct. Fixed seed so
    every render/session uses the identical excitation (fair A/B)."""
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n)
    b = [0.0] * 7
    out = np.empty(n)
    for i, w in enumerate(white):
        b[0] = 0.99886 * b[0] + w * 0.0555179
        b[1] = 0.99332 * b[1] + w * 0.0750759
        b[2] = 0.96900 * b[2] + w * 0.1538520
        b[3] = 0.86650 * b[3] + w * 0.3104856
        b[4] = 0.55000 * b[4] + w * 0.5329522
        b[5] = -0.7616 * b[5] - w * 0.0168980
        out[i] = b[0] + b[1] + b[2] + b[3] + b[4] + b[5] + b[6] + w * 0.5362
        b[6] = w * 0.115926
    out /= np.max(np.abs(out)) + 1e-12
    return (out * 0.9).astype(np.float32)


def travel_trajectory(n_blocks):
    """The clip IS the morph: sweep M0->M100 at Q0, return at Q100, then
    Q-bloom at mid-morph. Continuous filter state — the shipped path."""
    third = n_blocks // 3
    m, q = [], []
    for b in range(n_blocks):
        if b < third:                      # travel out
            m.append(b / max(third - 1, 1)); q.append(0.0)
        elif b < 2 * third:                # return, stressed
            t = (b - third) / max(third - 1, 1)
            m.append(1.0 - t); q.append(1.0)
        else:                              # bloom at mid-morph
            t = (b - 2 * third) / max(n_blocks - 2 * third - 1, 1)
            m.append(0.5); q.append(t)
    return m, q

TRAVEL_SEC = 6.0
TRAVEL_BLOCK = 512


def render_body(bb, src, trajectory):
    """ONE continuous render through the shipped engine with (morph, q)
    automated per block — the clip IS the interpolation, not corner poses."""
    m_blocks, q_blocks = trajectory
    raw = trench_ffi.engine_render_automated(bb, m_blocks, q_blocks, src.tobytes(),
                                             SR, block=TRAVEL_BLOCK)
    wet = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    pk = np.max(np.abs(wet))
    if pk > 1e-9:
        wet = wet / pk * 0.9  # level match: judge tone, not loudness
    return wet


def write_wav(path, x):
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    if not trench_ffi.engine_available():
        print("ABORT: shipped engine (trench_ffi) unavailable — would fall back to a")
        print("no-AGC Python cascade. That is NOT the shipped character; do not judge it.")
        print("Rebuild: cargo build --manifest-path trench-core/Cargo.toml")
        sys.exit(1)

    dirs = sys.argv[1:] or DEFAULT_DIRS
    tmp = ROOT / "dev" / "tmp"
    roots = [Path(d) if Path(d).is_absolute() else tmp / d for d in dirs]

    # collect every .body240, dedupe by content hash, remember the empties
    found, seen, empty_dirs = [], {}, []
    for r in roots:
        hits = sorted(r.rglob("*.body240")) if r.exists() else []
        renderable = 0
        for fp in hits:
            bb = fp.read_bytes()
            if len(bb) != 240:
                print(f"  skip (not 240B): {fp.relative_to(tmp)}")
                continue
            h = hashlib.sha1(bb).hexdigest()
            if h in seen:
                continue
            seen[h] = True
            found.append((fp, bb))
            renderable += 1
        if renderable == 0:
            empty_dirs.append(r.name)

    if not found:
        print("No .body240 bodies found in:", ", ".join(dirs))
        sys.exit(1)

    out = tmp / "audition" / "tournament"
    (out / "wav").mkdir(parents=True, exist_ok=True)
    (out / "plots").mkdir(parents=True, exist_ok=True)
    n_travel = int(SR * TRAVEL_SEC)
    src = pink_noise(n_travel)
    trajectory = travel_trajectory((n_travel + TRAVEL_BLOCK - 1) // TRAVEL_BLOCK)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_f = np.logspace(np.log10(30.0), np.log10(19200.0), 384)
    w = 2 * np.pi * plot_f / 39062.5
    z1 = np.exp(-1j * w); z2 = z1 * z1

    def corner_db(bb, m, q):
        pr = trench_ffi.packed_probe(bb, m, q)
        mag = np.ones_like(plot_f)
        for (b0, b1, b2, a1, a2) in pr["biquad"]:
            mag *= np.abs(b0 + b1 * z1 + b2 * z2) / np.maximum(np.abs(1 + a1 * z1 + a2 * z2), 1e-12)
        return 20 * np.log10(np.maximum(mag, 1e-9))

    def write_plot(bb, path):
        fig, ax = plt.subplots(figsize=(3.6, 1.15), dpi=100)
        fig.patch.set_facecolor("#0e1512"); ax.set_facecolor("#0e1512")
        for m, q, c in [(0, 0, "#5b9bd5"), (1, 0, "#e0555f"), (0, 1, "#5bef6f"), (1, 1, "#ffd23e")]:
            ax.semilogx(plot_f, corner_db(bb, m, q), color=c, lw=0.9)
        ax.axhline(0, color="#3a4a42", lw=0.5)
        ax.set_ylim(-55, 60); ax.set_xlim(30, 19200)
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color("#1c2722")
        fig.subplots_adjust(0, 0, 1, 1)
        fig.savefig(path, facecolor="#0e1512")
        plt.close(fig)


    items = []
    for i, (fp, bb) in enumerate(found):
        wid = f"{i:03d}"
        clip = render_body(bb, src, trajectory)
        write_wav(out / "wav" / f"{wid}.wav", clip)
        write_plot(bb, out / "plots" / f"{wid}.png")
        src_dir = fp.parent.name if fp.parent.name != "bodies" else fp.parent.parent.name
        items.append({"id": wid, "name": fp.stem, "src": src_dir,
                      "wav": f"wav/{wid}.wav", "plot": f"plots/{wid}.png"})
        print(f"  [{i + 1}/{len(found)}] {src_dir}/{fp.stem}")

    (out / "tournament.html").write_text(build_html(items), encoding="utf-8")
    if empty_dirs:
        print("\nNo renderable .body240 (skipped — only pre-rendered wavs/reports/src):")
        print("  " + ", ".join(empty_dirs))
    print(f"\n{len(items)} bodies rendered via SHIPPED engine (AGC+saturate), pink noise, MORPH TRAVEL clip.")
    print(f"open: {out / 'tournament.html'}")


def build_html(items):
    data = json.dumps(items)
    return TEMPLATE.replace("/*DATA*/[]", data)


TEMPLATE = r"""<!doctype html><meta charset=utf-8><title>TRENCH tournament</title>
<style>
:root{color-scheme:dark}
body{background:#0b0f0e;color:#cdd;font:14px/1.4 monospace;margin:0;padding:0 18px 120px}
header{position:sticky;top:0;background:#0b0f0e;padding:12px 0 8px;border-bottom:1px solid #1c2722;z-index:5}
h1{color:#5bef6f;margin:0 0 6px;font-size:15px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
button,select{background:#12201a;color:#cdd;border:1px solid #2a3d33;border-radius:5px;padding:5px 9px;font:13px monospace;cursor:pointer}
button:hover{border-color:#5bef6f}
.stat{color:#789}
.keys{color:#567;font-size:12px;margin-top:4px}
.grp{color:#5bef6f;margin:14px 0 2px;font-size:13px;border-bottom:1px dashed #1c2722}
.row{display:flex;gap:10px;align-items:center;padding:3px 8px;border-radius:5px;cursor:pointer}
.row:nth-child(even){background:#0d1411}
.row.cur{background:#15251d;outline:1px solid #2f5c42}
.row.killed{opacity:.25;filter:grayscale(1)}
.n{color:#ffd23e;flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.plot{height:44px;width:220px;object-fit:cover;border:1px solid #1c2722;border-radius:3px}
.stars{display:flex;gap:1px}
.star{color:#333c38;font-size:17px;cursor:pointer;user-select:none;line-height:1}
.star.on{color:#ffd23e}
.kill{color:#e0555f;border-color:#5a2a2e;padding:2px 7px}
.kill.on{background:#5a2a2e;color:#fff}
.playmark{width:14px;color:#5bef6f}
#deck{position:fixed;left:0;right:0;bottom:0;background:#0e1713;border-top:1px solid #2a3d33;padding:8px 18px;display:flex;gap:12px;align-items:center;z-index:9}
#now{color:#ffd23e;min-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#player{flex:1}
audio{width:100%;height:34px}
</style>
<header>
<h1>TRENCH tournament — pink noise · shipped engine · morph travel</h1>
<div class=bar>
  <span class=stat id=stat></span>
  <select id=filter>
    <option value=active>alive</option>
    <option value=all>everything</option>
    <option value=unrated>unrated alive</option>
    <option value=rated>rated</option>
    <option value=top20>TOP 20</option>
    <option value=top10>TOP 10</option>
  </select>
  <select id=fam><option value="">family: all</option></select>
  <select id=sort>
    <option value=orig>sort: roster</option>
    <option value=rank>sort: rating</option>
  </select>
  <label><input type=checkbox id=auto checked> auto-advance</label>
  <button id=cull>cull unrated+1&#9733;</button>
  <button id=export>export</button>
  <button id=reset>reset</button>
</div>
<div class=keys>SPACE play/pause &middot; &uarr;&darr; move &middot; ENTER play row &middot; 1&ndash;5 rate &middot; 0 clear &middot; X kill &middot; listening advances by itself</div>
</header>
<div id=list></div>
<div id=deck><span id=now>&mdash;</span><span id=player><audio id=au controls preload=auto></audio></span></div>
<script>
const ITEMS=/*DATA*/[];
const KEY='trench_tourney_v2';
let ST=JSON.parse(localStorage.getItem(KEY)||'{}');
function get(id){return ST[id]||(ST[id]={r:0,k:false});}
function save(){localStorage.setItem(KEY,JSON.stringify(ST));}
function famOf(n){const m=n.match(/^([A-Za-z]+)[_-]/);return m?m[1]:'misc';}
let cur=null;
let shown=[];
const au=document.getElementById('au');

const famSel=document.getElementById('fam');
[...new Set(ITEMS.map(x=>famOf(x.name)))].sort().forEach(f=>{
  const o=document.createElement('option');o.value=f;o.textContent='family: '+f;famSel.appendChild(o);
});

function view(){
  let a=ITEMS.map(it=>({...it,...get(it.name)}));
  const f=document.getElementById('filter').value;
  if(f==='active')a=a.filter(x=>!x.k);
  else if(f==='rated')a=a.filter(x=>x.r>0);
  else if(f==='unrated')a=a.filter(x=>!x.k&&!x.r);
  const fam=famSel.value;
  if(fam)a=a.filter(x=>famOf(x.name)===fam);
  if(document.getElementById('sort').value==='rank'||f.startsWith('top'))
    a.sort((x,y)=>(y.r-x.r)||(x.id<y.id?-1:1));
  if(f==='top20')a=a.filter(x=>!x.k).slice(0,20);
  if(f==='top10')a=a.filter(x=>!x.k).slice(0,10);
  return a;
}
function render(){
  const a=view();shown=a.map(x=>x.name);
  const alive=ITEMS.filter(x=>!get(x.name).k).length;
  const rated=ITEMS.filter(x=>get(x.name).r>0).length;
  document.getElementById('stat').textContent=
    ITEMS.length+' bodies | '+alive+' alive | '+rated+' rated | showing '+a.length;
  const L=document.getElementById('list');L.innerHTML='';
  let lastFam=null;
  a.forEach(x=>{
    const f=famOf(x.name);
    if(f!==lastFam){const h=document.createElement('div');h.className='grp';h.textContent=f;L.appendChild(h);lastFam=f;}
    const d=document.createElement('div');
    d.className='row'+(x.k?' killed':'')+(x.name===cur?' cur':'');
    d.dataset.row=x.name;
    d.innerHTML=
      '<span class=playmark>'+(x.name===cur?'&#9654;':'')+'</span>'+
      '<span class=n>'+x.name+'</span>'+
      '<span class=stars>'+[1,2,3,4,5].map(s=>'<span class="star'+(x.r>=s?' on':'')+'" data-id="'+x.name+'" data-s="'+s+'">&#9733;</span>').join('')+'</span>'+
      '<button class="kill'+(x.k?' on':'')+'" data-kill="'+x.name+'">'+(x.k?'dead':'X')+'</button>'+
      '<img class=plot loading=lazy src="'+x.plot+'">';
    L.appendChild(d);
  });
  document.getElementById('now').textContent=cur||'&mdash;';
}
function play(name){
  if(!name)return;
  cur=name;
  const it=ITEMS.find(x=>x.name===name);
  au.src=it.wav;au.play();
  render();
  const el=document.querySelector('[data-row="'+CSS.escape(name)+'"]');
  if(el)el.scrollIntoView({block:'center',behavior:'smooth'});
}
function step(d){
  if(!shown.length)return;
  let i=shown.indexOf(cur);
  i=(i<0)?0:Math.min(shown.length-1,Math.max(0,i+d));
  play(shown[i]);
}
au.onended=()=>{if(document.getElementById('auto').checked)step(1);};
document.addEventListener('click',e=>{
  const t=e.target;
  if(t.dataset.s){const g=get(t.dataset.id);g.r=(g.r==+t.dataset.s?0:+t.dataset.s);save();render();}
  else if(t.dataset.kill){const g=get(t.dataset.kill);g.k=!g.k;save();render();}
  else{const row=t.closest('[data-row]');if(row)play(row.dataset.row);}
});
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='SELECT'||e.target.tagName==='INPUT')return;
  if(e.code==='Space'){e.preventDefault();au.paused?(au.src?au.play():step(1)):au.pause();}
  else if(e.key==='ArrowDown'||e.key==='ArrowRight'){e.preventDefault();step(1);}
  else if(e.key==='ArrowUp'||e.key==='ArrowLeft'){e.preventDefault();step(-1);}
  else if(e.key==='Enter'){step(0);}
  else if(e.key>='1'&&e.key<='5'&&cur){const g=get(cur);g.r=+e.key;save();render();}
  else if(e.key==='0'&&cur){get(cur).r=0;save();render();}
  else if((e.key==='x'||e.key==='X')&&cur){const g=get(cur);g.k=!g.k;save();
    if(g.k&&document.getElementById('auto').checked)step(1);else render();}
});
document.getElementById('filter').onchange=()=>render();
famSel.onchange=()=>render();
document.getElementById('sort').onchange=render;
document.getElementById('cull').onclick=()=>{
  if(!confirm('Kill everything unrated or rated 1 star?'))return;
  ITEMS.forEach(it=>{const g=get(it.name);if(!g.k&&g.r<=1)g.k=true;});save();render();
};
document.getElementById('reset').onclick=()=>{
  if(!confirm('Wipe every verdict?'))return;ST={};save();render();
};
document.getElementById('export').onclick=()=>{
  const a=ITEMS.map(it=>({...it,...get(it.name)})).filter(x=>!x.k&&x.r>0)
    .sort((x,y)=>(y.r-x.r)||(x.id<y.id?-1:1));
  const txt=a.map((x,i)=>String(i+1).padStart(2)+'. '+'#'.repeat(x.r)+' '.repeat(5-x.r)+'  '+x.name+'  ('+x.src+')').join('\n');
  const blob=new Blob([txt||'(nothing kept + rated yet)'],{type:'text/plain'});
  const u=URL.createObjectURL(blob);const link=document.createElement('a');
  link.href=u;link.download='trench_ranking.txt';link.click();
};
render();
</script>
"""


if __name__ == "__main__":
    main()
