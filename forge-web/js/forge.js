import { packWithCore, bodyHex } from "./pack-core.js";
import { downloadBody, packedDb, wordsFromBytes, wordsAt, stageWordsToKernel, kernelToBiquad, biquadDbCoeffs } from "./packed.js";

const SR = 39062.5, F_LO = 20, F_HI = SR / 2, ZERO_END = SR * 0.49, DB_LO = -36, DB_HI = 48;
const WASM_URL = "wasm/forge_web_wasm.wasm?v=designer_surface";

const $ = id => document.getElementById(id);
const curveCanvas = $("curve");
const curveCtx = curveCanvas.getContext("2d");
const fieldCanvas = $("field");
const fieldCtx = fieldCanvas.getContext("2d");

const STATE = {
  name: "vowel_designer",
  m: 0.5, // boot at the design point: the morph interior is where character lives
  q: 0.5,
  drive: 0.40,
  src: 0,
  playing: false,
  railMode: "measured", // "measured" | "12tet" | "free"
  selStage: 0, // selected stage index (0..5)
  worstR: 0,
  auditVerdict: "PASS",
  bytes: null,
  hex: "",
  words: null,
  corners: null, // [4 corners][6 stages]
  drag: null, // { stage, type: "pole" | "zero", startX, startY }
};

// 30 standard P2K vocal/mode resonance frequencies
const MEASURED_RAILS = [
  55, 70, 90, 110, 150, 200, 270, 300, 420, 530, 640, 660, 730, 840, 870,
  1090, 1190, 1500, 1720, 1840, 2240, 2290, 2440, 3010, 3300, 4200, 5500, 7000, 9000, 12000
];

const STAGE_COLORS = ["#d24b3f", "#e09a2e", "#5ba35a", "#3f9690", "#4f7bb0", "#8c6bb8"];

// --- Helper Functions ---
const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
const logF = f => Math.log(clamp(f, F_LO, F_HI));
const fx = (f, w) => 48 + (logF(f) - logF(F_LO)) / (logF(F_HI) - logF(F_LO)) * (w - 70);
const fy = (db, h) => 18 + (1 - (clamp(db, DB_LO, DB_HI) - DB_LO) / (DB_HI - DB_LO)) * (h - 48);
const xToF = (x, w) => Math.exp(logF(F_LO) + clamp((x - 48) / (w - 70), 0, 1) * (logF(F_HI) - logF(F_LO)));
const yToDb = (y, h) => DB_LO + (1 - clamp((y - 18) / (h - 48), 0, 1)) * (DB_HI - DB_LO);

function snapHz(hz) {
  if (STATE.railMode === "free") return clamp(hz, F_LO, ZERO_END);
  if (STATE.railMode === "measured") {
    return MEASURED_RAILS.reduce((a, b) => Math.abs(b - hz) < Math.abs(a - hz) ? b : a, MEASURED_RAILS[0]);
  }
  if (STATE.railMode === "12tet") {
    // Snap to nearest 12-TET chromatic frequency centered on A440
    const semitones = Math.round(12 * Math.log2(hz / 440));
    return clamp(440 * Math.pow(2, semitones / 12), F_LO, ZERO_END);
  }
  return hz;
}

// --- Color Heat Map (Spectrogram) ---
function getHeatColor(db) {
  const cVoid = [11, 11, 13];
  const cZero = [52, 27, 77];
  const c20 = [138, 61, 42];
  const c33 = [199, 116, 31];
  const c44 = [246, 232, 200];
  const cHot = [255, 255, 255];
  
  if (db <= -12) return cVoid;
  if (db <= 0) return lerpColor(cVoid, cZero, (db - (-12)) / 12);
  if (db <= 20) return lerpColor(cZero, c20, db / 20);
  if (db <= 33) return lerpColor(c20, c33, (db - 20) / 13);
  if (db <= 44) return lerpColor(c33, c44, (db - 33) / 11);
  return cHot;
}

function lerpColor(c1, c2, t) {
  return [
    Math.round(c1[0] + (c2[0] - c1[0]) * t),
    Math.round(c1[1] + (c2[1] - c1[1]) * t),
    Math.round(c1[2] + (c2[2] - c1[2]) * t)
  ];
}

// --- Live Values ---
function getStageLive(si) {
  const corners = STATE.corners;
  const m = STATE.m, q = STATE.q;
  const w00 = (1 - m) * (1 - q);
  const w10 = m * (1 - q);
  const w01 = (1 - m) * q;
  const w11 = m * q;
  
  const c0 = corners[0][si];
  const c1 = corners[1][si];
  const c2 = corners[2][si];
  const c3 = corners[3][si];

  const hz = Math.exp(w00 * Math.log(c0.hz) + w10 * Math.log(c1.hz) + w01 * Math.log(c2.hz) + w11 * Math.log(c3.hz));
  const r = w00 * c0.r + w10 * c1.r + w01 * c2.r + w11 * c3.r;
  const gain = w00 * c0.gain + w10 * c1.gain + w01 * c2.gain + w11 * c3.gain;
  const cutHz = Math.exp(w00 * Math.log(c0.cutHz) + w10 * Math.log(c1.cutHz) + w01 * Math.log(c2.cutHz) + w11 * Math.log(c3.cutHz));
  const cutDepth = w00 * c0.cutDepth + w10 * c1.cutDepth + w01 * c2.cutDepth + w11 * c3.cutDepth;

  return {
    on: c0.on,
    hz,
    r,
    gain,
    cutOn: c0.cutOn,
    cutHz,
    cutDepth
  };
}

