// df2 Morph Designer — E-mu style. Per STAGE: SHAPE + FREQ/Q/GAIN at LO and HI morph (= Frame A/B).
// Typed shapes hide the pole-zero math; the compiler computes safe coefficients. 2 frames -> 4 corners
// via the Q-rule (FilRes tightens every stage's radius). No pole sliders, no cascade math by hand.
import {packWithCore, bodyHex} from "./pack-core.js";
import {downloadBody, packedDb, wordsFromBytes} from "./packed.js";

const SR=39062.5, F_LO=30, F_HI=SR/2, ZE=SR*.49, DB_LO=-30, DB_HI=30;
const WASM_URL="wasm/forge_web_wasm.wasm?v=md";
const $=id=>document.getElementById(id);
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const setStatus=t=>{ $("status").textContent=t; };

const QBOOST=2.6;   // FilRes range: hiQ = loQ * QBOOST (tightens radius toward the rim)
function defStages(){           // a Hedz-spirit oo->ee default
  return [
    {shape:"lowshelf", loFreq:120, loQ:1, hiFreq:120, hiQ:1, gain:5},   // body (held)
    {shape:"peak", loFreq:400, loQ:4, hiFreq:300, hiQ:4, gain:8},       // F1
    {shape:"peak", loFreq:900, loQ:5, hiFreq:2300, hiQ:6, gain:11},     // F2 leader (glides)
    {shape:"peak", loFreq:2200,loQ:5, hiFreq:3000, hiQ:6, gain:8},      // F3
    {shape:"notch",loFreq:600, loQ:3, hiFreq:850, hiQ:3, gain:0},       // cavity
    {shape:"highshelf",loFreq:6000,loQ:1,hiFreq:6000,hiQ:1,gain:-6},    // air
  ];
}
const state={ name:"morph_body", stages:defStages(), cur:0, m:0, drive:0.4, src:2, playing:false, bytes:null, words:null };

// ---- RBJ shape -> biquad ----
function rbj(shape,f,q,gainDb){
  f=clamp(f,30,ZE); q=Math.max(q,0.3); const w=2*Math.PI*f/SR,c=Math.cos(w),s=Math.sin(w),al=s/(2*q),A=Math.pow(10,gainDb/40);
  let b0,b1,b2,a0,a1,a2;
  switch(shape){
    case"LP": b0=(1-c)/2;b1=1-c;b2=(1-c)/2;a0=1+al;a1=-2*c;a2=1-al;break;
    case"HP": b0=(1+c)/2;b1=-(1+c);b2=(1+c)/2;a0=1+al;a1=-2*c;a2=1-al;break;
    case"BP": b0=al;b1=0;b2=-al;a0=1+al;a1=-2*c;a2=1-al;break;
    case"peak": b0=1+al*A;b1=-2*c;b2=1-al*A;a0=1+al/A;a1=-2*c;a2=1-al/A;break;
    case"notch": b0=1;b1=-2*c;b2=1;a0=1+al;a1=-2*c;a2=1-al;break;
    case"lowshelf":{const sq=2*Math.sqrt(A)*al;b0=A*((A+1)-(A-1)*c+sq);b1=2*A*((A-1)-(A+1)*c);b2=A*((A+1)-(A-1)*c-sq);a0=(A+1)+(A-1)*c+sq;a1=-2*((A-1)+(A+1)*c);a2=(A+1)+(A-1)*c-sq;break;}
    case"highshelf":{const sq=2*Math.sqrt(A)*al;b0=A*((A+1)+(A-1)*c+sq);b1=-2*A*((A-1)+(A+1)*c);b2=A*((A+1)+(A-1)*c-sq);a0=(A+1)-(A-1)*c+sq;a1=2*((A-1)-(A+1)*c);a2=(A+1)-(A-1)*c-sq;break;}
    default:return null;
  }
  let bq=[b0/a0,b1/a0,b2/a0,a1/a0,a2/a0];
  if(["LP","HP","BP","notch"].includes(shape) && gainDb){ const g=Math.pow(10,gainDb/20); bq=[bq[0]*g,bq[1]*g,bq[2]*g,bq[3],bq[4]]; } // gain = level for non-EQ shapes
  return bq;
}
// biquad -> the section's pole+zero+gain (the packer's format)
function pz(bq){
  const [b0,b1,b2,a1,a2]=bq;
  let pr=clamp(Math.sqrt(Math.max(a2,1e-9)),0.5,0.99940);
  const pf=Math.acos(clamp(-a1/(2*pr),-1,1))*SR/(2*Math.PI);
  const z1=b1/b0, z2=b2/b0; let zr=clamp(Math.sqrt(Math.max(Math.abs(z2),1e-9)),0,0.99940);
  const zf=Math.acos(clamp(-z1/(2*Math.max(zr,1e-6)),-1,1))*SR/(2*Math.PI);
  return {on:true, hz:clamp(pf||500,30,ZE), r:pr, gainDb:20*Math.log10(Math.abs(b0)+1e-9), cutOn:true, cutHz:clamp(zf||ZE,30,ZE), cutDepth:zr};
}
function section(st, frameB, qhi){
  if(st.shape==="off") return {on:false,hz:1000,r:0.7,gainDb:0,cutOn:false,cutHz:1000,cutDepth:0};
  const f=frameB? st.hiFreq : st.loFreq, q=(frameB? st.hiQ : st.loQ)*(qhi?QBOOST:1);
  return pz(rbj(st.shape, f, q, st.gain));
}
async function repack(){
  const corners=[[0,0],[1,0],[0,1],[1,1]].map(([b,q])=>state.stages.map(st=>{ const s=section(st,b,q); return {...s,gain:Math.pow(10,s.gainDb/20)}; }));
  state.bytes=await packWithCore(corners);
  state.words=wordsFromBytes(state.bytes);
  if(anode) anode.port.postMessage({body:state.bytes.buffer.slice(0)});
  draw(); setStatus(`${state.bytes.length} bytes`);
}

