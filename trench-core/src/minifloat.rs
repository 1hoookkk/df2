/// Packed-domain interpolation.
///
/// Implements morph-first bilinear lerp in u16 minifloat space, faithful to the
/// E-MU/MSVC decompiled FUN_1802c3d40 formula.
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
    let x = if e == 0 {
        m / 4096.0
    } else {
        (m + 4096.0) / 8192.0
    };
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

/// Convert one packed stage to shifted minifloat-domain kernel form.
///
/// This is the decoded form used by the Python response/plot tooling:
/// `[c0, c1, c2, c3, c4]` where
/// `b0=c4`, `b1=(c0-2)*c4`, `b2=(1-c1)*c4`, `a1=c2-2`, `a2=1-c3`.
pub fn stage_words_to_kernel(words: PackedStage) -> [f64; NUM_COEFFS] {
    let d0 = decode(words[0]);
    let d1 = decode(words[1]);
    let d2 = decode(words[2]);
    let d3 = decode(words[3]);
    let d4 = decode(words[4]);

    [
        COMBINE_K * d0 + d1,
        d1,
        COMBINE_K * d2 + d3,
        d3,
        COMBINE_K * d4,
    ]
}

/// Convert shifted minifloat-domain kernel form to the runtime Cascade row.
///
/// The Rust `Cascade` consumes direct DF2T biquad coefficients:
/// `[b0, b1, b2, a1, a2]` for
/// `H(z)=(b0+b1z^-1+b2z^-2)/(1+a1z^-1+a2z^-2)`.
pub fn kernel_to_biquad(k: [f64; NUM_COEFFS]) -> [f64; NUM_COEFFS] {
    let [c0, c1, c2, c3, c4] = k;
    [c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, c2 - 2.0, 1.0 - c3]
}

/// Convert one packed stage directly to the runtime Cascade row.
pub fn stage_words_to_biquad(words: PackedStage) -> [f64; NUM_COEFFS] {
    kernel_to_biquad(stage_words_to_kernel(words))
}

/// Exact on-disk size of a df2 body: 4 corners × 6 stages × 5 u16 words × 2 bytes.
///
/// This is the canonical body container size. A raw `.body240` file and a
/// JSON `packedWords` block both serialize to exactly this many bytes.
pub const BODY_BYTES: usize = 4 * NUM_STAGES * NUM_COEFFS * 2;

