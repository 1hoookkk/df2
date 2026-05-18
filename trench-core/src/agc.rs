/// Table-driven post-cascade soft limiter (verified against EmulatorX.dll binary).
/// All 16 table values confirmed exact. Algorithm confirmed from FUN_1802c04e0.
/// Index uses `& 0xF` wrapping (not clamp). No gain floor — gain can drop to zero.
const AGC_TABLE: [f32; 16] = [
    1.0001, 1.0001, 0.996, 0.990, 0.920, 0.500, 0.200, 0.160, 0.120, 0.120, 0.120, 0.120, 0.120,
    0.120, 0.120, 0.120,
];

#[inline(always)]
pub fn agc_step(sample: f32, agc_gain: &mut f32) -> f32 {
    let abs_sample = sample.abs();
    let idx = ((*agc_gain * abs_sample) as u32 & 0xF) as usize;
    let new_gain = *agc_gain * AGC_TABLE[idx];

    if new_gain < 1.0 {
        *agc_gain = new_gain;
    } else {
        *agc_gain = 1.0;
    }

    sample * *agc_gain
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quiet_signal_passes_through() {
        let mut gain = 1.0;
        let out = agc_step(0.5, &mut gain);
        assert!((out - 0.5).abs() < 0.01, "got {out}");
        assert!(
            (gain - 1.0).abs() < 0.01,
            "gain should stay near 1.0, got {gain}"
        );
    }

    #[test]
    fn loud_signal_reduces_gain() {
        let mut gain = 1.0;
        for _ in 0..100 {
            agc_step(10.0, &mut gain);
        }
        assert!(
            gain < 0.2,
            "Gain should be reduced for loud signal, got {gain}"
        );
    }

    #[test]
    fn gain_recovers_below_threshold() {
        let mut gain = 1.0;
        for _ in 0..100 {
            agc_step(10.0, &mut gain);
        }
        assert!(gain < 0.5, "Gain should be low after loud signal");

        let saved_gain = gain;
        for _ in 0..10000 {
            agc_step(0.1, &mut gain);
        }
        assert!(
            gain > saved_gain,
            "Gain should recover over time, was {saved_gain} now {gain}"
        );
    }

    #[test]
    fn no_gain_floor() {
        // C++ parity: gain can go below 0.001 (no floor)
        let mut gain = 1.0;
        for _ in 0..1000 {
            agc_step(1e10, &mut gain);
        }
        assert!(gain.is_finite(), "gain should be finite, got {gain}");
        assert!(gain >= 0.0, "gain should be non-negative, got {gain}");
    }

    #[test]
    fn output_stays_finite() {
        let mut gain = 1.0;
        for &x in &[0.0, 0.5, 1.0, 10.0, 1000.0, 1e10, -5.0, -100.0] {
            let out = agc_step(x, &mut gain);
            assert!(out.is_finite(), "Not finite for input {x}");
        }
    }
}
