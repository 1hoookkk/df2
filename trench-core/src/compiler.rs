//! Forward authoring compiler — the SINGLE owner of "section params -> biquad -> 5 packed words".
//! WASM (`forge-web-wasm`), the Python author server (via FFI `trench_compile_body`), and the DLL
//! all call THIS. The inverse side (decode / interpolate / cascade) lives in `minifloat` / `cascade`
//! — do not duplicate either direction.
//!
//! Canonical legacy section param order (7 f64):
//! `[on, pole_hz, pole_r, gain, zero_on, zero_hz, zero_depth]`.
//! Canonical typed card order (7 f64): `[type_id, fc_A, fc_B, q_lo, q_hi, gain_db, enabled]`.
//! Canonical corner order: `M0_Q0, M100_Q0, M0_Q100, M100_Q100`.
//! Body = 4 corners x 6 stages x 5 u16, little-endian = 240 bytes.

use crate::minifloat::encode;

pub const AUTHORING_SR: f64 = 39_062.5;
pub const TAU: f64 = core::f64::consts::PI * 2.0;
/// Single source of the pole/zero radius ceiling. Supersedes the Python server's old 0.9999
/// clamp (the two "mirrors" had drifted; one owner removes that hole by construction).
pub const MAX_RADIUS: f64 = 0.999999999999999;
pub const POLE_R_MIN: f64 = 0.5;
pub const GAIN_MIN: f64 = 0.05;
pub const GAIN_MAX: f64 = 4.0;
pub const FREQ_MIN: f64 = 20.0;
pub const FREQ_MAX: f64 = AUTHORING_SR * 0.49;
pub const ZERO_DEPTH_THRESH: f64 = 0.0001;
pub const GAIN_FLOOR: f64 = 1e-4;
pub const ZNORM_FLOOR: f64 = 1e-9;

pub const STAGES: usize = 6;
pub const CORNERS: usize = 4;
pub const PARAMS_PER_STAGE: usize = 7;
pub const BODY_LEN: usize = 240;
pub const PARAM_LEN: usize = CORNERS * STAGES * PARAMS_PER_STAGE; // 168
pub const TYPED_FIELDS_PER_CARD: usize = 7;
pub const TYPED_PARAM_LEN: usize = STAGES * TYPED_FIELDS_PER_CARD; // 42

pub const TYPE_PEAK: i32 = 0;
pub const TYPE_LOW_SHELF_CONTROLLED: i32 = 1;
pub const TYPE_NOTCH: i32 = 2;
pub const TYPE_LOWPASS: i32 = 3;
pub const TYPE_HIGHPASS: i32 = 4;
pub const TYPE_BANDPASS: i32 = 5;
pub const TYPE_HIGH_SHELF: i32 = 6;

const Q_MIN: f64 = 0.3;
const Q_MAX: f64 = 128.0;
const SHELF_RADIUS_MAX: f64 = 0.9992;
const NOTCH_RADIUS_MAX: f64 = 0.999;
const NOTCH_ZERO_RADIUS_MAX: f64 = 0.99999;

/// One section: a pole pair with an OPTIONAL notch zero. This is byte-for-byte the historical
/// `forge-web-wasm` / Python `stage_biquad`. NOTE: its all-pole branch (`[g,0,0,a1,a2]`) rolls off
/// -12 dB/oct and a cascade of six craters the sharp corner — that is the known corner-collapse bug.
/// Kept here for byte-exact migration parity and raw-param authoring; new musical authoring should
/// use [`section_biquad`] (flat-ended forms).
pub fn stage_biquad(p: &[f64]) -> [f64; 5] {
    let on = p[0] >= 0.5;
    if !on {
        return [1.0, 0.0, 0.0, 0.0, 0.0];
    }
    let fp = p[1].clamp(FREQ_MIN, FREQ_MAX);
    let rp = p[2].clamp(POLE_R_MIN, MAX_RADIUS);
    let gain = p[3].clamp(GAIN_MIN, GAIN_MAX);
    let cut_on = p[4] >= 0.5;
    let cut_hz = p[5].clamp(FREQ_MIN, FREQ_MAX);
    let cut_depth = p[6].clamp(0.0, MAX_RADIUS);

    let wp = TAU * fp / AUTHORING_SR;
    let a1 = -2.0 * rp * wp.cos();
    let a2 = rp * rp;

    if !cut_on || cut_depth <= ZERO_DEPTH_THRESH {
        let g = (1.0 - rp * rp).max(GAIN_FLOOR) * gain;
        return [g, 0.0, 0.0, a1, a2];
    }
    let wz = TAU * cut_hz / AUTHORING_SR;
    let nb1 = -2.0 * cut_depth * wz.cos();
    let nb2 = cut_depth * cut_depth;
    let g = (1.0 + a1 + a2) / (1.0 + nb1 + nb2).max(ZNORM_FLOOR) * gain;
    [g, g * nb1, g * nb2, a1, a2]
}

