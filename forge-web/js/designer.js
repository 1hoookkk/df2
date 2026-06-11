// df2 Filter Designer — section-level, octave-native. Each lane is a TYPED section placed on a real
// rail (start Hz) that MOVES in octaves (the morph). Compiles to a 240-byte body via WASM trench-core
// (the same encoder the DLL uses); the iconic corridor is a live honesty gauge, not a gate.
import {packWithCore, bodyHex} from "./pack-core.js";
import {downloadBody, packedDb, wordsFromBytes, wordsAt, stageWordsToKernel, kernelToBiquad} from "./packed.js";

const SR=39062.5, F_LO=20, F_HI=SR/2, ZERO_END=SR*.49, DB_LO=-30, DB_HI=36;
const WASM_URL="wasm/forge_web_wasm.wasm?v=designer";
const $=id=>document.getElementById(id);
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const hzText=v=>v>=1000?`${(v/1000).toFixed(v>=10000?1:2)}k`:`${Math.round(v)}`;
const setStatus=t=>{ $("status").textContent=t; };

// real rails — formants (Peterson-Barney) + body/mode anchors. start Hz snaps to the nearest.
const RAILS=[55,70,90,110,150,200,270,300,420,530,640,660,730,840,870,1090,1190,1500,1720,1840,2240,2290,2440,3010,3300,4200,5500,7000,9000,12000];
const snap=hz=>RAILS.reduce((a,b)=>Math.abs(b-hz)<Math.abs(a-hz)?b:a, RAILS[0]);

// section types -> how a lane expands to a pole+zero pair (the serial-cascade-safe primitives).
// each returns the per-corner relationship; the lane carries start/move/gain/radii.
const TYPES={
  body:   {label:"BODY",   zOff:1.58, held:true,  loQ:0.93,  hiQ:0.965, zDepth:0.55, gain:3},   // flat-top low-shelf-ish
  leader: {label:"LEADER", zOff:-0.5, held:false, loQ:0.965, hiQ:0.988, zDepth:0.96, gain:0},   // the multi-oct sweep
  res:    {label:"res",    zOff:0.5,  held:false, loQ:0.962, hiQ:0.986, zDepth:0.94, gain:0},
  bite:   {label:"BITE",   zOff:0.6,  held:false, loQ:0.96,  hiQ:0.986, zDepth:0.93, gain:0},
  canyon: {label:"CANYON", zOff:0.0,  held:false, loQ:0.90,  hiQ:0.95,  zDepth:0.985,gain:0},   // zero does the work
  air:    {label:"AIR",    zOff:1.0,  held:true,  loQ:0.92,  hiQ:0.95,  zDepth:0.60, gain:-10},  // high trim
};

// a starting iconic-ish body: held shelf + leader + 2 res + bite + air
function defaultLanes(){
  return [
    {type:"body",   startHz:70,   moveOct:0.0, gain:3,   zMove:0.0},
    {type:"leader", startHz:150,  moveOct:3.4, gain:0,   zMove:1.2},
    {type:"res",    startHz:300,  moveOct:1.2, gain:0,   zMove:0.6},
    {type:"res",    startHz:730,  moveOct:1.0, gain:0,   zMove:0.5},
    {type:"bite",   startHz:1840, moveOct:0.6, gain:0,   zMove:0.4},
    {type:"air",    startHz:4200, moveOct:0.0, gain:-10, zMove:0.0},
  ];
}

const state={ name:"designed_body", lanes:defaultLanes(), m:0, drive:0.40, src:2, playing:false,
              bytes:null, hex:"", words:null };

