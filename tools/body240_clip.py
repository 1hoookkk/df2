"""body240 <-> copy-pasteable clip string (Tyson 2026-07-12: "the body240 format
needs to be copy pasteable").

Format:  TRENCH1.<base64url(240 bytes, no padding)>.<crc32 hex8>
~330 chars — fits in a Discord message, a YouTube description, a QR code.

Usage:
  python tools/body240_clip.py encode path/to/body.body240
  python tools/body240_clip.py decode "TRENCH1...." out.body240
  python tools/body240_clip.py selftest
"""
from __future__ import annotations
import base64
import sys
import zlib

MAGIC = "TRENCH1"
BODY_BYTES = 240


def encode_clip(body: bytes) -> str:
    if len(body) != BODY_BYTES:
        raise ValueError(f"body must be exactly {BODY_BYTES} bytes, got {len(body)}")
    b64 = base64.urlsafe_b64encode(body).decode().rstrip("=")
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return f"{MAGIC}.{b64}.{crc:08x}"


def decode_clip(clip: str) -> bytes:
    clip = clip.strip().strip('"').strip("'")
    parts = clip.split(".")
    if len(parts) != 3 or parts[0] != MAGIC:
        raise ValueError("not a TRENCH1 clip (expected TRENCH1.<data>.<crc>)")
    b64 = parts[1] + "=" * (-len(parts[1]) % 4)
    body = base64.urlsafe_b64decode(b64)
    if len(body) != BODY_BYTES:
        raise ValueError(f"decoded {len(body)} bytes, expected {BODY_BYTES}")
    crc = zlib.crc32(body) & 0xFFFFFFFF
    if f"{crc:08x}" != parts[2].lower():
        raise ValueError("checksum mismatch - clip is corrupted or truncated")
    return body


def _selftest() -> None:
    import os
    body = os.urandom(BODY_BYTES)
    clip = encode_clip(body)
    assert decode_clip(clip) == body
    assert len(clip) < 340, len(clip)
    for broken in (clip[:-1], clip.replace(".", "!", 1), "TRENCH1.x.00000000"):
        try:
            decode_clip(broken)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted broken clip: {broken[:40]}")
    print(f"selftest ok - clip length {len(clip)}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "selftest":
        _selftest()
    elif len(sys.argv) >= 3 and sys.argv[1] == "encode":
        print(encode_clip(open(sys.argv[2], "rb").read()))
    elif len(sys.argv) >= 4 and sys.argv[1] == "decode":
        open(sys.argv[3], "wb").write(decode_clip(sys.argv[2]))
        print(f"wrote {sys.argv[3]}")
    else:
        print(__doc__)
