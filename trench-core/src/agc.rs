use crate::dsp::BASE_AGC_TABLE;

/// Build the per-instance AGC table using the sample-rate law from
/// `FUN_1802bfa10`.
pub fn active_agc_table(sample_rate: f64) -> [f32; 16] {
    let sqrt_count = if sample_rate > 130_000.0 {
        2
    } else if sample_rate > 65_000.0 {
        1
    } else {
        0
    };

    BASE_AGC_TABLE.map(|mut value| {
        for _ in 0..sqrt_count {
            value = value.sqrt();
        }
        value
    })
}

/// Table-driven post-cascade soft limiter (verified against EmulatorX.dll binary).
/// All 16 table values confirmed exact. Algorithm confirmed from FUN_1802c04e0.
/// Index uses `& 0xF` wrapping (not clamp). No gain floor — gain can drop to zero.
#[inline(always)]
pub fn agc_step(sample: f32, agc_gain: &mut f32, agc_table: &[f32; 16]) -> f32 {
    update_gain(sample.abs(), agc_gain, agc_table);
    sample * *agc_gain
}

/// Linked-stereo AGC path from `FUN_1802c04e0`.
///
/// The DLL measures the louder channel, updates one gain state, then applies
/// that shared multiplier to both channels.
#[inline(always)]
pub fn agc_step_stereo(
    left: f32,
    right: f32,
    agc_gain: &mut f32,
    agc_table: &[f32; 16],
) -> (f32, f32) {
    update_gain(left.abs().max(right.abs()), agc_gain, agc_table);
    (left * *agc_gain, right * *agc_gain)
}

#[inline(always)]
fn update_gain(magnitude: f32, agc_gain: &mut f32, agc_table: &[f32; 16]) {
    let idx = ((*agc_gain * magnitude) as u32 & 0xF) as usize;
    let new_gain = *agc_gain * agc_table[idx];

    if new_gain < 1.0 {
        *agc_gain = new_gain;
    } else {
        *agc_gain = 1.0;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn assert_tables_close(actual: &[f32; 16], expected: &[f32; 16]) {
        for (index, (actual, expected)) in actual.iter().zip(expected).enumerate() {
            assert!(
                (actual - expected).abs() < 1e-7,
                "table[{index}] expected {expected}, got {actual}"
            );
        }
    }

    #[test]
    fn active_table_uses_verified_sample_rate_bands() {
        assert_eq!(active_agc_table(65_000.0), BASE_AGC_TABLE);

        let sqrt_table = BASE_AGC_TABLE.map(f32::sqrt);
        assert_tables_close(&active_agc_table(65_000.1), &sqrt_table);
        assert_tables_close(&active_agc_table(130_000.0), &sqrt_table);

        let fourth_root_table = sqrt_table.map(f32::sqrt);
        assert_tables_close(&active_agc_table(130_000.1), &fourth_root_table);
    }

    #[test]
    fn quiet_signal_passes_through() {
        let mut gain = 1.0;
        let out = agc_step(0.5, &mut gain, &BASE_AGC_TABLE);
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
            agc_step(10.0, &mut gain, &BASE_AGC_TABLE);
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
            agc_step(10.0, &mut gain, &BASE_AGC_TABLE);
        }
        assert!(gain < 0.5, "Gain should be low after loud signal");

        let saved_gain = gain;
        for _ in 0..10000 {
            agc_step(0.1, &mut gain, &BASE_AGC_TABLE);
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
            agc_step(1e10, &mut gain, &BASE_AGC_TABLE);
        }
        assert!(gain.is_finite(), "gain should be finite, got {gain}");
        assert!(gain >= 0.0, "gain should be non-negative, got {gain}");
    }

    #[test]
    fn output_stays_finite() {
        let mut gain = 1.0;
        for &x in &[0.0, 0.5, 1.0, 10.0, 1000.0, 1e10, -5.0, -100.0] {
            let out = agc_step(x, &mut gain, &BASE_AGC_TABLE);
            assert!(out.is_finite(), "Not finite for input {x}");
        }
    }

    #[test]
    fn stereo_uses_louder_channel_and_shared_gain() {
        let mut gain = 1.0;
        let (left, right) = agc_step_stereo(0.25, 10.0, &mut gain, &BASE_AGC_TABLE);
        let expected_gain = BASE_AGC_TABLE[10];
        assert_eq!(gain, expected_gain);
        assert_eq!(left, 0.25 * expected_gain);
        assert_eq!(right, 10.0 * expected_gain);
    }
}