// ---- compile: lane -> 4 corner stages -> packWithCore ----
function laneCorners(l){
  const T=TYPES[l.type];
  const poleA=clamp(l.startHz,F_LO,ZERO_END);
  const poleB=clamp(poleA*2**(T.held?0:l.moveOct),F_LO,ZERO_END);
  const zA=clamp(poleA*2**T.zOff,F_LO,ZERO_END);
  const zB=clamp(zA*2**(T.held?0:l.zMove),F_LO,ZERO_END);
  const mk=(hz,r,zhz)=>({on:true,hz,r,gainDb:l.gain,cutOn:T.zDepth>0.05,cutHz:zhz,cutDepth:T.zDepth});
  return [ mk(poleA,T.loQ,zA),  mk(poleB,T.loQ,zB),  mk(poleA,T.hiQ,zA),  mk(poleB,T.hiQ,zB) ]; // C0..C3
}
function packModel(){
  const cols=[[],[],[],[]];
  for(const l of state.lanes){ const c=laneCorners(l); for(let i=0;i<4;i++) cols[i].push({...c[i],gain:Math.pow(10,c[i].gainDb/20)}); }
  return cols;
}
async function repack(soft){
  state.bytes=await packWithCore(packModel());
  state.hex=bodyHex(state.bytes);
  state.words=wordsFromBytes(state.bytes);
  if(anode) anode.port.postMessage({body:state.bytes.buffer.slice(0)});
  if(soft){ drawPlot(); renderGauge(); } else render();
  setStatus(`${state.hex.length/2} bytes`);
}

// ---- corridor metrics (in JS — the live gauge) ----
function liveDb(f,m,q){ return state.words?packedDb(state.words,m,q,f):0; }
function worstRadius(){
  let w=0; for(let mi=0;mi<=8;mi++)for(let qi=0;qi<=8;qi++){
    for(const row of wordsAt(state.words,mi/8,qi/8)){ const bq=kernelToBiquad(stageWordsToKernel(row));
      const d=bq[3]*bq[3]-4*bq[4]; const r=d<0?Math.sqrt(Math.max(0,bq[4])):Math.max(Math.abs((-bq[3]+Math.sqrt(d))/2),Math.abs((-bq[3]-Math.sqrt(d))/2));
      w=Math.max(w,r);} } return w;
}
function curveAt(m,q){ const a=[]; for(let i=0;i<200;i++){ const f=Math.exp(Math.log(40)+i/199*(Math.log(ZERO_END)-Math.log(40))); a.push(liveDb(f,m,q)); } return a; }
function metrics(){
  const c=curveAt(0.5,0.5); const span=Math.max(...c)-Math.min(...c);
  const a=curveAt(0,0), b=curveAt(1,0); let s=0; for(let i=0;i<a.length;i++) s+=(b[i]-a[i])**2; const morph=Math.sqrt(s/a.length);
  let leadP=0, leadZ=0; for(const l of state.lanes){ if(!TYPES[l.type].held){ leadP=Math.max(leadP,Math.abs(l.moveOct)); leadZ=Math.max(leadZ,Math.abs(l.zMove)); } }
  return { maxR:worstRadius(), span, morph, leadP, leadZ };
}
const GAUGE=[
  {key:"maxR",  label:"max radius", fmt:v=>v.toFixed(4), lo:0.983, hi:0.9999, want:[0.983,0.990], max:1},
  {key:"span",  label:"span dB",    fmt:v=>v.toFixed(0), lo:40,    want:[40,150],  max:150},
  {key:"morph", label:"morph dB",   fmt:v=>v.toFixed(1), lo:8,     want:[8,60],    max:60},
  {key:"leadP", label:"leader oct", fmt:v=>v.toFixed(2), lo:0.9,   want:[0.9,5.6], max:5.6},
  {key:"leadZ", label:"canyon oct", fmt:v=>v.toFixed(2), lo:0.9,   want:[0.9,5.6], max:5.6},
];
function renderGauge(){
  const m=metrics(); let allIn=true;
  $("gaugeBody").innerHTML=GAUGE.map(g=>{
    const v=m[g.key]; const inRange=v>=g.want[0] && v<=g.want[1]; if(!inRange) allIn=false;
    const pct=clamp(v/g.max*100,2,100);
    return `<div class="grow ${inRange?"":"bad"}"><span>${g.label}</span><div class="bar"><i style="width:${pct}%"></i></div><span>${g.fmt(v)}</span></div>`;
  }).join("");
  const vd=$("verdict"); vd.textContent=allIn?"IN CORRIDOR":"out of corridor";
  vd.className="verdict "+(allIn?"in":"out");
  $("light").className="light"+(m.maxR>=1?" bad":m.maxR>=0.9995?" warn":"");
}

// ---- plot ----
const canvas=$("plot"), ctx=canvas.getContext("2d");
function fitCanvas(){ const r=canvas.getBoundingClientRect(), dpr=Math.min(devicePixelRatio||1,2);
  const w=Math.max(320,r.width*dpr|0), h=Math.max(220,r.height*dpr|0); if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;} }
