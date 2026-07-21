"""Streaming download with progress bar. Writes chunks to disk as they arrive."""
import hashlib
import sys
import time
from pathlib import Path

import requests

url = sys.argv[1]
out_path = Path(sys.argv[2])
expected_md5 = sys.argv[3] if len(sys.argv) > 3 else None

r = requests.get(url, headers={"User-Agent": "TRENCH/1"}, stream=True, timeout=60)
r.raise_for_status()
total = int(r.headers.get("Content-Length", 0))
print(f"total: {total / 1e6:.0f} MB")

downloaded = 0
start = time.monotonic()
with out_path.open("wb") as f:
    for chunk in r.iter_content(chunk_size=1 << 20):
        f.write(chunk)
        downloaded += len(chunk)
        elapsed = time.monotonic() - start
        rate = downloaded / elapsed / 1e6 if elapsed > 0 else 0
        pct = downloaded / total * 100 if total else 0
        eta = (total - downloaded) / (rate * 1e6) if rate > 0 else 0
        print(f"  {pct:.0f}%  {rate:.1f} MB/s  ETA {eta/60:.0f}m{eta%60:.0f}s", end="\r", flush=True)

print()
if expected_md5:
    actual = hashlib.md5(out_path.read_bytes()).hexdigest()
    print(f"md5: {actual}  (expected: {expected_md5})")
    if actual != expected_md5:
        out_path.unlink()
        raise SystemExit("CHECKSUM MISMATCH")

print(f"done: {out_path}  ({out_path.stat().st_size / 1e6:.0f} MB)")
