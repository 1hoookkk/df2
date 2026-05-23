"""Designer compiler paths for heritage XML and direct four-corner authoring.

Two distinct paths live here:

1. Heritage XML import:
   MorphDesigner XML is morph-only, so the Q axis is historically collapsed.
2. Direct designer authoring:
   The Python workbench authors all four corners independently so MORPH and Q
   both change audible state.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from pyruntime.body import Body
from pyruntime.constants import NUM_BODY_STAGES, SR, TWO_PI
from pyruntime.corner import CornerArray, CornerName, CornerState
from pyruntime.encode import EncodedCoeffs
from pyruntime.heritage_coeffs import type1_compile, type2_compile, type3_compile
from pyruntime.stage_params import StageParams
from pyruntime.zero_law import ContourFamily


PASSTHROUGH_ENC = EncodedCoeffs(c0=2.0, c1=1.0, c2=2.0, c3=1.0, c4=1.0)
CORNER_ORDER = (
    CornerName.A,
    CornerName.B,
    CornerName.C,
    CornerName.D,
)

Q_RADIUS_LO = 0.70
Q_RADIUS_HI = 0.965


def q_to_radius(q: float) -> float:
    return Q_RADIUS_LO + q * (Q_RADIUS_HI - Q_RADIUS_LO)


@dataclass
class DesignerSection:
    """One MorphDesigner XML section with morph endpoints only."""

    type: int
    low_freq: int
    low_gain: int
    high_freq: int
    high_gain: int

    def is_bypass(self) -> bool:
        return self.type == 0

    def is_zeroed(self) -> bool:
        return (
            self.type == 0
            and self.low_freq == 0
            and self.low_gain == 0
            and self.high_freq == 0
            and self.high_gain == 0
        )


@dataclass
class DesignerCell:
    """One directly authored corner cell."""

    type: int = 0
    freq: int = 0
    gain: int = 0

    def normalized(self) -> DesignerCell:
        return DesignerCell(
            type=max(0, min(3, int(self.type))),
            freq=max(0, min(127, int(self.freq))),
            gain=max(0, min(127, int(self.gain))),
        )


@dataclass
class DesignerTemplate:
    """MorphDesigner XML template."""

    name: str
    sections: list[DesignerSection]
    frequency: float = 0.0
    gain: float = 0.0


@dataclass
class FourCornerDesignerTemplate:
    """Workbench-native four-corner authoring payload."""

    name: str
    corners: dict[CornerName, list[DesignerCell]]


def parse_xml(path: str) -> DesignerTemplate:
    """Parse an E-mu MorphDesigner XML template file."""
    tree = ET.parse(path)
    root = tree.getroot()
    name = root.get("name", Path(path).stem)

    filt = root.find("filter")
    if filt is None:
        raise ValueError(f"No <filter> element in {path}")

    frequency = float(filt.findtext("frequency", "0"))
    gain = float(filt.findtext("gain", "0"))

    sections: list[DesignerSection] = []
    for i in range(1, 7):
        sec = filt.find(f"designer-section[@index='{i}']")
        if sec is None:
            sections.append(DesignerSection(0, 0, 0, 0, 0))
            continue
        sections.append(
            DesignerSection(
                type=int(sec.findtext("type", "0")),
                low_freq=int(sec.findtext("low-freq", "0")),
                low_gain=int(sec.findtext("low-gain", "0")),
                high_freq=int(sec.findtext("high-freq", "0")),
                high_gain=int(sec.findtext("high-gain", "0")),
            )
        )

    return DesignerTemplate(
        name=name,
        sections=sections,
        frequency=frequency,
        gain=gain,
    )


def _compile_packed(type_id: int, freq_packed: int, gain_packed: int, shift: int = 0) -> tuple[StageParams, EncodedCoeffs]:
    if type_id <= 0:
        return StageParams.passthrough(), PASSTHROUGH_ENC
    if type_id == 1:
        return type1_compile(freq_packed, gain_packed, global_shift=shift)
    if type_id == 2:
        return type2_compile(freq_packed, gain_packed, global_shift=shift)
    if type_id == 3:
        return type3_compile(freq_packed, gain_packed, shift=shift)
    return type1_compile(freq_packed, gain_packed, global_shift=shift)


def _compile_section(sec: DesignerSection, morph: float, shift: int = 0) -> tuple[StageParams, EncodedCoeffs]:
    """Compile one XML section at a morph endpoint."""
    if sec.is_bypass() or sec.is_zeroed():
        return StageParams.passthrough(), PASSTHROUGH_ENC

    freq_packed = int(round(sec.low_freq + morph * (sec.high_freq - sec.low_freq)))
    gain_packed = int(round(sec.low_gain + morph * (sec.high_gain - sec.low_gain)))
    return _compile_packed(sec.type, freq_packed, gain_packed, shift=shift)


def _compile_corner_cells(cells: list[DesignerCell], boost: float, shift: int = 0) -> CornerState:
    stages: list[StageParams] = []
    pre_encoded: list[EncodedCoeffs] = []

    for cell in cells[:6]:
        normalized = cell.normalized()
        sp, enc = _compile_packed(normalized.type, normalized.freq, normalized.gain, shift=shift)
        stages.append(sp)
        pre_encoded.append(enc)

    while len(stages) < NUM_BODY_STAGES:
        stages.append(StageParams.passthrough())
        pre_encoded.append(PASSTHROUGH_ENC)

    return CornerState(stages=stages, boost=boost, _pre_encoded=pre_encoded)


def compile_designer(template: DesignerTemplate, boost: float = 4.0) -> CornerArray:
    """Compile a historical MorphDesigner template.

    Historical templates are morph-only. Q remains collapsed here by design.
    """
    shift = -32 + int((template.frequency + template.gain) * 63.0)
    morph_corners: list[CornerState] = []
    for morph in (0.0, 1.0):
        stages: list[StageParams] = []
        pre_encoded: list[EncodedCoeffs] = []
        for sec in template.sections[:6]:
            sp, enc = _compile_section(sec, morph, shift=shift)
            stages.append(sp)
            pre_encoded.append(enc)
        while len(stages) < NUM_BODY_STAGES:
            stages.append(StageParams.passthrough())
            pre_encoded.append(PASSTHROUGH_ENC)
        morph_corners.append(CornerState(stages=stages, boost=boost, _pre_encoded=pre_encoded))

    m0_corner = morph_corners[0]
    m100_corner = morph_corners[1]
    return CornerArray(a=m0_corner, b=m0_corner, c=m100_corner, d=m100_corner)


def compile_designer_to_body(template: DesignerTemplate, boost: float = 4.0) -> Body:
    return Body(name=template.name, corners=compile_designer(template, boost), boost=boost)


def make_template(name: str, sections: list[tuple[int, int, int, int, int]]) -> DesignerTemplate:
    designer_sections: list[DesignerSection] = []
    for type_id, low_freq, low_gain, high_freq, high_gain in sections:
        designer_sections.append(
            DesignerSection(
                type=type_id,
                low_freq=low_freq,
                low_gain=low_gain,
                high_freq=high_freq,
                high_gain=high_gain,
            )
        )
    while len(designer_sections) < 6:
        designer_sections.append(DesignerSection(0, 0, 0, 0, 0))
    return DesignerTemplate(name=name, sections=designer_sections)


def make_four_corner_template(
    name: str,
    corners: dict[str, list[dict | DesignerCell]],
) -> FourCornerDesignerTemplate:
    template_corners: dict[CornerName, list[DesignerCell]] = {}
    for corner_name in CORNER_ORDER:
        raw_cells = corners.get(corner_name.json_key(), [])
        parsed: list[DesignerCell] = []
        for cell in raw_cells[:6]:
            if isinstance(cell, DesignerCell):
                parsed.append(cell.normalized())
            else:
                parsed.append(
                    DesignerCell(
                        type=int(cell.get("type", 0)),
                        freq=int(cell.get("freq", 0)),
                        gain=int(cell.get("gain", 0)),
                    ).normalized()
                )
        while len(parsed) < 6:
            parsed.append(DesignerCell())
        template_corners[corner_name] = parsed
    return FourCornerDesignerTemplate(name=name, corners=template_corners)


def legacy_sections_to_four_corner(
    name: str,
    sections: list[tuple[int, int, int, int, int]],
) -> FourCornerDesignerTemplate:
    """Bridge the old 6x5 payload into the new four-corner template.

    This intentionally preserves the legacy collapsed-Q semantics so older callers
    still work while the UI moves to direct four-corner authoring.
    """
    m0_q0: list[DesignerCell] = []
    m100_q0: list[DesignerCell] = []
    for type_id, low_freq, low_gain, high_freq, high_gain in sections[:6]:
        m0_q0.append(DesignerCell(type=type_id, freq=low_freq, gain=low_gain).normalized())
        m100_q0.append(DesignerCell(type=type_id, freq=high_freq, gain=high_gain).normalized())
    while len(m0_q0) < 6:
        m0_q0.append(DesignerCell())
        m100_q0.append(DesignerCell())

    return FourCornerDesignerTemplate(
        name=name,
        corners={
            CornerName.A: m0_q0,
            CornerName.B: [cell.normalized() for cell in m0_q0],
            CornerName.C: m100_q0,
            CornerName.D: [cell.normalized() for cell in m100_q0],
        },
    )


def compile_four_corner_designer(template: FourCornerDesignerTemplate, boost: float = 4.0) -> CornerArray:
    """Compile a workbench-authored four-corner grid to a body surface."""
    compiled = {
        corner_name: _compile_corner_cells(template.corners[corner_name], boost=boost)
        for corner_name in CORNER_ORDER
    }
    return CornerArray(
        a=compiled[CornerName.A],
        b=compiled[CornerName.B],
        c=compiled[CornerName.C],
        d=compiled[CornerName.D],
    )


def compile_four_corner_to_body(template: FourCornerDesignerTemplate, boost: float = 4.0) -> Body:
    return Body(name=template.name, corners=compile_four_corner_designer(template, boost), boost=boost)


@dataclass
class HzEndpoint:
    freq_hz: float
    gain_db: float
    contour: str = "pure"


def _hz_to_stage(ep: HzEndpoint, q: float) -> StageParams:
    radius = q_to_radius(q)
    theta = TWO_PI * ep.freq_hz / SR
    a1 = -2.0 * radius * math.cos(theta)
    val1 = 10.0 ** (max(-24.0, min(24.0, ep.gain_db)) / 20.0) - 1.0

    if ep.contour == "unit_circle":
        family = ContourFamily.UNIT_CIRCLE
        val2, val3 = family.val2_val3(a1, radius)
    else:
        val2, val3 = 0.0, 0.0

    return StageParams(a1=a1, r=radius, val1=val1, val2=val2, val3=val3)


def make_hz_body(
    name: str,
    stages: list[tuple[HzEndpoint, HzEndpoint]],
    boost: float = 4.0,
) -> Body:
    corners: list[CornerState] = []
    for morph, q in ((0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)):
        stage_list: list[StageParams] = []
        for low_ep, high_ep in stages:
            stage_list.append(_hz_to_stage(low_ep if morph < 0.5 else high_ep, q))
        while len(stage_list) < NUM_BODY_STAGES:
            stage_list.append(StageParams.passthrough())
        corners.append(CornerState(stages=stage_list, boost=boost))

    return Body(
        name=name,
        corners=CornerArray(a=corners[0], b=corners[1], c=corners[2], d=corners[3]),
        boost=boost,
    )
