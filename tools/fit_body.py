#!/usr/bin/env python3
"""Fit a whole 240-byte TRENCH body (4 corners) under the STAGE LAW.

  python tools/fit_body.py m0.wav m100.wav --recipe PEAK,PEAK,PEAK,CUT,CUT,HISHELF \
                           --verb BLOOM --out body.json

WHAT THIS RESPECTS (trench-filters/METHOD.md @ 7630976):

  * 8 LETTERS. A lane is a typed shape, not 5 free floats. The optimiser drives a
    PEAK's centre and its zero offset; it cannot turn a PEAK into a shelf to win
    0.2 dB of LSD.
  * A 6-LETTER WORD, WRITTEN TWICE. Lane i at M0 and lane i at M100 are the SAME
    OBJECT — enforced by giving them the SAME LETTER. That, not a summed loss, is
    what couples the frames. (Two disjoint parameter sets under one .backward()
    are just two independent fits: d(loss_M0)/d(m100_params) is identically zero.)
  * NO SORTING, EVER. Stage index is the morph correspondence channel. Reordering
    is free for the frozen curve and fatal for the morph.
  * THE PAIRING IS AUTHORED, not fitted. Talking Hedz moves lane 1 from 891 -> 201 Hz
    while lane 5 goes 199 -> 1789 Hz; lanes cross. A "shortest path" regulariser
    would forbid the real body. The author picks the pairing; the recipe order IS
    the pairing.
  * Q IS A VERB. The Q100 corners are a differentiable function of the Q0 corners,
    not free variables. Gradients DO flow through the verb (no detach) — the whole
    point is that Q0 must choose a pose that still sounds right once bloomed.
  * BASELINE-Q LAW. Q0 poles stay damped (r <= 0.99) so the verb has headroom to
    bloom into. The filter never clips itself; it aims its gain at the saturator.

The morph is a bilinear lerp of the PACKED U16 WORDS (minifloat::interpolate), so
the mid-morph is a deterministic function of the corners — and is therefore
supervised here for level continuity, which is the only place a bad pairing shows
up in a loss at all.

Packing/quantisation is the REAL kernel via ctypes. lerp_u16 is mirrored (there is
no FFI export) and verified against trench-core's own known-answer tests on import.
"""

import argparse, ctypes, json, math, sys
from pathlib import Path

import numpy as np
import torch
from scipy.io import wavfile
from scipy.optimize import minimize
from scipy.signal import get_window

sys.path.insert(0, str(Path(__file__).resolve().parent))
import letters as L

STAGE_SR = 39062.5
N_STAGES = 6
NYQ = STAGE_SR / 2.0
R_REST_MAX = 0.99      # baseline-Q law: damped at rest, headroom to bloom
R_BLOOM_MAX = 0.999

# ------------------------------------------------------------------ the one kernel
_lib = None


def _kernel():
    global _lib
    if _lib is None:
        dll = Path(__file__).resolve().parents[1] / "target" / "release" / "trench_core.dll"
        if not dll.exists():
            sys.exit(f"missing {dll}\n  cargo rustc -p trench-core --release --lib --crate-type cdylib")
        _lib = ctypes.CDLL(str(dll))
        _lib.trench_packed_encode.argtypes = [ctypes.c_double]
        _lib.trench_packed_encode.restype = ctypes.c_uint16
        _lib.trench_packed_decode.argtypes = [ctypes.c_uint16]
        _lib.trench_packed_decode.restype = ctypes.c_double
    return _lib


def enc(v):
    k = _kernel()
    return np.array([k.trench_packed_encode(float(x)) for x in np.ravel(v)],
                    dtype=np.uint16).reshape(np.shape(v))


def dec(w):
    k = _kernel()
    return np.array([k.trench_packed_decode(int(x)) for x in np.ravel(w)],
                    dtype=np.float64).reshape(np.shape(w))


