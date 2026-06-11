// df2 Fitter — draw a target magnitude shape, solve 6 pole+zero stages to hit it, pack to 240 bytes.
// You curate (draw); the script crunches the math (System Identification, the E-mu way).
import {packWithCore, bodyHex} from "./pack-core.js";
import {downloadBody, packedDb, wordsFromBytes} from "./packed.js";

const SR=39062.5, F_LO=30, F_HI=SR/2, ZE=SR*.49, DB_LO=-30, DB_HI=30, N=256;
const WASM_URL="wasm/forge_web_wasm.wasm?v=fitter";
const $=id=>document.getElementById(id);
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const setStatus=t=>{ $("status").textContent=t; };
const canvas=$("plot"), ctx=canvas.getContext("2d");

// target curve: dB at N log-spaced freqs
const FREQ=Array.from({length:N},(_,i)=>Math.exp(Math.log(F_LO)+i/(N-1)*(Math.log(F_HI)-Math.log(F_LO))));
const state={ name:"fitted_body", target:new Array(N).fill(0), bytes:null, words:null, src:2, playing:false, drive:0.4, lastBin:null };

// ---- fit: target dB -> 6 pole+zero stages ----
const rPeak =db=>clamp(1-Math.pow(10,-clamp(db,2,40)/20)/1.4, 0.80, 0.9985);
const rNotch=db=>clamp(1-Math.pow(10,-clamp(-db,2,40)/20)/1.4, 0.80, 0.9970);
function extrema(wantMax,n,lo,hi){
  const out=[]; const t=state.target;
  for(let i=2;i<N-2;i++){ const f=FREQ[i]; if(f<lo||f>hi) continue;
    const seg=t.slice(i-2,i+3), c=t[i], mx=Math.max(...seg), mn=Math.min(...seg);
    if((wantMax && c===mx && c>mn+1.0) || (!wantMax && c===mn && c<mx-1.0)) out.push({hz:f,db:c}); }
  out.sort((a,b)=>wantMax? b.db-a.db : a.db-b.db);
  return out.slice(0,n);
}
function fit(){
  const base=[...state.target].sort((a,b)=>a-b)[N>>1]; // median
  const peaks=extrema(true,6,F_LO,ZE), notch=extrema(false,6,60,ZE);
  const sections=[];
  for(let k=0;k<6;k++){
    const p = peaks[k] || {hz:1000*(k+1), db:base+3};
    const pr = rPeak(p.db-base);
    let zf, zr;
    if(notch.length){ const z=notch.reduce((a,b)=>Math.abs(Math.log2(b.hz/p.hz))<Math.abs(Math.log2(a.hz/p.hz))?b:a); zf=z.hz; zr=rNotch(z.db-base); }
    else { zf=Math.min(p.hz*1.6,ZE); zr=0.55; }
    sections.push({on:true, hz:clamp(p.hz,F_LO,ZE), r:pr, gainDb:0, cutOn:true, cutHz:clamp(zf,F_LO,ZE), cutDepth:zr});
  }
  return sections;
}
async function runFit(){
  const secs=fit();
  const corners=[0,1,2,3].map(()=>secs.map(s=>({...s, gain:Math.pow(10,s.gainDb/20)}))); // static: 4 corners alike
  state.bytes=await packWithCore(corners);
  state.words=wordsFromBytes(state.bytes);
  if(anode) anode.port.postMessage({body:state.bytes.buffer.slice(0)});
  // fit error
  let e=0,m=0; for(let i=0;i<N;i++){ const d=packedDb(state.words,0,0,FREQ[i]); e+=(state.target[i]-d); }
  const off=e/N; let s=0; for(let i=0;i<N;i++){ const d=packedDb(state.words,0,0,FREQ[i])+off; s+=(state.target[i]-d)**2; }
  const rms=Math.sqrt(s/N);
  $("stages").textContent="6 stages fitted:\n"+secs.map((s,i)=>`S${i+1}  pole ${Math.round(s.hz)}Hz r=${s.r.toFixed(3)}   zero ${Math.round(s.cutHz)}Hz rz=${s.cutDepth.toFixed(3)}`).join("\n");
  setStatus(`fit RMS ${rms.toFixed(1)} dB · ${state.bytes.length} bytes`);
  draw();
}

// ---- canvas ----
function fitCanvas(){ const r=canvas.getBoundingClientRect(), dpr=Math.min(devicePixelRatio||1,2);
  const w=Math.max(320,r.width*dpr|0), h=Math.max(220,r.height*dpr|0); if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;} }
