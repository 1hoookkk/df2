/* ZERO — trench canyon editor. Zero-first authoring on the engine-faithful curve.
   Zeros (O) are the characters you carve; poles (X) are optional backend scaffolding.
   Packs through the SAME WASM encoder the engine runs; plot == engine (packed.js). */
import { wordsFromBytes, packedDb, hexFromWords, downloadBody } from "./packed.js";

const SR = 39062.5, NY = SR * 0.49;
const NS = 6;
const F_LO = 28, F_HI = 18000, DB_LO = -42, DB_HI = 24;
const PADL = 64, PADR = 26, PADT = 30, PADB = 34;
const C = { signal: "#f6a878", signalHot: "#ffb066", cut: "#54dcef", cutGlow: "#7ff4ff",
            pole: "#a8763e", danger: "#ff5e54", dim: "#697080", grid: "rgba(255,255,255,.05)" };

const cv = document.getElementById("c"), ctx = cv.getContext("2d");
let W = 0, H = 0, dpr = 1, ex = null, mem = null, paramsView = null, bodyBytes = null, words = null;

// section = { pole_hz, pole_r, gain, zon, zhz, zr } — pole from backend, zero authored
const SEED = [110, 285, 640, 1350, 3050, 7000];
// each section = a pole (backend) + its paired zero (the throttle). SKELETON default: pole and
// zero are coincident (same Hz + radius) so the section cancels to a flat 0 dB line. Drag a cut
// UP -> zero loosens, the pole erupts into a peak; drag DOWN -> zero bites, carving a canyon.
const sec = hz => { const pr = 0.965; return { pole_hz: hz, pole_r: pr, gain: 1, zon: 1, zhz: hz, zr: pr }; };
let FR = { home: SEED.map(sec), away: SEED.map(sec) };
const st = { frame: "home", morph: 0, q: 1, playing: false, showPoles: false, drag: null, hover: null };

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const fx = f => PADL + (Math.log(clamp(f, F_LO, F_HI)) - Math.log(F_LO)) / (Math.log(F_HI) - Math.log(F_LO)) * (W - PADL - PADR);
const fy = db => PADT + (1 - (clamp(db, DB_LO, DB_HI) - DB_LO) / (DB_HI - DB_LO)) * (H - PADT - PADB);
const xToF = x => Math.exp(Math.log(F_LO) + (clamp(x, PADL, W - PADR) - PADL) / (W - PADL - PADR) * (Math.log(F_HI) - Math.log(F_LO)));

// ---- WASM ----
async function init() {
  const wasm = await (await fetch("wasm/forge_web_wasm.wasm")).arrayBuffer();
  const m = await WebAssembly.instantiate(wasm, {});
  ex = m.instance.exports; mem = ex.memory;
  paramsView = new Float64Array(mem.buffer, ex.forge_params_ptr(), ex.forge_params_len());
  repack(); resize(); requestAnimationFrame(loop);   // opens FLAT — a skeleton you sculpt
}
const broaden = s => s.map(l => ({ ...l, pole_r: Math.max(0.55, 0.55 + (l.pole_r - 0.55) * 0.55) }));
function repack() {
  const corners = [broaden(FR.home), broaden(FR.away), FR.home, FR.away]; // M0Q0 M100Q0 M0Q100 M100Q100
  for (let c = 0; c < 4; c++) for (let s = 0; s < NS; s++) {
    const L = corners[c][s], b = (c * NS + s) * 7;
    paramsView[b] = 1; paramsView[b + 1] = L.pole_hz; paramsView[b + 2] = L.pole_r; paramsView[b + 3] = L.gain;
    paramsView[b + 4] = L.zon; paramsView[b + 5] = L.zhz; paramsView[b + 6] = L.zr;
  }
  ex.forge_pack_params();
  bodyBytes = new Uint8Array(mem.buffer, ex.forge_body_ptr(), ex.forge_body_len()).slice();
  words = wordsFromBytes(bodyBytes);
  if (anode) anode.port.postMessage({ body: bodyBytes.buffer.slice(0) });
}
const dbAt = (f, m = st.morph, q = st.q) => packedDb(words, m, q, f);

