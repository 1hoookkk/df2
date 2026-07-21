#!/usr/bin/env python3
"""Translate read-only measurement families into reproducible evidence bundles.

The command is intentionally an adapter/orchestrator.  Source roots remain
read-only.  DVTD measured and calculated tables become complex TF inputs for the
owned ``fit-complex-candidates`` binary; HRTF files become complete directional
complex surfaces plus explicitly named median/neutral fits; phononic data keeps
its full surface and an observed lane route; object WAVs stop at labeled direct
spectra.  No command in this file silently assigns four corners or promotes a
source to a product body.

Examples::

  python -m tools.translate_sources dvtd --dvtd-root C:\\Users\\hooki\\trench-filters\\data\\vocal\\dvtd
  python -m tools.translate_sources sonicom --sofa C:\\...\\P0001_Raw_48kHz.sofa
  python -m tools.translate_sources inventory --dvtd-zip C:\\...\\dvtd.zip
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import struct
import subprocess
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SR = 39062.5
DVTD_FIT_BAND = (100.0, 10000.0)
HRTF_FIT_BAND = (200.0, 16000.0)
FIT_GRID_POINTS = 256
TOOL_VERSION = 1
DEFAULT_OUT = ROOT / "dev" / "tmp" / "source_translation_20260720"
DEFAULT_DVTD_ROOT = Path(r"C:\Users\hooki\trench-filters\data\vocal\dvtd")
DEFAULT_DVTD_ZIP = DEFAULT_DVTD_ROOT / "dvtd.zip"
DEFAULT_SONICOM = Path(
    r"C:\Users\hooki\trench-filters\data\hrtf\sonicom\P0001\HRTF\HRTF\48kHz\P0001_Raw_48kHz.sofa"
)
DEFAULT_AALTO = Path(r"C:\Users\hooki\trench-filters\data\hrtf\aalto_laser_spark\NF_LIB_HRTF_measured.sofa")
DEFAULT_PHONONIC = Path(
    r"C:\Users\hooki\trench-filters\data\phononic\learning_inverse_design_acoustic_metamaterials\data\data_20000_S-A_range1_smaller0-82.csv"
)
DEFAULT_OBJECTS = ROOT / "wav-source-library" / "measured_objects" / "ir_library"
FITTER = ROOT / "target" / "release" / "fit-complex-candidates.exe"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    return path


def log_grid(lo: float, hi: float, count: int = FIT_GRID_POINTS) -> np.ndarray:
    return np.logspace(math.log10(lo), math.log10(hi), count, dtype=np.float64)


def interpolate_complex(freqs: np.ndarray, values: np.ndarray, grid: np.ndarray) -> np.ndarray:
    return np.interp(grid, freqs, values.real) + 1j * np.interp(grid, freqs, values.imag)


def read_dvtd_table_bytes(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    table = np.genfromtxt(io.BytesIO(data), skip_header=1)
    if table.ndim != 2 or table.shape[1] < 3:
        raise ValueError("DVTD table must have freq_Hz, magnitude, phase_rad columns")
    freqs = np.asarray(table[:, 0], dtype=np.float64)
    magnitude = np.asarray(table[:, 1], dtype=np.float64)
    phase = np.asarray(table[:, 2], dtype=np.float64)
    if not (np.all(np.isfinite(freqs)) and np.all(np.isfinite(magnitude)) and np.all(np.isfinite(phase))):
        raise ValueError("DVTD table contains nonfinite values")
    if np.any(np.diff(freqs) <= 0):
        raise ValueError("DVTD frequencies must be strictly ascending")
    return freqs, magnitude * np.exp(1j * phase)


def prepare_complex_tf(
    freqs: np.ndarray,
    response: np.ndarray,
    band: tuple[float, float],
    *,
    delay_from_ir: bool,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Band-limit, remove only estimated pure arrival delay, and resample.

    The returned complex response is still absolute; there is no per-curve
    gain normalization.  ``native_sr`` is inferred only for the DVTD table's
    regularly sampled frequency axis and is a provenance diagnostic.
    """
    if freqs.size < 4:
        raise ValueError("complex response needs at least four samples")
    delay_s = 0.0
    native_sr = float((freqs[1] - freqs[0]) * (2 * (len(freqs) - 1)))
    if delay_from_ir:
        n_full = 2 * (len(response) - 1)
        impulse = np.fft.irfft(response, n=n_full)
        onset = int(np.argmax(np.abs(impulse)))
        proposed = onset / native_sr if native_sr > 0 else 0.0
        delay_s = proposed if proposed <= 3.0e-3 else 0.0
    mask = (freqs >= band[0]) & (freqs <= band[1])
    band_freqs = freqs[mask]
    band_response = response[mask] * np.exp(1j * 2.0 * np.pi * band_freqs * delay_s)
    if band_freqs.size < 8:
        raise ValueError(f"fewer than eight response samples in fit band {band}")
    grid = log_grid(*band)
    return grid, interpolate_complex(band_freqs, band_response, grid), delay_s, native_sr


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_fitter(input_path: Path, output_path: Path) -> dict:
    if not FITTER.is_file():
        raise FileNotFoundError(
            f"owned fitter missing: {FITTER}; build with "
            "cargo build --release -p trench-core --bin fit-complex-candidates"
        )
    completed = subprocess.run(
        [str(FITTER), str(input_path), str(output_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{input_path.name}: fitter refused:\n{completed.stdout}{completed.stderr}")
    if completed.stdout.strip():
        print(completed.stdout.strip())
    return json.loads(output_path.read_text(encoding="utf-8"))


def dvtd_members(dvtd_root: Path, dvtd_zip: Path) -> tuple[list[dict], dict[str, bytes], dict[str, bytes]]:
    with zipfile.ZipFile(dvtd_zip) as archive:
        measured_names = sorted(name for name in archive.namelist() if name.endswith("-vvtf-measured.txt"))
        calculated_names = sorted(name for name in archive.namelist() if name.endswith("-vvtf-calculated.txt"))
        if len(measured_names) != 44:
            raise ValueError(f"expected 44 measured DVTD members, found {len(measured_names)} in {dvtd_zip}")
        if len(calculated_names) != 44:
            raise ValueError(f"expected 44 calculated DVTD members, found {len(calculated_names)} in {dvtd_zip}")
        measured = [
            {"model_id": Path(name).parent.name, "member": name}
            for name in measured_names
        ]
        measured_raw = {Path(name).parent.name: archive.read(name) for name in measured_names}
        calculated = {Path(name).parent.name: archive.read(name) for name in calculated_names}
    measured.sort(key=lambda item: item["model_id"])
    if {item["model_id"] for item in measured} != set(calculated):
        raise ValueError("measured and calculated DVTD model ids do not match")
    return measured, measured_raw, calculated


def fit_dvtd_one(
    model_id: str,
    raw_bytes: bytes,
    source_label: str,
    source_hash: str,
    role: str,
    out_dir: Path,
) -> dict:
    freqs, response = read_dvtd_table_bytes(raw_bytes)
    grid, prepared, delay_s, native_sr = prepare_complex_tf(
        freqs, response, DVTD_FIT_BAND, delay_from_ir=True
    )
    stem = f"{model_id}.{role}"
    input_path = out_dir / "inputs" / f"{stem}.complex_tf.json"
    result_path = out_dir / "fits" / f"{stem}.fit.json"
    input_payload = {
        "schema_version": 1,
        "source": {
            "family": "DVTD",
            "model_id": model_id,
            "role": role,
            "label": source_label,
            "sha256": source_hash,
        },
        "freqs_hz": grid.tolist(),
        "h_re": prepared.real.tolist(),
        "h_im": prepared.imag.tolist(),
        "adapter": {
            "fit_band_hz": list(DVTD_FIT_BAND),
            "grid_points": FIT_GRID_POINTS,
            "delay_removal": "irfft onset only; no phase-slope/group-delay removal",
            "removed_delay_seconds": delay_s,
            "native_sample_rate_hz": native_sr,
        },
    }
    write_json(input_path, input_payload)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result = run_fitter(input_path, result_path)
    result["source_provenance"] = input_payload["source"]
    result["adapter"] = input_payload["adapter"]
    return result


def contact_sheet(records: list[dict], out_path: Path, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    usable = [record for record in records if record.get("curve")]
    if not usable:
        return
    values = []
    for record in usable:
        values.extend(point["target_mag_db"] for point in record["curve"])
        values.extend(point["packed_mag_db"] for point in record["curve"])
    lo = math.floor(min(values) / 5.0) * 5.0
    hi = math.ceil(max(values) / 5.0) * 5.0
    cols = 6
    rows = (len(usable) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(2.3 * cols, 1.75 * rows), facecolor="#080a0a")
    axes = np.atleast_1d(axes).ravel()
    for ax, record in zip(axes, usable):
        points = record["curve"]
        x = np.asarray([point["freq_hz"] for point in points])
        target = np.asarray([point["target_mag_db"] for point in points])
        packed = np.asarray([point["packed_mag_db"] for point in points])
        ax.semilogx(x, target, color="#5bef6f", lw=0.8)
        ax.semilogx(x, packed, color="#ffb13e", lw=0.8)
        status = record.get("status", "?")
        ax.set_title(f"{record['source_provenance']['model_id']} [{status}]", fontsize=5.5,
                     color="#ee493c" if status != "PACKED_CONJUGATE" else "#cfe9df")
        ax.set_xlim(DVTD_FIT_BAND)
        ax.set_ylim(lo, hi)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_facecolor("#0b0f0e")
        for spine in ax.spines.values():
            spine.set_color("#283632")
    for ax in axes[len(usable):]:
        ax.axis("off")
    fig.suptitle(f"{title} — green measured/model, amber packed runtime; shared dB scale", fontsize=10, color="#cdd")
    fig.tight_layout(pad=0.4)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, facecolor="#080a0a")
    plt.close(fig)


def dvtd(args: argparse.Namespace) -> int:
    dvtd_root = args.dvtd_root.resolve()
    dvtd_zip = ensure_file(args.dvtd_zip, "DVTD zip")
    measured, measured_raw, calculated = dvtd_members(dvtd_root, dvtd_zip)
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_hash = sha256_file(dvtd_zip)
    records: list[dict] = []
    limit = args.limit if args.limit is not None else len(measured)
    if limit < 1 or limit > len(measured):
        raise ValueError(f"--limit must be in [1, {len(measured)}]")
    for item in measured[:limit]:
        raw = measured_raw[item["model_id"]]
        records.append(
            fit_dvtd_one(
                item["model_id"],
                raw,
                f"{dvtd_zip.as_posix()}::{item['member']}",
                sha256_bytes(raw),
                "measured",
                out_dir,
            )
        )
    for item in measured[:limit]:
        raw = calculated[item["model_id"]]
        records.append(
            fit_dvtd_one(
                item["model_id"],
                raw,
                f"{dvtd_zip.as_posix()}::{item['model_id']}-vvtf-calculated.txt",
                sha256_bytes(raw),
                "calculated_control",
                out_dir,
            )
        )
    measured_records = [record for record in records if record["source_provenance"]["role"] == "measured"]
    controls = [record for record in records if record["source_provenance"]["role"] != "measured"]
    status_counts = Counter(record.get("status", "UNKNOWN") for record in records)
    report_lines = [
        "# DVTD phase-aware source translation",
        "",
        f"- generated_at: {utc_now()}",
        f"- raw measured ZIP members: {len(measured_records)} / 44",
        f"- calculated controls: {len(controls)} / 44",
        f"- DVTD zip SHA-256: `{zip_hash}`",
        f"- fit band: {DVTD_FIT_BAND[0]:.0f}..{DVTD_FIT_BAND[1]:.0f} Hz",
        "- measured phase is fitted as complex H; calculated rows are controls only",
        "- no four-corner registration or product body is emitted",
        "",
        "## Status counts",
        "",
    ]
    report_lines.extend(f"- {key}: {value}" for key, value in sorted(status_counts.items()))
    report_lines.extend([
        "",
        "## Evidence boundary",
        "",
        "`PACKED_CONJUGATE` means the single measured corner survived the owned",
        "quantizer and runtime response path. It does not mean musical/product",
        "approval. `REFUSED_REAL_ROOT_ROW` remains explicit evidence and cannot",
        "enter the conjugate editor by conversion.",
    ])
    write_json(
        out_dir / "dvtd_translation.json",
        {
            "schema_version": 1,
            "tool": "tools.translate_sources dvtd",
            "tool_version": TOOL_VERSION,
            "generated_at": utc_now(),
            "source": {
                "family": "DVTD",
                "measured_root": str(dvtd_root),
                "zip": str(dvtd_zip),
                "zip_sha256": zip_hash,
                "fit_input_mode": "measured and calculated members read directly from dvtd.zip",
                "measured_count_available": len(measured),
                "calculated_count_available": len(calculated),
            },
            "method": {
                "fit": "fit-complex-candidates",
                "input": "freq_Hz, magnitude, phase_rad",
                "delay": "pure arrival onset only",
                "body_policy": "one response is one corner; explicit four-corner registration remains pending",
            },
            "records": [
                {
                    "model_id": record["source_provenance"]["model_id"],
                    "role": record["source_provenance"]["role"],
                    "status": record.get("status"),
                    "fit": record.get("fit"),
                    "representability": record.get("representability"),
                    "source_provenance": record.get("source_provenance"),
                    "result_path": str(
                        (out_dir / "fits" / f"{record['source_provenance']['model_id']}.{record['source_provenance']['role']}.fit.json").relative_to(out_dir)
                    ),
                }
                for record in records
            ],
        },
    )
    (out_dir / "REPORT.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    if args.plots:
        contact_sheet(measured_records, out_dir / "measured_contact_sheet.png", "DVTD measured")
        contact_sheet(controls, out_dir / "calculated_control_contact_sheet.png", "DVTD calculated control")
    print(f"wrote {out_dir} ({len(measured_records)} measured, {len(controls)} calculated controls)")
    return 0


def load_sofa(path: Path) -> tuple[np.ndarray, float, np.ndarray, dict]:
    import h5py

    def attribute_value(value):
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        array = np.asarray(value)
        if array.ndim == 0 and array.dtype.kind in "biufc":
            return array.item()
        if array.dtype.kind in "biufcU":
            return array.tolist()
        return str(value)

    with h5py.File(path, "r") as handle:
        ir = np.asarray(handle["Data.IR"], dtype=np.float64)
        sr = float(np.asarray(handle["Data.SamplingRate"]).ravel()[0])
        positions = np.asarray(handle["SourcePosition"], dtype=np.float64)
        attrs = {}
        for key, value in handle.attrs.items():
            attrs[key] = attribute_value(value)
    if ir.ndim != 3 or ir.shape[1] < 1 or positions.shape[0] != ir.shape[0]:
        raise ValueError(f"unsupported SOFA shapes IR={ir.shape} positions={positions.shape}")
    return ir, sr, positions, attrs


def load_sofa_metadata(path: Path) -> dict:
    import h5py

    with h5py.File(path, "r") as handle:
        ir_shape = list(handle["Data.IR"].shape)
        position_shape = list(handle["SourcePosition"].shape)
        sr = float(np.asarray(handle["Data.SamplingRate"]).ravel()[0])
        attrs = {}
        for key in ("License", "Title", "Origin", "SOFAConventions"):
            if key not in handle.attrs:
                continue
            value = handle.attrs[key]
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            else:
                array = np.asarray(value)
                if array.ndim == 0 and array.dtype.kind in "biufcU":
                    value = array.item()
                elif array.dtype.kind in "biufcU":
                    value = array.tolist()
                else:
                    value = str(value)
            attrs[key] = value
    return {
        "sample_rate_hz": sr,
        "ir_shape": ir_shape,
        "source_position_shape": position_shape,
        "attributes": attrs,
    }


def prepare_sofa_surface(ir: np.ndarray, sr: float, band: tuple[float, float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pad = max(4096, 1 << int(math.ceil(math.log2(ir.shape[-1] * 2))))
    native_freqs = np.fft.rfftfreq(pad, 1.0 / sr)
    mask = (native_freqs >= band[0]) & (native_freqs <= band[1])
    band_freqs = native_freqs[mask]
    spectrum = np.fft.rfft(ir, n=pad, axis=-1)[..., mask]
    onset_s = np.argmax(np.abs(ir), axis=-1).astype(np.float64) / sr
    spectrum *= np.exp(1j * 2.0 * np.pi * band_freqs[None, None, :] * onset_s[..., None])
    grid = log_grid(*band)
    surface = np.empty((ir.shape[0], ir.shape[1], grid.size), dtype=np.complex128)
    for direction in range(ir.shape[0]):
        for ear in range(ir.shape[1]):
            surface[direction, ear] = interpolate_complex(band_freqs, spectrum[direction, ear], grid)
    return grid, surface, onset_s


def translate_sofa(args: argparse.Namespace, family: str, dataset: str, prefix: str) -> int:
    sofa = ensure_file(args.sofa, f"{family} SOFA")
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ir, sr, positions, attrs = load_sofa(sofa)
    grid, surface, onset_s = prepare_sofa_surface(ir, sr, HRTF_FIT_BAND)
    surface_mag_db = 20.0 * np.log10(np.maximum(np.abs(surface), 1.0e-12))
    neutral_mag_db = np.median(surface_mag_db.reshape(-1, grid.size), axis=0)
    neutral_phase = np.angle(np.mean(np.exp(1j * np.angle(surface.reshape(-1, grid.size))), axis=0))
    neutral = np.exp(neutral_mag_db / 20.0 * math.log(10.0)) * np.exp(1j * neutral_phase)
    npz_path = out_dir / f"{prefix}_full_directional_surface.npz"
    np.savez_compressed(
        npz_path,
        freqs_hz=grid,
        source_position=positions,
        h_re=surface.real.astype(np.float32),
        h_im=surface.imag.astype(np.float32),
        onset_seconds=onset_s,
        neutral_h_re=neutral.real,
        neutral_h_im=neutral.imag,
        neutral_mag_db=neutral_mag_db,
        neutral_phase_rad=neutral_phase,
    )
    neutral_input = out_dir / "neutral.complex_tf.json"
    neutral_fit_path = out_dir / "neutral.fit.json"
    write_json(
        neutral_input,
        {
            "schema_version": 1,
            "source": {
                "family": family,
                "dataset": dataset,
                "role": "median_neutral_control",
                "sofa": str(sofa),
                "sofa_sha256": sha256_file(sofa),
            },
            "freqs_hz": grid.tolist(),
            "h_re": neutral.real.tolist(),
            "h_im": neutral.imag.tolist(),
            "adapter": {
                "fit_band_hz": list(HRTF_FIT_BAND),
                "grid_points": FIT_GRID_POINTS,
                "delay_removal": "per-direction/per-ear HRIR onset only",
                "neutral_estimator": "median magnitude dB + circular mean phase across all directions and ears",
            },
        },
    )
    fit = run_fitter(neutral_input, neutral_fit_path)
    packed_curve = np.asarray([point["packed_mag_db"] for point in fit["curve"]])
    residual = surface_mag_db - packed_curve[None, None, :]
    phase_residual = np.angle(
        np.exp(1j * (np.angle(surface) - neutral_phase[None, None, :]))
    )
    residual_name = f"{prefix}_directional_residual.npz"
    np.savez_compressed(
        out_dir / residual_name,
        residual_db=residual.astype(np.float32),
        phase_residual_rad=phase_residual.astype(np.float32),
    )
    surface_json_name = f"{prefix}_surface.json"
    write_json(
        out_dir / surface_json_name,
        {
            "schema_version": 1,
            "tool": f"tools.translate_sources {prefix}",
            "tool_version": TOOL_VERSION,
            "generated_at": utc_now(),
            "source": {
                "sofa": str(sofa),
                "sha256": sha256_file(sofa),
                "sample_rate_hz": sr,
                "ir_shape": list(ir.shape),
                "direction_count": int(ir.shape[0]),
                "ear_count": int(ir.shape[1]),
                "source_position_type": "SOFA spherical degree, degree, metre",
                "attributes": attrs,
            },
            "surface": {
                "npz": npz_path.name,
                "residual_npz": residual_name,
                "freq_band_hz": list(HRTF_FIT_BAND),
                "grid_points": FIT_GRID_POINTS,
                "full_directional_extraction": True,
                "directional_fit": "not run; only the named median/neutral control was fitted",
                "residual_db_min": float(np.min(residual)),
                "residual_db_max": float(np.max(residual)),
                "residual_db_rms": float(np.sqrt(np.mean(residual * residual))),
                "phase_residual_rad_min": float(np.min(phase_residual)),
                "phase_residual_rad_max": float(np.max(phase_residual)),
                "phase_residual_rad_rms": float(np.sqrt(np.mean(phase_residual * phase_residual))),
            },
            "neutral_fit": {
                "input": neutral_input.name,
                "result": neutral_fit_path.name,
                "status": fit.get("status"),
                "fit": fit.get("fit"),
                "representability": fit.get("representability"),
            },
            "body_policy": "full surface is evidence; no four-corner directional body is inferred",
        },
    )
    print(f"wrote {out_dir} ({ir.shape[0]} directions x {ir.shape[1]} ears; {family} neutral {fit.get('status')})")
    return 0


def sonicom(args: argparse.Namespace) -> int:
    return translate_sofa(args, "SONICOM", "P0001 raw 48kHz", "sonicom")


def aalto(args: argparse.Namespace) -> int:
    return translate_sofa(args, "AALTO", "NF_LIB_HRTF_measured", "aalto")


def read_phononic_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    data = np.loadtxt(path, delimiter=",", skiprows=1, dtype=np.float64)
    if data.ndim != 2 or data.shape[1] <= 10:
        raise ValueError(f"phononic CSV has unexpected shape {data.shape}")
    if not np.all(np.isfinite(data)):
        raise ValueError("phononic CSV contains nonfinite values")
    structure = data[:, :10]
    absorption = data[:, 10:]
    if absorption.min() < -1.0e-8 or absorption.max() > 1.0 + 1.0e-8:
        raise ValueError(
            f"phononic absorption is outside [0,1]: {absorption.min()}..{absorption.max()}"
        )
    # The dataset README defines the response as 100..10000 Hz.  The 109
    # response columns are persisted against this explicit uniform axis.
    freqs = np.linspace(100.0, 10000.0, absorption.shape[1], dtype=np.float64)
    return structure, np.clip(absorption, 0.0, 1.0), freqs


def phononic_peaks(absorption: np.ndarray, freqs: np.ndarray) -> list[dict]:
    from scipy.signal import find_peaks, peak_widths

    indices, properties = find_peaks(
        absorption,
        height=0.20,
        prominence=0.05,
        width=1,
    )
    if indices.size == 0:
        return []
    widths = peak_widths(absorption, indices, rel_height=0.5)[0]
    step_hz = float(freqs[1] - freqs[0])
    result = []
    for pos, index in enumerate(indices):
        alpha = float(absorption[index])
        fwhm_hz = max(float(widths[pos] * step_hz), step_hz)
        result.append(
            {
                "hz": float(freqs[index]),
                "alpha": alpha,
                "fwhm_hz": fwhm_hz,
                "prominence": float(properties["prominences"][pos]),
                "residual_db": float(10.0 * math.log10(max(1.0e-4, 1.0 - alpha))),
                "zero_r": float(np.clip(math.exp(-math.pi * fwhm_hz / RUNTIME_SR), 0.5, 0.9995)),
            }
        )
    return result


def phononic_geometry_chain(structure: np.ndarray, start: int, end: int, count: int) -> list[int]:
    lo = structure.min(axis=0)
    span = np.maximum(structure.max(axis=0) - lo, 1.0e-9)
    normalized = (structure - lo) / span
    chosen = [int(start)]
    for step in range(1, count - 1):
        target = normalized[start] * (1.0 - step / (count - 1)) + normalized[end] * (step / (count - 1))
        distance = np.linalg.norm(normalized - target, axis=1)
        distance[np.asarray(chosen, dtype=np.int64)] = np.inf
        chosen.append(int(np.argmin(distance)))
    chosen.append(int(end))
    return chosen


def track_phononic_lanes(peak_rows: list[list[dict]], max_lanes: int = 6) -> list[list[dict]]:
    """Track observed notch peaks without per-pose lane resorting.

    Lane order is initialized once at the first waypoint. Later rows use a
    continuity assignment in log-frequency space; unmatched rows stay
    explicitly inactive rather than being repaired or replaced.
    """
    from scipy.optimize import linear_sum_assignment

    initial = sorted(
        sorted(peak_rows[0], key=lambda item: item["prominence"], reverse=True)[:max_lanes],
        key=lambda item: item["hz"],
    )
    lanes: list[list[dict]] = [[] for _ in range(max_lanes)]
    previous = [None] * max_lanes
    for lane, observation in enumerate(initial):
        lanes[lane].append({"state": "active", **observation, "assignment": "initial_frequency_order"})
        previous[lane] = observation
    for lane in range(len(initial), max_lanes):
        lanes[lane].append({"state": "inactive", "reason": "no_initial_peak"})

    for peaks in peak_rows[1:]:
        usable = [peak for peak in peaks if peak["hz"] > 0.0]
        assigned: dict[int, int] = {}
        active_lanes = [index for index, item in enumerate(previous) if item is not None]
        if active_lanes and usable:
            cost = np.asarray(
                [[abs(math.log(peak["hz"] / previous[lane]["hz"])) for peak in usable] for lane in active_lanes],
                dtype=np.float64,
            )
            lane_idx, peak_idx = linear_sum_assignment(cost)
            for row, column in zip(lane_idx, peak_idx):
                # A two-octave jump is treated as a missing observation; it
                # is not silently reassigned to a different stage.
                if cost[row, column] <= math.log(2.0):
                    assigned[active_lanes[int(row)]] = int(column)
        used_peaks = set(assigned.values())
        free_lanes = [lane for lane in range(max_lanes) if previous[lane] is None]
        for peak_index in sorted(
            (index for index in range(len(usable)) if index not in used_peaks),
            key=lambda index: usable[index]["hz"],
        ):
            if not free_lanes:
                break
            lane = free_lanes.pop(0)
            assigned[lane] = peak_index
            used_peaks.add(peak_index)
        for lane in range(max_lanes):
            if lane in assigned:
                observation = usable[assigned[lane]]
                assignment = (
                    "continuity_log_frequency"
                    if previous[lane] is not None
                    else "new_observed_lane_frequency_order"
                )
                lanes[lane].append({"state": "active", **observation, "assignment": assignment})
                previous[lane] = observation
            else:
                lanes[lane].append({"state": "inactive", "reason": "no_continuous_peak"})
    return lanes


def phononic(args: argparse.Namespace) -> int:
    csv_path = ensure_file(args.phononic, "phononic CSV")
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    structure, absorption, freqs = read_phononic_csv(csv_path)
    residual_db = 10.0 * np.log10(np.maximum(1.0e-4, 1.0 - absorption))
    peak_rows = [phononic_peaks(row, freqs) for row in absorption]
    single_low = [
        (row[0]["alpha"] / row[0]["fwhm_hz"], index)
        for index, row in enumerate(peak_rows)
        if len(row) == 1 and row[0]["hz"] < 2000.0
    ]
    two_peak = [
        (sum(peak["alpha"] for peak in row[:2]), index)
        for index, row in enumerate(peak_rows)
        if len(row) >= 2
    ]
    if not single_low or not two_peak:
        raise ValueError("phononic dataset did not contain the required endpoint peak classes")
    start = max(single_low)[1]
    end = max(two_peak)[1]
    path_indices = phononic_geometry_chain(structure, start, end, args.waypoints)
    path_peaks = [peak_rows[index] for index in path_indices]
    lanes = track_phononic_lanes(path_peaks)
    np.savez_compressed(
        out_dir / "phononic_full_surface.npz",
        freqs_hz=freqs,
        structure_mm=structure.astype(np.float32),
        absorption=absorption.astype(np.float32),
        residual_db=residual_db.astype(np.float32),
        path_indices=np.asarray(path_indices, dtype=np.int64),
    )
    lane_rows = []
    for waypoint, sample_index in enumerate(path_indices):
        lane_rows.append(
            {
                "waypoint": waypoint,
                "sample_index": int(sample_index),
                "geometry_mm": [float(value) for value in structure[sample_index]],
                "lanes": [lane[waypoint] for lane in lanes],
            }
        )
    source_hash = sha256_file(csv_path)
    readme_path = csv_path.parent.parent / "README.md"
    payload = {
        "schema_version": 1,
        "tool": "tools.translate_sources phononic",
        "tool_version": TOOL_VERSION,
        "generated_at": utc_now(),
        "source": {
            "csv": str(csv_path),
            "sha256": source_hash,
            "readme": str(readme_path),
            "readme_sha256": sha256_file(readme_path) if readme_path.is_file() else None,
            "dataset_rows": int(structure.shape[0]),
            "structure_columns": int(structure.shape[1]),
            "response_columns": int(absorption.shape[1]),
            "frequency_axis_hz": [float(freqs[0]), float(freqs[-1])],
            "response_meaning": "absorption coefficient alpha",
        },
        "surface": {
            "npz": "phononic_full_surface.npz",
            "full_surface_extracted": True,
            "residual_definition": "10*log10(max(1e-4, 1-alpha))",
        },
        "selection": {
            "path_type": "nearest-neighbour geometry-space chain between observed endpoint structures",
            "waypoints": len(path_indices),
            "endpoint_start": {"sample_index": int(start), "criterion": "deepest narrow single peak below 2 kHz"},
            "endpoint_end": {"sample_index": int(end), "criterion": "strongest two-peak split"},
            "lanes": 6,
            "lane_order": "initialized once, then continuity-assigned in log-frequency space; no per-waypoint resorting",
            "rows": lane_rows,
        },
        "body_policy": "observed zero-lane evidence only; no four-corner body or packed promotion",
    }
    write_json(out_dir / "phononic_translation.json", payload)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = len(path_indices)
    cols = int(math.ceil(math.sqrt(rows)))
    fig, axes = plt.subplots(cols, cols, figsize=(2.0 * cols, 1.6 * cols), sharex=True, sharey=True)
    axes = np.atleast_1d(axes).ravel()
    lo = math.floor(float(residual_db[path_indices].min()) / 5.0) * 5.0
    hi = math.ceil(float(residual_db[path_indices].max()) / 5.0) * 5.0
    for ax, waypoint, sample_index in zip(axes, range(rows), path_indices):
        ax.semilogx(freqs, residual_db[sample_index], color="#5bef6f", lw=0.7)
        for lane in lanes:
            observation = lane[waypoint]
            if observation["state"] == "active":
                ax.axvline(observation["hz"], color="#ffb13e", lw=0.4, alpha=0.7)
        ax.set_title(f"wp {waypoint} #{sample_index}", fontsize=5)
        ax.set_xlim(float(freqs[0]), float(freqs[-1]))
        ax.set_ylim(lo, hi)
        ax.set_xticks([])
        ax.set_yticks([])
    for ax in axes[rows:]:
        ax.axis("off")
    fig.suptitle("Phononic full surface route — green residual, amber tracked zero observations", fontsize=9)
    fig.tight_layout(pad=0.3)
    fig.savefig(out_dir / "phononic_route_contact_sheet.png", dpi=130)
    plt.close(fig)
    report = [
        "# Phononic full-surface translation",
        "",
        f"- source rows: {structure.shape[0]}",
        f"- response samples: {absorption.shape[1]} at {freqs[0]:.0f}..{freqs[-1]:.0f} Hz",
        f"- extracted surface: `phononic_full_surface.npz` ({structure.shape[0]} rows)",
        f"- persistent route: {len(path_indices)} observed geometry waypoints, six continuity lanes",
        "- lane values are notch observations derived from absorption peaks; they are not a packed body",
        "- no per-waypoint lane resorting, smoothing, or synthesized missing peaks",
        "",
        "The full surface is retained for later selection. The route is a controlled evidence slice, not a claim that every candidate is a product pose.",
    ]
    (out_dir / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"wrote {out_dir} ({structure.shape[0]} rows; {len(path_indices)} route waypoints)")
    return 0


def object_slug(path: Path) -> str:
    import re

    return re.sub(r"[^a-zA-Z0-9._-]+", "-", path.stem).strip("-").lower() or "object"


def objects(args: argparse.Namespace) -> int:
    import soundfile as sf

    root = args.objects.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"measured object directory does not exist: {root}")
    wavs = sorted(root.rglob("*.wav"))
    if not wavs:
        raise ValueError(f"no WAV files found under {root}")
    out_dir = args.out.resolve()
    curve_dir = out_dir / "curves"
    curve_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for path in wavs:
        samples, sr = sf.read(str(path), dtype="float64", always_2d=True)
        if not np.all(np.isfinite(samples)):
            raise ValueError(f"nonfinite audio samples: {path}")
        n = samples.shape[0]
        nfft = 1 << int(math.ceil(math.log2(max(n, 2))))
        native_freqs = np.fft.rfftfreq(nfft, 1.0 / sr)
        spectrum = np.fft.rfft(samples, n=nfft, axis=0) / float(nfft)
        hi = min(20000.0, float(sr) * 0.5 * 0.999)
        grid = log_grid(20.0, hi)
        mask = (native_freqs >= grid[0]) & (native_freqs <= grid[-1])
        h = np.empty((grid.size, samples.shape[1]), dtype=np.complex128)
        for channel in range(samples.shape[1]):
            h[:, channel] = interpolate_complex(native_freqs[mask], spectrum[mask, channel], grid)
        curve_name = f"{object_slug(path)}.npz"
        np.savez_compressed(
            curve_dir / curve_name,
            freqs_hz=grid,
            h_re=h.real,
            h_im=h.imag,
            magnitude_db=(20.0 * np.log10(np.maximum(np.abs(h), 1.0e-12))).astype(np.float32),
        )
        records.append(
            {
                "file": str(path),
                "sha256": sha256_file(path),
                "sample_rate_hz": int(sr),
                "frames": int(n),
                "channels": int(samples.shape[1]),
                "curve": f"curves/{curve_name}",
                "interpretation": "direct FFT spectral observation of supplied waveform",
                "transfer_function_fit": "REFUSED_MISSING_EXCITATION_OR_DECONVOLUTION_METADATA",
            }
        )
    payload = {
        "schema_version": 1,
        "tool": "tools.translate_sources objects",
        "tool_version": TOOL_VERSION,
        "generated_at": utc_now(),
        "source": {"root": str(root), "file_count": len(wavs)},
        "method": {
            "curve": "full-record FFT, divided by fixed FFT length only",
            "band_hz": [20.0, 20000.0],
            "per_render_normalization": False,
            "phase_status": "waveform FFT phase; not a transfer-function phase",
        },
        "records": records,
        "body_policy": "no four-corner inference; no packed promotion without excitation/deconvolution evidence",
    }
    write_json(out_dir / "object_translation.json", payload)
    report = [
        "# Measured object spectral observations",
        "",
        f"- WAV files converted: {len(records)}",
        "- curves are fixed-FFT-length spectral observations of the supplied files",
        "- no per-file render normalization was applied",
        "- transfer-function fitting is refused because excitation/deconvolution metadata is absent",
        "- no four-corner body is inferred",
    ]
    (out_dir / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"wrote {out_dir} ({len(records)} WAV spectral observations)")
    return 0


def body_parity(args: argparse.Namespace) -> int:
    compiler = ROOT / "target" / "release" / "body-from-geometry.exe"
    if not compiler.is_file():
        raise FileNotFoundError(f"body compiler missing: {compiler}")
    fits_dir = args.fits_dir.resolve()
    fit_paths = sorted(fits_dir.glob("*.measured.fit.json"))
    if not fit_paths:
        raise ValueError(f"no measured fit results found under {fits_dir}")
    if args.limit is not None:
        fit_paths = fit_paths[:args.limit]
    out_dir = args.out.resolve()
    probe_dir = out_dir / "probes"
    probe_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for fit_path in fit_paths:
        fit = json.loads(fit_path.read_text(encoding="utf-8"))
        stages = fit.get("stages", [])
        params = fit.get("continuous_seed_params", [])
        if fit.get("status") != "PACKED_CONJUGATE" or len(stages) != 6 or len(params) != 6:
            records.append({"fit": str(fit_path), "status": "SKIPPED_NOT_PACKED_CONJUGATE"})
            continue
        # This is deliberately a repeated-corner compiler probe, not a product
        # registration. It verifies the fitter's words against the canonical
        # body compiler while leaving cross-corner authoring pending.
        geometry = {
            "name": f"body-parity-probe-{fit_path.stem}",
            "probe_policy": "same fitted corner repeated four times; not a product body",
            "corners": [params, params, params, params],
        }
        geometry_path = probe_dir / f"{fit_path.stem}.geometry.json"
        body_path = probe_dir / f"{fit_path.stem}.body240"
        cart_path = probe_dir / f"{fit_path.stem}.cart.json"
        write_json(geometry_path, geometry)
        completed = subprocess.run(
            [str(compiler), str(geometry_path), str(body_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or not body_path.is_file():
            records.append(
                {
                    "fit": str(fit_path),
                    "status": "BODY_COMPILER_REFUSED",
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            )
            continue
        body = body_path.read_bytes()
        expected_corner = [stage["packed_words"] for stage in stages]
        expected = [word for _corner in range(4) for stage in expected_corner for word in stage]
        actual = list(struct.unpack("<120H", body)) if len(body) == 240 else []
        cart = {
            "name": geometry["name"],
            "corners": [
                {"label": label, "boost": 1.0, "packedWords": expected_corner}
                for label in ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
            ],
        }
        write_json(cart_path, cart)
        cart_words = [word for corner in cart["corners"] for stage in corner["packedWords"] for word in stage]
        records.append(
            {
                "fit": str(fit_path),
                "body": str(body_path),
                "cart": str(cart_path),
                "body_bytes": len(body),
                "body_words_match_fitter": actual == expected,
                "body_cart_words_match": actual == cart_words,
                "compiler_stdout": completed.stdout.strip(),
                "status": "PASS" if len(body) == 240 and actual == expected == cart_words else "FAIL",
            }
        )
    passed = sum(record.get("status") == "PASS" for record in records)
    write_json(
        out_dir / "body_parity.json",
        {
            "schema_version": 1,
            "tool": "tools.translate_sources body-parity",
            "generated_at": utc_now(),
            "scope": "repeated-corner compiler probes from DVTD measured fit results",
            "product_promotion": False,
            "records": records,
            "summary": {"requested": len(fit_paths), "passed": passed, "failed_or_skipped": len(records) - passed},
        },
    )
    (out_dir / "REPORT.md").write_text(
        "\n".join(
            [
                "# DVTD body/cart parity probes",
                "",
                f"- fit results checked: {len(fit_paths)}",
                f"- passed: {passed}",
                "- probe body repeats one fitted corner four times; it is not a registered product body",
                "- canonical body compiler output was compared to fitter packed words and serialized packedWords",
                "- cross-corner stage registration remains pending",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_dir} ({passed}/{len(fit_paths)} body/cart parity probes passed)")
    return 0 if passed == len(fit_paths) else 1


def inventory(args: argparse.Namespace) -> int:
    dvtd_zip = ensure_file(args.dvtd_zip, "DVTD zip")
    sofa_paths = [ensure_file(args.sonicom, "SONICOM SOFA"), ensure_file(args.aalto, "Aalto SOFA")]
    phononic = ensure_file(args.phononic, "phononic CSV")
    objects = args.objects.resolve()
    hrtf_root = args.hrtf_root.resolve()
    if not hrtf_root.is_dir():
        raise FileNotFoundError(f"HRTF root does not exist: {hrtf_root}")
    with zipfile.ZipFile(dvtd_zip) as archive:
        names = archive.namelist()
        dvtd_counts = {
            "members": len(names),
            "measured_tables": sum(name.endswith("-vvtf-measured.txt") for name in names),
            "calculated_tables": sum(name.endswith("-vvtf-calculated.txt") for name in names),
        }
    with phononic.open("r", encoding="utf-8-sig") as handle:
        header = handle.readline().strip().split(",")
        rows = sum(1 for _ in handle)
    object_files = sorted(path.name for path in objects.rglob("*.wav")) if objects.is_dir() else []
    sofa_meta = []
    for path in sofa_paths:
        ir, sr, positions, attrs = load_sofa(path)
        sofa_meta.append({
            "path": str(path),
            "sha256": sha256_file(path),
            "sample_rate_hz": sr,
            "ir_shape": list(ir.shape),
            "direction_count": int(positions.shape[0]),
            "attributes": {key: attrs.get(key) for key in ("License", "Title", "Origin", "Comment") if key in attrs},
        })
    hrtf_inventory = []
    for path in sorted(hrtf_root.rglob("*.sofa")):
        metadata = load_sofa_metadata(path)
        name = path.name.lower()
        if "raw_48khz" in name:
            status = "translated_full_surface_and_neutral_control"
        elif name == "nf_lib_hrtf_measured.sofa":
            status = "translated_full_surface_and_neutral_control"
        else:
            status = "inventory_only_streamed_surface_pending"
        hrtf_inventory.append(
            {
                "path": str(path),
                "relative_path": path.relative_to(hrtf_root).as_posix(),
                "size_bytes": path.stat().st_size,
                **metadata,
                "sha256": None,
                "hash_note": "hash omitted for inventory-only HRTF families; selected translated sources carry hashes in their bundles",
                "translation_status": status,
            }
        )
    write_json(
        args.out.resolve(),
        {
            "schema_version": 1,
            "tool": "tools.translate_sources inventory",
            "generated_at": utc_now(),
            "dvtd": {"zip": str(dvtd_zip), "sha256": sha256_file(dvtd_zip), **dvtd_counts},
            "sofa": sofa_meta,
            "all_hrtf_sofa": hrtf_inventory,
            "phononic": {
                "path": str(phononic),
                "sha256": sha256_file(phononic),
                "data_rows": rows,
                "columns": len(header),
                "structure_columns": header[:10],
                "response_columns": header[10:],
                "status": "translated_full_surface; see tools.translate_sources phononic",
            },
            "measured_objects": {
                "path": str(objects),
                "wav_count": len(object_files),
                "files": object_files,
                "status": "translated_direct_spectra; transfer-function fitting conditional on acquisition metadata",
            },
            "translation_order": ["DVTD measured complex fit", "SONICOM full surface + neutral control", "Aalto", "phononic", "measured objects"],
        },
    )
    print(f"wrote {args.out.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    dvtd_parser = sub.add_parser("dvtd", help="fit all available DVTD measured tables and calculated controls")
    dvtd_parser.add_argument("--dvtd-root", type=Path, default=DEFAULT_DVTD_ROOT)
    dvtd_parser.add_argument("--dvtd-zip", type=Path, default=DEFAULT_DVTD_ZIP)
    dvtd_parser.add_argument("--out", type=Path, default=DEFAULT_OUT / "dvtd_phase_packed")
    dvtd_parser.add_argument("--limit", type=int, default=None, help="fit only the first N models of each role")
    dvtd_parser.add_argument("--plots", action="store_true", help="write shared-scale measured/control contact sheets")
    dvtd_parser.set_defaults(func=dvtd)
    sonicom_parser = sub.add_parser("sonicom", help="extract all directions and fit the named median/neutral control")
    sonicom_parser.add_argument("--sofa", type=Path, default=DEFAULT_SONICOM)
    sonicom_parser.add_argument("--out", type=Path, default=DEFAULT_OUT / "sonicom_raw_surface")
    sonicom_parser.set_defaults(func=sonicom)
    aalto_parser = sub.add_parser("aalto", help="extract all Aalto near-field directions and fit the neutral control")
    aalto_parser.add_argument("--sofa", type=Path, default=DEFAULT_AALTO)
    aalto_parser.add_argument("--out", type=Path, default=DEFAULT_OUT / "aalto_measured_surface")
    aalto_parser.set_defaults(func=aalto)
    phononic_parser = sub.add_parser("phononic", help="extract the full phononic surface and track six observed zero lanes")
    phononic_parser.add_argument("--phononic", type=Path, default=DEFAULT_PHONONIC)
    phononic_parser.add_argument("--out", type=Path, default=DEFAULT_OUT / "phononic_full_surface")
    phononic_parser.add_argument("--waypoints", type=int, default=64)
    phononic_parser.set_defaults(func=phononic)
    objects_parser = sub.add_parser("objects", help="convert measured object WAVs into labeled direct spectral observations")
    objects_parser.add_argument("--objects", type=Path, default=DEFAULT_OBJECTS)
    objects_parser.add_argument("--out", type=Path, default=DEFAULT_OUT / "measured_object_spectra")
    objects_parser.set_defaults(func=objects)
    parity_parser = sub.add_parser("body-parity", help="probe canonical body compiler and packedWords parity for fitted DVTD corners")
    parity_parser.add_argument("--fits-dir", type=Path, default=DEFAULT_OUT / "dvtd_phase_packed_full" / "fits")
    parity_parser.add_argument("--out", type=Path, default=DEFAULT_OUT / "dvtd_body_parity")
    parity_parser.add_argument("--limit", type=int, default=None)
    parity_parser.set_defaults(func=body_parity)
    inventory_parser = sub.add_parser("inventory", help="write a provenance-first inventory for the listed families")
    inventory_parser.add_argument("--dvtd-zip", type=Path, default=DEFAULT_DVTD_ZIP)
    inventory_parser.add_argument("--sonicom", type=Path, default=DEFAULT_SONICOM)
    inventory_parser.add_argument("--aalto", type=Path, default=DEFAULT_AALTO)
    inventory_parser.add_argument("--phononic", type=Path, default=DEFAULT_PHONONIC)
    inventory_parser.add_argument("--objects", type=Path, default=DEFAULT_OBJECTS)
    inventory_parser.add_argument("--hrtf-root", type=Path, default=Path(r"C:\Users\hooki\trench-filters\data\hrtf"))
    inventory_parser.add_argument("--out", type=Path, default=DEFAULT_OUT / "source_inventory.json")
    inventory_parser.set_defaults(func=inventory)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except (FileNotFoundError, OSError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
