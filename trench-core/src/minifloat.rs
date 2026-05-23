/// Packed-domain interpolation experiment — behind `packed_interp` feature flag.
///
/// Implements morph-first bilinear lerp in u16 minifloat space, faithful to the
/// E-MU/MSVC decompiled FUN_1802c3d40 formula. Not the shipping interpolation path.
///
/// Corner word derivation: when raw ROM u16 words are unavailable, words are derived
/// from decoded c0..c4 via inverse recombination. Results are labelled
/// derived-packed-canonical and do not claim historical E-MU bit parity.
use crate::cartridge::CornerData;
use crate::cascade::{NUM_COEFFS, NUM_STAGES};

const COMBINE_K: f64 = 4.0;

/// Decode u16 minifloat word to f64.
///
/// Formula: u = word + 1
///   u==65536 → 1.0 | u==1 → 0.0
///   e = (u>>12)&0xF, m = u&0xFFF
///   e==0: ldexp(m/4096, -15)  (denormal)
///   e>0:  ldexp((m|0x1000)/8192, e-15)  (normal)
pub fn decode(word: u16) -> f64 {
    let u = word as u32 + 1;
    if u == 65536 {
        return 1.0;
    }
    if u == 1 {
        return 0.0;
    }
    let e = ((u >> 12) & 0xF) as i32;
    let m = (u & 0xFFF) as f64;
    let x = if e == 0 { m / 4096.0 } else { (m + 4096.0) / 8192.0 };
    x * (2.0f64).powi(e - 15)
}

/// Encode f64 to nearest u16 minifloat word.
/// Inverse of `decode`. Used to derive packed words from decoded coefficients.
pub fn encode(value: f64) -> u16 {
    let v = value;
    if v >= 1.0 {
        return 0xFFFF;
    }
    if v <= 0.0 {
        return 0x0000;
    }

    // Try denormal range: mant * 2^-27
    let denorm_mant = (v * 134_217_728.0).round() as i64;
    if denorm_mant > 0 && denorm_mant <= 0xFFF {
        return ((denorm_mant - 1) as u64 & 0xFFFF) as u16;
    }

    let log2_val = v.log2();
    let mut exp_stored = ((log2_val.floor() as i32) + 1).min(0);
    if exp_stored < -14 {
        return 0x0000;
    }

    let mut biased_exp = exp_stored + 15;
    let mut mant_with_hidden = (v / (2.0f64).powi(exp_stored - 13)).round() as i64;

    if mant_with_hidden >= 0x2000 {
        if exp_stored < 0 {
            exp_stored += 1;
            biased_exp += 1;
            mant_with_hidden = (v / (2.0f64).powi(exp_stored - 13)).round() as i64;
            let mant = (mant_with_hidden & 0xFFF).min(0xFFF);
            let u = ((biased_exp as i64) << 12) | mant;
            return ((u - 1) & 0xFFFF) as u16;
        }
        return 0xFFFF;
    }

    let mant = (mant_with_hidden - 0x1000).clamp(0, 0xFFF);
    let u = ((biased_exp as i64) << 12) | mant;
    ((u - 1) & 0xFFFF) as u16
}

/// E-MU/MSVC-style u16 lerp: int16 truncation of the delta, then add base.
///
/// C formula: (uint16_t)((int16_t)((float)((int)b - (int)a) * frac) + a)
///
/// Critical: the (int16_t) cast wraps the delta BEFORE adding `a`.
/// Does NOT clamp — wraps per MSVC x86 behavior.
#[inline]
pub fn lerp_u16(a: u16, b: u16, frac: f32) -> u16 {
    let diff = (b as i32 - a as i32) as f32;
    // f32 multiply then truncate toward zero, wrap to i16
    let delta_i16 = (diff * frac) as i32 as i16;
    (delta_i16 as i32 + a as i32) as u16
}

/// Five packed u16 words for one biquad stage.
pub type PackedStage = [u16; NUM_COEFFS];

/// Derived-packed-canonical corner bank: 4 corners × 6 stages × 5 words.
///
/// Corner order: [0]=M0_Q0, [1]=M100_Q0, [2]=M0_Q100, [3]=M100_Q100
/// Matches `Cartridge::corners` index order.
pub struct PackedCorners {
    pub words: [[PackedStage; NUM_STAGES]; 4],
}

