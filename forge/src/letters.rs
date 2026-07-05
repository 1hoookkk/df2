//! The letter compiler — Phase 2 of the TRENCH FACTORY.
//!
//! A LETTER is the unit of authoring: a tagged pole/zero/gain compound measured
//! from the ROM 33 (see `desk/letters.json`, `tools/alphabet_trace.py`). This
//! module turns a `StageSpec` (letter + roots + gain) into the 5 packed words
//! the engine runs, going through the ONE encoder the whole forge shares
//! (`crate::biquad_to_words` -> `trench_core::minifloat`).
//!
//! Acceptance gate (the HEDZ EXAM): any ROM body, viewed as StageSpecs and
//! recompiled, must emit byte-identical words. Roots+gain is a LOSSLESS view of
//! a biquad, so the letter coordinate is a faithful substrate for the generator
//! to sample in. Proven for Talking Hedz below (0/120 words differ).

use crate::{biquad_to_words, words_to_biquad, CornerWords, SR};

const TAU: f64 = std::f64::consts::PI * 2.0;

/// The traced alphabet (matches tools/alphabet_trace.py LETTERS).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Letter {
    Foundation,
    Pad,
    RealRoot,
    Reson,
    Canyon,
    Scoop,
    AirCut,
    Crown,
}

impl Letter {
    pub fn tag(self) -> &'static str {
        match self {
            Letter::Foundation => "FOUNDATION",
            Letter::Pad => "PAD",
            Letter::RealRoot => "REALROOT",
            Letter::Reson => "RESON",
            Letter::Canyon => "CANYON",
            Letter::Scoop => "SCOOP",
            Letter::AirCut => "AIRCUT",
            Letter::Crown => "CROWN",
        }
    }
}

/// Minimal complex number — quadratic roots only, no dependency pulled in.
#[derive(Clone, Copy, Debug)]
pub struct Cplx {
    pub re: f64,
    pub im: f64,
}

impl Cplx {
    fn new(re: f64, im: f64) -> Self {
        Cplx { re, im }
    }
    fn add(self, o: Cplx) -> Cplx {
        Cplx::new(self.re + o.re, self.im + o.im)
    }
    fn mul(self, o: Cplx) -> Cplx {
        Cplx::new(self.re * o.re - self.im * o.im, self.re * o.im + self.im * o.re)
    }
    pub fn mag(self) -> f64 {
        (self.re * self.re + self.im * self.im).sqrt()
    }
    pub fn hz(self, sr: f64) -> f64 {
        self.im.atan2(self.re).abs() / TAU * sr
    }
    pub fn is_real(self) -> bool {
        self.im.abs() < 1e-9
    }
}

/// Roots of `a x^2 + b x + c` (np.roots convention: leading coeff first).
/// Returns 0, 1, or 2 roots depending on degree.
fn quad_roots(a: f64, b: f64, c: f64) -> Vec<Cplx> {
    if a.abs() < 1e-18 {
        if b.abs() < 1e-18 {
            return vec![];
        }
        return vec![Cplx::new(-c / b, 0.0)];
    }
    let disc = b * b - 4.0 * a * c;
    if disc >= 0.0 {
        let s = disc.sqrt();
        vec![Cplx::new((-b + s) / (2.0 * a), 0.0), Cplx::new((-b - s) / (2.0 * a), 0.0)]
    } else {
        let s = (-disc).sqrt();
        vec![Cplx::new(-b / (2.0 * a), s / (2.0 * a)), Cplx::new(-b / (2.0 * a), -s / (2.0 * a))]
    }
}

/// (sum, product) of a root list, real parts. For a conjugate pair the imag
/// parts cancel; for two reals it is exact; for <2 roots the missing terms 0.
fn sum_prod(roots: &[Cplx]) -> (f64, f64) {
    match roots.len() {
        2 => (roots[0].add(roots[1]).re, roots[0].mul(roots[1]).re),
        1 => (roots[0].re, 0.0),
        _ => (0.0, 0.0),
    }
}