def lerp_u16(a, b, frac):
    """Mirror of minifloat::lerp_u16 — the (int16_t) cast WRAPS the delta before
    adding a; it does NOT clamp (MSVC x86 behaviour). Verified below."""
    a = np.asarray(a, dtype=np.int64)
    b = np.asarray(b, dtype=np.int64)
    diff = (b - a).astype(np.float32)
    delta = (diff * np.float32(frac)).astype(np.int64)         # truncate toward zero
    delta = ((delta + 0x8000) & 0xFFFF) - 0x8000               # wrap to i16
    return ((delta + a) & 0xFFFF).astype(np.uint16)


def _verify_lerp():
    """trench-core's own known-answer tests. If the mirror drifts, stop."""
    assert int(lerp_u16(0x1000, 0x3000, 0.5)) == 0x2000, "lerp_u16 midpoint"
    assert int(lerp_u16(0x1000, 0x8000, 0.0)) == 0x1000, "lerp_u16 frac=0"
    assert int(lerp_u16(0x1000, 0x8000, 1.0)) == 0x8000, "lerp_u16 frac=1"
    assert int(lerp_u16(0x0000, 0xFFFF, 1.0)) == 0xFFFF, "lerp_u16 wrapping delta"
    assert int(lerp_u16(0x4000, 0x4000, 0.25)) == 0x4000, "lerp_u16 a==b"


_verify_lerp()


# ------------------------------------------------------- the authoring geometry
# ROOTS + SCALE. Not the RBJ vocabulary.
#
# CLAUDE.md: "Roots are an authoring coordinate system. Packed words and runtime-decoded
# coefficients are the executable result." The canonical forward path is
# stage_law::words_from_roots, and it is PACKABLE BY CONSTRUCTION:
#     c1 = 1 - rz^2            in [0,1] for rz <= 1
#     c3 = 1 - rp^2            in [0,1] for rp <= 1
#     (c0-c1)/4 = |1 - rz e^{j wz}|^2 / 4   in [0,1]
#     SCALE/4                  in [0,1] for SCALE <= 4
# Every word lands in the encoder's domain without a single clamp.
#
# The RBJ types in compiler::section_biquad are a CONVENIENCE LAYER, not this alphabet.
# Fitting through them was a mistake: measured, 171/840 RBJ cards produce words OUTSIDE
# [0,1] (BANDPASS: 120/120), because RBJ can express geometry the 240-byte format cannot
# hold. The Morph Designer XML types 0-3 (heritage::compile_designer_stage) write words
# directly from freq/gain 0..127 — that grammar is EVIDENCE, not the fitter's type system.
#
# Per stage the five authoring variables, in natural units:
#   p0 = log10(pole Hz)  p1 = pole r  p2 = log10(zero Hz)  p3 = zero r  p4 = SCALE
F_MIN, F_MAX = 30.0, STAGE_SR * 0.49          # == trench-core compiler::FREQ_MAX
LOG_F = (math.log10(F_MIN), math.log10(F_MAX))

R_REST_MAX = 0.99      # baseline-Q law: damped at rest, headroom to bloom
R_BLOOM_MAX = 0.999
SCALE_MAX = 4.0

STAGE_BOUNDS = [LOG_F, (0.0, R_REST_MAX), LOG_F, (0.0, 1.0), (0.02, SCALE_MAX)]


def stage_roots(p):
    """The five controls -> (pole_hz, pole_r, zero_hz, zero_r, scale)."""
    return (torch.pow(10.0, p[0]), p[1], torch.pow(10.0, p[2]), p[3], p[4])


# -------------------------------------------------------------------- the verbs
def apply_verb(roots, verb, vp):
    """Q0 roots -> Q100 roots. A differentiable graph op, NOT free variables.

    No .detach(): the Q100 loss MUST reach the Q0 pose — Q0 has to be a pose that
    still sounds right once bloomed.
    """
    ph, pr, zh, zr, k = roots
    if verb == "BLOOM":
        # MEASURED on Talking Hedz: radii -> ~0.999 while centres essentially hold.
        # MONOTONE BY CONSTRUCTION so the verb cannot invert (an earlier free absolute
        # target let "bloom" pull the poles DOWN, 0.971 -> 0.954).
        pr2 = pr + (R_BLOOM_MAX - pr) * vp[0]              # vp[0] in [0,1]
        return ph * torch.pow(2.0, vp[1]), pr2, zh, zr, k  # vp[1] = centre drift, octaves
    if verb == "SPREAD":
        c = torch.log2(ph).mean()
        return torch.pow(2.0, c + (torch.log2(ph) - c) * vp[0]), pr, zh, zr, k
    raise ValueError(f"unimplemented verb {verb} (BLOOM/SPREAD wired)")


