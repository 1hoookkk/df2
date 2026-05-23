"""FastAPI authoring runtime.

Active surfaces:
- `/`: unified morph designer + sift + analysis
- `/designer`: legacy four-corner designer
- `/sift`: legacy sift surface
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
from pyruntime.target import (
    build_landmark_target,
    build_nasal_target,
    build_vowel_target,
    build_morph_target,
    build_composite_target,
    build_bell_target,
    build_electronic_target,
    get_bell_names,
    get_electronic_keys,
    get_landmark_names,
    get_nasal_keys,
    get_vowel_keys,
)
from pyruntime.macro_compile import compile_body
from pyruntime.analysis import body_profile


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


class BatchRequest(BaseModel):
    base_sections: list = Field(default_factory=list)
    count: int = 10
    name_prefix: str = "candidate"
    boost: float = 4.0


class TargetRequest(BaseModel):
    name: str
    source: str
    key: str


class SpliceRequest(BaseModel):
    name: str
    body_a: str
    body_b: str
    mode: str = "RestToMorphed"


class MorphTargetRequest(BaseModel):
    name: str
    source_a: str
    key_a: str
    source_b: str
    key_b: str


class CompositeTargetRequest(BaseModel):
    name: str
    slots: list[dict]


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
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/designer")
def serve_designer():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/workbench")
def serve_workbench():
    return FileResponse(os.path.join(STATIC_DIR, "workbench.html"))


@app.get("/sift")
def serve_sift():
    return FileResponse(os.path.join(STATIC_DIR, "sift.html"))


@app.get("/forge")
def serve_forge():
    return FileResponse(os.path.join(STATIC_DIR, "forge.html"))


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


_candidate_queue: list[dict] = []
_candidate_index: int = 0
_p2k_bodies: list[dict] | None = None


def _get_p2k_bodies() -> list[dict]:
    global _p2k_bodies
    if _p2k_bodies is not None:
        return _p2k_bodies

    bodies: list[dict] = []
    skin_dir = os.path.join(os.path.dirname(__file__), "..", "datasets", "p2k_skins")
    for path in sorted(glob.glob(os.path.join(skin_dir, "P2k_*.json"))):
        with open(path) as f:
            bodies.append(json.load(f))
    _p2k_bodies = bodies
    return bodies


@app.post("/sift/generate")
def sift_generate(req: BatchRequest):
    """Generate a candidate queue for rapid ear triage."""
    global _candidate_queue, _candidate_index
    _candidate_queue = []
    _candidate_index = 0

    bodies = _get_p2k_bodies()
    if len(bodies) < 2:
        raise HTTPException(500, "Need at least 2 P2K bodies in datasets/p2k_skins/")

    corner_labels = ["M0_Q0", "M0_Q100", "M100_Q0", "M100_Q100"]

    def body_to_corners(bdata: dict, boost: float) -> list[CornerState]:
        out: list[CornerState] = []
        for label in corner_labels:
            raw_stages = bdata["corners"][label]["stages"]
            stages: list[StageParams] = []
            pre_encoded: list[EncodedCoeffs] = []
            for stage in raw_stages[:6]:
                sp = StageParams(
                    a1=stage["a1"],
                    r=stage["r"],
                    val1=stage["val1"],
                    val2=stage["val2"],
                    val3=stage["val3"],
                )
                stages.append(sp)
                pre_encoded.append(raw_to_encoded(sp, flag=stage.get("flag", 1.0)))
            while len(stages) < NUM_BODY_STAGES:
                stages.append(StageParams.passthrough())
                pre_encoded.append(PASSTHROUGH_ENC)
            out.append(CornerState(stages=stages, boost=boost, _pre_encoded=pre_encoded))
        return out

    def perturb_corner(corner: CornerState, semitones: float) -> CornerState:
        ratio = 2.0 ** (semitones / 12.0)
        stages: list[StageParams] = []
        pre_encoded: list[EncodedCoeffs] = []
        for sp in corner.stages[:6]:
            if sp.r > 0.01:
                freq_hz = math.acos(max(-1.0, min(1.0, -sp.a1 / (2 * sp.r)))) * 39062.5 / (2 * math.pi)
                new_freq = max(20.0, min(18000.0, freq_hz * ratio))
                theta = 2.0 * math.pi * new_freq / 39062.5
                new_sp = StageParams(
                    a1=-2.0 * sp.r * math.cos(theta),
                    r=sp.r,
                    val1=sp.val1,
                    val2=sp.val2,
                    val3=sp.val3,
                )
            else:
                new_sp = sp
            stages.append(new_sp)
            pre_encoded.append(raw_to_encoded(new_sp, flag=1.0))
        while len(stages) < NUM_BODY_STAGES:
            stages.append(StageParams.passthrough())
            pre_encoded.append(PASSTHROUGH_ENC)
        return CornerState(stages=stages, boost=corner.boost, _pre_encoded=pre_encoded)

    source_pairs = [
        ("vowel", "vowel"),
        ("vowel", "nasal"),
        ("vowel", "bell"),
        ("nasal", "landmark"),
    ]
    source_key_getters = {
        "vowel": get_vowel_keys,
        "nasal": get_nasal_keys,
        "landmark": get_landmark_names,
        "bell": get_bell_names,
    }

    for i in range(req.count):
        strategy = random.choice(["splice", "perturb", "cross", "target"])
        a_body = random.choice(bodies)
        b_body = random.choice(bodies)
        name = f"{req.name_prefix}_{i:03d}"

        if strategy == "target":
            try:
                src_a, src_b = random.choice(source_pairs)
                key_a = random.choice(source_key_getters[src_a]())
                key_b = random.choice(source_key_getters[src_b]())
                spec = build_morph_target(name, src_a, key_a, src_b, key_b)
                target_corners = compile_body(spec)
                body = Body(name=name, corners=target_corners, boost=spec.boost)
                _candidate_queue.append(json.loads(body.to_compiled_json(provenance="sift-target")))
            except (ValueError, IndexError):
                pass
            continue

        if strategy == "splice":
            a_ca = CornerArray(*body_to_corners(a_body, req.boost))
            b_ca = CornerArray(*body_to_corners(b_body, req.boost))
            try:
                spliced = splice_corners(
                    a_ca,
                    b_ca,
                    SpliceMode.REST_TO_MORPHED,
                    filter_type_a=a_body.get("filterType"),
                    filter_type_b=b_body.get("filterType"),
                )
            except SpliceError:
                continue
            corners = [
                spliced.corner(CornerName.A),
                spliced.corner(CornerName.B),
                spliced.corner(CornerName.C),
                spliced.corner(CornerName.D),
            ]
        elif strategy == "perturb":
            shift = random.uniform(-5.0, 5.0)
            base = body_to_corners(a_body, req.boost)
            corners = [perturb_corner(corner, shift) for corner in base]
        else:
            a_corners = body_to_corners(a_body, req.boost)
            b_corners = body_to_corners(b_body, req.boost)
            corners = []
            for idx in range(4):
                ac = a_corners[idx]
                bc = b_corners[idx]
                stages = list(ac.stages[:3]) + list(bc.stages[3:6]) + list(ac.stages[6:])
                pre = list(ac._pre_encoded[:3]) + list(bc._pre_encoded[3:6]) + list(ac._pre_encoded[6:])
                corners.append(CornerState(stages=stages, boost=req.boost, _pre_encoded=pre))

        body = Body(
            name=name,
            corners=CornerArray(a=corners[0], b=corners[1], c=corners[2], d=corners[3]),
            boost=req.boost,
        )
        _candidate_queue.append(json.loads(body.to_compiled_json(provenance=f"sift-{strategy}")))

    if _candidate_queue:
        with open(LIVE_PATH, "w") as f:
            json.dump(_candidate_queue[0], f)

    return {"count": len(_candidate_queue), "current": 0, "name": _candidate_queue[0].get("name", "") if _candidate_queue else ""}


@app.post("/sift/next")
def sift_next():
    global _candidate_index
    if not _candidate_queue:
        raise HTTPException(400, "No candidates. Call /sift/generate first.")
    _candidate_index = (_candidate_index + 1) % len(_candidate_queue)
    with open(LIVE_PATH, "w") as f:
        json.dump(_candidate_queue[_candidate_index], f)
    return {"current": _candidate_index, "count": len(_candidate_queue), "name": _candidate_queue[_candidate_index].get("name", "")}


@app.post("/sift/prev")
def sift_prev():
    global _candidate_index
    if not _candidate_queue:
        raise HTTPException(400, "No candidates. Call /sift/generate first.")
    _candidate_index = (_candidate_index - 1) % len(_candidate_queue)
    with open(LIVE_PATH, "w") as f:
        json.dump(_candidate_queue[_candidate_index], f)
    return {"current": _candidate_index, "count": len(_candidate_queue), "name": _candidate_queue[_candidate_index].get("name", "")}


@app.post("/sift/save")
def sift_save():
    if not _candidate_queue or _candidate_index >= len(_candidate_queue):
        raise HTTPException(400, "No current candidate.")
    candidate = _candidate_queue[_candidate_index]
    name = candidate.get("name", f"sift_{_candidate_index:03d}")
    os.makedirs(VAULT_DIR, exist_ok=True)
    path = os.path.join(VAULT_DIR, f"{name}.json")
    with open(path, "w") as f:
        json.dump(candidate, f, indent=2)
    return {"saved": name, "path": path}


@app.post("/sift/trash")
def sift_trash():
    global _candidate_queue, _candidate_index
    if not _candidate_queue:
        raise HTTPException(400, "No candidates.")
    _candidate_queue.pop(_candidate_index)
    if not _candidate_queue:
        return {"count": 0, "current": 0, "name": ""}
    _candidate_index = _candidate_index % len(_candidate_queue)
    with open(LIVE_PATH, "w") as f:
        json.dump(_candidate_queue[_candidate_index], f)
    return {"current": _candidate_index, "count": len(_candidate_queue), "name": _candidate_queue[_candidate_index].get("name", "")}


@app.get("/sift/status")
def sift_status():
    name = ""
    if _candidate_queue and _candidate_index < len(_candidate_queue):
        name = _candidate_queue[_candidate_index].get("name", "")
    return {"current": _candidate_index, "count": len(_candidate_queue), "name": name}


@app.get("/sift/current")
def sift_current():
    """Return the current sift candidate as a full body dict for audition."""
    if not _candidate_queue or _candidate_index >= len(_candidate_queue):
        raise HTTPException(400, "No current candidate.")
    return _candidate_queue[_candidate_index]


@app.get("/sonic-tables")
def sonic_tables():
    return {
        "vowels": get_vowel_keys(),
        "nasals": get_nasal_keys(),
        "landmarks": get_landmark_names(),
        "bells": get_bell_names(),
        "electronic": get_electronic_keys(),
    }


@app.post("/target")
def target_endpoint(req: TargetRequest):
    if req.source == "vowel":
        spec = build_vowel_target(req.name, req.key)
    elif req.source == "nasal":
        spec = build_nasal_target(req.name, req.key)
    elif req.source == "landmark":
        spec = build_landmark_target(req.name, req.key)
    elif req.source == "bell":
        spec = build_bell_target(req.name, req.key)
    elif req.source == "electronic":
        spec = build_electronic_target(req.name, req.key)
    else:
        raise HTTPException(400, f"Unknown source '{req.source}'. Use vowel, nasal, landmark, bell, or electronic.")

    corners = compile_body(spec)
    body = Body(name=req.name, corners=corners, boost=spec.boost)
    return json.loads(body.to_json())


@app.post("/morph-target")
def morph_target_endpoint(req: MorphTargetRequest):
    if not SAFE_NAME.match(req.name):
        raise HTTPException(400, "Name must be alphanumeric + underscore only")
    try:
        spec = build_morph_target(req.name, req.source_a, req.key_a, req.source_b, req.key_b)
        corners = compile_body(spec)
        body = Body(name=req.name, corners=corners, boost=spec.boost)
        return json.loads(body.to_json())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/composite-target")
def composite_target_endpoint(req: CompositeTargetRequest):
    if not SAFE_NAME.match(req.name):
        raise HTTPException(400, "Name must be alphanumeric + underscore only")
    try:
        spec = build_composite_target(req.name, req.slots)
        corners = compile_body(spec)
        body = Body(name=req.name, corners=corners, boost=spec.boost)
        return json.loads(body.to_json())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/analyze")
def analyze_endpoint(req: AnalyzeRequest):
    body = _load_body(req.body)
    return body_profile(body)


_SUGGEST_PAIRS = [
    # Cross-source morphs — maximal timbral contrast
    ("vowel", "ee", "nasal", "nasal_m", "bright vowel to nasal — F2 collision with anti-formant"),
    ("vowel", "ah", "bell", "Freiburg Hosanna", "open vowel to bell partials — formant-to-harmonic transition"),
    ("vowel", "oo", "electronic", "acid", "dark vowel to acid sweep — low formants meet resonant climb"),
    ("nasal", "nasal_n", "bell", "Stretched Treble", "nasal zeros against inharmonic bell partials"),
    ("vowel", "eh", "electronic", "telephone", "mid vowel to bandpass — spectral narrowing"),
    ("bell", "Berlin Freedom Bell", "vowel", "er", "low bell partials to colored vowel — mass to throat"),
    # Vowel-to-vowel — classic formant traverse
    ("vowel", "ee", "vowel", "oo", "front-to-back vowel — maximum F2 migration"),
    ("vowel", "ae", "vowel", "oo", "open-to-closed — F1 drops, F2 shifts"),
    ("vowel", "ah", "vowel", "ee", "open-back to closed-front — full vowel space diagonal"),
    ("vowel", "schwa", "vowel", "ih", "neutral to bright — subtle formant tightening"),
    # Nasal transitions
    ("vowel", "ah", "nasal", "nasal_n", "open vowel to uvular nasal — anti-formant carves the spectrum"),
    ("nasal", "nasal_m", "nasal", "nasal_n", "bilabial to uvular — anti-formant frequencies shift"),
    # Bell combinations
    ("bell", "Freiburg Hosanna", "bell", "St Mary le Tower", "two real bells — partial spacing differs"),
    ("electronic", "acid", "bell", "Stretched Treble", "sweep meets inharmonic partials"),
]


@app.post("/suggest")
def suggest_endpoint():
    """Suggest an interesting morph combination.

    Uses OpenRouter LLM if OPENROUTER_API_KEY is set, otherwise picks
    from curated cross-source pairs with acoustic rationale.
    """
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        return _suggest_via_openrouter(openrouter_key)
    # Smart random from curated pairs
    sa, ka, sb, kb, rationale = random.choice(_SUGGEST_PAIRS)
    return {"source_a": sa, "key_a": ka, "source_b": sb, "key_b": kb, "rationale": rationale}


def _suggest_via_openrouter(api_key: str) -> dict:
    import httpx

    available = {
        "vowels": get_vowel_keys(),
        "nasals": get_nasal_keys(),
        "bells": get_bell_names(),
        "electronic": get_electronic_keys(),
    }
    prompt = (
        "You are a Z-plane filter body designer. Pick two sources to morph between.\n"
        f"Available: {json.dumps(available)}\n"
        "Source types: vowel, nasal, bell, electronic.\n"
        "Pick a pair that creates interesting spectral motion — "
        "formant transitions, pole-zero crossings, timbral contrast.\n"
        "Respond ONLY with JSON: "
        '{"source_a":"...","key_a":"...","source_b":"...","key_b":"...","rationale":"one sentence"}'
    )

    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "openai/gpt-4o",
            "max_tokens": 200,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=15.0,
    )
    if resp.status_code != 200:
        raise HTTPException(502, f"OpenRouter error: {resp.status_code}")
    text = resp.json()["choices"][0]["message"]["content"].strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        raise HTTPException(502, f"LLM returned unparseable response: {text}")
    return json.loads(text[start:end])


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
