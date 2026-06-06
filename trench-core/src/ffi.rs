use crate::cartridge::{Cartridge, BODY_BYTES};
use crate::cascade::{NUM_COEFFS, NUM_STAGES};
use crate::dsp::BASE_AGC_TABLE;
use crate::engine::{FilterEngine, InputMode, SpatialMode};
use crate::minifloat::{decode, encode, pole_radius, PackedCorners};
use std::ffi::{c_char, c_void};
use std::ffi::CStr;

#[no_mangle]
pub unsafe extern "C" fn trench_engine_create() -> *mut c_void {
    let engine = Box::new(FilterEngine::new());
    Box::into_raw(engine) as *mut c_void
}

#[no_mangle]
pub unsafe extern "C" fn trench_engine_destroy(engine: *mut c_void) {
    if !engine.is_null() {
        let _ = Box::from_raw(engine as *mut FilterEngine);
    }
}

#[no_mangle]
pub unsafe extern "C" fn trench_engine_prepare(engine: *mut c_void, sample_rate: f64) {
    let engine = &mut *(engine as *mut FilterEngine);
    engine.prepare(sample_rate);
}

#[no_mangle]
pub unsafe extern "C" fn trench_engine_load_cartridge(
    engine: *mut c_void,
    json: *const c_char,
) -> i32 {
    let engine = &mut *(engine as *mut FilterEngine);
    if json.is_null() {
        return -1;
    }
    let c_str = CStr::from_ptr(json);
    let r_str = match c_str.to_str() {
        Ok(s) => s,
        Err(_) => return -2,
    };

    match Cartridge::from_json(r_str) {
        Ok(cart) => {
            engine.load_cartridge(cart);
            0
        }
        Err(_) => -3,
    }
}

/// Load a body directly from raw bytes. Must be exactly 240 bytes
/// (4 corners × 6 stages × 5 u16 words × 2 bytes). Routes through the same
/// canonical `Cartridge::from_body_bytes` → `PackedCorners` runtime path as a
/// JSON `packedWords` body — there is no separate DSP path for raw audition
/// bodies.
///
/// Returns: 0 on success, -1 null engine/ptr, -4 wrong length, -3 decode error.
#[no_mangle]
pub unsafe extern "C" fn trench_engine_load_body_bytes(
    engine: *mut c_void,
    bytes: *const u8,
    len: usize,
) -> i32 {
    if engine.is_null() || bytes.is_null() {
        return -1;
    }
    if len != BODY_BYTES {
        return -4;
    }
    let engine = &mut *(engine as *mut FilterEngine);
    let slice = std::slice::from_raw_parts(bytes, len);

    match Cartridge::from_body_bytes("audition", slice, 1.0) {
        Ok(cart) => {
            engine.load_cartridge(cart);
            0
        }
        Err(_) => -3,
    }
}

/// Decode one packed `u16` minifloat word to f64.
///
/// Stateless. This is the single source of the minifloat codec — Python tooling
/// calls it instead of reimplementing `decode`, so the bench and the plugin can
/// never disagree on what a word means.
#[no_mangle]
pub extern "C" fn trench_packed_decode(word: u16) -> f64 {
    decode(word)
}

/// Encode one f64 to the nearest packed `u16` minifloat word — the inverse of
/// `trench_packed_decode`.
///
/// Stateless, and the single source of the encode direction: Python tooling
/// calls it instead of reimplementing `encode`, so a body authored in Python
/// (coeffs -> words) packs to the EXACT words the shipped core would, and
/// therefore decodes back to what the author saw. decode is already owned;
/// exposing encode closes the only remaining packed-math operation that could
/// drift between Python and Rust — everything else (recombination,
/// kernel_to_biquad) is pure f64 arithmetic over these two codecs.
#[no_mangle]
pub extern "C" fn trench_packed_encode(value: f64) -> u16 {
    encode(value)
}

