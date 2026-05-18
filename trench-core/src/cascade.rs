use crate::cartridge::CornerData;

pub const NUM_STAGES: usize = 6;
pub const NUM_COEFFS: usize = 5;
pub const PASSTHROUGH_COEFFS: [f64; NUM_COEFFS] = [1.0, 0.0, 0.0, 0.0, 0.0];

#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
#[derive(Debug, Clone, Copy, Default)]
pub struct EncodedCoeffs {
    pub c0: f64,
    pub c1: f64,
    pub c2: f64,
    pub c3: f64,
    pub c4: f64,
}

/// Total stages in the cascade: 6 active + 6 passthrough.
pub const TOTAL_STAGES: usize = 12;
/// Control block size in samples.
pub const BLOCK_SIZE: usize = 32;

/// Per-stage DF2T biquad state.
#[derive(Clone)]
struct BiquadState {
    /// Current coefficients [c0, c1, c2, c3, c4].
    coeffs: [f64; NUM_COEFFS],
    /// Ramp deltas per sample.
    deltas: [f64; NUM_COEFFS],
    /// DF2T delay elements.
    w1: f64,
    w2: f64,
}

impl BiquadState {
    fn new() -> Self {
        Self {
            coeffs: PASSTHROUGH_COEFFS,
            deltas: [0.0; NUM_COEFFS],
            w1: 0.0,
            w2: 0.0,
        }
    }

    /// Set target coefficients and compute per-sample ramp deltas.
    fn set_target(&mut self, target: &[f64; NUM_COEFFS], ramp_samples: usize) {
        let ramp_samples = ramp_samples.max(1) as f64;
        for (i, &t) in target.iter().enumerate() {
            self.deltas[i] = (t - self.coeffs[i]) / ramp_samples;
        }
    }

    /// Process one sample through this DF2T stage.
    /// Ramps coefficients, then computes output.
    #[inline(always)]
    fn process_sample(&mut self, x: f64) -> (f64, bool) {
        // Ramp coefficients
        self.coeffs[0] += self.deltas[0];
        self.coeffs[1] += self.deltas[1];
        self.coeffs[2] += self.deltas[2];
        self.coeffs[3] += self.deltas[3];
        self.coeffs[4] += self.deltas[4];

        // DF2T execution (exact spec math)
        let mut y = self.coeffs[0] * x + self.w1;
        // Flush non-finite state before feedback to prevent death spiral.
        if !y.is_finite() {
            y = 0.0;
            self.w1 = 0.0;
            self.w2 = 0.0;
            self.deltas = [0.0; NUM_COEFFS];
            return (y, true);
        }
        self.w1 = self.coeffs[1] * x - self.coeffs[3] * y + self.w2;
        self.w2 = self.coeffs[2] * x - self.coeffs[4] * y;
        let unstable = !self.w1.is_finite() || !self.w2.is_finite();
        if unstable {
            self.w1 = 0.0;
            self.w2 = 0.0;
            self.deltas = [0.0; NUM_COEFFS];
        }
        (y, unstable)
    }
}

/// The 12-stage serial DF2T cascade.
/// 6 active stages (interpolated from cartridge) + 6 passthrough stages.
pub struct Cascade {
    stages: [BiquadState; TOTAL_STAGES],
    /// Current post-cascade boost (linear gain), ramped per sample.
    boost: f64,
    /// Per-sample ramp delta for boost.
    boost_delta: f64,
    /// Latched when stage math or boost becomes non-finite.
    instability_detected: bool,
}

impl Cascade {
    pub fn new() -> Self {
        Self {
            stages: std::array::from_fn(|_| BiquadState::new()),
            boost: 1.0,
            boost_delta: 0.0,
            instability_detected: false,
        }
    }

    /// Reset all delay state (call on transport reset / parameter jump).
    pub fn reset(&mut self) {
        for stage in &mut self.stages {
            stage.w1 = 0.0;
            stage.w2 = 0.0;
            stage.deltas = [0.0; NUM_COEFFS];
        }
        self.boost_delta = 0.0;
        self.instability_detected = false;
    }

    /// Set target post-cascade boost (linear gain) and compute per-sample ramp delta.
    pub fn set_boost(&mut self, target: f64, ramp_samples: usize) {
        let ramp_samples = ramp_samples.max(1) as f64;
        self.boost_delta = (target - self.boost) / ramp_samples;
    }

