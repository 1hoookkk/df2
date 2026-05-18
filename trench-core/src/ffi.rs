use crate::cartridge::Cartridge;
use crate::engine::{FilterEngine, InputMode, SpatialMode};
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
