import {packWithCore,bodyHex} from "./pack-core.js";
import {downloadBody,downloadText,packedDb,wordsFromBytes,wordsAt,stageWordsToKernel,kernelToBiquad} from "./packed.js";
import {FORGE_TEMPLATES} from "../data/templates.js";

const SR=39062.5, F_LO=20, F_HI=SR/2, ZERO_END=SR*.49, DB_LO=-30, DB_HI=36;
const LPC_ORDER=12, LPC_STAGES=6, LPC_FRAME=4096;
const COLORS=["#d24b3f","#e09a2e","#5ba35a","#3f9690","#4f7bb0","#8c6bb8"];
const SPOTS=[["low",160],["low-mid",450],["mid",1000],["high-mid",2800],["top",8000]];
const PARK=[140,420,900,1800,3600,8000];
const $=id=>document.getElementById(id);
const canvas=$("plot"), ctx=canvas.getContext("2d");

const state={
  name:"untitled",
  corner:0,
  stage:0,
  m:0,
  q:0,
  corners:null,
  bytes:null,
  hex:"",
  words:null,
  worstR:0,
  drag:null,
  linkCorners:true,
  fit:{
    active:false,
    source:"idle",
    writeLive:false,
    zerosLive:true,
    status:"idle",
    poles:[],
    audio:null,
    analyser:null,
    stream:null,
    nodes:[],
    timer:null,
    syntheticT:0,
  },
};

const SYSTEM_TEMPLATE=FORGE_TEMPLATES.find(t=>t.id==="three_layer_acoustic") || FORGE_TEMPLATES[0];

function emptyStage(i){
  return {on:false,hz:PARK[i],r:0.88,gainDb:0,cutOn:false,cutHz:PARK[i]*0.75,cutDepth:0.75,label:""};
}
function makeBlank(){
  return Array.from({length:4},()=>Array.from({length:6},(_,i)=>emptyStage(i)));
}

// --- template palette: seed the six editable lanes; never read-only after. ---
function cloneTemplateStages(stages){
  return stages.slice(0,6).map((s,i)=>({
    on:!!s.on,
    hz:clamp(+s.hz,F_LO,ZERO_END),
    r:clamp(+s.r,0.5,0.9999),
    gainDb:Number.isFinite(+s.gainDb)?+s.gainDb:0,
    cutOn:!!s.cutOn,
    cutHz:clamp(+(s.cutHz??s.hz*0.75),F_LO,ZERO_END),
    cutDepth:clamp(+(s.cutDepth??0),0,0.9999),
    label:s.label||"",
  }));
}
function applyTemplateToCorner(t,ci){ state.corners[ci]=cloneTemplateStages(t.stages); }
function applyTemplateToAllCorners(t){
  for(let ci=0;ci<4;ci++){
    const src=(t.corners&&t.corners[ci])?t.corners[ci]:t.stages;
    state.corners[ci]=cloneTemplateStages(src);
  }
}
function validateTemplate(t){
  const errs=[];
  const checkStages=(arr,where)=>{
    if(!Array.isArray(arr)||arr.length!==6){ errs.push(`${where}: need exactly 6 stages`); return; }
    arr.forEach((s,i)=>{
      const at=`${where} stage ${i+1}`;
      if(!Number.isFinite(+s.hz)||+s.hz<F_LO||+s.hz>ZERO_END) errs.push(`${at}: hz out of range`);
      if(!Number.isFinite(+s.r)||+s.r>=1||+s.r<0.5) errs.push(`${at}: r must be 0.5..<1`);
      if(!Number.isFinite(+s.gainDb)) errs.push(`${at}: gainDb not finite`);
      if(s.cutOn){
        if(!Number.isFinite(+s.cutHz)||+s.cutHz<F_LO||+s.cutHz>ZERO_END) errs.push(`${at}: cutHz out of range`);
        if(!Number.isFinite(+s.cutDepth)||+s.cutDepth<0||+s.cutDepth>=1) errs.push(`${at}: cutDepth must be 0..<1`);
      }
    });
  };
  checkStages(t.stages,"stages");
  if(t.corners){
    if(t.corners.length!==4) errs.push("corners: need 4");
    else t.corners.forEach((cn,i)=>checkStages(cn,`C${i}`));
  }
  return {ok:errs.length===0,errors:errs};
}
function resetToSystem(){
  applyTemplateToAllCorners(SYSTEM_TEMPLATE);
  state.name="three_layer_acoustic";
  state.stage=0;
}

