use crate::cartridge::CornerData;
use crate::cascade::{NUM_COEFFS, NUM_STAGES};
const COMBINE_K: f64 = 4.0;
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
pub fn encode(value: f64) -> u16 {
    let v = value;
    if v >= 1.0 {
        return 0xFFFF;
    }
    if v <= 0.0 {
        return 0x0000;
    }
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
#[inline]
pub fn lerp_u16(a: u16, b: u16, frac: f32) -> u16 {
    let diff = (b as i32 - a as i32) as f32;
    let delta_i16 = (diff * frac) as i32 as i16;
    (delta_i16 as i32 + a as i32) as u16
}
pub type PackedStage = [u16; NUM_COEFFS];
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
pub fn kernel_to_biquad(k: [f64; NUM_COEFFS]) -> [f64; NUM_COEFFS] {
    let [c0, c1, c2, c3, c4] = k;
    [c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, c2 - 2.0, 1.0 - c3]
}
pub fn stage_words_to_biquad(words: PackedStage) -> [f64; NUM_COEFFS] {
    kernel_to_biquad(stage_words_to_kernel(words))
}
pub const BODY_BYTES: usize = 4 * NUM_STAGES * NUM_COEFFS * 2;
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PackedCorners {
    pub words: [[PackedStage; NUM_STAGES]; 4],
}
impl PackedCorners {
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
    pub fn from_body_bytes(bytes: &[u8]) -> Result<Self, &'static str> {
        if bytes.len() != BODY_BYTES {
            return Err("body must be exactly 240 bytes (4 corners × 6 stages × 5 u16 words)");
        }
        Self::from_rom_bytes(bytes)
    }
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
    pub fn corner_kernel(&self, ci: usize) -> CornerData {
        let mut result = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
        for si in 0..NUM_STAGES {
            result[si] = stage_words_to_kernel(self.words[ci][si]);
        }
        result
    }
    pub fn interpolate_words(&self, morph: f32, q: f32) -> [PackedStage; NUM_STAGES] {
        let mut result = [[0u16; NUM_COEFFS]; NUM_STAGES];
        for si in 0..NUM_STAGES {
            let a = self.words[0][si];
            let b = self.words[1][si];
            let c = self.words[2][si];
            let d = self.words[3][si];
            for wi in 0..NUM_COEFFS {
                let edge0 = lerp_u16(a[wi], b[wi], morph);
                let edge1 = lerp_u16(c[wi], d[wi], morph);
                result[si][wi] = lerp_u16(edge0, edge1, q);
            }
        }
        result
    }
    pub fn interpolate(&self, morph: f32, q: f32) -> CornerData {
        let words = self.interpolate_words(morph, q);
        let mut result = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
        for si in 0..NUM_STAGES {
            result[si] = stage_words_to_kernel(words[si]);
        }
        result
    }
    pub fn interpolate_biquad(&self, morph: f32, q: f32) -> CornerData {
        let kernel = self.interpolate(morph, q);
        let mut result = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
        for si in 0..NUM_STAGES {
            result[si] = kernel_to_biquad(kernel[si]);
        }
        result
    }
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
pub fn pole_radius(a1: f64, a2: f64) -> f64 {
    if !a1.is_finite() || !a2.is_finite() {
        return f64::INFINITY;
    }
    let disc = a1 * a1 - 4.0 * a2;
    if disc < 0.0 {
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
        assert_eq!(decode(0x0000), 0.0);
        assert_eq!(decode(0xFFFF), 1.0);
        for w in [0x0100u16, 0x1000, 0x4000, 0x8000, 0xC000, 0xFFFE] {
            let v = decode(w);
            let w2 = encode(v);
            assert_eq!(w, w2, "encode(decode({w:#06x})) = {w2:#06x}, value={v}");
        }
    }
    #[test]
    fn lerp_u16_endpoints() {
        assert_eq!(lerp_u16(0x1000, 0x8000, 0.0), 0x1000);
        assert_eq!(lerp_u16(0x1000, 0x8000, 1.0), 0x8000);
    }
    #[test]
    fn lerp_u16_midpoint_symmetric() {
        for frac in [0.0f32, 0.25, 0.5, 0.75, 1.0] {
            assert_eq!(lerp_u16(0x4000, 0x4000, frac), 0x4000);
        }
    }
    #[test]
    fn lerp_u16_known_value() {
        assert_eq!(lerp_u16(0x1000, 0x3000, 0.5), 0x2000);
    }
    #[test]
    fn lerp_u16_wrapping_delta() {
        assert_eq!(lerp_u16(0x0000, 0xFFFF, 1.0), 0xFFFF);
    }
    #[test]
    fn from_rom_bytes_parses_corner_major_le() {
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
        let r = super::pole_radius(0.0, -0.25);
        assert!((r - 0.5).abs() < 1e-12);
    }
    #[test]
    fn pole_radius_complex_conjugate() {
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
        let b = sample_body(0x2000);
        for z in [0.0f32, 0.25, 0.5, 0.75, 1.0] {
            assert_eq!(PackedCorners::z_crossfade(&b, &b, z), b, "z={z}");
        }
    }
    #[test]
    fn z_crossfade_endpoints() {
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
                let edge0 = lerp_u16(a[wi], c[wi], q);
                let edge1 = lerp_u16(b[wi], d[wi], q);
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
        let mid_packed = pc.interpolate_biquad(0.5, 0.5);
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
                let e0 = 0.5 * (c[0][si][k] + c[1][si][k]);
                let e1 = 0.5 * (c[2][si][k] + c[3][si][k]);
                mid_coeff[si][k] = 0.5 * (e0 + e1);
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
    #[test]
    #[ignore = "renders A/B morph-sweep wavs for the interpolation law"]
    fn render_interp_law_ab() {
        const SR: f64 = 39_062.5;
        const OUT_SR: u32 = 44_100;
        const SECS: f64 = 8.0;
        const BLOCK: usize = 32;
        let p = "C:/Users/hooki/df2/desk/finishing/REF_013_talking_hedz.body240";
        let pc = PackedCorners::from_body_bytes(&std::fs::read(p).unwrap()).unwrap();
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
                    let e0 = dc[0][si][k] + (dc[1][si][k] - dc[0][si][k]) * m;
                    let e1 = dc[2][si][k] + (dc[3][si][k] - dc[2][si][k]) * m;
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
                let m = i as f64 / n as f64;
                let q = 1.0;
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
            let g = 0.5012 / pk;
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
    #[test]
    #[ignore = "diagnostic: verify the on-screen curve against the real response"]
    fn check_mason_jar() {
        const SR: f64 = 39_062.5;
        let p = "../filters/bodies/CAVL_mason_jar_to_stone_pipe.body240";
        let pc = PackedCorners::from_body_bytes(&std::fs::read(p).expect(p)).unwrap();
        let rows = pc.interpolate_biquad(0.0, 1.0);
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
