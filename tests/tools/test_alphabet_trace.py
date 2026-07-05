import os, sys
sys.path.insert(0, os.getcwd())
from tools.stage_features import load_body, body_features
from tools.alphabet_trace import classify_lane

HEDZ = os.path.join("ref", "p2k_variants", "P2k_013_talking_hedz")


def test_hedz_lane6_classifies_foundation():
    lanes = body_features(load_body(HEDZ))
    assert classify_lane(lanes[5]) == "FOUNDATION"


def test_every_musical_lane_gets_a_letter():
    from tools.stage_features import MUSICAL_33
    letters = set()
    for d in MUSICAL_33:
        for l in body_features(load_body(d)):
            name = classify_lane(l)
            assert name in {"FOUNDATION", "PAD", "REALROOT", "RESON", "CANYON", "SCOOP", "AIRCUT", "CROWN"}
            letters.add(name)
    assert "FOUNDATION" in letters and "CANYON" in letters
