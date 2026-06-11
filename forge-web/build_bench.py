#!/usr/bin/env python3
"""Build THE bench: one self-contained forge-web/bench.html — the transparency +
safety surface for every body (50 real P2K from the atlas + authored + compiled).
Response (per-stage overlay) + z-plane (numbered S1-S6) + safety strip + clickable
5x5 Morph×Q surface map + numbers + audio. Live, plot==engine. Double-click to open."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KMAP = {"M0Q0": "M0_Q0", "M100Q0": "M100_Q0", "M0Q100": "M0_Q100", "M100Q100": "M100_Q100"}
CK = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]


def words_from_bytes(b: bytes):
    out, p = {}, 0
    for key in CK:
        rows = []
        for _ in range(6):
            rows.append([b[p + 2 * w] | (b[p + 2 * w + 1] << 8) for w in range(5)]); p += 10
        out[key] = rows
    return out


bodies = []
atlas = json.loads((ROOT / "dev/tmp/p2k/atlas/P2K_atlas.json").read_text())
for name, e in atlas.items():
    bodies.append({"name": name, "group": "P2K " + (e.get("order_type") or ""),
                   "words": {KMAP[k]: v["words"] for k, v in e["corners"].items()}})
for grp, sub in [("Talking Hedz", "talking_hedz"), ("Fuzzi Face", "fuzzi_face")]:
    d = ROOT / "dev/tmp" / sub
    if d.exists():
        for bf in sorted(d.glob("*.body240")):
            bodies.append({"name": bf.stem, "group": grp, "words": words_from_bytes(bf.read_bytes())})
cdir = ROOT / "dev/tmp/compiler"
if cdir.exists():
    for bf in sorted(cdir.rglob("*.body240")):
        bodies.append({"name": bf.stem, "group": "Compiled", "words": words_from_bytes(bf.read_bytes())})

TEMPLATE = r"""<!doctype html><html><head><meta charset=utf-8><title>TRENCH bench</title>
<style>
 body{background:#0a0d0c;color:#cde;font:13px ui-monospace,Menlo,monospace;margin:0;padding:12px 18px}
 h1{color:#5bef6f;font-size:16px;margin:0 0 2px}.sub{color:#566;font-size:11px;margin:0 0 10px}
 header{display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap;margin-bottom:8px}
 select{background:#11201b;color:#cfe9df;border:1px solid #2a3a33;padding:5px;font:12px monospace;max-width:340px}
 .sl{display:flex;flex-direction:column;font-size:10px;color:#8aa;gap:2px}
 input[type=range]{width:240px;accent-color:#5bef6f}
 button{background:#1c3a2c;color:#5bef6f;border:1px solid #2a5a3c;padding:6px 14px;cursor:pointer;font:12px monospace;border-radius:4px}
 .strip{background:#0d1311;border:1px solid #1c2722;border-radius:5px;padding:6px 12px;margin-bottom:10px;font-size:12px;letter-spacing:.3px}
 .strip b{color:#cfe9df}.ok{color:#5bef6f}.bad{color:#ff5a44;font-weight:bold}
 .wrap{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}
 canvas{background:#070a09;border:1px solid #1c2722;border-radius:5px}
 #grid{cursor:pointer}
 #nums{font-size:11px;white-space:pre;line-height:1.5;margin-top:10px}
 .lab{color:#8aa;font-size:10px;margin:2px 0}
</style></head><body>
<h1>TRENCH bench</h1><div class=sub>response first · z-plane second · stage identity always on · runtime verification always on · angle=freq(Morph) radius=Q(sharpness) top↔bottom=mirror</div>
<header>
 <div class=sl><span class=lab>BODY</span><select id=body></select></div>
 <div class=sl><span class=lab>MORPH <span id=mv>0</span>%</span><input id=morph type=range min=0 max=1000 value=0></div>
 <div class=sl><span class=lab>Q <span id=qv>0</span>%</span><input id=q type=range min=0 max=1000 value=0></div>
 <button id=play>▶ play</button>
</header>
<div id=safety class=strip>—</div>
<div class=wrap>
 <div><div class=lab>magnitude response (dB) 40Hz→16kHz &nbsp;·&nbsp; bright = total, faint = each stage</div><canvas id=resp width=760 height=300></canvas></div>
 <div>
  <div class=lab>z-plane &nbsp;·&nbsp; numbered S1–S6</div><canvas id=zplane width=300 height=300></canvas>
  <div class=lab>Morph×Q surface (max dB) · click a cell</div><canvas id=grid width=300 height=150></canvas>
 </div>
</div>
<div id=nums></div>
<script>
const SR=39062.5, TAU=Math.PI*2, STAGES=6, WORDS=5;
const BODIES = __BODIES__;
const STAGE=['#5bef6f','#ffd23e','#2ec4ff','#ff6b6b','#9b8cff','#f0883e'];
function decodeWord(w){const u=(w&0xffff)+1;if(u===65536)return 1;if(u===1)return 0;const e=(u>>12)&0xf,m=u&0xfff;if(e===0)return (m/4096)*Math.pow(2,-15);return ((m+4096)/8192)*Math.pow(2,e-15);}
function i16(n){const u=n&0xffff;return u>=0x8000?u-0x10000:u;}
function lerpU16(a,b,f){const d=(b|0)-(a|0);return (i16(Math.trunc(Math.fround(d*Math.fround(f))))+(a|0))&0xffff;}
function k2b(r){const d0=decodeWord(r[0]),d1=decodeWord(r[1]),d2=decodeWord(r[2]),d3=decodeWord(r[3]),d4=decodeWord(r[4]);const k=[4*d0+d1,d1,4*d2+d3,d3,4*d4];return [k[4],(k[0]-2)*k[4],(1-k[1])*k[4],k[2]-2,1-k[3]];}
function bqsAt(W,m,q){const A=W.M0_Q0,B=W.M100_Q0,C=W.M0_Q100,D=W.M100_Q100,o=[];for(let s=0;s<STAGES;s++){const r=[];for(let w=0;w<WORDS;w++){const e0=lerpU16(A[s][w],B[s][w],m),e1=lerpU16(C[s][w],D[s][w],m);r.push(lerpU16(e0,e1,q));}o.push(k2b(r));}return o;}
function bqDb(bq,f){const[b0,b1,b2,a1,a2]=bq,w=TAU*f/SR,c=Math.cos(w),s=Math.sin(w),c2=Math.cos(2*w),s2=Math.sin(2*w);const nr=b0+b1*c+b2*c2,ni=-(b1*s+b2*s2),dr=1+a1*c+a2*c2,di=-(a1*s+a2*s2);return 20*Math.log10(Math.max(1e-12,Math.hypot(nr,ni)/Math.max(1e-12,Math.hypot(dr,di))));}
function roots(c1,c2){const d=c1*c1-4*c2;if(d<0){const r=Math.sqrt(Math.max(c2,0)),t=r>1e-9?Math.acos(Math.max(-1,Math.min(1,-c1/(2*r)))):0;return[r,t*SR/TAU];}return[Math.abs((-c1+Math.sqrt(d))/2),0];}
const NF=440,FREQS=[];for(let i=0;i<NF;i++)FREQS.push(40*Math.pow(400,i/(NF-1)));
const LX=f=>Math.log10(f/40)/Math.log10(400);
let cur=BODIES[0],M=0,Q=0,playing=false;
const sel=document.getElementById('body');
BODIES.forEach((b,i)=>{const o=document.createElement('option');o.value=i;o.textContent=b.group+'  ·  '+b.name;sel.appendChild(o);});
const rc=document.getElementById('resp'),zc=document.getElementById('zplane'),gc=document.getElementById('grid');
const rx=rc.getContext('2d'),zx=zc.getContext('2d'),gx=gc.getContext('2d');
const DMAX=24,DMIN=-72;
function drawResp(bqs){const W=rc.width,H=rc.height;rx.clearRect(0,0,W,H);
 rx.strokeStyle='#15201b';[100,1000,10000].forEach(f=>{const x=W*LX(f);rx.beginPath();rx.moveTo(x,0);rx.lineTo(x,H);rx.stroke();});
 rx.strokeStyle='#243';const y0=H-(0-DMIN)/(DMAX-DMIN)*H;rx.beginPath();rx.moveTo(0,y0);rx.lineTo(W,y0);rx.stroke();
 bqs.forEach((bq,si)=>{rx.strokeStyle=STAGE[si];rx.globalAlpha=0.30;rx.lineWidth=1;rx.beginPath();
  FREQS.forEach((f,i)=>{const x=W*LX(f),y=H-(Math.max(DMIN,Math.min(DMAX,bqDb(bq,f)))-DMIN)/(DMAX-DMIN)*H;i?rx.lineTo(x,y):rx.moveTo(x,y);});rx.stroke();});
 rx.globalAlpha=1;rx.strokeStyle='#dff';rx.lineWidth=1.8;rx.beginPath();
 FREQS.forEach((f,i)=>{let s=0;for(const bq of bqs)s+=bqDb(bq,f);const x=W*LX(f),y=H-(Math.max(DMIN,Math.min(DMAX,s))-DMIN)/(DMAX-DMIN)*H;i?rx.lineTo(x,y):rx.moveTo(x,y);});rx.stroke();}
function drawZ(bqs){const W=zc.width,cx=W/2,cy=W/2,R=W*0.42;zx.clearRect(0,0,W,W);
 zx.strokeStyle='#2a3a33';zx.lineWidth=1;zx.beginPath();zx.arc(cx,cy,R,0,TAU);zx.stroke();
 [0.95,0.98,0.995].forEach(rr=>{zx.strokeStyle='#13201a';zx.beginPath();zx.arc(cx,cy,R*rr,0,TAU);zx.stroke();});
 zx.strokeStyle='#15201b';zx.beginPath();zx.moveTo(cx-R,cy);zx.lineTo(cx+R,cy);zx.moveTo(cx,cy-R);zx.lineTo(cx,cy+R);zx.stroke();
 zx.fillStyle='#56685e';zx.font='9px ui-monospace,monospace';zx.textAlign='center';
 zx.fillText('f→0',cx+R-15,cy-5);zx.fillText('Nyq',cx-R+14,cy-5);zx.fillText('out = sharper (Q)',cx,cy+R+12);zx.textAlign='left';
 bqs.forEach((bq,si)=>{const[b0,b1,b2,a1,a2]=bq;const[pr,ph]=roots(a1,a2);const[zr,zh]=b0!==0?roots(b1/b0,b2/b0):[0,0];
  const pt=TAU*ph/SR,zt=TAU*zh/SR,col=STAGE[si];
  zx.strokeStyle=col;zx.lineWidth=1.6;for(const sg of [1,-1]){const x=cx+pr*Math.cos(pt)*R,y=cy-sg*pr*Math.sin(pt)*R;zx.beginPath();zx.moveTo(x-4,y-4);zx.lineTo(x+4,y+4);zx.moveTo(x-4,y+4);zx.lineTo(x+4,y-4);zx.stroke();}
  const lx=cx+pr*Math.cos(pt)*R,ly=cy-pr*Math.sin(pt)*R;zx.fillStyle=col;zx.font='9px ui-monospace';zx.fillText(si+1,lx+5,ly-4);
  for(const sg of [1,-1]){const x=cx+zr*Math.cos(zt)*R,y=cy-sg*zr*Math.sin(zt)*R;zx.beginPath();zx.arc(x,y,4,0,TAU);zx.stroke();}});}
function drawNums(bqs){let h='<span style="color:#eaf">'+cur.name+'</span>  '+cur.group+'   morph '+(M*100).toFixed(1)+'% Q '+(Q*100).toFixed(1)+'%\n\n';
 bqs.forEach((bq,i)=>{const[b0,b1,b2,a1,a2]=bq;const[pr,ph]=roots(a1,a2);const[zr,zh]=b0!==0?roots(b1/b0,b2/b0):[0,0];
  const pad=n=>String(Math.round(n)).padStart(6,' ');
  h+='<span style="color:'+STAGE[i]+'">S'+(i+1)+'</span>  pole '+pad(ph)+'Hz r'+pr.toFixed(4)+'    zero '+pad(zh)+'Hz r'+zr.toFixed(4)+'\n';});
 document.getElementById('nums').innerHTML=h;}
function safety(){let maxR=0,maxdb=-999,stable=true;const F=[];for(let i=0;i<80;i++)F.push(40*Math.pow(400,i/79));
 for(let qi=0;qi<5;qi++)for(let mi=0;mi<5;mi++){const bqs=bqsAt(cur.words,mi/4,qi/4);
  for(const bq of bqs){const r=Math.sqrt(Math.max(bq[4],0));if(r>maxR)maxR=r;if(r>=1)stable=false;}
  for(const f of F){let s=0;for(const bq of bqs)s+=bqDb(bq,f);if(s>maxdb)maxdb=s;}}
 const ceil=maxdb>30;
 document.getElementById('safety').innerHTML=
  '<span class="'+(stable?'ok':'bad')+'">'+(stable?'STABLE':'UNSTABLE')+'</span>'
  +' &nbsp;·&nbsp; max R <b>'+maxR.toFixed(4)+'</b>'+(maxR>0.995?' <span class=bad>(hot)</span>':'')
  +' &nbsp;·&nbsp; max dB <b>'+maxdb.toFixed(1)+'</b>'
  +' &nbsp;·&nbsp; <span class="'+(ceil?'bad':'ok')+'">CEILING '+(ceil?'⚠ '+maxdb.toFixed(0)+'dB':'clear')+'</span>';}
function drawGrid(){const W=gc.width,H=gc.height,cw=W/5,ch=H/5,F=[];for(let i=0;i<48;i++)F.push(40*Math.pow(400,i/47));
 const v=[];let vmax=-999,vmin=999;
 for(let qi=0;qi<5;qi++){v[qi]=[];for(let mi=0;mi<5;mi++){const bqs=bqsAt(cur.words,mi/4,qi/4);let s=-999;for(const f of F){let t=0;for(const bq of bqs)t+=bqDb(bq,f);if(t>s)s=t;}v[qi][mi]=s;if(s>vmax)vmax=s;if(s<vmin)vmin=s;}}
 gx.clearRect(0,0,W,H);
 for(let qi=0;qi<5;qi++)for(let mi=0;mi<5;mi++){const t=(v[qi][mi]-vmin)/Math.max(1,vmax-vmin),x=mi*cw,y=(4-qi)*ch;
  gx.fillStyle='rgb('+Math.round(t*255)+','+Math.round(t*120)+','+Math.round(t*30)+')';gx.fillRect(x+1,y+1,cw-2,ch-2);
  if(Math.round(M*4)===mi&&Math.round(Q*4)===qi){gx.strokeStyle='#fff';gx.lineWidth=2;gx.strokeRect(x+1,y+1,cw-2,ch-2);}}}
function redraw(){const bqs=bqsAt(cur.words,M,Q);drawResp(bqs);drawZ(bqs);drawNums(bqs);drawGrid();safety();if(playing)rebuildAudio(bqs);}
let ctx,noise,gain,chain=[];
function rebuildAudio(bqs){if(!ctx)return;chain.forEach(n=>{try{n.disconnect();}catch(e){}});chain=[];let prev=noise;for(const bq of bqs){let node;try{node=new IIRFilterNode(ctx,{feedforward:[bq[0],bq[1],bq[2]],feedback:[1,bq[3],bq[4]]});}catch(e){continue;}prev.connect(node);prev=node;chain.push(node);}prev.connect(gain);}
document.getElementById('play').onclick=()=>{if(!ctx){ctx=new AudioContext({sampleRate:SR});const n=Math.floor(ctx.sampleRate*2),buf=ctx.createBuffer(1,n,ctx.sampleRate),d=buf.getChannelData(0);for(let i=0;i<n;i++)d[i]=(Math.random()*2-1)*0.4;noise=ctx.createBufferSource();noise.buffer=buf;noise.loop=true;gain=ctx.createGain();gain.gain.value=0;gain.connect(ctx.destination);noise.start();}ctx.resume();playing=!playing;gain.gain.value=playing?0.4:0;if(playing)rebuildAudio(bqsAt(cur.words,M,Q));document.getElementById('play').textContent=playing?'■ stop':'▶ play';};
function setMQ(m,q){M=m;Q=q;document.getElementById('morph').value=M*1000;document.getElementById('q').value=Q*1000;document.getElementById('mv').textContent=(M*100).toFixed(0);document.getElementById('qv').textContent=(Q*100).toFixed(0);redraw();}
sel.onchange=e=>{cur=BODIES[+e.target.value];redraw();};
document.getElementById('morph').oninput=e=>{M=+e.target.value/1000;document.getElementById('mv').textContent=(M*100).toFixed(0);redraw();};
document.getElementById('q').oninput=e=>{Q=+e.target.value/1000;document.getElementById('qv').textContent=(Q*100).toFixed(0);redraw();};
gc.onclick=e=>{const r=gc.getBoundingClientRect(),mi=Math.floor((e.clientX-r.left)/(gc.width/5)),qi=4-Math.floor((e.clientY-r.top)/(gc.height/5));setMQ(Math.max(0,Math.min(4,mi))/4,Math.max(0,Math.min(4,qi))/4);};
redraw();
</script></body></html>"""

out = ROOT / "forge-web" / "bench.html"
out.write_text(TEMPLATE.replace("__BODIES__", json.dumps(bodies)), encoding="utf-8")
print(f"wrote {out}  ({len(bodies)} bodies, {out.stat().st_size//1024} KB, self-contained)")