/// Derived-packed-canonical corner bank: 4 corners x 6 stages x 5 words.
///
/// Corner order: [0]=M0_Q0, [1]=M100_Q0, [2]=M0_Q100, [3]=M100_Q100
/// Matches `Cartridge::corners` index order.
#[derive(Clone, Debug, PartialEq, Eq)]
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
    /// the packed-runtime coefficient map.
    ///
    /// Unlike `from_corner_data`, the words are taken verbatim — no decode /
    /// re-encode round-trip — so this ingests true E-mu ROM words.
    pub fn from_rom_bytes(bytes: &[u8]) -> Result<Self, &'static str> {
        if bytes.len() < BODY_BYTES {
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

    /// Parse a body from exactly 240 bytes — the canonical body container.
    ///
    /// Unlike `from_rom_bytes` (which slices the first 240 bytes out of a
    /// larger ROM dump), this rejects anything that is not exactly
    /// [`BODY_BYTES`] long. This is the entry point for `.body240` files and
    /// the FFI raw-byte loader.
    pub fn from_body_bytes(bytes: &[u8]) -> Result<Self, &'static str> {
        if bytes.len() != BODY_BYTES {
            return Err("body must be exactly 240 bytes (4 corners × 6 stages × 5 u16 words)");
        }
        Self::from_rom_bytes(bytes)
    }

    /// Serialize to the canonical 240-byte body layout: corner-major, 30 u16
    /// little-endian per corner, stage-major. Inverse of `from_rom_bytes`.
    pub fn to_rom_bytes(&self) -> [u8; BODY_BYTES] {
        let mut bytes = [0u8; BODY_BYTES];
        let mut i = 0;
        for corner in self.words.iter() {
            for stage in corner.iter() {
                for &w in stage.iter() {
                    let [lo, hi] = w.to_le_bytes();
                    bytes[i] = lo;
                    bytes[i + 1] = hi;
                    i += 2;
                }
            }
        }
        bytes
    }

    /// Decode one stored corner verbatim to kernel-domain coefficients.
    ///
    /// `ci` is the corner index (0=M0_Q0, 1=M100_Q0, 2=M0_Q100, 3=M100_Q100).
    /// This is the right primitive for "give me this corner as decoded
    /// coefficients" — direct unpack of the 5 u16 words per stage through
    /// `stage_words_to_kernel`. Use this instead of `interpolate(0,0)` etc.,
    /// which happens to be byte-identical at the four grid points today but
    /// depends on the f32 endpoint behaviour of `lerp_u16` and obscures intent.
    ///
    /// Panics if `ci >= 4`.
    pub fn corner_kernel(&self, ci: usize) -> CornerData {
        let mut result = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
        for si in 0..NUM_STAGES {
            result[si] = stage_words_to_kernel(self.words[ci][si]);
        }
        result
    }

    /// Morph-first bilinear interpolation in packed u16 space.
    ///
    /// Order: morph lerp (A→B, C→D) first, then Q lerp (edge0→edge1).
    /// Returns the exact five interpolated u16 words for all six stages before
    /// any decode. This is the capture primitive for turning a sampled runtime
    /// position into an authored corner without a decode/re-encode round trip.
    pub fn interpolate_words(&self, morph: f32, q: f32) -> [PackedStage; NUM_STAGES] {
        let mut result = [[0u16; NUM_COEFFS]; NUM_STAGES];
        for si in 0..NUM_STAGES {
            let a = self.words[0][si]; // M0_Q0
            let b = self.words[1][si]; // M100_Q0
            let c = self.words[2][si]; // M0_Q100
            let d = self.words[3][si]; // M100_Q100

            for wi in 0..NUM_COEFFS {
                let edge0 = lerp_u16(a[wi], b[wi], morph); // A→B along morph
                let edge1 = lerp_u16(c[wi], d[wi], morph); // C→D along morph
                result[si][wi] = lerp_u16(edge0, edge1, q); // edge0→edge1 along Q
            }
        }
        result
    }

    /// Decode the packed interpolation result to shifted minifloat-domain
    /// kernel form. Use `interpolate_biquad` for direct DF2T audio rows.
    pub fn interpolate(&self, morph: f32, q: f32) -> CornerData {
        let words = self.interpolate_words(morph, q);
        let mut result = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
        for si in 0..NUM_STAGES {
            result[si] = stage_words_to_kernel(words[si]);
        }
        result
    }

    /// Morph-first bilinear interpolation in packed u16 space, converted to
    /// the direct DF2T biquad rows consumed by `Cascade`.
    pub fn interpolate_biquad(&self, morph: f32, q: f32) -> CornerData {
        let kernel = self.interpolate(morph, q);
        let mut result = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
        for si in 0..NUM_STAGES {
            result[si] = kernel_to_biquad(kernel[si]);
        }
        result
    }

    /// Z-axis crossfade between two 4-corner plane bodies in packed u16 space.
    ///
    /// The 8-corner morph CUBE (X=Morph, Y=Q, Z=Transform) is stored as two
    /// 4-corner planes: a floor (z=0) and a ceiling (z=1). The runtime collapses
    /// the cube to one playable 4-corner body by lerping the two planes'
    /// packed words at the chosen `z`, then morph/Q-interpolating as usual.
    ///
    /// Additive: reuses `lerp_u16` (the same E-MU/MSVC u16 lerp the morph/Q
    /// bilinear uses) and touches no cascade/AGC math. `z` is clamped to 0..1.
    pub fn z_crossfade(floor: &PackedCorners, ceiling: &PackedCorners, z: f32) -> PackedCorners {
        let z = z.clamp(0.0, 1.0);
        let mut words = [[[0u16; NUM_COEFFS]; NUM_STAGES]; 4];
        for ci in 0..4 {
            for si in 0..NUM_STAGES {
                for wi in 0..NUM_COEFFS {
                    words[ci][si][wi] =
                        lerp_u16(floor.words[ci][si][wi], ceiling.words[ci][si][wi], z);
                }
            }
        }
        PackedCorners { words }
    }
}