const xF=(f,w)=>48+(Math.log(clamp(f,F_LO,F_HI))-Math.log(F_LO))/(Math.log(F_HI)-Math.log(F_LO))*(w-66);
const yF=(db,h)=>16+(1-(clamp(db,DB_LO,DB_HI)-DB_LO)/(DB_HI-DB_LO))*(h-44);
function drawCurve(m,q,col,wd,dash){ const w=canvas.width,h=canvas.height; ctx.save(); if(dash)ctx.setLineDash(dash);
  ctx.strokeStyle=col; ctx.lineWidth=wd; ctx.beginPath();
  for(let i=0;i<480;i++){ const t=i/479, f=Math.exp(Math.log(F_LO)+t*(Math.log(F_HI)-Math.log(F_LO))); const x=xF(f,w),y=yF(liveDb(f,m,q),h); i?ctx.lineTo(x,y):ctx.moveTo(x,y);} ctx.stroke(); ctx.restore(); }
function drawPlot(){ fitCanvas(); const w=canvas.width,h=canvas.height;
  ctx.fillStyle="#f7f3eb"; ctx.fillRect(0,0,w,h); ctx.strokeStyle="#e0d7c8"; ctx.lineWidth=1; ctx.font="12px Consolas"; ctx.fillStyle="#81786c";
  for(const db of[24,12,0,-12,-24]){ const y=yF(db,h); ctx.beginPath();ctx.moveTo(48,y);ctx.lineTo(w-18,y);ctx.stroke(); ctx.textAlign="right";ctx.fillText((db>0?"+":"")+db,42,y+4);}
  for(const f of[50,100,200,500,1000,2000,5000,10000]){ const x=xF(f,w); ctx.beginPath();ctx.moveTo(x,16);ctx.lineTo(x,h-26);ctx.stroke(); ctx.textAlign="center";ctx.fillText(f>=1000?f/1000+"k":f,x,h-8);}
  drawCurve(0,0,"rgba(63,123,176,.30)",1.2); drawCurve(1,0,"rgba(210,75,63,.30)",1.2);  // frame A / B at loQ
  drawCurve(state.m,0,"#15130f",2.6);  // live morph
}
addEventListener("resize",drawPlot);

// ---- lane UI ----
function renderLanes(){
  $("lanes").innerHTML=state.lanes.map((l,i)=>{
    const T=TYPES[l.type], held=T.held;
    const opts=Object.keys(TYPES).map(k=>`<option value="${k}" ${k===l.type?"selected":""}>${TYPES[k].label}</option>`).join("");
    return `<div class="lane ${l.type==="leader"?"leader":""}" data-i="${i}">
      <b>L${i}</b>
      <select data-f="type">${opts}</select>
      <label><span>start Hz (rail)</span><input data-f="startHz" type="range" min="40" max="12000" value="${l.startHz}"><small>${hzText(l.startHz)}</small></label>
      <label><span>${held?"held":"move oct"}</span><input data-f="moveOct" type="range" min="-4.5" max="4.5" step="0.05" value="${l.moveOct}" ${held?"disabled":""}><small>${held?"—":(l.moveOct>=0?"+":"")+l.moveOct.toFixed(2)}</small></label>
      <label><span>gain</span><input data-f="gain" type="range" min="-18" max="12" step="0.5" value="${l.gain}"><small>${l.gain>0?"+":""}${l.gain}</small></label>
    </div>`;
  }).join("");
  $("lanes").querySelectorAll(".lane").forEach(el=>{
    const i=+el.dataset.i;
    el.querySelector("[data-f=type]").onchange=async e=>{ state.lanes[i].type=e.target.value; await repack(); };
    el.querySelector("[data-f=startHz]").oninput=async e=>{ state.lanes[i].startHz=snap(+e.target.value); await repack(true); };
    el.querySelector("[data-f=startHz]").onchange=()=>renderLanes();
    const mo=el.querySelector("[data-f=moveOct]"); if(mo) mo.oninput=async e=>{ state.lanes[i].moveOct=+e.target.value; el.querySelector("[data-f=moveOct]").nextElementSibling.textContent=(state.lanes[i].moveOct>=0?"+":"")+state.lanes[i].moveOct.toFixed(2); await repack(true); };
    el.querySelector("[data-f=gain]").oninput=async e=>{ state.lanes[i].gain=+e.target.value; e.target.nextElementSibling.textContent=(state.lanes[i].gain>0?"+":"")+state.lanes[i].gain; await repack(true); };
  });
}
function render(){ renderLanes(); drawPlot(); renderGauge(); $("mOut").textContent=Math.round(state.m*100); $("dOut").textContent=Math.round(state.drive*100); }

