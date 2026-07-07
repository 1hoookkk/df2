use crate::cartridge::{Cartridge, BODY_BYTES};
use crate::cascade::{NUM_COEFFS, NUM_STAGES};
use crate::dsp::BASE_AGC_TABLE;
use crate::engine::{
    install_pending, CartridgeMailbox, EngineHandle, FilterEngine, InputMode, SpatialMode,
};
use crate::minifloat::{decode, encode, pole_radius, PackedCorners};
use std::ffi::CStr;
use std::ffi::{c_char, c_void};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::ptr;

/// Returned by any i32 FFI entry point whose body panicked. Distinct from the
/// hand-written error codes (-1..-4) so a panic is never mistaken for a normal
/// rejection. A panic must never unwind across the `extern "C"` boundary
/// (undefined behaviour); every export below is wrapped so it cannot.
const FFI_PANIC: i32 = -100;

/// Run `f` behind a panic barrier, returning `default` if it unwinds. The
/// closure is `AssertUnwindSafe` because the only state it touches across the
/// boundary is caller-owned memory reached through raw pointers — there is no
/// Rust-side invariant a partial unwind could leave broken (the engine itself is
/// never mutated past an `&mut` we already hold exclusively).
#[inline]
fn ffi_guard<R>(default: R, f: impl FnOnce() -> R) -> R {
    match catch_unwind(AssertUnwindSafe(f)) {
        Ok(v) => v,
        Err(_) => default,
    }
}

// === Engine handle projection ================================================
//
// The FFI handle is a `*mut EngineHandle`. We NEVER form `&EngineHandle` or
// `&mut EngineHandle`: that would let the audio thread's exclusive borrow of
// `handle.engine` alias the message thread's access to `handle.mailbox`. Instead
// we project to the disjoint fields through the raw pointer with `addr_of`, so
// the two borrows never overlap. See `EngineHandle` in engine.rs.

/// `&mut FilterEngine` for the audio-thread entry points. Caller must guarantee
/// no other thread is inside an engine-mutating call (true for the runtime:
/// process/prepare/set_* are all audio-thread or pre-roll only).
#[inline]
unsafe fn engine_mut<'a>(handle: *mut c_void) -> Option<&'a mut FilterEngine> {
    if handle.is_null() {
        return None;
    }
    let h = handle as *mut EngineHandle;
    Some(&mut *ptr::addr_of_mut!((*h).engine))
}

/// Shared `&FilterEngine` for read-only entry points called on the audio thread
/// (e.g. coefficient publish, immediately after process_block).
#[inline]
unsafe fn engine_ref<'a>(handle: *mut c_void) -> Option<&'a FilterEngine> {
    if handle.is_null() {
        return None;
    }
    let h = handle as *mut EngineHandle;
    Some(&*ptr::addr_of!((*h).engine))
}

/// `&CartridgeMailbox` for the message-thread entry points (body load, reclaim).
/// Only touches atomics, never the engine.
#[inline]
unsafe fn mailbox_ref<'a>(handle: *mut c_void) -> Option<&'a CartridgeMailbox> {
    if handle.is_null() {
        return None;
    }
    let h = handle as *mut EngineHandle;
    Some(&*ptr::addr_of!((*h).mailbox))
}

// === Lifecycle ===============================================================

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
            // Drops the engine and, via CartridgeMailbox::drop, any cartridge
            // still parked in the pending/garbage slots.
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

// === Body loading (message thread -> mailbox -> audio install) ===============

/// Parse a JSON cartridge and STAGE it for the audio thread to install at the
/// next block boundary. Runs on the message thread; never touches the live
/// engine. Returns 0 if the body parsed and was staged, <0 on rejection.
///
/// Returns: 0 ok, -1 null engine/json, -2 non-UTF8 json, -3 parse error,
/// -100 internal panic.
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

/// Stage a body from raw bytes. Must be exactly 240 bytes (4 corners × 6 stages
/// × 5 u16 words × 2). Routes through the same canonical `Cartridge::from_body_bytes`
/// → `PackedCorners` path as a JSON `packedWords` body — there is no separate DSP
/// path for raw audition bodies. Message-thread safe (stages, does not install).
///
/// Returns: 0 ok, -1 null engine/ptr, -4 wrong length, -3 decode error,
/// -100 internal panic.
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
        match Cartridge::from_body_bytes("audition", slice, 1.0) {
            Ok(cart) => {
                mailbox.stage(Box::new(cart));
                0
            }
            Err(_) => -3,
        }
    })
}