/// a0-normalized biquad `[b0,b1,b2,a1,a2]` -> 5 packed minifloat words. Unchanged historical path;
/// `encode` stays the single codec owner (`minifloat::encode`).
pub fn biquad_to_words(b: [f64; 5]) -> [u16; 5] {
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

fn normalize(b0: f64, b1: f64, b2: f64, a0: f64, a1: f64, a2: f64) -> [f64; 5] {
    let a0 = if a0.abs() < ZNORM_FLOOR {
        ZNORM_FLOOR
    } else {
        a0
    };
    [b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0]
}

fn rbj_lowpass(fc: f64, q: f64, gain_db: f64) -> [f64; 5] {
    let w0 = TAU * fc / AUTHORING_SR;
    let (sw, cw) = w0.sin_cos();
    let alpha = sw / (2.0 * q);
    let g = 10.0_f64.powf(gain_db / 20.0);
    normalize(
        g * (1.0 - cw) * 0.5,
        g * (1.0 - cw),
        g * (1.0 - cw) * 0.5,
        1.0 + alpha,
        -2.0 * cw,
        1.0 - alpha,
    )
}

fn rbj_highpass(fc: f64, q: f64, gain_db: f64) -> [f64; 5] {
    let w0 = TAU * fc / AUTHORING_SR;
    let (sw, cw) = w0.sin_cos();
    let alpha = sw / (2.0 * q);
    let g = 10.0_f64.powf(gain_db / 20.0);
    normalize(
        g * (1.0 + cw) * 0.5,
        -g * (1.0 + cw),
        g * (1.0 + cw) * 0.5,
        1.0 + alpha,
        -2.0 * cw,
        1.0 - alpha,
    )
}

fn rbj_bandpass(fc: f64, q: f64, gain_db: f64) -> [f64; 5] {
    let w0 = TAU * fc / AUTHORING_SR;
    let (sw, cw) = w0.sin_cos();
    let alpha = sw / (2.0 * q);
    let g = 10.0_f64.powf(gain_db / 20.0);
    normalize(
        g * alpha,
        0.0,
        -g * alpha,
        1.0 + alpha,
        -2.0 * cw,
        1.0 - alpha,
    )
}

fn rbj_peak(fc: f64, q: f64, gain_db: f64) -> [f64; 5] {
    let w0 = TAU * fc / AUTHORING_SR;
    let (sw, cw) = w0.sin_cos();
    let alpha = sw / (2.0 * q);
    let a = 10.0_f64.powf(gain_db / 40.0);
    normalize(
        1.0 + alpha * a,
        -2.0 * cw,
        1.0 - alpha * a,
        1.0 + alpha / a,
        -2.0 * cw,
        1.0 - alpha / a,
    )
}

fn controlled_low_shelf(fc: f64, q: f64, gain_db: f64) -> [f64; 5] {
    let a = 10.0_f64.powf(gain_db / 20.0);
    let wp = TAU * fc / AUTHORING_SR;
    let rp = (-core::f64::consts::PI * (fc / q.max(Q_MIN)) / AUTHORING_SR)
        .exp()
        .min(SHELF_RADIUS_MAX);
    let a1 = -2.0 * rp * wp.cos();
    let a2 = rp * rp;

    let rz = rp;
    let den_dc = 1.0 + a1 + a2;
    let den_ny = 1.0 - a1 + a2;
    let k = a * den_dc / den_ny.max(ZNORM_FLOOR);
    let s = 1.0 + rz * rz;
    let t = s * (k - 1.0) / (k + 1.0).max(ZNORM_FLOOR);
    let cwz = (-t / (2.0 * rz)).clamp(-1.0, 1.0);
    let b1n = -2.0 * rz * cwz;
    let b2n = rz * rz;
    let b0 = den_ny / (1.0 - b1n + b2n).max(ZNORM_FLOOR);
    [b0, b0 * b1n, b0 * b2n, a1, a2]
}

fn rbj_high_shelf(fc: f64, q: f64, gain_db: f64) -> [f64; 5] {
    let w0 = TAU * fc / AUTHORING_SR;
    let (sw, cw) = w0.sin_cos();
    let alpha = sw / (2.0 * q);
    let a = 10.0_f64.powf(gain_db / 40.0);
    let two_sqrt_a_alpha = 2.0 * a.sqrt() * alpha;
    normalize(
        a * ((a + 1.0) + (a - 1.0) * cw + two_sqrt_a_alpha),
        -2.0 * a * ((a - 1.0) + (a + 1.0) * cw),
        a * ((a + 1.0) + (a - 1.0) * cw - two_sqrt_a_alpha),
        (a + 1.0) - (a - 1.0) * cw + two_sqrt_a_alpha,
        2.0 * ((a - 1.0) - (a + 1.0) * cw),
        (a + 1.0) - (a - 1.0) * cw - two_sqrt_a_alpha,
    )
}

fn variable_notch(fc: f64, q: f64, depth_db: f64) -> [f64; 5] {
    let wc = TAU * fc / AUTHORING_SR;
    let rp = (-core::f64::consts::PI * (fc / q.max(0.5)) / AUTHORING_SR)
        .exp()
        .min(NOTCH_RADIUS_MAX);
    let rz = (1.0 - (1.0 - rp) * 10.0_f64.powf(depth_db.min(0.0) / 20.0))
        .clamp(0.0, NOTCH_ZERO_RADIUS_MAX);
    let cw = wc.cos();
    let a1 = -2.0 * rp * cw;
    let a2 = rp * rp;
    let b1n = -2.0 * rz * cw;
    let b2n = rz * rz;
    let b0 = (1.0 + a1 + a2) / (1.0 + b1n + b2n).max(ZNORM_FLOOR);
    [b0, b0 * b1n, b0 * b2n, a1, a2]
}

/// Flat-ended typed section vocabulary. `type_id`:
/// 0=PEAK, 1=controlled low-shelf, 2=NOTCH, 3=LP, 4=HP, 5=BP, 6=RBJ high-shelf.
/// Typed sections own their pole/zero behavior intrinsically; there are no legacy
/// `zero_A/zero_B/zero_depth` fields on a typed card.
pub fn section_biquad(type_id: i32, fc: f64, q: f64, gain_db: f64) -> [f64; 5] {
    let fc = fc.clamp(FREQ_MIN, FREQ_MAX);
    let q = q.clamp(Q_MIN, Q_MAX);
    match type_id {
        TYPE_PEAK => rbj_peak(fc, q, gain_db),
        TYPE_LOW_SHELF_CONTROLLED => controlled_low_shelf(fc, q, gain_db),
        TYPE_NOTCH => variable_notch(fc, q, gain_db),
        TYPE_LOWPASS => rbj_lowpass(fc, q, gain_db),
        TYPE_HIGHPASS => rbj_highpass(fc, q, gain_db),
        TYPE_BANDPASS => rbj_bandpass(fc, q, gain_db),
        TYPE_HIGH_SHELF => rbj_high_shelf(fc, q, gain_db),
        _ => [1.0, 0.0, 0.0, 0.0, 0.0],
    }
}

fn geom(a: f64, b: f64, x: f64) -> f64 {
    let a = a.max(1e-9);
    let b = b.max(1e-9);
    a * (b / a).powf(x)
}

fn typed_card_biquad(card: &[f64], morph: f64, qsel: f64) -> [f64; 5] {
    if card[6] < 0.5 {
        return [1.0, 0.0, 0.0, 0.0, 0.0];
    }
    let type_id = card[0].round() as i32;
    let fc = geom(card[1], card[2], morph);
    let q = geom(card[3], card[4], qsel);
    section_biquad(type_id, fc, q, card[5])
}

/// Pack 24 stages (4 corners x 6 stages) of 7-f64 params into the 240-byte body.
/// Corner-major, stage-major, LSB-first u16. `params.len()` must be `PARAM_LEN` (168).
pub fn pack_body(params: &[f64]) -> [u8; BODY_LEN] {
    let mut body = [0u8; BODY_LEN];
    let mut out = 0usize;
    for ci in 0..CORNERS {
        for si in 0..STAGES {
            let i = (ci * STAGES + si) * PARAMS_PER_STAGE;
            let bq = stage_biquad(&params[i..i + PARAMS_PER_STAGE]);
            let words = biquad_to_words(bq);
            for word in words {
                body[out] = (word & 0xff) as u8;
                body[out + 1] = (word >> 8) as u8;
                out += 2;
            }
        }
    }
    body
}

/// Pack 6 typed cards into the 240-byte body by expanding to the four canonical
/// corners: M0_Q0, M100_Q0, M0_Q100, M100_Q100.
pub fn pack_typed_body(cards: &[f64]) -> [u8; BODY_LEN] {
    let mut body = [0u8; BODY_LEN];
    let mut out = 0usize;
    let corners = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)];
    for (morph, qsel) in corners {
        for si in 0..STAGES {
            let i = si * TYPED_FIELDS_PER_CARD;
            let bq = typed_card_biquad(&cards[i..i + TYPED_FIELDS_PER_CARD], morph, qsel);
            let words = biquad_to_words(bq);
            for word in words {
                body[out] = (word & 0xff) as u8;
                body[out + 1] = (word >> 8) as u8;
                out += 2;
            }
        }
    }
    body
}