// ---- audio (reuse worklet) ----
let actx = null, anode = null;
async function startAudio() {
  actx = new (window.AudioContext || window.webkitAudioContext)();
  const wasm = await (await fetch("wasm/forge_web_wasm.wasm")).arrayBuffer();
  await actx.audioWorklet.addModule("js/forge-worklet.js");
  anode = new AudioWorkletNode(actx, "forge-processor", { numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [2],
    processorOptions: { wasm, body: bodyBytes.buffer.slice(0), src: 0 } });
  anode.port.onmessage = e => { if (e.data.ready) { pushParams(); anode.port.postMessage({ playing: st.playing }); } };
  anode.connect(actx.destination);
}
const pushParams = () => anode && anode.port.postMessage({ params: { morph: st.morph, q: st.q, agc: 3.5, slam: 0, wide: 0 } });
async function toggleAudio() {
  try { if (!actx) await startAudio(); if (actx.state === "suspended") await actx.resume();
    st.playing = !st.playing; if (anode) anode.port.postMessage({ playing: st.playing });
    document.getElementById("play").classList.toggle("on", st.playing);
    document.getElementById("play").innerHTML = st.playing ? "❚❚ &nbsp;stop" : "▶ &nbsp;play";
  } catch (e) { console.log(e); }
}

// ---- curve sampling ----
const NP = 320;
function curvePts(m, q) {
  const pts = [];
  for (let i = 0; i < NP; i++) { const t = i / (NP - 1), f = Math.exp(Math.log(F_LO) + t * (Math.log(F_HI) - Math.log(F_LO))); pts.push([fx(f), fy(dbAt(f, m, q))]); }
  return pts;
}

// ---- paint ----
function grid() {
  ctx.lineWidth = 1;
  for (const db of [12, 0, -12, -24, -36]) { const y = fy(db); ctx.strokeStyle = db === 0 ? "rgba(255,255,255,.1)" : C.grid;
    ctx.beginPath(); ctx.moveTo(PADL, y); ctx.lineTo(W - PADR, y); ctx.stroke();
    ctx.fillStyle = "#3b4250"; ctx.font = '10px "Spline Sans Mono"'; ctx.textAlign = "right"; ctx.fillText(db > 0 ? "+" + db : "" + db, PADL - 8, y + 3); }
  for (const f of [50, 100, 500, 1000, 5000, 10000]) { const x = fx(f); ctx.strokeStyle = C.grid;
    ctx.beginPath(); ctx.moveTo(x, PADT); ctx.lineTo(x, H - PADB); ctx.stroke();
    ctx.fillStyle = "#3b4250"; ctx.textAlign = "center"; ctx.fillText(f >= 1000 ? (f / 1000) + "k" : f, x, H - PADB + 16); }
}
function strokeCurve(pts, color, lw, glow, fill) {
  if (fill) {
    const g = ctx.createLinearGradient(0, PADT, 0, H - PADB);
    g.addColorStop(0, "rgba(246,168,120,.20)"); g.addColorStop(.55, "rgba(246,168,120,.05)"); g.addColorStop(1, "rgba(246,168,120,0)");
    ctx.beginPath(); ctx.moveTo(pts[0][0], H - PADB);
    for (const [x, y] of pts) ctx.lineTo(x, y);
    ctx.lineTo(pts[pts.length - 1][0], H - PADB); ctx.closePath(); ctx.fillStyle = g; ctx.fill();
  }
  ctx.save(); if (glow) { ctx.shadowColor = color; ctx.shadowBlur = glow; }
  ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.lineJoin = "round"; ctx.beginPath();
  pts.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.stroke(); ctx.restore();
}
function draw() {
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
  grid();
  // ghost endpoints (HOME amber, AWAY cyan) — the two ends of the travel
  strokeCurve(curvePts(0, st.q), "rgba(246,168,120,.22)", 1.2, 0, false);
  strokeCurve(curvePts(1, st.q), "rgba(84,220,239,.20)", 1.2, 0, false);
  // live curve
  strokeCurve(curvePts(st.morph, st.q), st.q > 0.85 ? C.signalHot : C.signal, 2.3, 16, true);

  const F = FR[st.frame];
  // cut beams (zeros) — cold light dropping into the canyon
  F.forEach((s, i) => {
    if (!s.zon) return;
    const x = fx(s.zhz), yc = fy(dbAt(s.zhz));
    const g = ctx.createLinearGradient(0, PADT, 0, H - PADB);
    g.addColorStop(0, "rgba(84,220,239,0)"); g.addColorStop(1, "rgba(84,220,239,.10)");
    ctx.fillStyle = g; ctx.fillRect(x - 1.5, PADT, 3, H - PADB - PADT);
  });
  // poles (optional, faint) under the signal
  if (st.showPoles) F.forEach((s, i) => {
    const x = fx(s.pole_hz), y = fy(dbAt(s.pole_hz)) ;
    ctx.strokeStyle = C.pole; ctx.globalAlpha = .55; ctx.lineWidth = 1.6;
    ctx.beginPath(); ctx.moveTo(x - 5, y - 5); ctx.lineTo(x + 5, y + 5); ctx.moveTo(x + 5, y - 5); ctx.lineTo(x - 5, y + 5); ctx.stroke();
    ctx.globalAlpha = 1;
  });
  // zero nodes — luminous rings sitting in their canyons
  F.forEach((s, i) => {
    if (!s.zon) return;
    const x = fx(s.zhz), y = fy(dbAt(s.zhz));
    const active = (st.drag && st.drag.kind === "zero" && st.drag.i === i) || (st.hover && st.hover.kind === "zero" && st.hover.i === i);
    const r = active ? 9 : 6.5;
    ctx.save(); ctx.shadowColor = C.cutGlow; ctx.shadowBlur = active ? 22 : 12;
    ctx.strokeStyle = C.cutGlow; ctx.lineWidth = 2.2; ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.stroke();
    ctx.fillStyle = "rgba(84,220,239,.18)"; ctx.fill();
    ctx.shadowBlur = 0; ctx.fillStyle = "#bdf6ff"; ctx.beginPath(); ctx.arc(x, y, 1.7, 0, 7); ctx.fill(); ctx.restore();
  });
}
function loop() { draw(); sync(); requestAnimationFrame(loop); }