// --- Distribute Edits ---
function distributeEdit(si, field, newVal, isGeom = false) {
  const m = STATE.m, q = STATE.q;
  const w00 = (1 - m) * (1 - q);
  const w10 = m * (1 - q);
  const w01 = (1 - m) * q;
  const w11 = m * q;
  const weights = [w00, w10, w01, w11];

  const liveVal = getStageLive(si)[field];

  if (isGeom) {
    const ratio = newVal / Math.max(1e-3, liveVal);
    for (let ci = 0; ci < 4; ci++) {
      const current = STATE.corners[ci][si][field];
      STATE.corners[ci][si][field] = clamp(current * Math.pow(ratio, weights[ci]), F_LO, ZERO_END);
    }
  } else {
    const delta = newVal - liveVal;
    for (let ci = 0; ci < 4; ci++) {
      const current = STATE.corners[ci][si][field];
      const maxClamp = (field === "r" || field === "cutDepth") ? 0.9995 : 1000.0;
      const minClamp = (field === "r" || field === "cutDepth") ? 0.05 : -1000.0;
      STATE.corners[ci][si][field] = clamp(current + delta * weights[ci], minClamp, maxClamp);
    }
  }
}

// --- Clean-room Type Solver Skeletons & Gain Normalization ---
const RIM = 0.9990;
const NY = SR * 0.49;

// Helper to construct a signature section
function L(role, a, e, r0, gain, za, ze, zr0, qw, zqw = 0.0) {
  return { role, a, e, r0, gain, za, ze, zr0, qw, zqw };
}

const VOWEL_FORM_MAP = {
  aah: [730, 1090, 2440, 3400],
  eee: [270, 2290, 3010, 3400],
  ooh: [300, 870, 2240, 3400],
  eh:  [530, 1840, 2480, 3400]
};

function vow_format(vA, vB) {
  const A = VOWEL_FORM_MAP[vA];
  const B = VOWEL_FORM_MAP[vB];
  const qw = [0.92, 1.0, 1.0, 0.85];
  const lanes = [];
  for (let i = 0; i < 4; i++) {
    const za = A[i] * 1.5;
    const ze = B[i] * 1.5;
    lanes.push(L(`F${i+1}`, A[i], B[i], 0.90, 0.5, za, ze, 0.93, qw[i], 0.12));
  }
  return lanes;
}

const SKELETON_PRESETS = {
  vow_aah_eee: vow_format("aah", "eee"),
  vow_ooh_aah: vow_format("ooh", "aah"),
  lpf_megasweep: [
    L("cutoff", 300, 6000, 0.93, 0.5, 520, 10200, 0.6, 1.0)
  ],
  rez_violent: [320, 520, 820, 1280, 2000, 3150].map((f, i) => 
    L(`ring${i+1}`, f, f, 0.94, 0.45, f*1.1, f*1.1, 0.90, 1.0)
  ),
  eq_acidbass: [
    L("squelch", 260, 2400, 0.94, 0.6, 300, 2760, 0.9, 1.0),
    L("grit", 1400, 1700, 0.95, 0.45, 1620, 1960, 0.88, 0.8)
  ],
  pha_gargle: [300, 600, 1100, 2000, 3600, 6500].map((f, i) =>
    L(`n${i+1}`, f, f*1.3, 0.90, 0.5, f, f*1.3, 0.90, 0.15, 1.0)
  ),
  bpf_contrary: [
    L("peakA", 500, 3000, 0.96, 0.55, 375, 2250, 0.0, 1.0),
    L("peakB", 3000, 500, 0.96, 0.55, 2250, 375, 0.0, 1.0)
  ]
};

function fill_to_six(lanes) {
  const roles = new Set(lanes.map(l => l.role));
  const out = [...lanes];
  if (!roles.has("body")) {
    out.unshift(L("body", 110, 110, 0.96, 0.06, 0, 0, 0.0, 0.02));
  }
  if (out.length < 6 && !roles.has("air")) {
    out.push(L("air", 9000, 9000, 0.90, 0.42, 16000, 16000, 0.5, 0.20));
  }
  let i = 0;
  while (out.length < 6) {
    const f = [220, 520, 1100, 2400, 4800][i % 5];
    out.push(L(`fill${i}`, f, f, 0.88, 0.4, f * 1.6, f * 1.6, 0.6, 0.10));
    i++;
  }
  return out.slice(0, 6);
}

