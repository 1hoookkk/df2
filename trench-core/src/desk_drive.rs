pub const SUPPORTED_MODEL: &str = "desk_slam_v1";

/// Pre-cascade authored drive.
///
/// This is intentionally honest about what it is: a generic ugly desk-style
/// saturator for hostile gain staging. It does not claim hardware identity.
#[derive(Debug, Clone)]
pub struct DeskDrive {
    enabled: bool,
    sample_rate: f32,
    pregain: f32,
    output_trim: f32,
    headroom_knee: f32,
    headroom_ratio: f32,
    positive_knee: f32,
    negative_knee: f32,
    positive_rail: f32,
    negative_rail: f32,
    hp_alpha: f32,
    hp_x1: f32,
    hp_y1: f32,
    edge_mix: f32,
    slew_limit: f32,
    slew_state: f32,
    lp_alpha: f32,
    lp_state: f32,
}

impl Default for DeskDrive {
    fn default() -> Self {
        Self {
            enabled: false,
            sample_rate: 44_100.0,
            pregain: 1.0,
            output_trim: 1.0,
            headroom_knee: 0.42,
            headroom_ratio: 0.35,
            positive_knee: 0.78,
            negative_knee: 0.72,
            positive_rail: 0.91,
            negative_rail: 0.87,
            hp_alpha: 0.0,
            hp_x1: 0.0,
            hp_y1: 0.0,
            edge_mix: 0.18,
            slew_limit: 0.08,
            slew_state: 0.0,
            lp_alpha: 1.0,
            lp_state: 0.0,
        }
    }
}

impl DeskDrive {
    pub fn new() -> Self {
        let mut drive = Self::default();
        drive.prepare(44_100.0);
        drive
    }

    pub fn prepare(&mut self, sample_rate: f32) {
        self.sample_rate = sample_rate.max(8_000.0);

        // Mild transient emphasis before slew limiting. This is not a literal
        // op-amp model; it is a cheap edge detector that makes the rate stage
        // flatten hits instead of sounding rounded.
        let hp_fc = 1_200.0;
        let hp_rc = 1.0 / (2.0 * std::f32::consts::PI * hp_fc);
        let hp_dt = 1.0 / self.sample_rate;
        self.hp_alpha = hp_rc / (hp_rc + hp_dt);

        // Simple post-damage analog rolloff.
        let lp_fc = 20_000.0_f32.min(self.sample_rate * 0.45);
        self.lp_alpha = one_pole_alpha(lp_fc, self.sample_rate);

        // Normalized edge rate. The nominal 5 V/us desk claim is far above
        // audio-band deltas in this unit domain, so keep a fixed, sample-rate
        // aware clamp that produces the intended transient flattening.
        self.slew_limit = 3_500.0 / self.sample_rate;
        self.reset();
    }

    pub fn configure(&mut self, input_gain_db: f32, model: &str) {
        let drive_db = input_gain_db.clamp(0.0, 60.0);
        self.enabled = model == SUPPORTED_MODEL && drive_db > 0.0;
        self.pregain = db_to_linear(drive_db).max(1.0);
        self.output_trim = if self.enabled {
            db_to_linear(-drive_db * 0.38).clamp(0.08, 1.0)
        } else {
            1.0
        };
        self.reset();
    }

    pub fn is_active(&self) -> bool {
        self.enabled
    }

    pub fn reset(&mut self) {
        self.hp_x1 = 0.0;
        self.hp_y1 = 0.0;
        self.slew_state = 0.0;
        self.lp_state = 0.0;
    }

    #[inline(always)]
    pub fn process(&mut self, input: f32) -> f32 {
        if !self.enabled {
            return input;
        }

        let staged = headroom_compand(
            input * self.pregain,
            self.headroom_knee,
            self.headroom_ratio,
        );
        let saturated = asym_rail_clip(
            staged,
            self.positive_knee,
            self.negative_knee,
            self.positive_rail,
            self.negative_rail,
        );

        let edge = self.highpass(saturated);
        let target = saturated - edge * self.edge_mix;

        let delta = (target - self.slew_state).clamp(-self.slew_limit, self.slew_limit);
        self.slew_state += delta;

        let rolled = self.lowpass(self.slew_state);
        rolled * self.output_trim
    }

    #[inline(always)]
    fn highpass(&mut self, input: f32) -> f32 {
        let output = self.hp_alpha * (self.hp_y1 + input - self.hp_x1);
        self.hp_x1 = input;
        self.hp_y1 = output;
        output
    }

    #[inline(always)]
    fn lowpass(&mut self, input: f32) -> f32 {
        self.lp_state += self.lp_alpha * (input - self.lp_state);
        self.lp_state
    }
}

#[inline(always)]
fn db_to_linear(db: f32) -> f32 {
    10.0_f32.powf(db / 20.0)
}

#[inline(always)]
fn one_pole_alpha(fc: f32, sample_rate: f32) -> f32 {
    let omega = 2.0 * std::f32::consts::PI * fc / sample_rate;
    (1.0 - (-omega).exp()).clamp(0.0, 1.0)
}

#[inline(always)]
fn headroom_compand(sample: f32, knee: f32, ratio: f32) -> f32 {
    let abs = sample.abs();
    if abs <= knee {
        return sample;
    }

    let extra = abs - knee;
    let curved = knee + (extra * ratio) / (1.0 + extra * (1.0 - ratio));
    curved.copysign(sample)
}

#[inline(always)]
fn asym_rail_clip(
    sample: f32,
    positive_knee: f32,
    negative_knee: f32,
    positive_rail: f32,
    negative_rail: f32,
) -> f32 {
    if sample >= 0.0 {
        saturate_halfwave(sample, positive_knee, positive_rail, 1.8)
    } else {
        -saturate_halfwave(-sample, negative_knee, negative_rail, 1.2)
    }
}

#[inline(always)]
fn saturate_halfwave(sample: f32, knee: f32, rail: f32, curvature: f32) -> f32 {
    if sample <= knee {
        return sample;
    }

    let span = (rail - knee).max(1e-5);
    let over = (sample - knee) / span;
    let bent = over / (1.0 + curvature * over);
    (knee + bent * span).min(rail)
}
