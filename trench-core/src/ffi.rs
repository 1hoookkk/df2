use crate::cartridge::{Cartridge, BODY_BYTES};
use crate::cascade::{NUM_COEFFS, NUM_STAGES};
use crate::engine::{FilterEngine, InputMode, SpatialMode};
use crate::minifloat::{decode, pole_radius, PackedCorners};
use libc::{c_char, c_void};
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