function stage_for(s, m, q) {
  const pole_hz = s.a * Math.pow(s.e / s.a, m);
  const pole_r = s.r0 + (RIM - s.r0) * q * s.qw;
  const zero_hz = s.za > 0 ? s.za * Math.pow(s.ze / Math.max(s.za, 1), m) : 0.0;
  const zero_r = s.zr0 + (0.999 - s.zr0) * q * s.zqw;
  
  return {
    on: true,
    hz: Math.min(NY, pole_hz),
    r: Math.min(pole_r, RIM),
    gain: s.gain,
    cutOn: s.za > 0,
    cutHz: s.za > 0 ? Math.min(NY, zero_hz) : 0.0,
    cutDepth: s.za > 0 ? Math.min(zero_r, 0.999) : 0.0,
    role: s.role
  };
}

const FF_POINTS = [];
const logFlo = Math.log(30);
const logFhi = Math.log(120);
for (let i = 0; i < 40; i++) {
  FF_POINTS.push(Math.exp(logFlo + (i / 39) * (logFhi - logFlo)));
}

function conjPair(hz, r) {
  const th = 2 * Math.PI * hz / SR;
  return [-2 * r * Math.cos(th), r * r];
}

function cornerLowDb(stages) {
  let sumMag = 0;
  for (let fi = 0; fi < 40; fi++) {
    const f = FF_POINTS[fi];
    const w = 2 * Math.PI * f / SR;
    const z_re = Math.cos(w);
    const z_im = -Math.sin(w);
    const z2_re = Math.cos(2 * w);
    const z2_im = -Math.sin(2 * w);
    
    let H_re = 1.0;
    let H_im = 0.0;
    
    for (const d of stages) {
      const g = d.gain;
      const pole_hz = d.hz;
      const pole_r = d.r;
      const zero_hz = d.cutOn ? d.cutHz : 0.0;
      const zero_r = d.cutOn ? d.cutDepth : 0.0;
      
      const [a1, a2] = conjPair(pole_hz, pole_r);
      const [n1, n2] = d.cutOn ? conjPair(zero_hz, zero_r) : [0.0, 0.0];
      
      // N(z) = g + g * n1 * z + g * n2 * z^2
      const num_re = g + g * n1 * z_re + g * n2 * z2_re;
      const num_im = g * n1 * z_im + g * n2 * z2_im;
      
      // D(z) = 1 + a1 * z + a2 * z^2
      const den_re = 1.0 + a1 * z_re + a2 * z2_re;
      const den_im = a1 * z_im + a2 * z2_im;
      
      // A = H * N
      const A_re = H_re * num_re - H_im * num_im;
      const A_im = H_re * num_im + H_im * num_re;
      
      // H = A / D
      const den_sq = den_re * den_re + den_im * den_im + 1e-24;
      H_re = (A_re * den_re + A_im * den_im) / den_sq;
      H_im = (A_im * den_re - A_re * den_im) / den_sq;
    }
    
    sumMag += Math.hypot(H_re, H_im);
  }
  return 20 * Math.log10(sumMag / 40.0 + 1e-9);
}

function solvePreset(name) {
  const fmt = SKELETON_PRESETS[name];
  if (!fmt) return null;
  const lanes = fill_to_six(fmt);
  
  const pts = [
    { m: 0, q: 0 }, // M0_Q0
    { m: 1, q: 0 }, // M100_Q0
    { m: 0, q: 1 }, // M0_Q100
    { m: 1, q: 1 }  // M100_Q100
  ];
  
  const corners = [];
  for (let ci = 0; ci < 4; ci++) {
    const p = pts[ci];
    const rows = lanes.map(s => stage_for(s, p.m, p.q));
    
    // Per-corner gain normalization — distributed over all 6 lanes (gain^(1/6))
    // so no single lane's minifloat saturates or underflows.
    const norm = Math.pow(10, -cornerLowDb(rows) / 20.0);
    const perLane = Math.pow(norm, 1 / rows.length);
    for (const row of rows) row.gain = clamp(row.gain * perLane, 0.001, 3.75);
    
    corners.push(rows);
  }
  return corners;
}

// --- Seeds ---
function applySeed(type) {
  let corners = [[], [], [], []];
  
  if (type === "blank") {
    // Coincident pole-zero pairs spread across the spectrum (flat 0 dB)
    const freqs = [100, 260, 620, 1500, 3800, 9200];
    for (let ci = 0; ci < 4; ci++) {
      for (let si = 0; si < 6; si++) {
        corners[ci].push({
          on: true,
          hz: freqs[si],
          r: 0.82,
          gain: 1.0,
          cutOn: true,
          cutHz: freqs[si],
          cutDepth: 0.82,
          role: `stage_${si + 1}`
        });
      }
    }
  } else {
    const solved = solvePreset(type);
    if (solved) {
      corners = solved;
    }
  }
  
  STATE.corners = corners;
  repack();
}