impl PackedCorners {
    /// Derive packed words from decoded c0..c4 corner data.
    ///
    /// Inverse recombination:
    ///   w0 = encode((c0 - c1) / 4)
    ///   w1 = encode(c1)
    ///   w2 = encode((c2 - c3) / 4)
    ///   w3 = encode(c3)
    ///   w4 = encode(c4 / 4)   (c4 scale 4.0, verified vs ROM 2026-05-19)
    pub fn from_corner_data(corners: &[CornerData; 4]) -> Self {
        let mut words = [[[0u16; NUM_COEFFS]; NUM_STAGES]; 4];
        for ci in 0..4 {
            for si in 0..NUM_STAGES {
                let [c0, c1, c2, c3, c4] = corners[ci][si];
                words[ci][si][0] = encode((c0 - c1) / COMBINE_K);
                words[ci][si][1] = encode(c1);
                words[ci][si][2] = encode((c2 - c3) / COMBINE_K);
                words[ci][si][3] = encode(c3);
                words[ci][si][4] = encode(c4 / COMBINE_K);
            }
        }
        Self { words }
    }

    /// Build a corner bank directly from a raw 240-byte ROM corner block.
    ///
    /// Layout: 4 corners (A/B/C/D = M0_Q0 / M100_Q0 / M0_Q100 / M100_Q100),
    /// contiguous, 60 bytes each; per corner 30 u16 little-endian, stage-major
    /// (6 stages × 5 words). This is the on-disk layout of
    /// `dev/tmp/cheat_engine_dump/skin13_corners_rom.bin`.
    ///
    /// Unlike `from_corner_data`, the words are taken verbatim — no decode /
    /// re-encode round-trip — so this ingests true E-mu ROM words.
    pub fn from_rom_bytes(bytes: &[u8]) -> Result<Self, &'static str> {
        const NEED: usize = 4 * NUM_STAGES * NUM_COEFFS * 2;
        if bytes.len() < NEED {
            return Err("ROM corner block must be at least 240 bytes");
        }
        let mut words = [[[0u16; NUM_COEFFS]; NUM_STAGES]; 4];
        let mut i = 0;
        for corner in words.iter_mut() {
            for stage in corner.iter_mut() {
                for w in stage.iter_mut() {
                    *w = u16::from_le_bytes([bytes[i], bytes[i + 1]]);
                    i += 2;
                }
            }
        }
        Ok(Self { words })
    }

    /// Morph-first bilinear interpolation in packed u16 space.
    ///
    /// Order: morph lerp (A→B, C→D) first, then Q lerp (edge0→edge1).
    /// Returns decoded kernel-form c0..c4 for all 6 stages.
    pub fn interpolate(&self, morph: f32, q: f32) -> CornerData {
        let mut result = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
        for si in 0..NUM_STAGES {
            let a = self.words[0][si]; // M0_Q0
            let b = self.words[1][si]; // M100_Q0
            let c = self.words[2][si]; // M0_Q100
            let d = self.words[3][si]; // M100_Q100

            let mut out_words = [0u16; NUM_COEFFS];
            for wi in 0..NUM_COEFFS {
                let edge0 = lerp_u16(a[wi], b[wi], morph); // A→B along morph
                let edge1 = lerp_u16(c[wi], d[wi], morph); // C→D along morph
                out_words[wi] = lerp_u16(edge0, edge1, q); // edge0→edge1 along Q
            }

            let d0 = decode(out_words[0]);
            let d1 = decode(out_words[1]);
            let d2 = decode(out_words[2]);
            let d3 = decode(out_words[3]);
            let d4 = decode(out_words[4]);

            result[si][0] = COMBINE_K * d0 + d1;
            result[si][1] = d1;
            result[si][2] = COMBINE_K * d2 + d3;
            result[si][3] = d3;
            result[si][4] = COMBINE_K * d4; // c4 scale 4.0 (verified vs ROM)
        }
        result
    }
}

#[cfg(test)]
mod unit_tests {
    use super::*;

