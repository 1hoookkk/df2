//! THE canonical stage law — `roots + SCALE ↔ five packed words`.
//!
//! First-principles verdict 2026-07-12 (tightened same day per the
//! hallucination-ledger review): the runtime object is a quantised
//! coefficient field, and the five packed words of one stage store EXACTLY a
//! root pair each for numerator and denominator, plus a scalar:
//!
//! ```text
//! H_s(z) = k · (1 + p_z·z⁻¹ + q_z·z⁻²) / (1 + p_p·z⁻¹ + q_p·z⁻²)
//!
//! word d0 = (p_z + 1 + q_z) / 4        (numerator:  c0 = p_z + 2)
//! word d1 = 1 − q_z
//! word d2 = (p_p + 1 + q_p) / 4        (denominator: c2 = p_p + 2)
//! word d3 = 1 − q_p
//! word d4 = k / 4                       (SCALE = b0 — representable k ∈ [0,4])
//! ```
//!
//! A quadratic pair is NOT always a conjugate pair: packed rows in the wild
//! (measured over 32 JUCE cartridges on a 9×9 Morph/Q sweep) contain
//! independent REAL root pairs. The decoding API is therefore non-silent:
//! [`geometry_from_words`] classifies every row exactly as `Conjugate`,
//! `RealPair`, or `Degenerate`, and [`roots_from_words`] REFUSES (returns
//! `None`) instead of clamping a real pair into an approximate conjugate.
//! No packed row ever becomes approximate editable roots silently.
//!
//! SCALE is the numerator scalar `k = b0`. It is NOT a normalized "gain":
//! the legacy `compiler::stage_biquad` interprets its gain param as
//! DC-normalized whenever a zero exists (a policy kept only for byte-exact
//! migration parity). The two interpretations disagree by 21.73 dB on the
//! reference stage (pole 1200 Hz r .95 · zero 4500 Hz r .90 · "0 dB") — the
//! pinned test below memorializes that so it can never become ambiguous again.
//!
//! Inactive stage = the IDENTITY biquad `[1,0,0,0,0]` (pole and zero pairs at
//! the origin, scale = 1). There is no packed on/off bit; "off at one pose,
//! active at another" morphs the stage in through the real packed interpolation.

use crate::minifloat::{decode, encode};

pub const STAGE_SR: f64 = crate::compiler::AUTHORING_SR;
const TAU: f64 = core::f64::consts::PI * 2.0;

/// Exact classification of one quadratic root pair as stored in two packed
/// words. Every packed row is one of these — nothing is clamped or invented.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum RootPair {
    /// Complex-conjugate pair: the editable authoring form.
    Conjugate { hz: f64, r: f64 },
    /// Two independent real roots on the z-plane real axis (|root| may
    /// differ). Exact inspection form — NOT editable as (hz, r).
    RealPair { root_a: f64, root_b: f64 },
    /// Both roots at the origin (the pair contributes only its scalar) —
    /// the identity-side case, editable as radius 0.
    Degenerate,
}

/// One stage decoded exactly: numerator pair, denominator pair, SCALE.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct StageGeometry {
    pub pole: RootPair,
    pub zero: RootPair,
    /// k = b0.
    pub scale: f64,
}

/// The five true authoring variables of one stage — the CONJUGATE authoring
/// domain of the law. Radius 0 means "pair at the origin" (no angle).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct StageRoots {
    pub pole_hz: f64,
    pub pole_r: f64,
    pub zero_hz: f64,
    pub zero_r: f64,
    /// SCALE — the numerator scalar k = b0. Unity = 1.0. Representable [0, 4].
    pub scale: f64,
}

impl StageRoots {
    /// H(z) = 1 — the honest meaning of "this stage is off at this pose".
    pub const IDENTITY: StageRoots = StageRoots {
        pole_hz: 0.0,
        pole_r: 0.0,
        zero_hz: 0.0,
        zero_r: 0.0,
        scale: 1.0,
    };

    /// The a0-normalized DF2T row `[b0,b1,b2,a1,a2]` this law defines.
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

/// roots + scale → the five packed words. The single forward direction of the
/// law; identical by construction to `compiler::biquad_to_words(roots.biquad())`.
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
        encode((c0 - c1) / 4.0), // = |1 − r_z e^{jω_z}|² / 4  ≥ 0 by construction
        encode(c1),
        encode((c2 - c3) / 4.0),
        encode(c3),
        encode(c4 / 4.0),
    ]
}

/// Exact root-pair geometry + scale -> five packed words.
///
/// Unlike [`words_from_roots`], this accepts independent real-root pairs. It
/// is the authoring path for an explicit real-pair edit; no pair is silently
/// projected into conjugate Hz/radius controls.
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
    match pair {
        RootPair::Conjugate { hz, r } => {
            let angle = TAU * hz / STAGE_SR;
            (-2.0 * r * angle.cos(), r * r)
        }
        RootPair::RealPair { root_a, root_b } => (-(root_a + root_b), root_a * root_b),
        RootPair::Degenerate => (0.0, 0.0),
    }
}

/// five packed words → exact stage geometry. Always succeeds, never
/// approximates: real-root rows come back as [`RootPair::RealPair`] verbatim.
pub fn geometry_from_words(words: [u16; 5]) -> StageGeometry {
    StageGeometry {
        zero: pair_geometry(decode(words[0]), decode(words[1])),
        pole: pair_geometry(decode(words[2]), decode(words[3])),
        scale: 4.0 * decode(words[4]),
    }
}