// ---- propose: randomize within the corridor (lightweight in-browser co-pilot) ----
function proposeInCorridor(){
  const rnd=(a,b)=>a+Math.random()*(b-a);
  const leaderStart=snap(rnd(110,400));
  state.lanes=[
    {type:"body",   startHz:snap(rnd(55,110)),  moveOct:0,             gain:rnd(1,6)|0, zMove:0},
    {type:"leader", startHz:leaderStart,         moveOct:rnd(2.4,4.2),  gain:0,          zMove:rnd(1.0,2.2)},
    {type:"res",    startHz:snap(rnd(220,520)),  moveOct:rnd(0.8,1.6),  gain:0,          zMove:rnd(0.5,1.1)},
    {type:"res",    startHz:snap(rnd(560,1200)), moveOct:rnd(0.7,1.4),  gain:0,          zMove:rnd(0.4,1.0)},
    {type:"bite",   startHz:snap(rnd(1500,3300)),moveOct:rnd(0.4,1.1),  gain:0,          zMove:rnd(0.4,0.9)},
    {type:"air",    startHz:snap(rnd(4000,9000)),moveOct:0,             gain:-(rnd(6,14)|0), zMove:0},
  ];
}

// ---- audio: worklet drive chain (DRIVE = the second knob) ----
let actx=null, anode=null;
function driveParams(){ const d=clamp(state.drive,0,1); return {agc:4+4*d, slam:0.25*d*d, wide:0, inputGain:1, makeup:1.5+2.5*d}; }
function pushParams(){ if(!anode) return; const p=driveParams(); anode.port.postMessage({params:{morph:state.m,q:0,agc:p.agc,slam:p.slam,wide:p.wide,inputGain:p.inputGain,makeup:p.makeup}}); }
async function startAudio(){
  actx=new (AudioContext||webkitAudioContext)();
  const wasm=await (await fetch(WASM_URL)).arrayBuffer();
  await actx.audioWorklet.addModule("js/forge-worklet.js");
  anode=new AudioWorkletNode(actx,"forge-processor",{numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[2],
    processorOptions:{wasm,body:state.bytes?state.bytes.buffer.slice(0):null,src:state.src}});
  anode.port.onmessage=e=>{ if(e.data.ready){pushParams(); if(state.playing) anode.port.postMessage({playing:true});}
    if(e.data.level!=null){ const m=$("meter"); m.firstElementChild.style.height=Math.min(100,e.data.level*140)+"%"; m.classList.toggle("flood",e.data.peak>0.985);} };
  anode.connect(actx.destination);
}
async function toggleAudio(){ try{ if(!actx) await startAudio(); if(actx.state==="suspended") await actx.resume();
  state.playing=!state.playing; anode.port.postMessage({playing:state.playing});
  $("play").classList.toggle("on",state.playing); $("play").textContent=state.playing?"❚❚ stop":"▶ play";
}catch(err){ setStatus("audio failed: "+err.message); } }

// ---- wiring ----
$("morph").oninput=e=>{ state.m=+e.target.value/100; pushParams(); $("mOut").textContent=e.target.value; drawPlot(); };
$("drive").oninput=e=>{ state.drive=+e.target.value/100; pushParams(); $("dOut").textContent=e.target.value; };
$("play").onclick=toggleAudio;
document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{ document.querySelectorAll(".chip").forEach(x=>x.classList.remove("on")); c.classList.add("on"); state.src=+c.dataset.src; if(anode) anode.port.postMessage({src:state.src}); });
$("proposeBtn").onclick=async()=>{ proposeInCorridor(); await repack(); setStatus("proposed a candidate in the corridor — audition, then shape it"); };
$("saveBtn").onclick=()=>{ downloadBody(`${state.name}.body240`,state.hex); setStatus(`saved ${state.name}.body240`); };
$("nameInput").oninput=e=>{ state.name=e.target.value.trim()||"untitled"; };

repack().catch(err=>setStatus("pack failed: "+err.message));