function stage(c=state.corner,i=state.stage){ return state.corners[c][i]; }
function cloneStage(s){ return {...s}; }
function syncLinkedStage(i=state.stage){
  if(!state.linkCorners) return;
  const src=cloneStage(state.corners[state.corner][i]);
  for(let c=0;c<4;c++) if(c!==state.corner) state.corners[c][i]=cloneStage(src);
}
function gainMul(s){ return Math.pow(10,s.gainDb/20); }
function packModel(){
  return state.corners.map(corner=>corner.map(s=>({
    ...s,
    gain:gainMul(s),
  })));
}
function hzText(v){ return v>=1000?`${(v/1000).toFixed(v>=10000?1:2)}k`:`${Math.round(v)}`; }
function clamp(v,a,b){ return Math.max(a,Math.min(b,v)); }
function setStatus(t){ $("status").textContent=t; }

function setFitStatus(t){
  state.fit.status=t;
  const el=$("fitState");
  if(el) el.textContent=t;
}

function modelJson(){
  return {
    format:"df2-forge-edit-v1",
    name:state.name,
    corners:state.corners,
  };
}

async function repack(){
  state.bytes=await packWithCore(packModel());
  state.hex=bodyHex(state.bytes);
  state.words=wordsFromBytes(state.bytes);
  state.worstR=worstRadius();
  render();
  setStatus(`${state.hex.length/2} bytes · ${state.worstR>=1?"bad":state.worstR>=.999?"edge":"runs"}`);
}