/// Pole radius from direct DF2T biquad denominator coefficients (a1, a2).
///
/// Denominator: `z² + a1·z + a2 = 0`.
/// Returns the larger of the two pole magnitudes.
/// Returns `f64::INFINITY` if either input is nonfinite.
pub fn pole_radius(a1: f64, a2: f64) -> f64 {
    if !a1.is_finite() || !a2.is_finite() {
        return f64::INFINITY;
    }
    let disc = a1 * a1 - 4.0 * a2;
    if disc < 0.0 {
        // Complex conjugate pair: |z| = sqrt(a2).
        a2.max(0.0).sqrt()
    } else {
        let sq = disc.sqrt();
        let r1 = ((-a1 + sq) / 2.0).abs();
        let r2 = ((-a1 - sq) / 2.0).abs();
        r1.max(r2)
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
            assert_eq!(w, w2, "encode(decode({w:#06x})) = {w2:#06x}, value={v}");
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
                    assert_eq!(
                        pc.words[ci][si][wi], idx,
                        "corner {ci} stage {si} word {wi}"
                    );
                    idx += 1;
                }
            }
        }
        assert!(PackedCorners::from_rom_bytes(&bytes[..239]).is_err());
    }

    #[test]
    fn pole_radius_real_roots() {
        // Two real poles at z = 0.5 and z = -0.3 → a1 = 0.5+(-0.3) but wait:
        // (z - 0.5)(z + 0.3) = z² - 0.2z - 0.15 → a1=-0.2, a2=-0.15.
        // Hmm, Cascade convention is z²+a1z+a2 (with sign), so
        // (z - p)(z - q) = z² - (p+q)z + pq → a1=-(p+q), a2=p*q.
        // Two poles at ±0.5: a1=0, a2=-0.25 → disc = 1 → roots ±0.5 → radius=0.5.
        let r = super::pole_radius(0.0, -0.25);
        assert!((r - 0.5).abs() < 1e-12);
    }

    #[test]
    fn pole_radius_complex_conjugate() {
        // Complex pair at radius 0.9 (angle 30°): a1 = -2*0.9*cos(30°) = -√3*0.9,
        // a2 = 0.9² = 0.81. disc = (√3*0.9)² - 4*0.81 = 2.43 - 3.24 < 0.
        let a2 = 0.81f64;
        let a1 = -2.0 * 0.9 * (std::f64::consts::PI / 6.0).cos();
        let r = super::pole_radius(a1, a2);
        assert!((r - 0.9).abs() < 1e-12, "expected 0.9, got {r}");
    }

    #[test]
    fn pole_radius_nonfinite_input() {
        assert_eq!(super::pole_radius(f64::NAN, 0.5), f64::INFINITY);
        assert_eq!(super::pole_radius(0.0, f64::INFINITY), f64::INFINITY);
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

    fn sample_body(seed: u16) -> PackedCorners {
        let mut words = [[[0u16; NUM_COEFFS]; NUM_STAGES]; 4];
        let mut v = seed;
        for corner in words.iter_mut() {
            for stage in corner.iter_mut() {
                for w in stage.iter_mut() {
                    *w = v;
                    v = v.wrapping_add(0x0123).wrapping_mul(3);
                }
            }
        }
        PackedCorners { words }
    }

    #[test]
    fn z_crossfade_identity() {
        // Crossfading a body with itself returns it verbatim at any z.
        let b = sample_body(0x2000);
        for z in [0.0f32, 0.25, 0.5, 0.75, 1.0] {
            assert_eq!(PackedCorners::z_crossfade(&b, &b, z), b, "z={z}");
        }
    }

    #[test]
    fn z_crossfade_endpoints() {
        // z=0 → floor words verbatim; z=1 → ceiling words verbatim
        // (lerp_u16 is exact at the endpoints for these values).
        let floor = sample_body(0x1000);
        let ceiling = sample_body(0x9000);
        let at0 = PackedCorners::z_crossfade(&floor, &ceiling, 0.0);
        assert_eq!(at0.words, floor.words, "z=0 must equal floor");
        let at1 = PackedCorners::z_crossfade(&floor, &ceiling, 1.0);
        for ci in 0..4 {
            for si in 0..NUM_STAGES {
                for wi in 0..NUM_COEFFS {
                    let got = at1.words[ci][si][wi];
                    let want = ceiling.words[ci][si][wi];
                    // lerp_u16 at frac=1 can land one LSB short via f32 floor.
                    let d = (got as i32 - want as i32).abs();
                    assert!(
                        d <= 1,
                        "z=1 corner {ci} stage {si} word {wi}: got {got}, want {want}"
                    );
                }
            }
        }
    }

    #[test]
    fn z_crossfade_clamps_z() {
        let floor = sample_body(0x1000);
        let ceiling = sample_body(0x9000);
        assert_eq!(
            PackedCorners::z_crossfade(&floor, &ceiling, -1.0).words,
            PackedCorners::z_crossfade(&floor, &ceiling, 0.0).words
        );
        assert_eq!(
            PackedCorners::z_crossfade(&floor, &ceiling, 2.0).words,
            PackedCorners::z_crossfade(&floor, &ceiling, 1.0).words
        );
    }
}

#[cfg(test)]
mod order_probe {
    use super::*;

    /// Q-first bilinear — the OTHER order. Not shipped; used only to measure how
    /// much the (unsourced) axis-order choice actually costs.
    fn interpolate_q_first(
        pc: &PackedCorners,
        morph: f32,
        q: f32,
    ) -> [[u16; NUM_COEFFS]; NUM_STAGES] {
        let mut out = [[0u16; NUM_COEFFS]; NUM_STAGES];
        for si in 0..NUM_STAGES {
            let (a, b, c, d) = (
                pc.words[0][si],
                pc.words[1][si],
                pc.words[2][si],
                pc.words[3][si],
            );
            for wi in 0..NUM_COEFFS {
                let edge0 = lerp_u16(a[wi], c[wi], q); // M0_Q0 -> M0_Q100   along Q
                let edge1 = lerp_u16(b[wi], d[wi], q); // M100_Q0 -> M100_Q100
                out[si][wi] = lerp_u16(edge0, edge1, morph);
            }
        }
        out
    }