VERB_BOUNDS = {
    "BLOOM":  [(0.0, 1.0), (-0.15, 0.15)],
    "SPREAD": [(1.0, 2.5), (0.0, 0.0)],
}


# ------------------------------------------------- roots -> packed words -> curve
def roots_to_words01(ph, pr, zh, zr, scale):
    """stage_law::words_from_roots, exactly — and packable by construction."""
    wz = 2 * math.pi * zh / STAGE_SR
    wp = 2 * math.pi * ph / STAGE_SR
    c0 = 2.0 - 2.0 * zr * torch.cos(wz)
    c1 = 1.0 - zr ** 2
    c2 = 2.0 - 2.0 * pr * torch.cos(wp)
    c3 = 1.0 - pr ** 2
    return torch.stack([(c0 - c1) / 4.0, c1, (c2 - c3) / 4.0, c3, scale / 4.0], dim=-1)


def ste_pack(v01):
    """Straight-through the REAL minifloat: forward = what the runtime will hold.

    The clip to [0,1] is the ENCODER'S domain, not a convenience: a word outside it
    cannot be represented at all. Silently clipping it corrupts the biquad, so the
    fit must be KEPT inside the representable set instead (see unpackable() below) --
    not quietly mangled after the fact."""
    q = torch.tensor(dec(enc(v01.detach().numpy().clip(0.0, 1.0))), dtype=torch.float64)
    return v01 + (q - v01).detach()


def unpackable(v01):
    """How far the words stray outside the encoder's [0,1] domain.

    MEASURED: 171 of 840 sampled typed cards land outside it -- and BANDPASS is
    120/120, i.e. a bandpass CANNOT be packed into a 240-byte body at any setting.
    That is precisely why METHOD.md's alphabet has eight letters and none of them is
    a bandpass: the packable alphabet is a SUBSET of the RBJ vocabulary. The format
    decides the alphabet, not the other way round."""
    return (torch.relu(-v01) + torch.relu(v01 - 1.0)).sum()


def words01_to_db(v, w):
    """The decode trench-core does, then the SERIAL CASCADE (magnitudes multiply;
    summing dB is that product, since log(ab) = log a + log b)."""
    zm, zrs, pm, prs, s01 = (v[..., i:i + 1] for i in range(5))
    qz, pz = 1.0 - zrs, (4.0 * zm + zrs) - 2.0
    qp, pp = 1.0 - prs, (4.0 * pm + prs) - 2.0
    k = 4.0 * s01
    z1 = torch.exp(-1j * w)
    z2 = z1 * z1
    h = (k * (1.0 + pz * z1 + qz * z2)) / (1.0 + pp * z1 + qp * z2 + 1e-12)
    return 20.0 * torch.log10(h.abs() + 1e-9).sum(dim=-2)


