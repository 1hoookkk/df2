use crate::agc::{active_agc_table, agc_step_stereo};
use crate::cartridge::{Cartridge, CornerData};
use crate::cascade::{Cascade, BLOCK_SIZE, NUM_COEFFS};
use crate::cvsd_input::CvsdInput;
use crate::desk_drive::{DeskDrive, SUPPORTED_MODEL as DESK_SLAM_MODEL};
use crate::qsound_spatial::QSoundSpatial;
use crate::trench_matrix::TrenchMatrix;
use std::ptr;
use std::sync::atomic::{AtomicPtr, Ordering};
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SpatialMode {
    QSound,
    Trench,
    Off,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InputMode {
    None,
    MackieDeskSlam,
    Cvsd,
}
#[derive(Debug, Clone, Copy)]
struct DcBlocker {
    x_prev: f32,
    y_prev: f32,
    r: f32,
}
impl DcBlocker {
    fn new(sample_rate: f64) -> Self {
        let fc = 20.0_f64;
        let r = 1.0 - (2.0 * std::f64::consts::PI * fc / sample_rate);
        Self {
            x_prev: 0.0,
            y_prev: 0.0,
            r: r as f32,
        }
    }
    #[inline(always)]
    fn process(&mut self, x: f32) -> f32 {
        let y = x - self.x_prev + self.r * self.y_prev;
        self.x_prev = x;
        self.y_prev = if y.is_finite() { y } else { 0.0 };
        self.y_prev
    }
}
#[derive(Debug, Clone, Copy)]
pub struct DebugToggles {
    pub agc_enabled: bool,
    pub dc_block_enabled: bool,
    pub saturation_enabled: bool,
    pub spatial_enabled: bool,
    pub agc_rate_scale: f32,
    pub agc_max_cut_db: f32,
    pub agc_bypass: bool,
    pub agc_makeup_gain: f32,
    pub coeff_ramp_scale: f32,
}
impl Default for DebugToggles {
    fn default() -> Self {
        Self {
            agc_enabled: true,
            dc_block_enabled: true,
            saturation_enabled: true,
            spatial_enabled: true,
            agc_rate_scale: 1.0,
            agc_max_cut_db: f32::INFINITY,
            agc_bypass: false,
            agc_makeup_gain: 1.0,
            coeff_ramp_scale: 1.0,
        }
    }
}
pub const WIDTH_GUARD_LO_HZ: f64 = 2_000.0;
pub const WIDTH_GUARD_HI_HZ: f64 = 18_980.0;
/// Dry-copy capacity reserved for the width guard, so the audio thread never
/// allocates. Comfortably above any real host block size.
const WIDTH_GUARD_MAX_BLOCK: usize = 8192;
#[derive(Debug, Clone, Copy, Default)]
struct GuardBiquad {
    b0: f32, b1: f32, b2: f32, a1: f32, a2: f32, w1: f32, w2: f32,
}
impl GuardBiquad {
    fn high_pass(hz: f64, sr: f64) -> Self {
        let w0 = 2.0 * std::f64::consts::PI * hz.min(sr * 0.45) / sr;
        let (c, s) = (w0.cos(), w0.sin());
        let al = s / std::f64::consts::SQRT_2;
        let a0 = 1.0 + al;
        Self {
            b0: (((1.0 + c) * 0.5) / a0) as f32,
            b1: ((-(1.0 + c)) / a0) as f32,
            b2: (((1.0 + c) * 0.5) / a0) as f32,
            a1: ((-2.0 * c) / a0) as f32,
            a2: ((1.0 - al) / a0) as f32,
            w1: 0.0, w2: 0.0,
        }
    }
    fn low_pass(hz: f64, sr: f64) -> Self {
        let w0 = 2.0 * std::f64::consts::PI * hz.min(sr * 0.45) / sr;
        let (c, s) = (w0.cos(), w0.sin());
        let al = s / std::f64::consts::SQRT_2;
        let a0 = 1.0 + al;
        Self {
            b0: (((1.0 - c) * 0.5) / a0) as f32,
            b1: (((1.0 - c)) / a0) as f32,
            b2: (((1.0 - c) * 0.5) / a0) as f32,
            a1: ((-2.0 * c) / a0) as f32,
            a2: ((1.0 - al) / a0) as f32,
            w1: 0.0, w2: 0.0,
        }
    }
    #[inline]
    fn process(&mut self, x: f32) -> f32 {
        let y = self.b0 * x + self.w1;
        self.w1 = self.b1 * x - self.a1 * y + self.w2;
        self.w2 = self.b2 * x - self.a2 * y;
        if y.is_finite() { y } else { self.w1 = 0.0; self.w2 = 0.0; 0.0 }
    }
    fn reset(&mut self) { self.w1 = 0.0; self.w2 = 0.0; }
}
// ---- output stage, reworked 2026-07-27 (RE-vault-authentic chain, probe cond G) ----
//
// AGC drive. The reverse-engineered DLL path (ref/ghidra_extracts/runtime_hacks.md,
// "AGC Processing") feeds the leveller the raw sample magnitude: there is no
// pre-scale, and the extract says so explicitly ("the repo's agc_drive pre-scale is
// an authoring and audition control, not part of the observed DLL path"). The old
// default was AGC_FIRST_TOOTH (2.0) / old SATURATE_KNEE (0.9) = 2.2222 — a number we
// invented so the leveller would hand the output tanh a signal already sitting on
// its knee. That made the tanh a tone stage. Default is now unity; set_agc_drive()
// survives as the authoring/audition hook (still clamped to >= 1.0).
pub const AGC_DRIVE: f32 = 1.0;
// No fixed broadband trim lives here. SCALE owns the body's authored level and
// the AGC may reduce only genuinely hot signal. A former -6.5 dB reference-match
// trim made every body quiet before the plugin's separately calibrated SLAM stage.
// saturate() is a SAFETY NET, not a tone stage.
const SATURATE_KNEE: f32 = 4.0; // +12.0 dBFS
const SATURATE_CEILING: f32 = 8.0; // +18.1 dBFS asymptote
pub const COEFF_RAMP_SECONDS: f64 = 0.080;
const KEY_SNAP_MINOR_DEGREES: [i32; 7] = [0, 2, 3, 5, 7, 8, 10];
const KEY_SNAP_MAJOR_DEGREES: [i32; 7] = [0, 2, 4, 5, 7, 9, 11];
fn key_snap_spec(choice: i32) -> Option<(i32, &'static [i32; 7])> {
    match choice {
        1..=12 => Some((choice - 1, &KEY_SNAP_MINOR_DEGREES)),
        13..=24 => Some((choice - 13, &KEY_SNAP_MAJOR_DEGREES)),
        _ => None,
    }
}
fn conjugate_pair_hz(c1: f64, c2: f64, sample_rate: f64) -> Option<f64> {
    let discriminant = c1 * c1 - 4.0 * c2;
    if discriminant >= 0.0 || c2 <= 1.0e-18 {
        return None;
    }
    let radius = c2.sqrt();
    let angle = (-c1 / (2.0 * radius)).clamp(-1.0, 1.0).acos();
    Some(angle * sample_rate / core::f64::consts::TAU)
}
fn transpose_conjugate_pair(c1: f64, c2: f64, sample_rate: f64, ratio: f64) -> f64 {
    let Some(hz) = conjugate_pair_hz(c1, c2, sample_rate) else {
        return c1;
    };
    let radius = c2.sqrt();
    let moved_hz = (hz * ratio).clamp(20.0, 0.49 * sample_rate);
    -2.0 * radius * (core::f64::consts::TAU * moved_hz / sample_rate).cos()
}
fn nearest_scale_hz(hz: f64, tonic: i32, degrees: &[i32; 7]) -> f64 {
    let midi = 69.0 + 12.0 * (hz / 440.0).log2();
    let centre = midi.round() as i32;
    let mut best_note = centre;
    let mut best_distance = f64::INFINITY;
    for note in (centre - 12)..=(centre + 12) {
        let pitch_class = note.rem_euclid(12);
        let degree = (pitch_class - tonic).rem_euclid(12);
        if !degrees.contains(&degree) {
            continue;
        }
        let distance = (note as f64 - midi).abs();
        if distance < best_distance - 1.0e-12
            || ((distance - best_distance).abs() <= 1.0e-12 && note < best_note)
        {
            best_note = note;
            best_distance = distance;
        }
    }
    440.0 * 2.0_f64.powf((best_note as f64 - 69.0) / 12.0)
}
fn snap_stage_to_key(stage: &mut [f64; NUM_COEFFS], sample_rate: f64, choice: i32) {
    let Some((tonic, degrees)) = key_snap_spec(choice) else {
        return;
    };
    let Some(pole_hz) = conjugate_pair_hz(stage[3], stage[4], sample_rate) else {
        return;
    };
    let ratio = nearest_scale_hz(pole_hz, tonic, degrees) / pole_hz;
    stage[3] = transpose_conjugate_pair(stage[3], stage[4], sample_rate, ratio);
    let b0 = stage[0];
    if b0.abs() > 1.0e-12 {
        stage[1] = transpose_conjugate_pair(stage[1] / b0, stage[2] / b0, sample_rate, ratio) * b0;
    }
}
#[inline]
pub(crate) fn saturate(x: f32) -> f32 {
    let a = x.abs();
    if a <= SATURATE_KNEE {
        x
    } else {
        let span = SATURATE_CEILING - SATURATE_KNEE;
        x.signum() * (SATURATE_KNEE + span * ((a - SATURATE_KNEE) / span).tanh())
    }
}
pub struct FilterEngine {
    cascade_l: Cascade,
    cascade_r: Cascade,
    coeff_ramp_samples: usize,
    control_phase: usize,
    cartridge: Option<Box<Cartridge>>,
    sample_rate: f64,
    output_gain: f32,
    target_output_gain: f32,
    delta_output_gain: f32,
    pre_drive_gain: f32,
    slam_drive: f32,
    target_slam_drive: f32,
    delta_slam_drive: f32,
    target_interstage_drive: f32,
    target_pole_distortion: f32,
    input_mode: InputMode,
    desk_drive_configured: bool,
    desk_drive_l: DeskDrive,
    desk_drive_r: DeskDrive,
    cvsd_l: CvsdInput,
    cvsd_r: CvsdInput,
    agc_gain: f32,
    agc_mix: f32,
    active_agc_table: [f32; 16],
    agc_drive: f32,
    dc_blocker_l: DcBlocker,
    dc_blocker_r: DcBlocker,
    spatial: QSoundSpatial,
    pub trench_matrix: TrenchMatrix,
    spatial_mode: SpatialMode,
    width_dry_l: Vec<f32>,
    width_dry_r: Vec<f32>,
    width_hp_l: GuardBiquad,
    width_lp_l: GuardBiquad,
    width_hp_r: GuardBiquad,
    width_lp_r: GuardBiquad,
    space: f32,
    amount: f32,
    pitch_ratio: f64,
    key_snap: i32,
    pub debug: DebugToggles,
}
impl Default for FilterEngine {
    fn default() -> Self {
        Self::new()
    }
}
impl FilterEngine {
    pub fn new() -> Self {
        let sr = 44100.0;
        Self {
            cascade_l: Cascade::new(),
            cascade_r: Cascade::new(),
            coeff_ramp_samples: BLOCK_SIZE,
            control_phase: 0,
            cartridge: None,
            sample_rate: sr,
            output_gain: 1.0,
            target_output_gain: 1.0,
            delta_output_gain: 0.0,
            pre_drive_gain: 1.0,
            slam_drive: 0.0,
            target_slam_drive: 0.0,
            delta_slam_drive: 0.0,
            target_interstage_drive: 0.0,
            target_pole_distortion: 0.0,
            input_mode: InputMode::None,
            desk_drive_configured: false,
            desk_drive_l: DeskDrive::new(),
            desk_drive_r: DeskDrive::new(),
            cvsd_l: CvsdInput::new(),
            cvsd_r: CvsdInput::new(),
            agc_gain: 1.0,
            agc_mix: 1.0,
            active_agc_table: active_agc_table(sr),
            agc_drive: AGC_DRIVE,
            dc_blocker_l: DcBlocker::new(sr),
            dc_blocker_r: DcBlocker::new(sr),
            spatial: QSoundSpatial::new(sr as f32),
            trench_matrix: TrenchMatrix::new(sr as f32),
            spatial_mode: SpatialMode::Off,
            width_dry_l: Vec::new(),
            width_dry_r: Vec::new(),
            width_hp_l: GuardBiquad::default(),
            width_lp_l: GuardBiquad::default(),
            width_hp_r: GuardBiquad::default(),
            width_lp_r: GuardBiquad::default(),
            space: 0.0,
            amount: 1.0,
            pitch_ratio: 1.0,
            key_snap: 0,
            debug: DebugToggles::default(),
        }
    }
    pub fn sample_rate(&self) -> f64 {
        self.sample_rate
    }
    pub fn prepare(&mut self, sample_rate: f64) {
        self.sample_rate = sample_rate;
        self.control_phase = 0;
        // The width guard copies the dry block into these on the AUDIO thread.
        // Reserve here or the first block with SPACE > 0 allocates under the
        // real-time deadline. clear() keeps capacity, so after this they never
        // grow again; an oversized block guards only what fits rather than
        // allocating (apply_width_guard already clamps to the shorter length).
        self.width_dry_l.reserve(WIDTH_GUARD_MAX_BLOCK);
        self.width_dry_r.reserve(WIDTH_GUARD_MAX_BLOCK);
        self.coeff_ramp_samples =
            ((COEFF_RAMP_SECONDS * sample_rate).round() as usize).max(BLOCK_SIZE);
        self.cascade_l.reset();
        self.cascade_r.reset();
        self.width_hp_l = GuardBiquad::high_pass(WIDTH_GUARD_LO_HZ, sample_rate);
        self.width_hp_r = GuardBiquad::high_pass(WIDTH_GUARD_LO_HZ, sample_rate);
        self.width_lp_l = GuardBiquad::low_pass(WIDTH_GUARD_HI_HZ, sample_rate);
        self.width_lp_r = GuardBiquad::low_pass(WIDTH_GUARD_HI_HZ, sample_rate);
        self.width_hp_l.reset();
        self.width_hp_r.reset();
        self.width_lp_l.reset();
        self.width_lp_r.reset();
        self.output_gain = 1.0;
        self.target_output_gain = 1.0;
        self.delta_output_gain = 0.0;
        self.slam_drive = 0.0;
        self.target_slam_drive = 0.0;
        self.delta_slam_drive = 0.0;
        self.target_interstage_drive = 0.0;
        self.target_pole_distortion = 0.0;
        self.input_mode = InputMode::None;
        self.desk_drive_configured = false;
        self.desk_drive_l.prepare(sample_rate as f32);
        self.desk_drive_r.prepare(sample_rate as f32);
        self.cvsd_l.prepare(sample_rate as f32);
        self.cvsd_r.prepare(sample_rate as f32);
        self.agc_gain = 1.0;
        self.active_agc_table = active_agc_table(sample_rate);
        self.dc_blocker_l = DcBlocker::new(sample_rate);
        self.dc_blocker_r = DcBlocker::new(sample_rate);
        self.spatial = QSoundSpatial::new(sample_rate as f32);
        self.spatial.reset();
        self.trench_matrix = TrenchMatrix::new(sample_rate as f32);
    }
    pub fn set_spatial_mode(&mut self, mode: SpatialMode) {
        self.spatial_mode = mode;
    }
    pub fn spatial_mode(&self) -> SpatialMode {
        self.spatial_mode
    }
    pub fn load_cartridge(&mut self, cart: Cartridge) {
        let _ = self.install_cartridge(Box::new(cart));
    }
    fn install_cartridge(&mut self, cart: Box<Cartridge>) -> Option<Box<Cartridge>> {
        self.pre_drive_gain = 10.0_f32.powf(cart.drive.input_gain_db / 20.0);
        self.spatial.clear_profile();
        self.cartridge.replace(cart)
    }
    pub fn set_space(&mut self, space: f32) {
        self.space = space.clamp(0.0, 1.0);
    }
    pub fn set_qsound_fallback_pan(&mut self, pan: f32) {
        self.spatial.set_fallback_pan(pan);
    }
    pub fn set_slam_drive(&mut self, drive: f32) {
        self.target_slam_drive = drive.clamp(0.0, 1.0);
    }
    /// Authentic E-MU pole-radius distortion (US 10,514,883). Sets the THRESHOLD at
    /// which each section's own resonance starts pushing its pole toward the unit
    /// circle. Distinct from interstage drive, which is a modern saturator.
    pub fn set_pole_distortion(&mut self, amount: f32) {
        self.target_pole_distortion = if amount.is_finite() { amount.clamp(0.0, 1.0) } else { 0.0 };
    }
    pub fn set_interstage_drive(&mut self, drive: f32) {
        self.target_interstage_drive = if drive.is_finite() { drive.clamp(0.0, 1.0) } else { 0.0 };
    }
    pub fn set_amount(&mut self, amount: f32) {
        self.amount = amount.clamp(0.0, 1.0);
    }
    pub fn set_pitch_ratio(&mut self, ratio: f32) {
        self.pitch_ratio = (ratio as f64).clamp(0.5, 2.0);
    }
    pub fn set_key_snap(&mut self, choice: i32) {
        self.key_snap = choice.clamp(0, 24);
    }
    pub fn set_agc_drive(&mut self, drive: f32) {
        self.agc_drive = drive.max(1.0);
    }
    pub fn set_input_mode(&mut self, mode: InputMode) {
        if self.input_mode != mode {
            self.input_mode = mode;
            self.desk_drive_l.reset();
            self.desk_drive_r.reset();
            self.cvsd_l.reset();
            self.cvsd_r.reset();
        }
    }
    fn set_parameters(&mut self, morph: f64, q: f64, chunk_size: usize) {
        let cart = match &self.cartridge {
            Some(c) => c,
            None => return,
        };
        let corner: CornerData = cart.interpolate(morph, q);
        let mut boost = cart.interpolate_boost(morph, q) as f32;
        let corner = if self.key_snap != 0 {
            let mut snapped = corner;
            for stage in snapped.iter_mut() {
                snap_stage_to_key(stage, self.sample_rate, self.key_snap);
            }
            snapped
        } else {
            corner
        };
        let corner = if (self.pitch_ratio - 1.0).abs() > 1.0e-9 {
            let sr = self.sample_rate;
            let ratio = self.pitch_ratio;
            let mut t = corner;
            for stage in t.iter_mut() {
                stage[3] = transpose_conjugate_pair(stage[3], stage[4], sr, ratio);
                let b0 = stage[0];
                if b0.abs() > 1.0e-12 {
                    stage[1] = transpose_conjugate_pair(stage[1] / b0, stage[2] / b0, sr, ratio) * b0;
                }
            }
            t
        } else {
            corner
        };
        let corner = if self.amount < 1.0 {
            let k = self.amount as f64;
            boost = boost.powf(self.amount);
            let mut blended = corner;
            for stage in blended.iter_mut() {
                let b0 = stage[0];
                let b0k = if b0 > 0.0 { b0.powf(k) } else { k * b0 + (1.0 - k) };
                let ratio = if b0.abs() > 1.0e-12 { b0k / b0 } else { 0.0 };
                let a2 = stage[4];
                let g = if a2 > 1.0e-9 {
                    a2.powf(0.5 * (1.0 / k.max(1.0e-3) - 1.0)).min(1.0)
                } else {
                    k
                };
                stage[1] *= g * ratio;
                stage[2] *= g * g * ratio;
                stage[0] = b0k;
                stage[3] *= g;
                stage[4] *= g * g;
            }
            let peak_full = compute_cascade_peak(&corner, self.sample_rate).max(1.0e-6);
            let peak_blended = compute_cascade_peak(&blended, self.sample_rate).max(1.0e-6);
            let expected_db = k as f32 * 20.0 * peak_full.log10();
            let actual_db = 20.0 * peak_blended.log10();
            boost *= 10.0_f32.powf((expected_db - actual_db) / 20.0);
            blended
        } else {
            corner
        };
        let ramp = chunk_size.max(BLOCK_SIZE);
        self.cascade_l.set_targets(&corner, ramp);
        self.cascade_r.set_targets(&corner, ramp);
        self.target_output_gain = boost;
        self.delta_output_gain = (boost - self.output_gain) / ramp as f32;
        self.delta_slam_drive = (self.target_slam_drive - self.slam_drive) / ramp as f32;
        self.cascade_l.set_interstage_drive(self.target_interstage_drive, ramp);
        self.cascade_r.set_interstage_drive(self.target_interstage_drive, ramp);
        self.cascade_l.set_pole_distortion(self.target_pole_distortion, ramp);
        self.cascade_r.set_pole_distortion(self.target_pole_distortion, ramp);
    }
    #[inline]
    fn process_input_stage(&mut self, l: f32, r: f32) -> (f32, f32) {
        match self.input_mode {
            InputMode::None => (l, r),
            InputMode::MackieDeskSlam => (
                self.desk_drive_l.process(l, self.slam_drive),
                self.desk_drive_r.process(r, self.slam_drive),
            ),
            InputMode::Cvsd => (self.cvsd_l.process(l), self.cvsd_r.process(r)),
        }
    }
    fn configure_desk_drive(&mut self) {
        if !self.desk_drive_configured {
            self.desk_drive_l.configure(DESK_SLAM_MODEL);
            self.desk_drive_r.configure(DESK_SLAM_MODEL);
            self.desk_drive_configured = true;
        }
    }
    #[inline]
    fn process_sample_inner(&mut self, l: f32, r: f32) -> (f32, f32) {
        let (mut sl, mut sr) = self.process_input_stage(l, r);
        self.slam_drive += self.delta_slam_drive;
        sl *= self.pre_drive_gain;
        sr *= self.pre_drive_gain;
        sl = self.cascade_l.tick(sl);
        sr = self.cascade_r.tick(sr);
        if self.debug.agc_enabled {
            if self.debug.agc_bypass {
                let mk = self.debug.agc_makeup_gain;
                sl += (sl * mk - sl) * self.agc_mix;
                sr += (sr * mk - sr) * self.agc_mix;
            } else if self.debug.agc_rate_scale == 1.0 && self.debug.agc_max_cut_db == f32::INFINITY
            {
                let d = self.agc_drive;
                let (agc_l, agc_r) =
                    agc_step_stereo(sl * d, sr * d, &mut self.agc_gain, &self.active_agc_table);
                let agc_l = agc_l / d;
                let agc_r = agc_r / d;
                sl += (agc_l - sl) * self.agc_mix;
                sr += (agc_r - sr) * self.agc_mix;
            } else {
                let d = self.agc_drive;
                let mag = (sl * d).abs().max((sr * d).abs());
                let idx = ((self.agc_gain * mag) as u32 & 0xF) as usize;
                let mut step = self.active_agc_table[idx];
                if self.debug.agc_rate_scale != 1.0 {
                    step = step.powf(self.debug.agc_rate_scale);
                }
                let floor = if self.debug.agc_max_cut_db == f32::INFINITY {
                    0.0
                } else {
                    10.0_f32.powf(-self.debug.agc_max_cut_db / 20.0)
                };
                self.agc_gain = (self.agc_gain * step).clamp(floor, 1.0);
                let agc_l = sl * self.agc_gain;
                let agc_r = sr * self.agc_gain;
                sl += (agc_l - sl) * self.agc_mix;
                sr += (agc_r - sr) * self.agc_mix;
            }
        }
        self.output_gain += self.delta_output_gain;
        sl *= self.output_gain;
        sr *= self.output_gain;
        if self.debug.dc_block_enabled {
            sl = self.dc_blocker_l.process(sl);
            sr = self.dc_blocker_r.process(sr);
        }
        if self.debug.saturation_enabled {
            sl = saturate(sl);
            sr = saturate(sr);
        }
        (sl, sr)
    }
    pub fn process_block(&mut self, left: &mut [f32], right: &mut [f32], morph: f64, q: f64) {
        if self.cartridge.is_none() {
            return;
        }
        let len = left.len().min(right.len());
        for i in 0..len {
            if self.control_phase == 0 {
                let ramp = ((self.coeff_ramp_samples as f64
                    * self.debug.coeff_ramp_scale.clamp(0.0, 1.0) as f64)
                    .round() as usize)
                    .max(BLOCK_SIZE);
                self.set_parameters(morph, q, ramp);
                if self.input_mode == InputMode::MackieDeskSlam {
                    self.configure_desk_drive();
                }
            }
            let (out_l, out_r) = self.process_sample_inner(left[i], right[i]);
            left[i] = out_l;
            right[i] = out_r;
            self.control_phase += 1;
            if self.control_phase >= BLOCK_SIZE {
                self.control_phase = 0;
            }
        }
        if self.debug.spatial_enabled && self.spatial_mode != SpatialMode::Off {
            let guarded = left.len().min(right.len()).min(self.width_dry_l.capacity());
            self.width_dry_l.clear();
            self.width_dry_r.clear();
            self.width_dry_l.extend_from_slice(&left[..guarded]);
            self.width_dry_r.extend_from_slice(&right[..guarded]);
            match self.spatial_mode {
                SpatialMode::QSound => {
                    self.spatial.set_space(self.space);
                    self.spatial.process_stereo(left, right);
                }
                SpatialMode::Trench => {
                    self.trench_matrix.space = self.space;
                    self.trench_matrix.process_stereo(left, right);
                }
                SpatialMode::Off => {}
            }
            self.apply_width_guard(left, right);
        }
    }
    fn apply_width_guard(&mut self, left: &mut [f32], right: &mut [f32]) {
        let n = left.len().min(right.len()).min(self.width_dry_l.len());
        for i in 0..n {
            let (dry_l, dry_r) = (self.width_dry_l[i], self.width_dry_r[i]);
            let add_l = left[i] - dry_l;
            let add_r = right[i] - dry_r;
            let band_l = self.width_lp_l.process(self.width_hp_l.process(add_l));
            let band_r = self.width_lp_r.process(self.width_hp_r.process(add_r));
            left[i] = dry_l + band_l;
            right[i] = dry_r + band_r;
        }
    }
    pub fn take_instability_flag(&mut self) -> bool {
        self.cascade_l.take_instability_flag() || self.cascade_r.take_instability_flag()
    }
    pub fn get_coeffs_for_ui(&self, out_coeffs: &mut [[f32; 5]; 6], out_boost: &mut f32) {
        let mut d_coeffs = [[0.0f64; 5]; 6];
        self.cascade_l.get_coeffs(&mut d_coeffs);
        for (i, stage) in d_coeffs.iter().enumerate() {
            for (j, &c) in stage.iter().enumerate() {
                out_coeffs[i][j] = c as f32;
            }
        }
        *out_boost = self.output_gain;
    }
}
pub struct CartridgeMailbox {
    pending: AtomicPtr<Cartridge>,
    garbage: AtomicPtr<Cartridge>,
}
impl CartridgeMailbox {
    fn new() -> Self {
        Self {
            pending: AtomicPtr::new(ptr::null_mut()),
            garbage: AtomicPtr::new(ptr::null_mut()),
        }
    }
    pub fn stage(&self, cart: Box<Cartridge>) {
        self.reclaim();
        let prev = self.pending.swap(Box::into_raw(cart), Ordering::AcqRel);
        if !prev.is_null() {
            drop(unsafe { Box::from_raw(prev) });
        }
    }
    pub fn reclaim(&self) {
        let g = self.garbage.swap(ptr::null_mut(), Ordering::AcqRel);
        if !g.is_null() {
            drop(unsafe { Box::from_raw(g) });
        }
    }
    fn take(&self) -> Option<Box<Cartridge>> {
        if !self.garbage.load(Ordering::Acquire).is_null() {
            return None;
        }
        let p = self.pending.swap(ptr::null_mut(), Ordering::AcqRel);
        if p.is_null() {
            None
        } else {
            Some(unsafe { Box::from_raw(p) })
        }
    }
    fn retire(&self, old: Box<Cartridge>) {
        let prev = self.garbage.swap(Box::into_raw(old), Ordering::AcqRel);
        debug_assert!(
            prev.is_null(),
            "garbage slot overwritten: producer fell behind take()'s guard"
        );
        if !prev.is_null() {
            drop(unsafe { Box::from_raw(prev) });
        }
    }
}
impl Drop for CartridgeMailbox {
    fn drop(&mut self) {
        let p = self.pending.swap(ptr::null_mut(), Ordering::AcqRel);
        if !p.is_null() {
            drop(unsafe { Box::from_raw(p) });
        }
        self.reclaim();
    }
}
pub struct EngineHandle {
    pub engine: FilterEngine,
    pub mailbox: CartridgeMailbox,
}
impl EngineHandle {
    pub fn new() -> Self {
        Self {
            engine: FilterEngine::new(),
            mailbox: CartridgeMailbox::new(),
        }
    }
}
impl Default for EngineHandle {
    fn default() -> Self {
        Self::new()
    }
}
pub fn install_pending(engine: &mut FilterEngine, mailbox: &CartridgeMailbox) {
    if let Some(new_cart) = mailbox.take() {
        if let Some(old) = engine.install_cartridge(new_cart) {
            mailbox.retire(old);
        }
    }
}
fn compute_cascade_peak(corner: &CornerData, sample_rate: f64) -> f32 {
    const NUM_BINS: usize = 1024;
    let nyquist = sample_rate / 2.0;
    let mut max_mag: f64 = 0.0;
    for bin in 0..=NUM_BINS {
        let freq = nyquist * (bin as f64 / NUM_BINS as f64);
        let omega = 2.0 * std::f64::consts::PI * freq / sample_rate;
        let cos_w = omega.cos();
        let cos_2w = (2.0 * omega).cos();
        let sin_w = omega.sin();
        let sin_2w = (2.0 * omega).sin();
        let mut cascade_mag_sq: f64 = 1.0;
        for stage in corner.iter() {
            let b0 = stage[0];
            let b1 = stage[1];
            let b2 = stage[2];
            let a1 = stage[3];
            let a2 = stage[4];
            let num_real = b0 + b1 * cos_w + b2 * cos_2w;
            let num_imag = -(b1 * sin_w + b2 * sin_2w);
            let den_real = 1.0 + a1 * cos_w + a2 * cos_2w;
            let den_imag = -(a1 * sin_w + a2 * sin_2w);
            let den_mag_sq = den_real * den_real + den_imag * den_imag;
            if den_mag_sq > 1e-30 {
                let stage_mag_sq = (num_real * num_real + num_imag * num_imag) / den_mag_sq;
                cascade_mag_sq *= stage_mag_sq;
            }
        }
        let mag = cascade_mag_sq.sqrt();
        if mag > max_mag {
            max_mag = mag;
        }
    }
    max_mag as f32
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::cascade::PASSTHROUGH_COEFFS;
    fn conjugate_coefficients(hz: f64, radius: f64, sample_rate: f64) -> (f64, f64) {
        let angle = core::f64::consts::TAU * hz / sample_rate;
        (-2.0 * radius * angle.cos(), radius * radius)
    }
    #[test]
    fn manual_key_snap_removes_a_natural_from_c_minor() {
        let snapped = nearest_scale_hz(440.0, 0, &KEY_SNAP_MINOR_DEGREES);
        let expected_ab = 440.0 * 2.0_f64.powf(-1.0 / 12.0);
        assert!((snapped - expected_ab).abs() < 1.0e-9, "snapped={snapped}");
    }
    #[test]
    fn manual_key_snap_preserves_the_stage_pole_zero_interval() {
        let sample_rate = 48_000.0;
        let (b1, b2) = conjugate_coefficients(660.0, 0.82, sample_rate);
        let (a1, a2) = conjugate_coefficients(440.0, 0.96, sample_rate);
        let mut stage = [1.0, b1, b2, a1, a2];
        let before_pole = conjugate_pair_hz(stage[3], stage[4], sample_rate).unwrap();
        let before_zero = conjugate_pair_hz(stage[1], stage[2], sample_rate).unwrap();
        snap_stage_to_key(&mut stage, sample_rate, 1);
        let after_pole = conjugate_pair_hz(stage[3], stage[4], sample_rate).unwrap();
        let after_zero = conjugate_pair_hz(stage[1], stage[2], sample_rate).unwrap();
        let expected_ab = 440.0 * 2.0_f64.powf(-1.0 / 12.0);
        assert!((after_pole - expected_ab).abs() < 1.0e-8);
        assert!((after_zero / before_zero - after_pole / before_pole).abs() < 1.0e-10);
        assert!((stage[2] - b2).abs() < 1.0e-15, "zero radius changed");
        assert!((stage[4] - a2).abs() < 1.0e-15, "pole radius changed");
    }
    #[test]
    fn manual_key_snap_leaves_real_pole_rows_verbatim() {
        let mut stage = [1.0, -0.4, 0.03, -1.1, 0.28];
        let before = stage;
        snap_stage_to_key(&mut stage, 48_000.0, 1);
        assert_eq!(stage, before);
    }
    #[test]
    fn manual_key_snap_off_is_an_exact_noop() {
        let (b1, b2) = conjugate_coefficients(660.0, 0.82, 48_000.0);
        let (a1, a2) = conjugate_coefficients(440.0, 0.96, 48_000.0);
        let mut stage = [0.91, b1 * 0.91, b2 * 0.91, a1, a2];
        let before = stage;
        snap_stage_to_key(&mut stage, 48_000.0, 0);
        assert_eq!(stage, before);
    }
    fn cartridge_from_corner(name: &str, corner: CornerData) -> Cartridge {
        let mut word_corner = [[0u16; crate::cascade::NUM_COEFFS]; crate::cascade::NUM_STAGES];
        for (stage_index, biquad) in corner.iter().enumerate() {
            word_corner[stage_index] = crate::compiler::biquad_to_words(*biquad);
        }
        let packed = crate::minifloat::PackedCorners {
            words: [word_corner; 4],
        };
        Cartridge::from_body_bytes(name, &packed.to_rom_bytes(), 1.0)
            .expect("packed test cartridge")
    }
    fn make_passthrough_cartridge() -> Cartridge {
        cartridge_from_corner(
            "passthrough",
            [PASSTHROUGH_COEFFS; crate::cascade::NUM_STAGES],
        )
    }
    #[test]
    fn empty_engine_passes_buffer_through_unchanged() {
        let mut engine = FilterEngine::new();
        engine.prepare(44100.0);
        let mut l = vec![0.1_f32, -0.2, 0.3, -0.4];
        let mut r = vec![-0.5_f32, 0.6, -0.7, 0.8];
        let l_copy = l.clone();
        let r_copy = r.clone();
        engine.process_block(&mut l, &mut r, 0.0, 0.0);
        assert_eq!(l, l_copy);
        assert_eq!(r, r_copy);
    }
    #[test]
    fn passthrough_cartridge_preserves_energy() {
        let mut engine = FilterEngine::new();
        engine.prepare(44100.0);
        engine.load_cartridge(make_passthrough_cartridge());
        let mut l = vec![0.0_f32; 256];
        let mut r = vec![0.0_f32; 256];
        l[0] = 1.0;
        r[0] = 1.0;
        let input_sum_sq: f32 =
            l.iter().map(|&s| s * s).sum::<f32>() + r.iter().map(|&s| s * s).sum::<f32>();
        engine.process_block(&mut l, &mut r, 0.5, 0.5);
        let output_sum_sq: f32 =
            l.iter().map(|&s| s * s).sum::<f32>() + r.iter().map(|&s| s * s).sum::<f32>();
        let expected = input_sum_sq;
        assert!(
            (output_sum_sq - expected).abs() < 0.1,
            "impulse energy drifted: in={input_sum_sq} out={output_sum_sq} \
             expected={expected}"
        );
        assert!(!engine.take_instability_flag());
    }
    #[test]
    fn prepare_installs_sample_rate_adjusted_agc_table() {
        let mut engine = FilterEngine::new();
        engine.prepare(65_000.0);
        assert_eq!(engine.active_agc_table, active_agc_table(65_000.0));
        engine.prepare(65_000.1);
        assert_eq!(engine.active_agc_table, active_agc_table(65_000.1));
        engine.prepare(130_000.1);
        assert_eq!(engine.active_agc_table, active_agc_table(130_000.1));
    }
    fn make_resonant_cartridge() -> Cartridge {
        let mut corner = [PASSTHROUGH_COEFFS; crate::cascade::NUM_STAGES];
        corner[0] = [0.90, -0.20, 0.08, -0.72, 0.20];
        cartridge_from_corner("resonant", corner)
    }
    #[test]
    fn amount_zero_drives_cascade_targets_to_passthrough() {
        let mut engine = FilterEngine::new();
        engine.prepare(44100.0);
        engine.load_cartridge(make_resonant_cartridge());
        engine.set_amount(0.0);
        let mut l = vec![0.0_f32; BLOCK_SIZE * 8];
        let mut r = vec![0.0_f32; BLOCK_SIZE * 8];
        engine.process_block(&mut l, &mut r, 0.5, 0.5);
        let mut coeffs = [[0.0_f64; crate::cascade::NUM_COEFFS]; crate::cascade::NUM_STAGES];
        engine.cascade_l.get_coeffs(&mut coeffs);
        for stage in coeffs.iter() {
            for (i, &c) in stage.iter().enumerate() {
                assert!(
                    (c - PASSTHROUGH_COEFFS[i]).abs() < 1e-6,
                    "amount=0 should drive every stage to passthrough, got {stage:?}"
                );
            }
        }
    }
    #[test]
    fn amount_one_leaves_cascade_targets_at_full_strength() {
        let mut engine = FilterEngine::new();
        engine.prepare(44100.0);
        let cartridge = make_resonant_cartridge();
        let expected = cartridge.interpolate(0.5, 0.5)[0];
        engine.load_cartridge(cartridge);
        engine.set_amount(1.0);
        let mut l = vec![0.0_f32; BLOCK_SIZE * 2048];
        let mut r = vec![0.0_f32; BLOCK_SIZE * 2048];
        engine.process_block(&mut l, &mut r, 0.5, 0.5);
        let mut coeffs = [[0.0_f64; crate::cascade::NUM_COEFFS]; crate::cascade::NUM_STAGES];
        engine.cascade_l.get_coeffs(&mut coeffs);
        for (i, &c) in coeffs[0].iter().enumerate() {
            assert!(
                (c - expected[i]).abs() < 1e-6,
                "amount=1 should leave stage 0 at full strength, got {:?}",
                coeffs[0]
            );
        }
    }
    #[test]
    fn amount_actually_changes_the_processed_output() {
        let mut full = FilterEngine::new();
        full.prepare(44100.0);
        full.load_cartridge(make_resonant_cartridge());
        full.set_amount(1.0);
        let mut flat = FilterEngine::new();
        flat.prepare(44100.0);
        flat.load_cartridge(make_resonant_cartridge());
        flat.set_amount(0.0);
        let make_input = || {
            let mut l = vec![0.0_f32; BLOCK_SIZE * 16];
            let mut r = vec![0.0_f32; BLOCK_SIZE * 16];
            for i in 0..l.len() {
                l[i] = 0.3 * ((i as f32) * 0.05).sin();
                r[i] = l[i];
            }
            (l, r)
        };
        let (mut l1, mut r1) = make_input();
        full.process_block(&mut l1, &mut r1, 0.5, 0.5);
        let (mut l0, mut r0) = make_input();
        flat.process_block(&mut l0, &mut r0, 0.5, 0.5);
        let tail = BLOCK_SIZE * 4;
        let diff: f32 = l1[tail..]
            .iter()
            .zip(l0[tail..].iter())
            .map(|(a, b)| (a - b).abs())
            .sum();
        assert!(
            diff > 0.5,
            "amount=1 vs amount=0 output should clearly differ, diff={diff}"
        );
        assert!(!full.take_instability_flag());
        assert!(!flat.take_instability_flag());
    }
    #[test]
    fn amount_tapers_the_cascade_peak_smoothly_and_monotonically() {
        let steps = [1.0f32, 0.75, 0.5, 0.25, 0.0];
        let mut peaks_db = Vec::new();
        for &amt in &steps {
            let mut engine = FilterEngine::new();
            engine.prepare(44100.0);
            engine.load_cartridge(make_resonant_cartridge());
            engine.set_amount(amt);
            let mut l = vec![0.0_f32; BLOCK_SIZE * 2048];
            let mut r = vec![0.0_f32; BLOCK_SIZE * 2048];
            engine.process_block(&mut l, &mut r, 0.5, 0.5);
            let mut coeffs = [[0.0_f64; NUM_COEFFS]; crate::cascade::NUM_STAGES];
            engine.cascade_l.get_coeffs(&mut coeffs);
            let peak = compute_cascade_peak(&coeffs, 44100.0);
            peaks_db.push(20.0 * peak.log10());
        }
        println!(
            "amount -> peak (dB): {:?}",
            steps.iter().zip(&peaks_db).collect::<Vec<_>>()
        );
        assert!(
            peaks_db[0] > 1.0,
            "amount=1 should show real resonance gain, got {} dB",
            peaks_db[0]
        );
        assert!(
            peaks_db[4].abs() < 0.01,
            "amount=0 should be exactly flat (0 dB), got {} dB",
            peaks_db[4]
        );
        for i in 1..peaks_db.len() {
            assert!(
                peaks_db[i] <= peaks_db[i - 1] + 0.05,
                "peak should taper monotonically as amount decreases: {:?}",
                peaks_db
            );
        }
    }
    #[test]
    fn num_coeffs_matches_corner_shape() {
        use crate::cascade::{NUM_COEFFS, NUM_STAGES};
        let _: [[f64; NUM_COEFFS]; NUM_STAGES] = [[0.0; NUM_COEFFS]; NUM_STAGES];
    }
    #[test]
    fn agc_drive_unity_is_identity_higher_compresses() {
        fn run(drive: f32) -> f32 {
            let mut eng = FilterEngine::new();
            eng.prepare(44_100.0);
            eng.load_cartridge(make_passthrough_cartridge());
            eng.debug.saturation_enabled = false;
            eng.debug.dc_block_enabled = false;
            eng.set_agc_drive(drive);
            let mut l = vec![0.7f32; 512];
            let mut r = l.clone();
            eng.process_block(&mut l, &mut r, 0.5, 0.5);
            let tail = &l[128..];
            (tail.iter().map(|s| s * s).sum::<f32>() / tail.len() as f32).sqrt()
        }
        let unity = run(1.0);
        let driven = run(8.0);
        // Unity is the shipped default: the AGC is asleep and the core is
        // broadband-unity for a passthrough body.
        let expected = 0.7;
        assert!(
            (unity - expected).abs() < 0.02,
            "unity drive must pass {expected} untouched (AGC asleep in float domain), got {unity}"
        );
        assert!(
            driven < unity * 0.85,
            "agc_drive=8 must visibly compress; got driven={driven} vs unity={unity}"
        );
    }
    #[test]
    #[ignore = "renders audition WAVs to target/agc_audition"]
    fn render_agc_audition() {
        use crate::cartridge::Cartridge;
        const BODY: &[u8; 240] = include_bytes!("../tests/fixtures/sf_mouth_frame.body240");
        let bytes = BODY.as_slice();
        let out = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("target/agc_audition");
        std::fs::create_dir_all(&out).expect("mkdir out");
        let sr_emu = 39_062.5f64;
        let out_sr = 48_000u32;
        let secs = 6.0f64;
        let total = (sr_emu * secs) as usize;
        let block = 256usize;
        let write_wav = |path: &std::path::Path, samples: &[f32]| {
            let data_len = (samples.len() * 2) as u32;
            let mut b: Vec<u8> = Vec::with_capacity(44 + data_len as usize);
            b.extend_from_slice(b"RIFF");
            b.extend_from_slice(&(36 + data_len).to_le_bytes());
            b.extend_from_slice(b"WAVE");
            b.extend_from_slice(b"fmt ");
            b.extend_from_slice(&16u32.to_le_bytes());
            b.extend_from_slice(&1u16.to_le_bytes());
            b.extend_from_slice(&1u16.to_le_bytes());
            b.extend_from_slice(&out_sr.to_le_bytes());
            b.extend_from_slice(&(out_sr * 2).to_le_bytes());
            b.extend_from_slice(&2u16.to_le_bytes());
            b.extend_from_slice(&16u16.to_le_bytes());
            b.extend_from_slice(b"data");
            b.extend_from_slice(&data_len.to_le_bytes());
            for &s in samples {
                b.extend_from_slice(&((s.clamp(-1.0, 1.0) * 32767.0) as i16).to_le_bytes());
            }
            std::fs::write(path, b).expect("write wav");
        };
        for &drive in &[1.0f32, 4.0, 8.0] {
            let mut eng = FilterEngine::new();
            eng.prepare(sr_emu);
            eng.load_cartridge(Cartridge::from_body_bytes("cleanroom", bytes, 1.0).unwrap());
            eng.set_agc_drive(drive);
            let mut rng = 0x2545_F491_4F6C_DD1Du64;
            let mut pb = [0f64; 7];
            let mut wet: Vec<f32> = Vec::with_capacity(total);
            let mut off = 0;
            while off < total {
                let len = block.min(total - off);
                let mut l = vec![0f32; len];
                for s in l.iter_mut() {
                    rng = rng
                        .wrapping_mul(6364136223846793005)
                        .wrapping_add(1442695040888963407);
                    let white = ((rng >> 40) as f64 / (1u64 << 23) as f64) - 1.0;
                    pb[0] = 0.99886 * pb[0] + white * 0.0555179;
                    pb[1] = 0.99332 * pb[1] + white * 0.0750759;
                    pb[2] = 0.96900 * pb[2] + white * 0.1538520;
                    pb[3] = 0.86650 * pb[3] + white * 0.3104856;
                    pb[4] = 0.55000 * pb[4] + white * 0.5329522;
                    pb[5] = -0.7616 * pb[5] - white * 0.0168980;
                    let p =
                        (pb[0] + pb[1] + pb[2] + pb[3] + pb[4] + pb[5] + pb[6] + white * 0.5362)
                            * 0.11;
                    pb[6] = white * 0.115926;
                    *s = (p as f32) * 0.85;
                }
                let mut r = l.clone();
                let morph = off as f64 / total as f64;
                eng.process_block(&mut l, &mut r, morph, 0.5);
                wet.extend_from_slice(&l);
                off += len;
            }
            let ratio = sr_emu / out_sr as f64;
            let out_n = (wet.len() as f64 / ratio) as usize;
            let resampled: Vec<f32> = (0..out_n)
                .map(|i| {
                    let pos = i as f64 * ratio;
                    let i0 = pos.floor() as usize;
                    let frac = (pos - i0 as f64) as f32;
                    let a = wet.get(i0).copied().unwrap_or(0.0);
                    let bb = wet.get(i0 + 1).copied().unwrap_or(a);
                    a + (bb - a) * frac
                })
                .collect();
            let peak = resampled.iter().fold(0.0f32, |m, &s| m.max(s.abs()));
            let path = out.join(format!("cleanroom_pink_sweep_drive{drive}.wav"));
            write_wav(&path, &resampled);
            println!("wrote {} (peak {:.3})", path.display(), peak);
        }
    }
    #[test]
    #[ignore = "diagnostic: pre-AGC scale vs AGC engagement"]
    fn diag_pre_agc_scaling() {
        use crate::agc::{active_agc_table, agc_step};
        use crate::cartridge::Cartridge;
        const BODY: &[u8; 240] = include_bytes!("../tests/fixtures/sf_mouth_frame.body240");
        let bytes = BODY.as_slice();
        let mut eng = FilterEngine::new();
        eng.prepare(39_062.5);
        eng.load_cartridge(Cartridge::from_body_bytes("d", &bytes, 1.0).unwrap());
        eng.debug.agc_enabled = false;
        eng.debug.saturation_enabled = false;
        eng.debug.dc_block_enabled = false;
        let n = 39_062usize;
        let mut ph = 0.0f64;
        let mut l: Vec<f32> = (0..n)
            .map(|_| {
                let s = ((ph * 2.0 - 1.0) * 0.36) as f32 * 0.85;
                ph = (ph + 110.0 / 39_062.5).fract();
                s
            })
            .collect();
        let mut r = l.clone();
        eng.process_block(&mut l, &mut r, 0.5, 1.0);
        let cascade = &l[4096..];
        let rms = |v: &[f32]| (v.iter().map(|s| s * s).sum::<f32>() / v.len() as f32).sqrt();
        let peak = |v: &[f32]| v.iter().fold(0.0f32, |m, &s| m.max(s.abs()));
        let cas_rms = rms(cascade);
        println!(
            "\n=== clean-room raw cascade (no AGC/sat/DC), q1, in=0.85: peak={:.3} rms={:.3} ===",
            peak(cascade),
            cas_rms
        );
        println!("pre-AGC scale -> compression after rescale, min agc_gain reached");
        let agc_table = active_agc_table(39_062.5);
        for scale in [1.0f32, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0] {
            let mut gain = 1.0f32;
            let mut min_gain = 1.0f32;
            let out: Vec<f32> = cascade
                .iter()
                .map(|&s| {
                    let y = agc_step(s * scale, &mut gain, &agc_table) / scale;
                    min_gain = min_gain.min(gain);
                    y
                })
                .collect();
            let red_db = 20.0 * (rms(&out) / cas_rms).max(1e-9).log10();
            println!("  x{scale:<6} -> {red_db:>7.2} dB   min_gain={min_gain:.4}");
        }
    }
    #[test]
    #[ignore = "diagnostic: which limiter is doing the work"]
    fn diag_limiter_handoff() {
        const SR: f64 = 39_062.5;
        const TAIL: usize = 12_288;
        let run = |cycles: f64, drive: f32, agc: bool, sat: bool, amp: f32| -> Probe {
            probe_body(cycles, Some(drive), agc, sat, amp)
        };
        let mut best = (0.0f64, 0.0f32);
        for k in 1..600 {
            let c = k as f64 * 4.0;
            let p = run(c, 1.0, false, false, 1.0).peak;
            if p > best.1 {
                best = (c, p);
            }
        }
        let (cyc, hot_peak) = best;
        println!("\n=== who is limiting? (real body, q=1, island rate) ===");
        println!(
            "AGC first tooth = |x| >= 2.0 (+6.0 dBFS)   saturate() knee = {SATURATE_KNEE} \
             (+{:.1} dBFS, safety net)   fixed post-AGC trim = none",
            20.0 * SATURATE_KNEE.log10()
        );
        println!(
            "body resonance at {:.0} Hz: full-scale input -> raw peak {:.3} (+{:.1} dBFS)\n",
            SR * cyc / TAIL as f64,
            hot_peak,
            20.0 * hot_peak.log10()
        );
        println!("  in    raw_peak | STOCK (agc+sat)                | AGC only  | sat only");
        println!("                 | peak    rms    resid    agc_g  | resid     | resid");
        for &amp in &[0.4f32, 0.6, 0.8, 0.9, 1.0] {
            let raw = run(cyc, 1.0, false, false, amp).peak;
            let s = run(cyc, 1.0, true, true, amp);
            let d_agc = run(cyc, 1.0, true, false, amp).resid_dbc;
            let d_sat = run(cyc, 1.0, false, true, amp).resid_dbc;
            println!(
                "  {amp:.1}   {raw:6.3}  | {:6.3} {:6.3} {:7.1}dBc {:6.4} | {d_agc:6.1}dBc | {d_sat:6.1}dBc",
                s.peak, s.rms, s.resid_dbc, s.agc_gain
            );
        }
        println!("\n=== agc_drive sweep at full-scale input ===");
        println!("  drive   peak    rms    resid     agc_gain | attack peak (AGC alone, sat off)");
        for &drive in &[1.0f32, 1.5, 2.0, AGC_DRIVE, 3.0, 4.0] {
            let s = run(cyc, drive, true, true, 1.0);
            let attack = run(cyc, drive, true, false, 1.0).attack;
            println!(
                "  x{drive:<5.2}  {:6.3} {:6.3} {:7.1}dBc {:6.4} | {attack:8.3}",
                s.peak, s.rms, s.resid_dbc, s.agc_gain
            );
        }
    }
    #[test]
    #[ignore = "diagnostic: which of the 16 AGC teeth the shipped drive uses"]
    fn diag_agc_curve() {
        use crate::agc::active_agc_table;
        use crate::dsp::BASE_AGC_TABLE;
        const SR: f64 = 39_062.5;
        let table = active_agc_table(SR);
        assert_eq!(
            table, BASE_AGC_TABLE,
            "island rate must use the verified 16 values unmodified"
        );
        println!("\n=== the AGC curve in use at {SR} Hz (16 values, verified) ===");
        for (i, v) in table.iter().enumerate() {
            let tag = if *v >= 1.0 { "no reduction" } else { "REDUCES" };
            println!("  [{i:2}] {v:.4}   {tag}");
        }
        println!("\nindex = (agc_gain * |x| * AGC_DRIVE) as int & 0xF");
        println!(
            "AGC_DRIVE = {AGC_DRIVE:.4} (RE-vault: the DLL path has no pre-scale; the old \
             2.0/0.9 = 2.2222 default was ours)\n"
        );
        const HOT_CYCLES: f64 = 964.0;
        println!("what the leveler hands to the saturator (safety-net knee = {SATURATE_KNEE}):");
        for &(label, drive) in &[("SHIPPED (unity)", AGC_DRIVE), ("OLD  (drive 2.2222)", 2.0f32 / 0.9)]
        {
            let leveller = probe_body(HOT_CYCLES, Some(drive), true, false, 1.0);
            let shipped = probe_body(HOT_CYCLES, Some(drive), true, true, 1.0);
            let verdict = if shipped.resid_dbc > leveller.resid_dbc + 1.0 {
                "-> tanh must finish the job, and it distorts doing it"
            } else {
                "-> tanh idle, the curve owns the level"
            };
            println!(
                "  {label:16} settles at peak {:.3}  {verdict}\n{:18}distortion: {:.1} dBc leveller alone -> {:.1} dBc with the tanh",
                leveller.peak, "", leveller.resid_dbc, shipped.resid_dbc
            );
        }
    }
    #[test]
    #[ignore = "diagnostic: why morph became musical"]
    fn diag_morph_musicality() {
        use crate::cartridge::Cartridge;
        const SR: f64 = 39_062.5;
        const N: usize = 8192;
        let saw: Vec<f32> = (0..N)
            .map(|i| {
                let ph = (110.0 * i as f64 / SR).fract();
                ((ph * 2.0 - 1.0) * 0.7) as f32
            })
            .collect();
        let at = |drive: f32, morph: f64| -> (f32, f32) {
            let mut eng = FilterEngine::new();
            eng.prepare(SR);
            eng.load_cartridge(
                Cartridge::from_body_bytes(
                    "d",
                    include_bytes!("../tests/fixtures/sf_mouth_frame.body240").as_slice(),
                    1.0,
                )
                .unwrap(),
            );
            eng.set_agc_drive(drive);
            let mut l = saw.clone();
            let mut r = saw.clone();
            eng.process_block(&mut l, &mut r, morph, 1.0);
            let mut l = saw.clone();
            let mut r = saw.clone();
            eng.process_block(&mut l, &mut r, morph, 1.0);
            let peak = l.iter().fold(0.0f32, |m, &s| m.max(s.abs()));
            let rms = ((l.iter().map(|&s| (s as f64).powi(2)).sum::<f64>()) / N as f64).sqrt() as f32;
            let crest = 20.0 * (peak / rms.max(1e-9)).log10();
            (rms, crest)
        };
        println!("\n=== a morph sweep, before and after ===");
        println!("crest: 3.01 dB = a sine.  ~1 dB = a square wave (fully clipped).\n");
        println!("  morph |   OLD (drive 1.0)      |   SHIPPED");
        println!("        |   rms     crest        |   rms     crest");
        let (mut old_rms, mut new_rms) = (Vec::new(), Vec::new());
        for k in 0..=10 {
            let m = k as f64 / 10.0;
            let (o_r, o_c) = at(1.0, m);
            let (n_r, n_c) = at(AGC_DRIVE, m);
            old_rms.push(o_r);
            new_rms.push(n_r);
            println!("   {m:.1}   |  {o_r:.3}   {o_c:5.2} dB     |  {n_r:.3}   {n_c:5.2} dB");
        }
        let spread = |v: &[f32]| {
            let (lo, hi) = v.iter().fold((f32::MAX, 0.0f32), |(l, h), &x| (l.min(x), h.max(x)));
            20.0 * (hi / lo.max(1e-9)).log10()
        };
        println!(
            "\nlevel contour across the sweep:  OLD {:.2} dB   SHIPPED {:.2} dB",
            spread(&old_rms),
            spread(&new_rms)
        );
        println!("(a sweep with no level contour is a sweep you cannot feel)");
    }
    #[test]
    #[ignore = "diagnostic: is the identity body a true bypass"]
    fn diag_identity_transparency() {
        use crate::cartridge::Cartridge;
        const SR: f64 = 39_062.5;
        const N: usize = 8192;
        const IDENTITY: &[u8; 240] = include_bytes!("../../plugin/assets/bodies/identity.body240");
        let run = |amp: f32, agc: bool, sat: bool, dc: bool| -> (f32, f64) {
            let mut eng = FilterEngine::new();
            eng.prepare(SR);
            eng.load_cartridge(
                Cartridge::from_body_bytes("identity", IDENTITY.as_slice(), 1.0).unwrap(),
            );
            eng.debug.agc_enabled = agc;
            eng.debug.saturation_enabled = sat;
            eng.debug.dc_block_enabled = dc;
            let dry: Vec<f32> = (0..N)
                .map(|i| {
                    let ph = (220.0 * i as f64 / SR).fract();
                    (amp as f64 * (ph * 2.0 - 1.0)) as f32
                })
                .collect();
            let mut l = dry.clone();
            let mut r = dry.clone();
            eng.process_block(&mut l, &mut r, 0.5, 0.5);
            let resid = (l
                .iter()
                .zip(dry.iter())
                .map(|(&o, &d)| ((o - d) as f64).powi(2))
                .sum::<f64>()
                / N as f64)
                .sqrt();
            (
                l.iter().fold(0.0f32, |m, &s| m.max(s.abs())),
                20.0 * resid.max(1e-12).log10(),
            )
        };
        println!("\n=== identity body: is the CASCADE itself identity? ===");
        println!("(everything after it switched off — this is the packed body alone)");
        for &amp in &[0.3f32, 1.0] {
            let (p, d) = run(amp, false, false, false);
            let v = if d < -100.0 { "EXACT identity" } else { "NOT identity — the body is wrong" };
            println!("   in {amp:.2} -> peak {p:.4}   null {d:8.1} dBFS   {v}");
        }
        println!("\n=== which stage breaks the bypass? ===");
        println!("  in    | cascade only | +DC block | +AGC     | +saturator (full)");
        for &amp in &[0.3f32, 0.6, 0.9, 1.0] {
            let a = run(amp, false, false, false).1;
            let b = run(amp, false, false, true).1;
            let c = run(amp, true, false, true).1;
            let d = run(amp, true, true, true).1;
            println!("  {amp:.2}  | {a:9.1} dB | {b:6.1} dB | {c:6.1} dB | {d:6.1} dB");
        }
    }
    #[test]
    fn moving_morph_is_identical_at_any_buffer_size() {
        use crate::cartridge::Cartridge;
        const BODY: &[u8; 240] = include_bytes!("../tests/fixtures/sf_mouth_frame.body240");
        const N: usize = 8192;
        let render = |block: usize| -> Vec<f32> {
            let mut eng = FilterEngine::new();
            eng.prepare(39_062.5);
            eng.load_cartridge(Cartridge::from_body_bytes("d", BODY.as_slice(), 1.0).unwrap());
            let src: Vec<f32> = (0..N)
                .map(|i| ((i as f64 * 0.013).sin() * 0.4) as f32)
                .collect();
            let mut out = Vec::with_capacity(N);
            let mut off = 0;
            while off < N {
                let n = block.min(N - off);
                let mut l = src[off..off + n].to_vec();
                let mut r = l.clone();
                eng.process_block(&mut l, &mut r, 0.5, 1.0);
                out.extend_from_slice(&l);
                off += n;
            }
            out
        };
        let reference = render(512);
        for &block in &[16usize, 32, 64, 100, 128, 333, 1024] {
            let other = render(block);
            let peak = reference
                .iter()
                .zip(other.iter())
                .map(|(a, b)| (a - b).abs())
                .fold(0.0f32, f32::max);
            let db = if peak <= 0.0 {
                -300.0
            } else {
                20.0 * (peak as f64).log10()
            };
            assert!(
                db < -120.0,
                "block {block} vs 512: peak residual {db:.1} dBFS — the ramp is block-size \
                 dependent again (E3). The control grid phase must survive block boundaries."
            );
        }
    }
    #[test]
    fn saturator_never_adds_distortion_to_the_leveller() {
        const HOT_CYCLES: f64 = 964.0;
        let leveller_only = probe_body(HOT_CYCLES, None, true, false, 1.0);
        let shipped = probe_body(HOT_CYCLES, None, true, true, 1.0);
        assert!(
            shipped.resid_dbc <= leveller_only.resid_dbc + 1.0,
            "the saturator is doing the levelling: {:.1} dBc with it vs {:.1} dBc without \
             (steady peak {:.3} vs knee {SATURATE_KNEE}). Check AGC_DRIVE.",
            shipped.resid_dbc,
            leveller_only.resid_dbc,
            leveller_only.peak
        );
    }
    struct Probe {
        peak: f32,
        rms: f32,
        resid_dbc: f64,
        agc_gain: f32,
        attack: f32,
    }
    fn probe_body(cycles: f64, drive: Option<f32>, agc: bool, sat: bool, amp: f32) -> Probe {
        use crate::cartridge::Cartridge;
        use std::f64::consts::PI;
        const BODY: &[u8; 240] = include_bytes!("../tests/fixtures/sf_mouth_frame.body240");
        const SR: f64 = 39_062.5;
        const WARMUP: usize = 4096;
        const TAIL: usize = 12_288;
        let f0 = SR * cycles / TAIL as f64;
        let mut eng = FilterEngine::new();
        eng.prepare(SR);
        eng.load_cartridge(Cartridge::from_body_bytes("d", BODY.as_slice(), 1.0).unwrap());
        eng.debug.agc_enabled = agc;
        eng.debug.saturation_enabled = sat;
        eng.debug.dc_block_enabled = false;
        if let Some(d) = drive {
            eng.set_agc_drive(d);
        }
        let tone = |i: usize| (amp as f64 * (2.0 * PI * f0 * i as f64 / SR).sin()) as f32;
        let mut sl: Vec<f32> = (0..WARMUP).map(tone).collect();
        let mut sr_ = sl.clone();
        eng.process_block(&mut sl, &mut sr_, 0.5, 1.0);
        let attack = sl.iter().fold(0.0f32, |m, &s| m.max(s.abs()));
        let mut l: Vec<f32> = (0..TAIL).map(|i| tone(WARMUP + i)).collect();
        let mut r = l.clone();
        eng.process_block(&mut l, &mut r, 0.5, 1.0);
        let (mut cr, mut ci) = (0.0f64, 0.0f64);
        for (i, &s) in l.iter().enumerate() {
            let ph = 2.0 * PI * f0 * (WARMUP + i) as f64 / SR;
            cr += s as f64 * ph.cos();
            ci += s as f64 * ph.sin();
        }
        let (a, b) = (2.0 * cr / TAIL as f64, 2.0 * ci / TAIL as f64);
        let fund_rms = (a * a + b * b).sqrt() / 2.0f64.sqrt();
        let mut acc = 0.0f64;
        for (i, &s) in l.iter().enumerate() {
            let ph = 2.0 * PI * f0 * (WARMUP + i) as f64 / SR;
            acc += (s as f64 - (a * ph.cos() + b * ph.sin())).powi(2);
        }
        Probe {
            peak: l.iter().fold(0.0f32, |m, &s| m.max(s.abs())),
            rms: ((l.iter().map(|&s| (s as f64).powi(2)).sum::<f64>()) / TAIL as f64).sqrt() as f32,
            resid_dbc: 20.0
                * ((acc / TAIL as f64).sqrt() / fund_rms.max(1e-12))
                    .max(1e-12)
                    .log10(),
            agc_gain: eng.agc_gain,
            attack,
        }
    }
}
#[cfg(test)]
mod ramp_taste {
    use super::*;
    use crate::cartridge::Cartridge;
    #[test]
    #[ignore = "renders the ramp-time A/B for Tyson's ear"]
    fn render_ramp_taste() {
        const SR: f64 = 39_062.5;
        const OUT_SR: u32 = 44_100;
        const SECS: f64 = 6.0;
        const HOST_BLOCK: usize = 256;
        let body = std::fs::read("../filters/bodies/CAVL_mason_jar_to_stone_pipe.body240")
            .expect("roster body");
        let n = (SECS * SR) as usize;
        let render = |ramp_ms: f64| -> Vec<f32> {
            let mut eng = FilterEngine::new();
            eng.prepare(SR);
            eng.load_cartridge(Cartridge::from_body_bytes("d", &body, 1.0).unwrap());
            eng.coeff_ramp_samples =
                (((ramp_ms / 1000.0) * SR).round() as usize).max(BLOCK_SIZE);
            let mut rng = 0x2545_F491_4F6C_DD1Du64;
            let mut pb = [0f64; 7];
            let mut out = Vec::with_capacity(n);
            let mut off = 0;
            while off < n {
                let len = HOST_BLOCK.min(n - off);
                let mut l: Vec<f32> = (0..len)
                    .map(|_| {
                        rng = rng.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
                        let w = ((rng >> 40) as f64 / (1u64 << 23) as f64) - 1.0;
                        pb[0] = 0.99886 * pb[0] + w * 0.0555179;
                        pb[1] = 0.99332 * pb[1] + w * 0.0750759;
                        pb[2] = 0.96900 * pb[2] + w * 0.1538520;
                        pb[3] = 0.86650 * pb[3] + w * 0.3104856;
                        pb[4] = 0.55000 * pb[4] + w * 0.5329522;
                        pb[5] = -0.7616 * pb[5] - w * 0.0168980;
                        let s = (pb[0]+pb[1]+pb[2]+pb[3]+pb[4]+pb[5]+pb[6] + w*0.5362) * 0.11;
                        pb[6] = w * 0.115926;
                        (s * 0.6) as f32
                    })
                    .collect();
                let mut r = l.clone();
                let t = (off + len / 2) as f64 / n as f64;
                let morph = 1.0 - (2.0 * t - 1.0).abs();
                eng.process_block(&mut l, &mut r, morph, 1.0);
                out.extend_from_slice(&l);
                off += len;
            }
            out
        };
        let dir = "C:/Users/hooki/df2-workstation/out/ramp_taste";
        std::fs::create_dir_all(dir).unwrap();
        println!("\nCAVL_mason_jar_to_stone_pipe, Q100, morph sweeping 0->1->0 over 6 s, pink noise.");
        println!("Only the coefficient ramp time differs. All level-matched to -6 dBFS.\n");
        for &ms in &[0.8f64, 5.0, 10.0, 20.0, 40.0, 80.0] {
            let s = render(ms);
            let ratio = SR / OUT_SR as f64;
            let on = (s.len() as f64 / ratio) as usize;
            let mut v: Vec<f32> = (0..on)
                .map(|i| {
                    let p = i as f64 * ratio;
                    let i0 = p.floor() as usize;
                    let fr = (p - i0 as f64) as f32;
                    let a = s.get(i0).copied().unwrap_or(0.0);
                    let b = s.get(i0 + 1).copied().unwrap_or(a);
                    a + (b - a) * fr
                })
                .collect();
            let pk = v.iter().fold(0.0f32, |m, &x| m.max(x.abs())).max(1e-9);
            let g = 0.5012 / pk;
            for x in v.iter_mut() { *x *= g; }
            let mut b = Vec::new();
            let dl = (v.len() * 2) as u32;
            b.extend_from_slice(b"RIFF");
            b.extend_from_slice(&(36 + dl).to_le_bytes());
            b.extend_from_slice(b"WAVEfmt ");
            b.extend_from_slice(&16u32.to_le_bytes());
            b.extend_from_slice(&1u16.to_le_bytes());
            b.extend_from_slice(&1u16.to_le_bytes());
            b.extend_from_slice(&OUT_SR.to_le_bytes());
            b.extend_from_slice(&(OUT_SR * 2).to_le_bytes());
            b.extend_from_slice(&2u16.to_le_bytes());
            b.extend_from_slice(&16u16.to_le_bytes());
            b.extend_from_slice(b"data");
            b.extend_from_slice(&dl.to_le_bytes());
            for &x in &v { b.extend_from_slice(&((x.clamp(-1.0,1.0) * 32767.0) as i16).to_le_bytes()); }
            let name = format!("{dir}/ramp_{:0>5.1}ms.wav", ms);
            std::fs::write(&name, b).unwrap();
            println!("  {name}");
        }
    }
}
#[cfg(test)]
mod stage_taste {
    use super::*;
    use crate::cartridge::Cartridge;
    use crate::desk_drive::mackity_saturate;
    #[test]
    #[ignore = "renders SLAM / QSound / soft-desk auditions"]
    fn render_stage_taste() {
        const SR: f64 = 39_062.5;
        const OUT: u32 = 44_100;
        const SECS: f64 = 6.0;
        const HB: usize = 256;
        let body = std::fs::read("../filters/bodies/CAVL_mason_jar_to_stone_pipe.body240").unwrap();
        let n = (SECS * SR) as usize;
        let render = |slam: f32, hard: bool, qsound: bool| -> (Vec<f32>, Vec<f32>) {
            let mut eng = FilterEngine::new();
            eng.prepare(SR);
            eng.load_cartridge(Cartridge::from_body_bytes("d", &body, 1.0).unwrap());
            eng.set_spatial_mode(if qsound { SpatialMode::QSound } else { SpatialMode::Off });
            if qsound { eng.set_space(1.0); }
            let mut rng = 0x2545_F491_4F6C_DD1Du64;
            let mut pb = [0f64; 7];
            let mut pr = [0f64; 7];
            let (mut ol, mut or_) = (Vec::with_capacity(n), Vec::with_capacity(n));
            let mut off = 0;
            while off < n {
                let len = HB.min(n - off);
                let mut l: Vec<f32> = (0..len).map(|_| {
                    rng = rng.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
                    let w = ((rng >> 40) as f64 / (1u64 << 23) as f64) - 1.0;
                    pb[0]=0.99886*pb[0]+w*0.0555179; pb[1]=0.99332*pb[1]+w*0.0750759;
                    pb[2]=0.96900*pb[2]+w*0.1538520; pb[3]=0.86650*pb[3]+w*0.3104856;
                    pb[4]=0.55000*pb[4]+w*0.5329522; pb[5]=-0.7616*pb[5]-w*0.0168980;
                    let s=(pb[0]+pb[1]+pb[2]+pb[3]+pb[4]+pb[5]+pb[6]+w*0.5362)*0.11;
                    pb[6]=w*0.115926;
                    (s*0.6) as f32
                }).collect();
                let mut r: Vec<f32> = (0..len).map(|_| {
                    rng = rng.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
                    let w = ((rng >> 40) as f64 / (1u64 << 23) as f64) - 1.0;
                    pr[0]=0.99886*pr[0]+w*0.0555179; pr[1]=0.99332*pr[1]+w*0.0750759;
                    pr[2]=0.96900*pr[2]+w*0.1538520; pr[3]=0.86650*pr[3]+w*0.3104856;
                    pr[4]=0.55000*pr[4]+w*0.5329522; pr[5]=-0.7616*pr[5]-w*0.0168980;
                    let s=(pr[0]+pr[1]+pr[2]+pr[3]+pr[4]+pr[5]+pr[6]+w*0.5362)*0.11;
                    pr[6]=w*0.115926;
                    (s*0.6) as f32
                }).collect();
                let t = (off + len/2) as f64 / n as f64;
                let morph = 1.0 - (2.0*t - 1.0).abs();
                eng.process_block(&mut l, &mut r, morph, 1.0);
                if slam > 1e-4 {
                    let drive = 10f32.powf(12.0 * slam / 20.0);
                    for v in l.iter_mut().chain(r.iter_mut()) {
                        let x = *v * drive;
                        *v = if hard {
                            x.clamp(-1.0, 1.0)
                        } else {
                            mackity_saturate(x as f64) as f32
                        };
                    }
                }
                ol.extend_from_slice(&l);
                or_.extend_from_slice(&r);
                off += len;
            }
            (ol, or_)
        };
        let dir = "C:/Users/hooki/df2-workstation/out/stage_taste";
        std::fs::create_dir_all(dir).unwrap();
        let write = |name: &str, l: &[f32], r: &[f32]| {
            let ratio = SR / OUT as f64;
            let on = (l.len() as f64 / ratio) as usize;
            let rs = |s: &[f32]| -> Vec<f32> {
                (0..on).map(|i| {
                    let p = i as f64 * ratio; let i0 = p.floor() as usize;
                    let f = (p - i0 as f64) as f32;
                    let a = s.get(i0).copied().unwrap_or(0.0);
                    let b = s.get(i0+1).copied().unwrap_or(a);
                    a + (b-a)*f
                }).collect()
            };
            let (mut a, mut b) = (rs(l), rs(r));
            let pk = a.iter().chain(b.iter()).fold(0.0f32,|m,&x| m.max(x.abs())).max(1e-9);
            let g = 0.5012 / pk;
            for x in a.iter_mut().chain(b.iter_mut()) { *x *= g; }
            let mut w = Vec::new();
            let dl = (a.len()*4) as u32;
            w.extend_from_slice(b"RIFF"); w.extend_from_slice(&(36+dl).to_le_bytes());
            w.extend_from_slice(b"WAVEfmt "); w.extend_from_slice(&16u32.to_le_bytes());
            w.extend_from_slice(&1u16.to_le_bytes()); w.extend_from_slice(&2u16.to_le_bytes());
            w.extend_from_slice(&OUT.to_le_bytes()); w.extend_from_slice(&(OUT*4).to_le_bytes());
            w.extend_from_slice(&4u16.to_le_bytes()); w.extend_from_slice(&16u16.to_le_bytes());
            w.extend_from_slice(b"data"); w.extend_from_slice(&dl.to_le_bytes());
            for i in 0..a.len() {
                w.extend_from_slice(&((a[i].clamp(-1.0,1.0)*32767.0) as i16).to_le_bytes());
                w.extend_from_slice(&((b[i].clamp(-1.0,1.0)*32767.0) as i16).to_le_bytes());
            }
            let p = format!("{dir}/{name}.wav");
            std::fs::write(&p, w).unwrap();
            println!("  {p}");
        };
        println!("\nmason_jar -> stone_pipe, Q100, morph 0->1->0, 80 ms ramp. Level-matched.\n");
        let (l,r) = render(0.0, true, false);  write("1_baseline_clean", &l, &r);
        let (l,r) = render(0.5, true, false);  write("2_SLAM_50_hardclip_SHIPPED", &l, &r);
        let (l,r) = render(1.0, true, false);  write("3_SLAM_100_hardclip_SHIPPED", &l, &r);
        let (l,r) = render(0.5, false, false); write("4_SLAM_50_soft_mackie_UNUSED", &l, &r);
        let (l,r) = render(1.0, false, false); write("5_SLAM_100_soft_mackie_UNUSED", &l, &r);
        let (l,r) = render(0.0, true, true);   write("6_QSOUND", &l, &r);
    }
}
