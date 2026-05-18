//! Aggressive M/S phase-destruction matrix — sibling to `qsound_spatial`.
//!
//! Architecture: split L/R into mid/side, run the side through an integer
//! delay and a Schroeder allpass (magnitude-flat phase smear), then fold the
//! processed side back with an explicit `mu` multiplier. Reconstruction is
//! `L = M + μS'`, `R = M − μS'`.
//!
//! `mu` is intentionally unclamped. `mu < 0` flips polarity; `|mu| > 1`
//! overshoots and steers energy outside the loudspeaker pair. `space` scales
//! the deviation from unity, so at `space = 0` the side passes through and
//! the stage is a no-op.

const MAX_SIDE_DELAY: usize = 4096;
const MAX_ALLPASS_DELAY: usize = 1024;

#[derive(Debug, Clone)]
struct IntDelay {
    buffer: Vec<f32>,
    write_idx: usize,
    delay: usize,
}

impl IntDelay {
    fn new(capacity: usize) -> Self {
        Self {
            buffer: vec![0.0; capacity.max(1)],
            write_idx: 0,
            delay: 0,
        }
    }

    fn set_delay(&mut self, samples: usize) {
        self.delay = samples.min(self.buffer.len() - 1);
    }

    #[inline(always)]
    fn process(&mut self, x: f32) -> f32 {
        let cap = self.buffer.len();
        self.buffer[self.write_idx] = x;
        let read_idx = (self.write_idx + cap - self.delay) % cap;
        let y = self.buffer[read_idx];
        self.write_idx = (self.write_idx + 1) % cap;
        y
    }

    fn reset(&mut self) {
        self.buffer.iter_mut().for_each(|s| *s = 0.0);
        self.write_idx = 0;
    }
}

/// Schroeder allpass: `v[n] = x[n] + g·v[n−D]`, `y[n] = −g·x[n] + v[n−D]`.
/// Magnitude is unity at all frequencies; only the phase response changes.
#[derive(Debug, Clone)]
struct SchroederAllpass {
    buffer: Vec<f32>,
    write_idx: usize,
    delay: usize,
    g: f32,
}

impl SchroederAllpass {
    fn new(capacity: usize) -> Self {
        Self {
            buffer: vec![0.0; capacity.max(1)],
            write_idx: 0,
            delay: 1,
            g: 0.0,
        }
    }

    fn set_delay(&mut self, samples: usize) {
        self.delay = samples.clamp(1, self.buffer.len() - 1);
    }

    fn set_g(&mut self, g: f32) {
        // Stability bound for the Schroeder allpass: |g| < 1.
        self.g = g.clamp(-0.999, 0.999);
    }

    #[inline(always)]
    fn process(&mut self, x: f32) -> f32 {
        let cap = self.buffer.len();
        let read_idx = (self.write_idx + cap - self.delay) % cap;
        let delayed = self.buffer[read_idx];
        let v = x + self.g * delayed;
        let y = -self.g * x + delayed;
        self.buffer[self.write_idx] = v;
        self.write_idx = (self.write_idx + 1) % cap;
        y
    }

    fn reset(&mut self) {
        self.buffer.iter_mut().for_each(|s| *s = 0.0);
        self.write_idx = 0;
    }
}

pub struct TrenchMatrix {
    /// Side-channel delay length (integer samples). Public; clamped to
    /// the preallocated capacity at apply-time.
    pub target_delay_samples: usize,
    /// Schroeder allpass internal delay (samples). Larger = more dispersive.
    pub allpass_delay_samples: usize,
    /// Schroeder allpass feedback. Internally clamped to `(-1, 1)` for
    /// stability — values outside that range diverge.
    pub allpass_g: f32,
    /// Phase-invert / fold multiplier applied to the processed side.
    /// Unclamped on purpose. `1.0` = passthrough, `0.0` = mono,
    /// `-1.0` = full polarity flip, `|μ| > 1` = overshoot ("tear").
    pub mu: f32,
    /// 0..1 macro. Scales `μ`'s deviation from unity, so `space = 0`
    /// is a guaranteed no-op regardless of `mu`.
    pub space: f32,

    side_delay: IntDelay,
    allpass: SchroederAllpass,
}

impl TrenchMatrix {
    pub fn new(_sample_rate: f32) -> Self {
        Self {
            target_delay_samples: 11,
            allpass_delay_samples: 7,
            allpass_g: 0.7,
            mu: -2.0,
            space: 0.0,
            side_delay: IntDelay::new(MAX_SIDE_DELAY),
            allpass: SchroederAllpass::new(MAX_ALLPASS_DELAY),
        }
    }

    pub fn reset(&mut self) {
        self.side_delay.reset();
        self.allpass.reset();
    }

    pub fn process_stereo(&mut self, l: &mut [f32], r: &mut [f32]) {
        if self.space <= 0.0 {
            return;
        }

        self.side_delay.set_delay(self.target_delay_samples);
        self.allpass.set_delay(self.allpass_delay_samples);
        self.allpass.set_g(self.allpass_g);

        let space = self.space.clamp(0.0, 1.0);
        let effective_mu = 1.0 + space * (self.mu - 1.0);

        let n = l.len().min(r.len());
        for i in 0..n {
            let lx = l[i];
            let rx = r[i];
            let mid = 0.5 * (lx + rx);
            let side = 0.5 * (lx - rx);

            let delayed = self.side_delay.process(side);
            let smeared = self.allpass.process(delayed);
            let side_out = effective_mu * smeared;

            l[i] = mid + side_out;
            r[i] = mid - side_out;
        }
    }
}
