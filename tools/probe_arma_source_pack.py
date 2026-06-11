#!/usr/bin/env python3
"""Probe representative ARMA source-pack WAVs through the shipped factorizer.

This is an offline fitability assay. It does not modify runtime code or install
cartridges. For each selected WAV:

1. Find a sustained analysis slice.
2. Derive a low-quefrency spectral envelope.
3. Fit that envelope through the bounded native-domain quarry fitter.
4. Pack and decode the six rows.
5. Measure shipped shape residual, packed drift, stability, and the number of
   rows that materially shape the response.

The fitted posture is authored inside the cartridge's packable coefficient box,
then decoded and evaluated through trench-core. This avoids treating an
unconstrained polynomial solve plus post-hoc root repair as an acceptable
generated filter.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly, sosfreqz


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime.freq_response import cascade_response_db  # noqa: E402
from pyruntime.quarry_fit import fit_envelope  # noqa: E402


PACK = ROOT / "dev" / "tmp" / "arma_source_pack"
OUT = PACK / "probe_hot_r0990_r0998"
FILTERS_OUT = OUT / "filters"
RUNTIME_SR = 39_062.5
ANALYSIS_SR = 16_000
FIT_FREQS = np.logspace(math.log10(40.0), math.log10(7_800.0), 192)
EVAL_FREQS = np.logspace(math.log10(40.0), math.log10(7_800.0), 320)
SHAPE_BAND = (120.0, 7_500.0)
LIFTER = 64

SOURCES = (
    ("synth_oo", "corners_audio_only/synth_sustained/vowel_oo_boot.wav"),
    ("synth_iy", "corners_audio_only/synth_sustained/vowel_iy_beet.wav"),
    ("synth_ah", "corners_audio_only/synth_sustained/vowel_ah_father.wav"),
    ("synth_choir", "corners_audio_only/synth_sustained/inst_choir.wav"),
    ("synth_reed", "corners_audio_only/synth_sustained/inst_reed.wav"),
    (
        "legisign_i",
        "corners_audio_only/phonetic_4corner_legisign/00_selected_primes/"
        "corner_1_bright_front_vowel__prime_i.wav",
    ),
    (
        "legisign_u",
        "corners_audio_only/phonetic_4corner_legisign/00_selected_primes/"
        "corner_2_dark_back_vowel__prime_u.wav",
    ),
    (
        "legisign_a",
        "corners_audio_only/phonetic_4corner_legisign/00_selected_primes/"
        "corner_3_open_vowel__prime_a.wav",
    ),
    (
        "legisign_sh",
        "corners_audio_only/phonetic_4corner_legisign/00_selected_primes/"
        "corner_4_consonant_rich_spectral_mode__prime_sh.wav",
    ),
    ("plasma_whistler", "corners_audio_only/other_sources/plasma/whistler.wav"),
    ("nmr_cyclohexane", "corners_audio_only/other_sources/nmr/nmrtalk/cyclohexane/fid.wav"),
    ("proteus_bell", "corners_audio_only/other_sources/kb6/extracted/EMU_Proteus3/Bell1.WAV"),
)


def load_mono_16k(path: Path) -> np.ndarray:
    sr, data = wavfile.read(str(path))
    x = np.asarray(data)
    if x.dtype.kind == "i":
        x = x.astype(np.float64) / float(np.iinfo(x.dtype).max)
    else:
        x = x.astype(np.float64)
    if x.ndim == 2:
        x = x.mean(axis=1)
    sr = int(sr)
    if sr != ANALYSIS_SR:
        gcd = math.gcd(sr, ANALYSIS_SR)
        x = resample_poly(x, ANALYSIS_SR // gcd, sr // gcd)
    return np.asarray(x, dtype=np.float64)


def sustained_slice(x: np.ndarray) -> np.ndarray:
    """Longest near-peak RMS frame run, capped at 400 ms."""
    frame = int(0.025 * ANALYSIS_SR)
    hop = int(0.010 * ANALYSIS_SR)
    if len(x) <= frame:
        return x
    starts = np.arange(0, len(x) - frame + 1, hop)
    rms = np.array([np.sqrt(np.mean(x[s:s + frame] ** 2) + 1e-30) for s in starts])
    hot = rms >= float(np.max(rms)) * (10.0 ** (-3.0 / 20.0))
    runs: list[tuple[int, int]] = []
    begin = None
    for index, value in enumerate(hot):
        if value and begin is None:
            begin = index
        elif not value and begin is not None:
            runs.append((begin, index))
            begin = None
    if begin is not None:
        runs.append((begin, len(hot)))
    if not runs:
        lo, hi = 0, min(len(x), int(0.4 * ANALYSIS_SR))
    else:
        begin, end = max(runs, key=lambda run: run[1] - run[0])
        lo = int(starts[begin])
        hi = int(starts[end - 1] + frame)
    hi = min(hi, lo + int(0.4 * ANALYSIS_SR))
    seg = x[lo:hi]
    if len(seg) < 256:
        seg = x[: min(len(x), int(0.4 * ANALYSIS_SR))]
    return seg


def smooth_envelope(path: Path) -> np.ndarray:
    seg = sustained_slice(load_mono_16k(path))
    nfft = 1
    while nfft < max(4096, len(seg)):
        nfft *= 2
    nfft = min(nfft, 16_384)
    buf = np.zeros(nfft)
    n = min(len(seg), nfft)
    buf[:n] = seg[:n] * np.hanning(n)
    logmag = np.log(np.abs(np.fft.rfft(buf)) + 1e-9)
    mirrored = np.concatenate((logmag, logmag[-2:0:-1]))
    cep = np.fft.ifft(mirrored).real
    kept = np.zeros_like(cep)
    lifter = min(LIFTER, len(cep) // 2 - 1)
    kept[:lifter] = cep[:lifter]
    kept[-lifter + 1:] = cep[-lifter + 1:]
    smooth = np.fft.fft(kept).real[: len(logmag)]
    freqs = np.fft.rfftfreq(nfft, 1.0 / ANALYSIS_SR)
    env_db = 20.0 / math.log(10.0) * smooth
    sampled = np.interp(FIT_FREQS, freqs, env_db)
    sampled -= float(np.max(sampled))
    return sampled


def stage_sos(row: tuple[float, ...]) -> np.ndarray:
    c0, c1, c2, c3, c4 = row
    return np.array([[c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, 1.0, c2 - 2.0, 1.0 - c3]])


def active_shape_rows(rows: list[tuple[float, ...]]) -> int:
    """Count rows contributing at least 0.75 dB of non-flat shape."""
    omega = 2.0 * np.pi * EVAL_FREQS / RUNTIME_SR
    count = 0
    for row in rows:
        _, h = sosfreqz(stage_sos(row), worN=omega)
        db = 20.0 * np.log10(np.maximum(np.abs(h), 1e-14))
        if float(np.max(db) - np.min(db)) >= 0.75:
            count += 1
    return count


def max_pole_radius(rows: list[tuple[float, ...]]) -> float:
    value = 0.0
    for _c0, _c1, c2, c3, _c4 in rows:
        roots = np.roots((1.0, c2 - 2.0, 1.0 - c3))
        value = max(value, float(np.max(np.abs(roots))))
    return value


def shape_residual(target_db: np.ndarray, fitted_db: np.ndarray) -> float:
    mask = (EVAL_FREQS >= SHAPE_BAND[0]) & (EVAL_FREQS <= SHAPE_BAND[1])
    residual = fitted_db[mask] - target_db[mask]
    residual -= float(np.mean(residual))
    return float(np.sqrt(np.mean(residual * residual)))


def probe(name: str, relative_path: str) -> dict:
    path = PACK / relative_path
    target_fit = smooth_envelope(path)
    fit = fit_envelope(
        FIT_FREQS,
        target_fit,
        runtime_sr=RUNTIME_SR,
        seed=sum(name.encode("utf-8")),
    )
    rows = fit.kernel_rows
    packed_rows = fit.packed_rows
    target_eval = np.interp(EVAL_FREQS, FIT_FREQS, target_fit)
    float_fit = cascade_response_db([EncodedCoeffs(*row) for row in rows], EVAL_FREQS, RUNTIME_SR)
    packed_fit = cascade_response_db([EncodedCoeffs(*row) for row in packed_rows], EVAL_FREQS, RUNTIME_SR)
    residual = shape_residual(target_eval, packed_fit)
    drift = shape_residual(float_fit, packed_fit)
    pole_radius = fit.packed_max_pole_radius
    active_rows = active_shape_rows(packed_rows)
    status = "good" if residual <= 4.0 else ("usable" if residual <= 8.0 else "rough")
    FILTERS_OUT.mkdir(parents=True, exist_ok=True)
    body_path = FILTERS_OUT / f"{name}.body240"
    corner_path = FILTERS_OUT / f"{name}.corner.json"
    body_path.write_bytes(fit.body_bytes)
    stages = [
        {f"c{index}": float(value) for index, value in enumerate(row)}
        for row in packed_rows
    ]
    packed_words = [list(row) for row in fit.packed_words]
    corner_path.write_text(
        json.dumps(
            {
                "format": "compiled-v1",
                "name": f"quarry envelope: {name}",
                "provenance": (
                    "standalone source envelope -> minphase -> bounded forge_fit -> "
                    "complex-pole radius crank -> packed readback"
                ),
                "source": relative_path,
                "sampleRate": RUNTIME_SR,
                "stages": 6,
                "authoring": {
                    "complexPoleRadiusBand": list(fit.complex_pole_radius_band),
                    "crankedComplexRows": fit.cranked_complex_rows,
                    "realSupportRows": "preserved",
                },
                "keyframes": [
                    {
                        "label": label,
                        "boost": 1.0,
                        "stages": stages,
                        "packedWords": packed_words,
                    }
                    for label in ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "name": name,
        "source": relative_path,
        "fit_backend": "bounded-forge-native-d-space",
        "status": status,
        "emitted_rows": len(rows),
        "effective_shape_rows": active_rows,
        "in_band_shape_rms_db": round(residual, 3),
        "packed_drift_rms_db": round(drift, 3),
        "max_pole_radius": round(pole_radius, 6),
        "stable": pole_radius < 1.0,
        "response_null_db": round(fit.response_null_db, 3),
        "complex_pole_radius_band": list(fit.complex_pole_radius_band),
        "cranked_complex_rows": fit.cranked_complex_rows,
        "body240": str(body_path.relative_to(PACK)).replace("\\", "/"),
        "corner_json": str(corner_path.relative_to(PACK)).replace("\\", "/"),
        "freqs_hz": EVAL_FREQS.tolist(),
        "target_db": target_eval.tolist(),
        "float_fit_db": float_fit.tolist(),
        "packed_fit_db": packed_fit.tolist(),
    }


def write_plot(rows: list[dict]) -> None:
    cols = 3
    plot_rows = math.ceil(len(rows) / cols)
    fig, axes = plt.subplots(plot_rows, cols, figsize=(14.0, plot_rows * 3.0), facecolor="#080a0a")
    for ax, row in zip(np.asarray(axes).ravel(), rows):
        freqs = np.array(row["freqs_hz"])
        ax.set_facecolor("#0b0f0e")
        ax.semilogx(freqs, row["target_db"], color="#8b949e", ls="--", lw=1.1, label="source envelope")
        ax.semilogx(freqs, row["packed_fit_db"], color="#9aef5a", lw=1.4, label="packed fit")
        ax.set_xlim(60.0, 7_800.0)
        ax.set_ylim(-62.0, 16.0)
        ax.grid(True, which="both", color="#1c2722", lw=0.35)
        ax.tick_params(colors="#889", labelsize=7)
        for spine in ax.spines.values():
            spine.set_color("#26302b")
        ax.set_title(
            f"{row['name']} [{row['status']}]  RMS {row['in_band_shape_rms_db']:.1f} dB  "
            f"rows {row['effective_shape_rows']}/6",
            color="#cdd",
            fontsize=9,
        )
    for ax in np.asarray(axes).ravel()[len(rows):]:
        ax.axis("off")
    np.asarray(axes).ravel()[0].legend(fontsize=7, labelcolor="#cdd", loc="lower left")
    fig.suptitle(
        "ARMA source-pack fitability probe: gray source envelope, green shipped packed fit",
        color="#f0f6fc",
        fontsize=13,
        fontweight="bold",
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.965))
    fig.savefig(OUT / "contact_sheet.png", dpi=140, facecolor="#080a0a")
    plt.close(fig)


def write_report(rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "arma_source_probe.json").write_text(json.dumps({"rows": rows}, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# ARMA source-pack fitability probe",
        "",
        "Offline response-first probe through trench-core. The direct raw-audio ARMA "
        "entrypoint is not used here; this derives a sustained source envelope, fits "
        "inside the packable coefficient box, then evaluates the trench-core packed readback.",
        "",
        "| source | verdict | effective rows | cranked complex rows | shape RMS | packed drift | max pole radius |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['name']}` | {row['status']} | {row['effective_shape_rows']}/6 | "
            f"{row['cranked_complex_rows']} | "
            f"{row['in_band_shape_rms_db']:.2f} dB | {row['packed_drift_rms_db']:.2f} dB | "
            f"{row['max_pole_radius']:.5f} |"
        )
    lines += [
        "",
        "`good` <= 4 dB shape RMS, `usable` <= 8 dB, `rough` > 8 dB. "
        "These are screening labels, not listening verdicts.",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if not trench_ffi.available():
        print("trench-core unavailable; run cargo build --release -p trench-core", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, relative_path in SOURCES:
        print(f"probe {name:<18} {relative_path}")
        row = probe(name, relative_path)
        rows.append(row)
        print(
            f"  {row['status']:<6} RMS={row['in_band_shape_rms_db']:>5.2f} dB  "
            f"rows={row['effective_shape_rows']}/6  drift={row['packed_drift_rms_db']:.2f} dB  "
            f"poleR={row['max_pole_radius']:.5f}"
        )
    OUT.mkdir(parents=True, exist_ok=True)
    write_plot(rows)
    write_report(rows)
    print(f"wrote: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
