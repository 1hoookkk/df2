// df2 Fit My Voice — capture audio (mic / drop a .wav / IR), send to the PROVEN Python fitter
// (/fitbody: ARMA character with cavities + your CHOSEN foundation), get the packed body back, play it.
// No JS LPC, no JS packing — the powerful tools do the math, the browser just captures + plays.
import {downloadBody, packedDb, wordsFromBytes} from "./packed.js";

const ENG_SR=39062.5, F_LO=30, F_HI=ENG_SR/2, ZE=ENG_SR*.49, DB_LO=-42, DB_HI=14;
const WASM_URL="wasm/forge_web_wasm.wasm?v=voice";
const $=id=>document.getElementById(id);
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const setStatus=t=>{ $("status").textContent=t; };
const canvas=$("plot"), ctx=canvas.getContext("2d");
const state={ name:"my_voice", samples:null, sr:44100, foundation:"low_hump", bytes:null, words:null, src:3, playing:false, drive:0.4 };

// ---- the fit: send samples to /fitbody, get a packed body back ----
async function fitViaServer(){
  if(!state.samples){ setStatus("record or drop a source first"); return; }
  setStatus("fitting (ARMA + "+state.foundation+")…");
  // a stationary centered window keeps the POST light and the fit clean
  const s=state.samples, mid=s.length>>1, half=Math.min(24000, s.length>>1);
  const slice=Array.from(s.subarray(Math.max(0,mid-half), mid+half));
  try{
    const res=await fetch("/fitbody",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({samples:slice, sr:state.sr, foundation:state.foundation, name:state.name})});
    const j=await res.json();
    if(!res.ok || j.ok===false) throw new Error(j.error||("/fitbody "+res.status));
    const b=new Uint8Array(j.hex.match(/../g).map(h=>parseInt(h,16)));
    state.bytes=b; state.words=wordsFromBytes(b);
    if(anode) anode.port.postMessage({body:b.buffer.slice(0)});
    setStatus(`fitted · foundation ${j.foundation} · ${j.character_sections} character · maxR ${j.max_radius} · ${j.stable?"stable":"UNSTABLE"}`);
    draw();
  }catch(err){ setStatus("fit failed: "+err.message+"  (is the Python server running? restart it for /fitbody)"); }
}

// ---- plot the fitted body ----
function fitC(){ const r=canvas.getBoundingClientRect(),d=Math.min(devicePixelRatio||1,2); const w=Math.max(320,r.width*d|0),h=Math.max(200,r.height*d|0); if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;} }
const xF=f=>44+(Math.log(clamp(f,F_LO,F_HI))-Math.log(F_LO))/(Math.log(F_HI)-Math.log(F_LO))*(canvas.width-58);
const yF=db=>14+(1-(clamp(db,DB_LO,DB_HI)-DB_LO)/(DB_HI-DB_LO))*(canvas.height-30);
function draw(){ fitC(); const w=canvas.width,h=canvas.height; ctx.fillStyle="#f7f3eb"; ctx.fillRect(0,0,w,h);
  ctx.strokeStyle="#e0d7c8"; ctx.lineWidth=1; ctx.font="12px Consolas"; ctx.fillStyle="#81786c"; ctx.textAlign="right";
  for(const db of[12,0,-12,-24,-36]){ const y=yF(db); ctx.beginPath();ctx.moveTo(44,y);ctx.lineTo(w-14,y);ctx.stroke(); ctx.fillText(db,40,y+4); }
  ctx.textAlign="center"; for(const f of[100,200,500,1000,2000,5000,10000]){ const x=xF(f); ctx.beginPath();ctx.moveTo(x,12);ctx.lineTo(x,h-20);ctx.stroke(); ctx.fillText(f>=1000?f/1000+"k":f,x,h-6); }
  if(state.words){ ctx.strokeStyle="#d2452f"; ctx.lineWidth=2; ctx.beginPath();
    for(let i=0;i<360;i++){ const t=i/359,f=Math.exp(Math.log(F_LO)+t*(Math.log(F_HI)-Math.log(F_LO))); const x=xF(f),y=yF(packedDb(state.words,0,0,f)); i?ctx.lineTo(x,y):ctx.moveTo(x,y);} ctx.stroke();
    ctx.fillStyle="#d2452f"; ctx.textAlign="left"; ctx.fillText("fitted body (ARMA + "+state.foundation+")",50,24); }
  else { ctx.fillStyle="#aaa"; ctx.textAlign="center"; ctx.fillText("record a vowel or drop a .wav / IR",w/2,h/2); }
}
addEventListener("resize",draw);

