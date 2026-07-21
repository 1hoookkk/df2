#!/usr/bin/env python3
"""Small raw-table picker for manually assembling the four packed corners.

This surface deliberately stops before fitting, lane registration, packing, or
audio.  It exposes the measured ``*.tf.json`` curves as-is and only produces a
recipe containing the four selected source paths.

Run from the workstation root::

    python -m tools.table_stitch_gui

Then open http://127.0.0.1:8758/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent.parent
TABLE_ROOT = ROOT / "dev" / "tmp"
DEFAULT_PORT = 8758


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _inside_root(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError("table must live inside the workstation") from exc
    return resolved


def _read_tf(path: Path) -> dict:
    """Read one raw TF file and reject malformed/non-finite data."""
    path = _inside_root(path)
    if not path.name.endswith(".tf.json"):
        raise ValueError("only .tf.json tables are accepted")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path.name}") from exc

    freqs = payload.get("freqs_hz")
    mags = payload.get("mag_db")
    if not isinstance(freqs, list) or not isinstance(mags, list):
        raise ValueError(f"{path.name} has no freqs_hz/mag_db arrays")
    if len(freqs) != len(mags) or len(freqs) < 2:
        raise ValueError(f"{path.name} has mismatched or empty arrays")

    clean_freqs: list[float] = []
    clean_mags: list[float] = []
    previous = 0.0
    for index, (frequency, magnitude) in enumerate(zip(freqs, mags)):
        try:
            frequency = float(frequency)
            magnitude = float(magnitude)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path.name} has non-numeric row {index}") from exc
        if not math.isfinite(frequency) or not math.isfinite(magnitude):
            raise ValueError(f"{path.name} has non-finite row {index}")
        if index and frequency <= previous:
            raise ValueError(f"{path.name} frequencies are not strictly ascending")
        previous = frequency
        clean_freqs.append(frequency)
        clean_mags.append(magnitude)

    return {
        "freqs_hz": clean_freqs,
        "mag_db": clean_mags,
        "source": payload.get("source", ""),
        "kind": payload.get("kind", "tf"),
    }


def _table_paths() -> list[Path]:
    if not TABLE_ROOT.exists():
        return []
    return sorted(
        (path for path in TABLE_ROOT.rglob("*.tf.json") if path.is_file()),
        key=lambda path: _relative(path).lower(),
    )


def _metadata(path: Path, payload: dict | None = None) -> dict:
    path = _inside_root(path)
    payload = payload or _read_tf(path)
    freqs = payload["freqs_hz"]
    mags = payload["mag_db"]
    return {
        "path": _relative(path),
        "name": path.name,
        "folder": _relative(path.parent),
        "rows": len(freqs),
        "min_hz": freqs[0],
        "max_hz": freqs[-1],
        "min_db": min(mags),
        "max_db": max(mags),
        "source": payload.get("source", ""),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _catalog() -> tuple[list[dict], dict]:
    records: list[dict] = []
    for path in _table_paths():
        try:
            payload = _read_tf(path)
            records.append(_metadata(path, payload))
        except ValueError:
            # An invalid table is not silently displayed as usable.  It is
            # omitted from the picker; the endpoint still reports the error
            # if someone requests it directly.
            continue

    if records:
        min_hz = min(record["min_hz"] for record in records)
        max_hz = max(record["max_hz"] for record in records)
        min_db = min(record["min_db"] for record in records)
        max_db = max(record["max_db"] for record in records)
    else:
        min_hz, max_hz, min_db, max_db = 30.0, 19200.0, -60.0, 20.0

    # One shared scale makes a curve move because the table changed, not
    # because the plot silently rescaled around it.
    plot_min_db = math.floor(min(min_db, 0.0) / 5.0) * 5.0 - 5.0
    plot_max_db = math.ceil(max(max_db, 0.0) / 5.0) * 5.0 + 5.0
    scale = {
        "min_hz": min_hz,
        "max_hz": max_hz,
        "min_db": plot_min_db,
        "max_db": plot_max_db,
    }
    return records, scale


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


PAGE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>table stitcher</title>
<style>
:root {
  color-scheme: dark;
  --bg: #0a0f0e;
  --panel: #111917;
  --panel-2: #151f1b;
  --line: #30433b;
  --line-bright: #557465;
  --text: #e9eee7;
  --muted: #9aaa9d;
  --dim: #718177;
  --gold: #efc36b;
  --cyan: #55d8e8;
  --green: #9ed7af;
  --danger: #f28c7e;
}
* { box-sizing: border-box; }
html, body { margin: 0; min-width: 1120px; background: var(--bg); color: var(--text); font: 14px/1.35 Inter, ui-sans-serif, system-ui, sans-serif; }
body { padding: 28px 34px 42px; }
button, input, select { font: inherit; }
button { cursor: pointer; }
.page { max-width: 1640px; margin: 0 auto; }
.eyebrow { color: var(--cyan); letter-spacing: .18em; text-transform: uppercase; font-size: 11px; font-weight: 750; }
h1 { margin: 7px 0 4px; font-size: clamp(32px, 4vw, 54px); line-height: .98; letter-spacing: -.045em; }
.intro { margin: 0; color: var(--muted); max-width: 840px; }
.topbar { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 22px; }
.actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: end; }
label { color: var(--muted); font-size: 12px; }
input, select { background: #0c1311; color: var(--text); border: 1px solid var(--line-bright); border-radius: 5px; padding: 9px 10px; outline: none; }
input:focus, select:focus { border-color: var(--cyan); box-shadow: 0 0 0 2px #55d8e822; }
input[type="text"] { width: 184px; }
button { border: 1px solid var(--line-bright); border-radius: 5px; padding: 9px 12px; color: var(--text); background: #1a2a23; }
button:hover { border-color: var(--cyan); background: #20372e; }
button.secondary { background: transparent; color: var(--muted); }
button.warn { border-color: #775044; color: #f1b2a6; background: transparent; }
.workbench { display: grid; grid-template-columns: 370px minmax(0, 1fr); gap: 18px; align-items: start; }
.panel, .corner, .recipe { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
.panel { overflow: hidden; }
.panel-head, .section-head, .recipe-head { padding: 14px 16px; border-bottom: 1px solid var(--line); display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.panel-head strong, .section-head strong, .recipe-head strong { font-size: 16px; letter-spacing: -.01em; }
.count, .tiny { color: var(--dim); font-size: 11px; }
.library-tools { padding: 12px; border-bottom: 1px solid var(--line); }
.load-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 7px; }
.load-row input { width: 100%; }
.drop-zone { margin-top: 8px; padding: 8px 9px; border: 1px dashed #476052; border-radius: 5px; color: var(--dim); font-size: 11px; text-align: center; }
.drop-zone.over { border-color: var(--cyan); color: var(--text); background: #12231d; }
#library { padding: 10px; display: grid; gap: 9px; max-height: calc(100vh - 260px); overflow: auto; }
.table-card { display: block; width: 100%; padding: 0; text-align: left; background: var(--panel-2); border: 1px solid #2d4438; border-radius: 5px; overflow: hidden; }
.table-card .thumb { display: block; width: 100%; height: 92px; border-bottom: 1px solid #283a31; background: #0b110f; }
.table-info { display: grid; gap: 3px; padding: 8px 10px 9px; }
.table-name { color: var(--text); font-weight: 700; overflow-wrap: anywhere; }
.table-source { color: var(--dim); font-size: 11px; }
.empty-library { padding: 18px; color: var(--muted); }
.stitch-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 10px; }
.stitch-head .plain { color: var(--muted); font-size: 12px; }
.slots { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.corner { min-width: 0; overflow: hidden; }
.corner-head { display: flex; align-items: center; justify-content: space-between; gap: 9px; padding: 13px 14px 10px; }
.corner-label { display: flex; flex-direction: column; gap: 2px; color: var(--gold); font-weight: 800; letter-spacing: .03em; }
.corner-detail { color: var(--dim); font-size: 10px; font-weight: 500; letter-spacing: 0; }
.corner-controls { display: flex; align-items: center; gap: 7px; min-width: 0; }
.corner-controls select { min-width: 0; width: 270px; padding: 7px 8px; font-size: 12px; }
.corner-controls .clear { padding: 7px 8px; color: var(--muted); background: transparent; }
.plot { margin: 0 12px 12px; border: 1px solid #2b3b34; border-radius: 5px; background: #0b110f; overflow: hidden; }
.plot svg { display: block; width: 100%; height: auto; }
.empty-plot { min-height: 246px; display: grid; place-items: center; color: var(--dim); font-size: 12px; }
.corner-meta { padding: 0 14px 12px; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; min-height: 30px; }
.recipe { margin-top: 14px; overflow: hidden; }
.recipe-head { align-items: center; }
.recipe-head .buttons { display: flex; gap: 7px; }
.recipe details { border-top: 1px solid var(--line); }
.recipe summary { padding: 10px 16px; color: var(--muted); cursor: pointer; font-size: 12px; }
#recipe { margin: 0; padding: 13px 16px 15px; color: var(--green); background: #0b110f; font: 12px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow: auto; }
.status { min-height: 20px; margin-top: 9px; color: var(--muted); font-size: 12px; }
.status.error { color: var(--danger); }
@media (max-width: 1220px) {
  html, body { min-width: 0; }
  body { padding: 20px; }
  .topbar { display: block; }
  .actions { justify-content: start; margin-top: 14px; }
  .workbench { grid-template-columns: 320px minmax(0, 1fr); }
  .corner-controls select { width: 210px; }
}
</style>
</head>
<body>
<main class="page">
  <div class="topbar">
    <div>
      <div class="eyebrow">table picker</div>
      <h1>Build a table map</h1>
      <p class="intro">See every curve, choose one table for each corner, and save the map.</p>
    </div>
    <div class="actions">
      <label for="body-name">Map name</label>
      <input id="body-name" type="text" value="my_table_map">
      <button id="clear-all" class="warn">Clear</button>
    </div>
  </div>

  <div class="workbench">
    <aside class="panel">
      <div class="panel-head"><strong>Tables</strong><span id="table-count" class="count">loading</span></div>
      <div class="library-tools">
        <div class="load-row">
          <input id="filter" type="search" placeholder="find a table">
          <button id="load-files" class="secondary" type="button">Load files</button>
          <input id="file-input" type="file" accept=".tf.json,.json" multiple hidden>
        </div>
        <div id="drop-zone" class="drop-zone">drop table files here</div>
      </div>
      <div id="library"></div>
    </aside>

    <section>
      <div class="stitch-head">
        <div><strong>Four corners</strong><div class="plain">Choose one table in each box. The lines are the tables themselves.</div></div>
      </div>
      <div id="slots" class="slots"></div>

      <div class="recipe">
        <div class="recipe-head">
          <strong>Save this map</strong>
          <div class="buttons"><button id="copy" class="secondary">Copy map</button><button id="download">Save map</button></div>
        </div>
        <details>
          <summary>Show map data</summary>
          <pre id="recipe"></pre>
        </details>
      </div>
      <div id="status" class="status"></div>
    </section>
  </div>
</main>
<script>
const CORNERS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
const state = { M0_Q0: null, M100_Q0: null, M0_Q100: null, M100_Q100: null };
const tableCache = new Map();
let catalog = [];
let scale = { min_hz: 30, max_hz: 19200, min_db: -50, max_db: 60 };
const CORNER_LABELS = {
  M0_Q0: "Corner A",
  M100_Q0: "Corner B",
  M0_Q100: "Corner C",
  M100_Q100: "Corner D",
};
const CORNER_DETAILS = {
  M0_Q0: "Morph 0 · Q 0",
  M100_Q0: "Morph 100 · Q 0",
  M0_Q100: "Morph 0 · Q 100",
  M100_Q100: "Morph 100 · Q 100",
};

const el = (id) => document.getElementById(id);
const esc = (value) => String(value).replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const nice = (value, digits = 1) => Number(value).toFixed(digits).replace(/\.0+$/, "");
const hz = (value) => value >= 1000 ? `${nice(value / 1000, value >= 10000 ? 0 : 1)}k` : `${Math.round(value)}`;

function xMap(value, width, pad) {
  const lo = Math.log10(scale.min_hz);
  const hi = Math.log10(scale.max_hz);
  return pad.left + (Math.log10(value) - lo) / (hi - lo) * (width - pad.left - pad.right);
}
function yMap(value, height, pad) {
  return pad.top + (scale.max_db - value) / (scale.max_db - scale.min_db) * (height - pad.top - pad.bottom);
}

function plotSvg(table, thumb = false) {
  const width = thumb ? 348 : 760;
  const height = thumb ? 92 : 276;
  const pad = thumb ? { left: 6, right: 5, top: 6, bottom: 6 } : { left: 45, right: 14, top: 15, bottom: 30 };
  const clipId = `clip-${thumb ? "t" : "s"}-${Math.random().toString(36).slice(2)}`;
  const verticalTicks = thumb ? [] : [30, 100, 1000, 10000, 20000].filter((v) => v >= scale.min_hz && v <= scale.max_hz);
  const horizontalTicks = thumb ? [] : (() => {
    const out = [];
    for (let value = Math.ceil(scale.min_db / 10) * 10; value <= scale.max_db; value += 10) out.push(value);
    return out;
  })();
  const pathParts = [];
  const limit = thumb ? 360 : 920;
  const step = Math.max(1, Math.ceil(table.freqs_hz.length / limit));
  for (let i = 0; i < table.freqs_hz.length; i += step) {
    const x = xMap(table.freqs_hz[i], width, pad).toFixed(2);
    const y = yMap(table.mag_db[i], height, pad).toFixed(2);
    pathParts.push(`${pathParts.length ? "L" : "M"}${x},${y}`);
  }
  const last = table.freqs_hz.length - 1;
  const lastX = xMap(table.freqs_hz[last], width, pad).toFixed(2);
  const lastY = yMap(table.mag_db[last], height, pad).toFixed(2);
  if (!pathParts.length || pathParts[pathParts.length - 1] !== `L${lastX},${lastY}`) pathParts.push(`L${lastX},${lastY}`);
  const grid = [];
  for (const value of verticalTicks) {
    const x = xMap(value, width, pad).toFixed(2);
    grid.push(`<line x1="${x}" y1="${pad.top}" x2="${x}" y2="${height - pad.bottom}" class="grid"/><text x="${x}" y="${height - 9}" text-anchor="middle" class="axis">${hz(value)}</text>`);
  }
  for (const value of horizontalTicks) {
    const y = yMap(value, height, pad).toFixed(2);
    grid.push(`<line x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}" class="grid"/><text x="${pad.left - 7}" y="${Number(y) + 4}" text-anchor="end" class="axis">${value}</text>`);
  }
  const zeroY = yMap(0, height, pad).toFixed(2);
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="raw magnitude plot for ${esc(table.name)}">
    <defs><clipPath id="${clipId}"><rect x="${pad.left}" y="${pad.top}" width="${width - pad.left - pad.right}" height="${height - pad.top - pad.bottom}"/></clipPath></defs>
    <style>.grid{stroke:#24342d;stroke-width:1}.axis{fill:#718177;font:10px ui-monospace,monospace}.zero{stroke:#557465;stroke-width:1}.curve{fill:none;stroke:#efc36b;stroke-width:${thumb ? 1.25 : 1.8};stroke-linejoin:round;stroke-linecap:round}</style>
    ${grid.join("")}
    <line x1="${pad.left}" y1="${zeroY}" x2="${width - pad.right}" y2="${zeroY}" class="zero"/>
    <path d="${pathParts.join(" ")}" class="curve" clip-path="url(#${clipId})"/>
    ${thumb ? "" : `<text x="${width / 2}" y="${height - 4}" text-anchor="middle" class="axis">frequency (Hz, log)</text><text x="12" y="${height / 2}" transform="rotate(-90 12 ${height / 2})" text-anchor="middle" class="axis">dB</text>`}
  </svg>`;
}

function emptyPlot() {
  return `<div class="empty-plot">choose a table</div>`;
}

function recipeObject() {
  const corners = Object.fromEntries(CORNERS.map((corner) => {
    const path = state[corner];
    if (!path) return [corner, null];
    const table = catalog.find((item) => item.path === path);
    return [corner, table && table.local ? { file: table.name } : path];
  }));
  return {
    schema_version: 1,
    name: el("body-name").value.trim() || "my_table_map",
    corners,
  };
}
function renderRecipe() {
  el("recipe").textContent = JSON.stringify(recipeObject(), null, 2);
}
function setStatus(message, error = false) {
  el("status").textContent = message;
  el("status").className = `status${error ? " error" : ""}`;
}

function renderLibrary() {
  const query = el("filter").value.trim().toLowerCase();
  const visible = catalog.filter((table) => table.name.toLowerCase().includes(query));
  el("table-count").textContent = query ? `${visible.length} of ${catalog.length}` : `${catalog.length} table${catalog.length === 1 ? "" : "s"}`;
  if (!visible.length) {
    el("library").innerHTML = `<div class="empty-library">no matching tables</div>`;
    return;
  }
  el("library").innerHTML = visible.map((table) => {
    const data = tableCache.get(table.path);
    const plot = data ? plotSvg(data, true) : `<div class="empty-plot">loading</div>`;
    return `<article class="table-card"><span class="thumb">${plot}</span><span class="table-info"><span class="table-name">${esc(table.name)}</span><span class="table-source">${table.local ? "loaded file" : "included"}</span></span></article>`;
  }).join("");
}

function renderSlots() {
  el("slots").innerHTML = CORNERS.map((corner) => {
    const selectedPath = state[corner];
    const table = selectedPath ? tableCache.get(selectedPath) : null;
    const options = [`<option value="">Choose a table</option>`].concat(catalog.map((item) => `<option value="${esc(item.path)}"${item.path === selectedPath ? " selected" : ""}>${esc(item.name)}</option>`));
    const meta = table ? esc(table.name) : "Choose a table";
    return `<article class="corner"><div class="corner-head"><div class="corner-label">${CORNER_LABELS[corner]}<span class="corner-detail">${CORNER_DETAILS[corner]}</span></div><div class="corner-controls"><select data-corner="${corner}" aria-label="table for ${CORNER_LABELS[corner]} (${CORNER_DETAILS[corner]})">${options.join("")}</select><button class="clear" data-clear="${corner}" title="clear ${CORNER_LABELS[corner]}">clear</button></div></div><div class="plot">${table ? plotSvg(table) : emptyPlot()}</div><div class="corner-meta">${meta}</div></article>`;
  }).join("");
  el("slots").querySelectorAll("select[data-corner]").forEach((select) => {
    select.addEventListener("change", () => {
      const corner = select.dataset.corner;
      state[corner] = select.value || null;
      renderSlots();
      renderRecipe();
      const table = select.value ? catalog.find((item) => item.path === select.value) : null;
      setStatus(select.value ? `${CORNER_LABELS[corner]}: ${table.name}.` : `${CORNER_LABELS[corner]} cleared.`);
    });
  });
  el("slots").querySelectorAll("button[data-clear]").forEach((button) => {
    button.addEventListener("click", () => {
      state[button.dataset.clear] = null;
      renderSlots();
      renderRecipe();
      setStatus(`${CORNER_LABELS[button.dataset.clear]} cleared.`);
    });
  });
}

function extendScale(table) {
  const minFrequency = table.freqs_hz[0];
  const maxFrequency = table.freqs_hz[table.freqs_hz.length - 1];
  const minDb = Math.min(...table.mag_db);
  const maxDb = Math.max(...table.mag_db);
  scale.min_hz = Math.min(scale.min_hz, minFrequency);
  scale.max_hz = Math.max(scale.max_hz, maxFrequency);
  if (minDb < scale.min_db) scale.min_db = Math.floor(minDb / 5) * 5 - 5;
  if (maxDb > scale.max_db) scale.max_db = Math.ceil(maxDb / 5) * 5 + 5;
}

function localTableFromPayload(payload, file) {
  const freqs = payload && payload.freqs_hz;
  const mags = payload && payload.mag_db;
  if (!Array.isArray(freqs) || !Array.isArray(mags) || freqs.length !== mags.length || freqs.length < 2) {
    throw new Error(`${file.name}: expected freqs_hz and mag_db arrays.`);
  }
  const cleanFreqs = [];
  const cleanMags = [];
  let previous = 0;
  for (let index = 0; index < freqs.length; index += 1) {
    const frequency = Number(freqs[index]);
    const magnitude = Number(mags[index]);
    if (!Number.isFinite(frequency) || !Number.isFinite(magnitude) || frequency <= 0 || (index && frequency <= previous)) {
      throw new Error(`${file.name}: frequencies must rise and values must be finite.`);
    }
    previous = frequency;
    cleanFreqs.push(frequency);
    cleanMags.push(magnitude);
  }
  const path = `local:${encodeURIComponent(file.name)}:${file.size}:${file.lastModified}`;
  const table = { path, name: file.name, freqs_hz: cleanFreqs, mag_db: cleanMags, local: true };
  const metadata = {
    path,
    name: file.name,
    folder: "Loaded files",
    rows: cleanFreqs.length,
    min_hz: cleanFreqs[0],
    max_hz: cleanFreqs[cleanFreqs.length - 1],
    min_db: Math.min(...cleanMags),
    max_db: Math.max(...cleanMags),
    local: true,
  };
  tableCache.set(path, table);
  const existing = catalog.findIndex((item) => item.path === path);
  if (existing >= 0) catalog[existing] = metadata;
  else catalog.push(metadata);
  extendScale(table);
  return table;
}

async function addFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  const results = await Promise.all(files.map(async (file) => {
    try {
      if (!/\.json$/i.test(file.name)) throw new Error(`${file.name}: use a JSON table file.`);
      localTableFromPayload(JSON.parse(await file.text()), file);
      return { ok: true };
    } catch (error) {
      return { ok: false, message: error.message || String(error) };
    }
  }));
  const added = results.filter((result) => result.ok).length;
  const failed = results.filter((result) => !result.ok);
  renderSlots();
  renderLibrary();
  renderRecipe();
  el("file-input").value = "";
  if (added) {
    setStatus(`${added} table${added === 1 ? "" : "s"} loaded from your files${failed.length ? `; ${failed.length} skipped` : ""}.`);
  } else {
    setStatus(failed[0] ? failed[0].message : "No files loaded.", true);
  }
}

async function load() {
  try {
    const response = await fetch("/tables");
    if (!response.ok) throw new Error(`catalog request failed (${response.status})`);
    const payload = await response.json();
    catalog = payload.tables;
    scale = payload.scale;
    renderSlots();
    renderLibrary();
    renderRecipe();
    const loaded = await Promise.all(catalog.map(async (table) => {
      const itemResponse = await fetch(`/table?p=${encodeURIComponent(table.path)}`);
      if (!itemResponse.ok) throw new Error(`${table.name} failed (${itemResponse.status})`);
      const item = await itemResponse.json();
      tableCache.set(table.path, item);
      return item;
    }));
    void loaded;
    renderSlots();
    renderLibrary();
    setStatus(`${catalog.length} tables ready. Choose one for each corner.`);
  } catch (error) {
    setStatus(error.message || String(error), true);
    el("table-count").textContent = "error";
  }
}

el("filter").addEventListener("input", renderLibrary);
el("body-name").addEventListener("input", renderRecipe);
el("load-files").addEventListener("click", () => el("file-input").click());
el("file-input").addEventListener("change", () => addFiles(el("file-input").files));
const dropZone = el("drop-zone");
["dragenter", "dragover"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
  event.preventDefault();
  dropZone.classList.add("over");
}));
["dragleave", "drop"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
  event.preventDefault();
  dropZone.classList.remove("over");
}));
dropZone.addEventListener("drop", (event) => addFiles(event.dataTransfer.files));
document.addEventListener("dragover", (event) => event.preventDefault());
document.addEventListener("drop", (event) => event.preventDefault());
el("clear-all").addEventListener("click", () => {
  for (const corner of CORNERS) state[corner] = null;
  renderSlots();
  renderRecipe();
  setStatus("All four corners cleared.");
});
el("copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(JSON.stringify(recipeObject(), null, 2));
    setStatus("Map copied to the clipboard.");
  } catch (error) {
    setStatus("Clipboard was not available; use Save map.", true);
  }
});
el("download").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(recipeObject(), null, 2) + "\n"], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${recipeObject().name}.table-stitch.json`;
  link.click();
  URL.revokeObjectURL(url);
  setStatus("Map saved.");
});
load();
</script>
</body>
</html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = "table-stitch/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        # Keep the console useful when this is launched in a terminal.
        print(f"{self.address_string()} - {format % args}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path in ("/", "/index.html"):
                body = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/tables":
                tables, plot_scale = _catalog()
                _json_response(self, 200, {"tables": tables, "scale": plot_scale})
                return
            if parsed.path == "/table":
                params = parse_qs(parsed.query)
                rel_path = params.get("p", [""])[0]
                if not rel_path:
                    raise ValueError("missing table path")
                path = _inside_root(ROOT / rel_path)
                if path not in _table_paths():
                    raise ValueError("table is not in the catalog")
                payload = _read_tf(path)
                payload.update(_metadata(path, payload))
                _json_response(self, 200, payload)
                return
            _json_response(self, 404, {"error": "not found"})
        except (OSError, ValueError) as exc:
            _json_response(self, 400, {"error": str(exc)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"table stitcher: http://127.0.0.1:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