/// One stage as a letter: the tag, its poles/zeros (as roots), and the gain b0.
#[derive(Clone, Debug)]
pub struct StageSpec {
    pub letter: Letter,
    pub gain: f64,
    pub zeros: Vec<Cplx>,
    pub poles: Vec<Cplx>,
}

impl StageSpec {
    /// LOSSLESS view of a biquad `[b0,b1,b2,a1,a2]` as roots + gain.
    /// When b0 == 0 the numerator is entirely zero (b1=b2=0 follow from the
    /// kernel), so there are no zeros.
    pub fn from_biquad(letter: Letter, b: [f64; 5]) -> Self {
        let [b0, b1, b2, a1, a2] = b;
        let poles = quad_roots(1.0, a1, a2);
        let zeros = if b0.abs() > 1e-18 { quad_roots(b0, b1, b2) } else { vec![] };
        StageSpec { letter, gain: b0, zeros, poles }
    }

    /// Rebuild the biquad from roots + gain. Inverse of `from_biquad`.
    pub fn to_biquad(&self) -> [f64; 5] {
        let (zs, zp) = sum_prod(&self.zeros);
        let (ps, pp) = sum_prod(&self.poles);
        [self.gain, self.gain * -zs, self.gain * zp, -ps, pp]
    }

    /// Compile to the 5 packed words through the shared encoder.
    pub fn compile(&self) -> [u16; 5] {
        biquad_to_words(self.to_biquad())
    }

    fn conj_pole_hz(&self) -> Option<f64> {
        self.poles.iter().find(|p| !p.is_real()).map(|p| p.hz(SR))
    }
    fn conj_zero(&self) -> Option<Cplx> {
        self.zeros.iter().find(|z| !z.is_real()).copied()
    }
}

/// A conjugate root pair at (freq Hz, radius r).
fn conj(f: f64, r: f64) -> Vec<Cplx> {
    let w = TAU * f / SR;
    vec![Cplx::new(r * w.cos(), r * w.sin()), Cplx::new(r * w.cos(), -r * w.sin())]
}

/// A deterministic example stage per letter — used by the signature tests and
/// as living documentation of each letterform.
pub fn example(letter: Letter) -> StageSpec {
    let (pole_f, pole_r) = (1000.0, 0.98);
    let poles = conj(pole_f, pole_r);
    let (zeros, gain): (Vec<Cplx>, f64) = match letter {
        Letter::Foundation => (conj(8000.0, 1.0), 0.5),
        Letter::Reson | Letter::Pad => (vec![], 1.0 - pole_r * pole_r),
        Letter::Canyon => (conj(pole_f * 0.9, 0.95), 1.0),
        Letter::Scoop => (conj(pole_f * 0.4, 0.9), 1.0),
        Letter::AirCut => (conj(pole_f * 2.5, 0.9), 1.0),
        Letter::Crown => (conj(pole_f * 1.1, 0.6), 1.0),
        Letter::RealRoot => (vec![Cplx::new(0.6, 0.0), Cplx::new(-0.3, 0.0)], 1.0),
    };
    StageSpec { letter, gain, zeros, poles }
}