function worstRadius(){
  if(!state.words) return 0;
  let worst=0;
  for(let mi=0;mi<=16;mi++){
    for(let qi=0;qi<=16;qi++){
      const rows=wordsAt(state.words,mi/16,qi/16);
      for(const row of rows){
        const bq=kernelToBiquad(stageWordsToKernel(row));
        worst=Math.max(worst,poleRadius(bq[3],bq[4]));
      }
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

function c(re=0,im=0){ return {re,im}; }
function cAdd(a,b){ return c(a.re+b.re,a.im+b.im); }
function cSub(a,b){ return c(a.re-b.re,a.im-b.im); }
function cMul(a,b){ return c(a.re*b.re-a.im*b.im,a.re*b.im+a.im*b.re); }
function cDiv(a,b){
  const d=b.re*b.re+b.im*b.im || 1e-24;
  return c((a.re*b.re+a.im*b.im)/d,(a.im*b.re-a.re*b.im)/d);
}
function cAbs(a){ return Math.hypot(a.re,a.im); }

function polyEval(coeffs,z){
  let y=c(coeffs[0],0);
  for(let i=1;i<coeffs.length;i++) y=cAdd(cMul(y,z),c(coeffs[i],0));
  return y;
}

function rootsDurandKerner(coeffs){
  const n=coeffs.length-1;
  let roots=Array.from({length:n},(_,i)=>{
    const a=2*Math.PI*(i+.35)/n;
    return c(.72*Math.cos(a),.72*Math.sin(a));
  });
  for(let iter=0;iter<70;iter++){
    let moved=0;
    roots=roots.map((z,i)=>{
      let den=c(1,0);
      for(let j=0;j<n;j++) if(j!==i) den=cMul(den,cSub(z,roots[j]));
      const dz=cDiv(polyEval(coeffs,z),den);
      moved=Math.max(moved,cAbs(dz));
      return cSub(z,dz);
    });
    if(moved<1e-10) break;
  }
  return roots;
}

function lpcCoefficients(samples,order=LPC_ORDER){
  const x=new Float64Array(samples.length);
  let mean=0;
  for(const v of samples) mean+=v;
  mean/=samples.length || 1;
  for(let i=0;i<samples.length;i++){
    const pre=i?samples[i]-.94*samples[i-1]:samples[i];
    const win=.5-.5*Math.cos(2*Math.PI*i/(samples.length-1));
    x[i]=(pre-mean)*win;
  }
  const r=new Float64Array(order+1);
  for(let lag=0;lag<=order;lag++){
    let s=0;
    for(let i=lag;i<x.length;i++) s+=x[i]*x[i-lag];
    r[lag]=s;
  }
  if(r[0]<1e-8) return null;
  let a=new Float64Array(order+1);
  a[0]=1;
  let e=r[0];
  for(let i=1;i<=order;i++){
    let acc=r[i];
    for(let j=1;j<i;j++) acc+=a[j]*r[i-j];
    let k=-acc/Math.max(e,1e-12);
    k=clamp(k,-.995,.995);
    const next=new Float64Array(order+1);
    next[0]=1;
    for(let j=1;j<i;j++) next[j]=a[j]+k*a[i-j];
    next[i]=k;
    a=next;
    e*=Math.max(1-k*k,1e-6);
  }
  return Array.from(a);
}

function lpcPolesFromSamples(samples,sampleRate=SR){
  const a=lpcCoefficients(samples,LPC_ORDER);
  if(!a) return [];
  const roots=rootsDurandKerner(a);
  const poles=[];
  for(const z of roots){
    const angle=Math.atan2(z.im,z.re);
    if(angle<=0 || angle>=Math.PI) continue;
    const hz=angle*sampleRate/(2*Math.PI);
    const r=cAbs(z);
    if(Number.isFinite(hz) && Number.isFinite(r) && hz>=45 && hz<=Math.min(sampleRate*.49,ZERO_END)){
      poles.push({hz,r:clamp(r,.5,.9999),rawR:r});
    }
  }
  poles.sort((a,b)=>b.r-a.r || a.hz-b.hz);
  const picked=poles.slice(0,LPC_STAGES).sort((a,b)=>a.hz-b.hz);
  while(picked.length<LPC_STAGES){
    const i=picked.length;
    picked.push({hz:PARK[i],r:.88,rawR:.88});
  }
  return picked;
}

function goertzelPower(samples,freq,sampleRate){
  const w=2*Math.PI*freq/sampleRate;
  const coeff=2*Math.cos(w);
  let s0=0,s1=0,s2=0;
  for(let i=0;i<samples.length;i++){
    const win=.5-.5*Math.cos(2*Math.PI*i/(samples.length-1));
    s0=samples[i]*win + coeff*s1 - s2;
    s2=s1;
    s1=s0;
  }
  return Math.max(s1*s1+s2*s2-coeff*s1*s2,1e-18);
}

function spectrumBands(samples,sampleRate){
  const bands=[];
  const n=96;
  const lo=60, hi=Math.min(ZERO_END,sampleRate*.49);
  let peak=-Infinity;
  for(let i=0;i<n;i++){
    const t=i/(n-1);
    const hz=Math.exp(Math.log(lo)+t*(Math.log(hi)-Math.log(lo)));
    const db=10*Math.log10(goertzelPower(samples,hz,sampleRate));
    bands.push({hz,db});
    peak=Math.max(peak,db);
  }
  for(const b of bands) b.relDb=b.db-peak;
  return bands;
}

function zeroForPole(pole,i,poles,bands){
  const prev=i>0?poles[i-1].hz:60;
  const next=i<poles.length-1?poles[i+1].hz:ZERO_END;
  const lo=Math.max(60,Math.sqrt(prev*pole.hz));
  const hi=Math.min(ZERO_END,Math.sqrt(next*pole.hz));
  let best=null;
  for(const b of bands){
    if(b.hz<lo || b.hz>hi) continue;
    if(!best || b.relDb<best.relDb) best=b;
  }
  if(!best){
    const side=i%2?-0.65:0.65;
    const hz=clamp(pole.hz*Math.pow(2,side),60,ZERO_END);
    return {cutHz:hz,cutDepth:0.72};
  }
  const depth=clamp(0.45 + Math.min(36,Math.abs(best.relDb))/44,0.45,0.9999);
  return {cutHz:best.hz,cutDepth:depth};
}

function polesAndZerosFromSamples(samples,sampleRate=SR){
  const poles=lpcPolesFromSamples(samples,sampleRate);
  if(!state.fit.zerosLive || !poles.length) return poles.map(p=>({...p,cutHz:ZERO_END,cutDepth:.9999}));
  const bands=spectrumBands(samples,sampleRate);
  return poles.map((p,i)=>({...p,...zeroForPole(p,i,poles,bands)}));
}

function poleSamplesFromAnalyser(){
  const buf=new Float32Array(LPC_FRAME);
  state.fit.analyser.getFloatTimeDomainData(buf);
  return polesAndZerosFromSamples(buf,state.fit.audio?.sampleRate || SR);
}

async function applyFitPolesToCorner(){
  const poles=state.fit.poles;
  if(!poles.length) return;
  const fitted=poles.slice(0,LPC_STAGES).map((p,i)=>({
    on:true,
    hz:clamp(p.hz,F_LO,ZERO_END),
    r:clamp(p.r,.5,.9999),
    gainDb:0,
    cutOn:true,
    cutHz:state.fit.zerosLive ? clamp(p.cutHz ?? ZERO_END,F_LO,ZERO_END) : ZERO_END,
    cutDepth:state.fit.zerosLive ? clamp(p.cutDepth ?? .9999,0,0.9999) : .9999,
    label:`lpc ${i+1}`,
  }));
  if(state.linkCorners){
    for(let c=0;c<4;c++) state.corners[c]=fitted.map(cloneStage);
  }else{
    state.corners[state.corner]=fitted.map(cloneStage);
  }
  await repack();
}

function stopFit(){
  if(state.fit.timer) clearTimeout(state.fit.timer);
  state.fit.timer=null;
  for(const node of state.fit.nodes){
    try{ node.stop?.(); }catch(_){}
    try{ node.disconnect?.(); }catch(_){}
  }
  state.fit.nodes=[];
  if(state.fit.stream){
    for(const track of state.fit.stream.getTracks()) track.stop();
  }
  state.fit.stream=null;
  if(state.fit.audio){
    state.fit.audio.close().catch(()=>{});
  }
  state.fit.audio=null;
  state.fit.analyser=null;
  state.fit.active=false;
  state.fit.source="idle";
  setFitStatus("idle");
  renderFitter();
}

function freezeFit(){
  if(state.fit.timer) clearTimeout(state.fit.timer);
  state.fit.timer=null;
  for(const node of state.fit.nodes){
    try{ node.stop?.(); }catch(_){}
    try{ node.disconnect?.(); }catch(_){}
  }
  state.fit.nodes=[];
  if(state.fit.stream){
    for(const track of state.fit.stream.getTracks()) track.stop();
  }
  state.fit.stream=null;
  if(state.fit.audio){
    state.fit.audio.close().catch(()=>{});
  }
  state.fit.audio=null;
  state.fit.analyser=null;
  state.fit.active=false;
  state.fit.source="frozen";
  setFitStatus("frozen");
  renderFitter();
}

function makeAnalyser(audio){
  const analyser=audio.createAnalyser();
  analyser.fftSize=LPC_FRAME;
  analyser.smoothingTimeConstant=.2;
  state.fit.analyser=analyser;
  return analyser;
}

function startFitLoop(){
  if(state.fit.timer) clearTimeout(state.fit.timer);
  state.fit.active=true;
  const tick=async()=>{
    if(!state.fit.active || !state.fit.analyser) return;
    try{
      state.fit.poles=poleSamplesFromAnalyser();
      setFitStatus(state.fit.source);
      renderFitter();
    }catch(err){
      setFitStatus("fit error");
      setStatus(`lpc failed: ${err.message}`);
    }
    state.fit.timer=setTimeout(tick,180);
  };
  tick();
}

async function startMicFit(){
  stopFit();
  const audio=new AudioContext();
  await audio.resume();
  const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false}});
  const src=audio.createMediaStreamSource(stream);
  src.connect(makeAnalyser(audio));
  state.fit.audio=audio;
  state.fit.stream=stream;
  state.fit.nodes=[src];
  state.fit.source="mic";
  startFitLoop();
}