# ------------------------------------------------------------------- the target
def envelope(path, n_bins=512, n_fft=4096):
    sr, x = wavfile.read(path)
    x = x.astype(np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    x /= (np.abs(x).max() + 1e-12)
    win = get_window("hann", n_fft)
    fr = [x[i:i + n_fft] * win for i in range(0, max(1, len(x) - n_fft), n_fft // 2)]
    if not fr:
        fr = [np.pad(x, (0, n_fft))[:n_fft] * win]
    psd = np.mean([np.abs(np.fft.rfft(f)) ** 2 for f in fr], axis=0)
    hz = np.fft.rfftfreq(n_fft, 1.0 / sr)
    grid = np.geomspace(20.0, min(sr / 2, NYQ) - 1.0, n_bins)
    db = 10 * np.log10(np.interp(grid, hz, psd) + 1e-12)
    k = 21
    db = np.convolve(np.pad(db, (k // 2, k // 2), mode="edge"), np.ones(k) / k, mode="valid")
    return grid, db - db.max()


def weight_mask(grid, lo=300.0, hi=4000.0, focus=6.0, air=0.25):
    """Gemini's one genuinely good idea: tell the optimiser where the character is,
    so it does not burn 3 of its 6 lanes modelling room rumble."""
    w = np.ones_like(grid) * air
    w[(grid >= lo) & (grid <= hi)] = focus
    w[(grid > hi) & (grid < 12000.0)] = 1.0
    return w / w.mean()


# ---------------------------------------------------------------------- the fit
class Body(torch.nn.Module):
    """The 4 corners as ONE graph. Parameters are the two AUTHORED frames (M0, M100)
    at Q0; the Q100 corners are made by the verb and are never free variables."""

    def __init__(self, verb, seed=0):
        super().__init__()
        self.verb = verb
        rng = np.random.default_rng(seed)
        b = self.bounds(verb)
        x0 = np.array([rng.uniform(lo, hi) if hi > lo else lo for lo, hi in b])
        i = 0
        self.m0 = torch.nn.Parameter(torch.tensor(x0[i:i + N_STAGES * 5].reshape(N_STAGES, 5))); i += N_STAGES * 5
        self.m100 = torch.nn.Parameter(torch.tensor(x0[i:i + N_STAGES * 5].reshape(N_STAGES, 5))); i += N_STAGES * 5
        self.vp = torch.nn.Parameter(torch.tensor(x0[i:i + 2]))

    @staticmethod
    def bounds(verb):
        b = []
        for _ in range(2):                                # the M0 frame, then M100
            for _ in range(N_STAGES):
                b += STAGE_BOUNDS
        b += VERB_BOUNDS[verb]
        return b

    def frame_words01(self, params, bloom):
        rows = []
        for i in range(N_STAGES):
            r = stage_roots(params[i])
            if bloom:
                r = apply_verb(r, self.verb, self.vp)
            rows.append(roots_to_words01(*r))
        return torch.stack(rows, dim=0)

    def corners01(self):
        return torch.stack([
            self.frame_words01(self.m0, False),           # M0_Q0
            self.frame_words01(self.m100, False),         # M100_Q0
            self.frame_words01(self.m0, True),            # M0_Q100
            self.frame_words01(self.m100, True),          # M100_Q100
        ], dim=0)


def bilinear01(corners_q, morph, q):
    """The runtime morph: bilinear in PACKED space, morph first then Q.

    Done on the already-quantised word values — lerping decoded reals would be a
    different filter (the whole Rossum point is that you interpolate the ENCODED
    values and decode after)."""
    a, b, c, d = corners_q[0], corners_q[1], corners_q[2], corners_q[3]
    e0 = a + (b - a) * morph
    e1 = c + (d - c) * morph
    return e0 + (e1 - e0) * q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("m0_wav")
    ap.add_argument("m100_wav")
    ap.add_argument("--verb", default="BLOOM")
    ap.add_argument("--iters", type=int, default=400)
    ap.add_argument("--restarts", type=int, default=4)
    ap.add_argument("--out", default="body.json")
    a = ap.parse_args()


    grid, t0 = envelope(a.m0_wav)
    _, t100 = envelope(a.m100_wav)
    w = torch.tensor(2 * math.pi * grid / STAGE_SR, dtype=torch.float64).reshape(-1, 1, 1)
    w = w.permute(1, 2, 0)                                    # broadcast over (stage, freq)
    wt = torch.tensor(weight_mask(grid), dtype=torch.float64)
    T0 = torch.tensor(t0, dtype=torch.float64)
    T100 = torch.tensor(t100, dtype=torch.float64)

    def wlsd(h, t):
        return torch.sum(wt * ((h - h.mean()) - (t - t.mean())) ** 2) / wt.sum()

    def losses(body):
        cq = ste_pack(body.corners01())                       # (4,6,5), packed
        h0 = words01_to_db(bilinear01(cq, 0.0, 0.0), w)
        h1 = words01_to_db(bilinear01(cq, 1.0, 0.0), w)
        fit_loss = wlsd(h0, T0) + wlsd(h1, T100)
        # Keep every one of the 4 corners inside the encoder's domain. Without this the
        # optimiser wanders into unpackable cards and the clip silently rewrites them.
        packable = 200.0 * unpackable(body.corners01())

        # MID-MORPH SUPERVISION. The corners-only loss cannot see the pairing at
        # all — the lane choreography only becomes visible BETWEEN the corners.
        # The runtime gets there by lerping packed words, which can collapse the
        # level mid-sweep ("users hate this"). So walk the morph and hold the
        # cascade's energy on the line between the endpoints.
        e0, e1 = h0.mean(), h1.mean()
        mid = sum((words01_to_db(bilinear01(cq, m, 0.0), w).mean()
                   - (e0 + (e1 - e0) * m)) ** 2 for m in (0.25, 0.5, 0.75))
        return fit_loss, fit_loss + 0.05 * mid + packable

    def run(seed):
        """L-BFGS-B on the flattened graph. torch gives the exact gradient (through
        the letters, the verb, and the straight-through packing); scipy gives the
        quasi-Newton step. Adam had to be told a learning rate and then crawled."""
        body = Body(a.verb, seed=seed)
        shapes = [(n, p.shape, p.numel()) for n, p in body.named_parameters()]

        def setx(x):
            i = 0
            for n, shp, cnt in shapes:
                getattr(body, n).data = torch.tensor(
                    x[i:i + cnt].reshape(shp), dtype=torch.float64)
                i += cnt

        def obj(x):
            setx(x)
            for p in body.parameters():
                p.grad = None
                p.requires_grad_(True)
            _, total = losses(body)
            total.backward()
            g = np.concatenate([getattr(body, n).grad.numpy().ravel() for n, _, _ in shapes])
            return total.item(), g

        x0 = np.concatenate([p.detach().numpy().ravel() for p in body.parameters()])
        # The REAL bounds on the REAL variables — Hz, radius, octaves, SCALE.
        res = minimize(obj, x0, jac=True, method="L-BFGS-B",
                       bounds=Body.bounds(a.verb),
                       options=dict(maxiter=a.iters, maxfun=a.iters * 2, ftol=1e-12))
        setx(res.x)
        with torch.no_grad():
            fit_loss, _ = losses(body)
        return body, fit_loss.item(), res.nfev

    best, best_loss = None, float("inf")
    for seed in range(a.restarts):
        body, f, nfev = run(seed)
        print(f"  restart {seed}: weighted LSD^2 {f:7.3f}   {nfev} evals")
        if f < best_loss:
            best, best_loss = body, f

    with torch.no_grad():
        cq = ste_pack(best.corners01()).numpy().clip(0.0, 1.0)
    words = enc(cq)                                           # (4,6,5) real u16

    # Report what the runtime will actually hold, decoded back out.
    print(f"\nbest weighted LSD^2 {best_loss:.3f}   verb {a.verb}")
    print("\npole Hz / r per lane per corner (decoded from the packed words):")
    names = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
    print("lane | " + " | ".join(f"{n:^16s}" for n in names))
    for si in range(N_STAGES):
        cells = []
        for ci in range(4):
            d = dec(words[ci][si])
            qp, pp = 1 - d[3], (4 * d[2] + d[3]) - 2
            r = np.roots([1, pp, qp])
            cells.append(f"{abs(np.angle(r[0])) * STAGE_SR / (2 * np.pi):7.0f}Hz r{np.abs(r).max():.3f}")
        print(f" {si}   | " + " | ".join(f"{c:^16s}" for c in cells))

    stable = True
    for ci in range(4):
        for si in range(N_STAGES):
            d = dec(words[ci][si])
            qp, pp = 1 - d[3], (4 * d[2] + d[3]) - 2
            stable &= np.abs(np.roots([1, pp, qp])).max() < 1.0
    print(f"\nALL 24 STAGES STABLE: {stable}")

    json.dump(dict(verb=a.verb, stage_sr=STAGE_SR,
                   corners=[[[int(x) for x in words[c][s]] for s in range(N_STAGES)]
                            for c in range(4)]),
              open(a.out, "w"), indent=2)
    print(f"240 bytes of words -> {a.out}")


if __name__ == "__main__":
    main()