    #[test]
    fn decode_encode_roundtrip_spot_checks() {
        // Known values: 0x0000=0.0, 0xFFFF=1.0
        assert_eq!(decode(0x0000), 0.0);
        assert_eq!(decode(0xFFFF), 1.0);

        // Round-trip: encode(decode(w)) should recover w (within minifloat grid)
        for w in [0x0100u16, 0x1000, 0x4000, 0x8000, 0xC000, 0xFFFE] {
            let v = decode(w);
            let w2 = encode(v);
            assert_eq!(
                w, w2,
                "encode(decode({w:#06x})) = {w2:#06x}, value={v}"
            );
        }
    }

    #[test]
    fn lerp_u16_endpoints() {
        // At frac=0 returns a; at frac=1 returns b (or b−1 due to f32 floor)
        assert_eq!(lerp_u16(0x1000, 0x8000, 0.0), 0x1000);
        // At frac=1.0: diff=28672, delta_i16=28672, result=0x8000
        assert_eq!(lerp_u16(0x1000, 0x8000, 1.0), 0x8000);
    }

    #[test]
    fn lerp_u16_midpoint_symmetric() {
        // lerp(a, a, any_frac) == a
        for frac in [0.0f32, 0.25, 0.5, 0.75, 1.0] {
            assert_eq!(lerp_u16(0x4000, 0x4000, frac), 0x4000);
        }
    }

    #[test]
    fn lerp_u16_known_value() {
        // a=0x1000 (4096), b=0x3000 (12288), frac=0.5
        // diff=8192, 8192*0.5=4096, delta_i16=4096, result=4096+4096=8192=0x2000
        assert_eq!(lerp_u16(0x1000, 0x3000, 0.5), 0x2000);
    }

    #[test]
    fn lerp_u16_wrapping_delta() {
        // a=0, b=0xFFFF, frac=1.0
        // diff=65535, 65535*1.0=65535 (f32 exact), as i32=65535, as i16=-1 (wraps)
        // result = (-1 as i32 + 0) as u16 = 65535 = 0xFFFF
        assert_eq!(lerp_u16(0x0000, 0xFFFF, 1.0), 0xFFFF);
    }

    #[test]
    fn from_rom_bytes_parses_corner_major_le() {
        // 240-byte block: 4 corners × 6 stages × 5 u16 LE, corner-major.
        // Encode the flat index in each word so the parse order is checked.
        let mut bytes = [0u8; 240];
        for (i, w) in bytes.chunks_exact_mut(2).enumerate() {
            let word = i as u16;
            w.copy_from_slice(&word.to_le_bytes());
        }
        let pc = PackedCorners::from_rom_bytes(&bytes).unwrap();
        let mut idx = 0u16;
        for ci in 0..4 {
            for si in 0..NUM_STAGES {
                for wi in 0..NUM_COEFFS {
                    assert_eq!(pc.words[ci][si][wi], idx, "corner {ci} stage {si} word {wi}");
                    idx += 1;
                }
            }
        }
        assert!(PackedCorners::from_rom_bytes(&bytes[..239]).is_err());
    }

    #[test]
    fn from_corner_data_roundtrip_at_corners() {
        // At morph=0/1, q=0/1 the packed result must recover the corner coefficients
        // to within minifloat quantization (worst case ~2^-15 per word decode error).
        let corners: [CornerData; 4] = [
            [[0.95, 0.0, 0.0, 0.0, 0.5]; 6],
            [[1.10, 0.0, 0.0, 0.0, 0.6]; 6],
            [[0.85, 0.0, 0.0, 0.0, 0.4]; 6],
            [[1.20, 0.0, 0.0, 0.0, 0.7]; 6],
        ];
        let packed = PackedCorners::from_corner_data(&corners);
        for (morph, q, ci) in [
            (0.0f32, 0.0f32, 0usize),
            (1.0f32, 0.0f32, 1usize),
            (0.0f32, 1.0f32, 2usize),
            (1.0f32, 1.0f32, 3usize),
        ] {
            let interp = packed.interpolate(morph, q);
            for si in 0..NUM_STAGES {
                for ki in 0..NUM_COEFFS {
                    let got = interp[si][ki];
                    let want = corners[ci][si][ki];
                    // Tolerance: minifloat grid spacing near these values is ~2^-14
                    assert!(
                        (got - want).abs() < 1e-3,
                        "corner {ci} stage {si} coeff {ki}: want {want}, got {got}"
                    );
                }
            }
        }
    }
}
