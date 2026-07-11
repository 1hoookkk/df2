//! Faithful one-shot SEED: spawn a legal, coherent SIBLING of a body by perturbing
//! its REAL poles/zeros within bounds and re-encoding ONCE — the in-core port of
//! surface-forge `scripts/sample_mint.py` (perturb_lane / make_variant / seed_family).
//!
//! Doctrine: all packed math stays in core. We decode each corner's lanes to their
//! real pole/zero geometry, apply a per-variant THEME (global frequency ratio +
//! radius offset + gain, applied to all four corners for coherence) plus small
//! per-lane jitter, keep flat/bypass lanes VERBATIM (never invent a pole), then
//! re-encode each active lane through the same recombination the runtime packer
//! uses (`PackedCorners::from_corner_data`) — proven byte-identical to the Python
//! `coeffs_to_words` path. Every candidate is certified over the whole morph × Q
//! surface; illegal draws are discarded and re-drawn.
//!
//! Frequency is perturbed in ANGLE space (a freq ratio is an angle ratio), so this
//! is sample-rate independent and needs no SR constant.

use crate::cascade::NUM_STAGES;
use crate::minifloat::{encode, pole_radius, stage_words_to_biquad, PackedCorners, BODY_BYTES};

const COMBINE_K: f64 = 4.0;
const R_AUTHOR_MAX: f64 = 0.995; // author poles below the Schur rim with margin (matches sample_mint)
const FLAT_DB: f64 = 0.5; // a lane whose magnitude span is below this is bypass — keep it verbatim
const MIN_ANGLE: f64 = 1.0e-3;
const MAX_ANGLE: f64 = std::f64::consts::PI * 0.98;

/// SplitMix64 — deterministic, dependency-free RNG seeded per call.
struct Rng(u64);
impl Rng {
    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
    /// Uniform f64 in [-1, 1).
    fn uni(&mut self) -> f64 {
        ((self.next_u64() >> 11) as f64 / (1u64 << 53) as f64) * 2.0 - 1.0
    }
}

/// Dominant root of `c0 + c1·z^-1 + c2·z^-2` as `(angle_rad, radius)`, or None if
/// the lane is degenerate (no resonance/notch to perturb).
fn root(c0: f64, c1: f64, c2: f64) -> Option<(f64, f64)> {
    if c0.abs() < 1.0e-12 {
        if c1.abs() < 1.0e-12 {
            return None;
        }
        let z = -c2 / c1;
        return Some((if z >= 0.0 { 0.0 } else { std::f64::consts::PI }, z.abs()));
    }
    let disc = c1 * c1 - 4.0 * c0 * c2;
    if disc < 0.0 {
        let r = (c2 / c0).max(0.0).sqrt();
        let cos_ang = if r > 1.0e-12 { (-c1 / (2.0 * c0)) / r } else { 1.0 };
        Some((cos_ang.clamp(-1.0, 1.0).acos(), r))
    } else {
        let sq = disc.sqrt();
        let z1 = (-c1 + sq) / (2.0 * c0);
        let z2 = (-c1 - sq) / (2.0 * c0);
        let z = if z1.abs() >= z2.abs() { z1 } else { z2 };
        Some((if z >= 0.0 { 0.0 } else { std::f64::consts::PI }, z.abs()))
    }
}

/// Build one lane's 5 packed words from perturbed pole/zero/gain — biquad → kernel
/// (inverse of `kernel_to_biquad`) → words (the `from_corner_data` recombination).
fn lane_words_from(pole: (f64, f64), zero: (f64, f64), gain: f64) -> [u16; 5] {
    let (pa, pr) = pole;
    let (za, zr) = zero;
    let a1 = -2.0 * pr * pa.cos();
    let a2 = pr * pr;
    let b0 = if gain.abs() > 1.0e-12 { gain } else { 1.0e-12 };
    let b1 = b0 * (-2.0 * zr * za.cos());
    let b2 = b0 * (zr * zr);
    let c0 = b1 / b0 + 2.0;
    let c1 = 1.0 - b2 / b0;
    let c2 = a1 + 2.0;
    let c3 = 1.0 - a2;
    [
        encode((c0 - c1) / COMBINE_K),
        encode(c1),
        encode((c2 - c3) / COMBINE_K),
        encode(c3),
        encode(b0 / COMBINE_K),
    ]
}

