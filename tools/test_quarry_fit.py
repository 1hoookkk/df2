import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi
from pyruntime.quarry_fit import (
    crank_complex_pole_radii,
    fit_envelope,
    packed_response_db,
    shape_residual_db,
)


def _bump(freqs, center, gain_db, width_oct):
    return gain_db * np.exp(-((np.log2(freqs / center) / width_oct) ** 2))


def test_shape_residual_ignores_global_gain():
    freqs = np.logspace(np.log10(40.0), np.log10(7_800.0), 64)
    target = np.sin(np.log(freqs))
    assert shape_residual_db(target, target - 27.0, freqs) < 1e-12


def test_radius_crank_preserves_complex_center_frequency_and_real_support_rows():
    theta = 0.4
    radius = 0.8
    complex_row = (2.0, 1.0, 2.0 - 2.0 * radius * np.cos(theta), 1.0 - radius * radius, 1.0)
    real_row = (2.0, 1.0, 2.0, 1.25, 1.0)
    rows, changed = crank_complex_pole_radii([complex_row, real_row])
    cranked = rows[0]
    cranked_radius = np.sqrt(1.0 - cranked[3])
    cranked_cos_theta = -(cranked[2] - 2.0) / (2.0 * cranked_radius)
    assert changed == 1
    assert np.isclose(cranked_radius, 0.990)
    assert np.isclose(cranked_cos_theta, np.cos(theta))
    assert rows[1] == real_row


def test_bounded_quarry_fit_emits_stable_packed_body():
    assert trench_ffi.available()
    source_freqs = np.logspace(np.log10(40.0), np.log10(7_800.0), 128)
    source_db = (
        -18.0
        + _bump(source_freqs, 650.0, 20.0, 0.55)
        + _bump(source_freqs, 1_700.0, 16.0, 0.55)
    )
    fit = fit_envelope(
        source_freqs,
        source_db,
        seed=123,
    )
    fitted_db = packed_response_db(fit, source_freqs)
    assert len(fit.body_bytes) == trench_ffi.BODY_BYTES
    assert fit.packed_unstable_mask == 0
    assert fit.packed_nonfinite_mask == 0
    assert fit.packed_max_pole_radius < 1.0
    for row in fit.packed_rows:
        roots = np.roots((1.0, row[2] - 2.0, 1.0 - row[3]))
        if abs(float(np.imag(roots[0]))) > 1e-7:
            radius = float(abs(roots[0]))
            assert 0.98999 <= radius <= 0.99801
    assert shape_residual_db(source_db, fitted_db, source_freqs) < 8.0
