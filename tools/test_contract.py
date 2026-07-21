#!/usr/bin/env python3
"""Contract test: the compiler and the fixture bodies must never drift.

  python -m tools.test_contract

1. fixtures/: every .body240 sha256 must match fixtures/manifest.json (the
   engine-contract vectors are VERBATIM bytes — nothing may rewrite them).
2. golden compile: dev/tmp/bytes_fix/cleanroom_megasweepz.geometry.json must
   compile byte-identical to its checked .body240 (proves body-from-geometry
   is deterministic and the stage law hasn't drifted).
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPILER = ROOT / "target" / "release" / "body-from-geometry.exe"
GOLD_GEO = ROOT / "dev/tmp/bytes_fix/cleanroom_megasweepz.geometry.json"
GOLD_BODY = ROOT / "dev/tmp/bytes_fix/cleanroom_megasweepz.body240"

fails = 0

manifest = json.loads((ROOT / "fixtures/manifest.json").read_text())
for fx in manifest["fixtures"]:
    p = ROOT / fx["path"]
    got = hashlib.sha256(p.read_bytes()).hexdigest()
    ok = got == fx["sha256"]
    print(f"{'PASS' if ok else 'FAIL'}  fixture {fx['name']}")
    fails += 0 if ok else 1

if COMPILER.exists() and GOLD_GEO.exists() and GOLD_BODY.exists():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "gold.body240"
        r = subprocess.run([str(COMPILER), str(GOLD_GEO), str(out)], capture_output=True, text=True)
        ok = r.returncode == 0 and out.read_bytes() == GOLD_BODY.read_bytes()
        print(f"{'PASS' if ok else 'FAIL'}  golden compile (geometry -> byte-identical body240)")
        fails += 0 if ok else 1
else:
    print("SKIP  golden compile (compiler or golden pair missing)")

sys.exit(1 if fails else 0)
