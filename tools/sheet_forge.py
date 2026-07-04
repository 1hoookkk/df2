"""SHEET FORGE — Tyson's live pen. Browser edits the sheet; every touch
compiles the REAL 240-byte body (morph_designer.compile_lanes, unit zeros
legal), updates the curve from the real packed pipeline, and rewrites
Documents/TRENCH/authoring_slot.json so a running diagnostics TRENCH
('@ Audition (live)' selected) sounds the change immediately.

Run:   python tools/sheet_forge.py [sheets/VOWL_aa_to_iy.json]
Open:  http://localhost:8140/
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from tools import author_sheet as ash
from tools import morph_designer as md
from src.utils.packed_runtime import evaluate_body, gate_failures

PAGE = ROOT / "forge-web" / "sheet_forge.html"
SHEETS = ROOT / "sheets"
OUT = ROOT / "dev" / "tmp" / "author_sheet"
PORT = 8140

STATE = {"sheet_path": None, "body": None, "lock": threading.Lock()}


def compile_sheet(sheet: dict) -> dict:
    lanes = [ash.lane_from_row(r) for r in sheet["lanes"][:6]]
    body = md.compile_lanes(sheet["name"], lanes)
    ev = evaluate_body(body, 17)
    fails = gate_failures(ev, md.GATES, md.REFERENCE)
    bad = (ev["grid_unstable_rows"] + ev["interior_unstable_rows"]
           + ev["grid_nonfinite_rows"] + ev["interior_nonfinite_rows"])
    curves = {}
    for label, m, q in (("LO", 0, 0), ("HI", 1, 0), ("LOQ", 0, 1), ("HIQ", 1, 1),
                        ("MID", 0.5, 0.5)):
        curves[label] = [round(float(v), 1) for v in md.resp(body, m, q)[::3]]
    return {
        "body": body,
        "reply": {
            "ok": True,
            "stable": not bad,
            "gate": "PASS" if not fails else "; ".join(fails),
            "metrics": {k: round(float(ev[k]), 2) for k in (
                "max_pole_radius", "endpoint_span_db_mean", "morph_contrast_rms_db",
                "secondary_contrast_rms_db", "center_response_peaks",
                "center_response_valleys", "max_zero_motion_octaves")},
            "freqs": [round(float(f), 1) for f in md.FREQS[::3]],
            "curves": curves,
        },
    }


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode())

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/sheet":
            self._json(json.loads(STATE["sheet_path"].read_text(encoding="utf-8")))
        elif self.path.startswith("/api/curve"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            m, s = float(q["m"][0]), float(q["q"][0])
            with STATE["lock"]:
                body = STATE["body"]
            if body is None:
                self._json({"ok": False}, 400); return
            self._json({"ok": True,
                        "curve": [round(float(v), 1) for v in md.resp(body, m, s)[::3]]})
        elif self.path.startswith("/out/"):
            f = OUT / Path(self.path[5:]).name
            if f.is_file():
                self._send(200, f.read_bytes(), "audio/wav")
            else:
                self._send(404, b"{}")
        else:
            self._send(404, b"{}")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/compile":
            try:
                res = compile_sheet(data)
            except Exception as e:  # provenance refusals land here, verbatim
                self._json({"ok": False, "error": str(e)}); return
            with STATE["lock"]:
                STATE["body"] = res["body"]
            name = data["name"]
            # persist: the sheet file IS the artifact; body + slot ride along
            STATE["sheet_path"].write_text(json.dumps(data, indent=2), encoding="utf-8")
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / f"{name}.body240").write_bytes(res["body"])
            slot = ash.write_audition_slot(name, res["body"],
                                           f"sheet_forge {STATE['sheet_path'].name}")
            res["reply"]["slot"] = str(slot) if slot else None
            self._json(res["reply"])
        elif self.path == "/api/sweep":
            with STATE["lock"]:
                body = STATE["body"]
            if body is None:
                self._json({"ok": False}, 400); return
            name = data.get("name", "sheet")
            wavs = ash.write_sweep_wavs(name, body)
            self._json({"ok": True, "wavs": ["/out/" + p.name for p in wavs]})
        else:
            self._send(404, b"{}")


def main():
    sheet = Path(sys.argv[1]) if len(sys.argv) > 1 else SHEETS / "VOWL_aa_to_iy.json"
    if not sheet.is_file():
        raise SystemExit(f"no sheet: {sheet}")
    bak = sheet.with_suffix(sheet.suffix + ".bak")
    if not bak.exists():
        bak.write_bytes(sheet.read_bytes())          # one backup per sheet, ever
    STATE["sheet_path"] = sheet
    print(f"SHEET  {sheet}")
    print(f"OPEN   http://localhost:{PORT}/")
    print("EARS   diagnostics TRENCH + '@ Audition (live)' = hears every edit")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
