const OS: usize = 4;
const PH: usize = 16;
const L: usize = OS * PH;
#[inline]
fn sinc(x: f64) -> f64 {
    if x.abs() < 1.0e-9 {
        1.0
    } else {
        let px = std::f64::consts::PI * x;
        px.sin() / px
    }
}
#[derive(Debug, Clone)]
pub struct Oversampler4x {
    up_h: [[f64; PH]; OS],
    down_h: [f64; L],
    up_hist: [f64; PH],
    down_hist: [f64; L],
}
impl Default for Oversampler4x {
    fn default() -> Self {
        let mut os = Self {
            up_h: [[0.0; PH]; OS],
            down_h: [0.0; L],
            up_hist: [0.0; PH],
            down_hist: [0.0; L],
        };
        os.build_taps();
        os
    }
}
impl Oversampler4x {
    pub fn new() -> Self {
        Self::default()
    }
    pub const fn latency_samples() -> usize {
        (L - 1) / OS
    }
    fn build_taps(&mut self) {
        let fc = 0.5 / OS as f64 * 0.90;
        let center = (L - 1) as f64 / 2.0;
        let mut proto = [0.0f64; L];
        let mut sum = 0.0;
        for (i, p) in proto.iter_mut().enumerate() {
            let n = i as f64 - center;
            let w = 0.42 - 0.5 * (2.0 * std::f64::consts::PI * i as f64 / (L - 1) as f64).cos()
                + 0.08 * (4.0 * std::f64::consts::PI * i as f64 / (L - 1) as f64).cos();
            *p = 2.0 * fc * sinc(2.0 * fc * n) * w;
            sum += *p;
        }
        for p in proto.iter_mut() {
            *p /= sum;
        }
        self.down_h = proto;
        for phase in 0..OS {
            for k in 0..PH {
                self.up_h[phase][k] = proto[phase + OS * k] * OS as f64;
            }
        }
    }
    pub fn reset(&mut self) {
        self.up_hist = [0.0; PH];
        self.down_hist = [0.0; L];
    }
    #[inline]
    pub fn upsample(&mut self, x: f64) -> [f64; OS] {
        for k in (1..PH).rev() {
            self.up_hist[k] = self.up_hist[k - 1];
        }
        self.up_hist[0] = x;
        let mut out = [0.0f64; OS];
        for (phase, o) in out.iter_mut().enumerate() {
            let mut acc = 0.0;
            for k in 0..PH {
                acc += self.up_hist[k] * self.up_h[phase][k];
            }
            *o = acc;
        }
        out
    }
    #[inline]
    pub fn downsample(&mut self, block: &[f64; OS]) -> f64 {
        for &s in block.iter() {
            for k in (1..L).rev() {
                self.down_hist[k] = self.down_hist[k - 1];
            }
            self.down_hist[0] = s;
        }
        let mut acc = 0.0;
        for k in 0..L {
            acc += self.down_hist[k] * self.down_h[k];
        }
        acc
    }
}
