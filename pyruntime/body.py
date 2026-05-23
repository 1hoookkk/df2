"""Body: named 4-corner filter body with JSON persistence.

Transcribed from runtime/src/body.rs.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from pyruntime.corner import CornerArray, CornerState, CornerName
from pyruntime.preset_schema import LegacyImportMode, PresetSchema
from pyruntime.stage_params import StageParams
from pyruntime.constants import NUM_BODY_STAGES

VAULT_DIR = Path(__file__).parent.parent / "vault"


class Body:
    def __init__(
        self,
        name: str,
        corners: CornerArray,
        boost: float = 4.0,
        preset_schema: PresetSchema | None = None,
        filter_type: int | None = None,
    ):
        self.name = name
        self.corners = corners
        self.boost = boost
        self.preset_schema = preset_schema
        self.filter_type = filter_type

    def to_json(self) -> str:
        """Serialize to keyframe JSON (plugin-loadable format)."""
        corner_morph_q = {
            CornerName.A: (0.0, 0.0),
            CornerName.B: (0.0, 1.0),
            CornerName.C: (1.0, 0.0),
            CornerName.D: (1.0, 1.0),
        }
        keyframes = []
        for cn in CornerName:
            c = self.corners.corner(cn)
            morph, q = corner_morph_q[cn]
            stages = []
            for s in c.stages:
                stages.append({
                    "a1": s.a1,
                    "r": s.r,
                    "val1": s.val1,
                    "val2": s.val2,
                    "val3": s.val3,
                    "flag": 1,
                })
            keyframes.append({
                "label": cn.json_key(),
                "morph": morph,
                "q": q,
                "boost": self.boost,
                "stages": stages,
            })

        payload = {
            "keyframes": keyframes,
            "name": self.name,
            "sampleRate": 39062.5,
            "stages": NUM_BODY_STAGES,
        }
        if self.filter_type is not None:
            payload["filterType"] = int(self.filter_type)
        if self.preset_schema is not None:
            payload["presetSchema"] = self.preset_schema.to_dict()
        return json.dumps(payload, indent=2)

    def to_compiled_json(self, provenance: str = "pyruntime") -> str:
        """Serialize to compiled-v1 JSON (plugin-loadable format).

        Encodes raw StageParams to kernel-form EncodedCoeffs and produces
        the compiled-v1 format required by trench-core BakedCartridge::from_json().
        """
        PASSTHROUGH = {"c0": 2.0, "c1": 1.0, "c2": 2.0, "c3": 1.0, "c4": 1.0}

        keyframes = []
        for cn in CornerName:
            c = self.corners.corner(cn)
            encoded = c.encode()
            stages = []
            for enc in encoded:
                stages.append({
                    "c0": enc.c0,
                    "c1": enc.c1,
                    "c2": enc.c2,
                    "c3": enc.c3,
                    "c4": enc.c4,
                })
            # Pad to NUM_BODY_STAGES with passthrough
            while len(stages) < NUM_BODY_STAGES:
                stages.append(PASSTHROUGH.copy())
            keyframes.append({
                "label": cn.json_key(),
                "boost": self.boost,
                "stages": stages[:NUM_BODY_STAGES],
            })

        payload = {
            "format": "compiled-v1",
            "name": self.name,
            "provenance": provenance,
            "sampleRate": 39062.5,
            "stages": NUM_BODY_STAGES,
            "keyframes": keyframes,
        }
        if self.filter_type is not None:
            payload["filterType"] = int(self.filter_type)
        if self.preset_schema is not None:
            payload["presetSchema"] = self.preset_schema.to_dict()
        return json.dumps(payload, indent=2)

    @classmethod
    def from_json(
        cls,
        path: str,
        legacy_mode: LegacyImportMode = LegacyImportMode.ERROR,
        warnings: list[str] | None = None,
    ) -> Body:
        """Load from a JSON file."""
        with open(path) as f:
            d = json.load(f)
        return cls.from_dict(d, legacy_mode=legacy_mode, warnings=warnings)

    @classmethod
    def from_dict(
        cls,
        d: dict,
        legacy_mode: LegacyImportMode = LegacyImportMode.ERROR,
        warnings: list[str] | None = None,
    ) -> Body:
        """Load from a parsed JSON dict.

        Supports two formats:
        - corners format: {"corners": {"M0_Q0": {"stages": [...]}, ...}}
        - keyframe format: {"keyframes": [{"label": "M0_Q0", "stages": [...]}, ...]}
        """
        name = d.get("name", "Untitled")
        boost = d.get("boost", 4.0)
        filter_type = d.get("filterType")

        if "corners" in d:
            corner_map = _parse_corners_format(d, boost)
        elif "keyframes" in d:
            corner_map = _parse_keyframe_format(d)
        else:
            raise ValueError("Body JSON must have 'corners' or 'keyframes' key")

        corners = CornerArray(
            a=corner_map[CornerName.A],
            b=corner_map[CornerName.B],
            c=corner_map[CornerName.C],
            d=corner_map[CornerName.D],
        )
        preset_schema = None
        if "presetSchema" in d:
            preset_schema = PresetSchema.from_dict(
                d["presetSchema"],
                legacy_mode=legacy_mode,
                warnings=warnings,
            )
        return cls(
            name=name,
            corners=corners,
            boost=boost,
            preset_schema=preset_schema,
            filter_type=filter_type,
        )


def _parse_stages(stage_list: list) -> list:
    stages = []
    for sd in stage_list:
        if "a1" in sd:
            # Raw format: a1, r, val1, val2, val3
            stages.append(StageParams(
                a1=sd["a1"], r=sd["r"], val1=sd["val1"],
                val2=sd["val2"], val3=sd["val3"],
            ))
        elif "c0" in sd:
            # Compiled format: c0..c4. Decode to raw StageParams.
            c0, c1, c2, c3, c4 = sd["c0"], sd["c1"], sd["c2"], sd["c3"], sd["c4"]
            a1 = c2 - 2.0
            r_sq = 1.0 - c3
            import math
            r = math.sqrt(r_sq) if r_sq > 0 else 0.0
            b0 = c4
            b1 = (c0 - 2.0) * c4
            b2 = (1.0 - c1) * c4
            val1 = b0 - 1.0
            val2 = b1 - a1 if abs(b0) > 1e-12 else 0.0
            val3 = r * r - b2 if abs(b0) > 1e-12 else 0.0
            stages.append(StageParams(a1=a1, r=r, val1=val1, val2=val2, val3=val3))
        else:
            stages.append(StageParams.passthrough())
    return stages


def _parse_corners_format(d: dict, boost: float) -> dict:
    corner_map = {}
    for cn in CornerName:
        corner_data = d["corners"][cn.json_key()]
        corner_map[cn] = CornerState(stages=_parse_stages(corner_data["stages"]), boost=boost)
    return corner_map


def _parse_keyframe_format(d: dict) -> dict:
    """Parse vault keyframe format: list of {label, morph, q, boost, stages}."""
    label_to_corner = {
        "M0_Q0": CornerName.A,
        "M0_Q100": CornerName.B,
        "M100_Q0": CornerName.C,
        "M100_Q100": CornerName.D,
    }
    corner_map = {}
    for kf in d["keyframes"]:
        label = kf["label"]
        cn = label_to_corner.get(label)
        if cn is None:
            continue
        corner_map[cn] = CornerState(
            stages=_parse_stages(kf["stages"]),
            boost=kf.get("boost", 4.0),
        )
    if len(corner_map) != 4:
        raise ValueError(f"Expected 4 keyframe corners, got {len(corner_map)}")
    return corner_map


def list_vault_bodies() -> list[str]:
    """List body names available in the vault directory."""
    if not VAULT_DIR.is_dir():
        return []
    return sorted(
        f.stem for f in VAULT_DIR.glob("*.json")
    )


def load_vault_body(name: str) -> Body:
    """Load a body from the vault by name."""
    path = VAULT_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"No vault body named '{name}'")
    return Body.from_json(str(path))