// ---- capture: mic + wav + drop ----
async function recordMic(seconds=2){
  setStatus("recording… hold the vowel"); $("recBtn").classList.add("rec");
  const ac=new (AudioContext||webkitAudioContext)(); const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false}});
  const src=ac.createMediaStreamSource(stream); const sp=ac.createScriptProcessor(4096,1,1); const chunks=[];
  sp.onaudioprocess=e=>chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  src.connect(sp); sp.connect(ac.destination);
  await new Promise(r=>setTimeout(r,seconds*1000));
  sp.disconnect(); src.disconnect(); stream.getTracks().forEach(t=>t.stop());
  $("recBtn").classList.remove("rec");
  let len=chunks.reduce((a,c)=>a+c.length,0); const buf=new Float32Array(len); let o=0; for(const c of chunks){ buf.set(c,o); o+=c.length; }
  state.samples=buf; state.sr=ac.sampleRate; ac.close(); await fitViaServer();
}
async function openWav(file){
  setStatus("decoding "+file.name); const ab=await file.arrayBuffer(); const ac=new (AudioContext||webkitAudioContext)();
  const dec=await ac.decodeAudioData(ab); state.samples=dec.getChannelData(0).slice(); state.sr=dec.sampleRate; ac.close(); await fitViaServer();
}

// ---- audio (play the fit) ----
let actx=null, anode=null;
function pushParams(){ if(!anode)return; const d=state.drive; anode.port.postMessage({params:{morph:0,q:0,agc:4+4*d,slam:0.25*d*d,wide:0,inputGain:1,makeup:1.5+2.5*d}}); }
async function startAudio(){ actx=new(AudioContext||webkitAudioContext)(); const wasm=await(await fetch(WASM_URL)).arrayBuffer();
  await actx.audioWorklet.addModule("js/forge-worklet.js");
  anode=new AudioWorkletNode(actx,"forge-processor",{numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[2],processorOptions:{wasm,body:state.bytes?state.bytes.buffer.slice(0):null,src:state.src}});
  anode.port.onmessage=e=>{ if(e.data.ready){pushParams(); if(state.playing)anode.port.postMessage({playing:true});}
    if(e.data.level!=null){const m=$("meter");m.firstElementChild.style.height=Math.min(100,e.data.level*140)+"%";m.classList.toggle("flood",e.data.peak>0.985);} };
  anode.connect(actx.destination); }
async function toggleAudio(){ try{ if(!state.bytes){setStatus("fit a source first");return;} if(!actx)await startAudio(); if(actx.state==="suspended")await actx.resume();
  state.playing=!state.playing; anode.port.postMessage({playing:state.playing}); $("play").classList.toggle("on",state.playing); $("play").textContent=state.playing?"❚❚ stop":"▶ play fit";
}catch(err){ setStatus("audio failed: "+err.message);} }

// ---- wiring ----
$("recBtn").onclick=()=>recordMic().catch(err=>{ $("recBtn").classList.remove("rec"); setStatus("mic failed: "+err.message); });
$("openBtn").onclick=()=>$("openFile").click();
$("openFile").onchange=()=>{ const f=$("openFile").files[0]; if(f) openWav(f).catch(err=>setStatus("open failed: "+err.message)); };
$("foundation").onchange=e=>{ state.foundation=e.target.value; if(state.samples) fitViaServer(); };  // re-fit with new bottom, no re-record
document.addEventListener("dragover",e=>{ e.preventDefault(); document.body.style.outline="3px dashed #c52f4d"; document.body.style.outlineOffset="-3px"; });
document.addEventListener("dragleave",e=>{ if(e.relatedTarget===null) document.body.style.outline=""; });
document.addEventListener("drop",e=>{ e.preventDefault(); document.body.style.outline=""; const f=e.dataTransfer.files&&e.dataTransfer.files[0]; if(f) openWav(f).catch(err=>setStatus("drop failed: "+err.message)); });
$("play").onclick=toggleAudio;
document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{ document.querySelectorAll(".chip").forEach(x=>x.classList.remove("on")); c.classList.add("on"); state.src=+c.dataset.src; if(anode)anode.port.postMessage({src:state.src}); });
$("saveBtn").onclick=()=>{ if(!state.bytes){setStatus("fit first");return;} downloadBody(`${state.name}.body240`, Array.from(state.bytes).map(b=>b.toString(16).padStart(2,"0")).join("")); setStatus(`saved ${state.name}.body240`); };
$("nameInput").oninput=e=>{ state.name=e.target.value.trim()||"untitled"; };
draw(); setStatus("hold a vowel and ● record, or drop a .wav / IR — pick a foundation");
