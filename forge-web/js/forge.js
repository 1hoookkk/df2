/* df2 forge - painter-only picker + player.
   Pick two real-physics frames, watch the morph, save the body. Everything on
   one canvas: hand-drawn, hit-tested. No HTML widgets. Plot is engine-faithful
   (packed.js word-space morph). */
import {FRAMES} from "../data/frames.js";
import {TARGETS} from "../data/targets.js";   // dev study yardstick (behaviour samples, not coeffs)
import {PACKED_BODIES} from "../data/packed-bodies.js";
import {stageWordsToKernel,kernelToBiquad,biquadDbCoeffs,wordsAt,packedDb,hexFromWords,bytesFromHex,downloadBody} from "./packed.js";

const SR=39062.5;
const F_LO=30, F_HI=18000, DB_LO=-40, DB_HI=26;
const GROUND="#0d0e11", PANEL="#15171b", LINE="#24272d", DIM="#5a606a",
      MID="#878d97", INK="#c4cad2", ACCENT="#e8923a", WARN="#d6564c", GOOD="#5fae6e";
const LAW={
  paper:"#f2eee5", panel:"#fffaf0", plot:"#f8f3ea", ink:"#17140f",
  muted:"#746b5f", line:"#cfc4b3", soft:"#e4d8c7", hot:"#ef4b22",
  pole:"#b54e2e", zero:"#147a73", ok:"#237a4d", warn:"#c38319", bad:"#b93434",
  blue:"#3f6f9a"
};
const STAGE_COLORS=["#d24b3f","#e09a2e","#5ba35a","#3f9690","#4f7bb0","#8c6bb8"];
const PHONE_W=700;

const cv=document.getElementById("c"), ctx=cv.getContext("2d");
let W=0,H=0,dpr=1;

const state={view:"law", A:null, B:null, armed:"A", morph:0, q:0, playing:false, drag:null, hot:null, t:0, target:null};

// ---- measurement: distance to a reference target (study yardstick) ------
const NS=128;
const SAMP=Array.from({length:NS},(_,i)=>F_LO*Math.pow(F_HI/F_LO,i/(NS-1)));
function targetCurve(tg,m,q){
  const mi=Math.min(1.999,m*2), qi=Math.min(1.999,q*2);
  const m0=Math.floor(mi),q0=Math.floor(qi),mf=mi-m0,qf=qi-q0,g=tg.grid,out=new Array(NS);
  for(let k=0;k<NS;k++){
    const a=g[m0][q0][k]*(1-qf)+g[m0][q0+1][k]*qf;
    const b=g[m0+1][q0][k]*(1-qf)+g[m0+1][q0+1][k]*qf;
    out[k]=a*(1-mf)+b*mf;
  }
  return out;
}
const mean=c=>c.reduce((a,b)=>a+b,0)/c.length;
const norm=c=>{const m=mean(c);return c.map(v=>v-m);};
function band(c,lo,hi){let s=0,n=0;for(let k=0;k<NS;k++)if(SAMP[k]>=lo&&SAMP[k]<=hi){s+=c[k];n++;}return n?s/n:0;}
function pkN(c,up){let n=0;for(let k=2;k<NS-2;k++){const e=up?(c[k]>c[k-1]&&c[k]>=c[k+1]&&c[k]-Math.min(c[k-2],c[k+2])>3):(c[k]<c[k-1]&&c[k]<=c[k+1]&&Math.max(c[k-2],c[k+2])-c[k]>3);if(e)n++;}return n;}
function metrics(cn,tg,m,q){
  const Lr=SAMP.map(f=>packedDb(cn,m,q,f)), Tr=targetCurve(tg,m,q);
  const L=norm(Lr), T=norm(Tr);
  let se=0,mx=0;for(let k=0;k<NS;k++){const d=L[k]-T[k];se+=d*d;mx=Math.max(mx,Math.abs(d));}
  return {rms:Math.sqrt(se/NS),mx,
    body:band(L,F_LO,300)-band(T,F_LO,300),
    tilt:(band(L,50,300)-band(L,4000,16000))-(band(T,50,300)-band(T,4000,16000)),
    pkL:pkN(L,1),pkT:pkN(T,1),nL:pkN(L,0),nT:pkN(T,0),
    Tr, offset:mean(Lr)-mean(Tr)};
}

// ---- frame helpers ------------------------------------------------------
function frameDb(frame,f){
  let s=0;
  for(const row of frame.words) s+=biquadDbCoeffs(kernelToBiquad(stageWordsToKernel(row)),f);
  return s;
}
function corners(){ // 4-corner body from the A/B pairing: Q lerps toward the hiQ siblings
  const {A,B}=state; if(!A||!B) return null;
  return {M0_Q0:A.words, M100_Q0:B.words, M0_Q100:A.wordsHiQ, M100_Q100:B.wordsHiQ};
}

