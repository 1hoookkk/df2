pub const SUPPORTED_MODEL: &str = "desk_slam_v1";

const MACKITY_ULTRASONIC_HZ: f64 = 19_160.0;
const MACKITY_BIQUAD_A_Q: f64 = 0.431_684_981_684_982;
const MACKITY_BIQUAD_B_Q: f64 = 1.158_229_8;
const MACKITY_IIR_A: f64 = 0.001_860_867;
const MACKITY_IIR_B: f64 = 0.000_287_496;
const MACKITY_CURVE: f64 = 0.1768;
const SLAM_TO_INPUT_GAIN: f64 = 99.0;

/// Pre-cascade Mackie 1202-style input abuse.
///
/// This follows the Airwindows Mackity input-stage topology: one-knob input
/// gain into subsonic cleanup, two ultrasonic lowpass biquads, and fifth-power
/// desk saturation. It intentionally does not quantize or resample; converter
/// grit is a separate sound from analog Mackie slam.
#[derive(Debug, Clone)]
pub struct DeskDrive {
    enabled: bool,
    sample_rate: f64,
    iir_amount_a: f64,
    iir_amount_b: f64,
    iir_sample_a: f64,
    iir_sample_b: f64,
    biquad_a: Biquad,
    biquad_b: Biquad,
}

impl Default for DeskDrive {
    fn default() -> Self {
        Self {
            enabled: false,
            sample_rate: 44_100.0,
            iir_amount_a: MACKITY_IIR_A,
            iir_amount_b: MACKITY_IIR_B,
            iir_sample_a: 0.0,
            iir_sample_b: 0.0,
            biquad_a: Biquad::default(),
            biquad_b: Biquad::default(),
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
        self.sample_rate = f64::from(sample_rate.max(8_000.0));
        let overall_scale = self.sample_rate / 44_100.0;
        self.iir_amount_a = MACKITY_IIR_A / overall_scale;
        self.iir_amount_b = MACKITY_IIR_B / overall_scale;
        self.biquad_a
            .set_lowpass(self.sample_rate, MACKITY_ULTRASONIC_HZ, MACKITY_BIQUAD_A_Q);
        self.biquad_b
            .set_lowpass(self.sample_rate, MACKITY_ULTRASONIC_HZ, MACKITY_BIQUAD_B_Q);
        self.reset();
    }

    pub fn configure(&mut self, model: &str) {
        let should_enable = model == SUPPORTED_MODEL;
        if self.enabled != should_enable {
            self.enabled = should_enable;
            self.reset();
        }
    }

    pub fn is_active(&self) -> bool {
        self.enabled
    }

    pub fn reset(&mut self) {
        self.iir_sample_a = 0.0;
        self.iir_sample_b = 0.0;
        self.biquad_a.reset();
        self.biquad_b.reset();
    }

    #[inline(always)]
    pub fn process(&mut self, input: f32, slam: f32) -> f32 {
        if !self.enabled {
            return input;
        }

        let slam = f64::from(slam.clamp(0.0, 1.0));
        let mut sample = f64::from(input) * (1.0 + slam * SLAM_TO_INPUT_GAIN);

        self.iir_sample_a = denormal_guard(
            self.iir_sample_a * (1.0 - self.iir_amount_a) + sample * self.iir_amount_a,
        );
        sample -= self.iir_sample_a;

        sample = self.biquad_a.process(sample);
        sample = mackity_saturate(sample);
        sample = self.biquad_b.process(sample);

        self.iir_sample_b = denormal_guard(
            self.iir_sample_b * (1.0 - self.iir_amount_b) + sample * self.iir_amount_b,
        );
        sample -= self.iir_sample_b;

        if sample.is_finite() {
            sample.clamp(-8.0, 8.0) as f32
        } else {
            0.0
        }
    }
}

#[derive(Debug, Clone, Copy, Default)]
struct Biquad {
    b0: f64,
    b1: f64,
    b2: f64,
    a1: f64,
    a2: f64,
    x1: f64,
    x2: f64,
    y1: f64,
    y2: f64,
}

impl Biquad {
    fn set_lowpass(&mut self, sample_rate: f64, freq_hz: f64, q: f64) {
        let normalized = (freq_hz / sample_rate).clamp(1.0e-6, 0.49);
        let k = (std::f64::consts::PI * normalized).tan();
        let norm = 1.0 / (1.0 + k / q + k * k);

        self.b0 = k * k * norm;
        self.b1 = 2.0 * self.b0;
        self.b2 = self.b0;
        self.a1 = 2.0 * (k * k - 1.0) * norm;
        self.a2 = (1.0 - k / q + k * k) * norm;
    }

    #[inline(always)]
    fn process(&mut self, input: f64) -> f64 {
        let output = self.b0 * input + self.b1 * self.x1 + self.b2 * self.x2
            - self.a1 * self.y1
            - self.a2 * self.y2;

        self.x2 = self.x1;
        self.x1 = input;
        self.y2 = self.y1;
        self.y1 = denormal_guard(output);
        self.y1
    }

    fn reset(&mut self) {
        self.x1 = 0.0;
        self.x2 = 0.0;
        self.y1 = 0.0;
        self.y2 = 0.0;
    }
}

#[inline(always)]
pub fn mackity_saturate(sample: f64) -> f64 {
    let clipped = sample.clamp(-1.0, 1.0);
    clipped - clipped.powi(5) * MACKITY_CURVE
}

#[inline(always)]
fn denormal_guard(sample: f64) -> f64 {
    if sample.abs() < 1.18e-37 {
        0.0
    } else {
        sample
    }
}