// --- Compilation and Repack ---
async function repack() {
  try {
    const rawModel = () => STATE.corners.map(corner => corner.map(s => ({ ...s })));

    STATE.bytes = await packWithCore(rawModel());
    STATE.words = wordsFromBytes(STATE.bytes);

    // Closed-loop low-end pin: measure the PACKED truth (packedDb) at the 4 corners
    // over 30-120 Hz and distribute the correction across all 6 lanes, then re-pack.
    // The JS biquad surrogate disagrees with the engine's minifloat gain semantics,
    // so the measurement must go through the packed words, not the model.
    const MQ = [[0, 0], [1, 0], [0, 1], [1, 1]]; // C0..C3 order matches STATE.corners
    const iters = STATE.drag ? 1 : 3;
    for (let it = 0; it < iters; it++) {
      const dbs = MQ.map(([m, q]) => {
        let sum = 0;
        for (const f of FF_POINTS) sum += packedDb(STATE.words, m, q, f);
        return sum / FF_POINTS.length;
      });
      if (Math.max(...dbs.map(Math.abs)) < 0.5) break;
      for (let ci = 0; ci < 4; ci++) {
        const perLane = Math.pow(10, -dbs[ci] / (20 * STATE.corners[ci].length));
        for (const row of STATE.corners[ci]) row.gain = clamp(row.gain * perLane, 0.001, 3.75);
      }
      STATE.bytes = await packWithCore(rawModel());
      STATE.words = wordsFromBytes(STATE.bytes);
    }

    STATE.hex = bodyHex(STATE.bytes);
    
    // Update live audio node
    if (anode) anode.port.postMessage({ body: STATE.bytes.buffer.slice(0) });
    
    runAudit();
    renderUI();
  } catch (err) {
    console.error("Repack failed:", err);
    $("status").textContent = `Error: ${err.message}`;
  }
}

// --- Audit & Verdict ---
function runAudit() {
  let worst = 0;
  let hasNonFinite = false;
  let minPeak = 999;
  let maxPeak = -999;
  
  // Probe a 9x9 grid in real-time
  const grid = 9;
  for (let mi = 0; mi < grid; mi++) {
    const m = mi / (grid - 1);
    for (let qi = 0; qi < grid; qi++) {
      const q = qi / (grid - 1);
      
      let peak = -999;
      // evaluate magnitude response across log frequencies
      for (let fi = 0; fi < 40; fi++) {
        const f = Math.exp(Math.log(F_LO) + (fi / 39) * (Math.log(F_HI) - Math.log(F_LO)));
        const db = packedDb(STATE.words, m, q, f);
        if (!Number.isFinite(db)) {
          hasNonFinite = true;
        } else {
          peak = Math.max(peak, db);
        }
      }
      
      minPeak = Math.min(minPeak, peak);
      maxPeak = Math.max(maxPeak, peak);

      // get max pole radius
      for (const row of wordsAt(STATE.words, m, q)) {
        const bq = kernelToBiquad(stageWordsToKernel(row));
        const a1 = bq[3], a2 = bq[4];
        const disc = a1 * a1 - 4 * a2;
        const r = disc < 0 ? Math.sqrt(Math.max(0, a2)) : Math.max(Math.abs((-a1 + Math.sqrt(disc)) / 2), Math.abs((-a1 - Math.sqrt(disc)) / 2));
        worst = Math.max(worst, r);
      }
    }
  }
  
  STATE.worstR = worst;
  
  // Evaluate verdict based on stability and the +33 to +44 dB iconic corridor
  const isStable = worst < 1.0 && !hasNonFinite;
  const inCorridor = maxPeak >= 33.0 && maxPeak <= 44.0;
  
  const lamp = $("auditLamp");
  if (!isStable) {
    STATE.auditVerdict = "FAIL (unstable)";
    lamp.className = "lamp fail";
    lamp.textContent = "unstable";
  } else if (!inCorridor) {
    STATE.auditVerdict = "WARN (off-corridor)";
    lamp.className = "lamp warn";
    lamp.textContent = `off-corridor (${maxPeak.toFixed(0)} dB)`;
  } else {
    STATE.auditVerdict = "PASS";
    lamp.className = "lamp pass";
    lamp.textContent = "pass";
  }
}

function drawTriangle(ctx, cx, cy, size, pointingUp, fillStyle) {
  ctx.fillStyle = fillStyle;
  ctx.beginPath();
  if (pointingUp) {
    ctx.moveTo(cx, cy - size);
    ctx.lineTo(cx + size, cy + size);
    ctx.lineTo(cx - size, cy + size);
  } else {
    ctx.moveTo(cx, cy + size);
    ctx.lineTo(cx + size, cy - size);
    ctx.lineTo(cx - size, cy - size);
  }
  ctx.closePath();
  ctx.fill();
}