// ---- live audio: WASM trench-core engine (filter + AGC + Mackie sat + QSound) --
let audioCtx=null, anode=null;
state.src=0;
const SRC_NAMES=["saw","noise","808","voice"];
function bodyBytes(){ const cn=corners(); return cn?bytesFromHex(hexFromWords(cn)):null; }
function pushParams(){
  if(anode) anode.port.postMessage({params:{morph:state.morph,q:state.q,agc:3.5,slam:0.35+0.45*state.q,wide:0.0}});
}
function pushBody(){ const b=bodyBytes(); if(anode&&b) anode.port.postMessage({body:b.buffer.slice(0)}); }
async function startAudio(){
  audioCtx=new (window.AudioContext||window.webkitAudioContext)();
  const wasm=await (await fetch("wasm/forge_web_wasm.wasm")).arrayBuffer();
  await audioCtx.audioWorklet.addModule("js/forge-worklet.js");
  const body=bodyBytes();
  anode=new AudioWorkletNode(audioCtx,"forge-processor",{
    numberOfInputs:0, numberOfOutputs:1, outputChannelCount:[2],
    processorOptions:{ wasm, body: body?body.buffer.slice(0):null, src:state.src }
  });
  anode.port.onmessage=e=>{
    if(e.data.ready){ pushParams(); if(state.playing) anode.port.postMessage({playing:true}); }
    if(e.data.error){ setStatus("audio: "+e.data.error); }
  };
  anode.connect(audioCtx.destination);
}
async function toggleAudio(){
  try{
    if(!audioCtx) await startAudio();
    if(audioCtx.state==="suspended") await audioCtx.resume();
    state.playing=!state.playing;
    if(anode) anode.port.postMessage({playing:state.playing});
  }catch(err){ setStatus("audio failed: "+err.message); state.playing=false; }
  draw();
}
function cycleSrc(){ state.src=(state.src+1)%4; if(anode) anode.port.postMessage({src:state.src}); }
function setStatus(t){ console.log(t); }
function worstRadius(words,m,q){
  let worst=0;
  for(const row of wordsAt(words,m,q)){
    const bq=kernelToBiquad(stageWordsToKernel(row));
    const a1=bq[3],a2=bq[4],disc=a1*a1-4*a2;
    const r=disc<0?Math.sqrt(Math.max(0,a2)):Math.max(Math.abs((-a1+Math.sqrt(disc))/2),Math.abs((-a1-Math.sqrt(disc))/2));
    worst=Math.max(worst,r);
  }
  return worst;
}
// centroid -> hue: low freq warm (red/orange), high freq cool (cyan/violet)
function hueFor(cen){
  const t=Math.max(0,Math.min(1,(Math.log(cen)-Math.log(60))/(Math.log(16000)-Math.log(60))));
  return 14+t*250;
}
function frameColor(frame,l=58,s=68){ return frame?`hsl(${hueFor(frame.centroid)},${s}%,${l}%)`:DIM; }
const hz=v=>v>=1000?`${(v/1000).toFixed(v>=10000?0:1)}k`:`${Math.round(v)}`;

// ---- Law Author audit surface ------------------------------------------
const LAW_BODY=PACKED_BODIES.lawAuthorGolden;
const LAW_STAGE_KEYS=["M0_S0","M1_S0","M0_S1","M1_S1"];
const LAW_CORNER_LABELS=["M0 S0","M1 S0","M0 S1","M1 S1"];
const LAW_CURVES=[[0,0],[1,0],[0,1],[1,1]];
const LAW_DB_LO=-100, LAW_DB_HI=28;
let lawCache=null;

