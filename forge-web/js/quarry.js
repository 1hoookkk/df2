/* df2 frame quarry — grounded SECTIONS (one resonance each) mined from real
   sources + every vowel + your own audio fits. Click →A / →B to drop a section's
   exact coeffs into the next open lane of Frame A/B in the open zedit tab.
   Same origin as zedit (localhost:8130) so the storage handshake reaches it. */
const GEN = "http://127.0.0.1:8131";
const SR = 39062.5, NY = SR / 2;
const F_LO = 30, F_HI = 18000, DB_LO = -40, DB_HI = 30;
const PEACH = "#f6a878", WARN = "#d6564c";
const SRC_COL = { vowel: "#6fa8d0", fit: "#e8923a", _physics: "#5fae6e", _voice: "#c98bd0",
                  _design: "#b0a060", _authored: "#9aa0aa" };

function magDb(lanes, f) {
  const w = 2 * Math.PI * f / SR, cw = Math.cos(w), sw = Math.sin(w), c2 = Math.cos(2 * w), s2 = Math.sin(2 * w);
  let re = 1, im = 0;
  for (const l of lanes) {
    const wp = 2 * Math.PI * Math.min(l.pole_hz, NY * 0.999) / SR;
    const a1 = -2 * l.pole_r * Math.cos(wp), a2 = l.pole_r * l.pole_r;
    let b1 = 0, b2 = 0;
    if (l.zon && l.zero_r > 0) {
      const wz = 2 * Math.PI * Math.min(l.zero_hz, NY * 0.999) / SR;
      b1 = -2 * l.zero_r * Math.cos(wz); b2 = l.zero_r * l.zero_r;
    }
    const g = l.gain ?? 1;
    const nr = g * (1 + b1 * cw + b2 * c2), ni = g * (-(b1 * sw + b2 * s2));
    const dr = 1 + a1 * cw + a2 * c2, di = -(a1 * sw + a2 * s2);
    const pr = re * nr - im * ni, pii = re * ni + im * nr, dd = dr * dr + di * di;
    re = (pr * dr + pii * di) / dd; im = (pii * dr - pr * di) / dd;
  }
  return 20 * Math.log10(Math.max(1e-9, Math.hypot(re, im)));
}

function drawTile(cv, lanes, col) {
  const W = cv.width, H = cv.height, ctx = cv.getContext("2d");
  ctx.fillStyle = "#0d0e11"; ctx.fillRect(0, 0, W, H);
  const fy = db => (1 - (Math.max(DB_LO, Math.min(DB_HI, db)) - DB_LO) / (DB_HI - DB_LO)) * H;
  ctx.strokeStyle = "#1b1e23"; ctx.lineWidth = 1;
  ctx.beginPath(); const y0 = fy(0); ctx.moveTo(0, y0); ctx.lineTo(W, y0); ctx.stroke();
  ctx.strokeStyle = col || PEACH; ctx.lineWidth = 1.4; ctx.beginPath();
  for (let i = 0; i < W; i++) {
    const f = Math.exp(Math.log(F_LO) + (i / (W - 1)) * (Math.log(F_HI) - Math.log(F_LO)));
    const y = fy(magDb(lanes, f)); i ? ctx.lineTo(i, y) : ctx.moveTo(0, y);
  }
  ctx.stroke();
}

let nonce = 0;
function pickSection(which, sec) {
  localStorage.setItem("forge_pick", JSON.stringify({ kind: "section", which, words: sec.words, name: sec.name, n: ++nonce }));
  document.getElementById("msg").textContent = `${sec.name} → FRAME ${which}  (next open lane in zedit)`;
}

const dpr = Math.min(2, window.devicePixelRatio || 1);
function tile(sec) {
  const t = document.createElement("div"); t.className = "tile";
  const cv = document.createElement("canvas"); cv.width = 164 * dpr; cv.height = 64 * dpr;
  cv.style.width = "164px"; cv.style.height = "64px"; t.appendChild(cv);
  drawTile(cv, [sec.lane], SRC_COL[sec.src] || PEACH);
  const nm = document.createElement("div"); nm.className = "nm"; nm.textContent = sec.name; t.appendChild(nm);
  const meta = document.createElement("div"); meta.className = "meta";
  meta.innerHTML = `<span style="color:${SRC_COL[sec.src] || "#789"}">${sec.src}</span>  ·  ${Math.round(sec.pole_hz)} Hz  r${sec.pole_r.toFixed(3)}`;
  t.appendChild(meta);
  const btns = document.createElement("div"); btns.className = "btns";
  const a = document.createElement("button"); a.textContent = "→ A"; a.onclick = () => pickSection("A", sec);
  const b = document.createElement("button"); b.textContent = "→ B"; b.className = "b"; b.onclick = () => pickSection("B", sec);
  btns.appendChild(a); btns.appendChild(b); t.appendChild(btns);
  return t;
}

async function loadSections() {
  const grid = document.getElementById("grid"), msg = document.getElementById("msg");
  grid.innerHTML = "";
  let secs;
  try { secs = (await (await fetch(GEN + "/sections")).json()).sections; }
  catch (e) { msg.textContent = "palette failed — is the gen server running?  python tools/forge_gen_server.py"; msg.style.color = WARN; return; }
  msg.textContent = `${secs.length} grounded sections (low→high) — open zedit.html in another tab, then click →A / →B`;
  for (const s of secs) grid.appendChild(tile(s));
  return secs;
}

async function fitAudio() {
  const path = document.getElementById("fitpath").value.trim();
  const msg = document.getElementById("msg");
  if (!path) { msg.textContent = "paste a WAV path to fit"; return; }
  msg.textContent = `fitting ${path} …`;
  let r;
  try { r = await (await fetch(GEN + "/fit?path=" + encodeURIComponent(path))).json(); }
  catch (e) { msg.textContent = "fit failed — server error"; msg.style.color = WARN; return; }
  if (r.error) { msg.textContent = "fit: " + r.error; msg.style.color = WARN; return; }
  msg.style.color = "#5fae6e";
  msg.textContent = `fitted ${r.name} → ${r.sections.length} sections (centroid ${r.centroid} Hz). Prepended below.`;
  const grid = document.getElementById("grid");
  for (const s of r.sections.slice().reverse()) grid.insertBefore(tile(s), grid.firstChild);
}

document.getElementById("fitbtn").onclick = fitAudio;
document.getElementById("fitpath").addEventListener("keydown", e => { if (e.key === "Enter") fitAudio(); });
loadSections();
