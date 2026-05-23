//! Source preprocessing — vintage-sampler degradation applied to a dropped sound
//! BEFORE the filter is modelled from it, so the cartridge inherits the sampler's
//! character. Two independent stages: bit reduction and sample-rate reduction.
//!
//! The anti-alias filter (AAF) toggle is the whole point:
//!   - AAF OFF: decimation folds high frequencies back into the band — the
//!     inharmonic "harmonic enhancement" brightness producers chase (and a way to
//!     manufacture a bright, clustered character to capture).
//!   - AAF ON: band-limit before decimating — clean reduction, no fold-back, a
//!     darker but truthful spectrum.
//!
//! This supersedes the old `zero_dither_truncation` stub (a fixed 16-bit
//! truncation). Pure std; deterministic dither so a given source fits identically.

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SamplerPre {
    /// Quantiser word length. 16+ effectively bypasses bit reduction.
    pub bits: u8,
    /// TPDF dither before quantising (decorrelates the truncation distortion).
    pub dither: bool,
    /// Reduce to this rate then reconstruct back to the host rate (baking in the
    /// artifacts). `None` = no rate reduction.
    pub target_sr: Option<f64>,
    /// Band-limit before decimating. Off = aliasing/fold-back character.
    pub aaf: bool,
}

impl SamplerPre {
    pub const CLEAN: SamplerPre = SamplerPre {
        bits: 24,
        dither: false,
        target_sr: None,
        aaf: true,
    };

    pub fn is_clean(&self) -> bool {
        self.bits >= 16 && self.target_sr.is_none()
    }
}

/// Era-approximate engineering defaults — tune against references before
/// treating any number as a character claim. Rates/bit-depths are the headline
/// figures each machine is known for; the musical signature is the bit depth +
/// rate + whether the converters band-limited the input.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum VintagePreset {
    None,
    Sp1200,    // 12-bit, ~26.04 kHz, no input AAF — gritty, aliased
    Mpc60,     // 12-bit, ~40 kHz, filtered — punchy but smoother (Linn filters)
    AkaiS900,  // 12-bit, ~40 kHz, filtered
    Fairlight, // 8-bit, ~24 kHz, no AAF — lo-fi, aliased
    Mirage,    // 8-bit, ~32 kHz, minimal AAF — gritty
}

impl VintagePreset {
    pub const ALL: [VintagePreset; 6] = [
        VintagePreset::None,
        VintagePreset::Sp1200,
        VintagePreset::Mpc60,
        VintagePreset::AkaiS900,
        VintagePreset::Fairlight,
        VintagePreset::Mirage,
    ];

    pub fn label(&self) -> &'static str {
        match self {
            VintagePreset::None => "CLEAN",
            VintagePreset::Sp1200 => "SP-1200",
            VintagePreset::Mpc60 => "MPC60",
            VintagePreset::AkaiS900 => "S900",
            VintagePreset::Fairlight => "FAIRLIGHT",
            VintagePreset::Mirage => "MIRAGE",
        }
    }

    pub fn settings(&self) -> SamplerPre {
        match self {
            VintagePreset::None => SamplerPre::CLEAN,
            VintagePreset::Sp1200 => SamplerPre {
                bits: 12,
                dither: false,
                target_sr: Some(26_040.0),
                aaf: false,
            },
            VintagePreset::Mpc60 => SamplerPre {
                bits: 12,
                dither: false,
                target_sr: Some(40_000.0),
                aaf: true,
            },
            VintagePreset::AkaiS900 => SamplerPre {
                bits: 12,
                dither: false,
                target_sr: Some(40_000.0),
                aaf: true,
            },
            VintagePreset::Fairlight => SamplerPre {
                bits: 8,
                dither: false,
                target_sr: Some(24_000.0),
                aaf: false,
            },
            VintagePreset::Mirage => SamplerPre {
                bits: 8,
                dither: false,
                target_sr: Some(32_000.0),
                aaf: false,
            },
        }
    }
}