async function startTestFit(){
  stopFit();
  state.fit.source="test";
  state.fit.active=true;
  const tick=async()=>{
    if(!state.fit.active || state.fit.source!=="test") return;
    state.fit.poles=polesAndZerosFromSamples(syntheticFitFrame(),SR);
    setFitStatus("test");
    renderFitter();
    state.fit.timer=setTimeout(tick,180);
  };
  tick();
}

function syntheticFitFrame(){
  const out=new Float32Array(LPC_FRAME);
  const freqs=[170,430,910,1850,3900,7900];
  const amps=[.7,.5,.45,.32,.22,.16];
  for(let i=0;i<out.length;i++){
    const t=(state.fit.syntheticT+i)/SR;
    let v=0;
    for(let k=0;k<freqs.length;k++){
      v+=amps[k]*Math.sin(2*Math.PI*freqs[k]*t + k*.7);
    }
    v+=.025*Math.sin(2*Math.PI*53*t);
    out[i]=v*.22;
  }
  state.fit.syntheticT+=out.length;
  return out;
}

function xFor(f,w){ return 48+(Math.log(clamp(f,F_LO,F_HI))-Math.log(F_LO))/(Math.log(F_HI)-Math.log(F_LO))*(w-70); }
function fFor(x,w){ return Math.exp(Math.log(F_LO)+clamp((x-48)/(w-70),0,1)*(Math.log(F_HI)-Math.log(F_LO))); }
function yFor(db,h){ return 18+(1-(clamp(db,DB_LO,DB_HI)-DB_LO)/(DB_HI-DB_LO))*(h-48); }
function dbFor(y,h){ return DB_LO+(1-clamp((y-18)/(h-48),0,1))*(DB_HI-DB_LO); }
function canvasPoint(e){
  const r=canvas.getBoundingClientRect();
  return {x:(e.clientX-r.left)*canvas.width/r.width,y:(e.clientY-r.top)*canvas.height/r.height};
}

