"""Post-compose validation. Hidden machine — not user-facing.

Transcribed from runtime/src/validator.rs.
"""
import math
from dataclasses import dataclass
from pyruntime.corner import CornerArray, CornerName

CROWDING_THRESHOLD_ST = 4.0


@dataclass
class Issue:
    kind: str       # "crowding", "regime", "degenerate"
    severity: str   # "warning", "error"
    message: str


def validate(corners: CornerArray) -> list[Issue]:
    """Run all validation checks. Returns issues found."""
    issues = []
    _check_distinct_corners(corners, issues)
    _check_regime_bounds(corners, issues)
    _check_crowding(corners, issues)
    return issues


def _check_distinct_corners(corners: CornerArray, issues: list[Issue]):
    """Check that not all 4 corners are identical (degenerate surface)."""
    names = list(CornerName)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            c1 = corners.corner(names[i])
            c2 = corners.corner(names[j])
            max_diff = 0.0
            for s1, s2 in zip(c1.stages, c2.stages):
                max_diff = max(max_diff,
                    abs(s1.a1 - s2.a1),
                    abs(s1.r - s2.r),
                    abs(s1.val1 - s2.val1),
                    abs(s1.val2 - s2.val2),
                    abs(s1.val3 - s2.val3),
                )
            if max_diff < 1e-6:
                issues.append(Issue(
                    kind="degenerate",
                    severity="warning",
                    message=f"Corners {names[i].name} and {names[j].name} are identical",
                ))


def _check_regime_bounds(corners: CornerArray, issues: list[Issue]):
    """Check all parameters within operating regime."""
    for cn in CornerName:
        c = corners.corner(cn)
        for si, s in enumerate(c.stages):
            if s.r >= 1.0:
                issues.append(Issue(
                    kind="regime",
                    severity="error",
                    message=f"Corner {cn.name} stage {si}: r={s.r:.4f} >= 1.0 (unstable)",
                ))
            if s.r < 0.0:
                issues.append(Issue(
                    kind="regime",
                    severity="error",
                    message=f"Corner {cn.name} stage {si}: r={s.r:.4f} < 0 (invalid)",
                ))


def _check_crowding(corners: CornerArray, issues: list[Issue]):
    """Check inter-stage crowding at all 4 corners."""
    for cn in CornerName:
        c = corners.corner(cn)
        freqs = [(i, s.freq_hz()) for i, s in enumerate(c.stages) if s.r > 0.01]
        for i in range(len(freqs)):
            for j in range(i + 1, len(freqs)):
                si, fi = freqs[i]
                sj, fj = freqs[j]
                if fi < 1.0 or fj < 1.0:
                    continue
                dist_st = abs(12.0 * math.log(fi / fj) / math.log(2.0))
                if dist_st < CROWDING_THRESHOLD_ST:
                    issues.append(Issue(
                        kind="crowding",
                        severity="warning",
                        message=f"Corner {cn.name}: stages {si} ({fi:.0f} Hz) and {sj} ({fj:.0f} Hz) are {dist_st:.1f} st apart",
                    ))