// --- Direct Graph Rendering ---
function drawCurve() {
  const w = curveCanvas.width;
  const h = curveCanvas.height;
  
  // Clear
  curveCtx.fillStyle = "#0B0B0D";
  curveCtx.fillRect(0, 0, w, h);
  
  // Draw Grid lines
  curveCtx.strokeStyle = "rgba(86, 82, 76, 0.2)";
  curveCtx.lineWidth = 1;
  
  // horizontal decibels
  for (const db of [36, 24, 12, 0, -12, -24, -36]) {
    const y = fy(db, h);
    curveCtx.beginPath();
    curveCtx.moveTo(48, y);
    curveCtx.lineTo(w - 22, y);
    curveCtx.stroke();
    
    curveCtx.fillStyle = "rgba(242, 239, 232, 0.4)";
    curveCtx.font = "9px Spline Sans Mono";
    curveCtx.textAlign = "right";
    curveCtx.fillText(`${db > 0 ? "+" : ""}${db}`, 40, y + 3);
  }
  
  // vertical frequencies
  for (const f of [50, 100, 200, 500, 1000, 2000, 5000, 10000, 15000]) {
    const x = fx(f, w);
    curveCtx.beginPath();
    curveCtx.moveTo(x, 18);
    curveCtx.lineTo(x, h - 30);
    curveCtx.stroke();
    
    curveCtx.fillStyle = "rgba(242, 239, 232, 0.4)";
    curveCtx.font = "9px Spline Sans Mono";
    curveCtx.textAlign = "center";
    curveCtx.fillText(f >= 1000 ? `${f / 1000}k` : String(f), x, h - 14);
  }
  
  // Draw Corridor Guide Band (+33 to +44 dB)
  const y33 = fy(33, h);
  const y44 = fy(44, h);
  curveCtx.fillStyle = "rgba(199, 116, 31, 0.08)";
  curveCtx.fillRect(48, y44, w - 70, y33 - y44);
  
  curveCtx.strokeStyle = "rgba(199, 116, 31, 0.25)";
  curveCtx.lineWidth = 1;
  curveCtx.beginPath();
  curveCtx.moveTo(48, y33); curveCtx.lineTo(w - 22, y33);
  curveCtx.moveTo(48, y44); curveCtx.lineTo(w - 22, y44);
  curveCtx.stroke();
  
  curveCtx.fillStyle = "rgba(199, 116, 31, 0.6)";
  curveCtx.font = "8px Spline Sans Mono";
  curveCtx.textAlign = "left";
  curveCtx.fillText("CORRIDOR LIMIT", 54, y44 - 4);

  // Draw response curves (Frame A / B ghosts, and current live)
  if (STATE.words) {
    drawResponsePath(0.0, STATE.q, "rgba(143, 227, 240, 0.15)", 1.2, true); // Frame A
    drawResponsePath(1.0, STATE.q, "rgba(199, 116, 31, 0.15)", 1.2, true);  // Frame B
    drawResponsePath(STATE.m, STATE.q, "#F2EFE8", 2.3, false);             // Live current
  }
  
  // Draw drag handles for 6 stages (needs packed words + corners from first repack)
  if (!STATE.words || !STATE.corners) return;
  for (let si = 0; si < 6; si++) {
    const live = getStageLive(si);
    if (!live.on) continue;
    
    const isSelected = (si === STATE.selStage);
    
    // Pole Peak handle
    const px = fx(live.hz, w);
    const py = fy(packedDb(STATE.words, STATE.m, STATE.q, live.hz), h);
    
    // Yellow triangle ▲ for poles
    drawTriangle(curveCtx, px, py, isSelected ? 6 : 4, true, "#F5C842");
    
    if (isSelected) {
      curveCtx.strokeStyle = "#8FE3F0"; // Ice glow outline
      curveCtx.lineWidth = 1;
      curveCtx.beginPath();
      curveCtx.arc(px, py, 11, 0, Math.PI * 2);
      curveCtx.stroke();
    }
    
    // Zero Valley handle (connected via dashed line)
    if (live.cutOn) {
      const zx = fx(live.cutHz, w);
      // valley depth
      const zy = fy(packedDb(STATE.words, STATE.m, STATE.q, live.cutHz) - live.cutDepth * 18, h);
      const topY = fy(packedDb(STATE.words, STATE.m, STATE.q, live.cutHz), h);
      
      curveCtx.strokeStyle = "rgba(86, 82, 76, 0.3)";
      curveCtx.setLineDash([2, 2]);
      curveCtx.beginPath();
      curveCtx.moveTo(zx, topY);
      curveCtx.lineTo(zx, zy);
      curveCtx.stroke();
      curveCtx.setLineDash([]);
      
      // Red triangle ▼ for zeros
      drawTriangle(curveCtx, zx, zy, isSelected ? 6 : 4, false, "#E5483C");
      
      if (isSelected) {
        curveCtx.strokeStyle = "#8FE3F0"; // Ice glow outline
        curveCtx.lineWidth = 1;
        curveCtx.strokeRect(zx - 7, zy - 7, 14, 14);
      }
    }
    
    // Label index
    curveCtx.fillStyle = isSelected ? "#8FE3F0" : "rgba(242, 239, 232, 0.6)";
    curveCtx.font = "9px Spline Sans Mono";
    curveCtx.textAlign = "center";
    curveCtx.fillText(String(si + 1), px, py - 14);
  }
}

function drawResponsePath(m, q, color, width, isDashed) {
  const w = curveCanvas.width;
  const h = curveCanvas.height;
  
  curveCtx.save();
  if (isDashed) curveCtx.setLineDash([4, 4]);
  curveCtx.strokeStyle = color;
  curveCtx.lineWidth = width;
  curveCtx.beginPath();
  
  const points = 300;
  for (let i = 0; i < points; i++) {
    const f = Math.exp(logF(F_LO) + (i / (points - 1)) * (logF(F_HI) - logF(F_LO)));
    const x = fx(f, w);
    const y = fy(packedDb(STATE.words, m, q, f), h);
    if (i === 0) curveCtx.moveTo(x, y);
    else curveCtx.lineTo(x, y);
  }
  curveCtx.stroke();
  curveCtx.restore();
}