const xF=f=>48+(Math.log(clamp(f,F_LO,F_HI))-Math.log(F_LO))/(Math.log(F_HI)-Math.log(F_LO))*(canvas.width-66);
const fX=x=>Math.exp(Math.log(F_LO)+clamp((x-48)/(canvas.width-66),0,1)*(Math.log(F_HI)-Math.log(F_LO)));
const yF=db=>16+(1-(clamp(db,DB_LO,DB_HI)-DB_LO)/(DB_HI-DB_LO))*(canvas.height-40);
const yDb=y=>DB_LO+(1-clamp((y-16)/(canvas.height-40),0,1))*(DB_HI-DB_LO);
const binOf=f=>clamp(Math.round((Math.log(clamp(f,F_LO,F_HI))-Math.log(F_LO))/(Math.log(F_HI)-Math.log(F_LO))*(N-1)),0,N-1);
function pt(e){ const r=canvas.getBoundingClientRect(); return {x:(e.clientX-r.left)*canvas.width/r.width, y:(e.clientY-r.top)*canvas.height/r.height}; }
function draw(){
  fitCanvas(); const w=canvas.width,h=canvas.height;
  ctx.fillStyle="#f7f3eb"; ctx.fillRect(0,0,w,h); ctx.strokeStyle="#e0d7c8"; ctx.lineWidth=1; ctx.font="12px Consolas"; ctx.fillStyle="#81786c";
  for(const db of[24,12,0,-12,-24]){ const y=yF(db); ctx.beginPath();ctx.moveTo(48,y);ctx.lineTo(w-14,y);ctx.stroke(); ctx.textAlign="right";ctx.fillText((db>0?"+":"")+db,42,y+4); }
  for(const f of[50,100,200,500,1000,2000,5000,10000]){ const x=xF(f); ctx.beginPath();ctx.moveTo(x,14);ctx.lineTo(x,h-22);ctx.stroke(); ctx.textAlign="center";ctx.fillText(f>=1000?f/1000+"k":f,x,h-6); }
  // target (what you draw)
  ctx.strokeStyle="#3b6fb0"; ctx.lineWidth=2.4; ctx.beginPath();
  for(let i=0;i<N;i++){ const x=xF(FREQ[i]),y=yF(state.target[i]); i?ctx.lineTo(x,y):ctx.moveTo(x,y); } ctx.stroke();
  // fitted (what 6 stages produce)
  if(state.words){ ctx.strokeStyle="#d2452f"; ctx.lineWidth=1.6; ctx.beginPath();
    let off=0; for(let i=0;i<N;i++) off+=state.target[i]-packedDb(state.words,0,0,FREQ[i]); off/=N;
    for(let i=0;i<N;i++){ const x=xF(FREQ[i]),y=yF(packedDb(state.words,0,0,FREQ[i])+off); i?ctx.lineTo(x,y):ctx.moveTo(x,y);} ctx.stroke(); }
}
addEventListener("resize",draw);

// draw the target by dragging
let drawing=false;
function paint(p){ const f=fX(p.x), db=yDb(p.y), b=binOf(f);
  if(state.lastBin!=null && state.lastBin!==b){ const a=Math.min(state.lastBin,b), z=Math.max(state.lastBin,b);
    for(let i=a;i<=z;i++) state.target[i]=db; } else state.target[b]=db; state.lastBin=b; draw(); }
canvas.addEventListener("pointerdown",e=>{ drawing=true; state.lastBin=null; canvas.setPointerCapture(e.pointerId); paint(pt(e)); });
canvas.addEventListener("pointermove",e=>{ if(drawing) paint(pt(e)); });
canvas.addEventListener("pointerup",()=>{ drawing=false; state.lastBin=null; });
canvas.addEventListener("pointercancel",()=>{ drawing=false; });

// ---- audio (drive chain) ----
let actx=null, anode=null;
function pushParams(){ if(!anode) return; const d=state.drive; anode.port.postMessage({params:{morph:0,q:0,agc:4+4*d,slam:0.25*d*d,wide:0,inputGain:1,makeup:1.5+2.5*d}}); }
async function startAudio(){
  actx=new (AudioContext||webkitAudioContext)(); const wasm=await (await fetch(WASM_URL)).arrayBuffer();
  await actx.audioWorklet.addModule("js/forge-worklet.js");
  anode=new AudioWorkletNode(actx,"forge-processor",{numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[2],processorOptions:{wasm,body:state.bytes?state.bytes.buffer.slice(0):null,src:state.src}});
  anode.port.onmessage=e=>{ if(e.data.ready){pushParams(); if(state.playing)anode.port.postMessage({playing:true});}
    if(e.data.level!=null){ const m=$("meter"); m.firstElementChild.style.height=Math.min(100,e.data.level*140)+"%"; m.classList.toggle("flood",e.data.peak>0.985);} };
  anode.connect(actx.destination);
}
async function toggleAudio(){ try{ if(!actx) await startAudio(); if(actx.state==="suspended")await actx.resume();
  state.playing=!state.playing; anode.port.postMessage({playing:state.playing}); $("play").classList.toggle("on",state.playing); $("play").textContent=state.playing?"❚❚ stop":"▶ play";
}catch(err){ setStatus("audio failed: "+err.message); } }

// ---- wiring ----
$("fitBtn").onclick=()=>runFit().catch(err=>setStatus("fit failed: "+err.message));
$("clearBtn").onclick=()=>{ state.target.fill(0); state.words=null; state.bytes=null; $("stages").textContent="draw a curve, then fit"; draw(); };
$("flatBtn").onclick=()=>{ for(let i=0;i<N;i++) state.target[i]=FREQ[i]<150?4:(FREQ[i]>6000?-6:0); draw(); };
$("play").onclick=toggleAudio;
document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{ document.querySelectorAll(".chip").forEach(x=>x.classList.remove("on")); c.classList.add("on"); state.src=+c.dataset.src; if(anode)anode.port.postMessage({src:state.src}); });
$("saveBtn").onclick=()=>{ if(!state.bytes){ setStatus("fit first"); return;} downloadBody(`${state.name}.body240`,bodyHex(state.bytes)); setStatus(`saved ${state.name}.body240`); };
$("nameInput").oninput=e=>{ state.name=e.target.value.trim()||"untitled"; };

$("flatBtn").onclick(); setStatus("draw a shape and hit ⌖ fit");
