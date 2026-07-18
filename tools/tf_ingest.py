"""tf_ingest — turn ANY measured source into a transfer function on the
standard grid (the internal representative for measured-object fitting).

Two lanes in, one object out:
  ir_to_tf(wav)        impulse response -> fractional-octave-smoothed |H(f)| dB
  modes_to_tf(modes)   modal table [(freq_hz, decay_t60_s | bw_hz, level_db)]
                       -> synthesized |H(f)| dB (resonator bank)

Output dict: {"freqs_hz": [...], "mag_db": [...], "source": str, "kind": str}
Feed to trench_ffi.fit_corner_from_magnitude / the tf_oracle lane.

Grid = the QC grid (30 Hz .. 19.2 kHz log, 512 pts) so gates and plots share
an axis with every existing body judgment.
"""
from __future__ import annotations
import json, math, sys
from pathlib import Path
import numpy as np

FREQS = np.geomspace(30.0, 19200.0, 512)


def ir_to_tf(wav_path, smooth_oct=1 / 6):
    from scipy.io import wavfile
    sr, x = wavfile.read(wav_path)
    x = x.astype(np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    x /= (np.max(np.abs(x)) + 1e-12)
    n = int(2 ** np.ceil(np.log2(len(x))))
    H = np.abs(np.fft.rfft(x, n))
    f = np.fft.rfftfreq(n, 1 / sr)
    mag = np.interp(FREQS, f, H)
    # fractional-octave smoothing: log-domain moving average per grid point
    lo = np.log2(np.maximum(FREQS, 1.0))
    sm = np.empty_like(mag)
    for i, c in enumerate(lo):
        w = np.abs(lo - c) <= smooth_oct / 2
        sm[i] = np.sqrt(np.mean(mag[w] ** 2))
    db = 20 * np.log10(np.maximum(sm, 1e-9))
    db -= np.median(db)  # floor at 0 dB median, same convention as body QC
    return {"freqs_hz": FREQS.tolist(), "mag_db": db.tolist(),
            "source": str(wav_path), "kind": "ir"}


def modes_to_tf(modes, source="modal-table"):
    """modes: list of dicts {freq_hz, t60_s | bw_hz, level_db (default 0)}.
    Resonator bank magnitude: each mode a 2-pole peak, bandwidth from T60."""
    mag = np.zeros_like(FREQS)
    for m in modes:
        f0 = float(m["freq_hz"])
        bw = float(m["bw_hz"]) if "bw_hz" in m else 2.2 / float(m["t60_s"])  # T60 -> -3dB BW
        amp = 10 ** (float(m.get("level_db", 0.0)) / 20)
        # magnitude of a resonance: 1 / sqrt(1 + ((f^2-f0^2)/(f*bw))^2)
        mag += amp / np.sqrt(1.0 + ((FREQS ** 2 - f0 ** 2) / np.maximum(FREQS * bw, 1e-9)) ** 2)
    db = 20 * np.log10(np.maximum(mag, 1e-9))
    db -= np.median(db)
    return {"freqs_hz": FREQS.tolist(), "mag_db": db.tolist(),
            "source": source, "kind": "modes"}


def main():
    if len(sys.argv) < 2:
        print("usage: tf_ingest.py <ir.wav | modes.json> [out.json]"); sys.exit(1)
    p = Path(sys.argv[1])
    if p.suffix.lower() == ".json":
        tf = modes_to_tf(json.loads(p.read_text())["modes"], source=str(p))
    else:
        tf = ir_to_tf(p)
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else p.with_suffix(".tf.json")
    out.write_text(json.dumps(tf))
    db = np.array(tf["mag_db"])
    print(f"{p.name} -> {out.name}  ({tf['kind']}, crown {db.max():+.1f} dB @ "
          f"{FREQS[int(np.argmax(db))]:.0f} Hz, floor 0 dB median)")


if __name__ == "__main__":
    main()
