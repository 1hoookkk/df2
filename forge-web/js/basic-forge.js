import {packWithCore,bodyHex} from "./pack-core.js";
import {downloadBody,downloadText,packedDb,wordsFromBytes,wordsAt,stageWordsToKernel,kernelToBiquad} from "./packed.js";
import {FORGE_TEMPLATES} from "../data/templates.js";

// ---- carve-zeros surface: poles are fit & read-only; the only authoring act is
// dropping/dragging zero canyons over the live morph curve. Audio runs through the
// real worklet drive chain (AGC -> Mackie -> QSound). Four ops: fit, carve, play, save.
const SR=39062.5, F_LO=20, F_HI=SR/2, ZERO_END=SR*.49, DB_LO=-30, DB_HI=36;
const LPC_ORDER=12, LPC_STAGES=6, LPC_FRAME=4096;
const COLORS=["#d24b3f","#e09a2e","#5ba35a","#3f9690","#4f7bb0","#8c6bb8"];
const PARK=[140,420,900,1800,3600,8000];
const WASM_URL="wasm/forge_web_wasm.wasm?v=carve";
const $=id=>document.getElementById(id);
const canvas=$("plot"), ctx=canvas.getContext("2d");

const state={
  name:"hand_vowel",
  m:0, q:0,
  corners:null,           // [4][6] packed-frame stages (poles read-only, motion baked in)
  selZero:0,              // lane whose zero is "armed" for scroll/depth
  bytes:null, hex:"", words:null, worstR:0, score:null,
  drag:null,
  // audio
  src:0, drive:0.40, playing:false,
  fit:{active:false,source:"idle",zerosLive:true,status:"idle",poles:[],audio:null,analyser:null,stream:null,nodes:[],timer:null,buf:null,bufPos:0,syntheticT:0},
};

const SYSTEM_TEMPLATE=FORGE_TEMPLATES.find(t=>t.id==="three_layer_acoustic") || FORGE_TEMPLATES[0];
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const hzText=v=>v>=1000?`${(v/1000).toFixed(v>=10000?1:2)}k`:`${Math.round(v)}`;
const setStatus=t=>{ $("status").textContent=t; };
const gainMul=s=>Math.pow(10,(s.gainDb||0)/20);

function cloneStage(s){ return {...s}; }
function cloneTemplateStages(stages){
  return stages.slice(0,6).map((s,i)=>({
    on:s.on!==false,
    hz:clamp(+s.hz,F_LO,ZERO_END),
    r:clamp(+s.r,0.5,0.9999),
    gainDb:Number.isFinite(+s.gainDb)?+s.gainDb:0,
    cutOn:!!s.cutOn,
    cutHz:clamp(+(s.cutHz??s.hz*0.75),F_LO,ZERO_END),
    cutDepth:clamp(+(s.cutDepth??0.6),0,0.9999),
    label:s.label||`lane ${i+1}`,
  }));
}
function loadTemplate(t){
  state.corners=[0,1,2,3].map(ci=>cloneTemplateStages((t.corners&&t.corners[ci])?t.corners[ci]:t.stages));
}
function resetToSystem(){
  loadTemplate(SYSTEM_TEMPLATE);
  state.name="hand_vowel"; state.m=0; state.q=0; state.selZero=0;
}

// ---- pack ----
function packModel(){
  return state.corners.map(corner=>corner.map(s=>({...s,gain:gainMul(s)})));
}
async function repack(opts={}){
  state.bytes=await packWithCore(packModel());
  state.hex=bodyHex(state.bytes);
  state.words=wordsFromBytes(state.bytes);
  state.worstR=worstRadius();
  state.score=null;
  if(anode) anode.port.postMessage({body:state.bytes.buffer.slice(0)});
  if(opts.soft){ renderTop(); renderZeroGrid(); renderMore(); drawPlot(); }
  else render();
  setStatus(`${state.hex.length/2} bytes · ${state.worstR>=1?"UNSTABLE":state.worstR>=.999?"edge":"runs"}`);
}
function worstRadius(){
  if(!state.words) return 0;
  let worst=0;
  for(let mi=0;mi<=16;mi++) for(let qi=0;qi<=16;qi++){
    for(const row of wordsAt(state.words,mi/16,qi/16)){
      const bq=kernelToBiquad(stageWordsToKernel(row));
      worst=Math.max(worst,poleRadius(bq[3],bq[4]));
    }
  }
  return worst;
}
function poleRadius(a1,a2){
  const disc=a1*a1-4*a2;
  if(disc<0) return Math.sqrt(Math.max(0,a2));
  const s=Math.sqrt(disc);
  return Math.max(Math.abs((-a1+s)/2),Math.abs((-a1-s)/2));
}