    /// Set target coefficients for the 6 active stages from interpolated cartridge data.
    /// Passthrough stages (6..12) remain identity.
    pub fn set_targets(&mut self, interpolated: &CornerData, ramp_samples: usize) {
        for (stage, coeffs) in self.stages[..NUM_STAGES]
            .iter_mut()
            .zip(interpolated.iter())
        {
            stage.set_target(coeffs, ramp_samples);
        }
        // Passthrough stages always target identity
        for i in NUM_STAGES..TOTAL_STAGES {
            self.stages[i].set_target(&PASSTHROUGH_COEFFS, ramp_samples);
        }
    }

    /// Process a single f32 sample through all 12 stages in series.
    /// Ramps coefficients and boost per-sample internally.
    #[inline(always)]
    pub fn tick(&mut self, x: f32) -> f32 {
        let mut v = x as f64;
        for stage in &mut self.stages {
            let (next, unstable) = stage.process_sample(v);
            if unstable {
                self.instability_detected = true;
                return 0.0;
            }
            v = next;
        }
        self.boost += self.boost_delta;
        if !self.boost.is_finite() {
            self.boost = 1.0;
            self.boost_delta = 0.0;
            self.instability_detected = true;
            return 0.0;
        }
        v *= self.boost;
        if !v.is_finite() {
            self.instability_detected = true;
            return 0.0;
        }
        v as f32
    }

    /// Process a mono slice of samples. Ramps coefficients per-sample.
    /// Call `set_targets()` before each 32-sample block.
    pub fn process_block_mono(&mut self, samples: &mut [f32]) {
        for sample in samples.iter_mut() {
            *sample = self.tick(*sample);
        }
    }

    /// Returns whether this cascade encountered a non-finite runtime condition since the last call.
    pub fn take_instability_flag(&mut self) -> bool {
        let instability_detected = self.instability_detected;
        self.instability_detected = false;
        instability_detected
    }

    /// Retrieve the current ramped coefficients for the active stages (for UI visualization).
    pub fn get_coeffs(&self, out: &mut [[f64; NUM_COEFFS]; NUM_STAGES]) {
        for (i, stage) in self.stages[..NUM_STAGES].iter().enumerate() {
            out[i] = stage.coeffs;
        }
    }
}

impl Default for Cascade {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn passthrough_is_identity() {
        let mut cascade = Cascade::new();
        // All stages are passthrough by default
        let mut buf = [1.0f32, 0.5, -0.3, 0.0];
        let expected = buf;
        cascade.process_block_mono(&mut buf);
        for (i, (&got, &exp)) in buf.iter().zip(expected.iter()).enumerate() {
            assert!(
                (got - exp).abs() < 1e-6,
                "sample {i}: expected {exp}, got {got}"
            );
        }
    }

    #[test]
    fn reset_clears_state() {
        let mut cascade = Cascade::new();
        // Push some signal through
        let mut buf = [1.0f32; 64];
        cascade.process_block_mono(&mut buf);
        cascade.reset();
        // After reset, delay lines should be zero
        let mut silence = [0.0f32; 32];
        cascade.process_block_mono(&mut silence);
        for &s in &silence {
            assert!(s.abs() < 1e-10, "expected silence after reset, got {s}");
        }
    }

    #[test]
    fn set_target_reaches_destination_for_short_blocks() {
        let mut stage = BiquadState::new();
        let target = [2.0, 0.0, 0.0, 0.0, 0.0];

        stage.set_target(&target, 8);
        for _ in 0..8 {
            let _ = stage.process_sample(0.0);
        }

        assert!((stage.coeffs[0] - 2.0).abs() < 1e-12);
    }

    #[test]
    fn reset_clears_ramp_state() {
        let mut cascade = Cascade::new();
        let target = [[2.0, 0.0, 0.0, 0.0, 0.0]; NUM_STAGES];

        cascade.set_targets(&target, BLOCK_SIZE);
        cascade.set_boost(2.0, BLOCK_SIZE);
        cascade.reset();

        for stage in &cascade.stages {
            assert_eq!(stage.deltas, [0.0; NUM_COEFFS]);
        }
        assert_eq!(cascade.boost_delta, 0.0);
    }

    #[test]
    fn non_finite_stage_sets_instability_flag() {
        let mut cascade = Cascade::new();
        cascade.stages[0].coeffs[0] = f64::NAN;

        let output = cascade.tick(1.0);

        assert_eq!(output, 0.0);
        assert!(cascade.take_instability_flag());
        assert!(!cascade.take_instability_flag());
    }
}
