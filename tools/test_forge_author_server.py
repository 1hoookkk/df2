import json
from pathlib import Path

import pytest

import tools.forge_author_server as server


def _lane(index, pole_hz):
    return {
        "role": f"test lane {index}",
        "on": True,
        "pf": float(pole_hz),
        "pfB": float(pole_hz * 1.35),
        "pr": 0.72 + index * 0.025,
        "prHi": 0.88 + index * 0.012,
        "gain": 0.22,
        "zA": {"on": True, "hz": float(pole_hz * 1.8), "depth": 0.55},
        "zB": {"on": True, "hz": float(pole_hz * 0.72), "depth": 0.58},
    }


def test_bake_publishes_plugin_audition_slot(tmp_path, monkeypatch):
    if not server.t.available():
        pytest.skip("trench_core packed probe is unavailable")

    out_root = tmp_path / "sessions"
    audition_dir = tmp_path / "Documents" / "TRENCH"
    audition_json = audition_dir / "authoring_slot.json"
    audition_body = audition_dir / "authoring_slot.body240"
    audition_json.parent.mkdir(parents=True)
    audition_json.write_text('{"name":"previous slot"}', encoding="utf-8")

    monkeypatch.setattr(server, "OUTROOT", out_root)
    monkeypatch.setattr(server, "AUDITION_DIR", audition_dir)
    monkeypatch.setattr(server, "AUDITION_JSON", audition_json)
    monkeypatch.setattr(server, "AUDITION_BODY", audition_body)

    payload = {
        "name": "slot regression",
        "foundation": 270.0,
        "lanes": [_lane(i, hz) for i, hz in enumerate([120, 270, 520, 1100, 2400, 5200])],
    }

    result = server.bake(payload)
    session_dir = Path(result["dir"])
    session_body = session_dir / "body.body240"
    session_cart = session_dir / "cartridge.json"

    assert result["ok"] is True
    assert result["audition"]["json"] == str(audition_json)
    assert result["audition"]["body240"] == str(audition_body)
    assert result["audition"]["body240_bytes"] == 240
    assert session_body.read_bytes() == audition_body.read_bytes()
    assert len(audition_body.read_bytes()) == 240

    slot = json.loads(audition_json.read_text(encoding="utf-8"))
    cart = json.loads(session_cart.read_text(encoding="utf-8"))
    assert slot["name"] == payload["name"]
    assert slot["keyframes"] == cart["keyframes"]
    assert (audition_dir / "authoring_slot.prev.json").read_text(encoding="utf-8") == '{"name":"previous slot"}'

    for artifact in (
        "target.json",
        "fitted_lanes.json",
        "law_source.json",
        "body.body240",
        "cartridge.json",
        "audit.json",
        "score.json",
        "response.png",
        "workbench.html",
    ):
        assert (session_dir / artifact).exists(), artifact