/// Message-thread reclaim: free a cartridge the audio thread retired after a
/// swap, if any. Optional (the next `load` also reclaims) — call on a timer to
/// release the previous body's memory promptly. No-op on null.
#[no_mangle]
pub unsafe extern "C" fn trench_engine_reclaim(engine: *mut c_void) {
    ffi_guard((), || {
        if let Some(mailbox) = unsafe { mailbox_ref(engine) } {
            mailbox.reclaim();
        }
    })
}

// === Stateless packed-math (Python tooling shares these exact codecs) =========

/// Decode one packed `u16` minifloat word to f64. Stateless.
#[no_mangle]
pub extern "C" fn trench_packed_decode(word: u16) -> f64 {
    ffi_guard(0.0, || decode(word))
}

/// Encode one f64 to the nearest packed `u16` minifloat word — the inverse of
/// `trench_packed_decode`. Stateless.
#[no_mangle]
pub extern "C" fn trench_packed_encode(value: f64) -> u16 {
    ffi_guard(0u16, || encode(value))
}

/// Copy the canonical 16-entry AGC (global compression) curve into `out`.
/// Returns the number of entries written (16), -1 on null/short buffer,
/// -100 on panic.
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

/// Factorize a TARGET magnitude curve into one fitted corner (kernel form).
/// `freqs`/`dbs` are `n` parallel sorted points `(freq_hz, db)`; writes 30 kernel
/// coefficients (6 stages × 5: c0..c4, stage-major) into `out`.
/// Returns: 0 ok, -1 null ptr, -2 fewer than 2 points, -3 fitter None, -100 panic.
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

/// Fit one recorded sound's minimum-phase spectral envelope into one six-stage
/// pole-zero corner (kernel form). Writes 30 kernel coefficients (stage-major).
/// Returns: 0 ok, -1 null ptr, -2 fewer than 64 samples, -3 fitter None, -100 panic.
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

/// Interpolate a 240-byte packed body at `(morph, q)` and write 30 kernel-form
/// coefficients (6 stages × 5: c0..c4), stage-major, into `out`. Stateless,
/// identical to the runtime's `PackedCorners::interpolate`.
/// Returns 0 ok, -1 null ptr, -4 wrong length, -3 decode error, -100 panic.
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

/// Interpolate a 240-byte packed body at `(morph, q)`, convert to biquad form,
/// and compute per-stage stability diagnostics — in a single call. Stateless.
///
/// Outputs:
///   `out_biquad[30]`     — 6 stages × 5 biquad coeffs [b0,b1,b2,a1,a2], stage-major.
///   `out_max_pole_radius`— max pole radius across all finite stages (0.0 if all nonfinite).
///   `out_unstable_mask`  — bit i set if stage i has pole radius ≥ 1.0.
///   `out_nonfinite_mask` — bit i set if any biquad coeff of stage i is nonfinite.
///
/// Returns 0 ok, -1 null ptr, -4 wrong length, -3 decode error, -100 panic.
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

// === SEED support: pack body from edited corner words + surface certify ========

/// Assemble a 240-byte body from 120 packed `u16` corner words (4 corners × 6
/// stages × 5 words, corner-major / stage-major — the exact order `PackedCorners`
/// stores and `to_rom_bytes` serialises). The missing inverse the SEED path needs:
/// perturb a corner's words, then pack them back to a loadable body WITHOUT any
/// decode/re-encode round-trip (words taken verbatim, so a seeded sibling stays
/// byte-faithful to the sanctioned packer the words came from).
/// Returns 0 ok, -1 null ptr, -4 wrong word count, -100 panic.
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
        const NWORDS: usize = 4 * NUM_STAGES * NUM_COEFFS; // 120
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

/// Certify a 240-byte body over the WHOLE morph × Q surface (not one point): sweep
/// a `res`×`res` lattice, interpolate each point to biquad form, and require every
/// stage's pole radius < `r_max` with finite coefficients. This is the surface gate
/// `surfaceforge.certify` uses — a single-point `trench_packed_probe` would pass
/// bodies that blow up at other morph positions. A dense sample, not a continuum
/// proof (raising `res` shrinks the gap, never closes it).
///
/// Writes: `out_pass` = 1 pass / 0 fail; `out_max_radius` = max pole radius over the
/// surface (INFINITY if a nonfinite stage was hit); `out_fail_morph`/`out_fail_q` =
/// first offending coordinate, or -1 on pass (both optional / nullable). `res` is
/// clamped to >= 2; `r_max` defaults to 1.0 when <= 0.
/// Returns 0 ok, -1 null ptr, -4 wrong length, -3 decode error, -100 panic.
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