// ---- interaction ----
const pos = e => { const b = cv.getBoundingClientRect(); return { x: e.clientX - b.left, y: e.clientY - b.top }; };
function pickNode(p) {
  const F = FR[st.frame]; let best = null, bd = 16;
  F.forEach((s, i) => {
    if (s.zon) { const d = Math.hypot(p.x - fx(s.zhz), p.y - fy(dbAt(s.zhz))); if (d < bd) { bd = d; best = { kind: "zero", i }; } }
    if (st.showPoles) { const d = Math.hypot(p.x - fx(s.pole_hz), p.y - fy(dbAt(s.pole_hz))); if (d < bd) { bd = d; best = { kind: "pole", i }; } }
  });
  return best;
}
function dropCut(f) {
  const F = FR[st.frame]; let i = F.findIndex(s => !s.zon);
  if (i < 0) { let bd = 1e9; F.forEach((s, k) => { const d = Math.abs(Math.log2(s.zhz / f)); if (d < bd) { bd = d; i = k; } }); }
  F[i].zon = 1; F[i].zhz = clamp(f, 40, NY); F[i].zr = 0.9; repack();
  return { kind: "zero", i };
}
cv.addEventListener("contextmenu", e => { e.preventDefault(); const n = pickNode(pos(e)); if (n && n.kind === "zero") { FR[st.frame][n.i].zon = 0; FR[st.frame][n.i].zhz = NY; repack(); } });
cv.addEventListener("pointerdown", e => {
  if (e.button === 2) return; const p = pos(e);
  if (p.x < PADL - 10 || p.x > W - PADR + 10 || p.y < PADT || p.y > H - PADB) return;
  let n = pickNode(p); if (!n) n = dropCut(xToF(p.x));
  st.drag = { ...n, sx: p.x, sy: p.y, sr: FR[st.frame][n.i].zr, spr: FR[st.frame][n.i].pole_r };
  cv.setPointerCapture(e.pointerId);
});
cv.addEventListener("pointermove", e => {
  const p = pos(e);
  if (st.drag) {
    const d = st.drag, F = FR[st.frame], L = F[d.i];
    if (d.kind === "zero") { L.zhz = clamp(xToF(p.x), 40, NY); L.zr = clamp(d.sr + (p.y - d.sy) * 0.0016, 0.5, 0.9985); }
    else { L.pole_hz = clamp(xToF(p.x), 30, NY); L.pole_r = clamp(d.spr - (p.y - d.sy) * 0.0008, 0.95, 0.9998); }
    repack(); showTip(p, d.kind, L);
  } else {
    st.hover = pickNode(p);
    cv.style.cursor = st.hover ? "grab" : (p.y < H - PADB && p.x > PADL ? "crosshair" : "default");
    if (st.hover) showTip(p, st.hover.kind, FR[st.frame][st.hover.i]); else hideTip();
  }
});
const endDrag = () => { st.drag = null; hideTip(); };
cv.addEventListener("pointerup", endDrag); cv.addEventListener("pointercancel", endDrag);