// ---- live-interpolated lane geometry (for handle placement; the curve itself is packed-truth) ----
function laneLive(i,m=state.m,q=state.q){
  const a=state.corners[0][i], b=state.corners[1][i], c=state.corners[2][i], d=state.corners[3][i];
  const w00=(1-m)*(1-q), w10=m*(1-q), w01=(1-m)*q, w11=m*q;
  const geo=(pa,pb,pc,pd)=>Math.exp(w00*Math.log(pa)+w10*Math.log(pb)+w01*Math.log(pc)+w11*Math.log(pd));
  const lin=(pa,pb,pc,pd)=>w00*pa+w10*pb+w01*pc+w11*pd;
  return {
    on:a.on, cutOn:a.cutOn,
    hz:geo(a.hz,b.hz,c.hz,d.hz),
    cutHz:geo(a.cutHz,b.cutHz,c.cutHz,d.cutHz),
    cutDepth:lin(a.cutDepth,b.cutDepth,c.cutDepth,d.cutDepth),
  };
}
// author a zero as an octave offset from its lane pole, applied to ALL corners so it tracks the formant.
function setZeroFromDrag(i,zeroHz){
  const live=laneLive(i);
  const delta=Math.log2(clamp(zeroHz,F_LO,ZERO_END)/Math.max(live.hz,1));
  for(let cI=0;cI<4;cI++){
    const s=state.corners[cI][i];
    s.cutOn=true;
    s.cutHz=clamp(s.hz*Math.pow(2,delta),F_LO,ZERO_END);
  }
}
function setZeroDepth(i,depth){
  for(let cI=0;cI<4;cI++) state.corners[cI][i].cutDepth=clamp(depth,0,0.9999);
}
function toggleZero(i){
  const on=!state.corners[0][i].cutOn;
  for(let cI=0;cI<4;cI++){
    const s=state.corners[cI][i];
    s.cutOn=on;
    if(on && !(s.cutHz>F_LO)) s.cutHz=s.hz*0.8;
    if(on && !(s.cutDepth>0)) s.cutDepth=0.65;
  }
}

// ---- plot ----
function fitCanvas(){
  const r=canvas.getBoundingClientRect();
  const dpr=Math.min(window.devicePixelRatio||1,2);
  const w=Math.max(320,Math.round(r.width*dpr)), h=Math.max(240,Math.round(r.height*dpr));
  if(canvas.width!==w||canvas.height!==h){ canvas.width=w; canvas.height=h; }
}
const xFor=(f,w)=>48+(Math.log(clamp(f,F_LO,F_HI))-Math.log(F_LO))/(Math.log(F_HI)-Math.log(F_LO))*(w-70);
const fFor=(x,w)=>Math.exp(Math.log(F_LO)+clamp((x-48)/(w-70),0,1)*(Math.log(F_HI)-Math.log(F_LO)));
const yFor=(db,h)=>18+(1-(clamp(db,DB_LO,DB_HI)-DB_LO)/(DB_HI-DB_LO))*(h-48);
function canvasPoint(e){
  const r=canvas.getBoundingClientRect();
  return {x:(e.clientX-r.left)*canvas.width/r.width,y:(e.clientY-r.top)*canvas.height/r.height};
}
function liveDb(f,m=state.m,q=state.q){ return state.words?packedDb(state.words,m,q,f):0; }