/// Magnitude span (dB) of one lane's biquad over log-spaced angles — the flat-lane
/// test (mirrors sample_mint `_lane_db(...).ptp() < FLAT_DB`).
fn lane_span_db(b: [f64; 5]) -> f64 {
    let [b0, b1, b2, a1, a2] = b;
    let (mut lo, mut hi) = (f64::INFINITY, f64::NEG_INFINITY);
    const N: usize = 48;
    let (l0, l1) = (MIN_ANGLE.ln(), MAX_ANGLE.ln());
    for i in 0..N {
        let w = (l0 + (i as f64 / (N as f64 - 1.0)) * (l1 - l0)).exp();
        let (c, s) = (w.cos(), w.sin());
        let (c2t, s2t) = ((2.0 * w).cos(), (2.0 * w).sin());
        let num = ((b0 + b1 * c + b2 * c2t).powi(2) + (b1 * s + b2 * s2t).powi(2)).sqrt();
        let den = ((1.0 + a1 * c + a2 * c2t).powi(2) + (a1 * s + a2 * s2t).powi(2))
            .sqrt()
            .max(1.0e-12);
        let db = 20.0 * (num / den).max(1.0e-12).log10();
        lo = lo.min(db);
        hi = hi.max(db);
    }
    hi - lo
}

/// Perturb a body once into a sibling (no certify). `amt` scales the spread
/// (1.0 = sample_mint default). Returns None only if the body is unparseable.
pub fn seed_one(body: &[u8], seed: u64, amt: f64) -> Option<[u8; BODY_BYTES]> {
    let packed = PackedCorners::from_body_bytes(body).ok()?;
    let mut rng = Rng(seed ^ 0x2545_F491_4F6C_DD1D);
    let (a_fr, a_ro, a_g) = (0.12 * amt, 0.015 * amt, 2.0 * amt);
    let freq_ratio = (rng.uni() * a_fr).exp(); // exp(uniform(-a_fr, a_fr))
    let r_off = rng.uni() * a_ro;
    let gain_db = rng.uni() * a_g;
    let jit = (0.08 * amt).min(0.2);

    let mut out = PackedCorners { words: packed.words };
    for ci in 0..4 {
        for si in 0..NUM_STAGES {
            let bq = stage_words_to_biquad(packed.words[ci][si]);
            if lane_span_db(bq) < FLAT_DB {
                continue; // bypass: keep verbatim, never invent a pole
            }
            let pole = match root(1.0, bq[3], bq[4]) {
                Some(p) => p,
                None => continue,
            };
            let pa = (pole.0 * freq_ratio * (1.0 + rng.uni() * jit)).clamp(MIN_ANGLE, MAX_ANGLE);
            let pr = (pole.1 + r_off + rng.uni() * jit * 0.05).clamp(0.0, R_AUTHOR_MAX);
            let (za, zr) = match root(bq[0], bq[1], bq[2]) {
                Some((za0, zr0)) => (
                    (za0 * freq_ratio * (1.0 + rng.uni() * jit)).clamp(MIN_ANGLE, MAX_ANGLE),
                    (zr0 + r_off + rng.uni() * jit * 0.05).clamp(0.0, 1.0),
                ),
                None => (pa, 0.0),
            };
            let gain = bq[0] * 10f64.powf(gain_db / 20.0) * (1.0 + rng.uni() * jit * 0.1);
            out.words[ci][si] = lane_words_from((pa, pr), (za, zr), gain);
        }
    }
    Some(out.to_rom_bytes())
}

/// Certify a body over the whole morph × Q surface: every interpolated pole radius
/// < `r_max`, all coefficients finite, on a `res`×`res` lattice.
pub fn certify_pass(body: &[u8], res: u32, r_max: f64) -> bool {
    let packed = match PackedCorners::from_body_bytes(body) {
        Ok(p) => p,
        Err(_) => return false,
    };
    let res = res.max(2);
    let denom = (res - 1) as f64;
    for qi in 0..res {
        let q = qi as f64 / denom;
        for mi in 0..res {
            let m = mi as f64 / denom;
            for row in packed.interpolate_biquad(m as f32, q as f32).iter() {
                if row.iter().any(|v| !v.is_finite()) {
                    return false;
                }
                if pole_radius(row[3], row[4]) >= r_max {
                    return false;
                }
            }
        }
    }
    true
}

