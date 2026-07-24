import pathlib
import hashlib
import struct

bodies_dir = pathlib.Path(r"c:\Users\hooki\df2-workstation\plugin\presets\bodies")
measured_crosses = [
    "glockenspiel_minecave",
    "kalimba_tunnel",
    "steelpan_cymbal",
    "violin_bass",
    "ukulele_ortf",
    "minesite_1way_2way"
]

print("=== Measured Cross Bodies in plugin/presets/bodies/ ===")
for slug in measured_crosses:
    bp = bodies_dir / f"{slug}.body240"
    if bp.exists():
        data = bp.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        print(f"{slug}.body240 ({len(data)} bytes) SHA256: {sha}")
    else:
        print(f"{slug}.body240: NOT FOUND")