/// Copy the canonical 16-entry AGC (global compression) curve into `out`.
///
/// Stateless, read-only. `BASE_AGC_TABLE` (`crate::dsp`) is the canonical DLL
/// allocation before the engine applies its sample-rate adjustment. Python audit
/// tools read these exact f32 values instead of hand-copying the literal.
///
/// Returns the number of entries written (16), or -1 on null/short buffer.
#[no_mangle]
pub unsafe extern "C" fn trench_agc_table(out: *mut f32, len: usize) -> i32 {
    if out.is_null() || len < BASE_AGC_TABLE.len() {
        return -1;
    }
    let dst = std::slice::from_raw_parts_mut(out, BASE_AGC_TABLE.len());
    dst.copy_from_slice(&BASE_AGC_TABLE);
    BASE_AGC_TABLE.len() as i32
}

/// Factorize a TARGET magnitude curve into one fitted corner (kernel form).
///
/// `freqs`/`dbs` are `n` parallel sorted points `(freq_hz, db)`; writes 30 kernel
/// coefficients (6 stages × 5: c0..c4, stage-major) into `out`. This is a thin
/// wrapper over `arma::fit_corner_from_magnitude` — no new DSP, the fit stays
/// dumb (the taste lives in the curve). It exists so the factorizer bench (and a
/// Target Browser) drive the SAME fitter the proof test exercised.
///
/// Returns: 0 ok, -1 null ptr, -2 fewer than 2 points, -3 fitter returned None.
#[no_mangle]
pub unsafe extern "C" fn trench_fit_corner_from_magnitude(
    freqs: *const f64,
    dbs: *const f64,
    n: usize,
    runtime_sr: f64,
    out: *mut f64,
) -> i32 {
    if freqs.is_null() || dbs.is_null() || out.is_null() {
        return -1;
    }
    if n < 2 {
        return -2;
    }
    let fs = std::slice::from_raw_parts(freqs, n);
    let ds = std::slice::from_raw_parts(dbs, n);
    let curve: Vec<(f64, f64)> = fs.iter().zip(ds).map(|(&f, &d)| (f, d)).collect();
    match crate::arma::fit_corner_from_magnitude(&curve, runtime_sr) {
        Some(corner) => {
            let dst = std::slice::from_raw_parts_mut(out, NUM_STAGES * NUM_COEFFS);
            for (si, stage) in corner.iter().enumerate() {
                for (ki, &c) in stage.iter().enumerate() {
                    dst[si * NUM_COEFFS + ki] = c;
                }
            }
            0
        }
        None => -3,
    }
}

/// Fit one recorded sound's minimum-phase spectral envelope into one six-stage
/// pole-zero corner (kernel form).
///
/// `samples` contains the already-conditioned mono recording slice. Writes 30
/// kernel coefficients (6 stages x 5: c0..c4, stage-major) into `out`. This is
/// a thin FFI wrapper over `arma::fit_corner_arma`: the numerator and
/// denominator are both fitted by the Rust ARMA solver.
///
/// Returns: 0 ok, -1 null ptr, -2 fewer than 64 samples, -3 fitter returned None.
#[no_mangle]
pub unsafe extern "C" fn trench_fit_corner_arma(
    samples: *const f64,
    n: usize,
    sr_in: f64,
    runtime_sr: f64,
    out: *mut f64,
) -> i32 {
    if samples.is_null() || out.is_null() {
        return -1;
    }
    if n < 64 {
        return -2;
    }
    let input = std::slice::from_raw_parts(samples, n);
    match crate::arma::fit_corner_arma(input, sr_in, runtime_sr) {
        Some(corner) => {
            let dst = std::slice::from_raw_parts_mut(out, NUM_STAGES * NUM_COEFFS);
            for (si, stage) in corner.iter().enumerate() {
                for (ki, &c) in stage.iter().enumerate() {
                    dst[si * NUM_COEFFS + ki] = c;
                }
            }
            0
        }
        None => -3,
    }
}