// ---- graph ----
const canvas=$("plot"), ctx=canvas.getContext("2d");
function fitC(){ const r=canvas.getBoundingClientRect(),d=Math.min(devicePixelRatio||1,2); const w=Math.max(320,r.width*d|0),h=Math.max(120,r.height*d|0); if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;} }
const xF=f=>40+(Math.log(clamp(f,F_LO,F_HI))-Math.log(F_LO))/(Math.log(F_HI)-Math.log(F_LO))*(canvas.width-50);
const yF=db=>10+(1-(clamp(db,DB_LO,DB_HI)-DB_LO)/(DB_HI-DB_LO))*(canvas.height-20);
function curve(m,q,col,wd){ const w=canvas.width; ctx.strokeStyle=col; ctx.lineWidth=wd; ctx.beginPath();
  for(let i=0;i<360;i++){ const t=i/359,f=Math.exp(Math.log(F_LO)+t*(Math.log(F_HI)-Math.log(F_LO))); const x=xF(f),y=yF(state.words?packedDb(state.words,m,q,f):0); i?ctx.lineTo(x,y):ctx.moveTo(x,y);} ctx.stroke(); }
function draw(){ fitC(); const w=canvas.width,h=canvas.height; ctx.fillStyle="#0f1a12"; ctx.fillRect(0,0,w,h);
  ctx.strokeStyle="#1f3a28"; ctx.lineWidth=1; for(const db of[12,0,-12]){const y=yF(db);ctx.beginPath();ctx.moveTo(40,y);ctx.lineTo(w-10,y);ctx.stroke();}
  for(const f of[100,1000,10000]){const x=xF(f);ctx.beginPath();ctx.moveTo(x,10);ctx.lineTo(x,h-10);ctx.stroke();}
  curve(0,0,"rgba(120,200,140,.30)",1); curve(1,0,"rgba(200,120,120,.30)",1); // frames A/B
  curve(state.m,0,"#7ee08a",2); }
