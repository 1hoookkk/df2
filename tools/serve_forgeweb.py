#!/usr/bin/env python3
"""Serve forge-web plus a narrow Forge API.

This keeps the phone/desktop URL useful: the browser gets the editor, while
whitelisted endpoints run repo-native Forge steps and return artifact links.

Run:
    python tools/serve_forgeweb.py
"""
from __future__ import annotations

import json
import mimetypes
import re
import subprocess
import sys
import time
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "forge-web"
DEV_TMP = ROOT / "dev" / "tmp"
API_ROOT = DEV_TMP / "forge_api"
TARGET_RUN_ROOT = DEV_TMP / "target_browser"

_HERE = str(Path(__file__).resolve().parent)
sys.path[:] = [p for p in sys.path if p not in ("", _HERE, str(ROOT))]
sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"
PORT = 8130


def safe_name(value: object, fallback: str = "body") -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or fallback)).strip("._-")
    return (name or fallback)[:80]


def stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def artifact_url(path: Path) -> str:
    rel = path.resolve().relative_to(DEV_TMP.resolve()).as_posix()
    return f"/artifacts/{rel}"


def artifact_payload(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "url": artifact_url(path),
        "bytes": path.stat().st_size if path.exists() else 0,
    }


def run_cmd(args: list[str], timeout: int = 120) -> dict[str, object]:
    proc = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "command": args,
    }


def script_manifest() -> list[dict[str, object]]:
    return [
        {
            "id": "visual.build",
            "label": "Build visual target session",
            "method": "POST",
            "endpoint": "/api/visual/build",
            "inputs": ["target JSON", "session", "grid"],
            "outputs": ["target.json", "fitted_lanes.json", "law_source.json", "body.body240", "cartridge.json", "audit.json", "response.png", "workbench.html"],
            "authority": "tools/forge_visual_author.py -> trench_core packed probe",
        },
        {
            "id": "filter-card.bake",
            "label": "Bake Peak/Shelf filter card",
            "method": "POST",
            "endpoint": "/api/filter-card/bake",
            "inputs": ["filter-card-v1 JSON", "session", "grid"],
            "outputs": ["card.json", "root_lanes.json", "law_source.json", "body.body240", "cartridge.json", "audit.json", "response.png", "workbench.html"],
            "authority": "filter_cards/bake.py -> tools.author_lanes -> trench_core packed probe",
        },
        {
            "id": "foundations.anchors",
            "label": "Measured foundation anchors",
            "method": "GET",
            "endpoint": "/api/foundations/anchors",
            "inputs": [],
            "outputs": ["aggregate low-anchor pole rails"],
            "authority": "dev/tmp/measured_foundations/summary.json",
        },
        {
            "id": "law.compile",
            "label": "Compile Law Author source",
            "method": "POST",
            "endpoint": "/api/law/compile",
            "inputs": ["preset or law JSON", "grid"],
            "outputs": ["law_source.json", ".body240", "cartridge JSON", "audit.json", "plot_sheet.png"],
            "authority": "tools/law_author.py -> trench_core packed probe",
        },
        {
            "id": "body.audit",
            "label": "Audit packed body bytes",
            "method": "POST",
            "endpoint": "/api/body/audit",
            "inputs": ["bodyHex", "grid"],
            "outputs": ["max pole radius", "unstable/nonfinite masks", "sample grid"],
            "authority": "pyruntime.trench_ffi.packed_probe",
        },
        {
            "id": "body.save",
            "label": "Save edited body/session",
            "method": "POST",
            "endpoint": "/api/body/save",
            "inputs": ["bodyHex", "name", "session JSON"],
            "outputs": ["dev/tmp/forge_keepers/*.body240", "optional .df2forge.json"],
            "authority": "240-byte packed body",
        },
        {
            "id": "family.rebuild",
            "label": "Rebuild Forge fundamentals data",
            "method": "POST",
            "endpoint": "/api/family/rebuild",
            "inputs": [],
            "outputs": ["forge-web/data/family-laws.js"],
            "authority": "tools/build_forge_family_data.py",
        },
        {
            "id": "target.templates",
            "label": "List Target Browser archetypes",
            "method": "GET",
            "endpoint": "/api/target/templates",
            "inputs": [],
            "outputs": ["template list"],
            "authority": "tools/target_templates.json",
        },
        {
            "id": "target.generate",
            "label": "Generate/audition target-browser candidates",
            "method": "POST",
            "endpoint": "/api/target/generate",
            "inputs": ["template", "seed", "count"],
            "outputs": ["audition.html", "candidate bodies", "reports"],
            "authority": "python -m tools.target_browser",
        },
        {
            "id": "target.keep",
            "label": "Promote target-browser keepers",
            "method": "POST",
            "endpoint": "/api/target/keep",
            "inputs": ["runDir", "candidates", "notes"],
            "outputs": ["dev/tmp/keepers/*.body240", "*.cart.json", "*.keep.json"],
            "authority": "python -m tools.target_browser --keep",
        },
        {
            "id": "production.authoring",
            "label": "Production training/export/verify",
            "method": "manual",
            "endpoint": None,
            "inputs": ["train.py model=v1", "scripts/export.py", "scripts/verify_run.py"],
            "outputs": ["verified promoted production run"],
            "authority": "PRODUCTION_AUTHORING.md",
            "note": "Listed only; intentionally not remotely runnable from the browser.",
        },
    ]


class ForgeWebHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, *args) -> None:
        pass

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed)
            return
        if parsed.path.startswith("/artifacts/"):
            self.handle_artifact(parsed.path)
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_json({"error": "unknown endpoint"}, code=404)
            return
        self.handle_api_post(parsed)

    def send_json(self, obj: object, code: int = 200) -> None:
        body = json.dumps(obj, indent=2, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, object]:
        n = int(self.headers.get("Content-Length", "0") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n).decode("utf-8")
        return json.loads(raw or "{}")

    def handle_artifact(self, path: str) -> None:
        rel = unquote(path.removeprefix("/artifacts/"))
        target = (DEV_TMP / rel).resolve()
        if not under(target, DEV_TMP) or not target.exists() or not target.is_file():
            self.send_json({"error": "artifact not found"}, code=404)
            return
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_api_get(self, parsed) -> None:
        try:
            if parsed.path == "/api/health":
                self.api_health()
            elif parsed.path == "/api/scripts":
                self.send_json({"ok": True, "scripts": script_manifest()})
            elif parsed.path == "/api/laws":
                self.api_laws()
            elif parsed.path == "/api/foundations/anchors":
                self.api_foundation_anchors()
            elif parsed.path == "/api/target/templates":
                self.api_target_templates()
            else:
                self.send_json({"error": "unknown endpoint"}, code=404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, code=500)

    def handle_api_post(self, parsed) -> None:
        try:
            if parsed.path == "/api/law/compile":
                self.api_law_compile()
            elif parsed.path == "/api/visual/build":
                self.api_visual_build()
            elif parsed.path == "/api/filter-card/bake":
                self.api_filter_card_bake()
            elif parsed.path == "/api/body/audit":
                self.api_body_audit()
            elif parsed.path == "/api/body/save":
                self.api_body_save()
            elif parsed.path == "/api/family/rebuild":
                self.api_family_rebuild()
            elif parsed.path == "/api/target/generate":
                self.api_target_generate()
            elif parsed.path == "/api/target/keep":
                self.api_target_keep()
            else:
                self.send_json({"error": "unknown endpoint"}, code=404)
        except subprocess.TimeoutExpired as exc:
            self.send_json({"error": "command timed out", "command": exc.cmd}, code=504)
        except Exception as exc:
            self.send_json({"error": str(exc)}, code=500)

    def api_foundation_anchors(self) -> None:
        from filter_cards.bake import MEASURED_FOUNDATIONS, measured_low_anchor_options

        self.send_json(
            {
                "ok": True,
                "source": str(MEASURED_FOUNDATIONS),
                "boundary": "aggregate rails only; no packed words, coefficient rows, endpoint curves, preset names, or reconstructable corner tables",
                "anchors": measured_low_anchor_options(),
            }
        )

    def api_visual_build(self) -> None:
        from pyruntime import trench_ffi
        from tools.forge_visual_author import (
            build_product,
            default_session_name,
            load_target,
            normalize_target,
            write_session,
        )

        if not trench_ffi.available():
            self.send_json({"error": "trench_core packed probe unavailable"}, code=500)
            return

        payload = self.read_json()
        grid = max(3, min(33, int(payload.get("grid", 17))))
        target_data = payload.get("target")
        if isinstance(target_data, dict):
            target = normalize_target(target_data)
        else:
            target = load_target(None)

        session_raw = str(payload.get("session") or "").strip()
        session = safe_name(session_raw, "") if session_raw else default_session_name(target["name"])
        out_dir = (DEV_TMP / "forge_visual_author" / session).resolve()
        if not under(out_dir, DEV_TMP / "forge_visual_author"):
            self.send_json({"error": "session path escaped forge_visual_author root"}, code=400)
            return

        product = build_product(target, grid)
        write_session(product, out_dir)
        artifacts = {
            "target": artifact_payload(out_dir / "target.json"),
            "fitted_lanes": artifact_payload(out_dir / "fitted_lanes.json"),
            "law_source": artifact_payload(out_dir / "law_source.json"),
            "body240": artifact_payload(out_dir / "body.body240"),
            "cartridge": artifact_payload(out_dir / "cartridge.json"),
            "audit": artifact_payload(out_dir / "audit.json"),
            "response": artifact_payload(out_dir / "response.png"),
            "workbench": artifact_payload(out_dir / "workbench.html"),
        }
        self.send_json(
            {
                "ok": product.audit["checks"]["stable"] and product.audit["checks"]["finite_response"],
                "verdict": product.audit.get("verdict"),
                "warnings": product.audit.get("warnings", []),
                "bodyBytes": len(product.body),
                "bodyHex": product.body.hex(),
                "audit": product.audit,
                "runDir": str(out_dir),
                "artifacts": artifacts,
            },
            code=200 if product.audit["checks"]["stable"] and product.audit["checks"]["finite_response"] else 422,
        )

    def api_filter_card_bake(self) -> None:
        from pyruntime import trench_ffi
        from filter_cards.bake import bake_to_dir, default_session_name, normalize_card

        if not trench_ffi.available():
            self.send_json({"error": "trench_core packed probe unavailable"}, code=500)
            return

        payload = self.read_json()
        grid = max(3, min(33, int(payload.get("grid", 17))))
        raw_card = payload.get("card")
        if not isinstance(raw_card, dict):
            raw_card = None
        card = normalize_card(raw_card or {})
        session_raw = str(payload.get("session") or "").strip()
        session = safe_name(session_raw, "") if session_raw else default_session_name(card["name"])
        out_dir = (DEV_TMP / "filter_cards" / session).resolve()
        if not under(out_dir, DEV_TMP / "filter_cards"):
            self.send_json({"error": "session path escaped filter_cards root"}, code=400)
            return

        product = bake_to_dir(card, out_dir, grid=grid)
        artifacts = {
            "card": artifact_payload(out_dir / "card.json"),
            "root_lanes": artifact_payload(out_dir / "root_lanes.json"),
            "law_source": artifact_payload(out_dir / "law_source.json"),
            "body240": artifact_payload(out_dir / "body.body240"),
            "cartridge": artifact_payload(out_dir / "cartridge.json"),
            "audit": artifact_payload(out_dir / "audit.json"),
            "response": artifact_payload(out_dir / "response.png"),
            "workbench": artifact_payload(out_dir / "workbench.html"),
        }
        ok = product.audit["checks"]["stable"] and product.audit["checks"]["finite_response"]
        self.send_json(
            {
                "ok": ok,
                "verdict": product.audit.get("verdict"),
                "warnings": product.audit.get("warnings", []),
                "bodyBytes": len(product.body),
                "bodyHex": product.body.hex(),
                "audit": product.audit,
                "runDir": str(out_dir),
                "artifacts": artifacts,
            },
            code=200 if ok else 422,
        )

    def api_health(self) -> None:
        try:
            from pyruntime import trench_ffi

            trench = {
                "packedProbe": bool(trench_ffi.available()),
                "engine": bool(trench_ffi.engine_available()),
            }
        except Exception as exc:
            trench = {"packedProbe": False, "engine": False, "error": str(exc)}
        self.send_json(
            {
                "ok": True,
                "root": str(ROOT),
                "webRoot": str(WEB_ROOT),
                "devTmp": str(DEV_TMP),
                "trenchCore": trench,
                "scripts": len(script_manifest()),
            }
        )

    def api_laws(self) -> None:
        laws = []
        for path in sorted((ROOT / "recipes" / "laws").glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            laws.append(
                {
                    "preset": path.stem,
                    "name": data.get("name", path.stem),
                    "format": data.get("format", "scalar-law-v1"),
                    "family": data.get("family", ""),
                    "path": str(path),
                }
            )
        self.send_json({"ok": True, "laws": laws})

    def api_law_compile(self) -> None:
        from pyruntime import trench_ffi
        from tools.law_author import default_law_path, load_law, write_outputs

        if not trench_ffi.available():
            self.send_json({"error": "trench_core packed probe unavailable"}, code=500)
            return

        payload = self.read_json()
        grid = max(3, min(33, int(payload.get("grid", 17))))
        preset = payload.get("preset")
        law_data = payload.get("law")

        if preset:
            law_path = default_law_path(safe_name(preset))
            if not law_path.exists():
                self.send_json({"error": f"unknown law preset: {preset}"}, code=404)
                return
            law_name = safe_name(load_law(law_path).name, str(preset))
            out_dir = API_ROOT / "law" / f"{stamp()}_{law_name}"
        elif isinstance(law_data, dict):
            law_name = safe_name(law_data.get("name") or payload.get("name") or "law")
            out_dir = API_ROOT / "law" / f"{stamp()}_{law_name}"
            out_dir.mkdir(parents=True, exist_ok=True)
            law_path = out_dir / "input_law.json"
            law_path.write_text(json.dumps(law_data, indent=2) + "\n", encoding="utf-8")
        else:
            self.send_json({"error": "expected {'preset': name} or {'law': {...}}"}, code=400)
            return

        result = write_outputs(law_path, out_dir, grid)
        paths = result["paths"]
        audit = result["audit"]
        body = paths["body240"].read_bytes()
        self.send_json(
            {
                "ok": audit.get("verdict") == "PASS",
                "verdict": audit.get("verdict"),
                "warnings": audit.get("warnings", []),
                "bodyBytes": len(body),
                "bodyHex": body.hex(),
                "audit": audit,
                "runDir": str(paths["run_dir"]),
                "artifacts": {key: artifact_payload(path) for key, path in paths.items() if path.is_file()},
            },
            code=200 if audit.get("verdict") == "PASS" else 422,
        )

    def api_body_audit(self) -> None:
        from pyruntime import trench_ffi

        payload = self.read_json()
        raw_hex = str(payload.get("bodyHex") or payload.get("body") or "")
        body = bytes.fromhex(re.sub(r"[^0-9A-Fa-f]", "", raw_hex))
        if len(body) != 240:
            self.send_json({"error": f"expected 240 body bytes, got {len(body)}"}, code=400)
            return
        grid = max(3, min(33, int(payload.get("grid", 17))))
        samples = []
        max_r = 0.0
        unstable = 0
        nonfinite = 0
        for qi in range(grid):
            q = qi / (grid - 1)
            for mi in range(grid):
                morph = mi / (grid - 1)
                probe = trench_ffi.packed_probe(body, morph, q)
                max_r = max(max_r, float(probe.get("max_pole_radius", 0.0)))
                unstable |= int(probe.get("unstable_mask", 0))
                nonfinite |= int(probe.get("nonfinite_mask", 0))
                if mi in (0, grid - 1) and qi in (0, grid - 1):
                    samples.append(
                        {
                            "morph": morph,
                            "q": q,
                            "maxPoleRadius": probe.get("max_pole_radius"),
                            "unstableMask": probe.get("unstable_mask"),
                            "nonfiniteMask": probe.get("nonfinite_mask"),
                        }
                    )
        self.send_json(
            {
                "ok": unstable == 0 and nonfinite == 0 and max_r < 1.0,
                "grid": grid,
                "maxPoleRadius": max_r,
                "unstableMask": unstable,
                "nonfiniteMask": nonfinite,
                "samples": samples,
            }
        )

    def api_body_save(self) -> None:
        payload = self.read_json()
        raw_hex = str(payload.get("bodyHex") or payload.get("body") or "")
        body = bytes.fromhex(re.sub(r"[^0-9A-Fa-f]", "", raw_hex))
        if len(body) != 240:
            self.send_json({"error": f"expected 240 body bytes, got {len(body)}"}, code=400)
            return
        name = safe_name(payload.get("name") or payload.get("bodyId") or "forge_keep")
        keep_dir = DEV_TMP / "forge_keepers"
        keep_dir.mkdir(parents=True, exist_ok=True)
        body_path = keep_dir / f"{name}.body240"
        body_path.write_bytes(body)
        artifacts = {"body240": artifact_payload(body_path)}
        if isinstance(payload.get("session"), dict):
            session_path = keep_dir / f"{name}.df2forge.json"
            session_path.write_text(json.dumps(payload["session"], indent=2) + "\n", encoding="utf-8")
            artifacts["session"] = artifact_payload(session_path)
        self.send_json({"ok": True, "artifacts": artifacts})

    def api_family_rebuild(self) -> None:
        result = run_cmd([sys.executable, "tools/build_forge_family_data.py"], timeout=30)
        result["staticUrl"] = "/data/family-laws.js"
        self.send_json(result, code=200 if result["ok"] else 500)

    def api_target_templates(self) -> None:
        path = ROOT / "tools" / "target_templates.json"
        self.send_json(json.loads(path.read_text(encoding="utf-8")))

    def api_target_generate(self) -> None:
        payload = self.read_json()
        template = safe_name(payload.get("template") or payload.get("name") or "")
        seed = int(payload.get("seed", 1))
        count = max(4, min(48, int(payload.get("count", 16))))
        templates = json.loads((ROOT / "tools" / "target_templates.json").read_text(encoding="utf-8"))
        names = {t["name"] for t in templates.get("templates", [])}
        if template not in names:
            self.send_json({"error": f"unknown target template: {template}", "templates": sorted(names)}, code=400)
            return
        result = run_cmd(
            [sys.executable, "-m", "tools.target_browser", "--template", template, "--seed", str(seed), "--count", str(count)],
            timeout=240,
        )
        match = re.search(r"audition -> (.+)", str(result.get("stdout", "")))
        if match:
            audition = Path(match.group(1).strip()).resolve()
            if audition.exists() and under(audition, DEV_TMP):
                result["audition"] = artifact_payload(audition)
                result["runDir"] = str(audition.parent)
        self.send_json(result, code=200 if result["ok"] else 500)

    def api_target_keep(self) -> None:
        payload = self.read_json()
        raw_run = Path(str(payload.get("runDir") or payload.get("run") or ""))
        run_dir = raw_run if raw_run.is_absolute() else (ROOT / raw_run)
        run_dir = run_dir.resolve()
        if not under(run_dir, TARGET_RUN_ROOT) or not run_dir.exists():
            self.send_json({"error": f"runDir must be under {TARGET_RUN_ROOT}"}, code=400)
            return
        candidates = payload.get("candidates") or payload.get("names") or []
        if isinstance(candidates, str):
            candidates = [candidates]
        names = [safe_name(c, "") for c in candidates if safe_name(c, "")]
        if not names:
            self.send_json({"error": "expected candidates list"}, code=400)
            return
        notes = str(payload.get("notes") or "")
        result = run_cmd(
            [sys.executable, "-m", "tools.target_browser", "--keep", str(run_dir), *names, "--notes", notes],
            timeout=60,
        )
        self.send_json(result, code=200 if result["ok"] else 500)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args(argv)

    API_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"forge-web + API on http://{args.host}:{args.port}  root={WEB_ROOT}")
    print("API: /api/health /api/scripts /api/law/compile /api/body/audit /api/body/save")
    ThreadingHTTPServer((args.host, args.port), ForgeWebHandler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