function drawGrid(w,h){
  ctx.fillStyle="#f7f3eb"; ctx.fillRect(0,0,w,h);
  ctx.strokeStyle="#e0d7c8"; ctx.lineWidth=1; ctx.font="13px Consolas, monospace"; ctx.fillStyle="#81786c";
  for(const db of [24,12,0,-12,-24]){ const y=yFor(db,h); ctx.beginPath(); ctx.moveTo(48,y); ctx.lineTo(w-22,y); ctx.stroke(); ctx.textAlign="right"; ctx.fillText((db>0?"+":"")+db,40,y+4); }
  for(const f of [50,100,200,500,1000,2000,5000,10000]){ const x=xFor(f,w); ctx.beginPath(); ctx.moveTo(x,18); ctx.lineTo(x,h-30); ctx.stroke(); ctx.textAlign="center"; ctx.fillText(f>=1000?`${f/1000}k`:String(f),x,h-9); }
}
function drawCurve(m,q,color,width,dash=null){
  const w=canvas.width,h=canvas.height;
  ctx.save(); if(dash) ctx.setLineDash(dash);
  ctx.strokeStyle=color; ctx.lineWidth=width; ctx.beginPath();
  for(let i=0;i<520;i++){ const t=i/519; const f=Math.exp(Math.log(F_LO)+t*(Math.log(F_HI)-Math.log(F_LO))); const x=xFor(f,w), y=yFor(liveDb(f,m,q),h); if(i) ctx.lineTo(x,y); else ctx.moveTo(x,y); }
  ctx.stroke(); ctx.restore();
}
function zeroPoint(i){
  const live=laneLive(i);
  const x=xFor(live.cutHz,canvas.width);
  const y=yFor(liveDb(live.cutHz)-live.cutDepth*18,canvas.height);
  return {x,y,live};
}
function polePoint(i){
  const live=laneLive(i);
  return {x:xFor(live.hz,canvas.width),y:yFor(liveDb(live.hz),canvas.height)};
}
function drawMarkers(){
  for(let i=0;i<6;i++){
    const lv=laneLive(i);
    if(!lv.on) continue;
    // pole: read-only, faint square
    const p=polePoint(i);
    ctx.globalAlpha=.5; ctx.strokeStyle=COLORS[i]; ctx.lineWidth=1.5;
    ctx.strokeRect(p.x-5,p.y-5,10,10);
    // zero: the editable canyon
    if(lv.cutOn){
      const z=zeroPoint(i), sel=i===state.selZero;
      ctx.globalAlpha=sel?1:.7; ctx.setLineDash([3,4]); ctx.strokeStyle="#c52f4d"; ctx.lineWidth=1;
      ctx.beginPath(); ctx.moveTo(z.x,yFor(liveDb(lv.cutHz),canvas.height)); ctx.lineTo(z.x,z.y); ctx.stroke();
      ctx.setLineDash([]); ctx.fillStyle="#fff7ee"; ctx.lineWidth=sel?2.5:1.6;
      ctx.beginPath(); ctx.arc(z.x,z.y,sel?8:6,0,Math.PI*2); ctx.fill(); ctx.stroke();
    }
  }
  ctx.globalAlpha=1; ctx.setLineDash([]);
}
function drawPlot(){
  fitCanvas();
  const w=canvas.width,h=canvas.height;
  drawGrid(w,h);
  drawCurve(0,0,"rgba(210,75,63,.18)",1.2);
  drawCurve(1,0,"rgba(63,123,176,.16)",1.2);
  drawCurve(1,1,"rgba(140,107,184,.16)",1.2);
  drawCurve(state.m,state.q,"#15130f",2.6);
  drawMarkers();
}