/// Interpolate a 240-byte packed body at `(morph, q)` and write 30 kernel-form
/// coefficients (6 stages × 5: c0..c4), stage-major, into `out`.
///
/// Stateless and identical to the runtime's `PackedCorners::interpolate`
/// (morph-first bilinear lerp in packed `u16` space, then minifloat decode):
/// `morph`/`q` are cast to f32 exactly as `Cartridge::interpolate` does. This is
/// the one path Python tools call so they judge the SAME interpolation the
/// player ships — no parallel `packed_bilinear`.
///
/// Returns 0 ok, -1 null ptr, -4 wrong length, -3 decode error.
#[no_mangle]
pub unsafe extern "C" fn trench_packed_interpolate(
    bytes: *const u8,
    len: usize,
    morph: f64,
    q: f64,
    out: *mut f64,
) -> i32 {
    if bytes.is_null() || out.is_null() {
        return -1;
    }
    if len != BODY_BYTES {
        return -4;
    }
    let slice = std::slice::from_raw_parts(bytes, len);
    let packed = match PackedCorners::from_body_bytes(slice) {
        Ok(p) => p,
        Err(_) => return -3,
    };
    let kernel = packed.interpolate(morph as f32, q as f32);
    let out_slice = std::slice::from_raw_parts_mut(out, NUM_STAGES * NUM_COEFFS);
    for si in 0..NUM_STAGES {
        for ci in 0..NUM_COEFFS {
            out_slice[si * NUM_COEFFS + ci] = kernel[si][ci];
        }
    }
    0
}

/// Interpolate a 240-byte packed body at `(morph, q)`, convert to biquad form,
/// and compute per-stage stability diagnostics — in a single call.
///
/// This is the diagnostic chokepoint: Python tools call this instead of
/// reimplementing `kernel_to_biquad` or `pole_radius`. Stateless.
///
/// Outputs:
///   `out_biquad[30]`     — 6 stages × 5 biquad coeffs [b0,b1,b2,a1,a2], stage-major.
///   `out_max_pole_radius`— max pole radius across all finite stages (0.0 if all nonfinite).
///   `out_unstable_mask`  — bit i set if stage i has pole radius ≥ 1.0.
///   `out_nonfinite_mask` — bit i set if any biquad coeff of stage i is nonfinite.
///
/// Returns 0 ok, -1 null ptr, -4 wrong length, -3 decode error.
#[no_mangle]
pub unsafe extern "C" fn trench_packed_probe(
    bytes: *const u8,
    len: usize,
    morph: f64,
    q: f64,
    out_biquad: *mut f64,
    out_max_pole_radius: *mut f64,
    out_unstable_mask: *mut u32,
    out_nonfinite_mask: *mut u32,
) -> i32 {
    if bytes.is_null()
        || out_biquad.is_null()
        || out_max_pole_radius.is_null()
        || out_unstable_mask.is_null()
        || out_nonfinite_mask.is_null()
    {
        return -1;
    }
    if len != BODY_BYTES {
        return -4;
    }
    let slice = std::slice::from_raw_parts(bytes, len);
    let packed = match PackedCorners::from_body_bytes(slice) {
        Ok(p) => p,
        Err(_) => return -3,
    };
    let biquad_rows = packed.interpolate_biquad(morph as f32, q as f32);

    let out_bq = std::slice::from_raw_parts_mut(out_biquad, NUM_STAGES * NUM_COEFFS);
    let mut max_r = 0.0f64;
    let mut unstable_mask = 0u32;
    let mut nonfinite_mask = 0u32;

    for si in 0..NUM_STAGES {
        let row = biquad_rows[si];
        for ci in 0..NUM_COEFFS {
            out_bq[si * NUM_COEFFS + ci] = row[ci];
        }
        if row.iter().any(|v| !v.is_finite()) {
            nonfinite_mask |= 1u32 << si;
        } else {
            let r = pole_radius(row[3], row[4]);
            if r > max_r {
                max_r = r;
            }
            if r >= 1.0 {
                unstable_mask |= 1u32 << si;
            }
        }
    }

    *out_max_pole_radius = max_r;
    *out_unstable_mask = unstable_mask;
    *out_nonfinite_mask = nonfinite_mask;
    0
}

#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_parameters(
    engine: *mut c_void,
    morph: f32,
    q: f32,
    slam_drive: f32,
    five_d: f32,
) {
    let engine = &mut *(engine as *mut FilterEngine);
    engine.set_slam_drive(slam_drive);
    engine.set_space(five_d);
    // Note: actual morph/q is passed per-block in process_block
}