/// Recompile every stage of a packed body through the letter path.
/// The identity map at the letter level — the fidelity guarantee.
pub fn recompile_body(cw: &CornerWords) -> CornerWords {
    let mut out = *cw;
    for c in 0..4 {
        for s in 0..6 {
            let bq = words_to_biquad(cw[c][s]);
            out[c][s] = StageSpec::from_biquad(Letter::Foundation, bq).compile();
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{words_from_body_bytes, words_to_body_bytes};

    const HEDZ: &str = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../ref/p2k_variants/P2k_013_talking_hedz/variant_0_dat_052.bin"
    );

    // THE HEDZ EXAM — the Phase 2 acceptance gate. Talking Hedz, viewed as
    // letters and recompiled through the rust path, must emit byte-identical
    // words. Feasibility was proven in python (0/120); this is the rust proof.
    #[test]
    fn hedz_recreates_byte_identical() {
        let bytes = std::fs::read(HEDZ).expect("Hedz ROM body present");
        assert_eq!(bytes.len(), 240);
        let cw = words_from_body_bytes(&bytes).expect("240 bytes parse");
        let rebuilt = recompile_body(&cw);
        let out = words_to_body_bytes(&rebuilt);
        let diffs = out.iter().zip(&bytes).filter(|(a, b)| a != b).count();
        assert_eq!(diffs, 0, "{diffs} bytes differ; letter path is not lossless on Hedz");
    }

    #[test]
    fn every_musical_body_recompiles_identical() {
        // the guarantee is general, not Hedz-luck: sweep the MUSICAL 33
        // (P2k_000..032). The utility set (033-049: plain LPF/HPF/EQ/phase)
        // uses degenerate all-pole stages outside the iconic letter grammar
        // and is not what the factory authors — out of scope by design.
        let root = concat!(env!("CARGO_MANIFEST_DIR"), "/../ref/p2k_variants");
        let mut checked = 0;
        for entry in std::fs::read_dir(root).expect("variants dir").flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            let num: Option<u32> = name.strip_prefix("P2k_").and_then(|s| s.get(0..3)).and_then(|s| s.parse().ok());
            if !matches!(num, Some(n) if n <= 32) {
                continue;
            }
            let bins: Vec<_> = std::fs::read_dir(entry.path())
                .map(|rd| rd.flatten().map(|e| e.path())
                    .filter(|p| p.extension().and_then(|s| s.to_str()) == Some("bin"))
                    .collect())
                .unwrap_or_default();
            let Some(bin) = bins.into_iter().find(|p| p.file_name()
                .and_then(|s| s.to_str()).map_or(false, |s| s.starts_with("variant_0_"))) else { continue };
            let bytes = std::fs::read(&bin).unwrap();
            if bytes.len() != 240 {
                continue;
            }
            let cw = words_from_body_bytes(&bytes).unwrap();
            let out = words_to_body_bytes(&recompile_body(&cw));
            assert_eq!(out, bytes, "{name} not byte-identical through the letter path");
            checked += 1;
        }
        assert!(checked >= 33, "expected >=33 bodies, checked {checked}");
    }

    #[test]
    fn foundation_compiles_to_exact_unit_zero() {
        let b = words_to_biquad(example(Letter::Foundation).compile());
        assert!(b[0] != 0.0);
        assert_eq!(b[2], b[0], "foundation zero must be r=1.0 exactly (b2==b0)");
    }

    #[test]
    fn canyon_zero_sits_below_pole() {
        let spec = StageSpec::from_biquad(Letter::Canyon, words_to_biquad(example(Letter::Canyon).compile()));
        let pf = spec.conj_pole_hz().expect("canyon has a pole");
        let zf = spec.conj_zero().expect("canyon has a zero").hz(SR);
        assert!(zf < pf, "canyon zero {zf:.0} Hz should sit below pole {pf:.0} Hz");
    }

    #[test]
    fn aircut_zero_sits_above_pole() {
        let spec = StageSpec::from_biquad(Letter::AirCut, words_to_biquad(example(Letter::AirCut).compile()));
        let pf = spec.conj_pole_hz().expect("aircut has a pole");
        let zf = spec.conj_zero().expect("aircut has a zero").hz(SR);
        assert!(zf > pf, "aircut zero {zf:.0} Hz should sit above pole {pf:.0} Hz");
    }

    #[test]
    fn reson_compiles_to_bare_resonator() {
        let b = words_to_biquad(example(Letter::Reson).compile());
        assert!(b[1].abs() < 1e-6 && b[2].abs() < 1e-6, "reson numerator should be bare: {b:?}");
    }
}