// ---- zero hit-testing / interaction ----
function hitZero(pt){
  let best=null,bestD=14;
  for(let i=0;i<6;i++){
    const lv=laneLive(i);
    if(!lv.on||!lv.cutOn) continue;
    const z=zeroPoint(i), d=Math.hypot(z.x-pt.x,z.y-pt.y);
    if(d<bestD){ bestD=d; best=i; }
  }
  return best;
}
canvas.addEventListener("pointerdown",e=>{
  const pt=canvasPoint(e), i=hitZero(pt);
  if(i==null) return;
  state.selZero=i; state.drag=i; canvas.setPointerCapture(e.pointerId); render();
});
canvas.addEventListener("pointermove",async e=>{
  if(state.drag==null) return;
  const pt=canvasPoint(e);
  setZeroFromDrag(state.drag,fFor(pt.x,canvas.width));
  await repack({soft:true});
});
canvas.addEventListener("pointerup",()=>{ if(state.drag!=null){ state.drag=null; render(); } });
canvas.addEventListener("pointercancel",()=>{ state.drag=null; render(); });
canvas.addEventListener("wheel",async e=>{
  const pt=canvasPoint(e), i=hitZero(pt)??state.selZero;
  if(i==null) return;
  e.preventDefault();
  state.selZero=i;
  const cur=laneLive(i).cutDepth;
  setZeroDepth(i,cur+(e.deltaY<0?.03:-.03));
  await repack({soft:true});
},{passive:false});

// ---- renders ----
function renderTop(){
  const name=$("nameInput");
  if(name && document.activeElement!==name) name.value=state.name;
  $("morph").value=Math.round(state.m*100); $("q").value=Math.round(state.q*100);
  $("mOut").textContent=Math.round(state.m*100); $("qOut").textContent=Math.round(state.q*100);
  $("light").className="light"+(state.worstR>=1?" bad":state.worstR>=.999?" warn":"");
}
function renderZeroGrid(){
  const el=$("zeroGrid"); if(!el) return;
  el.innerHTML=state.corners[0].map((s,i)=>{
    const on=s.cutOn?" on":"", sel=i===state.selZero?" sel":"";
    const lv=laneLive(i);
    return `<button class="zBtn${on}${sel}" data-z="${i}">Z${i+1}<br>${s.cutOn?hzText(lv.cutHz):"off"}</button>`;
  }).join("");
  el.querySelectorAll("[data-z]").forEach(b=>{
    const i=+b.dataset.z;
    b.onclick=async()=>{ state.selZero=i; toggleZero(i); await repack(); };
  });
}
function renderMore(){
  const sc=state.score
    ? `<div>score ${state.score.verdict} · morph ${state.score.metrics.morph_contrast_rms_db.toFixed(1)} dB · q ${state.score.metrics.secondary_contrast_rms_db.toFixed(1)} dB · zero move ${state.score.metrics.median_zero_motion_octaves.toFixed(2)} oct</div>`
    : "<div>score idle</div>";
  $("moreBody").innerHTML=`<div>${state.hex.length/2} bytes · worst r ${state.worstR.toFixed(5)}</div>${sc}`;
}
function renderFitStatus(){ $("fitState").textContent=state.fit.poles.length?`${state.fit.source}: ${state.fit.poles.length} poles — "→ poles" to place`:state.fit.status; }
function render(){
  renderTop(); renderZeroGrid(); renderMore(); renderFitStatus(); drawPlot();
}
window.addEventListener("resize",()=>drawPlot());

// ---- transport / sliders ----
$("morph").oninput=()=>{ state.m=+$("morph").value/100; pushParams(); renderTop(); renderZeroGrid(); drawPlot(); };
$("q").oninput=()=>{ state.q=+$("q").value/100; pushParams(); renderTop(); renderZeroGrid(); drawPlot(); };
$("nameInput").oninput=e=>{ state.name=e.target.value.trim()||"untitled"; };

