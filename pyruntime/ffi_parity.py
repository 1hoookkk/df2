"""FFI parity guard -- proves the shipped trench-core packed math and the
pure-Python reference agree bit-for-bit.

This is the contract behind "one math owner": `packed_interp.py` delegates to
trench-core when the library is loaded, and keeps a pure-Python fallback. They
must be identical, or a tool that runs with the fallback would judge a different
corner than the plugin ships. This script checks every operation that could
possibly differ -- the two codecs (`decode`/`encode`) and the composites built on
them (`interpolate`, `probe`).

Run:  python -m pyruntime.ffi_parity
Exit: 0 if every check is bit-exact, 1 on any mismatch (and 2 if the library
isn't built -- the fallback can't be checked against an owner that isn't there).
"""
from __future__ import annotations

import random
import sys

from pyruntime import packed_interp as pi
from pyruntime import trench_ffi as core

NUM_STAGES = 6
GRID = [i / 8.0 for i in range(9)]  # 0, 0.125, ... 1.0


def _force_py(fn, *args):
    """Call a packed_interp function with delegation disabled (pure-Python)."""
    saved = pi._core
    pi._core = None
    try:
        return fn(*args)
    finally:
        pi._core = saved


def _py_bilinear(cw, m, q):
    out = []
    for si in range(NUM_STAGES):
        a, b, c, d = cw["A"][si], cw["B"][si], cw["C"][si], cw["D"][si]
        ow = tuple(
            _force_py(pi.lerp_u16, _force_py(pi.lerp_u16, a[wi], b[wi], m),
                      _force_py(pi.lerp_u16, c[wi], d[wi], m), q)
            for wi in range(5)
        )
        out.append(_force_py(pi.words_to_coeffs, ow))
    return out


def main() -> int:
    if not core.available():
        print("FFI parity: SKIP -- trench-core library not built "
              "(build with: cargo build --release -p trench-core)")
        return 2
    print(f"FFI parity: lib = {core.lib_path()}")
    rng = random.Random(20260527)
    fails = []

    # 1) decode -- all 65536 words
    dbad = sum(1 for w in range(65536) if core.decode(w) != _force_py(pi.decode, w))
    print(f"  decode (all 65536 words):           {65536 - dbad}/65536 exact")
    if dbad:
        fails.append(f"decode: {dbad} mismatches")

    # 2) encode -- dense fuzz + boundaries + denormal-range stress
    vals = [0.0, 1.0, 1e-9, 0.999999, 0.5, 0.25, 1 / 3, 2 / 3]
    vals += [rng.random() for _ in range(200000)]
    vals += [rng.uniform(0, 0.01) for _ in range(50000)]
    ebad = sum(1 for v in vals if core.encode(v) != _force_py(pi.encode, v))
    print(f"  encode (vs py-ref, {len(vals)} vals):   {len(vals) - ebad}/{len(vals)} exact")
    if ebad:
        fails.append(f"encode: {ebad} mismatches")

    # 3) encode(decode(w)) round-trip -- encode must invert decode on the grid
    rt = sum(1 for w in range(65536) if core.encode(core.decode(w)) != w)
    print(f"  encode(decode(w)) round-trip:       {65536 - rt}/65536 recover")
    if rt:
        fails.append(f"round-trip: {rt} fail")

    # 4) interpolate + probe -- random bodies x Morph/Q grid
    kerr = bqerr = rerr = 0.0
    mask_bad = 0
    npts = 0
    for _ in range(50):
        cw = {k: [tuple(rng.randint(0, 65535) for _ in range(5)) for _ in range(NUM_STAGES)]
              for k in "ABCD"}
        body = core.body_bytes_from_corner_words(cw)
        for m in GRID:
            for q in GRID:
                f_kernel = core.packed_interpolate(body, m, q)
                p_kernel = _py_bilinear(cw, m, q)
                for r1, r2 in zip(f_kernel, p_kernel):
                    for x, y in zip(r1, r2):
                        kerr = max(kerr, abs(x - y))
                fp = core.packed_probe(body, m, q)
                p_bq = [_force_py(pi.kernel_to_biquad, r) for r in p_kernel]
                p_max = 0.0
                p_unstable = p_nonfinite = 0
                for si, s in enumerate(p_bq):
                    if not all(v == v and abs(v) != float("inf") for v in s):
                        p_nonfinite |= (1 << si)
                        continue
                    rr = _force_py(pi._pole_radius, s[3], s[4])
                    if rr != float("inf"):
                        p_max = max(p_max, rr)
                        if rr >= 1.0:
                            p_unstable |= (1 << si)
                for s1, s2 in zip(fp["biquad"], p_bq):
                    for x, y in zip(s1, s2):
                        bqerr = max(bqerr, abs(x - y))
                rerr = max(rerr, abs(fp["max_pole_radius"] - p_max))
                if fp["unstable_mask"] != p_unstable or fp["nonfinite_mask"] != p_nonfinite:
                    mask_bad += 1
                npts += 1
    print(f"  interpolate kernel ({npts} grid pts):  max |diff| = {kerr:.3e}")
    print(f"  probe biquad:                       max |diff| = {bqerr:.3e}")
    print(f"  probe max_radius:                   max |diff| = {rerr:.3e}")
    print(f"  probe stability masks:              {npts - mask_bad}/{npts} exact")
    if kerr:
        fails.append(f"interpolate kernel drift {kerr:.3e}")
    if bqerr:
        fails.append(f"probe biquad drift {bqerr:.3e}")
    if rerr:
        fails.append(f"probe radius drift {rerr:.3e}")
    if mask_bad:
        fails.append(f"probe masks: {mask_bad} mismatches")

    if fails:
        print("FFI parity: FAIL -- " + "; ".join(fails))
        return 1
    print("FFI parity: PASS -- FFI owner and Python reference are bit-identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
