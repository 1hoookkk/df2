const DEFAULT_STAGE = [
  {
    active: true,
    label: "contrary tear actor",
    home: { freq_hz: 246, shelf: -50, peak_db: -24 },
    away: { freq_hz: 4488, shelf: 30, peak_db: 1.5 },
  },
  { active: false, label: "neutral", home: {}, away: {} },
  { active: false, label: "neutral", home: {}, away: {} },
  { active: false, label: "neutral", home: {}, away: {} },
  { active: false, label: "neutral", home: {}, away: {} },
  { active: false, label: "neutral", home: {}, away: {} },
];

let stages = structuredClone(DEFAULT_STAGE);
let foundationAnchors = [
  { hz: 530, band: "low-mid", skin_count: 41, total_hits: 135 },
  { hz: 390, band: "low-mid", skin_count: 40, total_hits: 370 },
  { hz: 355, band: "low-mid", skin_count: 39, total_hits: 120 },
  { hz: 270, band: "low", skin_count: 36, total_hits: 110 },
  { hz: 780, band: "mouth", skin_count: 31, total_hits: 203 },
  { hz: 194, band: "low", skin_count: 26, total_hits: 292 },
  { hz: 98, band: "sub", skin_count: 21, total_hits: 239 },
];

const $ = (id) => document.getElementById(id);

function numberValue(id, fallback) {
  const n = Number($(id).value);
  return Number.isFinite(n) ? n : fallback;
}

function endpointInput(stageIndex, frame, key, fallback) {
  const id = `s${stageIndex}_${frame}_${key}`;
  const n = Number($(id).value);
  return Number.isFinite(n) ? n : fallback;
}

function stageRow(stage, i) {
  const home = stage.home || {};
  const away = stage.away || {};
  return `
    <div class="stage">
      <div class="stageHead">
        <div>
          <label for="s${i}_active">on</label>
          <select id="s${i}_active">
            <option value="1"${stage.active ? " selected" : ""}>on</option>
            <option value="0"${!stage.active ? " selected" : ""}>off</option>
          </select>
        </div>
        <div>
          <label for="s${i}_label">lane ${i + 1}</label>
          <input id="s${i}_label" value="${escapeAttr(stage.label || "")}">
        </div>
        <div class="kindWrap">
          <label>kind</label>
          <input value="${stage.active ? "peak_shelf" : "identity"}" disabled>
        </div>
      </div>
      <div class="frames">
        ${frameBlock(i, "home", "A", home)}
        ${frameBlock(i, "away", "B", away)}
      </div>
    </div>`;
}

function frameBlock(i, key, label, data) {
  return `
    <div class="frame">
      <b>FRAME ${label}</b>
      <div class="grid3">
        <div>
          <label for="s${i}_${key}_freq_hz">freq</label>
          <input id="s${i}_${key}_freq_hz" inputmode="decimal" value="${data.freq_hz ?? ""}">
        </div>
        <div>
          <label for="s${i}_${key}_shelf">shelf</label>
          <input id="s${i}_${key}_shelf" inputmode="decimal" value="${data.shelf ?? ""}">
        </div>
        <div>
          <label for="s${i}_${key}_peak_db">peak</label>
          <input id="s${i}_${key}_peak_db" inputmode="decimal" value="${data.peak_db ?? ""}">
        </div>
      </div>
    </div>`;
}

function escapeAttr(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch]);
}

function renderStages() {
  $("stages").innerHTML = stages.map(stageRow).join("");
}

function renderFoundationOptions() {
  const select = $("foundation");
  select.innerHTML = "";
  const off = document.createElement("option");
  off.value = "off";
  off.textContent = "none";
  select.appendChild(off);
  for (const anchor of foundationAnchors) {
    const opt = document.createElement("option");
    opt.value = String(anchor.hz);
    opt.textContent = `${Math.round(anchor.hz)} Hz · ${anchor.band} · ${anchor.skin_count}/50`;
    if (Math.round(anchor.hz) === 530) opt.selected = true;
    select.appendChild(opt);
  }
}