/// Spawn a LEGAL sibling: perturb + certify, re-drawing the theme until a candidate
/// passes the surface gate or `max_tries` is exhausted. Returns None if no legal
/// sibling was found (the caller can widen `amt` or retry with a new seed).
pub fn seed_legal(
    body: &[u8],
    seed: u64,
    amt: f64,
    res: u32,
    r_max: f64,
    max_tries: u32,
) -> Option<[u8; BODY_BYTES]> {
    let r_max = if r_max > 0.0 { r_max } else { 0.9999 };
    for t in 0..max_tries.max(1) {
        let cand = seed_one(body, seed.wrapping_add(t as u64), amt)?;
        if certify_pass(&cand, res, r_max) {
            return Some(cand);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cartridge::CornerData;

    /// A stable resonant body: every lane a complex pole at r=0.9 plus a notch,
    /// the four corners slightly detuned so the morph surface is non-trivial.
    fn resonant_body() -> [u8; BODY_BYTES] {
        let mut words = [[[0u16; 5]; NUM_STAGES]; 4];
        for ci in 0..4 {
            let pa = 0.30 * std::f64::consts::PI * (1.0 + 0.05 * ci as f64);
            for si in 0..NUM_STAGES {
                words[ci][si] = lane_words_from((pa, 0.9), (0.5 * std::f64::consts::PI, 0.5), 1.0);
            }
        }
        PackedCorners { words }.to_rom_bytes()
    }

    #[test]
    fn seed_legal_produces_distinct_certified_sibling() {
        let body = resonant_body();
        assert!(certify_pass(&body, 65, 0.9999), "base resonant body must be legal");
        let sib = seed_legal(&body, 7, 1.0, 65, 0.9999, 24).expect("a legal sibling");
        assert_ne!(&sib[..], &body[..], "sibling must differ from the source");
        assert!(certify_pass(&sib, 129, 0.9999), "sibling must pass at authority res");
    }

    #[test]
    fn seed_is_deterministic_per_seed() {
        let body = resonant_body();
        let a = seed_legal(&body, 42, 1.0, 65, 0.9999, 24).unwrap();
        let b = seed_legal(&body, 42, 1.0, 65, 0.9999, 24).unwrap();
        assert_eq!(&a[..], &b[..], "same seed must give the same sibling");
        let c = seed_legal(&body, 43, 1.0, 65, 0.9999, 24).unwrap();
        assert_ne!(&a[..], &c[..], "different seeds should differ");
    }

    #[test]
    fn flat_lanes_kept_verbatim() {
        // Corner bank: lane 0 resonant, lane 1 a true passthrough (kernel [2,1,2,1,1]).
        let pass: CornerData = [[2.0, 1.0, 2.0, 1.0, 1.0]; NUM_STAGES];
        let mut corners = [pass; 4];
        for ci in 0..4 {
            // make lane 0 a real resonance via from_corner_data round-trip
            let lane = lane_words_from((0.3 * std::f64::consts::PI, 0.9), (0.0, 0.0), 1.0);
            let bq = stage_words_to_biquad(lane);
            corners[ci][0] = [
                bq[1] / bq[0] + 2.0,
                1.0 - bq[2] / bq[0],
                bq[3] + 2.0,
                1.0 - bq[4],
                bq[0],
            ];
        }
        let body = PackedCorners::from_corner_data(&corners).to_rom_bytes();
        let src = PackedCorners::from_body_bytes(&body).unwrap();
        let sib = seed_one(&body, 11, 1.0).unwrap();
        let sibp = PackedCorners::from_body_bytes(&sib).unwrap();
        for ci in 0..4 {
            // lane 1..5 are passthrough (flat) -> must be unchanged
            for si in 1..NUM_STAGES {
                assert_eq!(
                    src.words[ci][si], sibp.words[ci][si],
                    "flat lane {si} in corner {ci} must be verbatim"
                );
            }
        }
    }
}