// --- Draw Spectrogram Field ---
function drawField() {
  const w = fieldCanvas.width;
  const h = fieldCanvas.height;
  
  if (!STATE.words) return;
  
  // Sample a low-res buffer and paint pixels with bilinear smoothing
  const stepsY = 60;
  const stepsX = 120;
  const buffer = new Float32Array(stepsY * stepsX);
  
  const logFlo = Math.log(F_LO);
  const logFhi = Math.log(F_HI);
  const freqs = [];
  for (let x = 0; x < stepsX; x++) {
    freqs.push(Math.exp(logFlo + (x / (stepsX - 1)) * (logFhi - logFlo)));
  }
  
  for (let y = 0; y < stepsY; y++) {
    const morph = y / (stepsY - 1);
    const wAt = wordsAt(STATE.words, morph, STATE.q);
    const bqs = wAt.map(row => kernelToBiquad(stageWordsToKernel(row)));
    
    for (let x = 0; x < stepsX; x++) {
      const f = freqs[x];
      let db = 0;
      for (const bq of bqs) db += biquadDbCoeffs(bq, f);
      buffer[y * stepsX + x] = db;
    }
  }
  
  const imgData = fieldCtx.createImageData(w, h);
  for (let cy = 0; cy < h; cy++) {
    const yFrac = 1 - (cy / (h - 1));
    const yIdx = Math.floor(yFrac * (stepsY - 1));
    const yLerp = yFrac * (stepsY - 1) - yIdx;
    
    for (let cx = 0; cx < w; cx++) {
      const xFrac = cx / (w - 1);
      const xIdx = Math.floor(xFrac * (stepsX - 1));
      const xLerp = xFrac * (stepsX - 1) - xIdx;
      
      const i00 = buffer[yIdx * stepsX + xIdx];
      const i10 = buffer[yIdx * stepsX + xIdx + 1];
      const i01 = buffer[(yIdx + 1) * stepsX + xIdx];
      const i11 = buffer[(yIdx + 1) * stepsX + xIdx + 1];
      
      const v = (1 - yLerp) * (1 - xLerp) * i00 + (1 - yLerp) * xLerp * i10 + yLerp * (1 - xLerp) * i01 + yLerp * xLerp * i11;
      const [r, g, b] = getHeatColor(v);
      
      const pixIdx = (cy * w + cx) * 4;
      imgData.data[pixIdx] = r;
      imgData.data[pixIdx + 1] = g;
      imgData.data[pixIdx + 2] = b;
      imgData.data[pixIdx + 3] = 255;
    }
  }
  
  fieldCtx.putImageData(imgData, 0, 0);
  
  // Draw Headroom Spine (20px left margin gutter)
  fieldCtx.fillStyle = "rgba(26, 25, 28, 0.9)";
  fieldCtx.fillRect(0, 0, 20, h);
  fieldCtx.strokeStyle = "rgba(86, 82, 76, 0.4)";
  fieldCtx.lineWidth = 1;
  fieldCtx.beginPath();
  fieldCtx.moveTo(20, 0); fieldCtx.lineTo(20, h);
  fieldCtx.stroke();
  
  // Draw maximum magnitude flares along the spine
  for (let cy = 0; cy < h; cy++) {
    const yFrac = 1 - (cy / (h - 1));
    const yIdx = Math.floor(yFrac * (stepsY - 1));
    let maxVal = -999;
    for (let x = 0; x < stepsX; x++) {
      maxVal = Math.max(maxVal, buffer[yIdx * stepsX + x]);
    }
    const [r, g, b] = getHeatColor(maxVal);
    fieldCtx.fillStyle = `rgb(${r},${g},${b})`;
    fieldCtx.fillRect(4, cy, 12, 1);
  }

  // Draw current morph playhead bar
  const py = (1 - STATE.m) * h;
  fieldCtx.strokeStyle = "#F2EFE8";
  fieldCtx.lineWidth = 1.5;
  fieldCtx.beginPath();
  fieldCtx.moveTo(20, py);
  fieldCtx.lineTo(w, py);
  fieldCtx.stroke();
  
  // If a stage is selected, overlay its frequency trajectory thread as a glowing Ice line
  if (STATE.selStage !== null) {
    fieldCtx.strokeStyle = "#8FE3F0";
    fieldCtx.lineWidth = 2;
    fieldCtx.beginPath();
    
    for (let cy = 0; cy < h; cy++) {
      const morph = 1 - (cy / (h - 1));
      const live = getStageLive(STATE.selStage);
      
      // Calculate pole frequency at this morph slice
      const c0 = STATE.corners[0][STATE.selStage];
      const c1 = STATE.corners[1][STATE.selStage];
      const c2 = STATE.corners[2][STATE.selStage];
      const c3 = STATE.corners[3][STATE.selStage];
      
      const w00 = (1 - morph) * (1 - STATE.q);
      const w10 = morph * (1 - STATE.q);
      const w01 = (1 - morph) * STATE.q;
      const w11 = morph * STATE.q;
      
      const fHz = Math.exp(w00 * Math.log(c0.hz) + w10 * Math.log(c1.hz) + w01 * Math.log(c2.hz) + w11 * Math.log(c3.hz));
      const cx = fx(fHz, w);
      
      if (cy === 0) fieldCtx.moveTo(cx, cy);
      else fieldCtx.lineTo(cx, cy);
    }
    fieldCtx.stroke();
  }
}