function liveDb(f,m=state.m,q=state.q){
  if(!state.words) return 0;
  return packedDb(state.words,m,q,f);
}

function drawGrid(w,h){
  ctx.fillStyle="#f7f3eb"; ctx.fillRect(0,0,w,h);
  ctx.strokeStyle="#e0d7c8"; ctx.lineWidth=1;
  ctx.font="13px Consolas, monospace"; ctx.fillStyle="#81786c";
  for(const db of [24,12,0,-12,-24]){
    const y=yFor(db,h);
    ctx.beginPath(); ctx.moveTo(48,y); ctx.lineTo(w-22,y); ctx.stroke();
    ctx.textAlign="right"; ctx.fillText((db>0?"+":"")+db,40,y+4);
  }
  for(const f of [50,100,200,500,1000,2000,5000,10000]){
    const x=xFor(f,w);
    ctx.beginPath(); ctx.moveTo(x,18); ctx.lineTo(x,h-30); ctx.stroke();
    ctx.textAlign="center"; ctx.fillText(f>=1000?`${f/1000}k`:String(f),x,h-9);
  }
}

function drawCurve(m,q,color,width){
  const w=canvas.width,h=canvas.height;
  ctx.strokeStyle=color; ctx.lineWidth=width; ctx.beginPath();
  for(let i=0;i<520;i++){
    const t=i/519;
    const f=Math.exp(Math.log(F_LO)+t*(Math.log(F_HI)-Math.log(F_LO)));
    const x=xFor(f,w), y=yFor(liveDb(f,m,q),h);
    if(i) ctx.lineTo(x,y); else ctx.moveTo(x,y);
  }
  ctx.stroke();
}

function stagePoint(s){
  return {x:xFor(s.hz,canvas.width),y:yFor(liveDb(s.hz,state.corner&1,state.corner>>1),canvas.height)};
}
function cutPoint(s){
  const curveDb=liveDb(s.cutHz,state.m,state.q);
  return {x:xFor(s.cutHz,canvas.width),y:yFor(curveDb - s.cutDepth*18,canvas.height)};
}