/// five packed words → conjugate authoring roots, or an explicit REFUSAL.
/// Returns `Some` only when BOTH pairs are conjugate (or degenerate-origin,
/// which reads as radius 0). A row containing a real root pair returns
/// `None` — inspect it through [`geometry_from_words`] instead. Nothing is
/// ever clamped into an approximate conjugate reading.
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
    // words store: d_rsq = 1 − q, d_mag = (c − (1 − q))/4 with c = p + 2,
    // for the monic quadratic 1 + p·z⁻¹ + q·z⁻² (roots of z² + p·z + q).
    let q = 1.0 - d_rsq;
    let c = 4.0 * d_mag + d_rsq;
    let p = c - 2.0;
    if p == 0.0 && q == 0.0 {
        return RootPair::Degenerate;
    }
    let disc = p * p - 4.0 * q;
    if disc < 0.0 {
        let r = q.sqrt();
        let cos_w = -p / (2.0 * r); // |cos| < 1 exactly when disc < 0
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

    /// The invertibility law: after ONE quantization, words are a fixed point.
    /// roots → words → roots → words must be word-identical. Near-DC
    /// low-radius roots may quantize into a repeated REAL pair — the reader
    /// then refuses honestly instead of round-tripping an approximation; the
    /// test verifies every refusal is in that known degradation domain.
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

    /// Quantization is the ONLY loss, honestly characterized. MEASURED
    /// envelope (2026-07-12 profile over hz × r):
    ///   · radius error ≤ ~1.6e-5 and scale error ≤ ~0.0005 dB everywhere
    ///   · RESONANT roots (r ≥ 0.95): < 10 cents at every freq ≥ 40 Hz —
    ///     precision concentrates exactly where poles matter musically
    ///   · r ≥ 0.85 at freq ≥ 200 Hz: < 5 cents
    ///   · any radius at freq ≥ 440 Hz: < 3 cents
    ///   · LOW-radius LOW-frequency roots degrade (e.g. ~177 cents at
    ///     40 Hz r 0.85) and can collapse to DC — the angle offset falls
    ///     under one minifloat grid step. A true format fact, reported,
    ///     never hidden; audibly these are broad near-DC tilts.
    #[test]
    fn quantization_bounds() {
        let mut max_dr = 0.0f64;
        let mut max_scale_db = 0.0f64;
        let mut max_resonant = 0.0f64; // r ≥ 0.95, any freq
        let mut max_mid = 0.0f64; // r ≥ 0.85, freq ≥ 200
        let mut max_high_freq = 0.0f64; // any r, freq ≥ 440
        let mut collapses: Vec<(f64, f64)> = Vec::new();
        for r in root_sweep() {
            // near-DC low-radius rows can quantize into a real pair: the
            // reader refuses those; they are the collapse cases by definition
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
        // every collapse must be a genuinely near-DC, low-radius root
        for (hz, r) in &collapses {
            assert!(
                *r < 0.85 && *hz < 250.0,
                "unexpected DC collapse at {hz} Hz r {r}"
            );
        }
    }

    /// One owner: the law's forward direction is bit-identical to packing its
    /// own biquad through the historical `biquad_to_words` path.
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

    /// "Off" means the identity biquad, exactly — decodable back to [1,0,0,0,0].
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

    /// PINNED FINDING (2026-07-12): the legacy compiler's `gain` is DC-normalized
    /// when a zero exists; the format's SCALE is b0. For the reference stage the
    /// two "0 dB" interpretations disagree by 21.73 dB. SCALE is the law;
    /// stage_biquad's normalization is a compatibility policy, not authority.
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

    /// Real-root rows are REFUSED by the conjugate reader and returned exactly
    /// by the geometry reader — never clamped into an approximate conjugate.
    #[test]
    fn real_root_rows_refused_not_clamped() {
        // d_rsq = 0.75 → q = 0.25; conjugate needs p² < 4q = 1, i.e. c ∈ (1, 3),
        // d_mag ∈ (0.0625, 0.5625). d_mag = 0.7 → c = 3.55, p = 1.55: real roots.
        let w_real = [
            encode(0.7),
            encode(0.75),
            encode(0.2), // pole side conjugate (c = 1.55, cos = -... fine)
            encode(0.75),
            encode(0.25),
        ];
        assert_eq!(roots_from_words(w_real), None, "real pair must be refused");
        match geometry_from_words(w_real).zero {
            RootPair::RealPair { root_a, root_b } => {
                // roots of z² + 1.55·z + 0.25 (up to minifloat grid)
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

    // ── deterministic packed-geometry gate ──────────────────────────────────

    fn declared_stage_rows() -> Vec<([u16; 5], String)> {
        // The real fixture is clean-room and local to trench-core. The packed
        // sweep makes coverage independent of whatever old bodies or JSON
        // happen to exist elsewhere in the checkout.
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

    /// DETERMINISTIC GATE over one declared clean-room `.body240` fixture and
    /// 65,536 packed rows sampled across the full u16 word domain:
    ///   · conjugate row → roots → words must be WORD-IDENTICAL
    ///   · real-root row → conjugate reader refuses (exact inspection only)
    ///   · no row is silently approximated
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
                    // refusal path: geometry must classify it as a real pair
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