// --- Hit Testing ---
function hitTestGraph(pt) {
  const w = curveCanvas.width;
  const h = curveCanvas.height;
  const range = 18;
  
  for (let si = 0; si < 6; si++) {
    const live = getStageLive(si);
    if (!live.on) continue;
    
    // Check pole peak
    const px = fx(live.hz, w);
    const py = fy(packedDb(STATE.words, STATE.m, STATE.q, live.hz), h);
    if (Math.hypot(pt.x - px, pt.y - py) < range) {
      return { si, type: "pole" };
    }
    
    // Check zero notch
    if (live.cutOn) {
      const zx = fx(live.cutHz, w);
      const zy = fy(packedDb(STATE.words, STATE.m, STATE.q, live.cutHz) - live.cutDepth * 18, h);
      if (Math.hypot(pt.x - zx, pt.y - zy) < range) {
        return { si, type: "zero" };
      }
    }
  }
  return null;
}

// --- Event Listeners for curve canvas ---
function getCanvasCoords(e, canvas) {
  const r = canvas.getBoundingClientRect();
  return {
    x: (e.clientX - r.left) * canvas.width / r.width,
    y: (e.clientY - r.top) * canvas.height / r.height
  };
}

curveCanvas.addEventListener("pointerdown", e => {
  const pt = getCanvasCoords(e, curveCanvas);
  const hit = hitTestGraph(pt);
  
  if (hit) {
    STATE.selStage = hit.si;
    STATE.drag = {
      si: hit.si,
      type: hit.type,
      startX: pt.x,
      startY: pt.y
    };
    curveCanvas.setPointerCapture(e.pointerId);
    repack();
  }
});

curveCanvas.addEventListener("pointermove", e => {
  if (!STATE.drag) return;
  
  const pt = getCanvasCoords(e, curveCanvas);
  const w = curveCanvas.width;
  const h = curveCanvas.height;
  
  if (STATE.drag.type === "pole") {
    // Edit pole frequency (horizontal) and radius (vertical)
    const newHz = snapHz(xToF(pt.x, w));
    const newDb = yToDb(pt.y, h);
    
    // Map peak magnitude back to radius
    // Peak dB is proportional to 1 / (1 - r)
    // Map -36..48 dB range to 0.5..0.9992 radius
    const normDb = clamp((newDb - DB_LO) / (DB_HI - DB_LO), 0, 1);
    const newR = clamp(0.5 + normDb * 0.4992, 0.5, 0.9992);
    
    distributeEdit(STATE.drag.si, "hz", newHz, true);
    distributeEdit(STATE.drag.si, "r", newR, false);
  } else if (STATE.drag.type === "zero") {
    // Edit zero frequency (horizontal) and notch depth (vertical)
    const newHz = snapHz(xToF(pt.x, w));
    const newDb = yToDb(pt.y, h);
    
    // Map notch depth back to zero radius
    const peakDb = packedDb(STATE.words, STATE.m, STATE.q, newHz);
    const diffDb = clamp(peakDb - newDb, 0, 60);
    const newDepth = clamp(diffDb / 60.0, 0.05, 0.9995);
    
    distributeEdit(STATE.drag.si, "cutHz", newHz, true);
    distributeEdit(STATE.drag.si, "cutDepth", newDepth, false);
  }
  
  repack();
});

curveCanvas.addEventListener("pointerup", () => {
  STATE.drag = null;
  repack();
});

// --- UI Rendering ---
function renderUI() {
  $("morphVal").textContent = STATE.m.toFixed(2);
  $("qVal").textContent = STATE.q.toFixed(2);
  $("morphSlider").value = Math.round(STATE.m * 100);
  $("qSlider").value = Math.round(STATE.q * 100);
  $("driveVal").textContent = Math.round(STATE.drive * 100);
  $("driveSlider").value = Math.round(STATE.drive * 100);
  
  // Lanes list
  const list = $("laneList");
  list.innerHTML = "";
  for (let si = 0; si < 6; si++) {
    const live = getStageLive(si);
    const row = document.createElement("div");
    row.className = `laneRow ${si === STATE.selStage ? "selected" : ""}`;
    row.innerHTML = `
      <div class="index">${si + 1}</div>
      <div class="role">${live.role || `stage_${si + 1}`}</div>
      <div class="vals">
        pole: <span>${Math.round(live.hz)}</span> Hz / <span>${live.r.toFixed(3)}</span><br>
        zero: <span>${live.cutOn ? Math.round(live.cutHz) : "off"}</span> / <span>${live.cutOn ? live.cutDepth.toFixed(3) : "—"}</span>
      </div>
    `;
    row.onclick = () => {
      STATE.selStage = si;
      renderUI();
    };
    list.appendChild(row);
  }
  
  $("status").textContent = `Words Interpolated · Max Radius: ${STATE.worstR.toFixed(5)} · Verdict: ${STATE.auditVerdict}`;
  
  drawCurve();
  drawField();
}