// ===================== AUDIO: worklet drive chain (AGC -> Mackie -> QSound) =====================
let actx=null, anode=null;
function driveParams(){
  const d=clamp(state.drive,0,1);
  return { agc:4.0+4.0*d, slam:0.25*d*d, wide:0, inputGain:1.0, makeup:1.5+2.5*d };
}
function pushParams(){
  if(!anode) return;
  const p=driveParams();
  anode.port.postMessage({params:{morph:state.m,q:state.q,agc:p.agc,slam:p.slam,wide:p.wide,inputGain:p.inputGain,makeup:p.makeup}});
}
async function startAudio(){
  actx=new (window.AudioContext||window.webkitAudioContext)();
  const wasm=await (await fetch(WASM_URL)).arrayBuffer();
  await actx.audioWorklet.addModule("js/forge-worklet.js");
  anode=new AudioWorkletNode(actx,"forge-processor",{numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[2],
    processorOptions:{wasm,body:state.bytes?state.bytes.buffer.slice(0):null,src:state.src}});
  anode.port.onmessage=e=>{
    if(e.data.ready){ pushParams(); if(state.playing) anode.port.postMessage({playing:true}); }
    if(e.data.level!=null) updateMeter(e.data.peak,e.data.level);
    if(e.data.error) setStatus("audio: "+e.data.error);
  };
  anode.connect(actx.destination);
}
async function toggleAudio(){
  try{
    if(!actx) await startAudio();
    if(actx.state==="suspended") await actx.resume();
    state.playing=!state.playing;
    if(anode) anode.port.postMessage({playing:state.playing});
    $("play").classList.toggle("on",state.playing);
    $("play").textContent=state.playing?"❚❚ stop":"▶ play";
  }catch(err){ setStatus("audio failed: "+err.message); console.error(err); }
}
function updateMeter(peak,rms){
  const m=$("meter"); if(!m) return;
  m.firstElementChild.style.height=Math.min(100,rms*140)+"%";
  m.classList.toggle("flood",peak>0.985);
}
$("play").onclick=toggleAudio;
document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{
  document.querySelectorAll(".chip").forEach(x=>x.classList.remove("on")); c.classList.add("on");
  state.src=+c.dataset.src; if(anode) anode.port.postMessage({src:state.src});
});

