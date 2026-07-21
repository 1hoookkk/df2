#!/usr/bin/env python3
"""prove-master-body — reproducible packed-runtime proof for one compiled body.

Consumes one artifact directory holding a compiled candidate:

    NAME.body240                    (required — the 240-byte packed body)
    NAME.geometry.json              (optional — compiler input, for quantization diffs)
    NAME.registered_lanes.json      (optional — lane names)
    master_body.manifest.json       (optional — declared crossing pairs)

and emits, next to them:

    NAME.runtime_proof.json         (all stats + assertions; the tracked record)
    NAME.packed_runtime_response.png
    NAME.pole_lane_crossings.png
    NAME.body_solo_morph_q.float32.wav
    NAME.decoded.geometry.json      (filter_cli decode of the body)

Everything runtime is trench-core through the shipped DLL (direct ctypes, the
same binding pattern as tools/audition_raw_vs_packed.py and tools/corner_bench.py):

  - certification: trench_certify_body (res x res sampled grid) plus a per-point
    trench_packed_probe sweep so individual failing rows are named, not just the
    first. Sampled certification, never a continuum proof.
  - round trip: trench_pack_body_from_corner_words(words(body)) == body bytes.
  - response/lane plots: packed/runtime-decoded DF2T rows (trench_packed_probe).
  - BODY SOLO audio: the real engine (input None, spatial Off, AGC/DC-block/
    saturation off, drive 0, amount 1) — no per-render normalization, no AGC.

This tool never fits, packs, sorts, or repairs. It proves or refuses.

    python -m tools.prove_master_body dev/tmp/.../NAME_artifact_dir
    python -m tools.prove_master_body DIR --grid 65 --seed 20260720 --force

Exit code 0 only when every assertion passes.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DLL = ROOT / "target" / "release" / "trench_core.dll"

BODY_BYTES = 240
NUM_STAGES = 6
NUM_COEFFS = 5
RUNTIME_SR = 39062.5
AUDIO_SR = 44100
AUDIO_SECONDS = 6.0
AUDIO_BLOCK = 512
INPUT_RMS = 0.25
RESPONSE_YLIM = (-100.0, 80.0)
RESPONSE_POINTS = (
    ("M0_Q0", 0.0, 0.0),
    ("M100_Q0", 1.0, 0.0),
    ("M0_Q100", 0.0, 1.0),
    ("M100_Q100", 1.0, 1.0),
    ("MID_Q0", 0.5, 0.0),
    ("MID_Q100", 0.5, 1.0),
)
CROSS_SAMPLES = 401


class ProofError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value, force: bool):
    if path.exists() and not force:
        raise ProofError(f"refusing to overwrite existing file: {path} (use --force)")
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _check_output(path: Path, force: bool):
    if path.exists() and not force:
        raise ProofError(f"refusing to overwrite existing file: {path} (use --force)")


# ── DLL binding ───────────────────────────────────────────────────────────────


class TrenchCore:
    """Direct ctypes binding to the shipped trench-core. No Python re-implementation
    of packed math anywhere in this file; every runtime number comes from the DLL."""

    def __init__(self, dll_path: Path):
        if not dll_path.exists():
            raise ProofError(f"trench-core DLL missing: {dll_path} (cargo build --release -p trench-core)")
        self.path = dll_path
        lib = ctypes.CDLL(str(dll_path))
        self.lib = lib

        lib.trench_pack_body_from_corner_words.argtypes = [
            ctypes.POINTER(ctypes.c_uint16), ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint8)]
        lib.trench_pack_body_from_corner_words.restype = ctypes.c_int

        lib.trench_packed_probe.argtypes = [
            ctypes.c_void_p, ctypes.c_size_t, ctypes.c_double, ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32)]
        lib.trench_packed_probe.restype = ctypes.c_int

        lib.trench_certify_body.argtypes = [
            ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_double,
            ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]
        lib.trench_certify_body.restype = ctypes.c_int

        lib.trench_engine_create.restype = ctypes.c_void_p
        lib.trench_engine_destroy.argtypes = [ctypes.c_void_p]
        lib.trench_engine_prepare.argtypes = [ctypes.c_void_p, ctypes.c_double]
        lib.trench_engine_load_body_bytes.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        lib.trench_engine_load_body_bytes.restype = ctypes.c_int
        lib.trench_engine_set_input_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.trench_engine_set_spatial_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.trench_engine_set_agc_enabled.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.trench_engine_set_dc_block_enabled.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.trench_engine_set_saturation_enabled.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.trench_engine_set_coeff_ramp_scale.argtypes = [ctypes.c_void_p, ctypes.c_float]
        lib.trench_engine_set_interstage_drive.argtypes = [ctypes.c_void_p, ctypes.c_float]
        lib.trench_engine_set_parameters.argtypes = [ctypes.c_void_p] + [ctypes.c_float] * 5
        lib.trench_engine_process_block.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float),
            ctypes.c_int, ctypes.c_double, ctypes.c_double]

    def roundtrip(self, body: bytes) -> bool:
        words = np.frombuffer(body, dtype="<u2").astype(np.uint16)
        out = (ctypes.c_uint8 * BODY_BYTES)()
        rc = self.lib.trench_pack_body_from_corner_words(
            words.ctypes.data_as(ctypes.POINTER(ctypes.c_uint16)),
            words.size, out)
        return rc == 0 and bytes(out) == body

    def probe(self, body: bytes, morph: float, q: float):
        """Returns (rows[6x5], max_pole_radius, unstable_mask, nonfinite_mask, rc)."""
        rows = (ctypes.c_double * (NUM_STAGES * NUM_COEFFS))()
        max_r = ctypes.c_double()
        unstable = ctypes.c_uint32()
        nonfinite = ctypes.c_uint32()
        buf = ctypes.create_string_buffer(body, len(body))
        rc = self.lib.trench_packed_probe(
            buf, len(body), ctypes.c_double(morph), ctypes.c_double(q),
            rows, ctypes.byref(max_r), ctypes.byref(unstable), ctypes.byref(nonfinite))
        return (np.ctypeslib.as_array(rows).copy().reshape(NUM_STAGES, NUM_COEFFS),
                float(max_r.value), int(unstable.value), int(nonfinite.value), rc)

    def certify(self, body: bytes, res: int, r_max: float = 1.0):
        passed = ctypes.c_int32()
        max_r = ctypes.c_double()
        fail_m = ctypes.c_double()
        fail_q = ctypes.c_double()
        buf = ctypes.create_string_buffer(body, len(body))
        rc = self.lib.trench_certify_body(
            buf, len(body), ctypes.c_uint32(res), ctypes.c_double(r_max),
            ctypes.byref(passed), ctypes.byref(max_r),
            ctypes.byref(fail_m), ctypes.byref(fail_q))
        return {"rc": rc, "pass": int(passed.value), "max_radius": float(max_r.value),
                "fail_morph": float(fail_m.value), "fail_q": float(fail_q.value),
                "res": res, "r_max": r_max}

    def render_body_solo(self, body: bytes, signal: np.ndarray, trajectory):
        """signal: mono float32. trajectory: t_seconds -> (morph, q). Returns mono float32."""
        eng = self.lib.trench_engine_create()
        if not eng:
            raise ProofError("trench_engine_create returned null")
        try:
            self.lib.trench_engine_prepare(eng, ctypes.c_double(AUDIO_SR))
            buf = ctypes.create_string_buffer(body, len(body))
            rc = self.lib.trench_engine_load_body_bytes(eng, buf, len(body))
            if rc != 0:
                raise ProofError(f"trench_engine_load_body_bytes failed with rc={rc}")
            self.lib.trench_engine_set_input_mode(eng, 0)       # None — cascade only
            self.lib.trench_engine_set_spatial_mode(eng, 2)     # Off
            self.lib.trench_engine_set_agc_enabled(eng, 0)
            self.lib.trench_engine_set_dc_block_enabled(eng, 0)
            self.lib.trench_engine_set_saturation_enabled(eng, 0)
            self.lib.trench_engine_set_coeff_ramp_scale(eng, ctypes.c_float(0.0))
            self.lib.trench_engine_set_interstage_drive(eng, ctypes.c_float(0.0))
            self.lib.trench_engine_set_parameters(eng, 0.0, 0.0, 0.0, 0.0, 1.0)  # amount 1
            left = np.ascontiguousarray(signal, dtype=np.float32).copy()
            right = np.ascontiguousarray(signal, dtype=np.float32).copy()
            n = left.size
            for i0 in range(0, n, AUDIO_BLOCK):
                nb = min(AUDIO_BLOCK, n - i0)
                morph, q = trajectory(i0 / AUDIO_SR)
                self.lib.trench_engine_process_block(
                    eng,
                    left[i0:].ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                    right[i0:].ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                    nb, ctypes.c_double(morph), ctypes.c_double(q))
            return left
        finally:
            self.lib.trench_engine_destroy(ctypes.c_void_p(eng))


# ── analysis helpers (plot-side math only; runtime rows always come from the DLL) ──


def _pole_hz_radius(a1: float, a2: float):
    """Pole (hz, radius) from a decoded denominator row, at the runtime rate.

    Returns (hz, radius, kind) with kind 'conjugate' or 'real'. Plot/diagnostic
    use only — the certification path uses the core's own masks and radius.
    """
    if not (math.isfinite(a1) and math.isfinite(a2)):
        return (float("nan"), float("inf"), "nonfinite")
    disc = a1 * a1 - 4.0 * a2
    if disc < 0.0:
        r = math.sqrt(max(a2, 0.0))
        if r <= 0.0:
            return (0.0, 0.0, "conjugate")
        hz = math.acos(max(-1.0, min(1.0, -a1 / (2.0 * r)))) / (2.0 * math.pi) * RUNTIME_SR
        return (hz, r, "conjugate")
    sq = math.sqrt(disc)
    r = max(abs((-a1 + sq) / 2.0), abs((-a1 - sq) / 2.0))
    return (float("nan"), r, "real")


def _cascade_db(rows: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    """Magnitude of the six DF2T sections as a serial cascade. Plot use only."""
    w = 2.0 * np.pi * freqs / RUNTIME_SR
    z1 = np.exp(-1j * w)
    z2 = z1 * z1
    h = np.ones(freqs.shape, dtype=complex)
    for b0, b1, b2, a1, a2 in rows:
        h *= (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-9))


def _trajectory(t: float):
    """The proof trajectory: M0->M100 at Q0, return at Q100, then Q at M=0.5."""
    third = AUDIO_SECONDS / 3.0
    if t < third:
        return (t / third, 0.0)
    if t < 2.0 * third:
        return (1.0 - (t - third) / third, 1.0)
    return (0.5, (t - 2.0 * third) / third)


def _audio_stats(x: np.ndarray):
    return {"samples": int(x.size), "peak_abs": float(np.max(np.abs(x))) if x.size else 0.0,
            "rms": float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if x.size else 0.0,
            "finite": bool(np.all(np.isfinite(x)))}


# ── the proof ─────────────────────────────────────────────────────────────────


def run(args) -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.io import wavfile

    artifact_dir = Path(args.dir).resolve()
    if not artifact_dir.is_dir():
        raise ProofError(f"not a directory: {artifact_dir}")
    bodies = sorted(artifact_dir.glob("*.body240"))
    if args.name:
        bodies = [b for b in bodies if b.stem == args.name]
    if len(bodies) != 1:
        raise ProofError(f"{artifact_dir}: expected exactly one .body240 (use --name); found {[b.name for b in bodies]}")
    body_path = bodies[0]
    name = body_path.stem
    body = body_path.read_bytes()
    if len(body) != BODY_BYTES:
        raise ProofError(f"{body_path}: not a body240 ({len(body)} bytes)")

    geo_path = artifact_dir / f"{name}.geometry.json"
    reg_path = artifact_dir / f"{name}.registered_lanes.json"
    manifest_path = artifact_dir / "master_body.manifest.json"
    proof_path = artifact_dir / f"{name}.runtime_proof.json"
    response_png = artifact_dir / f"{name}.packed_runtime_response.png"
    lanes_png = artifact_dir / f"{name}.pole_lane_crossings.png"
    wav_path = artifact_dir / f"{name}.body_solo_morph_q.float32.wav"
    decoded_path = artifact_dir / f"{name}.decoded.geometry.json"
    for out in (proof_path, response_png, lanes_png, wav_path, decoded_path):
        _check_output(out, args.force)

    core = TrenchCore(Path(args.core_dll).resolve())

    lane_ids = [f"lane {i}" for i in range(NUM_STAGES)]
    if reg_path.exists():
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        plan = reg.get("stage_plan") or []
        if len(plan) == NUM_STAGES and all(isinstance(e.get("lane_id"), str) for e in plan):
            lane_ids = [e["lane_id"] for e in sorted(plan, key=lambda e: e.get("slot", 0))]

    declared_pairs, declared_indices = [], []
    if manifest_path.exists():
        snap = json.loads(manifest_path.read_text(encoding="utf-8"))
        intent = ((snap.get("body") or {}).get("crossing_intent") or {})
        for pair in intent.get("pairs") or []:
            if isinstance(pair, list) and len(pair) == 2 and all(p in lane_ids for p in pair):
                declared_pairs.append(list(pair))
                declared_indices.append([lane_ids.index(pair[0]), lane_ids.index(pair[1])])

    assertions = []

    def assert_that(label, ok):
        assertions.append({"assertion": label, "pass": bool(ok)})
        return ok

    # ── 1. packed-word round trip (core-owned) ──
    roundtrip_ok = core.roundtrip(body)
    assert_that("packed_words_roundtrip_byte_identical", roundtrip_ok)

    # ── 2. certification: core grid verdict + per-point rows ──
    core_verdict = core.certify(body, args.grid)
    assert_that("core_certify_pass", core_verdict["rc"] == 0 and core_verdict["pass"] == 1)

    unstable_rows, nonfinite_rows = [], []
    max_radius = 0.0
    denom = args.grid - 1
    for qi in range(args.grid):
        q = qi / denom
        for mi in range(args.grid):
            m = mi / denom
            _, point_max_r, unstable, nonfinite, rc = core.probe(body, m, q)
            if rc != 0 or nonfinite or not math.isfinite(point_max_r):
                nonfinite_rows.append({"morph": m, "q": q, "mask": nonfinite, "rc": rc})
                continue
            if unstable:
                unstable_rows.append({"morph": m, "q": q, "mask": unstable})
            max_radius = max(max_radius, point_max_r)
    assert_that("zero_unstable_rows", not unstable_rows)
    assert_that("zero_nonfinite_rows", not nonfinite_rows)

    # ── 3. packed-runtime response plot ──
    freqs = np.logspace(math.log10(20.0), math.log10(19000.0), 600)
    curves = {}
    for label, m, q in RESPONSE_POINTS:
        rows, _, _, _, rc = core.probe(body, m, q)
        if rc != 0:
            raise ProofError(f"probe failed at {label} (rc={rc})")
        curves[label] = _cascade_db(rows, freqs)
    fig, ax = plt.subplots(figsize=(12, 6), facecolor="#0f1512")
    ax.set_facecolor("#0f1512")
    colors = ["#7fb2e5", "#e57373", "#8fd18a", "#e5d16b", "#f0f0f0", "#c9a6e8"]
    for (label, _, _), color in zip(RESPONSE_POINTS, colors):
        ax.semilogx(freqs, curves[label], color=color, linewidth=1.2, label=label)
    ax.set_ylim(*RESPONSE_YLIM)
    ax.set_xlim(20, 20000)
    ax.grid(True, which="both", alpha=0.25)
    ax.set_title(f"{name} — packed/runtime-decoded DF2T cascade", color="#dddddd")
    ax.set_xlabel("Frequency (Hz)", color="#dddddd")
    ax.set_ylabel("Packed runtime response (dB)", color="#dddddd")
    ax.tick_params(colors="#aaaaaa")
    legend = ax.legend(facecolor="#1a211d", labelcolor="#dddddd", edgecolor="#444444")
    fig.savefig(response_png, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    # ── 4. pole lanes + declared crossings ──
    morphs = np.linspace(0.0, 1.0, CROSS_SAMPLES)
    lane_hz = {0.0: np.full((NUM_STAGES, CROSS_SAMPLES), np.nan),
               1.0: np.full((NUM_STAGES, CROSS_SAMPLES), np.nan)}
    real_rooted = {"0.0": [], "1.0": []}
    for q_val in (0.0, 1.0):
        for k, m in enumerate(morphs):
            rows, _, _, _, _ = core.probe(body, float(m), q_val)
            for lane in range(NUM_STAGES):
                hz, _, kind = _pole_hz_radius(rows[lane][3], rows[lane][4])
                if kind == "conjugate":
                    lane_hz[q_val][lane, k] = hz
                else:
                    real_rooted[str(q_val)].append({"lane": lane, "lane_id": lane_ids[lane],
                                                    "morph": float(m), "kind": kind})
    crossing_evidence = []
    for (la, lb), (ida, idb) in zip(declared_pairs, declared_indices):
        for q_val in (0.0, 1.0):
            fa, fb = lane_hz[q_val][la], lane_hz[q_val][lb]
            delta = fa - fb
            valid = np.isfinite(delta)
            crossings = []
            for k in range(CROSS_SAMPLES - 1):
                if not (valid[k] and valid[k + 1]):
                    continue
                if delta[k] == 0.0 or delta[k] * delta[k + 1] < 0.0:
                    frac = abs(delta[k]) / (abs(delta[k]) + abs(delta[k + 1])) if delta[k] != delta[k + 1] else 0.0
                    crossings.append(float(morphs[k] + frac * (morphs[k + 1] - morphs[k])))
            order = []
            for idx in (0, CROSS_SAMPLES - 1):
                if valid[idx]:
                    order.append("a_below_b" if delta[idx] < 0 else ("a_above_b" if delta[idx] > 0 else "touching"))
                else:
                    order.append("real_rooted")
            crossing_evidence.append({
                "lane_a": la, "lane_b": lb, "lane_a_id": ida, "lane_b_id": idb, "q": q_val,
                "crossing_morph": crossings,
                "endpoint_delta_hz": [float(delta[0]) if valid[0] else None,
                                      float(delta[-1]) if valid[-1] else None],
                "endpoint_order": order})

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True, facecolor="#0f1512")
    lane_colors = ["#7fb2e5", "#e57373", "#e5d16b", "#c9a6e8", "#8fd18a", "#e891b8"]
    for ax, q_val, title in ((axes[0], 0.0, "Q0"), (axes[1], 1.0, "Q100")):
        ax.set_facecolor("#0f1512")
        for lane in range(NUM_STAGES):
            ax.semilogy(morphs, lane_hz[q_val][lane], color=lane_colors[lane],
                        linewidth=1.4, label=f"{lane} {lane_ids[lane]}")
        for ev in crossing_evidence:
            if ev["q"] != q_val:
                continue
            for cm in ev["crossing_morph"]:
                k = int(cm * (CROSS_SAMPLES - 1))
                fa = lane_hz[q_val][ev["lane_a"]]
                y = fa[k] if np.isfinite(fa[k]) else None
                if y:
                    ax.plot([cm], [y], "o", color="#ffffff", markersize=7, markerfacecolor="none")
        ax.set_title(f"{title} — packed/runtime-decoded pole lanes", color="#dddddd")
        ax.set_xlabel("Morph (M0 -> M100)", color="#dddddd")
        ax.grid(True, which="both", alpha=0.25)
        ax.tick_params(colors="#aaaaaa")
    axes[0].set_ylabel("Pole frequency (Hz, log scale)", color="#dddddd")
    axes[0].legend(facecolor="#1a211d", labelcolor="#dddddd", edgecolor="#444444", fontsize=8)
    fig.savefig(lanes_png, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    # ── 5. BODY SOLO audio (the real engine; nothing post-processed) ──
    rng = np.random.RandomState(args.seed)
    n = int(AUDIO_SECONDS * AUDIO_SR)
    signal = rng.standard_normal(n).astype(np.float32)
    signal *= np.float32(INPUT_RMS / np.sqrt(np.mean(signal.astype(np.float64) ** 2)))
    output = core.render_body_solo(body, signal, _trajectory)
    in_stats = _audio_stats(signal)
    out_stats = _audio_stats(output)
    assert_that("body_solo_is_finite", out_stats["finite"])
    wavfile.write(str(wav_path), AUDIO_SR, output.astype(np.float32))

    # ── 6. decode + quantization diff against the compiler input ──
    quantization = None
    if geo_path.exists():
        completed = subprocess.run(
            [sys.executable, "-m", "tools.filter_cli", "decode", str(body_path), str(decoded_path)],
            cwd=ROOT, capture_output=True, text=True)
        if completed.returncode != 0:
            raise ProofError(f"filter_cli decode failed: {completed.stderr.strip()}")
        authored = json.loads(geo_path.read_text(encoding="utf-8"))["corners"]
        decoded = json.loads(decoded_path.read_text(encoding="utf-8"))["corners"]
        keys = ("pole_hz", "pole_r", "zero_hz", "zero_r", "scale")
        max_delta = {k: 0.0 for k in keys}
        worst = {k: None for k in keys}
        for ci, (ca, cb) in enumerate(zip(authored, decoded)):
            for si, (sa, sb) in enumerate(zip(ca, cb)):
                for k in keys:
                    if k in sa and k in sb:
                        d = abs(float(sa[k]) - float(sb[k]))
                        if d > max_delta[k]:
                            max_delta[k] = d
                            worst[k] = {"corner_index": ci, "stage": si,
                                        "authored": float(sa[k]), "packed": float(sb[k])}
        quantization = {"source": "geometry.json (compiler input) vs decoded body240",
                        "max_abs_delta": max_delta, "worst_stage": worst}

    # ── 7. the tracked record ──
    overall = all(a["pass"] for a in assertions)
    proof = {
        "schema_version": 1,
        "tool": "tools/prove_master_body.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_backend": f"trench-core FFI via direct ctypes binding: {core.path}",
        "inputs": {
            "body": str(body_path), "body_sha256": _sha256(body_path),
            "geometry": str(geo_path) if geo_path.exists() else None,
            "registered_lanes": str(reg_path) if reg_path.exists() else None,
            "manifest_snapshot": str(manifest_path) if manifest_path.exists() else None,
            "core_dll": str(core.path), "core_dll_sha256": _sha256(core.path),
        },
        "body": body_path.name,
        "body_bytes": BODY_BYTES,
        "packed_words_roundtrip_byte_identical": roundtrip_ok,
        "certification_grid": {
            "shape": [args.grid, args.grid],
            "rows": args.grid * args.grid,
            "max_pole_radius": max_radius,
            "unstable_rows": unstable_rows,
            "nonfinite_rows": nonfinite_rows,
            "core_certify": core_verdict,
            "note": "Sampled certification, not a continuum proof; raise --grid to shrink the gap.",
        },
        "intentional_crossovers": {
            "declared_pairs": declared_pairs,
            "runtime_lane_indices": declared_indices,
            "evidence": crossing_evidence,
            "real_rooted_samples": real_rooted,
            "note": "Packed runtime poles from trench_packed_probe denominator rows; stage slot remains the lane identity.",
        },
        "response": {
            "source": "packed/runtime-decoded DF2T rows (trench_packed_probe)",
            "sample_rate_hz": RUNTIME_SR,
            "shared_db_ylim": list(RESPONSE_YLIM),
            "points": [label for label, _, _ in RESPONSE_POINTS],
            "plot": response_png.name,
        },
        "pole_lane_plot": lanes_png.name,
        "quantization": quantization,
        "body_solo_audio": {
            "source_seed": args.seed,
            "input_rms": INPUT_RMS,
            "sample_rate_hz": AUDIO_SR,
            "trajectory": "continuous M0->M100 at Q0, return at Q100, then Q at M=0.5",
            "agc": False, "dc_block": False, "saturation": False,
            "per_render_normalization": False,
            "input_stats": in_stats,
            "output_stats": out_stats,
            "wav": wav_path.name,
        },
        "assertions": assertions,
        "pass": overall,
    }
    _write_json(proof_path, proof, args.force)

    print(f"body: {body_path.name} ({BODY_BYTES} bytes, sha256 {_sha256(body_path)[:16]}...)")
    print(f"round trip: {'byte-identical' if roundtrip_ok else 'MISMATCH'}")
    print(f"grid {args.grid}x{args.grid}: {len(unstable_rows)} unstable, {len(nonfinite_rows)} nonfinite rows; "
          f"max pole radius {max_radius:.10f}")
    print(f"core certify: pass={core_verdict['pass']} max_radius={core_verdict['max_radius']:.10f}")
    for ev in crossing_evidence:
        print(f"crossing lanes {ev['lane_a']}/{ev['lane_b']} q={ev['q']}: "
          + (", ".join(f"M={c:.4f}" for c in ev["crossing_morph"]) or "none"))
    print(f"audio: peak {out_stats['peak_abs']:.6f}, rms {out_stats['rms']:.6f}, finite={out_stats['finite']}")
    print(f"wrote {proof_path}")
    print(f"wrote {response_png}")
    print(f"wrote {lanes_png}")
    print(f"wrote {wav_path}")
    print("PROOF:", "PASS" if overall else "FAIL")
    return 0 if overall else 1


def _parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dir", help="artifact directory holding the compiled body")
    p.add_argument("--name", help="body name when the directory holds more than one .body240")
    p.add_argument("--grid", type=int, default=65, help="certification grid resolution (default 65)")
    p.add_argument("--seed", type=int, default=20260720, help="audio exciter seed")
    p.add_argument("--core-dll", default=str(DEFAULT_DLL), help="path to trench_core.dll")
    p.add_argument("--force", action="store_true", help="overwrite existing proof artifacts")
    return p


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        return run(args)
    except ProofError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