    fn interpolate_morph_first(
        pc: &PackedCorners,
        morph: f32,
        q: f32,
    ) -> [[u16; NUM_COEFFS]; NUM_STAGES] {
        let mut out = [[0u16; NUM_COEFFS]; NUM_STAGES];
        for si in 0..NUM_STAGES {
            let (a, b, c, d) = (
                pc.words[0][si],
                pc.words[1][si],
                pc.words[2][si],
                pc.words[3][si],
            );
            for wi in 0..NUM_COEFFS {
                let edge0 = lerp_u16(a[wi], b[wi], morph);
                let edge1 = lerp_u16(c[wi], d[wi], morph);
                out[si][wi] = lerp_u16(edge0, edge1, q);
            }
        }
        out
    }

    /// Does the (unsourced) bilinear axis order actually change the bits, and by
    /// how much, on the REAL shipping roster?
    ///   cargo test -p trench-core --lib order_probe -- --ignored --nocapture
    #[test]
    #[ignore = "diagnostic: morph-first vs Q-first bilinear on the real roster"]
    fn bilinear_axis_order_sensitivity() {
        let dir = std::path::Path::new("../filters/bodies");
        let mut files: Vec<_> = std::fs::read_dir(dir)
            .expect("filters/bodies")
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.extension().map(|x| x == "body240").unwrap_or(false))
            .collect();
        files.sort();

        let (mut total, mut differ) = (0u64, 0u64);
        let mut max_delta = 0i32;
        let mut worst = String::new();
        let mut bodies_affected = 0;

        for f in &files {
            let bytes = std::fs::read(f).unwrap();
            let pc = match PackedCorners::from_body_bytes(&bytes) {
                Ok(p) => p,
                Err(_) => continue,
            };
            let mut this_body_differs = false;
            for mi in 0..=10 {
                for qi in 0..=10 {
                    let (m, q) = (mi as f32 / 10.0, qi as f32 / 10.0);
                    let a = interpolate_morph_first(&pc, m, q);
                    let b = interpolate_q_first(&pc, m, q);
                    for si in 0..NUM_STAGES {
                        for wi in 0..NUM_COEFFS {
                            total += 1;
                            let d = a[si][wi] as i32 - b[si][wi] as i32;
                            if d != 0 {
                                differ += 1;
                                this_body_differs = true;
                                if d.abs() > max_delta {
                                    max_delta = d.abs();
                                    worst = format!(
                                        "{} m={m:.1} q={q:.1} stage{si} word{wi}: {} vs {}",
                                        f.file_name().unwrap().to_string_lossy(),
                                        a[si][wi],
                                        b[si][wi]
                                    );
                                }
                            }
                        }
                    }
                }
            }
            if this_body_differs {
                bodies_affected += 1;
            }
        }

        println!("\n=== bilinear axis order: morph-first (SHIPPED) vs Q-first ===");
        println!(
            "roster: {} bodies, 11x11 morph/Q grid, all 6 stages x 5 words\n",
            files.len()
        );
        println!("  words compared      : {total}");
        println!(
            "  words that DIFFER   : {differ}  ({:.2}%)",
            100.0 * differ as f64 / total as f64
        );
        println!(
            "  bodies affected     : {bodies_affected} / {}",
            files.len()
        );
        println!("  max |delta| (packed): {max_delta} LSB");
        if !worst.is_empty() {
            println!("  worst               : {worst}");
        }
        if differ == 0 {
            println!("\n  -> the order is IRRELEVANT. Both give identical bits. Non-issue.");
        } else {
            println!(
                "\n  -> the orders differ in BITS. But is that AUDIBLE? Decode and compare in dB."
            );
        }