function collectCard() {
  const foundationValue = $("foundation").value;
  const sections = [];
  for (let i = 0; i < 6; i++) {
    const active = $(`s${i}_active`).value === "1";
    if (!active) {
      sections.push({ lane: i + 1, kind: "identity", label: $(`s${i}_label`).value || "neutral" });
      continue;
    }
    sections.push({
      lane: i + 1,
      kind: "peak_shelf",
      label: $(`s${i}_label`).value || `section ${i + 1}`,
      home: {
        freq_hz: endpointInput(i, "home", "freq_hz", 1000),
        shelf: endpointInput(i, "home", "shelf", 0),
        peak_db: endpointInput(i, "home", "peak_db", 0),
      },
      away: {
        freq_hz: endpointInput(i, "away", "freq_hz", 1000),
        shelf: endpointInput(i, "away", "shelf", 0),
        peak_db: endpointInput(i, "away", "peak_db", 0),
      },
    });
  }
  return {
    format: "filter-card-v1",
    name: $("cardName").value || "filter_card",
    foundation: {
      enabled: foundationValue !== "off",
      lane: 2,
      anchor_hz: foundationValue === "off" ? 530 : Number(foundationValue),
    },
    q_peak_db: 3.0,
    q_gain_db: 0.8,
    sections,
  };
}

function setBusy(on) {
  $("bake").disabled = on;
  $("reset").disabled = on;
}

function log(value) {
  $("log").textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function setVerdict(text, ok) {
  const v = $("verdict");
  v.textContent = text;
  v.className = `pill ${ok === true ? "good" : ok === false ? "bad" : ""}`;
}

function artifactLinks(artifacts) {
  const links = $("links");
  links.innerHTML = "";
  if (!artifacts) return;
  for (const [key, item] of Object.entries(artifacts)) {
    if (!item || !item.url) continue;
    const a = document.createElement("a");
    a.href = item.url;
    a.textContent = key;
    a.target = "_blank";
    links.appendChild(a);
  }
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

async function health() {
  try {
    const data = await api("/api/health");
    const core = data.trenchCore || {};
    $("health").textContent = `probe ${core.packedProbe ? "ok" : "missing"} / engine ${core.engine ? "ok" : "missing"}`;
  } catch (err) {
    $("health").textContent = `api offline`;
  }
}

async function loadFoundations() {
  try {
    const data = await api("/api/foundations/anchors");
    if (Array.isArray(data.anchors) && data.anchors.length) {
      foundationAnchors = data.anchors;
      renderFoundationOptions();
    }
  } catch (_err) {
    renderFoundationOptions();
  }
}

async function bake() {
  setBusy(true);
  setVerdict("baking", null);
  artifactLinks(null);
  $("plot").style.display = "none";
  try {
    const payload = {
      session: $("session").value || undefined,
      grid: numberValue("grid", 17),
      card: collectCard(),
    };
    log({ request: "bake", card: payload.card.name });
    const result = await api("/api/filter-card/bake", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setVerdict(result.verdict || (result.ok ? "PASS" : "WARN"), !!result.ok);
    artifactLinks(result.artifacts);
    log({
      ok: result.ok,
      verdict: result.verdict,
      bodyBytes: result.bodyBytes,
      runDir: result.runDir,
      checks: result.audit && result.audit.checks,
      warnings: result.warnings,
    });
    if (result.artifacts && result.artifacts.response) {
      $("plot").src = `${result.artifacts.response.url}?t=${Date.now()}`;
      $("plot").style.display = "block";
    }
  } catch (err) {
    setVerdict("ERROR", false);
    log(String(err.message || err));
  } finally {
    setBusy(false);
  }
}

function reset() {
  stages = structuredClone(DEFAULT_STAGE);
  $("cardName").value = "contrary_peak_shelf_sweep";
  $("foundation").value = "530";
  $("grid").value = "17";
  $("session").value = "";
  renderStages();
  setVerdict("idle", null);
  log("idle");
  artifactLinks(null);
  $("plot").style.display = "none";
}

renderStages();
renderFoundationOptions();
$("bake").addEventListener("click", bake);
$("reset").addEventListener("click", reset);
health();
loadFoundations();
