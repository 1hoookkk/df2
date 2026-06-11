use trench_core::compiler::{pack_body, pack_typed_body};
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

#[no_mangle]
pub extern "C" fn forge_pack_params() -> i32 {
    // Forward compile is owned ONCE by trench-core (compiler::pack_body). WASM, the
    // Python author server, and the DLL all run this same Rust object code, so the
    // bytes the browser auditions are bit-identical to what /bake writes.
    unsafe {
        let body = pack_body(&PARAMS[..]);
        BODY[..].copy_from_slice(&body);
    }
    0
}

// ---- Rossum Filter Designer path: 6 typed cards -> 240 body bytes.
// Each card is [type_id, fc_A, fc_B, q_lo, q_hi, gain_db, enabled] (7 f64).
// type_id: 0=Peak 1=LowShelf 2=Notch 3=LP 4=HP 5=BP 6=HighShelf. The card IS a
// heritage designer-section: fc_A/fc_B are its low/high-frame frequencies, Morph
// interpolates between them. Routed through trench-core's pack_typed_body (one
// owner) so the designed body is bit-identical to the DLL.
const TYPED_FIELDS_PER_CARD: usize = 7;
const TYPED_PARAM_LEN: usize = STAGES * TYPED_FIELDS_PER_CARD;
static mut TYPED: [f64; TYPED_PARAM_LEN] = [0.0; TYPED_PARAM_LEN];

#[no_mangle]
pub extern "C" fn forge_typed_ptr() -> *mut f64 {
    unsafe { TYPED.as_mut_ptr() }
}

#[no_mangle]
pub extern "C" fn forge_typed_len() -> usize {
    TYPED_PARAM_LEN
}

#[no_mangle]
pub extern "C" fn forge_pack_typed() -> i32 {
    unsafe {
        let body = pack_typed_body(&TYPED[..]);
        BODY[..].copy_from_slice(&body);
    }
    0
}
