use crate::cartridge::CornerData;
use crate::cascade::{Cascade, NUM_COEFFS, NUM_STAGES};
pub const TRANSITION_SECONDS: f64 = 0.035;
pub struct DualCascade {
    a: Cascade,
    b: Cascade,
    current: Option<CornerData>,
    incoming: Option<CornerData>,
    pending: Option<CornerData>,
    fade_pos: usize,
    fade_len: usize,
}
impl DualCascade {
    pub fn new() -> Self {
        Self {
            a: Cascade::new(),
            b: Cascade::new(),
            current: None,
            incoming: None,
            pending: None,
            fade_pos: 0,
            fade_len: 1,
        }
    }
    pub fn set_fade_len(&mut self, samples: usize) {
        self.fade_len = samples.max(1);
    }
    pub fn reset(&mut self) {
        self.a.reset();
        self.b.reset();
        self.incoming = None;
        self.pending = None;
        self.fade_pos = 0;
    }
    pub fn set_target(&mut self, corner: &CornerData) {
        if let Some(incoming) = &self.incoming {
            if incoming == corner {
                self.pending = None;
            } else {
                self.pending = Some(*corner);
            }
            return;
        }
        if self.current.as_ref() == Some(corner) {
            return;
        }
        if self.current.is_none() {
            self.a.snap_targets(corner);
            self.current = Some(*corner);
            return;
        }
        self.b.reset();
        self.b.snap_targets(corner);
        self.incoming = Some(*corner);
        self.fade_pos = 0;
    }
    #[inline]
    pub fn tick(&mut self, x: f32) -> f32 {
        let ya = self.a.tick(x);
        if self.incoming.is_none() {
            return ya;
        }
        let yb = self.b.tick(x);
        self.fade_pos += 1;
        let t = (self.fade_pos as f64 / self.fade_len as f64).min(1.0);
        let theta = t * std::f64::consts::FRAC_PI_2;
        let y = (theta.cos() * ya as f64 + theta.sin() * yb as f64) as f32;
        if self.fade_pos >= self.fade_len {
            std::mem::swap(&mut self.a, &mut self.b);
            self.current = self.incoming.take();
            if let Some(next) = self.pending.take() {
                self.set_target(&next);
            }
        }
        y
    }
    pub fn take_instability_flag(&mut self) -> bool {
        let ia = self.a.take_instability_flag();
        let ib = self.b.take_instability_flag();
        ia || ib
    }
    pub fn get_coeffs(&self, out: &mut [[f64; NUM_COEFFS]; NUM_STAGES]) {
        if self.incoming.is_some() {
            self.b.get_coeffs(out);
        } else {
            self.a.get_coeffs(out);
        }
    }
}
impl Default for DualCascade {
    fn default() -> Self {
        Self::new()
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    const RESONANT: CornerData = [
        [0.90, -0.20, 0.08, -0.72, 0.20],
        [1.05, 0.12, -0.04, -0.51, 0.15],
        [0.82, 0.25, 0.10, -0.93, 0.36],
        [1.00, -0.08, 0.03, -0.30, 0.08],
        [0.76, 0.18, 0.06, -1.10, 0.49],
        [1.0, 0.0, 0.0, 0.0, 0.0],
    ];
    const TILT: CornerData = [
        [0.70, 0.10, 0.02, -0.40, 0.10],
        [1.10, -0.15, 0.05, -0.60, 0.22],
        [0.95, 0.05, -0.02, -0.20, 0.05],
        [1.0, 0.0, 0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0, 0.0, 0.0],
    ];
    fn sine(n: usize) -> Vec<f32> {
        (0..n)
            .map(|i| (std::f32::consts::TAU * 620.0 * i as f32 / 39_062.5).sin() * 0.25)
            .collect()
    }
    fn frozen_reference(corner: &CornerData, input: &[f32]) -> Vec<f32> {
        let mut c = Cascade::new();
        c.snap_targets(corner);
        input.iter().map(|&x| c.tick(x)).collect()
    }
    #[test]
    fn first_target_snaps_and_matches_frozen_cascade() {
        let input = sine(2048);
        let mut dual = DualCascade::new();
        dual.set_fade_len(1367);
        dual.set_target(&RESONANT);
        let got: Vec<f32> = input.iter().map(|&x| dual.tick(x)).collect();
        assert_eq!(got, frozen_reference(&RESONANT, &input));
    }
    #[test]
    fn repeated_target_is_a_no_op() {
        let input = sine(2048);
        let mut dual = DualCascade::new();
        dual.set_fade_len(1367);
        dual.set_target(&RESONANT);
        let got: Vec<f32> = input
            .iter()
            .enumerate()
            .map(|(i, &x)| {
                if i % 32 == 0 {
                    dual.set_target(&RESONANT);
                }
                dual.tick(x)
            })
            .collect();
        assert_eq!(got, frozen_reference(&RESONANT, &input));
    }
    #[test]
    fn fade_settles_to_target_steady_state() {
        let n = 39_062;
        let input = sine(n);
        let fade = 1367usize;
        let mut dual = DualCascade::new();
        dual.set_fade_len(fade);
        dual.set_target(&RESONANT);
        let mut out = Vec::with_capacity(n);
        for (i, &x) in input.iter().enumerate() {
            if i == 8192 {
                dual.set_target(&TILT);
            }
            out.push(dual.tick(x));
        }
        let reference = frozen_reference(&TILT, &input);
        let settle = 8192 + fade + 8000;
        let err: f32 = out[settle..]
            .iter()
            .zip(&reference[settle..])
            .map(|(g, r)| (g - r).abs())
            .fold(0.0, f32::max);
        assert!(err < 1e-4, "steady-state error after fade: {err}");
        assert!(!dual.take_instability_flag());
    }
    #[test]
    fn mid_fade_targets_latch_latest_and_chain() {
        let n = 16_384;
        let input = sine(n);
        let fade = 512usize;
        let mut dual = DualCascade::new();
        dual.set_fade_len(fade);
        dual.set_target(&RESONANT);
        let mut out = Vec::with_capacity(n);
        for (i, &x) in input.iter().enumerate() {
            if i == 4096 {
                dual.set_target(&TILT);
            }
            if i == 4200 {
                dual.set_target(&RESONANT);
            }
            out.push(dual.tick(x));
        }
        let reference = frozen_reference(&RESONANT, &input);
        let settle = 4096 + 2 * fade + 8000;
        let err: f32 = out[settle..]
            .iter()
            .zip(&reference[settle..])
            .map(|(g, r)| (g - r).abs())
            .fold(0.0, f32::max);
        assert!(err < 1e-4, "latched fade did not return home: {err}");
    }
    #[test]
    fn returning_to_incoming_mid_fade_clears_pending() {
        let mut dual = DualCascade::new();
        dual.set_fade_len(512);
        dual.set_target(&RESONANT);
        dual.set_target(&TILT);
        dual.set_target(&RESONANT);
        dual.set_target(&TILT);
        for _ in 0..600 {
            dual.tick(0.0);
        }
        assert_eq!(dual.current, Some(TILT));
        assert!(dual.incoming.is_none() && dual.pending.is_none());
    }
}
