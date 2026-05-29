"""Generate the self-contained HTML morph player + word-sculpting bench.

No build, no server: every body's verbatim packed-16 words are baked into one
HTML file. Drag the Morph x Q pad and the page runs the REAL packed-word
bilinear morph (lerp_u16, exactly the engine) and redraws the response live.
The word bench lets you edit any w0..w4 of any corner/stage and watch the
response + morph update instantly — nudge -> render -> name. Save back to TOML.
Re-run this script after authoring to refresh the bodies.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROSTER = ["keeper_04", "myvoice_aa", "search_01", "search_02", "search_03", "search_04", "search_05", "search_06",
          "hedz_template", "vox_ah_oo_ee", "vowel_morph", "bell", "tube", "neon_vane", "gong",
          "anvil", "razor", "scream", "bloom", "ascension", "talkbox", "vowelshift", "siphon", "spectre"]
LABELS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]


def load_body(name: str):
    p = ROOT / "bodies" / f"{name}.cart.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    out = {}
    for kf in d["keyframes"]:
        if "packedWords" in kf:
            words = [[int(w) & 0xFFFF for w in row] for row in kf["packedWords"]]
        else:
            from pyruntime.packed_interp import coeffs_to_words
            words = [list(coeffs_to_words(s["c0"], s["c1"], s["c2"], s["c3"], s["c4"])) for s in kf["stages"]]
        out[kf["label"]] = words
    if not all(l in out for l in LABELS):
        return None
    return out


def main():
    bodies = {n: load_body(n) for n in ROSTER}
    bodies = {n: b for n, b in bodies.items() if b}
    html = HTML.replace("/*__DATA__*/", json.dumps(bodies))
    out = ROOT / "dev" / "tmp" / "factory" / "morph_player.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}  ({len(bodies)} bodies)")


HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<title>TRENCH Morph Player + Word Bench</title>
<style>
 body{background:#070a09;color:#e5dccb;font:13px/1.4 Consolas,monospace;margin:0;padding:16px}
 h1{font-size:15px;color:#ffa838;margin:0 0 10px;letter-spacing:2px}
 .row{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}
 select,button{background:#141821;color:#e5dccb;border:1px solid #2f5a6e;padding:5px 9px;font:13px monospace}
 button{cursor:pointer} button:hover{border-color:#9aef5a}
 canvas{background:#0b0f0e;border:1px solid #222;border-radius:8px}
 #pad{cursor:crosshair}
 .lab{color:#8fc8ff;font-size:11px;margin:5px 0 2px}
 #readout{color:#9aef5a}
 table{border-collapse:collapse;margin-top:6px}
 th{color:#8fc8ff;font-size:9px;font-weight:normal;padding:1px 3px}
 td{padding:1px}
 .stg{color:#5a605c;font-size:9px;padding-right:5px;text-align:right}
 input.w{width:54px;background:#0b0f0e;color:#e5dccb;border:1px solid #243;font:11px monospace;text-align:center}
 input.w:focus{border-color:#9aef5a;outline:none}
 .tab{padding:3px 9px;border:1px solid #2f5a6e;cursor:pointer;font-size:11px}
 .tab.on{background:#1a2a1a;border-color:#9aef5a;color:#9aef5a}
 .vocab{color:#777;font-size:10px;margin:4px 0}
</style></head><body>
<h1>TRENCH — MORPH PLAYER + WORD BENCH</h1>
<div class="row" style="margin-bottom:8px">
 <div><div class="lab">BODY</div><select id="body"></select></div>
 <div><div class="lab">MORPH × Q</div><span id="readout">M 50  Q 50</span></div>
 <div><div class="lab">AUDIO</div><button id="play">▶ pink noise</button></div>
 <div><div class="lab">SAVE</div><button id="save">⤓ .packed.toml</button></div>
 <div><div class="lab">&nbsp;</div><label style="font-size:11px"><input type="checkbox" id="link"> link word across all 4 corners</label></div>
</div>
<div class="row">
 <div><div class="lab">MORPH → (x)   Q ↑ (y)</div><canvas id="pad" width="220" height="220"></canvas></div>
 <div><div class="lab">RESPONSE (green = 0 dB · real packed-word morph)</div><canvas id="resp" width="720" height="380"></canvas></div>
</div>
<div class="vocab">w0 = low-end / DC (keep low or pedestal returns) &nbsp;·&nbsp; w1 = high notch / numerator zero &nbsp;·&nbsp; w2 = pole position &nbsp;·&nbsp; w3 = pole sharpness &nbsp;·&nbsp; w4 = level</div>
<div class="row">
 <div>
  <div class="lab">WORD BENCH — edit hex, response updates live. neutral row = DFFF FFFF DFFF FFFF DFFF</div>
  <div id="tabs" class="row" style="gap:4px;margin-bottom:4px"></div>
  <div id="grid"></div>
 </div>
</div>
<script>
const BODIES = /*__DATA__*/;
const SR=39062.5, NYQ=SR/2, LAB=["M0_Q0","M100_Q0","M0_Q100","M100_Q100"];
let cur=Object.keys(BODIES)[0], morph=0.5, q=0.5, tab=0;
let audio=null, playing=false, noiseBuf=null, srcGain=null;

// ---- packed-word codec (matches pyruntime exactly) ----
function decodeWord(w){w=(w&0xFFFF)>>>0; let u=w+1;
 if(u===65536)return 1.0; if(u===1)return 0.0;
 let e=(u>>12)&0xF, m=u&0xFFF; let x=(e===0)?m/4096:(m|0x1000)/8192; return x*Math.pow(2,e-15);}
function wordsToCoeffs(ws){let d=ws.map(decodeWord);
 return [4*d[0]+d[1], d[1], 4*d[2]+d[3], d[3], 4*d[4]];}
function lerpU16(a,b,frac){a=a&0xFFFF;b=b&0xFFFF;
 let product=Math.fround(Math.fround(b-a)*Math.fround(frac));
 let trunc=Math.trunc(product);
 let delta=(((trunc+0x8000)%0x10000)+0x10000)%0x10000 - 0x8000;
 return (a+delta)&0xFFFF;}
// REAL packed bilinear morph -> coeffs per stage
function morphCoeffs(name,m,qq){const c=BODIES[name];const out=[];
 for(let s=0;s<6;s++){const w=[];for(let k=0;k<5;k++){
   const e0=lerpU16(c.M0_Q0[s][k],c.M100_Q0[s][k],m), e1=lerpU16(c.M0_Q100[s][k],c.M100_Q100[s][k],m);
   w.push(lerpU16(e0,e1,qq));}out.push(wordsToCoeffs(w));}return out;}
function cornerCoeffs(name,label){return BODIES[name][label].map(wordsToCoeffs);}

function stageDb(c,w){const a1=c[2]-2,a2=1-c[3],b0=c[4],b1=(c[0]-2)*c[4],b2=(1-c[1])*c[4];
 const cw=Math.cos(w),sw=Math.sin(w),c2=Math.cos(2*w),s2=Math.sin(2*w);
 const nr=b0+b1*cw+b2*c2, ni=-(b1*sw+b2*s2), dr=1+a1*cw+a2*c2, di=-(a1*sw+a2*s2);
 return 20*Math.log10(Math.max(Math.hypot(nr,ni)/Math.max(Math.hypot(dr,di),1e-9),1e-9));}
function respDb(stages){const N=400,out=[];for(let p=0;p<N;p++){
 const f=20*Math.pow(NYQ/20,p/(N-1)),w=2*Math.PI*f/SR;let db=0;for(const s of stages)db+=stageDb(s,w);out.push([f,db]);}return out;}

const rc=document.getElementById("resp"),rg=rc.getContext("2d");
const DBMIN=-54,DBMAX=18;
function x2(f){return 8+(rc.width-16)*(Math.log(f/20)/Math.log(NYQ/20));}
function y2(db){return 6+(rc.height-12)*(1-(Math.max(DBMIN,Math.min(DBMAX,db))-DBMIN)/(DBMAX-DBMIN));}
function plot(st,col,lw,al){const p=respDb(st);rg.beginPath();
 for(let i=0;i<p.length;i++){const x=x2(p[i][0]),y=y2(p[i][1]);i?rg.lineTo(x,y):rg.moveTo(x,y);}
 rg.globalAlpha=al;rg.strokeStyle=col;rg.lineWidth=lw;rg.stroke();rg.globalAlpha=1;}
function draw(){rg.clearRect(0,0,rc.width,rc.height);
 rg.strokeStyle="#3a5fe0";rg.globalAlpha=.16;rg.lineWidth=1;
 for(const f of [50,100,200,500,1000,2000,5000,10000]){const x=x2(f);rg.beginPath();rg.moveTo(x,0);rg.lineTo(x,rc.height);rg.stroke();}
 rg.globalAlpha=1;rg.strokeStyle="#36c828";const y0=y2(0);rg.beginPath();rg.moveTo(0,y0);rg.lineTo(rc.width,y0);rg.stroke();
 const C={M0_Q0:"#2ec4ff",M100_Q0:"#ffd23e",M0_Q100:"#ff6b6b",M100_Q100:"#9b8cff"};
 for(const l of LAB) plot(cornerCoeffs(cur,l), C[l], 1, .28);
 plot(morphCoeffs(cur,morph,q), "#f6f8ff", 2.2, 1);
 rg.fillStyle="#777";rg.font="9px monospace";
 for(const [f,t] of [[100,"100"],[1000,"1k"],[10000,"10k"]]) rg.fillText(t,x2(f)-6,rc.height-2);
 document.getElementById("readout").textContent=`M ${Math.round(morph*100)}  Q ${Math.round(q*100)}   [${cur}]`;}

const pc=document.getElementById("pad"),pg=pc.getContext("2d");
function drawPad(){pg.fillStyle="#0b0f0e";pg.fillRect(0,0,pc.width,pc.height);
 pg.strokeStyle="#2f5a6e";pg.strokeRect(.5,.5,pc.width-1,pc.height-1);
 pg.strokeStyle="#444";pg.globalAlpha=.4;pg.beginPath();pg.moveTo(pc.width/2,0);pg.lineTo(pc.width/2,pc.height);pg.moveTo(0,pc.height/2);pg.lineTo(pc.width,pc.height/2);pg.stroke();pg.globalAlpha=1;
 const px=morph*pc.width,py=(1-q)*pc.height;pg.fillStyle="#9aef5a";pg.beginPath();pg.arc(px,py,6,0,7);pg.fill();}
function setXY(e){const r=pc.getBoundingClientRect();
 morph=Math.max(0,Math.min(1,(e.clientX-r.left)/pc.width));
 q=Math.max(0,Math.min(1,1-(e.clientY-r.top)/pc.height));
 drawPad();draw();if(playing)rebuildAudio();}
let drag=false;pc.onmousedown=e=>{drag=true;setXY(e);};window.onmousemove=e=>{if(drag)setXY(e);};window.onmouseup=()=>{drag=false;};

// ---- word bench ----
const tabsEl=document.getElementById("tabs"),gridEl=document.getElementById("grid");
function buildTabs(){tabsEl.innerHTML="";LAB.forEach((l,i)=>{const d=document.createElement("div");
 d.className="tab"+(i===tab?" on":"");d.textContent=l;d.onclick=()=>{tab=i;buildTabs();buildGrid();};tabsEl.appendChild(d);});}
function buildGrid(){const label=LAB[tab];const words=BODIES[cur][label];
 let h='<table><tr><th></th><th>w0 low</th><th>w1 notch</th><th>w2 pole</th><th>w3 sharp</th><th>w4 level</th></tr>';
 for(let s=0;s<6;s++){h+=`<tr><td class="stg">stg ${s}</td>`;
  for(let k=0;k<5;k++) h+=`<td><input class="w" id="w_${s}_${k}" value="${words[s][k].toString(16).toUpperCase().padStart(4,'0')}"></td>`;
  h+='</tr>';}
 h+='</table>';gridEl.innerHTML=h;
 for(let s=0;s<6;s++)for(let k=0;k<5;k++){const inp=document.getElementById(`w_${s}_${k}`);
  inp.oninput=()=>{let v=parseInt(inp.value,16);if(isNaN(v))return;v=v&0xFFFF;
   if(document.getElementById("link").checked){LAB.forEach(L=>BODIES[cur][L][s][k]=v);}
   else BODIES[cur][label][s][k]=v;
   draw();if(playing)rebuildAudio();};}}

const sel=document.getElementById("body");
for(const n of Object.keys(BODIES)){const o=document.createElement("option");o.value=n;o.textContent=n;sel.appendChild(o);}
sel.onchange=()=>{cur=sel.value;buildGrid();draw();if(playing)rebuildAudio();};

document.getElementById("save").onclick=()=>{
 let t=`# ${cur} -- edited in word bench\nformat = "packed-body-v1"\nname = "${cur}"\nboost = 1.0\nauthoring_sample_rate_hz = 39062.5\n\n`;
 for(const l of LAB){t+=`[corner.${l}]\nwords = [\n`;
  for(const row of BODIES[cur][l]) t+="  ["+row.map(v=>"0x"+(v&0xFFFF).toString(16).toUpperCase().padStart(4,'0')).join(", ")+"],\n";
  t+="]\n\n";}
 const b=new Blob([t],{type:"text/plain"});const a=document.createElement("a");
 a.href=URL.createObjectURL(b);a.download=cur+".packed.toml";a.click();};

// ---- audio ----
function makeNoise(ctx){const n=ctx.sampleRate*2,buf=ctx.createBuffer(1,n,ctx.sampleRate),d=buf.getChannelData(0);
 let a=0,b=0,c=0;for(let i=0;i<n;i++){const w=Math.random()*2-1;a=.99*a+w*.05;b=.95*b+w*.07;c=.8*c+w*.12;d[i]=(a+b+c+w*.2)*.35;}return buf;}
function rebuildAudio(){if(!audio)return;if(srcGain){try{srcGain.disconnect();}catch(e){}}
 const stages=morphCoeffs(cur,morph,q);const src=audio.createBufferSource();src.buffer=noiseBuf;src.loop=true;let node=src;
 for(const c of stages){const b0=c[4],b1=(c[0]-2)*c[4],b2=(1-c[1])*c[4],a1=c[2]-2,a2=1-c[3];
  try{const f=audio.createIIRFilter([b0,b1,b2],[1,a1,a2]);node.connect(f);node=f;}catch(e){}}
 const g=audio.createGain();g.gain.value=0.25;node.connect(g);g.connect(audio.destination);src.start();
 srcGain={disconnect(){src.stop();g.disconnect();}};}
document.getElementById("play").onclick=function(){
 if(!audio){audio=new(window.AudioContext||window.webkitAudioContext)();noiseBuf=makeNoise(audio);}
 if(playing){if(srcGain)srcGain.disconnect();playing=false;this.textContent="▶ pink noise";}
 else{playing=true;rebuildAudio();this.textContent="■ stop";}};

buildTabs();buildGrid();drawPad();draw();
</script></body></html>"""


if __name__ == "__main__":
    main()
