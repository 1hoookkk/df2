//! E-mu raw stage projection for the current Domain 1 DF2T cascade.
//! Bypasses stage_math.rs and RBJ cookbook entirely.

use crate::cascade::EncodedCoeffs;

pub struct EmuResonatorParams {
    pub freq_hz: f32,
    pub radius: f32,
    pub val1: f32,
    pub val2: f32,
    pub val3: f32,
}

/// Compute DF2T coefficients from E-mu raw stage parameters.
pub fn emu_resonator(params: &EmuResonatorParams, sample_rate: f64) -> EncodedCoeffs {
    let freq = params.freq_hz as f64;
    let r = params.radius as f64;
    let v1 = params.val1 as f64;
    let v2 = params.val2 as f64;
    let v3 = params.val3 as f64;

    // Pole angle
    let theta = 2.0 * std::f64::consts::PI * freq / sample_rate;

    // Denominator (standard resonator poles)
    let a1 = -2.0 * r * theta.cos();
    let a2 = r * r;

    // Numerator (E-mu zero-placement projection).
    let b0 = 1.0 + v1;
    let b1 = a1 + v2;
    let b2 = a2 - v3;

    EncodedCoeffs {
        c0: b0,
        c1: b1,
        c2: b2,
        c3: a1,
        c4: a2,
    }
}

/// Compute freq from a1 and r (inverse of the standard project)
pub fn freq_from_a1_r(a1: f64, r: f64, sample_rate: f64) -> f64 {
    let arg = -a1 / (2.0 * r);
    let theta = if arg.abs() <= 1.0 { arg.acos() } else { 0.0 };
    theta * sample_rate / (2.0 * std::f64::consts::PI)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn raw_stage_projects_to_df2t_row() {
        let params = EmuResonatorParams {
            freq_hz: 246.0,
            radius: 0.9,
            val1: -0.25,
            val2: 0.5,
            val3: 0.125,
        };

        let enc = emu_resonator(&params, 39062.5);
        let theta = 2.0 * std::f64::consts::PI * 246.0 / 39062.5;
        let a1 = -2.0 * 0.9 * theta.cos();
        let a2 = 0.9 * 0.9;

        assert!((enc.c0 - 0.75).abs() < 1.0e-6);
        assert!((enc.c1 - (a1 + 0.5)).abs() < 1.0e-6);
        assert!((enc.c2 - (a2 - 0.125)).abs() < 1.0e-6);
        assert!((enc.c3 - a1).abs() < 1.0e-6);
        assert!((enc.c4 - a2).abs() < 1.0e-6);
    }
}