        // Differing bits is not the question — audibility is. A packed word is a
        // minifloat, so 1-2 LSB is a small RELATIVE step. Decode both orders to
        // biquad coefficients and compare the actual magnitude response.
        const SR: f64 = 39_062.5;
        let mut max_db = 0.0f64;
        let mut where_db = String::new();
        let mut all: Vec<f64> = Vec::new();
        for f in &files {
            let bytes = std::fs::read(f).unwrap();
            let pc = match PackedCorners::from_body_bytes(&bytes) {
                Ok(p) => p,
                Err(_) => continue,
            };
            for mi in 0..=10 {
                for qi in 0..=10 {
                    let (m, q) = (mi as f32 / 10.0, qi as f32 / 10.0);
                    let wa = interpolate_morph_first(&pc, m, q);
                    let wb = interpolate_q_first(&pc, m, q);
                    let ka: Vec<[f64; NUM_COEFFS]> = (0..NUM_STAGES)
                        .map(|si| kernel_to_biquad(stage_words_to_kernel(wa[si])))
                        .collect();
                    let kb: Vec<[f64; NUM_COEFFS]> = (0..NUM_STAGES)
                        .map(|si| kernel_to_biquad(stage_words_to_kernel(wb[si])))
                        .collect();

                    let mag = |rows: &Vec<[f64; NUM_COEFFS]>, w: f64| -> f64 {
                        let (cw, sw) = (w.cos(), w.sin());
                        let (c2w, s2w) = ((2.0 * w).cos(), (2.0 * w).sin());
                        let mut acc = 1.0f64;
                        for r in rows {
                            let (b0, b1, b2, a1, a2) = (r[0], r[1], r[2], r[3], r[4]);
                            let nr = b0 + b1 * cw + b2 * c2w;
                            let ni = -(b1 * sw + b2 * s2w);
                            let dr = 1.0 + a1 * cw + a2 * c2w;
                            let di = -(a1 * sw + a2 * s2w);
                            let n = (nr * nr + ni * ni).sqrt();
                            let d = (dr * dr + di * di).sqrt().max(1e-12);
                            acc *= n / d;
                        }
                        acc.max(1e-12)
                    };

                    for k in 0..200 {
                        let hz = 20.0 * (19_000.0f64 / 20.0).powf(k as f64 / 199.0);
                        let w = 2.0 * std::f64::consts::PI * hz / SR;
                        let d = 20.0 * (mag(&ka, w) / mag(&kb, w)).log10();
                        all.push(d.abs());
                        if d.abs() > max_db {
                            max_db = d.abs();
                            where_db = format!(
                                "{} m={m:.1} q={q:.1} @ {hz:.0} Hz",
                                f.file_name().unwrap().to_string_lossy()
                            );
                        }
                    }
                }
            }
        }
        all.sort_by(|x, y| x.partial_cmp(y).unwrap());
        let pct = |p: f64| all[((all.len() - 1) as f64 * p) as usize];
        println!("\n=== the same question, in dB — what your ear actually gets ===");
        println!("  {} response points compared\n", all.len());
        println!("    median   {:.4} dB", pct(0.50));
        println!("    p90      {:.4} dB", pct(0.90));
        println!("    p99      {:.4} dB", pct(0.99));
        println!("    p99.9    {:.4} dB", pct(0.999));
        println!("    max      {:.4} dB   <- {where_db}", max_db);
        println!(
            "\n  (dB blows up near a notch even when little changed — judge on the\n   median/p99, not the max, which lands on a notch body by construction.)"
        );
        if pct(0.99) < 0.1 {
            println!("\n  -> Typical difference is INAUDIBLE. The axis order is a non-issue in practice,");
            println!("     but it remains UNSOURCED — worth settling if you ever null against a real X3.");
        } else {
            println!("\n  -> AUDIBLE at the typical case. The unsourced axis order is changing the sound.");
        }
    }
}

#[cfg(test)]
mod x3_groundtruth {
    use super::*;

    /// Dump our packed-bilinear response at the 4 corners + the midpoint, so it
    /// can be nulled against real X3 renders of the same preset.
    ///
    /// The reference body is read from df2 AT RUNTIME (never vendored) — P2K
    /// material is study evidence and no protected bytes enter this repo.
    ///   cargo test -p trench-core --lib dump_hedz_response -- --ignored --nocapture
    #[test]
    #[ignore = "ground truth: dump our response for nulling against X3 renders"]
    fn dump_hedz_response() {
        const SR: f64 = 39_062.5;
        let p = "C:/Users/hooki/df2/desk/finishing/REF_013_talking_hedz.body240";
        let bytes = std::fs::read(p).expect("reference body (evidence, external)");
        let pc = PackedCorners::from_body_bytes(&bytes).expect("240 bytes");

        let pts = [
            ("m0q0", 0.0f32, 0.0f32),
            ("m0q1", 0.0, 1.0),
            ("m1q0", 1.0, 0.0),
            ("m1q1", 1.0, 1.0),
            ("m50q50", 0.5, 0.5),
        ];

        let mut out = String::from("hz");
        for (n, _, _) in &pts {
            out.push('\t');
            out.push_str(n);
        }
        out.push('\n');

        for k in 0..512 {
            let hz = 20.0 * (19_000.0f64 / 20.0).powf(k as f64 / 511.0);
            let w = 2.0 * std::f64::consts::PI * hz / SR;
            let (cw, sw) = (w.cos(), w.sin());
            let (c2w, s2w) = ((2.0 * w).cos(), (2.0 * w).sin());
            out.push_str(&format!("{hz:.3}"));
            for (_, m, q) in &pts {
                let rows = pc.interpolate_biquad(*m, *q);
                let mut acc = 1.0f64;
                for r in rows.iter() {
                    let (b0, b1, b2, a1, a2) = (r[0], r[1], r[2], r[3], r[4]);
                    let nr = b0 + b1 * cw + b2 * c2w;
                    let ni = -(b1 * sw + b2 * s2w);
                    let dr = 1.0 + a1 * cw + a2 * c2w;
                    let di = -(a1 * sw + a2 * s2w);
                    acc *= (nr * nr + ni * ni).sqrt() / (dr * dr + di * di).sqrt().max(1e-12);
                }
                out.push_str(&format!("\t{:.6}", 20.0 * acc.max(1e-12).log10()));
            }
            out.push('\n');
        }
        let dst = "C:/WINDOWS/TEMP/claude/C--Users-hooki-df2-workstation/c08ea51b-7464-4c34-82ce-729142ff350c/scratchpad/ours_hedz.tsv";
        std::fs::write(dst, out).unwrap();
        println!("wrote {dst}");
    }

