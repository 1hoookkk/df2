const SYLLABIC_CHARGE_TAU_MS: f32 = 39.499_355;
const SYLLABIC_DISCHARGE_TAU_MS: f32 = 16.546_566;
const RECONSTRUCTION_INTEGRATOR_TAU_MS: f32 = 4.360_179_4;
const IDLE_OSCILLATION_FREQ_HZ: f32 = 2_596.0;
const IDLE_OSCILLATION_LEVEL_DBFS: f32 = -91.289_73;
const TRANSIENT_OVERSHOOT_DB: f32 = 2.465_908_5;
const TRANSIENT_RECOVERY_MS: f32 = 2.3125;

#[derive(Debug, Clone)]
pub struct CvsdInput {
    sample_rate: f32,
    charge_alpha: f32,
    discharge_alpha: f32,
    recon_alpha: f32,
    recovery_alpha: f32,
    idle_phase: f32,
    idle_phase_delta: f32,
    idle_amp: f32,
    syllabic: f32,
    step: f32,
    stair: f32,
    recon: f32,
    prev_recon: f32,
    overshoot_gain: f32,
}

impl Default for CvsdInput {
    fn default() -> Self {
        let mut cvsd = Self {
            sample_rate: 44_100.0,
            charge_alpha: 0.0,
            discharge_alpha: 0.0,
            recon_alpha: 0.0,
            recovery_alpha: 0.0,
            idle_phase: 0.0,
            idle_phase_delta: 0.0,
            idle_amp: db_to_linear(IDLE_OSCILLATION_LEVEL_DBFS),
            syllabic: 0.0,
            step: 0.0,
            stair: 0.0,
            recon: 0.0,
            prev_recon: 0.0,
            overshoot_gain: db_to_linear(TRANSIENT_OVERSHOOT_DB),
        };
        cvsd.prepare(44_100.0);
        cvsd
    }
}

impl CvsdInput {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn prepare(&mut self, sample_rate: f32) {
        self.sample_rate = sample_rate.max(8_000.0);
        self.charge_alpha = tau_alpha(SYLLABIC_CHARGE_TAU_MS, self.sample_rate);
        self.discharge_alpha = tau_alpha(SYLLABIC_DISCHARGE_TAU_MS, self.sample_rate);
        self.recon_alpha = tau_alpha(RECONSTRUCTION_INTEGRATOR_TAU_MS, self.sample_rate);
        self.recovery_alpha = tau_alpha(TRANSIENT_RECOVERY_MS, self.sample_rate);
        self.idle_phase_delta = std::f32::consts::TAU * IDLE_OSCILLATION_FREQ_HZ / self.sample_rate;
        self.idle_amp = db_to_linear(IDLE_OSCILLATION_LEVEL_DBFS);
        self.overshoot_gain = db_to_linear(TRANSIENT_OVERSHOOT_DB);
        self.reset();
    }

    pub fn reset(&mut self) {
        self.idle_phase = 0.0;
        self.syllabic = 0.0;
        self.step = self.idle_amp;
        self.stair = 0.0;
        self.recon = 0.0;
        self.prev_recon = 0.0;
    }

    #[inline(always)]
    pub fn process(&mut self, input: f32) -> f32 {
        let x = input.clamp(-1.0, 1.0);
        let error = x - self.recon;
        let bit = if error >= 0.0 { 1.0 } else { -1.0 };
        let error_mag = error.abs();

        let syllabic_alpha = if error_mag > self.syllabic {
            self.charge_alpha
        } else {
            self.discharge_alpha
        };
        self.syllabic += syllabic_alpha * (error_mag - self.syllabic);

        let target_step = (self.idle_amp + self.syllabic * 0.86).clamp(self.idle_amp, 0.62);
        self.step += self.recovery_alpha * (target_step - self.step);

        self.stair =
            (self.stair + bit * self.step).clamp(-self.overshoot_gain, self.overshoot_gain);
        self.prev_recon = self.recon;
        self.recon += self.recon_alpha * (self.stair - self.recon);

        self.idle_phase += self.idle_phase_delta;
        if self.idle_phase >= std::f32::consts::TAU {
            self.idle_phase -= std::f32::consts::TAU;
        }

        let idle_gate = (1.0 - self.syllabic * 96.0).clamp(0.0, 1.0);
        let idle = self.idle_phase.sin() * self.idle_amp * idle_gate;
        let transient = (self.recon - self.prev_recon) * (self.overshoot_gain - 1.0) * 0.18;

        (self.recon + transient + idle).clamp(-self.overshoot_gain, self.overshoot_gain)
    }
}

#[inline(always)]
fn tau_alpha(tau_ms: f32, sample_rate: f32) -> f32 {
    let tau_seconds = (tau_ms * 0.001).max(1e-6);
    (1.0 - (-1.0 / (tau_seconds * sample_rate)).exp()).clamp(0.0, 1.0)
}

#[inline(always)]
fn db_to_linear(db: f32) -> f32 {
    10.0_f32.powf(db / 20.0)
}