/// Apply the full preprocessing chain at the source's own rate, returning a new
/// buffer the same length/rate (artifacts baked in). Rate reduction first
/// (band-limit + fold-back happen in the analog/converter domain), then the
/// quantiser.
pub fn apply(x: &[f64], sr_in: f64, pre: &SamplerPre) -> Vec<f64> {
    if pre.is_clean() {
        return x.to_vec();
    }
    let mut y = match pre.target_sr {
        Some(t) if t > 0.0 && t < sr_in => reduce_rate(x, sr_in, t, pre.aaf),
        _ => x.to_vec(),
    };
    if pre.bits < 16 {
        quantize_bits(&mut y, pre.bits, pre.dither);
    }
    y
}

/// Quantise to `bits` (mid-tread), optional TPDF dither of 1 LSB. Deterministic.
pub fn quantize_bits(x: &mut [f64], bits: u8, dither: bool) {
    let levels = (1u32 << (bits.clamp(2, 24) - 1)) as f64; // peak = ±levels
    let step = 1.0 / levels;
    let mut rng = 0x9E37_79B9_7F4A_7C15u64;
    let mut tpdf = || {
        // two independent uniforms -> triangular, scaled to ±1 LSB
        rng = rng
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        let a = (rng >> 40) as f64 / (1u64 << 24) as f64;
        rng = rng
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        let b = (rng >> 40) as f64 / (1u64 << 24) as f64;
        (a - b) * step
    };
    for v in x.iter_mut() {
        let d = if dither { tpdf() } else { 0.0 };
        *v = ((*v + d) * levels).round() / levels;
    }
}

/// Reduce to `target_sr` then reconstruct to `sr_in` via zero-order hold (the
/// vintage sample-and-hold converter). With `aaf`, band-limit to target Nyquist
/// first so nothing folds back; without it, the decimation aliases — the gritty
/// brightness. Output keeps the input length/rate.
pub fn reduce_rate(x: &[f64], sr_in: f64, target_sr: f64, aaf: bool) -> Vec<f64> {
    let src = if aaf {
        let mut t = x.to_vec();
        butterworth_lowpass(&mut t, sr_in, target_sr * 0.5);
        t
    } else {
        x.to_vec()
    };
    let ratio = sr_in / target_sr; // host samples per reduced sample (>1)
    let mut out = vec![0.0; src.len()];
    let mut held = 0.0;
    let mut next = 0.0;
    for (i, o) in out.iter_mut().enumerate() {
        if (i as f64) >= next {
            held = src[i]; // latch a new reduced-rate sample
            next += ratio;
        }
        *o = held; // zero-order hold reconstruction (imaging artifacts intact)
    }
    out
}

/// Two cascaded one-pole low-passes (~12 dB/oct) — gentle anti-alias, in the
/// spirit of the cheap converters these machines used, not a brickwall.
fn butterworth_lowpass(x: &mut [f64], sr: f64, cutoff: f64) {
    let fc = cutoff.clamp(100.0, sr * 0.49);
    let dt = 1.0 / sr;
    let rc = 1.0 / (2.0 * std::f64::consts::PI * fc);
    let alpha = dt / (rc + dt);
    for _ in 0..2 {
        let mut y = 0.0;
        for v in x.iter_mut() {
            y += alpha * (*v - y);
            *v = y;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clean_is_identity() {
        let x: Vec<f64> = (0..1000).map(|i| (i as f64 * 0.1).sin()).collect();
        assert_eq!(apply(&x, 44_100.0, &SamplerPre::CLEAN), x);
    }

    #[test]
    fn bit_reduction_quantises() {
        let mut x = vec![0.123_456_789, -0.5, 0.999];
        quantize_bits(&mut x, 8, false);
        let step = 1.0 / 128.0;
        for v in &x {
            let n = v / step;
            assert!((n - n.round()).abs() < 1e-9, "not on an 8-bit grid: {v}");
        }
    }

    #[test]
    fn rate_reduction_holds_samples() {
        // 2:1 zero-order hold (no AAF) repeats every other sample.
        let x: Vec<f64> = (0..8).map(|i| i as f64).collect();
        let y = reduce_rate(&x, 44_100.0, 22_050.0, false);
        assert_eq!(y.len(), x.len());
        // held in pairs: y[1]==y[0], y[3]==y[2], ...
        assert_eq!(y[0], y[1]);
        assert_eq!(y[2], y[3]);
    }
}
