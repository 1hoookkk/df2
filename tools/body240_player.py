#!/usr/bin/env python3
"""One browser player for generated 240-byte bodies.

This is deliberately not an index of old WAVs. It scans raw 240-byte bodies
(`.body240` and 240-byte `.bin`) plus compiled-v1 JSON `packedWords`, then each
play request renders the selected body through the shipped trench-core engine.

Run:
    python -m tools.body240_player

Then open the printed localhost URL.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import random
import re
import struct
import sys
import time
import wave
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402

TMP = ROOT / "dev" / "tmp"
OUT = TMP / "body240_player"
STATE_PATH = OUT / "listen_state.json"
BODY_BYTES = 240
SR = 44100
BLOCK = 512

CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
LABEL_POS = {
    "home": ("HOME", 0.0, 0.0),
    "morph": ("MORPH", 1.0, 0.0),
    "tension": ("TENSION", 0.0, 1.0),
    "morph_tension": ("MORPH+TENSION", 1.0, 1.0),
    "middle": ("MIDDLE", 0.5, 0.5),
}


@dataclass
class BodyRecord:
    id: str
    name: str
    source: str
    category: str
    primary_path: str
    bytes_path: str | None
    json_path: str | None
    sha256: str
    duplicate_count: int
    duplicate_paths: list[str]
    modified: float
    size: int
    notes_hint: str


def _rel(path: Path) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", text.strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "body"


def _category(path: Path) -> str:
    rel = _rel(path)
    parts = rel.split("/")
    if rel.startswith("dev/tmp/keepers/"):
        return "keeper"
    if rel.startswith("dev/tmp/target_browser/"):
        return "target_browser"
    if rel.startswith("dev/tmp/reference_brief/"):
        return "reference_brief"
    if rel.startswith("dev/tmp/corner_bench/"):
        return "corner_bench"
    if rel.startswith("dev/tmp/"):
        top = parts[2] if len(parts) > 2 else "dev_tmp"
        if top in {
            "body_rack",
            "keeper_hunt",
            "vocal_rack",
            "vocal_rack2",
            "vocal_rack3",
            "vocal_rack2_low_to_high",
            "vocal_rack_tube",
            "metal_rack",
            "floor_transfer",
            "audition",
        }:
            return "legacy_rack"
        if top in {"factorizer_bench", "factorizer_proof", "forge_voice_regression", "teleport_stress"}:
            return "proof_or_bench"
        return top
    if rel.startswith("bodies/generated/"):
        return "generated_bin"
    if rel.startswith("bodies/crazy/"):
        return "crazy"
    if rel.startswith("bodies/proofs/"):
        return "proof"
    if rel.startswith("bodies/"):
        return "canonical_body"
    return "other"


def _read_cart_bytes(path: Path) -> tuple[str, bytes] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None
    if doc.get("format") != "compiled-v1":
        return None
    keyframes = doc.get("keyframes")
    if not isinstance(keyframes, list) or len(keyframes) < 4:
        return None

    by_label = {str(kf.get("label", "")): kf for kf in keyframes if isinstance(kf, dict)}
    ordered = []
    if all(label in by_label for label in CORNER_ORDER):
        ordered = [by_label[label] for label in CORNER_ORDER]
    else:
        ordered = keyframes[:4]

    words: list[int] = []
    for kf in ordered:
        rows = kf.get("packedWords") if isinstance(kf, dict) else None
        if not isinstance(rows, list) or len(rows) != 6:
            return None
        for row in rows:
            if not isinstance(row, list) or len(row) != 5:
                return None
            words.extend(int(v) & 0xFFFF for v in row)
    if len(words) != 120:
        return None
    name = str(doc.get("name") or path.stem.replace(".cart", ""))
    return name, struct.pack("<" + "H" * len(words), *words)


def _sidecar_json_for(raw_path: Path) -> Path | None:
    stems = [
        raw_path.with_suffix(".cart.json"),
        raw_path.with_name(raw_path.stem + ".cart.json"),
        raw_path.with_name(raw_path.stem.replace(".body240", "") + ".cart.json"),
    ]
    for p in stems:
        if p.exists():
            return p
    return None


def _name_for_raw(path: Path, sidecar: Path | None) -> str:
    if sidecar:
        loaded = _read_cart_bytes(sidecar)
        if loaded:
            return loaded[0]
    stem = path.stem
    if stem.endswith(".body240"):
        stem = stem[:-8]
    return stem


def _notes_hint(path: Path) -> str:
    report = path.parent / "report.json"
    if report.exists():
        try:
            doc = json.loads(report.read_text(encoding="utf-8"))
            bits = []
            for key in ("template", "seed", "index", "provenance", "family"):
                if key in doc:
                    bits.append(f"{key}={doc[key]}")
            gate = doc.get("gate")
            if isinstance(gate, dict):
                if gate.get("pass") is not None:
                    bits.append(f"gate={'PASS' if gate.get('pass') else 'FAIL'}")
                adv = gate.get("advisory_failed")
                if adv:
                    bits.append("warn=" + ",".join(str(x) for x in adv))
            return " · ".join(bits)
        except Exception:
            pass
    keep = path.with_suffix(".keep.json")
    if keep.exists():
        try:
            doc = json.loads(keep.read_text(encoding="utf-8"))
            return str(doc.get("notes") or doc.get("provenance") or "")
        except Exception:
            pass
    return ""


def _scan_roots(include_canonical: bool) -> list[Path]:
    roots = [TMP, ROOT / "bodies" / "generated", ROOT / "bodies" / "crazy", ROOT / "bodies" / "proofs"]
    if include_canonical:
        roots.extend(
            p for p in (ROOT / "bodies").iterdir()
            if p.exists() and p.name not in {"rom"} and p not in roots
        )
        roots.append(ROOT / "bodies")
    return [r for r in roots if r.exists()]


def scan_bodies(include_canonical: bool = True) -> list[BodyRecord]:
    by_hash: dict[str, dict[str, Any]] = {}
    seen_paths: set[Path] = set()

    def add(raw: bytes, path: Path, name: str, json_path: Path | None = None) -> None:
        if len(raw) != BODY_BYTES:
            return
        path = path.resolve()
        if path in seen_paths:
            return
        seen_paths.add(path)
        sha = hashlib.sha256(raw).hexdigest()
        st = path.stat()
        entry = by_hash.setdefault(
            sha,
            {
                "raw": raw,
                "paths": [],
                "json_paths": [],
                "name": name,
                "modified": st.st_mtime,
                "size": st.st_size,
                "primary": path,
            },
        )
        entry["paths"].append(path)
        if json_path:
            entry["json_paths"].append(json_path.resolve())
        if _category(path) == "keeper":
            entry["name"] = name
            entry["primary"] = path
        elif entry["primary"].suffix.lower() not in {".body240", ".bin"} and path.suffix.lower() in {".body240", ".bin"}:
            entry["name"] = name
            entry["primary"] = path
        entry["modified"] = max(float(entry["modified"]), st.st_mtime)

    for root in _scan_roots(include_canonical):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            lower = path.name.lower()
            if lower.endswith(".body240") or path.suffix.lower() == ".bin":
                try:
                    raw = path.read_bytes()
                except OSError:
                    continue
                if len(raw) != BODY_BYTES:
                    continue
                sidecar = _sidecar_json_for(path)
                add(raw, path, _name_for_raw(path, sidecar), sidecar)

    # Add compiled-v1 JSON bodies that do not already have a raw sibling.
    for root in _scan_roots(include_canonical):
        for path in root.rglob("*.json"):
            if not path.is_file():
                continue
            loaded = _read_cart_bytes(path)
            if not loaded:
                continue
            name, raw = loaded
            raw_sibling = path.with_suffix("")
            likely_raws = [
                path.with_suffix(".body240"),
                path.with_name(path.name.replace(".cart.json", ".body240")),
                raw_sibling.with_suffix(".body240"),
            ]
            raw_path = next((p for p in likely_raws if p.exists() and p.stat().st_size == BODY_BYTES), None)
            add(raw, raw_path or path, name, path)

    records: list[BodyRecord] = []
    priority = {
        "keeper": 0,
        "target_browser": 1,
        "reference_brief": 2,
        "generated_bin": 3,
        "crazy": 4,
        "proof": 5,
        "corner_bench": 6,
        "legacy_rack": 7,
        "proof_or_bench": 8,
        "canonical_body": 9,
    }

    def sort_key(kv):
        primary = kv[1]["primary"]
        return (priority.get(_category(primary), 50), _rel(primary).lower())

    for index, (sha, item) in enumerate(sorted(by_hash.items(), key=sort_key), 1):
        primary: Path = item["primary"]
        json_paths: list[Path] = item["json_paths"]
        bytes_path = primary if primary.suffix.lower() in {".body240", ".bin"} else None
        rec_id = f"b{index:04d}_{sha[:10]}"
        records.append(
            BodyRecord(
                id=rec_id,
                name=item["name"],
                source=primary.parent.name,
                category=_category(primary),
                primary_path=_rel(primary),
                bytes_path=_rel(bytes_path) if bytes_path else None,
                json_path=_rel(json_paths[0]) if json_paths else (_rel(primary) if primary.suffix.lower() == ".json" else None),
                sha256=sha,
                duplicate_count=len(item["paths"]),
                duplicate_paths=[_rel(p) for p in sorted(item["paths"], key=lambda x: _rel(x).lower())],
                modified=float(item["modified"]),
                size=int(item["size"]),
                notes_hint=_notes_hint(primary),
            )
        )
    return records


def _body_bytes(record: BodyRecord) -> bytes:
    if record.bytes_path:
        raw = (ROOT / record.bytes_path).read_bytes()
        if len(raw) != BODY_BYTES:
            raise ValueError(f"{record.bytes_path} is {len(raw)} bytes, expected 240")
        return raw
    if record.json_path:
        loaded = _read_cart_bytes(ROOT / record.json_path)
        if loaded:
            return loaded[1]
    raw = (ROOT / record.primary_path).read_bytes()
    if len(raw) != BODY_BYTES:
        raise ValueError(f"{record.primary_path} is {len(raw)} bytes, expected 240")
    return raw


def _source(kind: str, seconds: float, sr: int, seed: int = 1234) -> np.ndarray:
    n = max(64, int(sr * seconds))
    t = np.arange(n, dtype=np.float64) / float(sr)
    env = np.minimum(1.0, 25.0 * t) * np.exp(-t / max(0.08, seconds * 0.72))
    if kind == "tone":
        x = np.sin(2.0 * np.pi * 110.0 * t) * env
    elif kind == "saw":
        f = 55.0
        x = 2.0 * ((f * t) % 1.0) - 1.0
        x *= env
    elif kind == "pink":
        rng = np.random.default_rng(seed)
        white = rng.standard_normal(n + 16)
        rows = np.zeros((16, n + 16))
        running = np.zeros(16)
        for i in range(n + 16):
            k = 0
            r = i + 1
            while (r & 1) == 0 and k < 16:
                running[k] = white[i] * (0.5 ** (k * 0.35))
                k += 1
                r >>= 1
            rows[:, i] = running
        x = rows.sum(axis=0)[16:]
        x = x / max(1e-9, float(np.max(np.abs(x)))) * env
    else:
        f = 45.0 + 72.0 * np.exp(-t / 0.035)
        phase = 2.0 * np.pi * np.cumsum(f) / sr
        body = np.sin(phase) * np.exp(-t / 0.34)
        click = np.zeros(n)
        c = min(n, int(sr * 0.004))
        if c:
            click[:c] = np.linspace(1.0, 0.0, c)
        x = body + 0.22 * click
    peak = float(np.max(np.abs(x)))
    if peak > 1e-9:
        x = x / peak * 0.75
    return x.astype(np.float32)


def _automation(mode: str, n: int, sr: int) -> tuple[np.ndarray, np.ndarray]:
    blocks = max(1, math.ceil(n / BLOCK))
    u = np.linspace(0.0, 1.0, blocks, endpoint=True, dtype=np.float64)
    if mode == "morph_sweep":
        return u, np.zeros_like(u)
    if mode == "q_sweep":
        return np.zeros_like(u), u
    if mode == "diagonal_sweep":
        return u, u
    if mode == "field_sweep":
        return (
            0.5 - 0.5 * np.cos(2.0 * np.pi * 2.0 * u),
            0.5 - 0.5 * np.cos(2.0 * np.pi * 0.5 * u),
        )
    raise ValueError(f"unknown automation mode: {mode}")


def _render(body: bytes, mode: str, source_kind: str, seconds: float, normalize: bool) -> bytes:
    if not trench_ffi.engine_available():
        raise RuntimeError(
            "trench-core engine FFI is unavailable; build it with `cargo build --release -p trench-core`"
        )
    x = _source(source_kind, seconds, SR)
    if mode == "sequence":
        gap = np.zeros(int(SR * 0.11), dtype=np.float32)
        chunks = []
        for _key, (_label, m, q) in LABEL_POS.items():
            raw = trench_ffi.engine_render(body, m, q, x.tobytes(), SR)
            y = np.frombuffer(raw, dtype=np.float32).copy()
            if normalize:
                y = _normalize(y)
            chunks.extend([y, gap])
        out = np.concatenate(chunks)
    elif mode in LABEL_POS:
        _label, m, q = LABEL_POS[mode]
        raw = trench_ffi.engine_render(body, m, q, x.tobytes(), SR)
        out = np.frombuffer(raw, dtype=np.float32).copy()
        if normalize:
            out = _normalize(out)
    else:
        morph, q = _automation(mode, len(x), SR)
        raw = trench_ffi.engine_render_automated(body, morph, q, x.tobytes(), SR, block=BLOCK)
        out = np.frombuffer(raw, dtype=np.float32).copy()
        if normalize:
            out = _normalize(out)
    return _wav_bytes(out, SR)


def _normalize(y: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > 1e-7:
        y = y / peak * 0.92
    return y


def _wav_bytes(samples: np.ndarray, sr: int) -> bytes:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype("<i2")
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm16.tobytes())
    return buf.getvalue()


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"items": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"items": {}}


def _save_state(state: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


class BodyServer(ThreadingHTTPServer):
    def __init__(self, addr, handler, records: list[BodyRecord]):
        super().__init__(addr, handler)
        self.records = records
        self.by_id = {r.id: r for r in records}
        self.started_at = time.time()


class Handler(BaseHTTPRequestHandler):
    server: BodyServer

    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: Any, status: int = 200) -> None:
        self._send(status, json.dumps(payload, indent=2).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path == "/" or path == "/player":
                self._send(200, PLAYER_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/bodies":
                self._json(
                    {
                        "engine_available": trench_ffi.engine_available(),
                        "engine_path": str(trench_ffi.lib_path()) if trench_ffi.lib_path() else None,
                        "count": len(self.server.records),
                        "records": [asdict(r) for r in self.server.records],
                        "state": _load_state(),
                    }
                )
            elif path == "/api/render":
                body_id = qs.get("id", [""])[0]
                rec = self.server.by_id.get(body_id)
                if not rec:
                    self._json({"error": f"unknown body id: {body_id}"}, HTTPStatus.NOT_FOUND)
                    return
                mode = qs.get("mode", ["sequence"])[0]
                source = qs.get("source", ["808"])[0]
                seconds = float(qs.get("seconds", ["1.0"])[0])
                normalize = qs.get("normalize", ["1"])[0] != "0"
                wav = _render(_body_bytes(rec), mode, source, max(0.15, min(8.0, seconds)), normalize)
                safe = quote(f"{rec.name}_{mode}.wav")
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Disposition", f'inline; filename="{safe}"')
                self.end_headers()
                self.wfile.write(wav)
            elif path == "/api/body":
                body_id = qs.get("id", [""])[0]
                rec = self.server.by_id.get(body_id)
                if not rec:
                    self._json({"error": f"unknown body id: {body_id}"}, HTTPStatus.NOT_FOUND)
                    return
                body = _body_bytes(rec)
                probes = {}
                for key, (_label, m, q) in LABEL_POS.items():
                    try:
                        probes[key] = trench_ffi.packed_probe(body, m, q)
                    except Exception as exc:
                        probes[key] = {"error": str(exc)}
                self._json({"record": asdict(rec), "probes": probes})
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            if parsed.path == "/api/mark":
                body_id = str(payload.get("id", ""))
                if body_id not in self.server.by_id:
                    self._json({"error": f"unknown body id: {body_id}"}, HTTPStatus.NOT_FOUND)
                    return
                state = _load_state()
                items = state.setdefault("items", {})
                item = items.setdefault(body_id, {})
                for key in ("vote", "notes", "last_mode", "last_source"):
                    if key in payload:
                        item[key] = payload[key]
                item["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                _save_state(state)
                self._json({"ok": True, "state": state})
            elif parsed.path == "/api/rescan":
                self.server.records = scan_bodies()
                self.server.by_id = {r.id: r for r in self.server.records}
                self._json({"ok": True, "count": len(self.server.records)})
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


PLAYER_HTML = r"""<!doctype html>
<meta charset="utf-8">
<title>body240 player</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#080a0b;color:#e9e5d8;font:13px/1.35 system-ui,Segoe UI,sans-serif}
button,input,select,textarea{font:inherit}
.app{display:grid;grid-template-columns:minmax(320px,430px) 1fr;height:100vh;min-height:720px}
aside{border-right:1px solid #27313a;background:#0f1316;display:flex;flex-direction:column;min-width:0}
main{display:grid;grid-template-rows:auto 1fr;min-width:0}
.top{padding:14px 16px;border-bottom:1px solid #26313a;background:#12171b}
h1{font-size:18px;margin:0 0 8px;color:#fff1cc}
.sub{color:#9aa6a3;font-size:12px}
.filters{display:grid;grid-template-columns:1fr 128px;gap:8px;padding:12px;border-bottom:1px solid #26313a}
input,select,textarea{width:100%;background:#080b0d;color:#ede9dd;border:1px solid #34424c;border-radius:5px;padding:8px}
.list{overflow:auto;padding:8px}
.item{width:100%;text-align:left;background:#11171b;color:#e9e5d8;border:1px solid #26313a;border-radius:6px;padding:8px;margin-bottom:6px;cursor:pointer}
.item.active{border-color:#f0cc6a;background:#1b1a12}
.item.keep{border-color:#61d394}
.item.maybe{border-color:#d1b753}
.item.reject{opacity:.45}
.item b{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item .meta{color:#8e9b98;font-size:11px;margin-top:3px}
.panel{padding:16px;min-width:0;overflow:auto}
.transport{display:grid;grid-template-columns:auto auto 1fr auto auto;gap:8px;align-items:center;margin-top:12px}
button{background:#172027;color:#eee4cf;border:1px solid #384856;border-radius:5px;padding:8px 10px;cursor:pointer}
button:hover{background:#202b34}
button.primary{background:#f0cc6a;color:#17140a;border-color:#f7da86;font-weight:700}
button.keep.active{background:#183c28;border-color:#61d394}
button.maybe.active{background:#3d3418;border-color:#d1b753}
button.reject.active{background:#3d1b1b;border-color:#e26c6c}
.controls{display:grid;grid-template-columns:repeat(5,minmax(110px,1fr));gap:10px;margin:14px 0}
.controls label{color:#99a5a2;font-size:12px}
audio{width:100%;margin:12px 0}
.path{font:12px ui-monospace,Consolas,monospace;color:#92cfff;word-break:break-all;background:#0d1114;border:1px solid #26313a;border-radius:5px;padding:8px}
.bad{color:#ff9a8a}
.ok{color:#83e6a0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.stat{border:1px solid #26313a;background:#101519;border-radius:6px;padding:10px}
textarea{height:96px;resize:vertical}
.votes{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
.small{font-size:12px;padding:6px 8px}
@media(max-width:900px){.app{grid-template-columns:1fr;height:auto}.controls{grid-template-columns:1fr 1fr}.transport{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}aside{height:45vh;border-right:0;border-bottom:1px solid #26313a}}
</style>
<div class="app">
  <aside>
    <div class="top">
      <h1>body240 player</h1>
      <div id="engine" class="sub">loading...</div>
    </div>
    <div class="filters">
      <input id="search" placeholder="search name/path/notes">
      <select id="cat"></select>
    </div>
    <div id="list" class="list"></div>
  </aside>
  <main>
    <div class="top">
      <div id="now" class="sub">No body selected.</div>
      <div class="transport">
        <button id="prev">Prev</button>
        <button id="play" class="primary">Play</button>
        <audio id="audio" controls preload="none"></audio>
        <button id="next">Next</button>
        <button id="shuffle">Shuffle</button>
      </div>
    </div>
    <div class="panel">
      <div class="controls">
        <label>Mode<select id="mode">
          <option value="sequence">5-position sequence</option>
          <option value="home">HOME M0/Q0</option>
          <option value="morph">MORPH M100/Q0</option>
          <option value="tension">TENSION M0/Q100</option>
          <option value="morph_tension">MORPH+TENSION</option>
          <option value="middle">MIDDLE</option>
          <option value="morph_sweep">Morph sweep</option>
          <option value="q_sweep">Q sweep</option>
          <option value="diagonal_sweep">Diagonal sweep</option>
          <option value="field_sweep">Field sweep</option>
        </select></label>
        <label>Source<select id="source">
          <option value="808">808 hit</option>
          <option value="saw">Saw</option>
          <option value="pink">Pink noise</option>
          <option value="tone">Tone</option>
        </select></label>
        <label>Seconds<input id="seconds" type="number" min="0.15" max="8" step="0.05" value="1.0"></label>
        <label>Level<select id="normalize"><option value="1">normalized</option><option value="0">raw engine level</option></select></label>
        <label>Autoplay<select id="autoplay"><option value="0">off</option><option value="1">next body</option></select></label>
      </div>
      <div class="votes">
        <button class="keep" data-vote="KEEP">KEEP</button>
        <button class="maybe" data-vote="MAYBE">MAYBE</button>
        <button class="reject" data-vote="REJECT">REJECT</button>
        <button id="clearVote" class="small">clear vote</button>
        <button id="copyPath" class="small">copy path</button>
        <button id="rescan" class="small">rescan</button>
      </div>
      <textarea id="notes" placeholder="listening notes"></textarea>
      <h2 id="title">Select a body</h2>
      <div id="path" class="path"></div>
      <div id="hint" class="sub"></div>
      <div class="grid" style="margin-top:12px">
        <div class="stat"><b>Runtime path</b><div class="sub">selected file -> 240 bytes -> trench_engine_load_body_bytes -> process_block -> transient WAV response</div></div>
        <div class="stat"><b>Keyboard</b><div class="sub">Space play/pause · J/K prev/next · 1/2/3 vote KEEP/MAYBE/REJECT</div></div>
      </div>
      <pre id="detail" class="path" style="margin-top:12px;white-space:pre-wrap"></pre>
    </div>
  </main>
</div>
<script>
let records = [];
let state = {items:{}};
let filtered = [];
let index = 0;
const el = id => document.getElementById(id);
const audio = el("audio");

async function load() {
  const data = await (await fetch("/api/bodies")).json();
  records = data.records;
  state = data.state || {items:{}};
  el("engine").innerHTML = data.engine_available
    ? `<span class=ok>${records.length} unique 240-byte bodies · engine ${data.engine_path || ""}</span>`
    : `<span class=bad>engine unavailable; build trench-core release</span>`;
  const cats = ["all", ...Array.from(new Set(records.map(r => r.category))).sort()];
  el("cat").innerHTML = cats.map(c => `<option value="${c}">${c}</option>`).join("");
  applyFilter();
}

function voteOf(id) { return (state.items[id] || {}).vote || ""; }
function notesOf(id) { return (state.items[id] || {}).notes || ""; }

function applyFilter() {
  const q = el("search").value.toLowerCase();
  const cat = el("cat").value || "all";
  filtered = records.filter(r => {
    if (cat !== "all" && r.category !== cat) return false;
    const text = `${r.name} ${r.primary_path} ${r.category} ${r.notes_hint}`.toLowerCase();
    return text.includes(q);
  });
  if (index >= filtered.length) index = Math.max(0, filtered.length - 1);
  renderList();
  renderCurrent(false);
}

function renderList() {
  el("list").innerHTML = filtered.map((r, i) => {
    const v = voteOf(r.id).toLowerCase();
    const active = i === index ? "active" : "";
    const dup = r.duplicate_count > 1 ? ` · ${r.duplicate_count} copies` : "";
    return `<button class="item ${active} ${v}" data-i="${i}">
      <b>${escapeHtml(r.name)}</b>
      <div class="meta">${escapeHtml(r.category)} · ${escapeHtml(r.primary_path)}${dup}</div>
    </button>`;
  }).join("") || `<div class=sub style="padding:8px">No bodies match.</div>`;
  document.querySelectorAll(".item").forEach(btn => btn.onclick = () => {
    index = Number(btn.dataset.i);
    renderList();
    renderCurrent(false);
  });
}

function renderCurrent(fetchDetail=true) {
  const r = filtered[index];
  if (!r) return;
  const item = state.items[r.id] || {};
  el("now").textContent = `${index + 1}/${filtered.length} · ${r.name}`;
  el("title").textContent = r.name;
  el("path").textContent = r.primary_path + (r.duplicate_count > 1 ? `\n${r.duplicate_count} duplicate paths share the same bytes.` : "");
  el("hint").textContent = r.notes_hint || "";
  el("notes").value = item.notes || "";
  document.querySelectorAll("[data-vote]").forEach(b => b.classList.toggle("active", b.dataset.vote === item.vote));
  if (fetchDetail) {
    fetch(`/api/body?id=${encodeURIComponent(r.id)}`).then(x => x.json()).then(d => {
      el("detail").textContent = JSON.stringify(d.probes || d, null, 2);
    }).catch(e => { el("detail").textContent = e.message; });
  }
}

async function play() {
  const r = filtered[index];
  if (!r) return;
  await saveMark({last_mode: el("mode").value, last_source: el("source").value}, false);
  const url = `/api/render?id=${encodeURIComponent(r.id)}&mode=${encodeURIComponent(el("mode").value)}&source=${encodeURIComponent(el("source").value)}&seconds=${encodeURIComponent(el("seconds").value)}&normalize=${encodeURIComponent(el("normalize").value)}&t=${Date.now()}`;
  audio.src = url;
  await audio.play();
}

function move(delta) {
  if (!filtered.length) return;
  index = (index + delta + filtered.length) % filtered.length;
  renderList();
  renderCurrent();
  if (el("autoplay").value === "1") play().catch(console.warn);
}

async function saveMark(extra={}, refresh=true) {
  const r = filtered[index];
  if (!r) return;
  const payload = {id: r.id, notes: el("notes").value, ...extra};
  const res = await (await fetch("/api/mark", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)})).json();
  if (res.state) state = res.state;
  if (refresh) { renderList(); renderCurrent(false); }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

el("search").oninput = applyFilter;
el("cat").onchange = applyFilter;
el("play").onclick = () => play().catch(e => alert(e.message));
el("prev").onclick = () => move(-1);
el("next").onclick = () => move(1);
el("shuffle").onclick = () => { index = Math.floor(Math.random() * Math.max(1, filtered.length)); renderList(); renderCurrent(); };
el("notes").onchange = () => saveMark({}, true);
el("clearVote").onclick = () => saveMark({vote:""}, true);
el("copyPath").onclick = async () => { const r = filtered[index]; if (r) await navigator.clipboard.writeText(r.primary_path); };
el("rescan").onclick = async () => { await fetch("/api/rescan", {method:"POST", body:"{}"}); await load(); };
document.querySelectorAll("[data-vote]").forEach(b => b.onclick = () => saveMark({vote:b.dataset.vote}, true));
audio.onended = () => { if (el("autoplay").value === "1") move(1); };
document.addEventListener("keydown", e => {
  if (e.target && ["INPUT","TEXTAREA","SELECT"].includes(e.target.tagName)) return;
  if (e.code === "Space") { e.preventDefault(); if (audio.paused) play().catch(console.warn); else audio.pause(); }
  if (e.key === "j" || e.key === "ArrowLeft") move(-1);
  if (e.key === "k" || e.key === "ArrowRight") move(1);
  if (e.key === "1") saveMark({vote:"KEEP"}, true);
  if (e.key === "2") saveMark({vote:"MAYBE"}, true);
  if (e.key === "3") saveMark({vote:"REJECT"}, true);
});
load();
</script>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-canonical", action="store_true", help="scan dev/tmp only, not bodies/")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    records = scan_bodies(include_canonical=not args.no_canonical)
    if not records:
        print("No 240-byte bodies found.", file=sys.stderr)
        return 2
    server = BodyServer((args.host, args.port), Handler, records)
    print(f"body240 player -> http://{args.host}:{args.port}/")
    print(f"{len(records)} unique 240-byte bodies")
    print("source = .body240 / 240-byte .bin / compiled-v1 packedWords; old WAVs are ignored")
    print("Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