/// Spawn a LEGAL sibling body (SEED): perturb the source body's real poles/zeros
/// within bounds and re-encode once, certified over the morph × Q surface. The
/// faithful in-core port of `sample_mint` — all packed math stays in core. `seed`
/// makes it deterministic; `amt` scales the spread (1.0 = default); `res`/`r_max`
/// are the surface gate (e.g. 65 / 0.9999). Writes 240 bytes on success.
/// Returns 0 ok, -1 null ptr, -4 wrong length, -5 no legal sibling found, -100 panic.
#[no_mangle]
pub unsafe extern "C" fn trench_seed_body(
    in_body: *const u8,
    len: usize,
    seed: u64,
    amt: f64,
    res: u32,
    r_max: f64,
    out_body: *mut u8,
) -> i32 {
    ffi_guard(FFI_PANIC, || {
        if in_body.is_null() || out_body.is_null() {
            return -1;
        }
        if len != BODY_BYTES {
            return -4;
        }
        let slice = unsafe { std::slice::from_raw_parts(in_body, len) };
        match crate::seed::seed_legal(slice, seed, amt, res, r_max, 24) {
            Some(b) => {
                let out = unsafe { std::slice::from_raw_parts_mut(out_body, BODY_BYTES) };
                out.copy_from_slice(&b);
                0
            }
            None => -5,
        }
    })
}

/// Parse a JSON cartridge and write its canonical 240-byte body — the inverse seam
/// to `trench_engine_load_cartridge`. Hands the host the raw bytes of the currently
/// loaded roster/JSON body, to SEED from or EXPORT. `packedWords` are the authority;
/// a legacy stage-only body derives its words from the decoded corners. Stateless.
/// Returns 0 ok, -1 null ptr, -2 non-UTF8 json, -3 parse error, -100 panic.
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
        let packed = cart
            .packed
            .unwrap_or_else(|| PackedCorners::from_corner_data(&cart.corners));
        let bytes = packed.to_rom_bytes();
        let out = unsafe { std::slice::from_raw_parts_mut(out_body, BODY_BYTES) };
        out.copy_from_slice(&bytes);
        0
    })
}

/// Forward authoring compiler (single owner). Reads `n_params` f64 section params
/// (must be `compiler::PARAM_LEN`) and writes 240 body bytes.
/// Returns 0 ok, -1 null ptr, -4 wrong length, -100 panic.
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

/// Typed-section compiler for v1 preset authoring. Reads `compiler::TYPED_PARAM_LEN`
/// f64 values and writes one canonical 240-byte body.
/// Returns 0 ok, -1 null ptr, -4 wrong length, -100 panic.
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

// === Engine control (audio / pre-roll thread) ================================

#[no_mangle]
pub unsafe extern "C" fn trench_engine_set_parameters(
    engine: *mut c_void,
    morph: f32,
    q: f32,
    slam_drive: f32,
    five_d: f32,
    amount: f32,
) {
    let _ = (morph, q); // actual morph/q is passed per-block in process_block
    ffi_guard((), || {
        if let Some(eng) = unsafe { engine_mut(engine) } {
            eng.set_slam_drive(slam_drive);
            eng.set_space(five_d);
            eng.set_amount(amount);
        }
    })
}

/// 0 = None (default), 1 = Mackie desk slam, 2 = CVSD. Unknown values ignored.
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

/// Local no-profile QSound recreation pan: -1 = left, 0 = mono center, +1 = right.
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
        // Disjoint borrows: &mut engine + &mailbox, never &EngineHandle.
        let eng = unsafe { &mut *ptr::addr_of_mut!((*h).engine) };
        let mailbox = unsafe { &*ptr::addr_of!((*h).mailbox) };

        // Install a staged body at the block boundary (allocation-free).
        install_pending(eng, mailbox);

        let n = num_samples as usize;
        let left_slice = unsafe { std::slice::from_raw_parts_mut(left, n) };
        let right_slice = unsafe { std::slice::from_raw_parts_mut(right, n) };
        eng.process_block(left_slice, right_slice, morph, q);
    })
}

/// 0 = QSound (default), 1 = Trench M/S matrix, 2 = Off. Unknown values ignored.
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

/// Set the four `TrenchMatrix` knobs in one call.
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