function log2safe(v){ return Math.log(Math.max(1e-6,v))/Math.log(2); }
function lawInfo(){
  if(lawCache) return lawCache;
  const body=LAW_BODY;
  const stages=body?.stages || {};
  let remote=0,total=0;
  const motion=[];
  for(const key of LAW_STAGE_KEYS){
    for(const row of stages[key] || []){
      if(row.pole_hz>0 && row.zero_hz>0){
        total++;
        if(Math.abs(log2safe(row.zero_hz/row.pole_hz))>1.5) remote++;
      }
    }
  }
  for(const pair of [["M0_S0","M1_S0"],["M0_S1","M1_S1"]]){
    const a=stages[pair[0]] || [], b=stages[pair[1]] || [];
    for(let i=0;i<Math.min(a.length,b.length);i++){
      const poleMove=Math.abs(log2safe(b[i].pole_hz/a[i].pole_hz));
      const zeroMove=Math.abs(log2safe(b[i].zero_hz/a[i].zero_hz));
      motion.push(Math.abs(zeroMove-poleMove));
    }
  }
  const freqs=Array.from({length:96},(_,i)=>F_LO*Math.pow(F_HI/F_LO,i/95));
  const center=freqs.map(f=>packedDb(body.words,.5,.5,f));
  const cornerMean=freqs.map(f=>{
    let s=0;
    for(const [m,q] of LAW_CURVES) s+=packedDb(body.words,m,q,f);
    return s/LAW_CURVES.length;
  });
  const centerSag=mean(center.map((v,i)=>v-cornerMean[i]));
  const checks=body?.audit?.checks || {};
  lawCache={
    stages,
    verdict:body?.audit?.verdict || (body?.audit?.warnings?.length ? "WARN" : "PASS"),
    maxRadius:checks.max_pole_radius || 0,
    tiltSpan:checks.tilt_span_db || 0,
    bodyBytes:body?.body240Bytes || 0,
    remoteFraction:total ? remote/total : 0,
    remoteCount:remote,
    totalRows:total,
    zeroMotion:motion.length ? mean(motion) : 0,
    centerSag,
    center,
    cornerMean,
    freqs,
  };
  return lawCache;
}
function lawFx(f,r){ return r.x+(Math.log(Math.max(F_LO,Math.min(F_HI,f)))-Math.log(F_LO))/(Math.log(F_HI)-Math.log(F_LO))*r.w; }
function lawFy(db,r){ return r.y+(1-(Math.max(LAW_DB_LO,Math.min(LAW_DB_HI,db))-LAW_DB_LO)/(LAW_DB_HI-LAW_DB_LO))*r.h; }
function lawPanel(r,title){
  fillR(r.x,r.y,r.w,r.h,LAW.panel,4);
  strokeR(r.x,r.y,r.w,r.h,LAW.line,4);
  if(title) text(title,r.x+10,r.y+15,LAW.ink,12,"left",true);
}
function lawButton(r,label,active=false){
  fillR(r.x,r.y,r.w,r.h,active?LAW.hot:LAW.panel,4);
  strokeR(r.x,r.y,r.w,r.h,active?LAW.hot:LAW.ink,4);
  text(label,r.x+r.w/2,r.y+r.h/2,active?"white":LAW.ink,12,"center",true);
}
function lawGrid(r){
  ctx.save();rr(r.x,r.y,r.w,r.h,4);ctx.clip();
  ctx.lineWidth=1;
  for(const f of [100,1000,10000]){
    const x=lawFx(f,r); ctx.strokeStyle=LAW.soft; ctx.beginPath(); ctx.moveTo(x,r.y); ctx.lineTo(x,r.y+r.h); ctx.stroke();
  }
  for(const db of [0,-24,-48,-72]){
    const y=lawFy(db,r); ctx.strokeStyle=db===0?LAW.line:LAW.soft; ctx.beginPath(); ctx.moveTo(r.x,y); ctx.lineTo(r.x+r.w,y); ctx.stroke();
  }
  ctx.restore();
}
function lawCurve(r,dbs,color,width,dash=false){
  const info=lawInfo();
  ctx.save();rr(r.x,r.y,r.w,r.h,4);ctx.clip();
  ctx.strokeStyle=color;ctx.lineWidth=width;if(dash)ctx.setLineDash([5,4]);
  ctx.beginPath();
  info.freqs.forEach((f,i)=>{const x=lawFx(f,r), y=lawFy(dbs[i],r); i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
  ctx.stroke();ctx.setLineDash([]);ctx.restore();
}
function drawLawResponse(r){
  lawPanel(r,"packed response");
  const plot={x:r.x+9,y:r.y+26,w:r.w-18,h:r.h-38};
  fillR(plot.x,plot.y,plot.w,plot.h,LAW.plot,4); lawGrid(plot);
  const body=LAW_BODY;
  const cornerColors=["#9b8a76","#b59d7a","#7a9a91","#8a7aa8"];
  LAW_CURVES.forEach(([m,q],idx)=>{
    const dbs=lawInfo().freqs.map(f=>packedDb(body.words,m,q,f));
    lawCurve(plot,dbs,cornerColors[idx],1.2,true);
  });
  lawCurve(plot,lawInfo().center,LAW.hot,2.5,false);
  text("M50 S50",plot.x+10,plot.y+14,LAW.hot,11,"left",true);
  text(`center sag ${lawInfo().centerSag.toFixed(1)} dB`,plot.x+10,plot.y+30,LAW.muted,11);
  text("100",plot.x+3,plot.y+plot.h-4,LAW.muted,10);
  text("1k",lawFx(1000,plot),plot.y+plot.h-4,LAW.muted,10,"center");
  text("10k",lawFx(10000,plot),plot.y+plot.h-4,LAW.muted,10,"center");
}
function heatColor(v,bad){
  if(bad) return LAW.bad;
  const t=Math.max(0,Math.min(1,(v-.9988)/(.9999-.9988)));
  if(t<.55) return `rgb(${Math.round(35+t*210)},${Math.round(122-t*18)},${Math.round(77-t*48)})`;
  return `rgb(${Math.round(205+t*40)},${Math.round(131-(t-.55)*190)},${Math.round(25-(t-.55)*35)})`;
}
function drawLawHeat(r){
  lawPanel(r,"max-radius grid");
  const audit=LAW_BODY.audit || {}, grid=audit.grid || [], n=audit.grid_n || Math.round(Math.sqrt(grid.length));
  const gx=r.x+12, gy=r.y+28, gw=r.w-24, gh=r.h-48, gap=2;
  const cw=(gw-gap*(n-1))/n, ch=(gh-gap*(n-1))/n;
  for(const cell of grid){
    const x=gx+cell.morph*(n-1)*(cw+gap);
    const y=gy+cell.secondary*(n-1)*(ch+gap);
    fillR(x,y,cw,ch,heatColor(cell.max_pole_radius,cell.unstable_mask||cell.nonfinite_mask),1);
  }
  text("Morph",gx+gw/2,r.y+r.h-12,LAW.muted,10,"center");
  text("Q",gx-4,gy+4,LAW.muted,10,"right");
  text(`max r ${lawInfo().maxRadius.toFixed(6)}`,r.x+r.w-10,r.y+15,lawInfo().maxRadius>=.9999?LAW.warn:LAW.ok,11,"right",true);
}
function drawLawStats(r){
  lawPanel(r,"runtime verdict");
  const info=lawInfo();
  const stats=[
    ["verdict",info.verdict,info.verdict==="PASS"?LAW.ok:LAW.warn],
    ["body",`${info.bodyBytes} bytes`,info.bodyBytes===240?LAW.ok:LAW.bad],
    ["max r",info.maxRadius.toFixed(6),info.maxRadius<1?LAW.ok:LAW.bad],
    ["tilt span",`${info.tiltSpan.toFixed(1)} dB`,LAW.blue],
    ["remote zeros",`${info.remoteCount}/${info.totalRows}`,LAW.zero],
    ["zero motion",`${info.zeroMotion.toFixed(2)} oct`,LAW.zero],
  ];
  const cols=2, gap=7, cw=(r.w-20-gap)/cols, ch=31;
  stats.forEach((s,i)=>{
    const x=r.x+10+(i%cols)*(cw+gap), y=r.y+29+Math.floor(i/cols)*(ch+gap);
    fillR(x,y,cw,ch,LAW.plot,4); strokeR(x,y,cw,ch,LAW.soft,4);
    text(s[0],x+8,y+10,LAW.muted,10,"left",true);
    text(s[1],x+8,y+22,s[2],12,"left",true);
  });
}
function drawLawTracks(r){
  lawPanel(r,"pole / zero tracks");
  const info=lawInfo(), stages=info.stages;
  const plot={x:r.x+50,y:r.y+29,w:r.w-64,h:r.h-44};
  fillR(plot.x,plot.y,plot.w,plot.h,LAW.plot,4);
  for(const f of [100,300,1000,3000,10000]){
    const x=lawFx(f,plot); ctx.strokeStyle=LAW.soft; ctx.beginPath(); ctx.moveTo(x,plot.y); ctx.lineTo(x,plot.y+plot.h); ctx.stroke();
    text(hz(f),x,plot.y+plot.h+10,LAW.muted,9,"center");
  }
  for(let i=0;i<6;i++){
    const y=plot.y+(i+.5)*plot.h/6;
    ctx.strokeStyle=LAW.soft; ctx.beginPath(); ctx.moveTo(plot.x,y); ctx.lineTo(plot.x+plot.w,y); ctx.stroke();
    const role=(stages.M0_S0?.[i]?.role || `lane ${i+1}`).slice(0,12);
    text(`${i+1} ${role}`,r.x+8,y,LAW.muted,10,"left");
    for(const kind of ["pole","zero"]){
      ctx.strokeStyle=kind==="pole"?LAW.pole:LAW.zero;
      ctx.lineWidth=kind==="pole"?2:1.7;
      if(kind==="zero") ctx.setLineDash([4,3]);
      ctx.beginPath();
      LAW_STAGE_KEYS.forEach((key,j)=>{
        const row=stages[key]?.[i]; if(!row)return;
        const f=kind==="pole"?row.pole_hz:row.zero_hz;
        const x=lawFx(f,plot), yy=y-12+j*8;
        j?ctx.lineTo(x,yy):ctx.moveTo(x,yy);
      });
      ctx.stroke();ctx.setLineDash([]);
      LAW_STAGE_KEYS.forEach((key,j)=>{
        const row=stages[key]?.[i]; if(!row)return;
        const f=kind==="pole"?row.pole_hz:row.zero_hz;
        const x=lawFx(f,plot), yy=y-12+j*8;
        ctx.fillStyle=kind==="pole"?LAW.pole:LAW.zero;
        ctx.beginPath();ctx.arc(x,yy,2.7,0,Math.PI*2);ctx.fill();
      });
    }
  }
  text("pole",r.x+r.w-70,r.y+15,LAW.pole,10,"left",true);
  text("zero",r.x+r.w-36,r.y+15,LAW.zero,10,"left",true);
}
function drawLawTables(r){
  lawPanel(r,"four corner stage tables");
  const stages=lawInfo().stages, gap=7;
  const cols=W<PHONE_W?1:(W<1050?2:4);
  const rows=Math.ceil(LAW_STAGE_KEYS.length/cols);
  const tw=(r.w-20-gap*(cols-1))/cols, th=(r.h-31-gap*(rows-1))/rows;
  LAW_STAGE_KEYS.forEach((key,idx)=>{
    const x=r.x+10+(idx%cols)*(tw+gap), y=r.y+26+Math.floor(idx/cols)*(th+gap);
    fillR(x,y,tw,th,LAW.plot,4); strokeR(x,y,tw,th,LAW.soft,4);
    text(LAW_CORNER_LABELS[idx],x+7,y+12,LAW.ink,10,"left",true);
    const data=stages[key] || [];
    data.forEach((row,i)=>{
      const yy=y+29+i*((th-34)/6);
      const col=STAGE_COLORS[i%STAGE_COLORS.length];
      ctx.fillStyle=col;ctx.fillRect(x+7,yy-6,4,12);
      text(`${i+1}`,x+15,yy,LAW.muted,9,"left",true);
      text(`${hz(row.pole_hz)} r${row.pole_r.toFixed(3)}`,x+30,yy,LAW.pole,9);
      text(`${hz(row.zero_hz)} r${row.zero_r.toFixed(2)}`,x+Math.min(tw-74,112),yy,LAW.zero,9);
      text(row.gain.toFixed(2),x+tw-7,yy,LAW.muted,9,"right");
    });
  });
}
function lawLayout(){
  const mobile=W<PHONE_W;
  const pad=mobile?10:14, top=mobile?64:44, gap=mobile?8:10;
  const saveW=mobile?84:84, pickW=mobile?76:86;
  const save={x:W-pad-saveW,y:mobile?38:9,w:saveW,h:mobile?28:26};
  const pick={x:save.x-gap-pickW,y:mobile?38:9,w:pickW,h:mobile?28:26};
  let stats, heat, response, tracks;
  if(mobile){
    stats={x:pad,y:top,w:W-pad*2,h:132};
    response={x:pad,y:stats.y+stats.h+gap,w:W-pad*2,h:164};
    heat={x:pad,y:response.y+response.h+gap,w:W-pad*2,h:168};
    tracks={x:pad,y:heat.y+heat.h+gap,w:W-pad*2,h:238};
  }else if(W<980){
    const topW=(W-pad*2-gap)/2;
    stats={x:pad,y:top,w:topW,h:150};
    heat={x:pad+topW+gap,y:top,w:topW,h:150};
    response={x:pad,y:top+stats.h+gap,w:W-pad*2,h:150};
    tracks={x:pad,y:response.y+response.h+gap,w:W-pad*2,h:Math.max(160,Math.min(210,H*.24))};
  }else{
    stats={x:pad,y:top,w:Math.max(260,Math.min(360,W*.30)),h:150};
    heat={x:stats.x+stats.w+gap,y:top,w:Math.max(205,Math.min(270,W*.24)),h:150};
    response={x:heat.x+heat.w+gap,y:top,w:W-pad-(heat.x+heat.w+gap),h:150};
    tracks={x:pad,y:top+stats.h+gap,w:W-pad*2,h:Math.max(176,Math.min(230,H*.27))};
  }
  const tablesH=mobile?900:H-(tracks.y+tracks.h+gap)-pad;
  const tables={x:pad,y:tracks.y+tracks.h+gap,w:W-pad*2,h:tablesH};
  return {save,pick,stats,heat,response,tracks,tables};
}
function drawLaw(){
  ctx.setTransform(dpr,0,0,dpr,0,0);
  ctx.fillStyle=LAW.paper;ctx.fillRect(0,0,W,H);
  const L=lawLayout(); state._lawL=L;
  const info=lawInfo();
  if(W<PHONE_W){
    const compactName=W<460?"hedz_like_anchor":LAW_BODY.name;
    text("df2 Law Author",10,22,LAW.hot,15,"left",true);
    text(compactName,10,52,LAW.muted,11,"left");
    text(info.verdict,Math.min(W-176,160),22,info.verdict==="PASS"?LAW.ok:LAW.warn,12,"center",true);
  }else{
    text("df2 Law Author",14,23,LAW.hot,17,"left",true);
    text(LAW_BODY.name,166,23,LAW.muted,12,"left");
    text(info.verdict,Math.max(360,W/2),23,info.verdict==="PASS"?LAW.ok:LAW.warn,13,"center",true);
  }
  lawButton(L.pick,"picker",state.hot==="pick");
  lawButton(L.save,"body240",state.hot==="lawSave");
  drawLawStats(L.stats);
  drawLawHeat(L.heat);
  drawLawResponse(L.response);
  drawLawTracks(L.tracks);
  drawLawTables(L.tables);
}

// ---- layout (css px) ----------------------------------------------------
function layout(){
  const pad=14, top=46, gap=12;
  const stripH=118, ctrlH=40;
  const bodyTop=top, bodyBot=H-pad-stripH-gap-ctrlH-gap;
  const frameH=Math.round((bodyBot-bodyTop-gap)*0.52);
  const colW=(W-pad*2-gap)/2;
  const fA={x:pad,y:bodyTop,w:colW,h:frameH};
  const fB={x:pad+colW+gap,y:bodyTop,w:colW,h:frameH};
  const casc={x:pad,y:bodyTop+frameH+gap,w:W-pad*2,h:bodyBot-(bodyTop+frameH+gap)};
  const ctrlY=bodyBot+gap;
  const playW=80, srcW=66;
  const faderW=(W-pad*2-gap*3-playW-srcW)/2;
  const morph={x:pad,y:ctrlY,w:faderW,h:ctrlH};
  const qf={x:pad+faderW+gap,y:ctrlY,w:faderW,h:ctrlH};
  const srcBtn={x:pad+faderW*2+gap*2,y:ctrlY,w:srcW,h:ctrlH};
  const play={x:srcBtn.x+srcW+gap,y:ctrlY,w:playW,h:ctrlH};
  const strip={x:pad,y:ctrlY+ctrlH+gap,w:W-pad*2,h:stripH};
  const save={x:W-pad-72,y:9,w:72,h:26};
  const target={x:save.x-8-150,y:9,w:150,h:26};
  const law={x:target.x-8-86,y:9,w:86,h:26};
  return {fA,fB,casc,morph,qf,srcBtn,play,strip,save,target,law,pad,top};
}

// ---- low-level paint ----------------------------------------------------
function rr(x,y,w,h,r=4){ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();}
function fillR(x,y,w,h,c,r=4){ctx.fillStyle=c;rr(x,y,w,h,r);ctx.fill();}
function strokeR(x,y,w,h,c,r=4,lw=1){ctx.strokeStyle=c;ctx.lineWidth=lw;rr(x,y,w,h,r);ctx.stroke();}
function text(t,x,y,c=INK,sz=12,al="left",b=false){ctx.fillStyle=c;ctx.font=`${b?"600 ":""}${sz}px Consolas,monospace`;ctx.textAlign=al;ctx.textBaseline="middle";ctx.fillText(t,x,y);}
const fx=(f,r)=>r.x+(Math.log(Math.max(F_LO,Math.min(F_HI,f)))-Math.log(F_LO))/(Math.log(F_HI)-Math.log(F_LO))*r.w;
const fy=(db,r)=>r.y+(1-(Math.max(DB_LO,Math.min(DB_HI,db))-DB_LO)/(DB_HI-DB_LO))*r.h;

function curve(r,dbFn,color,width){
  ctx.strokeStyle=color;ctx.lineWidth=width;ctx.beginPath();
  const n=Math.max(80,Math.round(r.w));
  for(let i=0;i<n;i++){
    const t=i/(n-1), f=Math.exp(Math.log(F_LO)+t*(Math.log(F_HI)-Math.log(F_LO)));
    const x=r.x+t*r.w, y=fy(dbFn(f),r);
    i?ctx.lineTo(x,y):ctx.moveTo(x,y);
  }
  ctx.stroke();
}
function grat(r){
  ctx.save();rr(r.x,r.y,r.w,r.h,4);ctx.clip();
  ctx.lineWidth=1;
  for(const f of [100,1000,10000]){const x=fx(f,r);ctx.strokeStyle="#1b1e23";ctx.beginPath();ctx.moveTo(x,r.y);ctx.lineTo(x,r.y+r.h);ctx.stroke();}
  for(const db of [12,0,-12,-24]){const y=fy(db,r);ctx.strokeStyle=db===0?"#23272e":"#191c21";ctx.beginPath();ctx.moveTo(r.x,y);ctx.lineTo(r.x+r.w,y);ctx.stroke();}
  ctx.restore();
}

// ---- panels -------------------------------------------------------------
function framePanel(r,frame,slot){
  const armed=state.armed===slot;
  fillR(r.x,r.y,r.w,r.h,PANEL);
  grat(r);
  if(frame){
    const col=frameColor(frame);
    curve(r,f=>frameDb(frame,f),col,2.2);
    // soft fill under the curve
    ctx.save();rr(r.x,r.y,r.w,r.h,4);ctx.clip();
    ctx.globalAlpha=.12;ctx.fillStyle=col;
    ctx.beginPath();const n=Math.round(r.w);
    for(let i=0;i<n;i++){const t=i/(n-1),f=Math.exp(Math.log(F_LO)+t*(Math.log(F_HI)-Math.log(F_LO)));i?ctx.lineTo(r.x+t*r.w,fy(frameDb(frame,f),r)):ctx.moveTo(r.x,fy(frameDb(frame,f),r));}
    ctx.lineTo(r.x+r.w,r.y+r.h);ctx.lineTo(r.x,r.y+r.h);ctx.closePath();ctx.fill();ctx.restore();
    text(frame.source.replace(/_/g," "),r.x+10,r.y+15,INK,12,"left",true);
    text(`${hz(frame.centroid)} Hz`,r.x+10,r.y+31,frameColor(frame,66),11);
  }else{
    text("click a frame below",r.x+r.w/2,r.y+r.h/2,DIM,12,"center");
  }
  // slot chip
  const cw=22;
  fillR(r.x+r.w-cw-8,r.y+8,cw,18,armed?ACCENT:LINE,3);
  text(slot,r.x+r.w-cw-8+cw/2,r.y+8+9,armed?GROUND:MID,12,"center",true);
  strokeR(r.x,r.y,r.w,r.h,armed?ACCENT:LINE,4,armed?1.5:1);
}

function cascade(r){
  fillR(r.x,r.y,r.w,r.h,PANEL);
  grat(r);
  const cn=corners();
  const tg=state.target!=null?TARGETS[state.target]:null;
  if(cn){
    curve(r,f=>packedDb(cn,0,0,f),frameColor(state.A,40,40),1.2);
    curve(r,f=>packedDb(cn,1,0,f),frameColor(state.B,40,40),1.2);
    let M=null;
    if(tg){
      M=metrics(cn,tg,state.morph,state.q);
      // ghost target curve (level-aligned), dashed
      ctx.save();rr(r.x,r.y,r.w,r.h,4);ctx.clip();
      ctx.strokeStyle="#7d6a4a";ctx.lineWidth=1.6;ctx.setLineDash([5,4]);ctx.beginPath();
      for(let k=0;k<NS;k++){const x=r.x+k/(NS-1)*r.w,y=fy(M.Tr[k]+M.offset,r);k?ctx.lineTo(x,y):ctx.moveTo(x,y);}
      ctx.stroke();ctx.setLineDash([]);ctx.restore();
    }
    curve(r,f=>packedDb(cn,state.morph,state.q,f),INK,2.6);
    const wr=worstRadius(cn,state.morph,state.q);
    ctx.fillStyle=wr>=.999?WARN:GOOD;ctx.beginPath();ctx.arc(r.x+r.w-12,r.y+12,4,0,Math.PI*2);ctx.fill();
    if(M) drawMatch(r,tg,M);
  }else{
    text(tg?"pick two frames — match the dashed target":"pick two frames to morph between",r.x+r.w/2,r.y+r.h/2,DIM,12,"center");
  }
  text("morph",r.x+10,r.y+14,MID,11,"left",true);
  strokeR(r.x,r.y,r.w,r.h,LINE,4);
}
function drawMatch(r,tg,M){
  const x=r.x+r.w-200, y=r.y+10, lh=15;
  const rc=M.rms<3?GOOD:M.rms<8?ACCENT:WARN;
  const sg=v=>(v>=0?"+":"")+v.toFixed(0);
  text("match: "+tg.label,x,y,MID,11,"left",true);
  text(`rms ${M.rms.toFixed(1)}  max ${M.mx.toFixed(0)} dB`,x,y+lh,rc,12,"left",true);
  text(`body ${sg(M.body)}  tilt ${sg(M.tilt)} dB`,x,y+lh*2,Math.abs(M.body)<3&&Math.abs(M.tilt)<4?GOOD:ACCENT,11,"left");
  text(`peaks ${M.pkL}/${M.pkT}   notch ${M.nL}/${M.nT}`,x,y+lh*3,(M.nL<M.nT-1||M.pkL<M.pkT-1)?WARN:MID,11,"left");
}

function fader(r,label,val,color){
  fillR(r.x,r.y,r.w,r.h,PANEL);strokeR(r.x,r.y,r.w,r.h,LINE,4);
  const tx=r.x+12, tw=r.w-24, my=r.y+r.h/2+4;
  text(label,r.x+12,r.y+13,MID,11,"left",true);
  text(`${Math.round(val*100)}`,r.x+r.w-12,r.y+13,color,11,"right");
  ctx.strokeStyle="#2a2e35";ctx.lineWidth=3;ctx.lineCap="round";
  ctx.beginPath();ctx.moveTo(tx,my);ctx.lineTo(tx+tw,my);ctx.stroke();
  const kx=tx+val*tw;
  ctx.strokeStyle=color;ctx.beginPath();ctx.moveTo(tx,my);ctx.lineTo(kx,my);ctx.stroke();
  ctx.fillStyle=INK;ctx.beginPath();ctx.arc(kx,my,5,0,Math.PI*2);ctx.fill();
  return {tx,tw};
}
function button(r,label,active){
  fillR(r.x,r.y,r.w,r.h,active?ACCENT:PANEL,4);strokeR(r.x,r.y,r.w,r.h,active?ACCENT:LINE,4);
  text(label,r.x+r.w/2,r.y+r.h/2,active?GROUND:INK,12,"center",true);
}
function strip(r){
  fillR(r.x,r.y,r.w,r.h,PANEL);strokeR(r.x,r.y,r.w,r.h,LINE,4);
  text("quarry  low",r.x+10,r.y+13,MID,10,"left",true);
  text("high",r.x+r.w-10,r.y+13,MID,10,"right",true);
  const n=FRAMES.length, gap=4, x0=r.x+8, y0=r.y+22, tw=(r.w-16-gap*(n-1))/n, th=r.h-30;
  for(let i=0;i<n;i++){
    const f=FRAMES[i], tx=x0+i*(tw+gap), tr={x:tx,y:y0,w:tw,h:th};
    const sel=(f===state.A?"A":f===state.B?"B":null), hov=state.hot===("tile"+i);
    fillR(tx,y0,tw,th,"#101216",3);
    // sparkline
    ctx.save();rr(tx,y0,tw,th,3);ctx.clip();
    ctx.strokeStyle=frameColor(f,60);ctx.lineWidth=1.4;ctx.beginPath();
    const m=Math.max(16,Math.round(tw));
    for(let k=0;k<m;k++){const t=k/(m-1),fr=Math.exp(Math.log(F_LO)+t*(Math.log(F_HI)-Math.log(F_LO)));
      const yy=y0+th-(Math.max(DB_LO,Math.min(DB_HI,frameDb(f,fr))-DB_LO)/(DB_HI-DB_LO))*th;
      k?ctx.lineTo(tx+t*tw,yy):ctx.moveTo(tx,yy);}
    ctx.stroke();ctx.restore();
    strokeR(tx,y0,tw,th,sel?frameColor(f,70):hov?MID:"#23262c",3,sel?1.6:1);
    if(sel){fillR(tx+tw/2-7,y0-1,14,12,frameColor(f,62),2);text(sel,tx+tw/2,y0+5,GROUND,9,"center",true);}
  }
  r._tiles={x0,y0,tw,th,gap,n};
}

function draw(){
  if(state.view==="law"){ drawLaw(); return; }
  ctx.setTransform(dpr,0,0,dpr,0,0);
  ctx.fillStyle=GROUND;ctx.fillRect(0,0,W,H);
  const L=layout();
  text("df2 forge",L.pad,23,ACCENT,17,"left",true);
  text("pick A + B  ·  morph between  ·  Q sharpens",L.pad+108,23,DIM,11,"left");
  button(L.law,"law",state.hot==="law");
  button(L.target,state.target!=null?`◎ ${TARGETS[state.target].label}`:"target ·off",state.target!=null||state.hot==="target");
  button(L.save,"save",state.hot==="save");
  framePanel(L.fA,state.A,"A");
  framePanel(L.fB,state.B,"B");
  cascade(L.casc);
  state._mf=fader(L.morph,"MORPH",state.morph,ACCENT);state._mr=L.morph;
  state._qf=fader(L.qf,"Q",state.q,"#6fa8d0");state._qr=L.qf;
  button(L.srcBtn,SRC_NAMES[state.src],state.hot==="src");
  button(L.play,state.playing?"❚❚ stop":"▶ play",state.playing);
  strip(L.strip);
  state._L=L;
}

// ---- interaction --------------------------------------------------------
function inR(p,r){return p.x>=r.x&&p.x<=r.x+r.w&&p.y>=r.y&&p.y<=r.y+r.h;}
function pos(e){const b=cv.getBoundingClientRect();return {x:e.clientX-b.left,y:e.clientY-b.top};}
function tileAt(p){
  const r=state._L?.strip, t=r?._tiles; if(!t)return -1;
  if(p.y<t.y0||p.y>t.y0+t.th)return -1;
  const i=Math.floor((p.x-t.x0)/(t.tw+t.gap));
  if(i<0||i>=t.n)return -1;
  const tx=t.x0+i*(t.tw+t.gap); return (p.x>=tx&&p.x<=tx+t.tw)?i:-1;
}
function pickFrame(i){
  const f=FRAMES[i];
  if(state.armed==="A"){state.A=f;state.armed="B";}
  else{state.B=f;state.armed="A";}
  draw(); pushBody();    // live: reload the paired body into the engine
}
cv.addEventListener("pointerdown",e=>{
  const p=pos(e);
  if(state.view==="law"){
    const lawL=state._lawL; if(!lawL)return;
    if(inR(p,lawL.pick)){ state.view="picker"; state.hot=null; resize(); return; }
    if(inR(p,lawL.save)){ downloadBody(`${LAW_BODY.name}.body240`,LAW_BODY.body240Hex); return; }
    return;
  }
  const L=state._L; if(!L)return;
  if(inR(p,L.law)){ state.view="law"; state.hot=null; resize(); return; }
  if(inR(p,L.save)){ const cn=corners(); if(cn){downloadBody(`${state.A.id}_${state.B.id}.body240`,hexFromWords(cn));} return; }
  if(inR(p,L.target)){ state.target = (!TARGETS.length)?null : (state.target==null?0 : (state.target+1>=TARGETS.length?null:state.target+1)); draw(); return; }
  if(inR(p,L.fA)){state.armed="A";draw();return;}
  if(inR(p,L.fB)){state.armed="B";draw();return;}
  if(inR(p,L.srcBtn)){cycleSrc();draw();return;}
  if(inR(p,L.play)){toggleAudio();return;}
  if(inR(p,L.morph)){state.drag="morph";onDrag(p);cv.setPointerCapture(e.pointerId);return;}
  if(inR(p,L.qf)){state.drag="q";onDrag(p);cv.setPointerCapture(e.pointerId);return;}
  const ti=tileAt(p); if(ti>=0){pickFrame(ti);return;}
});
function onDrag(p){
  if(state.drag==="morph"){const f=state._mf;state.morph=Math.max(0,Math.min(1,(p.x-f.tx)/f.tw));}
  else if(state.drag==="q"){const f=state._qf;state.q=Math.max(0,Math.min(1,(p.x-f.tx)/f.tw));}
  draw(); pushParams();   // live: morph/q straight to the engine
}
cv.addEventListener("pointermove",e=>{
  const p=pos(e);
  if(state.view==="law"){
    const L=state._lawL; if(!L)return;
    let hot=null;
    if(inR(p,L.pick)) hot="pick"; else if(inR(p,L.save)) hot="lawSave";
    if(hot!==state.hot){state.hot=hot;cv.style.cursor=hot?"pointer":"default";draw();}
    return;
  }
  if(state.drag){onDrag(p);return;}
  const L=state._L;if(!L)return;
  let hot=null;
  if(inR(p,L.law))hot="law"; else if(inR(p,L.save))hot="save"; else if(inR(p,L.target))hot="target";
  else if(inR(p,L.srcBtn))hot="src"; else if(inR(p,L.play))hot="play";
  else {const ti=tileAt(p);if(ti>=0)hot="tile"+ti;}
  if(hot!==state.hot){state.hot=hot;cv.style.cursor=hot?"pointer":"default";draw();}
});
cv.addEventListener("pointerup",()=>{state.drag=null;});

// ---- play loop + resize -------------------------------------------------
// play now means LIVE AUDIO; morph/q are driven by hand off the sliders.
function frame(){ requestAnimationFrame(frame); }
function mobileLawHeight(width){
  const pad=10, top=64, gap=8;
  const statsH=132, responseH=164, heatH=168, tracksH=238, tablesH=900;
  return top+statsH+gap+responseH+gap+heatH+gap+tracksH+gap+tablesH+pad;
}
function desiredCanvasHeight(width, viewportHeight){
  if(width<PHONE_W && state.view==="law") return Math.max(viewportHeight, mobileLawHeight(width));
  if(width<PHONE_W) return Math.max(viewportHeight, 780);
  return viewportHeight;
}
function resize(){
  dpr=Math.min(2,window.devicePixelRatio||1);
  const cssW=Math.max(1,document.documentElement.clientWidth || window.innerWidth || cv.clientWidth);
  const viewportH=Math.max(1,window.innerHeight || document.documentElement.clientHeight || cv.clientHeight);
  const cssH=desiredCanvasHeight(cssW,viewportH);
  cv.style.height=`${cssH}px`;
  W=cv.clientWidth;H=cv.clientHeight;
  cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);
  draw();
}
window.addEventListener("resize",resize);
if(window.visualViewport) window.visualViewport.addEventListener("resize",resize);
resize();
requestAnimationFrame(frame);
