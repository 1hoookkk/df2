#!/usr/bin/env python3
"""Tiny static server for the See Your Plugin x-ray tool, plus a /save endpoint
that writes ui_layout.json to the location the plugin actually reads (handles the
OneDrive-redirected Documents folder). Serves from the repo root."""
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def layout_target() -> str:
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "OneDrive", "Documents", "TRENCH", "ui_layout.json"),
        os.path.join(home, "Documents", "TRENCH", "ui_layout.json"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return candidates[0]  # plugin creates it under OneDrive Documents on first open


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=REPO_ROOT, **kwargs)

    def do_POST(self):
        if self.path != "/save":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length)
            parsed = json.loads(payload)  # validate it is JSON before writing
            if not isinstance(parsed, dict) or parsed.get("version") != 1:
                raise ValueError("not a version-1 layout")
            target = layout_target()
            os.makedirs(os.path.dirname(target), exist_ok=True)
            tmp = target + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(parsed, f, indent=2)
            os.replace(tmp, target)  # atomic
            body = json.dumps({"ok": True, "wrote": target}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:  # never crash the server on bad input
            msg = json.dumps({"ok": False, "error": str(exc)}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8777), Handler).serve_forever()
