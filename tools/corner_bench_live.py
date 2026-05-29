#!/usr/bin/env python3
"""Live Corner Bench — browser controls for poking one packed word at a time.

Launch once, then stay in the browser:

    python tools/corner_bench_live.py bodies/neon_vane.body240

Click a word, click a nudge button, listen. No repeated CLI poke/render/open loop.
The live bench still writes the normal Corner Bench artifacts under
dev/tmp/corner_bench/ so anything good can be kept or loaded elsewhere.
"""
from __future__ import annotations

import argparse
import copy
import html
import json
import mimetypes
import random
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
for _p in (str(ROOT), str(TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import author_body as ab  # noqa: E402
import corner_bench as cb  # noqa: E402
import teleport_stress as ts  # noqa: E402


DELTAS = (-0x0800, -0x0200, -0x0040, -0x0008, 0x0008, 0x0040, 0x0200, 0x0800)


class LiveSession:
    def __init__(self, body: Path, sr: int, quick_seconds: float,
                 teleport_seconds: float, drive: float, seed: int) -> None:
        self.body = body
        self.sr = sr
        self.quick_seconds = quick_seconds
        self.teleport_seconds = teleport_seconds
        self.drive = drive
        self.seed = seed
        self.rng = random.Random(seed)
        self.lock = threading.Lock()
        self.render_id = 0
        self.last_full_render = False

        name, boost, raw = cb.load_body(body)
        self.name = name
        self.boost = boost
        self.origin_raw = raw
        self.words = copy.deepcopy(cb.words_from_bytes(raw))
        self.history: dict[str, Any] = {
            "origin_source": str(body),
            "origin_name": name,
            "origin_bytes_hex": raw.hex(),
            "mutations": [],
        }
        cb.OUT.mkdir(parents=True, exist_ok=True)
        self.render_quick()

    def render_quick(self) -> None:
        """Render only original/current sweep for fast browser feedback."""
        cb.OUT.mkdir(parents=True, exist_ok=True)
        raw = ab.raw_from_words(self.words)
        (cb.OUT / "current.body240").write_bytes(raw)
        payload = ab.compiled_payload(self.name, self.boost, self.words)
        (cb.OUT / "current.cart.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )

        origin_wav = cb.OUT / "sweep_slow_original.wav"
        if self.render_id == 0 or not origin_wav.exists():
            origin_words = cb.words_from_bytes(self.origin_raw)
            cb.render_sweep(origin_words, origin_wav,
                            self.sr, self.quick_seconds, self.drive)
        sweep_dyn, sweep_static = cb.render_sweep(self.words, cb.OUT / "sweep_slow.wav",
                                                 self.sr, self.quick_seconds, self.drive)
        self.stability = cb.aggregate_stability(sweep_static, sweep_dyn, {})
        self.report = {
            "name": self.name,
            "source": str(self.body),
            "sample_rate": self.sr,
            "live": True,
            "full_stress_rendered": self.last_full_render,
            "sweep": {"dynamic": sweep_dyn, "static_probe": sweep_static},
            "modes": {},
            "stability": self.stability,
            "mutations": self.history["mutations"],
            "outputs": {
                "body240": str(cb.OUT / "current.body240"),
                "cart_json": str(cb.OUT / "current.cart.json"),
                "sweep_original": str(cb.OUT / "sweep_slow_original.wav"),
                "sweep": str(cb.OUT / "sweep_slow.wav"),
                "audition": str(cb.OUT / "live.html"),
            },
        }
        (cb.OUT / "report.json").write_text(json.dumps(self.report, indent=2), encoding="utf-8")
        cb.HISTORY.write_text(json.dumps(self.history, indent=2), encoding="utf-8")
        self.render_id += 1

    def render_full_stress(self) -> None:
        source = ts.source_signal(int(round(self.teleport_seconds * self.sr)), self.sr)
        modes = cb.render_teleports(self.words, cb.OUT, self.sr, self.teleport_seconds,
                                    self.seed, self.drive, source)
        sweep = self.report["sweep"]
        self.stability = cb.aggregate_stability(sweep["static_probe"], sweep["dynamic"], modes)
        self.report["modes"] = modes
        self.report["stability"] = self.stability
        self.report["full_stress_rendered"] = True
        self.last_full_render = True
        (cb.OUT / "report.json").write_text(json.dumps(self.report, indent=2), encoding="utf-8")
        cb.write_audition_html(cb.OUT / "audition.html", self.report, self.words,
                               self.history, self.hot_cell())
        self.render_id += 1

    def hot_cell(self) -> tuple[str, int, int] | None:
        muts = self.history.get("mutations", [])
        if not muts:
            return None
        last = muts[-1]
        return (last["corner"], int(last["row"]), int(last["word"]))

    def poke(self, corner: str, row: int, word: int, delta: int) -> dict[str, Any]:
        old, new = cb.apply_mutation(self.words, corner, row, word, delta)
        self.history["mutations"].append({
            "kind": "poke",
            "corner": corner,
            "row": row,
            "word": word,
            "delta": int(delta),
            "old": old,
            "new": new,
            "time": time.time(),
        })
        self.last_full_render = False
        self.render_quick()
        return {"old": old, "new": new}

    def random_poke(self) -> dict[str, Any]:
        corner = self.rng.choices(
            population=("M100_Q100", "M0_Q100", "M100_Q0", "M0_Q0"),
            weights=(46, 28, 20, 6),
            k=1,
        )[0]
        row = self.rng.randrange(cb.STAGES)
        word = self.rng.choices(
            population=(0, 1, 2, 3, 4),
            weights=(18, 12, 26, 28, 16),
            k=1,
        )[0]
        delta = self.rng.choice(DELTAS)
        result = self.poke(corner, row, word, delta)
        self.history["mutations"][-1]["kind"] = "random"
        return {"corner": corner, "row": row, "word": word, "delta": delta, **result}

    def undo(self) -> dict[str, Any]:
        muts = self.history.get("mutations", [])
        if not muts:
            return {"undone": False}
        last = muts.pop()
        rows = [list(r) for r in self.words[last["corner"]]]
        rows[int(last["row"])][int(last["word"])] = int(last["old"]) & 0xFFFF
        self.words[last["corner"]] = [tuple(r) for r in rows]
        self.last_full_render = False
        self.render_quick()
        return {"undone": True, "mutation": last}

    def reset(self) -> None:
        self.words = copy.deepcopy(cb.words_from_bytes(self.origin_raw))
        self.history["mutations"] = []
        self.last_full_render = False
        self.render_quick()

    def save_keeper(self, name: str) -> dict[str, str]:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name.strip())
        if not safe:
            raise ValueError("keeper name is empty")
        cb.KEEPERS.mkdir(parents=True, exist_ok=True)
        raw = ab.raw_from_words(self.words)
        body240 = cb.KEEPERS / f"{safe}.body240"
        cart = cb.KEEPERS / f"{safe}.cart.json"
        body240.write_bytes(raw)
        payload = ab.compiled_payload(safe, self.boost, self.words)
        cart.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return {"body240": str(body240), "cart_json": str(cart)}

    def state(self) -> dict[str, Any]:
        def hex_words() -> dict[str, list[list[str]]]:
            return {
                label: [[f"{int(v) & 0xFFFF:04X}" for v in row] for row in rows]
                for label, rows in self.words.items()
            }

        return {
            "name": self.name,
            "source": str(self.body),
            "render_id": self.render_id,
            "words": hex_words(),
            "mutations": self.history["mutations"],
            "stability": self.stability,
            "full_stress_rendered": self.last_full_render,
            "keeper_suggestion": f"{self.name.lower().replace(' ', '_')}_take_{len(self.history['mutations']):02d}",
            "files": {
                "original": "/files/sweep_slow_original.wav",
                "current": "/files/sweep_slow.wav",
                "noise": "/files/teleport_noise.wav",
                "square": "/files/teleport_square_150hz.wav",
                "derivative": "/files/teleport_derivative.wav",
                "body240": str(cb.OUT / "current.body240"),
                "cart_json": str(cb.OUT / "current.cart.json"),
            },
        }


def page() -> str:
    delta_buttons = "\n".join(
        f'<button class="delta" data-delta="{d}">{d:+#06x}</button>' for d in DELTAS
    )
    labels = json.dumps(cb.CORNER_ORDER)
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Live Corner Bench</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; background:#080a0a; color:#eee9dc; font:14px/1.35 system-ui,Segoe UI,sans-serif; }}
  main {{ max-width:1180px; margin:0 auto; padding:18px 18px 42px; }}
  header {{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin-bottom:14px; }}
  h1 {{ margin:0; font-size:22px; }}
  h2 {{ font-size:12px; letter-spacing:.11em; color:#78d9b1; text-transform:uppercase; margin:18px 0 8px; }}
  .muted {{ color:#8b9088; }}
  .top {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
  .panel {{ background:#0d1110; border:1px solid #1b2b25; border-radius:8px; padding:12px; }}
  .start {{ border-color:#365e50; background:#0e1513; }}
  .lead {{ margin:2px 0 12px; color:#c9d1c9; font-size:15px; }}
  audio {{ width:100%; }}
  .controls {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; }}
  button {{ background:#111b18; color:#e9f8ef; border:1px solid #315548; border-radius:6px; padding:8px 10px; cursor:pointer; font:13px ui-monospace,Consolas,monospace; }}
  button:hover {{ background:#193028; }}
  button.primary {{ background:#163f31; border-color:#66b593; color:#f4fff9; font-size:16px; padding:13px 16px; }}
  button.big {{ font-size:15px; padding:11px 14px; }}
  button.danger {{ border-color:#60302e; color:#ffb2a7; }}
  input {{ background:#080d0b; color:#e9f8ef; border:1px solid #315548; border-radius:6px; padding:8px; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
  details {{ margin-top:14px; }}
  summary {{ cursor:pointer; color:#98ecc7; font-weight:700; }}
  .hidden-help {{ color:#8b9088; margin:8px 0 12px; }}
  table {{ border-collapse:collapse; width:100%; font:12px ui-monospace,Consolas,monospace; }}
  td, th {{ border:1px solid #20322c; padding:5px 7px; text-align:right; }}
  th {{ color:#78a992; font-weight:600; }}
  td.word {{ color:#cfecdf; cursor:pointer; }}
  td.word:hover {{ background:#1a3129; }}
  td.word.sel {{ background:#f1d76a; color:#12100a; font-weight:800; }}
  .corner-title {{ color:#98ecc7; font:13px ui-monospace,Consolas,monospace; margin:0 0 5px; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font:12px ui-monospace,Consolas,monospace; }}
  .ok {{ background:#163b2b; color:#85e7ae; }}
  .bad {{ background:#461717; color:#ff9a9a; }}
  .status {{ min-height:18px; color:#f1d76a; font:12px ui-monospace,Consolas,monospace; }}
  .history {{ max-height:220px; overflow:auto; }}
  @media (max-width: 850px) {{ .top,.grid {{ grid-template-columns:1fr; }} }}
</style>
<main>
  <header>
    <div>
      <h1>Live Corner Bench</h1>
      <div id="sub" class="muted"></div>
    </div>
    <div id="badge" class="badge">loading</div>
  </header>

  <section class="panel start">
    <h2>Start Here</h2>
    <p class="lead">This bench is not for understanding all 240 bytes. It is for one loop: listen, hit <b>Random</b>, keep it if it bites, hit <b>Undo</b> if it got worse.</p>
    <div class="controls">
      <button id="random" class="primary">Random: make it weirder</button>
      <button id="undo" class="big">Undo / reject</button>
      <button id="reset" class="danger big">Reset</button>
      <input id="keeper" placeholder="keeper_name">
      <button id="save" class="big">Save keeper</button>
    </div>
    <div id="status" class="status"></div>
  </section>

  <section class="top">
    <div class="panel">
      <h2>Original Seed</h2>
      <audio id="original" controls preload="none" loop></audio>
    </div>
    <div class="panel">
      <h2>Current</h2>
      <audio id="current" controls preload="none" loop></audio>
    </div>
  </section>

  <section class="panel">
    <h2>Teleport Stress</h2>
    <p class="muted">Only render this after the slow sweep sounds interesting. It makes the destruction WAVs.</p>
    <div class="controls">
      <button id="full">Render teleport stress</button>
    </div>
    <div class="top" style="margin-top:10px">
      <div><h2>Noise</h2><audio id="noise" controls preload="none"></audio></div>
      <div><h2>150 Hz Strobe</h2><audio id="square" controls preload="none"></audio></div>
      <div><h2>Derivative</h2><audio id="derivative" controls preload="none"></audio></div>
    </div>
  </section>

  <details class="panel">
    <summary>Advanced word surgery</summary>
    <p class="hidden-help">Ignore this until random finds something close. Then click one word and nudge it. Keys: <b>1</b>/<b>2</b>/<b>3</b>/<b>4</b> = +tiny/fine/medium/coarse, Shift = negative, <b>R</b> = random, <b>U</b> = undo.</p>
    <div class="controls">{delta_buttons}</div>
    <div id="selected" class="status"></div>
    <h2>Words</h2>
    <div id="words" class="grid"></div>
  </details>

  <section class="panel history">
    <h2>History</h2>
    <table id="history"></table>
  </section>
</main>
<script>
const corners = {labels};
let state = null;
let selected = {{ corner: "M100_Q100", row: 0, word: 0 }};
let pendingAudioSnapshot = null;
let lastKeeperSuggestion = "";

function qs(id) {{ return document.getElementById(id); }}
function audioUrl(path) {{ return path + "?v=" + (state ? state.render_id : Date.now()); }}
function setStatus(msg) {{ qs("status").textContent = msg || ""; }}
function selectedText() {{ return `${{selected.corner}} r${{selected.row}} w${{selected.word}}`; }}

async function api(path, body=null) {{
  const opt = body ? {{ method:"POST", headers:{{"Content-Type":"application/json"}}, body:JSON.stringify(body) }} : {{}};
  const res = await fetch(path, opt);
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}}

function snapshotAudio() {{
  const out = {{}};
  ["original", "current", "noise", "square", "derivative"].forEach(id => {{
    const el = qs(id);
    if (el) out[id] = {{ time: el.currentTime || 0, paused: el.paused, rate: el.playbackRate || 1 }};
  }});
  return out;
}}

function restoreAudio(snapshot) {{
  if (!snapshot) return;
  Object.entries(snapshot).forEach(([id, info]) => {{
    const el = qs(id);
    if (!el || !el.src) return;
    el.playbackRate = info.rate || 1;
    const apply = () => {{
      try {{
        const dur = Number.isFinite(el.duration) ? el.duration : info.time;
        el.currentTime = Math.max(0, Math.min(info.time || 0, Math.max(0, dur - 0.03)));
      }} catch (_) {{}}
      if (!info.paused) el.play().catch(() => {{}});
    }};
    if (el.readyState >= 1) apply();
    else el.addEventListener("loadedmetadata", apply, {{ once:true }});
  }});
}}

function renderWords() {{
  const wrap = qs("words");
  wrap.innerHTML = "";
  for (const corner of corners) {{
    const div = document.createElement("div");
    div.innerHTML = `<p class="corner-title">${{corner}}</p>`;
    const table = document.createElement("table");
    let html = "<tr><th></th><th>w0</th><th>w1</th><th>w2</th><th>w3</th><th>w4</th></tr>";
    state.words[corner].forEach((row, ri) => {{
      html += `<tr><th>r${{ri}}</th>`;
      row.forEach((word, wi) => {{
        const sel = selected.corner === corner && selected.row === ri && selected.word === wi ? " sel" : "";
        html += `<td class="word${{sel}}" data-corner="${{corner}}" data-row="${{ri}}" data-word="${{wi}}">${{word}}</td>`;
      }});
      html += "</tr>";
    }});
    table.innerHTML = html;
    div.appendChild(table);
    wrap.appendChild(div);
  }}
  document.querySelectorAll("td.word").forEach(td => td.onclick = () => {{
    selected = {{ corner: td.dataset.corner, row: Number(td.dataset.row), word: Number(td.dataset.word) }};
    renderWords();
    qs("selected").textContent = "selected " + selectedText();
  }});
  qs("selected").textContent = "selected " + selectedText();
}}

function renderHistory() {{
  const h = qs("history");
  h.innerHTML = "<tr><th>#</th><th>kind</th><th>corner</th><th>cell</th><th>delta</th><th>word</th></tr>";
  state.mutations.forEach((m, i) => {{
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${{i+1}}</td><td>${{m.kind || "poke"}}</td><td>${{m.corner}}</td><td>r${{m.row}} w${{m.word}}</td><td>${{m.delta}}</td><td>${{m.old.toString(16).toUpperCase().padStart(4,"0")}} -> ${{m.new.toString(16).toUpperCase().padStart(4,"0")}}</td>`;
    h.appendChild(tr);
  }});
}}

function renderState() {{
  qs("sub").textContent = `${{state.name}} · ${{state.source}}`;
  const st = state.stability;
  qs("badge").className = "badge " + (st.clean ? "ok" : "bad");
  qs("badge").textContent = `${{st.clean ? "clean" : "unstable"}} · max r ${{st.max_pole_radius.toFixed(5)}}`;
  qs("original").src = audioUrl(state.files.original);
  qs("current").src = audioUrl(state.files.current);
  if (state.full_stress_rendered) {{
    qs("noise").src = audioUrl(state.files.noise);
    qs("square").src = audioUrl(state.files.square);
    qs("derivative").src = audioUrl(state.files.derivative);
  }}
  const keeper = qs("keeper");
  if (keeper && (!keeper.value.trim() || keeper.value === lastKeeperSuggestion)) {{
    keeper.value = state.keeper_suggestion || "";
    lastKeeperSuggestion = keeper.value;
  }}
  renderWords();
  renderHistory();
  restoreAudio(pendingAudioSnapshot);
  pendingAudioSnapshot = null;
}}

async function refresh() {{
  state = await api("/api/state");
  renderState();
}}

async function poke(delta) {{
  setStatus("rendering " + selectedText() + " " + delta + " ...");
  pendingAudioSnapshot = snapshotAudio();
  try {{
    state = await api("/api/poke", {{ ...selected, delta }});
    renderState();
    setStatus("done");
  }} catch (e) {{
    setStatus("error: " + e.message);
  }}
}}

async function randomPoke() {{
  setStatus("rendering random nudge ...");
  pendingAudioSnapshot = snapshotAudio();
  try {{
    state = await api("/api/random", {{}});
    const m = state.mutations[state.mutations.length - 1];
    selected = {{ corner: m.corner, row: Number(m.row), word: Number(m.word) }};
    renderState();
    setStatus("random " + selectedText() + " " + m.delta);
  }} catch (e) {{
    setStatus("error: " + e.message);
  }}
}}

async function undo() {{
  setStatus("undo ...");
  pendingAudioSnapshot = snapshotAudio();
  try {{
    state = await api("/api/undo", {{}});
    renderState();
    setStatus("undone");
  }} catch (e) {{
    setStatus("error: " + e.message);
  }}
}}

document.querySelectorAll("button.delta").forEach(btn => btn.onclick = () => poke(Number(btn.dataset.delta)));
document.addEventListener("keydown", ev => {{
  if (["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
  const map = {{ "1": 0x0008, "2": 0x0040, "3": 0x0200, "4": 0x0800 }};
  if (ev.key in map) {{
    ev.preventDefault();
    poke(ev.shiftKey ? -map[ev.key] : map[ev.key]);
  }}
  if (ev.key.toLowerCase() === "r") {{ ev.preventDefault(); randomPoke(); }}
  if (ev.key.toLowerCase() === "u") {{ ev.preventDefault(); undo(); }}
}});
qs("random").onclick = randomPoke;
qs("undo").onclick = undo;
qs("full").onclick = async () => {{
  setStatus("rendering full teleport stress ...");
  pendingAudioSnapshot = snapshotAudio();
  try {{ state = await api("/api/full", {{}}); renderState(); setStatus("full stress done"); }}
  catch(e) {{ setStatus("error: " + e.message); }}
}};
qs("reset").onclick = async () => {{
  setStatus("resetting ...");
  pendingAudioSnapshot = snapshotAudio();
  state = await api("/api/reset", {{}});
  renderState();
  setStatus("reset");
}};
qs("save").onclick = async () => {{
  const name = qs("keeper").value.trim() || state.keeper_suggestion;
  if (!name) {{ setStatus("name the keeper first"); return; }}
  try {{ const r = await api("/api/save", {{ name }}); setStatus("saved " + r.body240); }}
  catch(e) {{ setStatus("error: " + e.message); }}
}};
refresh().catch(e => setStatus("error: " + e.message));
</script>
"""


class Handler(BaseHTTPRequestHandler):
    session: LiveSession

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("live-bench: " + fmt % args + "\n")

    def send_json(self, payload: Any, code: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def send_text(self, text: str, code: int = 200, content_type: str = "text/html") -> None:
        data = text.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def read_json(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length", "0"))
        if n <= 0:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self.send_text(page())
            return
        if path == "/api/state":
            with self.session.lock:
                self.send_json(self.session.state())
            return
        if path.startswith("/files/"):
            name = Path(unquote(path.removeprefix("/files/"))).name
            target = cb.OUT / name
            if not target.exists() or not target.is_file():
                self.send_text("not found", 404, "text/plain")
                return
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_text("not found", 404, "text/plain")

    def do_POST(self) -> None:
        try:
            payload = self.read_json()
            with self.session.lock:
                if self.path == "/api/poke":
                    self.session.poke(
                        str(payload["corner"]),
                        int(payload["row"]),
                        int(payload["word"]),
                        int(payload["delta"]),
                    )
                    self.send_json(self.session.state())
                    return
                if self.path == "/api/random":
                    self.session.random_poke()
                    self.send_json(self.session.state())
                    return
                if self.path == "/api/undo":
                    self.session.undo()
                    self.send_json(self.session.state())
                    return
                if self.path == "/api/full":
                    self.session.render_full_stress()
                    self.send_json(self.session.state())
                    return
                if self.path == "/api/reset":
                    self.session.reset()
                    self.send_json(self.session.state())
                    return
                if self.path == "/api/save":
                    self.send_json(self.session.save_keeper(str(payload.get("name", ""))))
                    return
            self.send_text("not found", 404, "text/plain")
        except Exception as exc:  # noqa: BLE001 - report to browser, keep server alive.
            self.send_text(html.escape(str(exc)), 500, "text/plain")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("body", type=Path)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--sr", type=int, default=44_100)
    ap.add_argument("--quick-seconds", type=float, default=0.85)
    ap.add_argument("--teleport-seconds", type=float, default=0.8)
    ap.add_argument("--containment-drive", type=float, default=4.0)
    ap.add_argument("--seed", type=int, default=0x513DF2)
    ap.add_argument("--open", action="store_true", help="open the browser after starting")
    args = ap.parse_args(argv)

    Handler.session = LiveSession(args.body, args.sr, args.quick_seconds,
                                  args.teleport_seconds, args.containment_drive,
                                  args.seed)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    (cb.OUT / "live.url.txt").write_text(url + "\n", encoding="utf-8")
    print(f"live corner bench -> {url}")
    print(f"artifacts -> {cb.OUT}")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