function drawStageMarkers(){
  const corner=state.corners[state.corner];
  for(let i=0;i<6;i++){
    const s=corner[i];
    if(!s.on) continue;
    const p=stagePoint(s), selected=i===state.stage;
    ctx.strokeStyle=COLORS[i]; ctx.fillStyle=COLORS[i]; ctx.lineWidth=selected?3:1.5;
    ctx.globalAlpha=selected?1:.62;
    ctx.beginPath(); ctx.arc(p.x,p.y,selected?8:6,0,Math.PI*2); ctx.fill();
    ctx.strokeStyle="#15130f"; ctx.stroke();
    if(s.cutOn){
      const c=cutPoint(s);
      ctx.strokeStyle="#c52f4d"; ctx.fillStyle="#fff7ee"; ctx.globalAlpha=selected?.75:.35; ctx.setLineDash([3,4]);
      ctx.beginPath(); ctx.moveTo(c.x,yFor(liveDb(s.cutHz,state.m,state.q),canvas.height)); ctx.lineTo(c.x,c.y); ctx.stroke();
      ctx.globalAlpha=1; ctx.setLineDash([]); ctx.lineWidth=selected?2.5:1.5;
      ctx.beginPath(); ctx.arc(c.x,c.y,selected?7:5,0,Math.PI*2); ctx.fill(); ctx.stroke();
    }
  }
  const sel=state.stage;
  for(let c=0;c<4;c++){
    if(c===state.corner) continue;
    const s=state.corners[c][sel];
    if(!s.on) continue;
    const p=stagePoint(s);
    ctx.globalAlpha=.22; ctx.fillStyle=COLORS[sel];
    ctx.fillRect(p.x-4,p.y-4,8,8);
  }
  ctx.globalAlpha=1;
}

function drawPlot(){
  const w=canvas.width,h=canvas.height;
  drawGrid(w,h);
  drawCurve(0,0,"rgba(210,75,63,.23)",1.3);
  drawCurve(1,0,"rgba(63,123,176,.18)",1.3);
  drawCurve(0,1,"rgba(91,163,90,.18)",1.3);
  drawCurve(1,1,"rgba(140,107,184,.18)",1.3);
  drawCurve(state.m,state.q,"#15130f",2.6);
  drawStageMarkers();
}

function renderTop(){
  $("cornerTabs").innerHTML=[0,1,2,3].map(i=>`<button class="${i===state.corner?"on":""}" data-corner="${i}">C${i}</button>`).join("");
  $("cornerTabs").querySelectorAll("button").forEach(b=>b.onclick=()=>{ state.corner=+b.dataset.corner; render(); });
  $("linkCorners").checked=state.linkCorners;
  $("mOut").textContent=Math.round(state.m*100);
  $("qOut").textContent=Math.round(state.q*100);
  const l=$("light");
  l.className="light"+(state.worstR>=1?" bad":state.worstR>=.999?" warn":"");
}

function renderStagePicker(){
  $("stageSelect").innerHTML=state.corners[state.corner].map((s,i)=>{
    const name=s.label || `stage ${i+1}`;
    return `<option value="${i}" ${i===state.stage?"selected":""}>${i+1}</option>`;
  }).join("");
  $("shapeSelect").value=stage().on ? "eq" : "off";
  const s=stage();
  const path=state.corners.map((corner,ci)=>{
    const cs=corner[state.stage];
    return `<button class="cornerCell ${ci===state.corner?"on":""}" data-corner-cell="${ci}"><b>C${ci}</b><span>${cs.on?hzText(cs.hz):"off"}</span><span>${cs.cutOn?`cut ${hzText(cs.cutHz)}`:"cut off"}</span></button>`;
  }).join("");
  $("stageReadout").innerHTML=s.on
    ? `<div>stage ${state.stage+1}${s.label?` / ${s.label}`:""}</div><div>${hzText(s.hz)} Hz / ${s.gainDb.toFixed(1)} dB / ${s.r.toFixed(4)}</div><div class="traj">${path}</div>`
    : `<div>stage ${state.stage+1}</div><div>off</div><div class="traj">${path}</div>`;
  $("stageSelect").onchange=()=>{ state.stage=+$("stageSelect").value; render(); };
  $("stageReadout").querySelectorAll("[data-corner-cell]").forEach(btn=>btn.onclick=()=>{
    state.corner=+btn.dataset.cornerCell;
    render();
  });
  $("shapeSelect").onchange=async e=>{
    const s=stage();
    s.on=e.target.value!=="off";
    if(s.on) s.cutHz=s.cutHz||s.hz*.75;
    syncLinkedStage();
    await repack();
  };
}