// --- FFI and Audio Worklet playback ---
let actx = null, anode = null;
function getDriveParameters() {
  const d = clamp(STATE.drive, 0, 1);
  return {
    agc: 4.0 + 4.0 * d,
    slam: 0.25 * d * d,
    wide: 0.0,
    inputGain: 1.0,
    makeup: 1.5 + 2.5 * d
  };
}

function pushEngineParams() {
  if (!anode) return;
  const p = getDriveParameters();
  anode.port.postMessage({
    params: {
      morph: STATE.m,
      q: STATE.q,
      agc: p.agc,
      slam: p.slam,
      wide: p.wide,
      inputGain: p.inputGain,
      makeup: p.makeup
    }
  });
}

async function startAudio() {
  actx = new (window.AudioContext || window.webkitAudioContext)();
  const wasmRes = await fetch("wasm/forge_web_wasm.wasm");
  const wasm = await wasmRes.arrayBuffer();
  
  await actx.audioWorklet.addModule("js/forge-worklet.js");
  
  anode = new AudioWorkletNode(actx, "forge-processor", {
    numberOfInputs: 0,
    numberOfOutputs: 1,
    outputChannelCount: [2],
    processorOptions: {
      wasm,
      body: STATE.bytes ? STATE.bytes.buffer.slice(0) : null,
      src: STATE.src
    }
  });
  
  anode.port.onmessage = e => {
    if (e.data.ready) {
      pushEngineParams();
      if (STATE.playing) anode.port.postMessage({ playing: true });
    }
    if (e.data.level != null) {
      const m = $("meter");
      m.firstElementChild.style.width = Math.min(100, e.data.level * 140) + "%";
      m.classList.toggle("flood", e.data.peak > 0.985);
    }
  };
  
  anode.connect(actx.destination);
}

async function toggleAudio() {
  try {
    if (!actx) await startAudio();
    if (actx.state === "suspended") await actx.resume();
    
    STATE.playing = !STATE.playing;
    if (anode) anode.port.postMessage({ playing: STATE.playing });
    
    const playBtn = $("playBtn");
    playBtn.classList.toggle("primary", STATE.playing);
    playBtn.textContent = STATE.playing ? "❚❚ stop" : "▶ play";
  } catch (err) {
    console.error("Audio activation failed:", err);
    $("status").textContent = `Audio Error: ${err.message}`;
  }
}

// --- Wire UI Events ---
$("morphSlider").oninput = e => {
  STATE.m = +e.target.value / 100;
  pushEngineParams();
  renderUI();
};

$("qSlider").oninput = e => {
  STATE.q = +e.target.value / 100;
  pushEngineParams();
  renderUI();
};

$("driveSlider").oninput = e => {
  STATE.drive = +e.target.value / 100;
  pushEngineParams();
  renderUI();
};

$("playBtn").onclick = toggleAudio;

// Excitation Source Toggles
document.querySelectorAll("#foot [data-src]").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll("#foot [data-src]").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    STATE.src = +b.dataset.src;
    if (anode) anode.port.postMessage({ src: STATE.src });
  };
});

// Snap Rails Toggles
document.querySelectorAll("#railSelect [data-rail]").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll("#railSelect [data-rail]").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    STATE.railMode = b.dataset.rail;
  };
});

// Seed Toggles
document.querySelectorAll("#seedSelect [data-seed]").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll("#seedSelect [data-seed]").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    applySeed(b.dataset.seed);
  };
});

$("nameInput").oninput = e => {
  STATE.name = e.target.value.trim() || "untitled";
};

$("resetBtn").onclick = () => {
  applySeed("blank");
};

$("saveBtn").onclick = () => {
  downloadBody(`${STATE.name}.body240`, STATE.hex);
  $("status").textContent = `Exported body: ${STATE.name}.body240`;
};

// --- Initialization ---
function resizeCanvases() {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  
  const curveW = curveCanvas.clientWidth;
  const curveH = curveCanvas.clientHeight;
  curveCanvas.width = curveW * dpr;
  curveCanvas.height = curveH * dpr;
  curveCtx.scale(dpr, dpr);
  
  const fieldW = fieldCanvas.clientWidth;
  const fieldH = fieldCanvas.clientHeight;
  fieldCanvas.width = fieldW * dpr;
  fieldCanvas.height = fieldH * dpr;
  fieldCtx.scale(dpr, dpr);
  
  drawCurve();
  drawField();
}

window.addEventListener("resize", resizeCanvases);

// Boot up
const bootSeed = "vow_aah_eee";
document.querySelector(`#seedSelect [data-seed="${bootSeed}"]`)?.classList.add("active");
applySeed(bootSeed);
setTimeout(resizeCanvases, 200);