    #[test]
    fn interpolate_words_is_the_exact_source_of_decoded_interpolation() {
        let mut bytes = [0u8; BODY_BYTES];
        for (index, pair) in bytes.chunks_exact_mut(2).enumerate() {
            pair.copy_from_slice(&(0x2710u16.wrapping_add(index as u16 * 97)).to_le_bytes());
        }
        let packed = PackedCorners::from_body_bytes(&bytes).unwrap();
        let words = packed.interpolate_words(0.37, 0.64);
        let decoded = packed.interpolate(0.37, 0.64);
        for stage in 0..NUM_STAGES {
            assert_eq!(stage_words_to_kernel(words[stage]), decoded[stage]);
        }
    }
}

#[cfg(test)]
mod interp_law {
    use super::*;

    /// Which interpolation law does the real machine use?
    ///
    /// Emits the midpoint response under two competing laws, from the SAME body:
    ///   A: lerp the packed u16 WORDS, then decode   (what we ship)
    ///   B: decode the corners, then lerp the COEFFICIENTS
    /// Plus the four corners. A third candidate (lerp the response in dB) is
    /// computed downstream in Python from the corners.
    ///   cargo test -p trench-core --lib dump_interp_laws -- --ignored --nocapture
    #[test]
    #[ignore = "ground truth: which interpolation law does the X3 use"]
    fn dump_interp_laws() {
        const SR: f64 = 39_062.5;
        let p = "C:/Users/hooki/df2/desk/finishing/REF_013_talking_hedz.body240";
        let bytes = std::fs::read(p).expect("reference body (external evidence)");
        let pc = PackedCorners::from_body_bytes(&bytes).unwrap();

        let resp = |rows: &[[f64; NUM_COEFFS]; NUM_STAGES], hz: f64| -> f64 {
            let w = 2.0 * std::f64::consts::PI * hz / SR;
            let (cw, sw) = (w.cos(), w.sin());
            let (c2w, s2w) = ((2.0 * w).cos(), (2.0 * w).sin());
            let mut acc = 1.0f64;
            for r in rows.iter() {
                let (b0, b1, b2, a1, a2) = (r[0], r[1], r[2], r[3], r[4]);
                let nr = b0 + b1 * cw + b2 * c2w;
                let ni = -(b1 * sw + b2 * s2w);
                let dr = 1.0 + a1 * cw + a2 * c2w;
                let di = -(a1 * sw + a2 * s2w);
                acc *= (nr * nr + ni * ni).sqrt() / (dr * dr + di * di).sqrt().max(1e-12);
            }
            20.0 * acc.max(1e-12).log10()
        };

        // A: shipped — lerp packed words at (0.5, 0.5), then decode.
        let mid_packed = pc.interpolate_biquad(0.5, 0.5);

        // B: decode all four corners first, then bilinear the COEFFICIENTS.
        let c: Vec<[[f64; NUM_COEFFS]; NUM_STAGES]> = (0..4)
            .map(|ci| {
                let mut rows = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
                for si in 0..NUM_STAGES {
                    rows[si] = kernel_to_biquad(stage_words_to_kernel(pc.words[ci][si]));
                }
                rows
            })
            .collect();
        let mut mid_coeff = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
        for si in 0..NUM_STAGES {
            for k in 0..NUM_COEFFS {
                // corners: 0=M0Q0 1=M100Q0 2=M0Q100 3=M100Q100
                let e0 = 0.5 * (c[0][si][k] + c[1][si][k]); // along morph @ q0
                let e1 = 0.5 * (c[2][si][k] + c[3][si][k]); // along morph @ q1
                mid_coeff[si][k] = 0.5 * (e0 + e1); // along q
            }
        }

        let corners: Vec<_> = (0..4)
            .map(|ci| {
                let mut rows = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
                for si in 0..NUM_STAGES {
                    rows[si] = kernel_to_biquad(stage_words_to_kernel(pc.words[ci][si]));
                }
                rows
            })
            .collect();

        let mut out = String::from("hz\tc_m0q0\tc_m1q0\tc_m0q1\tc_m1q1\tA_packed\tB_coeff\n");
        for k in 0..512 {
            let hz = 20.0 * (19_000.0f64 / 20.0).powf(k as f64 / 511.0);
            out.push_str(&format!("{hz:.3}"));
            for ci in 0..4 {
                out.push_str(&format!("\t{:.6}", resp(&corners[ci], hz)));
            }
            out.push_str(&format!("\t{:.6}", resp(&mid_packed, hz)));
            out.push_str(&format!("\t{:.6}\n", resp(&mid_coeff, hz)));
        }
        let dst = "C:/WINDOWS/TEMP/claude/C--Users-hooki-df2-workstation/c08ea51b-7464-4c34-82ce-729142ff350c/scratchpad/interp_laws.tsv";
        std::fs::write(dst, out).unwrap();
        println!("wrote {dst}");
    }
}