/// 0 = None (default), 1 = Mackie desk slam, 2 = CVSD.
/// Unknown values are ignored.
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_input_mode(engine: *mut c_void, mode: i32) {
    let engine = &mut *(engine as *mut FilterEngine);
    let m = match mode {
        0 => InputMode::None,
        1 => InputMode::MackieDeskSlam,
        2 => InputMode::Cvsd,
        _ => return,
    };
    engine.set_input_mode(m);
}

/// Local no-profile QSound recreation pan: -1 = left, 0 = mono center,
/// +1 = right. Cartridge-backed spatial profiles ignore this control.
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_qsound_fallback_pan(engine: *mut c_void, pan: f32) {
    let engine = &mut *(engine as *mut FilterEngine);
    engine.set_qsound_fallback_pan(pan);
}

#[no_mangle]
pub unsafe extern "C" fn trench_engine_process_block(
    engine: *mut c_void,
    left: *mut f32,
    right: *mut f32,
    num_samples: i32,
    morph: f64,
    q: f64,
) {
    let engine = &mut *(engine as *mut FilterEngine);
    let left_slice = std::slice::from_raw_parts_mut(left, num_samples as usize);
    let right_slice = std::slice::from_raw_parts_mut(right, num_samples as usize);

    engine.process_block(left_slice, right_slice, morph, q);
}

/// 0 = QSound (default), 1 = Trench M/S phase-destruction matrix, 2 = Off.
/// Unknown values are ignored.
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_spatial_mode(engine: *mut c_void, mode: i32) {
    let engine = &mut *(engine as *mut FilterEngine);
    let m = match mode {
        0 => SpatialMode::QSound,
        1 => SpatialMode::Trench,
        2 => SpatialMode::Off,
        _ => return,
    };
    engine.set_spatial_mode(m);
}

#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_agc_enabled(engine: *mut c_void, enabled: i32) {
    let engine = &mut *(engine as *mut FilterEngine);
    engine.debug.agc_enabled = enabled != 0;
}

#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_dc_block_enabled(engine: *mut c_void, enabled: i32) {
    let engine = &mut *(engine as *mut FilterEngine);
    engine.debug.dc_block_enabled = enabled != 0;
}

#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_saturation_enabled(engine: *mut c_void, enabled: i32) {
    let engine = &mut *(engine as *mut FilterEngine);
    engine.debug.saturation_enabled = enabled != 0;
}

#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_agc_drive(engine: *mut c_void, drive: f32) {
    let engine = &mut *(engine as *mut FilterEngine);
    engine.set_agc_drive(drive);
}

/// Set the four `TrenchMatrix` knobs in one call. Field semantics in
/// `trench_matrix.rs`: `mu` is unclamped, `space` clamps to 0..1 internally.
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_trench_matrix(
    engine: *mut c_void,
    target_delay_samples: i32,
    allpass_delay_samples: i32,
    allpass_g: f32,
    mu: f32,
) {
    let engine = &mut *(engine as *mut FilterEngine);
    engine.trench_matrix.target_delay_samples = target_delay_samples.max(0) as usize;
    engine.trench_matrix.allpass_delay_samples = allpass_delay_samples.max(1) as usize;
    engine.trench_matrix.allpass_g = allpass_g;
    engine.trench_matrix.mu = mu;
}

#[no_mangle]
pub unsafe extern "C" fn trench_engine_get_coeffs(
    engine: *mut c_void,
    out_coeffs: *mut f32, // Pointer to [f32; 30] (6 stages * 5 coeffs)
    out_boost: *mut f32,
) {
    let engine = &*(engine as *mut FilterEngine);
    let mut r_coeffs = [[0.0f32; 5]; 6];
    let mut r_boost = 1.0f32;

    engine.get_coeffs_for_ui(&mut r_coeffs, &mut r_boost);

    let out_ptr = out_coeffs as *mut f32;
    for i in 0..6 {
        for j in 0..5 {
            *out_ptr.add(i * 5 + j) = r_coeffs[i][j];
        }
    }
    *out_boost = r_boost;
}