// ===================== FIT: LPC(12) -> 6 read-only pole lanes =====================
function c2(re=0,im=0){ return {re,im}; }
const cAdd=(a,b)=>c2(a.re+b.re,a.im+b.im), cSub=(a,b)=>c2(a.re-b.re,a.im-b.im);
const cMul=(a,b)=>c2(a.re*b.re-a.im*b.im,a.re*b.im+a.im*b.re);
function cDiv(a,b){ const d=b.re*b.re+b.im*b.im||1e-24; return c2((a.re*b.re+a.im*b.im)/d,(a.im*b.re-a.re*b.im)/d); }
const cAbs=a=>Math.hypot(a.re,a.im);
function polyEval(co,z){ let y=c2(co[0],0); for(let i=1;i<co.length;i++) y=cAdd(cMul(y,z),c2(co[i],0)); return y; }
function rootsDK(co){
  const n=co.length-1;
  let roots=Array.from({length:n},(_,i)=>{ const a=2*Math.PI*(i+.35)/n; return c2(.72*Math.cos(a),.72*Math.sin(a)); });
  for(let it=0;it<70;it++){ let moved=0; roots=roots.map((z,i)=>{ let den=c2(1,0); for(let j=0;j<n;j++) if(j!==i) den=cMul(den,cSub(z,roots[j])); const dz=cDiv(polyEval(co,z),den); moved=Math.max(moved,cAbs(dz)); return cSub(z,dz); }); if(moved<1e-10) break; }
  return roots;
}
function lpcCoeffs(samples,order=LPC_ORDER){
  const x=new Float64Array(samples.length); let mean=0;
  for(const v of samples) mean+=v; mean/=samples.length||1;
  for(let i=0;i<samples.length;i++){ const pre=i?samples[i]-.94*samples[i-1]:samples[i]; const win=.5-.5*Math.cos(2*Math.PI*i/(samples.length-1)); x[i]=(pre-mean)*win; }
  const r=new Float64Array(order+1);
  for(let lag=0;lag<=order;lag++){ let s=0; for(let i=lag;i<x.length;i++) s+=x[i]*x[i-lag]; r[lag]=s; }
  if(r[0]<1e-8) return null;
  let a=new Float64Array(order+1); a[0]=1; let e=r[0];
  for(let i=1;i<=order;i++){ let acc=r[i]; for(let j=1;j<i;j++) acc+=a[j]*r[i-j]; let k=clamp(-acc/Math.max(e,1e-12),-.995,.995); const next=new Float64Array(order+1); next[0]=1; for(let j=1;j<i;j++) next[j]=a[j]+k*a[i-j]; next[i]=k; a=next; e*=Math.max(1-k*k,1e-6); }
  return Array.from(a);
}
function lpcPoles(samples,sr=SR){
  const a=lpcCoeffs(samples,LPC_ORDER); if(!a) return [];
  const poles=[];
  for(const z of rootsDK(a)){ const ang=Math.atan2(z.im,z.re); if(ang<=0||ang>=Math.PI) continue; const hz=ang*sr/(2*Math.PI); const r=cAbs(z); if(Number.isFinite(hz)&&hz>=45&&hz<=Math.min(sr*.49,ZERO_END)) poles.push({hz,r:clamp(r,.5,.9999)}); }
  poles.sort((a,b)=>b.r-a.r||a.hz-b.hz);
  const picked=poles.slice(0,LPC_STAGES).sort((a,b)=>a.hz-b.hz);
  while(picked.length<LPC_STAGES){ const i=picked.length; picked.push({hz:PARK[i],r:.88}); }
  return picked;
}
// place fitted poles into ALL 4 corners (still frame); keeps existing zeros tracking via cutHz recompute.
async function placePoles(){
  const poles=state.fit.poles;
  if(!poles.length){ setStatus("run a source first (open/mic/test), then freeze"); return; }
  for(let cI=0;cI<4;cI++){
    state.corners[cI]=poles.slice(0,LPC_STAGES).map((p,i)=>{
      const prev=state.corners[cI][i]||{};
      return {on:true,hz:clamp(p.hz,F_LO,ZERO_END),r:clamp(p.r,.5,.9999),gainDb:0,
        cutOn:!!prev.cutOn,cutHz:clamp(prev.cutOn?prev.cutHz:p.hz*0.8,F_LO,ZERO_END),cutDepth:prev.cutOn?prev.cutDepth:0.6,label:`lpc ${i+1}`};
    });
  }
  await repack();
  setStatus("placed 6 fit pole lanes (still frame — morph A/B fit is next)");
}
function makeAnalyser(audio){ const an=audio.createAnalyser(); an.fftSize=LPC_FRAME; an.smoothingTimeConstant=.2; state.fit.analyser=an; return an; }
function stopFit(keep){
  if(state.fit.timer) clearTimeout(state.fit.timer); state.fit.timer=null;
  for(const n of state.fit.nodes){ try{n.stop?.();}catch(_){} try{n.disconnect?.();}catch(_){} }
  state.fit.nodes=[];
  if(state.fit.stream){ for(const t of state.fit.stream.getTracks()) t.stop(); } state.fit.stream=null;
  if(state.fit.audio){ state.fit.audio.close().catch(()=>{}); } state.fit.audio=null; state.fit.analyser=null;
  state.fit.active=false; state.fit.source=keep||"idle"; state.fit.status=keep||"idle"; renderFitStatus();
}
function fitFromAnalyser(){ const buf=new Float32Array(LPC_FRAME); state.fit.analyser.getFloatTimeDomainData(buf); return lpcPoles(buf,state.fit.audio?.sampleRate||SR); }
function startLoop(){
  state.fit.active=true;
  const tick=()=>{ if(!state.fit.active||!state.fit.analyser) return; try{ state.fit.poles=fitFromAnalyser(); renderFitStatus(); }catch(err){ setStatus("lpc failed: "+err.message); } state.fit.timer=setTimeout(tick,180); };
  tick();
}
async function startMic(){
  stopFit();
  const audio=new AudioContext(); await audio.resume();
  const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false}});
  const src=audio.createMediaStreamSource(stream); src.connect(makeAnalyser(audio));
  state.fit.audio=audio; state.fit.stream=stream; state.fit.nodes=[src]; state.fit.source="mic"; startLoop();
}
function synthFrame(){
  const out=new Float32Array(LPC_FRAME); const fr=[170,430,910,1850,3900,7900], am=[.7,.5,.45,.32,.22,.16];
  for(let i=0;i<out.length;i++){ const t=(state.fit.syntheticT+i)/SR; let v=0; for(let k=0;k<fr.length;k++) v+=am[k]*Math.sin(2*Math.PI*fr[k]*t+k*.7); v+=.025*Math.sin(2*Math.PI*53*t); out[i]=v*.22; }
  state.fit.syntheticT+=out.length; return out;
}
function startTest(){
  stopFit(); state.fit.source="test"; state.fit.active=true;
  const tick=()=>{ if(!state.fit.active||state.fit.source!=="test") return; state.fit.poles=lpcPoles(synthFrame(),SR); renderFitStatus(); state.fit.timer=setTimeout(tick,180); };
  tick();
}
async function fitFile(file){
  stopFit();
  const ab=await file.arrayBuffer();
  const ac=new (window.AudioContext||window.webkitAudioContext)();
  const audioBuf=await ac.decodeAudioData(ab);
  const ch=audioBuf.getChannelData(0);
  // take a centered LPC_FRAME window (or the whole thing if short)
  const start=Math.max(0,Math.floor((ch.length-LPC_FRAME)/2));
  const win=ch.subarray(start,start+LPC_FRAME);
  state.fit.poles=lpcPoles(win,audioBuf.sampleRate);
  state.fit.source=file.name; state.fit.status=file.name; ac.close().catch(()=>{});
  renderFitStatus();
  setStatus(`fit ${file.name}: ${state.fit.poles.length} poles — "→ poles" to place`);
}
$("micBtn").onclick=async()=>{ try{ await startMic(); setStatus("lpc mic running — freeze to capture"); }catch(err){ setStatus("mic failed: "+err.message); } };
$("testBtn").onclick=()=>{ startTest(); setStatus("lpc test source running — freeze to capture"); };
$("freezeBtn").onclick=()=>{ stopFit("frozen"); setStatus(`frozen ${state.fit.poles.length} poles`); };
$("openBtn").onclick=()=>$("openFile").click();
$("openFile").onchange=async()=>{ const f=$("openFile").files[0]; if(f) await fitFile(f); };
$("placeBtn").onclick=placePoles;