#[cfg(test)]
mod interp_law_audio {
    use super::*;
    use crate::cascade::Cascade;

    /// Render a pink-noise MORPH SWEEP under both interpolation laws, so the
    /// difference can be heard rather than argued about.
    ///
    ///   A: lerp packed u16 WORDS, then decode  (shipped)
    ///   B: decode corners, then lerp COEFFICIENTS
    ///
    /// Cascade only — no AGC, no saturator — so nothing but the interpolation law
    /// differs. Both are peak-normalised to the same level: judge character, not
    /// loudness.
    ///   cargo test -p trench-core --lib render_interp_law_ab -- --ignored --nocapture
    #[test]
    #[ignore = "renders A/B morph-sweep wavs for the interpolation law"]
    fn render_interp_law_ab() {
        const SR: f64 = 39_062.5;
        const OUT_SR: u32 = 44_100;
        const SECS: f64 = 8.0;
        const BLOCK: usize = 32;

        let p = "C:/Users/hooki/df2/desk/finishing/REF_013_talking_hedz.body240";
        let pc = PackedCorners::from_body_bytes(&std::fs::read(p).unwrap()).unwrap();

        // decoded corners, for law B
        let dc: Vec<CornerData> = (0..4)
            .map(|ci| {
                let mut rows = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
                for si in 0..NUM_STAGES {
                    rows[si] = kernel_to_biquad(stage_words_to_kernel(pc.words[ci][si]));
                }
                rows
            })
            .collect();

        let law_b = |m: f64, q: f64| -> CornerData {
            let mut out = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
            for si in 0..NUM_STAGES {
                for k in 0..NUM_COEFFS {
                    let e0 = dc[0][si][k] + (dc[1][si][k] - dc[0][si][k]) * m; // morph @ q0
                    let e1 = dc[2][si][k] + (dc[3][si][k] - dc[2][si][k]) * m; // morph @ q1
                    out[si][k] = e0 + (e1 - e0) * q;
                }
            }
            out
        };

        let n = (SECS * SR) as usize;
        let render = |packed_law: bool| -> Vec<f32> {
            let mut casc = Cascade::new();
            let mut rng = 0x2545_F491_4F6C_DD1Du64;
            let mut pb = [0f64; 7];
            let mut out = Vec::with_capacity(n);
            let mut i = 0;
            while i < n {
                let len = BLOCK.min(n - i);
                let m = i as f64 / n as f64; // morph sweeps 0 -> 1
                let q = 1.0; // max bloom: where the laws diverge most
                let corner = if packed_law {
                    pc.interpolate_biquad(m as f32, q as f32)
                } else {
                    law_b(m, q)
                };
                casc.set_targets(&corner, len);
                let mut buf: Vec<f32> = (0..len)
                    .map(|_| {
                        rng = rng
                            .wrapping_mul(6364136223846793005)
                            .wrapping_add(1442695040888963407);
                        let w = ((rng >> 40) as f64 / (1u64 << 23) as f64) - 1.0;
                        pb[0] = 0.99886 * pb[0] + w * 0.0555179;
                        pb[1] = 0.99332 * pb[1] + w * 0.0750759;
                        pb[2] = 0.96900 * pb[2] + w * 0.1538520;
                        pb[3] = 0.86650 * pb[3] + w * 0.3104856;
                        pb[4] = 0.55000 * pb[4] + w * 0.5329522;
                        pb[5] = -0.7616 * pb[5] - w * 0.0168980;
                        let s =
                            (pb[0] + pb[1] + pb[2] + pb[3] + pb[4] + pb[5] + pb[6] + w * 0.5362)
                                * 0.11;
                        pb[6] = w * 0.115926;
                        (s * 0.5) as f32
                    })
                    .collect();
                casc.process_block_mono(&mut buf);
                out.extend_from_slice(&buf);
                i += len;
            }
            out
        };

        let write_wav = |path: &str, s: &[f32]| {
            // resample to 44.1k, peak-normalise to -6 dBFS so the A/B is level-matched
            let ratio = SR / OUT_SR as f64;
            let on = (s.len() as f64 / ratio) as usize;
            let mut r: Vec<f32> = (0..on)
                .map(|i| {
                    let pos = i as f64 * ratio;
                    let i0 = pos.floor() as usize;
                    let fr = (pos - i0 as f64) as f32;
                    let a = s.get(i0).copied().unwrap_or(0.0);
                    let b = s.get(i0 + 1).copied().unwrap_or(a);
                    a + (b - a) * fr
                })
                .collect();
            let pk = r.iter().fold(0.0f32, |m, &x| m.max(x.abs())).max(1e-9);
            let g = 0.5012 / pk; // -6 dBFS
            for x in r.iter_mut() {
                *x *= g;
            }
            let mut b = Vec::new();
            let dl = (r.len() * 2) as u32;
            b.extend_from_slice(b"RIFF");
            b.extend_from_slice(&(36 + dl).to_le_bytes());
            b.extend_from_slice(b"WAVEfmt ");
            b.extend_from_slice(&16u32.to_le_bytes());
            b.extend_from_slice(&1u16.to_le_bytes());
            b.extend_from_slice(&1u16.to_le_bytes());
            b.extend_from_slice(&OUT_SR.to_le_bytes());
            b.extend_from_slice(&(OUT_SR * 2).to_le_bytes());
            b.extend_from_slice(&2u16.to_le_bytes());
            b.extend_from_slice(&16u16.to_le_bytes());
            b.extend_from_slice(b"data");
            b.extend_from_slice(&dl.to_le_bytes());
            for &x in &r {
                b.extend_from_slice(&((x.clamp(-1.0, 1.0) * 32767.0) as i16).to_le_bytes());
            }
            std::fs::write(path, b).unwrap();
            println!("  wrote {path}  (peak-normalised to -6 dBFS)");
        };

        let dir = "C:/Users/hooki/df2-workstation/out/interp_law_ab";
        std::fs::create_dir_all(dir).unwrap();
        println!("\nTalking Hedz, q=1 (max bloom), morph sweeping 0 -> 1 over 8 s, pink noise.");
        println!("Cascade only. No AGC, no saturator. Level-matched.\n");
        write_wav(&format!("{dir}/A_packed_words_SHIPPED.wav"), &render(true));
        write_wav(&format!("{dir}/B_coefficients.wav"), &render(false));
    }
}

