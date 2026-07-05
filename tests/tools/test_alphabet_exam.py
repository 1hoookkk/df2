import os, sys
sys.path.insert(0, os.getcwd())
from tools.alphabet_exam import sample_lane, respell_roundtrip


def test_foundation_sample_roundtrips():
    import json
    doc = json.load(open(os.path.join("desk", "letters.json"), encoding="utf-8"))
    lane = sample_lane("FOUNDATION", doc["letters"]["FOUNDATION"], seed=7)
    from tools.alphabet_trace import classify_lane
    assert classify_lane(lane) == "FOUNDATION"


def test_respell_rate_high():
    rate, per_letter = respell_roundtrip(seed=11, k=24)
    assert rate >= 0.9, f"round-trip {rate:.2f}, per-letter {per_letter}"
