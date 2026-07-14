"""Read E-MU .ebl sample blocks (the SamplePool inside an .exb bank).

Format, from the bytes:
    FORM <be32 size> 'E5B0'
      'TOC2' <be32 size> ...
      'E5S1' <be32 size>  <- the sample block
Inside E5S1: a small header (flags, UTF-16LE name, params), then 16-bit LE PCM.

The PCM offset is not announced anywhere we can trust, so it is FOUND: walk the
candidate offsets and take the one whose int16 reading looks like audio (high lag-1
autocorrelation, low zero-crossing rate). Junk/params score near zero; audio scores
~0.99. Verified against the whole pool by extract_all()'s reject count.

E-MU hardware runs at 39062.5 Hz — the SAME rate as the stage law's AUTHORING_SR —
so these samples are the one source that needs NO resampling to fit a body.
"""

import struct
import numpy as np

EMU_SR = 39_062.5


def _chunks(buf, off, end):
    while off + 8 <= end:
        cid = buf[off:off + 4]
        sz = struct.unpack(">I", buf[off + 4:off + 8])[0]
        yield cid, off + 8, sz
        off += 8 + sz + (sz & 1)


def _score(x):
    """Does this read as audio? lag-1 autocorrelation of a slice."""
    if len(x) < 512 or x.std() < 1.0:
        return -1.0
    s = x[:8192].astype(np.float64)
    return float(np.corrcoef(s[:-1], s[1:])[0, 1])


def read_ebl(path):
    """-> (name, float32 mono in [-1,1], sample_rate). Raises on a non-sample block."""
    b = path.read_bytes() if hasattr(path, "read_bytes") else open(path, "rb").read()
    if b[:4] != b"FORM":
        raise ValueError("not an IFF FORM")
    form_sz = struct.unpack(">I", b[4:8])[0]

    body = None
    for cid, o, sz in _chunks(b, 12, min(len(b), 8 + form_sz)):
        if cid == b"E5S1":
            body = b[o:o + sz]
            break
    if body is None:
        raise ValueError("no E5S1 sample chunk")

    # UTF-16LE name sits just after a small flag field.
    name = body[4:4 + 64].decode("utf-16-le", "replace").split("\x00")[0].lstrip("\x02").strip()

    # Find where the PCM starts: the first offset that reads as audio and stays audio.
    best, best_s = None, -2.0
    for hdr in range(120, 260, 2):
        n = (len(body) - hdr) // 2 * 2
        if n < 2048:
            break
        s = _score(np.frombuffer(body[hdr:hdr + n], dtype="<i2"))
        if s > best_s:
            best, best_s = hdr, s
    if best is None or best_s < 0.5:
        raise ValueError(f"no PCM found (best autocorr {best_s:.2f})")

    n = (len(body) - best) // 2 * 2
    pcm = np.frombuffer(body[best:best + n], dtype="<i2").astype(np.float32) / 32768.0
    return name, pcm, EMU_SR


def extract_all(pool_dir, limit=None):
    """Yield (path, name, samples, sr) for every readable .ebl in a SamplePool."""
    from pathlib import Path
    files = sorted(Path(pool_dir).glob("*.ebl"))
    if limit:
        files = files[:limit]
    for f in files:
        try:
            name, x, sr = read_ebl(f)
        except Exception as e:              # a few blocks are not samples
            continue
        yield f, name, x, sr


if __name__ == "__main__":
    import sys
    from pathlib import Path
    from scipy.io import wavfile

    pool = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    ok = bad = 0
    for f, name, x, sr in extract_all(pool, limit=int(sys.argv[3]) if len(sys.argv) > 3 else None):
        ok += 1
        dur = len(x) / sr
        print(f"{f.name:22s} {name[:28]:28s} {len(x):8d} samp  {dur:6.2f}s  peak {np.abs(x).max():.3f}")
        if out:
            out.mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or f.stem
            wavfile.write(out / f"{f.stem}_{safe}.wav", int(sr), (x * 32767).astype(np.int16))
    print(f"\nread {ok} sample blocks @ {EMU_SR} Hz")
