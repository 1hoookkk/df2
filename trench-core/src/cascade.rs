use crate::cartridge::CornerData;
pub const NUM_STAGES: usize = 6;
pub const NUM_COEFFS: usize = 5;
pub const PASSTHROUGH_COEFFS: [f64; NUM_COEFFS] = [1.0, 0.0, 0.0, 0.0, 0.0];
pub const BLOCK_SIZE: usize = 32;
/// Full-scale reference for pole-radius distortion (patent's |V_p|).
const V_PEAK: f64 = 1.0;
/// Which per-section nonlinear topology CHEW runs. A/B hook only - the shipped
/// default is and stays `PoleRadius`.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ChewTopology {
    /// Shipped path: DF2T biquad with dynamic pole-radius push.
    PoleRadius,
    /// US 10,514,883 Max Mathews phasor section: complex pole state, saturation
    /// applied to the complex phasor itself (plus the same radius push).
    Phasor,
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
    /// Phasor path only: complex pole state z[n]. Unused by the DF2T paths.
    zr: f64,
    zi: f64,
    /// False when `zr/zi` do not correspond to the current `w1/w2` history
    /// (after reset, or after a degenerate-pole sample fell back to DF2).
    z_synced: bool,
}
impl BiquadState {
    fn new() -> Self {
        Self {
            coeffs: PASSTHROUGH_COEFFS,
            deltas: [0.0; NUM_COEFFS],
            w1: 0.0,
            w2: 0.0,
            y_prev: 0.0,
            zr: 0.0,
            zi: 0.0,
            z_synced: false,
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
    fn process_sample_pole_distort(&mut self, x: f64, vt: f64) -> (f64, bool) {
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
                    let ratio = ((vg - vt) / V_PEAK).clamp(0.0, 4.0);
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
    /// US 10,514,883 alternate topology: the Max Mathews phasor section.
    ///
    /// The two-pole denominator is realised as ONE complex one-pole
    ///     z[n] = p*z[n-1] + x[n],   p = R*e^(j*theta)
    /// (the input joins the REAL part, per the patent), and the real all-pole
    /// signal is recovered as
    ///     w[n] = Re(z[n]) + cot(theta)*Im(z[n]).
    /// That identity is exact: z = X*(1 - conj(p)/z)/D, so Re(z) = w - R*cos*w[n-1]
    /// and Im(z) = R*sin*w[n-1]. The zeros then apply as the ordinary direct-form
    /// feed-forward on the same w history, so with saturation off this section is
    /// mathematically the DF2T biquad.
    ///
    /// The nonlinearity the patent adds here is on the COMPLEX state, not the real
    /// output: the phasor is magnitude-limited before it is stored, so the clip
    /// feeds back into the resonator's own rotation. The dynamic pole-radius push
    /// stays composed on top of it - the patent has both.
    ///
    /// Degenerate poles (real poles, theta -> 0 or pi) have no usable cot(theta);
    /// those samples fall back to the plain direct-form recursion on w1/w2, which
    /// is the same state the phasor path maintains, so no state is lost.
    ///
    /// NOTE: on this path `w1/w2` are the ALL-POLE (direct form II) history, not
    /// the DF2T accumulators. Topology is fixed for the lifetime of a reset.
    #[inline(always)]
    fn process_sample_phasor(&mut self, x: f64, vt: f64) -> (f64, bool) {
        self.coeffs[0] += self.deltas[0];
        self.coeffs[1] += self.deltas[1];
        self.coeffs[2] += self.deltas[2];
        self.coeffs[3] += self.deltas[3];
        self.coeffs[4] += self.deltas[4];

        let (mut a1, mut a2) = (self.coeffs[3], self.coeffs[4]);
        let (b0, b1, b2) = (self.coeffs[0], self.coeffs[1], self.coeffs[2]);
        // Identical detector, formula and asymptotic brake as the shipped path.
        let vg = self.y_prev.abs();
        if vg > vt && a2 > 1.0e-9 {
            let r = a2.sqrt();
            if r > 1.0e-6 && r < 1.0 {
                let cos_theta = -a1 / (2.0 * r);
                if cos_theta.abs() <= 1.0 {
                    let ratio = ((vg - vt) / V_PEAK).clamp(0.0, 4.0);
                    let r_new = (r + r * (1.0 - r) * ratio).clamp(0.0, 0.999_9);
                    a1 = -2.0 * r_new * cos_theta;
                    a2 = r_new * r_new;
                }
            }
        }

        let r = if a2 > 0.0 { a2.sqrt() } else { 0.0 };
        let cos_theta = if r > 1.0e-9 { -a1 / (2.0 * r) } else { 2.0 };
        let w = if cos_theta.abs() <= 1.0 - 1.0e-6 {
            let sin_theta = (1.0 - cos_theta * cos_theta).sqrt();
            if !self.z_synced {
                // z[n-1] = w[n-1] - conj(p)*w[n-2]
                self.zr = self.w1 - r * cos_theta * self.w2;
                self.zi = r * sin_theta * self.w2;
                self.z_synced = true;
            }
            let mut zr = r * (cos_theta * self.zr - sin_theta * self.zi) + x;
            let mut zi = r * (sin_theta * self.zr + cos_theta * self.zi);
            // Complex-state saturation. The patent names a threshold but not a
            // curve; this is a magnitude-only soft limit that is C1-continuous at
            // the knee and asymptotes to 2*vt, so the phasor's ANGLE is untouched
            // and only its length is confiscated.
            let m = (zr * zr + zi * zi).sqrt();
            if m > vt && vt > 0.0 {
                let g = (vt + vt * ((m - vt) / vt).tanh()) / m;
                zr *= g;
                zi *= g;
            }
            self.zr = zr;
            self.zi = zi;
            zr + (cos_theta / sin_theta) * zi
        } else {
            self.z_synced = false;
            x - a1 * self.w1 - a2 * self.w2
        };
        let y = b0 * w + b1 * self.w1 + b2 * self.w2;
        if !w.is_finite() || !y.is_finite() {
            self.w1 = 0.0;
            self.w2 = 0.0;
            self.zr = 0.0;
            self.zi = 0.0;
            self.z_synced = false;
            self.y_prev = 0.0;
            self.deltas = [0.0; NUM_COEFFS];
            return (0.0, true);
        }
        self.w2 = self.w1;
        self.w1 = w;
        self.y_prev = y;
        (y, false)
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
    chew_topology: ChewTopology,
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
            chew_topology: ChewTopology::PoleRadius,
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
            stage.zr = 0.0;
            stage.zi = 0.0;
            stage.z_synced = false;
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
    /// Engine-side A/B hook: swaps the CHEW section topology. Default unchanged.
    pub fn set_chew_topology(&mut self, topology: ChewTopology) {
        if topology != self.chew_topology {
            self.chew_topology = topology;
            self.reset();
        }
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
            // Threshold mapping, calibrated against measured section levels (a power
            // curve put the whole useful range above 0.6 and CHEW never got there).
            //   0.00 -> 1.50  off      0.22 -> 0.28  mid (CHEW at full Q)
            //   0.40 -> 0.08  hard     1.00 -> 0.02  always biting
            let amt = self.pole_distort as f64;
            let vt = 1.48 * (-8.0 * amt).exp() + 0.02;
            let phasor = self.chew_topology == ChewTopology::Phasor;
            for stage in &mut self.stages {
                let (next, unstable) = if phasor {
                    stage.process_sample_phasor(v, vt)
                } else {
                    stage.process_sample_pole_distort(v, vt)
                };
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
    /// Three genuinely high-Q coefficient rows DECODED from a shipping body by the
    /// crate's own packed interpolator - never hand-typed. One per morph pose, each
    /// the section with the tightest pole radius at that pose.
    fn high_q_rows_from_ship_body() -> Vec<[f64; NUM_COEFFS]> {
        const BODY: &[u8; 240] =
            include_bytes!("../../presets_ship_v1/bodies/shipv2_303_cavity_acid.body240");
        let cart = crate::cartridge::Cartridge::from_body_bytes("acid", BODY, 1.0).unwrap();
        [0.0, 0.5, 1.0]
            .iter()
            .map(|&m| {
                let corner = cart.interpolate(m, 1.0);
                *corner
                    .iter()
                    .max_by(|a, b| a[4].partial_cmp(&b[4]).unwrap())
                    .unwrap()
            })
            .collect()
    }
    #[test]
    fn phasor_section_is_the_biquad_when_saturation_is_off() {
        let mut cases: Vec<[f64; NUM_COEFFS]> = vec![
            [0.72, -0.31, 0.18, -1.112, 0.716],
            [1.0, 0.0, 0.0, -0.842, 0.303],
            [0.19, 0.27, 0.19, -1.438, 0.522],
        ];
        cases.extend(high_q_rows_from_ship_body());
        let input: Vec<f64> = (0..4096)
            .map(|i| ((i as f64 * 0.7919).sin() * 0.6 + (i as f64 * 0.1013).sin() * 0.4))
            .collect();
        let mut worst = 0.0f64;
        for coeffs in cases {
            let expected = rossum_reference(&coeffs, &input);
            let mut stage = BiquadState::new();
            stage.coeffs = coeffs;
            for (i, (&x, &want)) in input.iter().zip(expected.iter()).enumerate() {
                // vt = +inf: no radius push, no phasor saturation - pure topology.
                let (got, unstable) = stage.process_sample_phasor(x, f64::INFINITY);
                assert!(!unstable, "case {coeffs:?} went unstable at sample {i}");
                worst = worst.max((got - want).abs());
                assert!(
                    (got - want).abs() <= 1e-9,
                    "sample {i}: phasor {got:.15e} != Rossum {want:.15e} for {coeffs:?}"
                );
            }
        }
        println!("phasor vs Rossum max abs error = {worst:.3e}");
    }
    #[test]
    fn phasor_survives_the_full_morph_q_grid_with_saturation_hard() {
        const BODY: &[u8; 240] =
            include_bytes!("../../presets_ship_v1/bodies/shipv2_303_cavity_acid.body240");
        let cart = crate::cartridge::Cartridge::from_body_bytes("acid", BODY, 1.0).unwrap();
        let mut cascade = Cascade::new();
        cascade.set_chew_topology(ChewTopology::Phasor);
        // Hardest setting the mapping allows: vt = 0.02, every section always biting.
        cascade.set_pole_distortion(1.0, 1);
        let mut seed = 0x2f6e_2b1u64;
        let mut noise = || {
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            ((seed >> 33) as f64 / (1u64 << 31) as f64 * 2.0 - 1.0) * 4.0
        };
        let mut peak = 0.0f64;
        for mi in 0..=20 {
            for qi in 0..=20 {
                let (m, q) = (mi as f64 / 20.0, qi as f64 / 20.0);
                let corner = cart.interpolate(m, q);
                // Ramped, not snapped: the per-sample coefficient ramp must hold up.
                cascade.set_targets(&corner, 512);
                for _ in 0..512 {
                    let y = cascade.tick(noise() as f32);
                    assert!(y.is_finite(), "non-finite output at morph {m} q {q}");
                    peak = peak.max(y.abs() as f64);
                }
                assert!(
                    !cascade.take_instability_flag(),
                    "instability latched at morph {m} q {q}"
                );
            }
        }
        println!("phasor grid sweep 441 points OK, peak |y| = {peak:.4}");
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
}