addEventListener("resize",draw);

// ---- stage editor UI ----
function renderNav(){ $("stageNav").innerHTML=state.stages.map((_,i)=>`<button class="${i===state.cur?"on":""}" data-s="${i}">${i+1}</button>`).join("");
  $("stageNav").querySelectorAll("button").forEach(b=>b.onclick=()=>{ state.cur=+b.dataset.s; loadStage(); }); }
function loadStage(){ const st=state.stages[state.cur];
  $("shape").value=st.shape; $("gain").value=st.gain; $("gOut").textContent=st.gain;
  $("loFreq").value=st.loFreq; $("loFreqV").textContent=Math.round(st.loFreq); $("loQ").value=st.loQ; $("loQV").textContent=st.loQ;
  $("hiFreq").value=st.hiFreq; $("hiFreqV").textContent=Math.round(st.hiFreq); $("hiQ").value=st.hiQ; $("hiQV").textContent=st.hiQ;
  renderNav(); }
function bind(id, field, outId, isInt){ $(id).oninput=async e=>{ const v=isInt?Math.round(+e.target.value):+e.target.value; state.stages[state.cur][field]=v; if(outId)$(outId).textContent=v; await repack(); }; }
bind("gain","gain","gOut"); bind("loFreq","loFreq","loFreqV",true); bind("loQ","loQ","loQV"); bind("hiFreq","hiFreq","hiFreqV",true); bind("hiQ","hiQ","hiQV");
$("shape").onchange=async e=>{ state.stages[state.cur].shape=e.target.value; await repack(); };

// ---- audio ----
let actx=null, anode=null;
function pushParams(){ if(!anode)return; const d=state.drive; anode.port.postMessage({params:{morph:state.m,q:0,agc:4+4*d,slam:0.25*d*d,wide:0,inputGain:1,makeup:1.5+2.5*d}}); }
async function startAudio(){ actx=new(AudioContext||webkitAudioContext)(); const wasm=await(await fetch(WASM_URL)).arrayBuffer();
  await actx.audioWorklet.addModule("js/forge-worklet.js");
  anode=new AudioWorkletNode(actx,"forge-processor",{numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[2],processorOptions:{wasm,body:state.bytes?state.bytes.buffer.slice(0):null,src:state.src}});
  anode.port.onmessage=e=>{ if(e.data.ready){pushParams(); if(state.playing)anode.port.postMessage({playing:true});}
    if(e.data.level!=null){const m=$("meter");m.firstElementChild.style.height=Math.min(100,e.data.level*140)+"%";m.classList.toggle("flood",e.data.peak>0.985);} };
  anode.connect(actx.destination); }
async function toggleAudio(){ try{ if(!actx)await startAudio(); if(actx.state==="suspended")await actx.resume();
  state.playing=!state.playing; anode.port.postMessage({playing:state.playing}); $("play").classList.toggle("on",state.playing); $("play").textContent=state.playing?"❚❚ stop":"▶ play";
}catch(err){ setStatus("audio failed: "+err.message);} }

$("morph").oninput=e=>{ state.m=+e.target.value/100; $("mOut").textContent=e.target.value; pushParams(); draw(); };
$("drive").oninput=e=>{ state.drive=+e.target.value/100; $("dOut").textContent=e.target.value; pushParams(); };
$("play").onclick=toggleAudio;
document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{ document.querySelectorAll(".chip").forEach(x=>x.classList.remove("on")); c.classList.add("on"); state.src=+c.dataset.src; if(anode)anode.port.postMessage({src:state.src}); });
$("saveBtn").onclick=()=>{ if(!state.bytes){setStatus("nothing to save");return;} downloadBody(`${state.name}.body240`,bodyHex(state.bytes)); setStatus(`saved ${state.name}.body240`); };
$("nameInput").oninput=e=>{ state.name=e.target.value.trim()||"untitled"; };

loadStage(); repack().catch(err=>setStatus("pack failed: "+err.message));