#[cfg(test)]
mod curve_check {
    use super::*;
    /// Is the UI curve telling the truth? Compute the real response of the body
    /// on screen at the exact morph/Q shown.
    ///   cargo test -p trench-core --lib check_mason_jar -- --ignored --nocapture
    #[test]
    #[ignore = "diagnostic: verify the on-screen curve against the real response"]
    fn check_mason_jar() {
        const SR: f64 = 39_062.5;
        let p = "../filters/bodies/CAVL_mason_jar_to_stone_pipe.body240";
        let pc = PackedCorners::from_body_bytes(&std::fs::read(p).expect(p)).unwrap();
        let rows = pc.interpolate_biquad(0.0, 1.0); // MORPH 0, Q 100 — as on screen

        let mag = |hz: f64| -> f64 {
            let w = 2.0 * std::f64::consts::PI * hz / SR;
            let (cw, sw) = (w.cos(), w.sin());
            let (c2, s2) = ((2.0 * w).cos(), (2.0 * w).sin());
            let mut acc = 1.0f64;
            for r in rows.iter() {
                let (b0, b1, b2, a1, a2) = (r[0], r[1], r[2], r[3], r[4]);
                let nr = b0 + b1 * cw + b2 * c2;
                let ni = -(b1 * sw + b2 * s2);
                let dr = 1.0 + a1 * cw + a2 * c2;
                let di = -(a1 * sw + a2 * s2);
                acc *= (nr * nr + ni * ni).sqrt() / (dr * dr + di * di).sqrt().max(1e-12);
            }
            20.0 * acc.max(1e-12).log10()
        };

        // find every resonance
        let n = 4000;
        let f: Vec<f64> = (0..n)
            .map(|k| 20.0 * (19_000.0f64 / 20.0).powf(k as f64 / (n - 1) as f64))
            .collect();
        let d: Vec<f64> = f.iter().map(|&hz| mag(hz)).collect();
        println!(
            "\n=== CAVL_mason_jar_to_stone_pipe @ MORPH 0, Q 100 (what is on your screen) ===\n"
        );
        println!("  peaks the BODY actually has:");
        for i in 1..n - 1 {
            if d[i] > d[i - 1] && d[i] > d[i + 1] && d[i] > -25.0 {
                println!("    {:8.0} Hz   {:+7.1} dB", f[i], d[i]);
            }
        }
        println!("\n  stage pole radii (Q) — how sharp each is:");
        for (si, r) in rows.iter().enumerate() {
            let rad = pole_radius(r[3], r[4]);
            println!(
                "    stage {si}: radius {rad:.5}{}",
                if rad > 0.9995 {
                    "   <-- RAZOR (near-unstable)"
                } else {
                    ""
                }
            );
        }
    }
}