function renderEditor(){
  const s=stage();
  $("stageEditor").innerHTML=`
    <div class="field"><span>Freq</span><input id="edHz" type="range" min="20" max="19500" value="${Math.round(s.hz)}"><output>${hzText(s.hz)}</output></div>
    <div class="field"><span>Gain</span><input id="edGain" type="range" min="-24" max="24" step="0.1" value="${s.gainDb}"><output>${s.gainDb.toFixed(1)}</output></div>
    <div class="field"><span>Radius</span><input id="edR" type="range" min="0.5" max="0.9999" step="0.0001" value="${s.r}"><output>${s.r.toFixed(4)}</output></div>
    <label class="check"><input id="edCutOn" type="checkbox" ${s.cutOn?"checked":""}> cut</label>
    <div class="field"><span>Cut</span><input id="edCutHz" type="range" min="20" max="19500" value="${Math.round(s.cutHz)}"><output>${hzText(s.cutHz)}</output></div>
    <div class="field"><span>Cut R</span><input id="edDepth" type="range" min="0" max="0.9999" step="0.0001" value="${s.cutDepth}"><output>${s.cutDepth.toFixed(4)}</output></div>
  `;
  $("edHz").oninput=async e=>{ s.hz=+e.target.value; if(!s.cutOn) s.cutHz=s.hz*.75; syncLinkedStage(); await repack(); };
  $("edGain").oninput=async e=>{ s.gainDb=+e.target.value; syncLinkedStage(); await repack(); };
  $("edR").oninput=async e=>{ s.r=+e.target.value; syncLinkedStage(); await repack(); };
  $("edCutOn").onchange=async e=>{ s.cutOn=e.target.checked; if(!s.on) s.on=true; syncLinkedStage(); await repack(); };
  $("edCutHz").oninput=async e=>{ s.cutHz=+e.target.value; syncLinkedStage(); await repack(); };
  $("edDepth").oninput=async e=>{ s.cutDepth=+e.target.value; syncLinkedStage(); await repack(); };
}

function renderMore(){
  const cells=[];
  if(state.words){
    for(let qi=0;qi<=16;qi++){
      for(let mi=0;mi<=16;mi++){
        const rows=wordsAt(state.words,mi/16,qi/16);
        let r=0;
        for(const row of rows){
          const bq=kernelToBiquad(stageWordsToKernel(row));
          r=Math.max(r,poleRadius(bq[3],bq[4]));
        }
        cells.push(`<div class="cell ${r>=1?"bad":r>=.999?"warn":""}"></div>`);
      }
    }
  }
  $("moreBody").innerHTML=`<div>max ${state.worstR.toFixed(6)}</div><div>${state.hex.length/2} bytes</div><div class="auditGrid">${cells.join("")}</div>`;
}

function renderFitter(){
  $("fitState").textContent=state.fit.status;
  $("fitZeros").checked=state.fit.zerosLive;
  $("fitPoles").innerHTML=state.fit.poles.length
    ? state.fit.poles.slice(0,LPC_STAGES).map((p,i)=>`<div class="fitPole">${i+1} ${hzText(p.hz)}</div><div class="fitPole">cut ${hzText(p.cutHz ?? ZERO_END)}</div><div class="fitPole">${p.r.toFixed(4)}</div>`).join("")
    : `<div class="fitPole">no poles</div><div class="fitPole">no cuts</div><div class="fitPole">start</div>`;
  $("fitZeros").onchange=e=>{ state.fit.zerosLive=e.target.checked; };
  $("micBtn").onclick=async()=>{
    try{
      await startMicFit();
      setStatus("lpc mic running");
    }catch(err){
      setFitStatus("mic blocked");
      setStatus(`mic failed: ${err.message}`);
    }
  };
  $("testBtn").onclick=async()=>{
    try{
      await startTestFit();
      setStatus("lpc test source running");
    }catch(err){
      setFitStatus("test failed");
      setStatus(`test source failed: ${err.message}`);
    }
  };
  $("fitFreezeBtn").onclick=()=>freezeFit();
  $("fitStopBtn").onclick=()=>stopFit();
  $("fitClearBtn").onclick=()=>{
    stopFit();
    state.fit.poles=[];
    setFitStatus("idle");
    renderFitter();
    setStatus("fitter cleared");
  };
  $("fitPlaceBtn").onclick=async()=>{
    await applyFitPolesToCorner();
    setStatus("placed lpc poles");
  };
}

