use crate::cartridge::CornerData;
pub const NUM_STAGES: usize = 6;
pub const NUM_COEFFS: usize = 5;
pub const PASSTHROUGH_COEFFS: [f64; NUM_COEFFS] = [1.0, 0.0, 0.0, 0.0, 0.0];
pub const BLOCK_SIZE: usize = 32;
/// Full-scale reference for pole-radius distortion (patent's |V_p|).
const V_PEAK: f64 = 1.0;
const CHEW_THRESHOLD_OFF: f64 = 1.5;
const CHEW_THRESHOLD_FULL: f64 = 0.02;

#[inline(always)]
fn chew_threshold(amount: f64) -> f64 {
    // Keep the detector entering the measured section-level range early enough
    // to expose several stages across the knob. Smoothness is owned separately
    // by chew_push_strength, so threshold crossings no longer receive the full
    // pole movement at once.
    let amount = amount.clamp(0.0, 1.0);
    (CHEW_THRESHOLD_OFF - CHEW_THRESHOLD_FULL) * (-8.0 * amount).exp() + CHEW_THRESHOLD_FULL
}

#[inline(always)]
fn chew_push_strength(amount: f64) -> f64 {
    // Crossing a threshold must not immediately receive the full patent push.
    // Square law retains the authentic full pole-radius movement at CHEW 100%
    // while keeping the feedback build in the middle of the knob controllable.
    let amount = amount.clamp(0.0, 1.0);
    amount * amount
}
#[derive(Clone)]
struct BiquadState {
    coeffs: [f64; NUM_COEFFS],
    deltas: [f64; NUM_COEFFS],
    w1: f64,
    w2: f64,
    /// Previous real output of this section. The pole-radius distortion detector
    /// reads the n-1 sample of the section it controls (US 10,514,883).
    y_prev: f64,
}
impl BiquadState {
    fn new() -> Self {
        Self {
            coeffs: PASSTHROUGH_COEFFS,
            deltas: [0.0; NUM_COEFFS],
            w1: 0.0,
            w2: 0.0,
            y_prev: 0.0,
        }
    }
    fn set_target(&mut self, target: &[f64; NUM_COEFFS], ramp_samples: usize) {
        let ramp_samples = ramp_samples.max(1) as f64;
        for (i, &t) in target.iter().enumerate() {
            self.deltas[i] = (t - self.coeffs[i]) / ramp_samples;
        }
    }
    /// E-MU dynamic pole-radius distortion (US 10,514,883), applied PER SECTION.
    ///
    /// When this section's previous real output exceeds the threshold, its pole is
    /// pushed toward the unit circle:
    ///     R_new = R + R(1-R) * (|Vg| - Vt) / |Vp|
    /// The (1-R) term is an asymptotic brake - as R approaches 1 the increase chokes
    /// to zero, so the filter is unconditionally stable and can never reach radius 1.
    ///
    /// This is NOT interstage clipping. E-MU deliberately used a 67-bit accumulator so
    /// spikes pass BETWEEN sections unclipped; the nonlinearity lives in the pole math.
    /// Because the radius moves, the resonant frequency and Q move with it - the peak
    /// blooms and wanders rather than merely getting dirty. A saturator cannot do that.
    #[inline(always)]
    fn process_sample_pole_distort(&mut self, x: f64, vt: f64, push_strength: f64) -> (f64, bool) {
        self.coeffs[0] += self.deltas[0];
        self.coeffs[1] += self.deltas[1];
        self.coeffs[2] += self.deltas[2];
        self.coeffs[3] += self.deltas[3];
        self.coeffs[4] += self.deltas[4];

        let (mut a1, mut a2) = (self.coeffs[3], self.coeffs[4]);
        let (b0, b1, b2) = (self.coeffs[0], self.coeffs[1], self.coeffs[2]);
        let vg = self.y_prev.abs();
        if vg > vt && a2 > 1.0e-9 {
            let r = a2.sqrt();
            if r > 1.0e-6 && r < 1.0 {
                let cos_theta = -a1 / (2.0 * r);
                if cos_theta.abs() <= 1.0 {
                    // |Vp| is a FULL-SCALE PEAK REFERENCE, not the pole's own level.
                    // The push scales with how far over threshold the section is; the
                    // (1-R) brake guarantees it can never reach radius 1.
                    // The patent's full-scale reference defines the useful
                    // detector span. Let small excursions remain linear, but
                    // compress overdrive smoothly instead of allowing a 4x
                    // feedback shove that makes the cascade tip as a switch.
                    let over = ((vg - vt) / V_PEAK).max(0.0);
                    let ratio = over.tanh() * push_strength;
                    let r_new = (r + r * (1.0 - r) * ratio).clamp(0.0, 0.999_9);
                    a1 = -2.0 * r_new * cos_theta;
                    a2 = r_new * r_new;
                }
            }
        }
        // NOT IMPLEMENTED, deliberately: DC gain stabilisation and zero-side
        // distortion. Both are in the patent, both were tried 2026-07-26, and
        // together they turned CHEW into a volume effect (+114% RMS at 22%,
        // saturating by 10%). The zero direction is unspecified in the patent and
        // shrinking the zero radius removes notches and dumps energy back in.
        // Revisit ONE at a time, with the offline sweep, against a heard reference.

        let mut y = b0 * x + self.w1;
        if !y.is_finite() {
            y = 0.0;
            self.w1 = 0.0;
            self.w2 = 0.0;
            self.y_prev = 0.0;
            self.deltas = [0.0; NUM_COEFFS];
            return (y, true);
        }
        self.w1 = b1 * x - a1 * y + self.w2;
        self.w2 = b2 * x - a2 * y;
        let unstable = !self.w1.is_finite() || !self.w2.is_finite();
        if unstable {
            self.w1 = 0.0;
            self.w2 = 0.0;
            self.y_prev = 0.0;
            self.deltas = [0.0; NUM_COEFFS];
        } else {
            self.y_prev = y;
        }
        (y, unstable)
    }
    #[inline(always)]
    fn process_sample(&mut self, x: f64) -> (f64, bool) {
        self.coeffs[0] += self.deltas[0];
        self.coeffs[1] += self.deltas[1];
        self.coeffs[2] += self.deltas[2];
        self.coeffs[3] += self.deltas[3];
        self.coeffs[4] += self.deltas[4];
        let mut y = self.coeffs[0] * x + self.w1;
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
        } else {
            self.y_prev = y;
        }
        (y, unstable)
    }
}
pub struct Cascade {
    stages: [BiquadState; NUM_STAGES],
    boost: f64,
    boost_delta: f64,
    interstage_drive: f32,
    interstage_delta: f32,
    /// 0 = off. Higher lowers the distortion threshold Vt, so more sections tip in.
    pole_distort: f32,
    pole_delta: f32,
    instability_detected: bool,
}
impl Cascade {
    pub fn new() -> Self {
        Self {
            stages: std::array::from_fn(|_| BiquadState::new()),
            boost: 1.0,
            boost_delta: 0.0,
            interstage_drive: 0.0,
            interstage_delta: 0.0,
            pole_distort: 0.0,
            pole_delta: 0.0,
            instability_detected: false,
        }
    }
    pub fn reset(&mut self) {
        for stage in &mut self.stages {
            stage.w1 = 0.0;
            stage.w2 = 0.0;
            stage.deltas = [0.0; NUM_COEFFS];
        }
        for stage in &mut self.stages {
            stage.y_prev = 0.0;
        }
        self.boost_delta = 0.0;
        self.interstage_delta = 0.0;
        self.pole_delta = 0.0;
        self.instability_detected = false;
    }
    pub fn set_boost(&mut self, target: f64, ramp_samples: usize) {
        let ramp_samples = ramp_samples.max(1) as f64;
        self.boost_delta = (target - self.boost) / ramp_samples;
    }
    pub fn set_interstage_drive(&mut self, target: f32, ramp_samples: usize) {
        let target = target.clamp(0.0, 1.0);
        self.interstage_delta = (target - self.interstage_drive) / ramp_samples.max(1) as f32;
    }
    /// The patent's controlled parameter is the THRESHOLD, not a drive amount: you
    /// lower the bar at which the filter's own resonance destabilises itself.
    pub fn set_pole_distortion(&mut self, target: f32, ramp_samples: usize) {
        let target = target.clamp(0.0, 1.0);
        self.pole_delta = (target - self.pole_distort) / ramp_samples.max(1) as f32;
    }
    pub fn snap_targets(&mut self, interpolated: &CornerData) {
        for (stage, coeffs) in self.stages.iter_mut().zip(interpolated.iter()) {
            stage.coeffs = *coeffs;
            stage.deltas = [0.0; NUM_COEFFS];
        }
    }
    pub fn set_targets(&mut self, interpolated: &CornerData, ramp_samples: usize) {
        for (stage, coeffs) in self.stages.iter_mut().zip(interpolated.iter()) {
            stage.set_target(coeffs, ramp_samples);
        }
    }
    #[inline(always)]
    pub fn tick(&mut self, x: f32) -> f32 {
        let mut v = x as f64;
        if self.pole_distort > 0.0 || self.pole_delta != 0.0 {
            self.pole_distort = (self.pole_distort + self.pole_delta).clamp(0.0, 1.0);
            let amt = self.pole_distort as f64;
            let vt = chew_threshold(amt);
            let push_strength = chew_push_strength(amt);
            for stage in &mut self.stages {
                let (next, unstable) = stage.process_sample_pole_distort(v, vt, push_strength);
                if unstable {
                    self.instability_detected = true;
                    return 0.0;
                }
                v = next;
            }
        } else if self.interstage_drive <= 0.0 && self.interstage_delta == 0.0 {
            for stage in &mut self.stages {
                let (next, unstable) = stage.process_sample(v);
                if unstable {
                    self.instability_detected = true;
                    return 0.0;
                }
                v = next;
            }
        } else {
            self.interstage_drive = (self.interstage_drive + self.interstage_delta).clamp(0.0, 1.0);
            let g = 1.0 + 7.0 * self.interstage_drive as f64;
            for (i, stage) in self.stages.iter_mut().enumerate() {
                let (next, unstable) = stage.process_sample(v);
                if unstable {
                    self.instability_detected = true;
                    return 0.0;
                }
                v = next;
                if i < NUM_STAGES - 1 {
                    v = crate::desk_drive::mackity_saturate(v * g) / g;
                }
            }
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
    pub fn process_block_mono(&mut self, samples: &mut [f32]) {
        for sample in samples.iter_mut() {
            *sample = self.tick(*sample);
        }
    }
    pub fn take_instability_flag(&mut self) -> bool {
        let instability_detected = self.instability_detected;
        self.instability_detected = false;
        instability_detected
    }
    pub fn get_coeffs(&self, out: &mut [[f64; NUM_COEFFS]; NUM_STAGES]) {
        for (i, stage) in self.stages.iter().enumerate() {
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
    fn rossum_reference(coeffs: &[f64; NUM_COEFFS], input: &[f64]) -> Vec<f64> {
        let mut x1 = 0.0;
        let mut x2 = 0.0;
        let mut y1 = 0.0;
        let mut y2 = 0.0;
        let mut out = Vec::with_capacity(input.len());
        for &x0 in input {
            let y0 =
                coeffs[0] * x0 + coeffs[1] * x1 + coeffs[2] * x2 - coeffs[3] * y1 - coeffs[4] * y2;
            out.push(y0);
            x2 = x1;
            x1 = x0;
            y2 = y1;
            y1 = y0;
        }
        out
    }
    #[test]
    fn passthrough_is_identity() {
        let mut cascade = Cascade::new();
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
        let mut buf = [1.0f32; 64];
        cascade.process_block_mono(&mut buf);
        cascade.reset();
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
    #[test]
    fn df2t_stage_matches_rossum_biquad_difference_equation() {
        let cases = [
            [0.72, -0.31, 0.18, -1.112, 0.716],
            [1.0, 0.0, 0.0, -0.842, 0.303],
            [0.19, 0.27, 0.19, -1.438, 0.522],
        ];
        let input = [
            1.0, -0.25, 0.125, 0.0, 0.5, -0.75, 0.375, -0.1875, 0.09375, 0.0, -0.03125, 0.015625,
        ];
        for coeffs in cases {
            let expected = rossum_reference(&coeffs, &input);
            let mut stage = BiquadState::new();
            stage.coeffs = coeffs;
            for (i, (&x, &want)) in input.iter().zip(expected.iter()).enumerate() {
                let (got, unstable) = stage.process_sample(x);
                assert!(!unstable, "case {coeffs:?} went unstable at sample {i}");
                assert!(
                    (got - want).abs() <= 1e-12,
                    "sample {i}: DF2T {got:.15e} != Rossum {want:.15e} for {coeffs:?}"
                );
            }
        }
    }
    #[test]
    fn six_stage_cascade_matches_serial_rossum_biquads_without_ramping() {
        let corner: CornerData = [
            [0.90, -0.20, 0.08, -0.72, 0.20],
            [1.05, 0.12, -0.04, -0.51, 0.15],
            [0.82, 0.25, 0.10, -0.93, 0.36],
            [1.00, -0.08, 0.03, -0.30, 0.08],
            [0.76, 0.18, 0.06, -1.10, 0.49],
            PASSTHROUGH_COEFFS,
        ];
        let input = [
            0.0, 0.25, -0.5, 0.125, 0.75, -0.375, 0.1875, 0.0, -0.0625, 0.03125,
        ];
        let mut reference = input.to_vec();
        for coeffs in &corner {
            reference = rossum_reference(coeffs, &reference);
        }
        let mut cascade = Cascade::new();
        for (stage, coeffs) in cascade.stages[..NUM_STAGES].iter_mut().zip(corner.iter()) {
            stage.coeffs = *coeffs;
        }
        for (i, (&x, &want)) in input.iter().zip(reference.iter()).enumerate() {
            let got = cascade.tick(x as f32) as f64;
            assert!(
                (got - want).abs() <= 1e-6,
                "sample {i}: cascade {got:.15e} != serial Rossum {want:.15e}"
            );
        }
        assert!(!cascade.take_instability_flag());
    }
    #[test]
    fn chew_control_law_is_smooth_monotonic_and_keeps_its_endpoints() {
        assert!((chew_threshold(0.0) - CHEW_THRESHOLD_OFF).abs() < 1.0e-12);
        assert!(chew_threshold(1.0) < CHEW_THRESHOLD_FULL + 0.000_5);
        assert_eq!(chew_push_strength(0.0), 0.0);
        assert_eq!(chew_push_strength(1.0), 1.0);

        let mut previous_threshold = chew_threshold(0.0);
        let mut previous_push = chew_push_strength(0.0);
        for step in 1..=100 {
            let amount = step as f64 / 100.0;
            let threshold = chew_threshold(amount);
            let push = chew_push_strength(amount);
            assert!(threshold < previous_threshold);
            assert!(push > previous_push);
            previous_threshold = threshold;
            previous_push = push;
        }

        // Low CHEW cannot jump directly to a large pole movement even if an
        // unusually hot section has already crossed its threshold.
        assert!(chew_push_strength(0.1) <= 0.010_001);
        assert!(chew_push_strength(0.25) <= 0.062_501);
    }
}
