use crate::cartridge::{Cartridge, BODY_BYTES};
use crate::cascade::{NUM_COEFFS, NUM_STAGES};
use crate::designer::{self, DesignerSection};
use crate::dsp::BASE_AGC_TABLE;
use crate::engine::{
    install_pending, CartridgeMailbox, EngineHandle, FilterEngine, InputMode, SpatialMode,
};
use crate::minifloat::{decode, encode, pole_radius, PackedCorners};
use crate::stage_law::{roots_from_words, words_from_roots, StageRoots};
use std::ffi::CStr;
use std::ffi::{c_char, c_void};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::ptr;
const FFI_PANIC: i32 = -100;
#[inline]
fn ffi_guard<R>(default: R, f: impl FnOnce() -> R) -> R {
    match catch_unwind(AssertUnwindSafe(f)) {
        Ok(v) => v,
        Err(_) => default,
    }
}
#[inline]
unsafe fn engine_mut<'a>(handle: *mut c_void) -> Option<&'a mut FilterEngine> {
    if handle.is_null() {
        return None;
    }
    let h = handle as *mut EngineHandle;
    Some(&mut *ptr::addr_of_mut!((*h).engine))
}
#[inline]
unsafe fn engine_ref<'a>(handle: *mut c_void) -> Option<&'a FilterEngine> {
    if handle.is_null() {
        return None;
    }
    let h = handle as *mut EngineHandle;
    Some(&*ptr::addr_of!((*h).engine))
}
#[inline]
unsafe fn mailbox_ref<'a>(handle: *mut c_void) -> Option<&'a CartridgeMailbox> {
    if handle.is_null() {
        return None;
    }
    let h = handle as *mut EngineHandle;
    Some(&*ptr::addr_of!((*h).mailbox))
}
#[no_mangle]
pub extern "C" fn trench_engine_create() -> *mut c_void {
    ffi_guard(ptr::null_mut(), || {
        Box::into_raw(Box::new(EngineHandle::new())) as *mut c_void
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_destroy(engine: *mut c_void) {
    ffi_guard((), || {
        if !engine.is_null() {
            let _ = unsafe { Box::from_raw(engine as *mut EngineHandle) };
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_prepare(engine: *mut c_void, sample_rate: f64) {
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.prepare(sample_rate);
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_load_cartridge(
    engine: *mut c_void,
    json: *const c_char,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if json.is_null() {
            return -1;
        }
        let mailbox = match unsafe { mailbox_ref(engine) } {
            Some(m) => m,
            None => return -1,
        };
        let c_str = unsafe { CStr::from_ptr(json) };
        let r_str = match c_str.to_str() {
            Ok(s) => s,
            Err(_) => return -2,
        };
        match Cartridge::from_json(r_str) {
            Ok(cart) => {
                mailbox.stage(Box::new(cart));
                0
            }
            Err(_) => -3,
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_load_body_bytes(
    engine: *mut c_void,
    bytes: *const u8,
    len: usize,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if bytes.is_null() {
            return -1;
        }
        if len != BODY_BYTES {
            return -4;
        }
        let mailbox = match unsafe { mailbox_ref(engine) } {
            Some(m) => m,
            None => return -1,
        };
        let slice = unsafe { std::slice::from_raw_parts(bytes, len) };
        let rate = match unsafe { engine_ref(engine) } {
            Some(eng) => eng.sample_rate(),
            None => return -1,
        };
        match Cartridge::from_body_bytes_at("audition", slice, 1.0, rate) {
            Ok(cart) => {
                mailbox.stage(Box::new(cart));
                0
            }
            Err(_) => -3,
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_reclaim(engine: *mut c_void) {
    ffi_guard((), || {
        if let Some(mailbox) = unsafe { mailbox_ref(engine) } {
            mailbox.reclaim();
        }
    })
}
#[no_mangle]
pub extern "C" fn trench_packed_decode(word: u16) -> f64 {
    ffi_guard(0.0, || decode(word))
}
#[no_mangle]
pub extern "C" fn trench_packed_encode(value: f64) -> u16 {
    ffi_guard(0u16, || encode(value))
}
#[no_mangle]
pub unsafe extern "C" fn trench_agc_table(out: *mut f32, len: usize) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if out.is_null() || len < BASE_AGC_TABLE.len() {
            return -1;
        }
        let dst = unsafe { std::slice::from_raw_parts_mut(out, BASE_AGC_TABLE.len()) };
        dst.copy_from_slice(&BASE_AGC_TABLE);
        BASE_AGC_TABLE.len() as i32
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_fit_corner_from_magnitude(
    freqs: *const f64,
    dbs: *const f64,
    n: usize,
    runtime_sr: f64,
    out: *mut f64,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if freqs.is_null() || dbs.is_null() || out.is_null() {
            return -1;
        }
        if n < 2 {
            return -2;
        }
        let fs = unsafe { std::slice::from_raw_parts(freqs, n) };
        let ds = unsafe { std::slice::from_raw_parts(dbs, n) };
        let curve: Vec<(f64, f64)> = fs.iter().zip(ds).map(|(&f, &d)| (f, d)).collect();
        match crate::arma::fit_corner_from_magnitude(&curve, runtime_sr) {
            Some(corner) => {
                let dst = unsafe { std::slice::from_raw_parts_mut(out, NUM_STAGES * NUM_COEFFS) };
                for (si, stage) in corner.iter().enumerate() {
                    for (ki, &c) in stage.iter().enumerate() {
                        dst[si * NUM_COEFFS + ki] = c;
                    }
                }
                0
            }
            None => -3,
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_fit_corner_arma(
    samples: *const f64,
    n: usize,
    sr_in: f64,
    runtime_sr: f64,
    out: *mut f64,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if samples.is_null() || out.is_null() {
            return -1;
        }
        if n < 64 {
            return -2;
        }
        let input = unsafe { std::slice::from_raw_parts(samples, n) };
        match crate::arma::fit_corner_arma(input, sr_in, runtime_sr) {
            Some(corner) => {
                let dst = unsafe { std::slice::from_raw_parts_mut(out, NUM_STAGES * NUM_COEFFS) };
                for (si, stage) in corner.iter().enumerate() {
                    for (ki, &c) in stage.iter().enumerate() {
                        dst[si * NUM_COEFFS + ki] = c;
                    }
                }
                0
            }
            None => -3,
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_packed_interpolate(
    bytes: *const u8,
    len: usize,
    morph: f64,
    q: f64,
    out: *mut f64,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if bytes.is_null() || out.is_null() {
            return -1;
        }
        if len != BODY_BYTES {
            return -4;
        }
        let slice = unsafe { std::slice::from_raw_parts(bytes, len) };
        let packed = match PackedCorners::from_body_bytes(slice) {
            Ok(p) => p,
            Err(_) => return -3,
        };
        let kernel = packed.interpolate(morph as f32, q as f32);
        let out_slice = unsafe { std::slice::from_raw_parts_mut(out, NUM_STAGES * NUM_COEFFS) };
        for si in 0..NUM_STAGES {
            for ci in 0..NUM_COEFFS {
                out_slice[si * NUM_COEFFS + ci] = kernel[si][ci];
            }
        }
        0
    })
}
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
    ffi_guard(FFI_PANIC, || {
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
        let slice = unsafe { std::slice::from_raw_parts(bytes, len) };
        let packed = match PackedCorners::from_body_bytes(slice) {
            Ok(p) => p,
            Err(_) => return -3,
        };
        let biquad_rows = packed.interpolate_biquad(morph as f32, q as f32);
        let out_bq = unsafe { std::slice::from_raw_parts_mut(out_biquad, NUM_STAGES * NUM_COEFFS) };
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
        unsafe {
            *out_max_pole_radius = max_r;
            *out_unstable_mask = unstable_mask;
            *out_nonfinite_mask = nonfinite_mask;
        }
        0
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_pack_body_from_corner_words(
    words: *const u16,
    n: usize,
    out_body: *mut u8,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if words.is_null() || out_body.is_null() {
            return -1;
        }
        const NWORDS: usize = 4 * NUM_STAGES * NUM_COEFFS;
        if n != NWORDS {
            return -4;
        }
        let src = unsafe { std::slice::from_raw_parts(words, n) };
        let mut pc = [[[0u16; NUM_COEFFS]; NUM_STAGES]; 4];
        let mut i = 0;
        for corner in pc.iter_mut() {
            for stage in corner.iter_mut() {
                for w in stage.iter_mut() {
                    *w = src[i];
                    i += 1;
                }
            }
        }
        let bytes = PackedCorners { words: pc }.to_rom_bytes();
        let out = unsafe { std::slice::from_raw_parts_mut(out_body, BODY_BYTES) };
        out.copy_from_slice(&bytes);
        0
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_certify_body(
    bytes: *const u8,
    len: usize,
    res: u32,
    r_max: f64,
    out_pass: *mut i32,
    out_max_radius: *mut f64,
    out_fail_morph: *mut f64,
    out_fail_q: *mut f64,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if bytes.is_null() || out_pass.is_null() || out_max_radius.is_null() {
            return -1;
        }
        if len != BODY_BYTES {
            return -4;
        }
        let slice = unsafe { std::slice::from_raw_parts(bytes, len) };
        let packed = match PackedCorners::from_body_bytes(slice) {
            Ok(p) => p,
            Err(_) => return -3,
        };
        let res = res.max(2);
        let rmax = if r_max > 0.0 { r_max } else { 1.0 };
        let denom = (res - 1) as f64;
        let mut max_r = 0.0f64;
        let mut pass = 1i32;
        let mut fail_m = -1.0f64;
        let mut fail_q = -1.0f64;
        'sweep: for qi in 0..res {
            let q = qi as f64 / denom;
            for mi in 0..res {
                let m = mi as f64 / denom;
                let rows = packed.interpolate_biquad(m as f32, q as f32);
                for row in rows.iter() {
                    if row.iter().any(|v| !v.is_finite()) {
                        pass = 0;
                        max_r = f64::INFINITY;
                        fail_m = m;
                        fail_q = q;
                        break 'sweep;
                    }
                    let r = pole_radius(row[3], row[4]);
                    if r > max_r {
                        max_r = r;
                    }
                    if r >= rmax {
                        pass = 0;
                        fail_m = m;
                        fail_q = q;
                        break 'sweep;
                    }
                }
            }
        }
        unsafe {
            *out_pass = pass;
            *out_max_radius = max_r;
            if !out_fail_morph.is_null() {
                *out_fail_morph = fail_m;
            }
            if !out_fail_q.is_null() {
                *out_fail_q = fail_q;
            }
        }
        0
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_stage_roots_from_words(
    words: *const u16,
    out_roots: *mut f64,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if words.is_null() || out_roots.is_null() {
            return -1;
        }
        let w = unsafe { std::slice::from_raw_parts(words, NUM_COEFFS) };
        let roots = match roots_from_words([w[0], w[1], w[2], w[3], w[4]]) {
            Some(r) => r,
            None => return -3,
        };
        let out = unsafe { std::slice::from_raw_parts_mut(out_roots, 5) };
        out[0] = roots.pole_hz;
        out[1] = roots.pole_r;
        out[2] = roots.zero_hz;
        out[3] = roots.zero_r;
        out[4] = roots.scale;
        0
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_stage_words_from_roots(
    roots: *const f64,
    out_words: *mut u16,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if roots.is_null() || out_words.is_null() {
            return -1;
        }
        let r = unsafe { std::slice::from_raw_parts(roots, 5) };
        if r.iter().any(|v| !v.is_finite()) {
            return -2;
        }
        let words = words_from_roots(&StageRoots {
            pole_hz: r[0],
            pole_r: r[1],
            zero_hz: r[2],
            zero_r: r[3],
            scale: r[4],
        });
        let out = unsafe { std::slice::from_raw_parts_mut(out_words, NUM_COEFFS) };
        out.copy_from_slice(&words);
        0
    })
}
/// `sections`: array of `n` DesignerSection (repr(C)), n <= 6. Writes 30 words.
#[no_mangle]
pub unsafe extern "C" fn trench_designer_compile_corner(
    sections: *const DesignerSection,
    n: usize,
    morph: f64,
    shift: i32,
    out_words: *mut u16,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if (sections.is_null() && n != 0) || out_words.is_null() || !morph.is_finite() {
            return -1;
        }
        let secs: &[DesignerSection] = if n == 0 {
            &[]
        } else {
            unsafe { std::slice::from_raw_parts(sections, n) }
        };
        let words = match designer::compile_corner(secs, morph, shift) {
            Ok(w) => w,
            Err(_) => return -2,
        };
        let out = unsafe { std::slice::from_raw_parts_mut(out_words, designer::WORDS_PER_CORNER) };
        out.copy_from_slice(&words);
        0
    })
}
/// `q0`/`q100`: the two Q-page section sets (pass the same pointer twice for
/// heritage Q-collapsed bodies). Writes 240 bytes.
#[no_mangle]
pub unsafe extern "C" fn trench_designer_body(
    q0: *const DesignerSection,
    q100: *const DesignerSection,
    n: usize,
    shift: i32,
    out_body: *mut u8,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if ((q0.is_null() || q100.is_null()) && n != 0) || out_body.is_null() {
            return -1;
        }
        let (a, b): (&[DesignerSection], &[DesignerSection]) = if n == 0 {
            (&[], &[])
        } else {
            unsafe {
                (
                    std::slice::from_raw_parts(q0, n),
                    std::slice::from_raw_parts(q100, n),
                )
            }
        };
        let bytes = match designer::body_bytes(a, b, shift) {
            Ok(b) => b,
            Err(_) => return -2,
        };
        let out = unsafe { std::slice::from_raw_parts_mut(out_body, BODY_BYTES) };
        out.copy_from_slice(&bytes);
        0
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_cartridge_json_to_body(
    json: *const c_char,
    out_body: *mut u8,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if json.is_null() || out_body.is_null() {
            return -1;
        }
        let r_str = match unsafe { CStr::from_ptr(json) }.to_str() {
            Ok(s) => s,
            Err(_) => return -2,
        };
        let cart = match Cartridge::from_json(r_str) {
            Ok(c) => c,
            Err(_) => return -3,
        };
        let bytes = cart.packed.to_rom_bytes();
        let out = unsafe { std::slice::from_raw_parts_mut(out_body, BODY_BYTES) };
        out.copy_from_slice(&bytes);
        0
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_compile_body(
    params: *const f64,
    n_params: usize,
    out_body: *mut u8,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if params.is_null() || out_body.is_null() {
            return -1;
        }
        if n_params != crate::compiler::PARAM_LEN {
            return -4;
        }
        let p = unsafe { std::slice::from_raw_parts(params, n_params) };
        let body = crate::compiler::pack_body(p);
        let out = unsafe { std::slice::from_raw_parts_mut(out_body, crate::compiler::BODY_LEN) };
        out.copy_from_slice(&body);
        0
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_compile_body_typed(
    cards: *const f64,
    n_values: usize,
    out_body: *mut u8,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if cards.is_null() || out_body.is_null() {
            return -1;
        }
        if n_values != crate::compiler::TYPED_PARAM_LEN {
            return -4;
        }
        let p = unsafe { std::slice::from_raw_parts(cards, n_values) };
        let body = crate::compiler::pack_typed_body(p);
        let out = unsafe { std::slice::from_raw_parts_mut(out_body, crate::compiler::BODY_LEN) };
        out.copy_from_slice(&body);
        0
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_parameters(
    engine: *mut c_void,
    morph: f32,
    q: f32,
    slam_drive: f32,
    five_d: f32,
    amount: f32,
) {
    let _ = (morph, q);
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.set_slam_drive(slam_drive);
            eng.set_space(five_d);
            eng.set_amount(amount);
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_input_mode(engine: *mut c_void, mode: i32) {
    ffi_guard((), || {
        let eng = match unsafe { engine_mut(engine) } {
            Some(e) => e,
            None => return,
        };
        let m = match mode {
            0 => InputMode::None,
            1 => InputMode::MackieDeskSlam,
            2 => InputMode::Cvsd,
            _ => return,
        };
        eng.set_input_mode(m);
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_qsound_fallback_pan(engine: *mut c_void, pan: f32) {
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.set_qsound_fallback_pan(pan);
        }
    })
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
    ffi_guard((), || {
        if engine.is_null() || left.is_null() || right.is_null() || num_samples <= 0 {
            return;
        }
        let h = engine as *mut EngineHandle;
        let eng = unsafe { &mut *ptr::addr_of_mut!((*h).engine) };
        let mailbox = unsafe { &*ptr::addr_of!((*h).mailbox) };
        install_pending(eng, mailbox);
        let n = num_samples as usize;
        let left_slice = unsafe { std::slice::from_raw_parts_mut(left, n) };
        let right_slice = unsafe { std::slice::from_raw_parts_mut(right, n) };
        eng.process_block(left_slice, right_slice, morph, q);
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_spatial_mode(engine: *mut c_void, mode: i32) {
    ffi_guard((), || {
        let eng = match unsafe { engine_mut(engine) } {
            Some(e) => e,
            None => return,
        };
        let m = match mode {
            0 => SpatialMode::QSound,
            1 => SpatialMode::Trench,
            2 => SpatialMode::Off,
            _ => return,
        };
        eng.set_spatial_mode(m);
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_agc_enabled(engine: *mut c_void, enabled: i32) {
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.debug.agc_enabled = enabled != 0;
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_dc_block_enabled(engine: *mut c_void, enabled: i32) {
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.debug.dc_block_enabled = enabled != 0;
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_saturation_enabled(engine: *mut c_void, enabled: i32) {
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.debug.saturation_enabled = enabled != 0;
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_agc_drive(engine: *mut c_void, drive: f32) {
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.set_agc_drive(drive);
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_coeff_ramp_scale(engine: *mut c_void, scale: f32) {
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.debug.coeff_ramp_scale = if scale.is_finite() { scale.clamp(0.0, 1.0) } else { 1.0 };
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_pole_distortion(engine: *mut c_void, drive: f32) {
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.set_pole_distortion(drive);
        }
    })
}

#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_chew_topology(engine: *mut c_void, topology: i32) {
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.set_chew_topology(topology);
        }
    })
}

#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_phasor_vt_scale(engine: *mut c_void, scale: f32) {
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.set_phasor_vt_scale(scale);
        }
    })
}

#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_interstage_drive(engine: *mut c_void, drive: f32) {
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.set_interstage_drive(drive);
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_pitch_ratio(engine: *mut c_void, ratio: f32) {
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.set_pitch_ratio(if ratio.is_finite() { ratio } else { 1.0 });
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_key_snap(engine: *mut c_void, choice: i32) {
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.set_key_snap(choice);
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_trench_matrix(
    engine: *mut c_void,
    target_delay_samples: i32,
    allpass_delay_samples: i32,
    allpass_g: f32,
    mu: f32,
) {
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.trench_matrix.target_delay_samples = target_delay_samples.max(0) as usize;
            eng.trench_matrix.allpass_delay_samples = allpass_delay_samples.max(1) as usize;
            eng.trench_matrix.allpass_g = allpass_g;
            eng.trench_matrix.mu = mu;
        }
    })
}
#[no_mangle]
pub unsafe extern "C" fn trench_engine_get_coeffs(
    engine: *mut c_void,
    out_coeffs: *mut f32,
    out_boost: *mut f32,
) {
    ffi_guard((), || {
        if out_boost.is_null() {
            return;
        }
        let eng = match unsafe { engine_ref(engine) } {
            Some(e) => e,
            None => {
                unsafe { *out_boost = 1.0 };
                return;
            }
        };
        if out_coeffs.is_null() {
            unsafe { *out_boost = 1.0 };
            return;
        }
        let mut r_coeffs = [[0.0f32; 5]; 6];
        let mut r_boost = 1.0f32;
        eng.get_coeffs_for_ui(&mut r_coeffs, &mut r_boost);
        let out_ptr = out_coeffs;
        for i in 0..6 {
            for j in 0..5 {
                unsafe { *out_ptr.add(i * 5 + j) = r_coeffs[i][j] };
            }
        }
        unsafe { *out_boost = r_boost };
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    fn passthrough_json() -> String {
        let corners = [[[2.0f64, 1.0, 2.0, 1.0, 1.0]; NUM_STAGES]; 4];
        let packed = PackedCorners::from_corner_data(&corners);
        let labels = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
        let keyframes = labels
            .iter()
            .enumerate()
            .map(|(corner_index, label)| {
                serde_json::json!({
                    "label": label,
                    "boost": 1.0,
                    "packedWords": packed.words[corner_index]
                })
            })
            .collect::<Vec<_>>();
        serde_json::json!({
            "format": "compiled-v1",
            "name": "passthrough",
            "sampleRate": 44_100.0,
            "keyframes": keyframes
        })
        .to_string()
    }
    #[test]
    fn stage_roots_words_ffi_round_trip_is_a_fixed_point() {
        let roots = [1000.0f64, 0.98, 2000.0, 0.9, 0.5];
        let mut words = [0u16; 5];
        let mut decoded = [0.0f64; 5];
        let mut words2 = [0u16; 5];
        unsafe {
            assert_eq!(
                trench_stage_words_from_roots(roots.as_ptr(), words.as_mut_ptr()),
                0
            );
            assert_eq!(
                trench_stage_roots_from_words(words.as_ptr(), decoded.as_mut_ptr()),
                0
            );
            assert_eq!(
                trench_stage_words_from_roots(decoded.as_ptr(), words2.as_mut_ptr()),
                0
            );
        }
        assert_eq!(words, words2);
        let identity_words = words_from_roots(&StageRoots::IDENTITY);
        let mut identity_decoded = [0.0f64; 5];
        unsafe {
            assert_eq!(
                trench_stage_roots_from_words(identity_words.as_ptr(), identity_decoded.as_mut_ptr()),
                0
            );
        }
        assert_eq!(identity_decoded[4], 1.0);
        unsafe {
            assert_eq!(trench_stage_words_from_roots(ptr::null(), words.as_mut_ptr()), -1);
            assert_eq!(trench_stage_roots_from_words(ptr::null(), decoded.as_mut_ptr()), -1);
        }
    }
    #[test]
    fn null_pointers_are_rejected_not_dereferenced() {
        unsafe {
            assert_eq!(
                trench_engine_load_cartridge(ptr::null_mut(), ptr::null()),
                -1
            );
            assert_eq!(
                trench_engine_load_body_bytes(ptr::null_mut(), ptr::null(), 240),
                -1
            );
            trench_engine_prepare(ptr::null_mut(), 44100.0);
            trench_engine_process_block(
                ptr::null_mut(),
                ptr::null_mut(),
                ptr::null_mut(),
                64,
                0.5,
                0.5,
            );
            trench_engine_reclaim(ptr::null_mut());
            let mut coeffs = [0.0f32; 30];
            let mut boost = 0.0f32;
            trench_engine_get_coeffs(ptr::null_mut(), coeffs.as_mut_ptr(), &mut boost);
            assert_eq!(boost, 1.0, "null engine must report unity boost");
        }
        let mut morph = 0.0f32;
        let mut q = 0.0f32;
        assert_eq!(
            trench_motion_path_value_timed(
                std::ptr::null(),
                2,
                0.5,
                0,
                0,
                0.2,
                0.3,
                1.0,
                &mut morph,
                &mut q,
            ),
            -1
        );
    }
    #[test]
    fn timed_motion_ffi_matches_the_core_sampler() {
        let points = [
            0.0f32, 0.0, 0.0, 0.2, 0.8, 0.4, 0.7, 0.1, 0.9, 1.0, 0.0, 0.0,
        ];
        let expected = crate::motion::path_value_timed(&points, 0.2, false, 0.1, 0.1, 1.0, 4);
        let mut morph = 0.0f32;
        let mut q = 0.0f32;
        let rc = trench_motion_path_value_timed(
            points.as_ptr(),
            4,
            0.2,
            0,
            4,
            0.1,
            0.1,
            1.0,
            &mut morph,
            &mut q,
        );
        assert_eq!(rc, 0);
        assert!((morph - expected.0).abs() < 1.0e-6);
        assert!((q - expected.1).abs() < 1.0e-6);
    }
    #[test]
    fn wrong_length_body_is_rejected() {
        unsafe {
            let engine = trench_engine_create();
            assert!(!engine.is_null());
            let bytes = [0u8; 16];
            assert_eq!(
                trench_engine_load_body_bytes(engine, bytes.as_ptr(), bytes.len()),
                -4
            );
            trench_engine_destroy(engine);
        }
    }
    #[test]
    fn staged_load_installs_on_next_process_block() {
        unsafe {
            let engine = trench_engine_create();
            assert!(!engine.is_null());
            trench_engine_prepare(engine, 44100.0);
            let json = std::ffi::CString::new(passthrough_json()).unwrap();
            assert_eq!(trench_engine_load_cartridge(engine, json.as_ptr()), 0);
            let mut l = vec![0.25f32; 256];
            let mut r = vec![0.25f32; 256];
            trench_engine_process_block(
                engine,
                l.as_mut_ptr(),
                r.as_mut_ptr(),
                l.len() as i32,
                0.5,
                0.5,
            );
            assert!(l.iter().all(|s| s.is_finite()));
            let mut coeffs = [0.0f32; 30];
            let mut boost = 0.0f32;
            trench_engine_get_coeffs(engine, coeffs.as_mut_ptr(), &mut boost);
            assert!(boost.is_finite());
            trench_engine_reclaim(engine);
            trench_engine_reclaim(engine);
            trench_engine_destroy(engine);
        }
    }
    #[test]
    fn rapid_restage_then_install_is_clean() {
        unsafe {
            let engine = trench_engine_create();
            trench_engine_prepare(engine, 44100.0);
            let json = std::ffi::CString::new(passthrough_json()).unwrap();
            for _ in 0..8 {
                assert_eq!(trench_engine_load_cartridge(engine, json.as_ptr()), 0);
            }
            let mut l = vec![0.1f32; 128];
            let mut r = vec![0.1f32; 128];
            trench_engine_process_block(engine, l.as_mut_ptr(), r.as_mut_ptr(), 128, 0.5, 0.5);
            assert!(l.iter().all(|s| s.is_finite()));
            trench_engine_destroy(engine);
        }
    }
    #[test]
    fn pack_body_from_corner_words_roundtrips_bytes() {
        let mut body = [0u8; BODY_BYTES];
        for (i, w) in body.chunks_exact_mut(2).enumerate() {
            let word = (i as u16).wrapping_mul(7).wrapping_add(3);
            w.copy_from_slice(&word.to_le_bytes());
        }
        let pc = PackedCorners::from_body_bytes(&body).unwrap();
        let mut words = [0u16; 4 * NUM_STAGES * NUM_COEFFS];
        let mut i = 0;
        for ci in 0..4 {
            for si in 0..NUM_STAGES {
                for wi in 0..NUM_COEFFS {
                    words[i] = pc.words[ci][si][wi];
                    i += 1;
                }
            }
        }
        let mut out = [0u8; BODY_BYTES];
        let rc = unsafe {
            trench_pack_body_from_corner_words(words.as_ptr(), words.len(), out.as_mut_ptr())
        };
        assert_eq!(rc, 0);
        assert_eq!(
            &out[..],
            &body[..],
            "packed bytes must equal the original body"
        );
    }
    #[test]
    fn pack_body_rejects_wrong_word_count() {
        let words = [0u16; 10];
        let mut out = [0u8; BODY_BYTES];
        let rc = unsafe {
            trench_pack_body_from_corner_words(words.as_ptr(), words.len(), out.as_mut_ptr())
        };
        assert_eq!(rc, -4);
    }
    #[test]
    fn certify_passes_unity_body() {
        let corners = [[[2.0f64, 1.0, 2.0, 1.0, 1.0]; NUM_STAGES]; 4];
        let body = PackedCorners::from_corner_data(&corners).to_rom_bytes();
        let (mut pass, mut maxr, mut fm, mut fq) = (0i32, 0.0f64, 0.0f64, 0.0f64);
        let rc = unsafe {
            trench_certify_body(
                body.as_ptr(),
                body.len(),
                33,
                0.9999,
                &mut pass,
                &mut maxr,
                &mut fm,
                &mut fq,
            )
        };
        assert_eq!(rc, 0);
        assert_eq!(pass, 1, "unity body must certify pass");
        assert!(maxr < 0.5, "unity poles sit near radius 0, got {maxr}");
    }
    #[test]
    fn certify_fails_rim_body() {
        let corners = [[[2.0f64, 1.0, 2.0, 0.0, 1.0]; NUM_STAGES]; 4];
        let body = PackedCorners::from_corner_data(&corners).to_rom_bytes();
        let (mut pass, mut maxr, mut fm, mut fq) = (1i32, 0.0f64, -1.0f64, -1.0f64);
        let rc = unsafe {
            trench_certify_body(
                body.as_ptr(),
                body.len(),
                9,
                0.9999,
                &mut pass,
                &mut maxr,
                &mut fm,
                &mut fq,
            )
        };
        assert_eq!(rc, 0);
        assert_eq!(pass, 0, "radius-1 body must certify fail");
        assert!(fm >= 0.0 && fq >= 0.0, "fail coordinate must be reported");
    }
    #[test]
    fn cartridge_json_to_body_yields_loadable_bytes() {
        let json = std::ffi::CString::new(passthrough_json()).unwrap();
        let mut out = [0u8; BODY_BYTES];
        let rc = unsafe { trench_cartridge_json_to_body(json.as_ptr(), out.as_mut_ptr()) };
        assert_eq!(rc, 0);
        assert!(
            PackedCorners::from_body_bytes(&out).is_ok(),
            "must be a valid 240-byte body"
        );
    }
}
#[no_mangle]
pub unsafe extern "C" fn trench_desk_saturate_stereo(
    left: *mut f32,
    right: *mut f32,
    num_samples: i32,
    drive: f32,
) {
    if left.is_null() || num_samples <= 0 {
        return;
    }
    let n = num_samples as usize;
    let l = std::slice::from_raw_parts_mut(left, n);
    for x in l.iter_mut() {
        *x = crate::desk_drive::mackity_saturate((*x * drive) as f64) as f32;
    }
    if right.is_null() || std::ptr::eq(right, left) {
        return;
    }
    let r = std::slice::from_raw_parts_mut(right, n);
    for x in r.iter_mut() {
        *x = crate::desk_drive::mackity_saturate((*x * drive) as f64) as f32;
    }
}
#[no_mangle]
pub extern "C" fn trench_keyframe_value(
    a: f32,
    b: f32,
    leg_bars: f32,
    ppq: f64,
    beats_per_bar: f64,
    mode: u32,
) -> f32 {
    crate::keyframe::keyframe_loop_value_mode(
        a,
        b,
        leg_bars,
        ppq,
        beats_per_bar,
        crate::keyframe::LoopMode::from_u32(mode),
    )
}
#[no_mangle]
pub extern "C" fn trench_motion_path_value(
    points: *const f32,
    point_count: usize,
    phase: f64,
    closed: i32,
    base_morph: f32,
    base_q: f32,
    amount: f32,
    out_morph: *mut f32,
    out_q: *mut f32,
) -> i32 {
    if out_morph.is_null() || out_q.is_null() || point_count == 0 {
        return -1;
    }
    if points.is_null() {
        return -1;
    }
    let count = point_count.min(crate::motion::MAX_PATH_POINTS);
    let values = unsafe { std::slice::from_raw_parts(points, count * 2) };
    let (morph, q) =
        crate::motion::path_value(values, phase, closed != 0, base_morph, base_q, amount);
    unsafe {
        *out_morph = morph;
        *out_q = q;
    }
    0
}
#[no_mangle]
pub extern "C" fn trench_motion_path_value_timed(
    points: *const f32,
    point_count: usize,
    phase: f64,
    closed: i32,
    grid_steps: usize,
    base_morph: f32,
    base_q: f32,
    amount: f32,
    out_morph: *mut f32,
    out_q: *mut f32,
) -> i32 {
    if out_morph.is_null() || out_q.is_null() || point_count == 0 {
        return -1;
    }
    if points.is_null() {
        return -1;
    }
    let count = point_count.min(crate::motion::MAX_PATH_POINTS);
    let values =
        unsafe { std::slice::from_raw_parts(points, count * crate::motion::TIMED_POINT_STRIDE) };
    let (morph, q) = crate::motion::path_value_timed(
        values,
        phase,
        closed != 0,
        base_morph,
        base_q,
        amount,
        grid_steps,
    );
    unsafe {
        *out_morph = morph;
        *out_q = q;
    }
    0
}
#[no_mangle]
pub extern "C" fn trench_section_biquad(
    type_id: i32,
    fc: f64,
    q: f64,
    gain_db: f64,
    out: *mut f64,
) {
    if out.is_null() {
        return;
    }
    let bq = crate::compiler::section_biquad(type_id, fc, q, gain_db);
    unsafe {
        core::ptr::copy_nonoverlapping(bq.as_ptr(), out, 5);
    }
}
