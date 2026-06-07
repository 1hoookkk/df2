use trench_core::minifloat::encode;
use trench_core::{Cartridge, FilterEngine, InputMode, SpatialMode};

// ---- live engine: filter cascade + AGC + Mackie saturation + QSound, in WASM.
// JS writes 240 body bytes into BODY, calls forge_engine_load(), then feeds the
// source loop into INBUF and pulls OUTL/OUTR each block. This is the drive chain
// the product runs - so the ear authors against the real nonlinear sound. ------
const MAXN: usize = 2048;
const ENGINE_SR: f64 = 39_062.5;
static mut ENGINE: Option<FilterEngine> = None;
static mut INBUF: [f32; MAXN] = [0.0; MAXN];
static mut OUTL: [f32; MAXN] = [0.0; MAXN];
static mut OUTR: [f32; MAXN] = [0.0; MAXN];
static mut P_MORPH: f64 = 0.0;
static mut P_Q: f64 = 0.0;
static mut P_AGC: f32 = 3.0;
static mut P_SLAM: f32 = 0.0;
static mut P_WIDE: f32 = 0.4;

#[no_mangle]
pub extern "C" fn forge_engine_init() {
    unsafe {
        let mut e = FilterEngine::new();
        e.prepare(ENGINE_SR);
        e.debug.agc_enabled = true;
        e.set_spatial_mode(SpatialMode::Off); // audition AGC-only — no QSound widening
        ENGINE = Some(e);
    }
}

#[no_mangle]
pub extern "C" fn forge_engine_load() -> i32 {
    unsafe {
        match Cartridge::from_body_bytes("bench", &BODY[..], 1.0) {
            Ok(cart) => {
                if let Some(e) = ENGINE.as_mut() {
                    e.load_cartridge(cart);
                }
                0
            }
            Err(_) => -1,
        }
    }
}

#[no_mangle]
pub extern "C" fn forge_engine_sr() -> f64 {
    ENGINE_SR
}
#[no_mangle]
pub extern "C" fn forge_max_block() -> usize {
    MAXN
}
#[no_mangle]
pub extern "C" fn forge_in_ptr() -> *mut f32 {
    unsafe { INBUF.as_mut_ptr() }
}
#[no_mangle]
pub extern "C" fn forge_outl_ptr() -> *mut f32 {
    unsafe { OUTL.as_mut_ptr() }
}
#[no_mangle]
pub extern "C" fn forge_outr_ptr() -> *mut f32 {
    unsafe { OUTR.as_mut_ptr() }
}

#[no_mangle]
pub extern "C" fn forge_set_params(morph: f64, q: f64, agc: f32, slam: f32, wide: f32) {
    unsafe {
        P_MORPH = morph;
        P_Q = q;
        P_AGC = agc;
        P_SLAM = slam;
        P_WIDE = wide;
    }
}

#[no_mangle]
pub extern "C" fn forge_engine_process(n: usize) {
    unsafe {
        let n = n.min(MAXN);
        if let Some(e) = ENGINE.as_mut() {
            e.set_agc_drive(P_AGC);
            e.set_slam_drive(P_SLAM);
            e.set_input_mode(if P_SLAM > 0.02 {
                InputMode::MackieDeskSlam
            } else {
                InputMode::None
            });
            e.set_space(P_WIDE);
            for i in 0..n {
                OUTL[i] = INBUF[i];
                OUTR[i] = INBUF[i];
            }
            e.process_block(&mut OUTL[..n], &mut OUTR[..n], P_MORPH, P_Q);
        }
    }
}

const SR: f64 = 39_062.5;
const TAU: f64 = core::f64::consts::PI * 2.0;
const STAGES: usize = 6;
const CORNERS: usize = 4;
const PARAMS_PER_STAGE: usize = 7;
const PARAM_LEN: usize = CORNERS * STAGES * PARAMS_PER_STAGE;
const BODY_LEN: usize = 240;

static mut PARAMS: [f64; PARAM_LEN] = [0.0; PARAM_LEN];
static mut BODY: [u8; BODY_LEN] = [0; BODY_LEN];

#[no_mangle]
pub extern "C" fn forge_params_ptr() -> *mut f64 {
    unsafe { PARAMS.as_mut_ptr() }
}

#[no_mangle]
pub extern "C" fn forge_params_len() -> usize {
    PARAM_LEN
}

#[no_mangle]
pub extern "C" fn forge_body_ptr() -> *const u8 {
    unsafe { BODY.as_ptr() }
}

#[no_mangle]
pub extern "C" fn forge_body_len() -> usize {
    BODY_LEN
}

fn biquad_to_words(b: [f64; 5]) -> [u16; 5] {
    let (b0, b1, b2, a1, a2) = (b[0], b[1], b[2], b[3], b[4]);
    let c4 = b0;
    let c0 = if c4 != 0.0 { b1 / c4 + 2.0 } else { 2.0 };
    let c1 = if c4 != 0.0 { 1.0 - b2 / c4 } else { 1.0 };
    let c2 = a1 + 2.0;
    let c3 = 1.0 - a2;
    [
        encode((c0 - c1) / 4.0),
        encode(c1),
        encode((c2 - c3) / 4.0),
        encode(c3),
        encode(c4 / 4.0),
    ]
}

fn stage_biquad(p: &[f64]) -> [f64; 5] {
    let on = p[0] >= 0.5;
    if !on {
        return [1.0, 0.0, 0.0, 0.0, 0.0];
    }

    let fp = p[1].clamp(20.0, SR * 0.49);
    let rp = p[2].clamp(0.5, 0.9999);
    let gain = p[3].clamp(0.05, 4.0);
    let cut_on = p[4] >= 0.5;
    let cut_hz = p[5].clamp(20.0, SR * 0.49);
    let cut_depth = p[6].clamp(0.0, 0.9999);

    let wp = TAU * fp / SR;
    let a1 = -2.0 * rp * wp.cos();
    let a2 = rp * rp;

    if !cut_on || cut_depth <= 0.0001 {
        let g = (1.0 - rp * rp).max(1e-4) * gain;
        return [g, 0.0, 0.0, a1, a2];
    }

    let wz = TAU * cut_hz / SR;
    let nb1 = -2.0 * cut_depth * wz.cos();
    let nb2 = cut_depth * cut_depth;
    let g = (1.0 + a1 + a2) / (1.0 + nb1 + nb2).max(1e-9) * gain;
    [g, g * nb1, g * nb2, a1, a2]
}

#[no_mangle]
pub extern "C" fn forge_pack_params() -> i32 {
    unsafe {
        let mut out = 0usize;
        for ci in 0..CORNERS {
            for si in 0..STAGES {
                let i = (ci * STAGES + si) * PARAMS_PER_STAGE;
                let bq = stage_biquad(&PARAMS[i..i + PARAMS_PER_STAGE]);
                let words = biquad_to_words(bq);
                for word in words {
                    BODY[out] = (word & 0xff) as u8;
                    BODY[out + 1] = (word >> 8) as u8;
                    out += 2;
                }
            }
        }
    }
    0
}