const tip = document.getElementById("tip");
function showTip(p, kind, L) {
  const hz = kind === "zero" ? L.zhz : L.pole_hz;
  const lab = kind === "zero" ? `CUT · ${fmtHz(hz)} · depth ${Math.round((L.zr - 0.5) / 0.4985 * 100)}%`
                              : `POLE · ${fmtHz(hz)} · Q≈${Math.round(1 / (2 * (1 - L.pole_r)))}`;
  tip.textContent = lab; tip.style.left = fx(hz) + "px"; tip.style.top = fy(dbAt(hz)) + "px";
  tip.style.color = kind === "zero" ? C.cutGlow : C.pole; tip.classList.add("on");
}
const hideTip = () => tip.classList.remove("on");
const fmtHz = h => h >= 1000 ? (h / 1000).toFixed(2) + "k" : Math.round(h) + " Hz";

// ---- chrome ----
const readout = document.getElementById("readout");
function sync() {
  document.getElementById("morphVal").textContent = (st.morph * 100) | 0;
  document.getElementById("qVal").textContent = (st.q * 100) | 0;
  document.getElementById("knob").style.left = (st.morph * 100) + "%";
  document.getElementById("trackFill").style.opacity = st.morph;
  document.getElementById("qfill").style.height = (st.q * 100) + "%";
  document.getElementById("qline").style.bottom = (st.q * 100) + "%";
  const n = FR[st.frame].filter(s => s.zon).length;
  readout.innerHTML = `<b>${st.frame.toUpperCase()}</b> · ${n} cut${n === 1 ? "" : "s"} · morph <b>${(st.morph * 100) | 0}</b> · Q <b>${(st.q * 100) | 0}</b>`;
}
function setFrame(f) {
  st.frame = f;
  document.getElementById("fHome").classList.toggle("on", f === "home");
  document.getElementById("fAway").classList.toggle("on", f === "away");
  st.morph = f === "home" ? 0 : 1; pushParams(); sync();
}
document.getElementById("fHome").onclick = () => setFrame("home");
document.getElementById("fAway").onclick = () => setFrame("away");

const track = document.getElementById("track");
function trackDrag(e) { const b = track.getBoundingClientRect(); st.morph = clamp((e.clientX - b.left) / b.width, 0, 1); pushParams(); sync(); }
track.addEventListener("pointerdown", e => { track.setPointerCapture(e.pointerId); trackDrag(e); track.onpointermove = ev => ev.buttons && trackDrag(ev); });
track.addEventListener("pointerup", () => track.onpointermove = null);

const qbar = document.getElementById("qbar");
function qDrag(e) { const b = qbar.getBoundingClientRect(); st.q = clamp(1 - (e.clientY - b.top) / b.height, 0, 1); pushParams(); sync(); }
qbar.addEventListener("pointerdown", e => { qbar.setPointerCapture(e.pointerId); qDrag(e); qbar.onpointermove = ev => ev.buttons && qDrag(ev); });
qbar.addEventListener("pointerup", () => qbar.onpointermove = null);

document.getElementById("play").onclick = toggleAudio;
document.getElementById("save").onclick = () => { if (bodyBytes) downloadBody("zero.body240", hexFromWords(words)); };
document.getElementById("reset").onclick = () => { FR = { home: SEED.map(sec), away: SEED.map(sec) }; repack(); sync(); };
const pt = document.getElementById("polesToggle");
pt.onclick = () => { st.showPoles = !st.showPoles; pt.classList.toggle("on", st.showPoles); };

function resize() { dpr = Math.min(2, window.devicePixelRatio || 1); W = cv.clientWidth; H = cv.clientHeight; cv.width = W * dpr | 0; cv.height = H * dpr | 0; }
window.addEventListener("resize", resize);
init().then(sync);
