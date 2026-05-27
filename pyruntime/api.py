"""FastAPI authoring runtime.

Active surfaces:
- `/desk/*`: the response-first command center (draw -> forge_fit -> audition -> live).
- `/` redirects to `/desk`.
- `/designer*`: the heritage Compiler (E-mu MorphDesigner XML), kept separate.
- shared: `/response`, `/analyze`, `/bake`, `/export`, `/render`, `/vault`, `/splice`,
  `/live-response`, `/health`.

The stage-first generator path (target/macro_compile + /sift, /target, designer UIs)
was retired 2026-05-27 and quarantined under pyruntime/legacy/.
"""
from __future__ import annotations

import glob
import json
import math
import os
import random
import re

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from pyruntime.body import Body, list_vault_bodies, load_vault_body
from pyruntime.constants import NUM_BODY_STAGES, SR
from pyruntime.corner import CornerArray, CornerName, CornerState
from pyruntime.designer_compile import (
    compile_four_corner_to_body,
    legacy_sections_to_four_corner,
    make_four_corner_template,
)
from pyruntime.encode import EncodedCoeffs, raw_to_encoded
from pyruntime.freq_response import cascade_response_db, freq_points
from pyruntime.render import render_body, render_from_body
from pyruntime.splice import SpliceError, SpliceMode, splice_corners
from pyruntime.stage_params import StageParams
from pyruntime.analysis import body_profile

# NOTE: the stage-first generator path (pyruntime.target + pyruntime.macro_compile)
# and its routes (/target, /morph-target, /composite-target, /sonic-tables,
# /suggest, /sift/*) and static designer UIs were retired 2026-05-27 — those
# modules are quarantined under pyruntime/legacy/. The forward path is the
# response-first desk (/desk/*). See pyruntime/legacy/README.md.


app = FastAPI(title="TRENCH Authoring Runtime")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
LIVE_PATH = os.path.join(os.path.dirname(__file__), "..", "trench_live.json")
VAULT_DIR = os.path.join(os.path.dirname(__file__), "..", "vault")
SAFE_NAME = re.compile(r"^[A-Za-z0-9_]+$")

PASSTHROUGH_ENC = EncodedCoeffs(c0=2.0, c1=1.0, c2=2.0, c3=1.0, c4=1.0)
CORNER_KEYS = ("M0_Q0", "M0_Q100", "M100_Q0", "M100_Q100")


class ResponseRequest(BaseModel):
    body: dict
    morph: float = 0.5
    q: float = 0.5


class ExportRequest(BaseModel):
    body: dict
    name: str


class BakeRequest(BaseModel):
    body: dict
    provenance: str = "pyruntime"


class RenderRequest(BaseModel):
    body: dict | None = None
    morph: float = 0.5
    q: float = 0.5
    mackie_amount: float = 0.5
    erode_amount: float = 0.0
    corrode_amount: float = 0.0
    duration: float = 2.0


class DesignerSectionInput(BaseModel):
    type: int = 0
    low_freq: int = 0
    low_gain: int = 0
    high_freq: int = 0
    high_gain: int = 0


class DesignerCellInput(BaseModel):
    type: int = 0
    freq: int = 0
    gain: int = 0


class DesignerRequest(BaseModel):
    name: str = "Untitled"
    boost: float = 4.0
    corners: dict[str, list[DesignerCellInput]] = Field(default_factory=dict)
    sections: list[DesignerSectionInput] = Field(default_factory=list)


class DesignerRenderRequest(DesignerRequest):
    morph: float = 0.5
    q: float = 0.5
    mackie_amount: float = 0.5
    erode_amount: float = 0.0
    corrode_amount: float = 0.0
    duration: float = 2.0


class SpliceRequest(BaseModel):
    name: str
    body_a: str
    body_b: str
    mode: str = "RestToMorphed"


class AnalyzeRequest(BaseModel):
    body: dict


def _load_body(d: dict) -> Body:
    try:
        return Body.from_dict(d)
    except ValueError as e:
        raise HTTPException(400, f"Body parse error: {e}") from e


def _designer_template_from_request(req: DesignerRequest):
    if req.corners:
        missing = [key for key in CORNER_KEYS if key not in req.corners]
        if missing:
            raise HTTPException(400, f"Designer request missing corners: {missing}")
        corner_payload = {
            key: [
                {"type": cell.type, "freq": cell.freq, "gain": cell.gain}
                for cell in req.corners[key][:6]
            ]
            for key in CORNER_KEYS
        }
        return make_four_corner_template(req.name, corner_payload)

    if req.sections:
        tuples = [
            (section.type, section.low_freq, section.low_gain, section.high_freq, section.high_gain)
            for section in req.sections[:6]
        ]
        return legacy_sections_to_four_corner(req.name, tuples)

    return make_four_corner_template(
        req.name,
        {key: [{"type": 0, "freq": 0, "gain": 0} for _ in range(6)] for key in CORNER_KEYS},
    )


def _compile_designer_body(req: DesignerRequest) -> Body:
    template = _designer_template_from_request(req)
    return compile_four_corner_to_body(template, boost=req.boost)


@app.get("/")
def serve_root():
    # Root now points at the response-first command center (the desk).
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/desk")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/live-response")
def live_response():
    if not os.path.exists(LIVE_PATH):
        return {"freqs": [], "db": [], "label": ""}
    try:
        with open(LIVE_PATH) as f:
            live_data = json.load(f)
        body = Body.from_dict(live_data)
        enc = body.corners.interpolate(0.5, 0.5)
        freqs = freq_points()
        db = cascade_response_db(enc, freqs, SR)
        return {"freqs": freqs.tolist(), "db": db.tolist(), "label": live_data.get("name", "")}
    except Exception:
        return {"freqs": [], "db": [], "label": ""}