function render(){
  renderTop();
  renderFitter();
  renderStagePicker();
  renderEditor();
  renderMore();
  drawPlot();
}

function hitTest(pt){
  const corner=state.corners[state.corner];
  for(let i=0;i<6;i++){
    const s=corner[i];
    if(!s.on) continue;
    if(s.cutOn){
      const c=cutPoint(s);
      if(Math.hypot(c.x-pt.x,c.y-pt.y)<12) return {kind:"cut",stage:i};
    }
    const p=stagePoint(s);
    if(Math.hypot(p.x-pt.x,p.y-pt.y)<14) return {kind:"pole",stage:i};
  }
  return null;
}

canvas.addEventListener("pointerdown",e=>{
  const pt=canvasPoint(e), h=hitTest(pt);
  if(!h) return;
  state.stage=h.stage;
  state.drag={...h};
  canvas.setPointerCapture(e.pointerId);
  render();
});
canvas.addEventListener("pointermove",async e=>{
  if(!state.drag) return;
  const pt=canvasPoint(e), s=stage(state.corner,state.drag.stage);
  if(state.drag.kind==="pole"){
    s.hz=fFor(pt.x,canvas.width);
    s.gainDb=clamp(dbFor(pt.y,canvas.height),-24,24);
  }else{
    s.cutHz=fFor(pt.x,canvas.width);
    const curveDb=liveDb(s.cutHz,state.m,state.q);
    s.cutDepth=clamp((curveDb-dbFor(pt.y,canvas.height))/18,0,0.9999);
  }
  syncLinkedStage(state.drag.stage);
  await repack();
});
canvas.addEventListener("pointerup",()=>{ state.drag=null; });
canvas.addEventListener("wheel",async e=>{
  const pt=canvasPoint(e), h=hitTest(pt);
  if(!h || h.kind!=="pole") return;
  e.preventDefault();
  state.stage=h.stage;
  const s=stage();
  s.r=clamp(s.r + (e.deltaY<0?.006:-.006),0.5,0.9999);
  syncLinkedStage();
  await repack();
},{passive:false});

$("morph").oninput=()=>{ state.m=+$("morph").value/100; renderTop(); drawPlot(); };
$("q").oninput=()=>{ state.q=+$("q").value/100; renderTop(); drawPlot(); };
$("linkCorners").onchange=async e=>{
  state.linkCorners=e.target.checked;
  if(state.linkCorners){
    const src=state.corners[state.corner].map(cloneStage);
    for(let c=0;c<4;c++) state.corners[c]=src.map(cloneStage);
    await repack();
    setStatus("all C linked");
  }else{
    renderTop();
    setStatus("editing current C only");
  }
};
$("saveBtn").onclick=()=>{
  downloadBody(`${state.name}.body240`,state.hex);
  setStatus(`saved ${state.name}.body240`);
};
$("keepBtn").onclick=()=>{
  downloadText(`${state.name}.json`,JSON.stringify(modelJson(),null,2));
  setStatus(`kept ${state.name}.json`);
};
$("openBtn").onclick=()=>$("openFile").click();
$("openFile").onchange=async()=>{
  const file=$("openFile").files[0];
  if(!file) return;
  const doc=JSON.parse(await file.text());
  if(doc.format!=="df2-forge-edit-v1" || !Array.isArray(doc.corners)) throw new Error("not a forge edit json");
  state.name=doc.name||"untitled";
  state.corners=doc.corners;
  state.corner=0; state.stage=0;
  await repack();
  setStatus(`opened ${state.name}`);
};
$("resetBtn").onclick=async()=>{
  resetToSystem();
  await repack();
  setStatus(`reset · ${state.hex.length/2} bytes · ${state.worstR>=1?"bad":state.worstR>=.999?"edge":"runs"}`);
};

state.corners=makeBlank();
resetToSystem();
repack().catch(err=>setStatus(`pack failed: ${err.message}`));
