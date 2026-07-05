import os, sys
sys.path.insert(0, os.getcwd())
from tools.stage_features import load_body, body_features

HEDZ = os.path.join("ref", "p2k_variants", "P2k_013_talking_hedz")
LPF = os.path.join("ref", "p2k_variants", "P2k_033_classic_4_lpf")


def test_hedz_stage6_is_unit_zero_at_all_corners():
    lanes = body_features(load_body(HEDZ))
    assert len(lanes) == 6
    lane6 = lanes[5]
    assert all(c["zr1"] for c in lane6["corners"]), "Hedz stage 6 = foundation (OBSERVED 2026-07-05)"


def test_utility_lpf_has_no_foundation_lane():
    lanes = body_features(load_body(LPF))
    assert not any(all(c["zr1"] for c in l["corners"]) for l in lanes)


def test_lane_features_shape():
    lanes = body_features(load_body(HEDZ))
    l = lanes[0]
    assert set(l) >= {"corners", "pole_travel_oct", "zero_travel_oct", "max_dc", "q_pole_df", "q_pole_dr"}
    c = l["corners"][0]
    assert set(c) >= {"poles", "zeros", "dc", "flat", "zr1", "has_zero"}
