use crate::minifloat::{decode, encode};
pub const STAGE_SR: f64 = crate::compiler::AUTHORING_SR;
const TAU: f64 = core::f64::consts::PI * 2.0;
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum RootPair {
    Conjugate { hz: f64, r: f64 },
    RealPair { root_a: f64, root_b: f64 },
    Degenerate,
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct StageGeometry {
    pub pole: RootPair,
    pub zero: RootPair,
    pub scale: f64,
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct StageRoots {
    pub pole_hz: f64,
    pub pole_r: f64,
    pub zero_hz: f64,
    pub zero_r: f64,
    pub scale: f64,
}
impl StageRoots {
    pub const IDENTITY: StageRoots = StageRoots {
        pole_hz: 0.0,
        pole_r: 0.0,
        zero_hz: 0.0,
        zero_r: 0.0,
        scale: 1.0,
    };
    pub fn biquad(&self) -> [f64; 5] {
        let (wz, wp) = (TAU * self.zero_hz / STAGE_SR, TAU * self.pole_hz / STAGE_SR);
        let k = self.scale;
        [
            k,
            k * (-2.0 * self.zero_r * wz.cos()),
            k * (self.zero_r * self.zero_r),
            -2.0 * self.pole_r * wp.cos(),
            self.pole_r * self.pole_r,
        ]
    }
}
pub fn words_from_roots(r: &StageRoots) -> [u16; 5] {
    let wz = TAU * r.zero_hz / STAGE_SR;
    let wp = TAU * r.pole_hz / STAGE_SR;
    let (rz, rp) = (r.zero_r, r.pole_r);
    let c0 = 2.0 - 2.0 * rz * wz.cos();
    let c1 = 1.0 - rz * rz;
    let c2 = 2.0 - 2.0 * rp * wp.cos();
    let c3 = 1.0 - rp * rp;
    let c4 = r.scale;
    [
        encode((c0 - c1) / 4.0),
        encode(c1),
        encode((c2 - c3) / 4.0),
        encode(c3),
        encode(c4 / 4.0),
    ]
}
pub fn words_from_geometry(g: &StageGeometry) -> [u16; 5] {
    let (zero_p, zero_q) = pair_coefficients(g.zero);
    let (pole_p, pole_q) = pair_coefficients(g.pole);
    [
        encode((zero_p + 1.0 + zero_q) / 4.0),
        encode(1.0 - zero_q),
        encode((pole_p + 1.0 + pole_q) / 4.0),
        encode(1.0 - pole_q),
        encode(g.scale / 4.0),
    ]
}
fn pair_coefficients(pair: RootPair) -> (f64, f64) {
    pair_coefficients_at(pair, STAGE_SR)
}
fn pair_coefficients_at(pair: RootPair, sr: f64) -> (f64, f64) {
    match pair {
        RootPair::Conjugate { hz, r } => {
            let angle = TAU * hz / sr;
            (-2.0 * r * angle.cos(), r * r)
        }
        RootPair::RealPair { root_a, root_b } => (-(root_a + root_b), root_a * root_b),
        RootPair::Degenerate => (0.0, 0.0),
    }
}
pub fn reencode_words_at(words: [u16; 5], target_sr: f64) -> [u16; 5] {
    if target_sr == STAGE_SR {
        return words;
    }
    let ex = STAGE_SR / target_sr;
    let map = |p: RootPair| -> RootPair {
        match p {
            RootPair::Conjugate { hz, r } => RootPair::Conjugate {
                hz: hz.min(0.49 * target_sr),
                r: r.powf(ex),
            },
            RootPair::RealPair { root_a, root_b } => RootPair::RealPair {
                root_a: root_a.signum() * root_a.abs().powf(ex),
                root_b: root_b.signum() * root_b.abs().powf(ex),
            },
            RootPair::Degenerate => RootPair::Degenerate,
        }
    };
    let g = geometry_from_words(words);
    let mut g2 = StageGeometry {
        zero: map(g.zero),
        pole: map(g.pole),
        scale: g.scale,
    };
    let eval_dc = |pair: RootPair, sr: f64| -> f64 {
        let (p, q) = pair_coefficients_at(pair, sr);
        (1.0 + p + q).abs().max(1.0e-9)
    };
    let dc0 = eval_dc(g.zero, STAGE_SR) / eval_dc(g.pole, STAGE_SR);
    let dc2 = eval_dc(g2.zero, target_sr) / eval_dc(g2.pole, target_sr);
    g2.scale = (g.scale * dc0 / dc2.max(1.0e-9)).clamp(0.0, 4.0);
    let (zero_p, zero_q) = pair_coefficients_at(g2.zero, target_sr);
    let (pole_p, pole_q) = pair_coefficients_at(g2.pole, target_sr);
    [
        encode((zero_p + 1.0 + zero_q) / 4.0),
        encode(1.0 - zero_q),
        encode((pole_p + 1.0 + pole_q) / 4.0),
        encode(1.0 - pole_q),
        encode(g2.scale / 4.0),
    ]
}
pub fn geometry_from_words(words: [u16; 5]) -> StageGeometry {
    StageGeometry {
        zero: pair_geometry(decode(words[0]), decode(words[1])),
        pole: pair_geometry(decode(words[2]), decode(words[3])),
        scale: 4.0 * decode(words[4]),
    }
}
pub fn roots_from_words(words: [u16; 5]) -> Option<StageRoots> {
    let g = geometry_from_words(words);
    let (zero_hz, zero_r) = conjugate_or_origin(&g.zero)?;
    let (pole_hz, pole_r) = conjugate_or_origin(&g.pole)?;
    Some(StageRoots {
        pole_hz,
        pole_r,
        zero_hz,
        zero_r,
        scale: g.scale,
    })
}
fn conjugate_or_origin(p: &RootPair) -> Option<(f64, f64)> {
    match p {
        RootPair::Conjugate { hz, r } => Some((*hz, *r)),
        RootPair::Degenerate => Some((0.0, 0.0)),
        RootPair::RealPair { .. } => None,
    }
}
fn pair_geometry(d_mag: f64, d_rsq: f64) -> RootPair {
    let q = 1.0 - d_rsq;
    let c = 4.0 * d_mag + d_rsq;
    let p = c - 2.0;
    if p == 0.0 && q == 0.0 {
        return RootPair::Degenerate;
    }
    let disc = p * p - 4.0 * q;
    if disc < 0.0 {
        let r = q.sqrt();
        let cos_w = -p / (2.0 * r);
        RootPair::Conjugate {
            hz: cos_w.acos() / TAU * STAGE_SR,
            r,
        }
    } else {
        let s = disc.sqrt();
        RootPair::RealPair {
            root_a: (-p + s) / 2.0,
            root_b: (-p - s) / 2.0,
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::compiler::{biquad_to_words, stage_biquad};
    use crate::minifloat::stage_words_to_biquad;
    fn root_sweep() -> Vec<StageRoots> {
        let mut out = Vec::new();
        let freqs = [
            40.0, 90.0, 200.0, 440.0, 1000.0, 1200.0, 2500.0, 4500.0, 8000.0, 14000.0, 18000.0,
        ];
        let radii = [0.5, 0.7, 0.85, 0.95, 0.99, 0.999, 0.9999];
        let scales = [0.05, 0.25, 1.0, 2.0, 3.9];
        for (i, &pf) in freqs.iter().enumerate() {
            for &pr in &radii {
                let zf = freqs[(i + 3) % freqs.len()];
                let zr = radii[(i + 2) % radii.len()];
                out.push(StageRoots {
                    pole_hz: pf,
                    pole_r: pr,
                    zero_hz: zf,
                    zero_r: zr,
                    scale: scales[i % scales.len()],
                });
            }
        }
        out
    }
    #[test]
    fn words_are_a_fixed_point() {
        for r in root_sweep() {
            let w1 = words_from_roots(&r);
            match roots_from_words(w1) {
                Some(r2) => {
                    let w2 = words_from_roots(&r2);
                    assert_eq!(
                        w1, w2,
                        "words drifted for {r:?}: {w1:04x?} -> {r2:?} -> {w2:04x?}"
                    );
                }
                None => {
                    let near_dc = (r.pole_r < 0.85 && r.pole_hz < 250.0)
                        || (r.zero_r < 0.85 && r.zero_hz < 250.0);
                    assert!(near_dc, "unexpected refusal for authored {r:?}");
                }
            }
        }
    }
    #[test]
    fn quantization_bounds() {
        let mut max_dr = 0.0f64;
        let mut max_scale_db = 0.0f64;
        let mut max_resonant = 0.0f64;
        let mut max_mid = 0.0f64;
        let mut max_high_freq = 0.0f64;
        let mut collapses: Vec<(f64, f64)> = Vec::new();
        for r in root_sweep() {
            let Some(r2) = roots_from_words(words_from_roots(&r)) else {
                if r.pole_r < 0.85 && r.pole_hz < 250.0 {
                    collapses.push((r.pole_hz, r.pole_r));
                }
                if r.zero_r < 0.85 && r.zero_hz < 250.0 {
                    collapses.push((r.zero_hz, r.zero_r));
                }
                continue;
            };
            max_dr = max_dr
                .max((r2.pole_r - r.pole_r).abs())
                .max((r2.zero_r - r.zero_r).abs());
            max_scale_db = max_scale_db.max((20.0 * (r2.scale / r.scale).log10()).abs());
            let cents = |a: f64, b: f64| ((a / b).ln() / 2.0f64.ln() * 1200.0).abs();
            for (hz, rr, hz2) in [
                (r.pole_hz, r.pole_r, r2.pole_hz),
                (r.zero_hz, r.zero_r, r2.zero_hz),
            ] {
                if hz2 <= 0.0 {
                    collapses.push((hz, rr));
                    continue;
                }
                let e = cents(hz2, hz);
                if rr >= 0.95 {
                    max_resonant = max_resonant.max(e);
                }
                if rr >= 0.85 && hz >= 200.0 {
                    max_mid = max_mid.max(e);
                }
                if hz >= 440.0 {
                    max_high_freq = max_high_freq.max(e);
                }
            }
        }
        println!(
            "stage_law quantization: resonant(r≥.95) {max_resonant:.2}c · mid(r≥.85,f≥200) {max_mid:.2}c · high-freq(f≥440) {max_high_freq:.2}c · radius {max_dr:.2e} · scale {max_scale_db:.5} dB"
        );
        println!("angle-collapsed-to-DC roots (low r · low hz): {collapses:?}");
        assert!(
            max_resonant < 10.0,
            "resonant roots above 10 cents: {max_resonant}"
        );
        assert!(max_mid < 5.0, "mid-radius roots above 5 cents: {max_mid}");
        assert!(
            max_high_freq < 3.0,
            "≥440 Hz roots above 3 cents: {max_high_freq}"
        );
        assert!(max_dr < 5e-4, "radius quantization above 5e-4");
        assert!(max_scale_db < 0.01, "scale quantization above 0.01 dB");
        for (hz, r) in &collapses {
            assert!(
                *r < 0.85 && *hz < 250.0,
                "unexpected DC collapse at {hz} Hz r {r}"
            );
        }
    }
    #[test]
    fn consistent_with_biquad_to_words() {
        for r in root_sweep() {
            assert_eq!(
                words_from_roots(&r),
                biquad_to_words(r.biquad()),
                "law vs biquad_to_words diverged for {r:?}"
            );
        }
    }
    #[test]
    fn identity_is_exact() {
        let w = words_from_roots(&StageRoots::IDENTITY);
        let bq = stage_words_to_biquad(w);
        assert_eq!(bq, [1.0, 0.0, 0.0, 0.0, 0.0], "identity words {w:04x?}");
        let g = geometry_from_words(w);
        assert_eq!(g.pole, RootPair::Degenerate);
        assert_eq!(g.zero, RootPair::Degenerate);
        assert_eq!(g.scale, 1.0);
    }
    #[test]
    fn legacy_gain_disagreement_pinned() {
        let legacy = stage_biquad(&[1.0, 1200.0, 0.95, 1.0, 1.0, 4500.0, 0.90]);
        let law = StageRoots {
            pole_hz: 1200.0,
            pole_r: 0.95,
            zero_hz: 4500.0,
            zero_r: 0.90,
            scale: 1.0,
        };
        let law_b0 = roots_from_words(words_from_roots(&law)).unwrap().scale;
        let disagreement_db = 20.0 * (law_b0 / legacy[0]).log10();
        println!(
            "legacy b0 {:.6} · law b0 {law_b0:.6} · disagreement {disagreement_db:.2} dB",
            legacy[0]
        );
        assert!((legacy[0] - 0.081909).abs() < 1e-4, "legacy b0 drifted");
        assert!(
            (disagreement_db - 21.73).abs() < 0.05,
            "the pinned 21.73 dB disagreement changed: {disagreement_db:.3} dB"
        );
    }
    #[test]
    fn real_root_rows_refused_not_clamped() {
        let w_real = [
            encode(0.7),
            encode(0.75),
            encode(0.2),
            encode(0.75),
            encode(0.25),
        ];
        assert_eq!(roots_from_words(w_real), None, "real pair must be refused");
        match geometry_from_words(w_real).zero {
            RootPair::RealPair { root_a, root_b } => {
                assert!(
                    (root_a * root_b - 0.25).abs() < 1e-3,
                    "product {}",
                    root_a * root_b
                );
                assert!(
                    (root_a + root_b + 1.55).abs() < 1e-3,
                    "sum {}",
                    root_a + root_b
                );
            }
            other => panic!("expected RealPair, got {other:?}"),
        }
        let w_conj = [
            encode(0.3),
            encode(0.75),
            encode(0.2),
            encode(0.75),
            encode(0.25),
        ];
        assert!(roots_from_words(w_conj).is_some());
    }
    fn declared_stage_rows() -> Vec<([u16; 5], String)> {
        const BODY: &[u8; 240] = include_bytes!("../tests/fixtures/sf_mouth_frame.body240");
        let mut rows = Vec::with_capacity(65_560);
        for (row_index, chunk) in BODY.chunks_exact(10).enumerate() {
            let mut words = [0u16; 5];
            for (word_index, bytes) in chunk.chunks_exact(2).enumerate() {
                words[word_index] = u16::from_le_bytes([bytes[0], bytes[1]]);
            }
            rows.push((words, format!("cleanroom-body#{row_index}")));
        }
        let mut state = 0x6D2B_79F5u32;
        for row_index in 0..65_536usize {
            let mut words = [0u16; 5];
            for word in &mut words {
                state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
                *word = (state >> 16) as u16;
            }
            rows.push((words, format!("packed-sweep#{row_index}")));
        }
        rows
    }
    #[test]
    fn declared_geometry_round_trip() {
        let rows = declared_stage_rows();
        assert_eq!(rows.len(), 65_560, "declared packed sweep changed");
        let mut conjugate = 0usize;
        let mut real = 0usize;
        let mut mismatches = Vec::new();
        for (w, src) in &rows {
            match roots_from_words(*w) {
                Some(r) => {
                    conjugate += 1;
                    let w2 = words_from_roots(&r);
                    if w2 != *w {
                        mismatches.push((src.clone(), *w, w2));
                    }
                }
                None => {
                    real += 1;
                    let g = geometry_from_words(*w);
                    let has_real = matches!(g.pole, RootPair::RealPair { .. })
                        || matches!(g.zero, RootPair::RealPair { .. });
                    assert!(has_real, "{src}: refused but no real pair found");
                }
            }
        }
        println!(
            "declared geometry: {} stage rows · {conjugate} conjugate · {real} real-root (refused) · {} round-trip mismatches",
            rows.len(),
            mismatches.len()
        );
        for (src, w, w2) in mismatches.iter().take(10) {
            println!("  MISMATCH {src}: {w:04x?} -> {w2:04x?}");
        }
        assert!(
            mismatches.is_empty(),
            "{} conjugate rows failed the word-identity round trip",
            mismatches.len()
        );
    }
}