// ===================== save / score / json =====================
function modelJson(){ return {format:"df2-forge-edit-v1",name:state.name,corners:state.corners}; }
function authorPayload(){ return {format:"df2-hand-pz-frame-v1",name:state.name,cornerOrder:["M0_Q0","M100_Q0","M0_Q100","M100_Q100"],hex:state.hex,corners:state.corners}; }
async function postJson(path,payload){
  const res=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  const json=await res.json().catch(()=>({}));
  if(!res.ok||json.ok===false) throw new Error(json.error||`${path} ${res.status}`);
  return json;
}
$("saveBtn").onclick=()=>{ downloadBody(`${state.name}.body240`,state.hex); setStatus(`saved ${state.name}.body240`); };
$("keepBtn").onclick=()=>{ downloadText(`${state.name}.json`,JSON.stringify(modelJson(),null,2)); setStatus(`kept ${state.name}.json`); };
$("openJsonBtn").onclick=()=>$("openJsonFile").click();
$("openJsonFile").onchange=async()=>{
  const f=$("openJsonFile").files[0]; if(!f) return;
  try{ const doc=JSON.parse(await f.text()); if(doc.format!=="df2-forge-edit-v1"||!Array.isArray(doc.corners)) throw new Error("not a forge edit json");
    state.name=doc.name||"untitled"; state.corners=doc.corners.map(cn=>cn.map(cloneStage)); state.selZero=0; await repack(); setStatus(`opened ${state.name}`);
  }catch(err){ setStatus("open failed: "+err.message); }
};
$("resetBtn").onclick=async()=>{ resetToSystem(); await repack(); setStatus(`reset · ${state.hex.length/2} bytes`); };
$("scoreBtn").onclick=async()=>{
  try{ setStatus("scoring..."); state.score=await postJson("/score",{hex:state.hex,grid:9}); renderMore();
    setStatus(`score ${state.score.verdict} · morph ${state.score.metrics.morph_contrast_rms_db.toFixed(1)} dB`);
  }catch(err){ setStatus("score failed: "+err.message); }
};

// ---- boot ----
resetToSystem();
repack().catch(err=>setStatus("pack failed: "+err.message));