/// Read the smoothed cascade coefficients for the UI. Called on the AUDIO thread
/// (e.g. immediately after process_block) and the result published to a UI
/// snapshot — never called concurrently with process_block from another thread.
/// `out_coeffs` is `[f32; 30]` (6 stages × 5). Defaults to unity boost on null.
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

    const PASSTHROUGH: &str = r#"{
        "format": "compiled-v1", "name": "pt", "sampleRate": 44100,
        "keyframes": [
            {"label":"M0_Q0","morph":0.0,"q":0.0,"boost":1.0,"stages":[
                {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}]},
            {"label":"M0_Q100","morph":0.0,"q":1.0,"boost":1.0,"stages":[
                {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}]},
            {"label":"M100_Q0","morph":1.0,"q":0.0,"boost":1.0,"stages":[
                {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}]},
            {"label":"M100_Q100","morph":1.0,"q":1.0,"boost":1.0,"stages":[
                {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}]}
        ]
    }"#;

    /// Null engine pointers must be rejected with an error code, never crash.
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
            // void-returning entry points must simply no-op on null.
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
    }

    /// Wrong-length body is rejected before any decode work.
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

    /// Full staged round-trip through the FFI: create, stage a JSON body, install
    /// it at a process_block boundary, and confirm the engine actually filters
    /// (coeffs published). Exercises mailbox stage -> take -> install -> retire.
    #[test]
    fn staged_load_installs_on_next_process_block() {
        unsafe {
            let engine = trench_engine_create();
            assert!(!engine.is_null());
            trench_engine_prepare(engine, 44100.0);

            let json = std::ffi::CString::new(PASSTHROUGH).unwrap();
            assert_eq!(trench_engine_load_cartridge(engine, json.as_ptr()), 0);

            // First block installs the staged cartridge, then filters.
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

            // Coeffs publish should now reflect an installed (unity) body.
            let mut coeffs = [0.0f32; 30];
            let mut boost = 0.0f32;
            trench_engine_get_coeffs(engine, coeffs.as_mut_ptr(), &mut boost);
            assert!(boost.is_finite());

            // Reclaim is safe to call repeatedly.
            trench_engine_reclaim(engine);
            trench_engine_reclaim(engine);
            trench_engine_destroy(engine);
        }
    }

    /// Rapid re-staging before the audio thread consumes must not leak or crash
    /// (the producer reclaims the superseded pending box).
    #[test]
    fn rapid_restage_then_install_is_clean() {
        unsafe {
            let engine = trench_engine_create();
            trench_engine_prepare(engine, 44100.0);
            let json = std::ffi::CString::new(PASSTHROUGH).unwrap();
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

    // --- Phase 1: SEED support exports (pack-from-words + surface certify) ---

    /// Packing 120 corner words back to bytes must reproduce a body verbatim
    /// (words in -> PackedCorners -> to_rom_bytes == original bytes).
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
        assert_eq!(&out[..], &body[..], "packed bytes must equal the original body");
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

    /// A unity (passthrough) body — kernel [2,1,2,1,1] -> biquad [1,0,0,0,0],
    /// poles at radius 0 — must certify PASS over the whole surface.
    #[test]
    fn certify_passes_unity_body() {
        let corners = [[[2.0f64, 1.0, 2.0, 1.0, 1.0]; NUM_STAGES]; 4];
        let body = PackedCorners::from_corner_data(&corners).to_rom_bytes();
        let (mut pass, mut maxr, mut fm, mut fq) = (0i32, 0.0f64, 0.0f64, 0.0f64);
        let rc = unsafe {
            trench_certify_body(
                body.as_ptr(), body.len(), 33, 0.9999,
                &mut pass, &mut maxr, &mut fm, &mut fq,
            )
        };
        assert_eq!(rc, 0);
        assert_eq!(pass, 1, "unity body must certify pass");
        assert!(maxr < 0.5, "unity poles sit near radius 0, got {maxr}");
    }

    /// A body with c3=0 -> a2=1.0 -> pole radius 1.0 must certify FAIL at the rim.
    #[test]
    fn certify_fails_rim_body() {
        let corners = [[[2.0f64, 1.0, 2.0, 0.0, 1.0]; NUM_STAGES]; 4];
        let body = PackedCorners::from_corner_data(&corners).to_rom_bytes();
        let (mut pass, mut maxr, mut fm, mut fq) = (1i32, 0.0f64, -1.0f64, -1.0f64);
        let rc = unsafe {
            trench_certify_body(
                body.as_ptr(), body.len(), 9, 0.9999,
                &mut pass, &mut maxr, &mut fm, &mut fq,
            )
        };
        assert_eq!(rc, 0);
        assert_eq!(pass, 0, "radius-1 body must certify fail");
        assert!(fm >= 0.0 && fq >= 0.0, "fail coordinate must be reported");
    }

    /// A JSON cartridge round-trips to a valid, loadable 240-byte body (the SEED
    /// source / EXPORT-body seam). PASSTHROUGH is stage-only, so this also covers
    /// the legacy derive-from-corners path.
    #[test]
    fn cartridge_json_to_body_yields_loadable_bytes() {
        let json = std::ffi::CString::new(PASSTHROUGH).unwrap();
        let mut out = [0u8; BODY_BYTES];
        let rc = unsafe { trench_cartridge_json_to_body(json.as_ptr(), out.as_mut_ptr()) };
        assert_eq!(rc, 0);
        assert!(PackedCorners::from_body_bytes(&out).is_ok(), "must be a valid 240-byte body");
    }
}