@app.post("/response")
def response_endpoint(req: ResponseRequest):
    body = _load_body(req.body)
    enc = body.corners.interpolate(req.morph, req.q)
    freqs = freq_points()
    db = cascade_response_db(enc, freqs, SR)
    return {"freqs": freqs.tolist(), "db": db.tolist()}


@app.post("/export")
def export_endpoint(req: ExportRequest):
    if not SAFE_NAME.match(req.name):
        raise HTTPException(400, "Name must be alphanumeric + underscore only")
    os.makedirs(VAULT_DIR, exist_ok=True)
    path = os.path.join(VAULT_DIR, f"{req.name}.json")
    body = _load_body(req.body)
    with open(path, "w") as f:
        f.write(body.to_compiled_json())
    return {"path": path}


@app.post("/bake")
def bake_endpoint(req: BakeRequest):
    body = _load_body(req.body)
    return json.loads(body.to_compiled_json(provenance=req.provenance))


@app.post("/render")
def render_endpoint(req: RenderRequest):
    return render_body(
        body_dict=req.body,
        morph=req.morph,
        q=req.q,
        mackie_amount=req.mackie_amount,
        erode_amount=req.erode_amount,
        corrode_amount=req.corrode_amount,
        duration=req.duration,
    )


@app.post("/designer")
def designer_endpoint(req: DesignerRequest):
    return json.loads(_compile_designer_body(req).to_json())


@app.post("/designer/render")
def designer_render_endpoint(req: DesignerRenderRequest):
    body = _compile_designer_body(req)
    return render_from_body(
        body,
        req.morph,
        req.q,
        req.mackie_amount,
        req.erode_amount,
        req.corrode_amount,
        req.duration,
    )


@app.post("/designer/response")
def designer_response_endpoint(req: DesignerRenderRequest):
    body = _compile_designer_body(req)
    enc = body.corners.interpolate(req.morph, req.q)
    freqs = freq_points()
    return {"freqs": freqs.tolist(), "db": cascade_response_db(enc, freqs, SR).tolist()}


@app.post("/designer/live")
def designer_live_endpoint(req: DesignerRequest):
    body = _compile_designer_body(req)
    compiled = body.to_compiled_json(provenance="designer-live")
    with open(LIVE_PATH, "w") as f:
        f.write(compiled)
    return {"status": "ok", "name": body.name}


@app.post("/analyze")
def analyze_endpoint(req: AnalyzeRequest):
    body = _load_body(req.body)
    return body_profile(body)


@app.get("/vault")
def vault_listing():
    return list_vault_bodies()


@app.post("/splice")
def splice_endpoint(req: SpliceRequest):
    try:
        body_a = load_vault_body(req.body_a)
        body_b = load_vault_body(req.body_b)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e

    try:
        mode = SpliceMode(req.mode)
    except ValueError as e:
        modes = [member.value for member in SpliceMode]
        raise HTTPException(400, f"Unknown mode '{req.mode}'. Use one of: {modes}") from e

    try:
        spliced = splice_corners(
            body_a.corners,
            body_b.corners,
            mode,
            filter_type_a=body_a.filter_type,
            filter_type_b=body_b.filter_type,
        )
    except SpliceError as e:
        raise HTTPException(400, str(e)) from e
    body = Body(name=req.name, corners=spliced, boost=body_a.boost)
    return json.loads(body.to_json())


# ── Anatomy-First filter design desk ─────────────────────────────────────────
# draw magnitude target -> cepstral min-phase -> the REAL forge_fit solver ->
# stable cartridge -> the plugin's live slot (~/Documents/TRENCH/authoring_slot.json).
from pyruntime import desk_compile as _desk  # noqa: E402

_DESK_HTML = os.path.join(os.path.dirname(__file__), "..", "dev", "filter_desk", "index.html")


class _DeskPoint(BaseModel):
    hz: float
    db: float


class _DeskCorner(BaseModel):
    points: list[_DeskPoint]


class _DeskDesign(BaseModel):
    name: str = "desk_body"
    boost: float = 1.0
    corners: dict[str, _DeskCorner]


class _DeskAudition(BaseModel):
    cartridge: dict
    morph: float = 0.5
    q: float = 0.5
    source: str = "808"      # "808" | "saw" | "noise"
    seconds: float = 2.5


def _as_dict(model):
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


@app.get("/desk")
def serve_desk():
    return FileResponse(_DESK_HTML)


@app.get("/desk/health")
def desk_health():
    return _desk.health()


@app.get("/desk/live")
def desk_live():
    d = _desk.live_as_design()
    return d if d is not None else {"name": "", "corners": {}}


@app.post("/desk/compile")
def desk_compile_route(design: _DeskDesign):
    return _desk.compile_design(_as_dict(design))


@app.post("/desk/validate")
def desk_validate(cart: dict):
    return _desk.validate_cartridge(cart)


@app.post("/desk/write-live")
def desk_write(cart: dict):
    val = _desk.validate_cartridge(cart)
    if not val["ok"]:
        raise HTTPException(400, {"error": "validation failed", **val})
    return {"path": _desk.write_live(cart), "validate": val}


@app.post("/desk/audition")
def desk_audition(req: _DeskAudition):
    """Render the body through the SHIPPED engine at (morph, q) — returns a WAV."""
    from fastapi.responses import Response as _Resp
    try:
        wav = _desk.audition(req.cartridge, req.morph, req.q,
                             source=req.source, seconds=req.seconds)
    except RuntimeError as e:
        raise HTTPException(503, {"error": str(e)})
    except (ValueError, KeyError) as e:
        raise HTTPException(400, {"error": str(e)})
    return _Resp(content=wav, media_type="audio/wav")
