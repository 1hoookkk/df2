//! FilterEngine — thin runtime wrapper over the frozen `Cascade`.
//!
//! Order (matches `trenchwork_clean/trench-core/src/engine.rs` and the
//! `authoring/compilers/parity_null.py` reference pipeline):
//! cascade -> AGC (with mix) -> output_gain (boost, ramped) -> DC blocker.
//!
//! The Trench `Cascade` already owns 12-stage biquad DSP, bilinear
//! interpolation, and per-sample coefficient ramping, so this module is
//! additive only: control-rate parameter dispatch, cascade-peak gain
//! ceiling, AGC, DC blocker.
//!
//! Doctrine: `Cascade` is frozen. This module does not touch its
//! internals. The cascade-peak estimator uses direct biquad form
//! `(b0, b1, b2, a1, a2)` — not the shifted minifloat-domain kernel from
//! the `trenchwork_clean` engine. See SESSION_STATE rev 4 for the split.

use crate::agc::{active_agc_table, agc_step_stereo};
use crate::cartridge::{Cartridge, CornerData};
use crate::cascade::{Cascade, BLOCK_SIZE, NUM_COEFFS, PASSTHROUGH_COEFFS};
use crate::cvsd_input::CvsdInput;
use crate::desk_drive::{DeskDrive, SUPPORTED_MODEL as DESK_SLAM_MODEL};
use crate::qsound_spatial::QSoundSpatial;
use crate::trench_matrix::TrenchMatrix;
use std::ptr;
use std::sync::atomic::{AtomicPtr, Ordering};

/// Selects which post-cascade spatial stage runs (or `Off`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SpatialMode {
    QSound,
    Trench,
    Off,
}

/// Selects the pre-cascade input character stage.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InputMode {
    None,
    MackieDeskSlam,
    Cvsd,
}

/// First-order DC blocker (~20 Hz highpass).
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

/// Runtime debug toggles.
#[derive(Debug, Clone, Copy)]
pub struct DebugToggles {
    pub agc_enabled: bool,
    pub dc_block_enabled: bool,
    pub saturation_enabled: bool,
    pub spatial_enabled: bool,
    /// DEBUG probe knob: scales the AGC adaptation rate in the log-gain domain
    /// (`gain *= table[idx]^scale` instead of `gain *= table[idx]`).
    /// 1.0 = stock behavior (bit-identical path, `agc_step_stereo` is called).
    /// 0.25 = 4x slower attack AND release; 0.05 = 20x slower.
    pub agc_rate_scale: f32,
    /// DEBUG probe knob: maximum AGC attenuation depth in dB — the gain state is
    /// floored at `10^(-agc_max_cut_db/20)`. `f32::INFINITY` = stock (no floor,
    /// gain may fall to zero). e.g. 6.0 limits the leveler to 6 dB of cut.
    pub agc_max_cut_db: f32,
    /// DEBUG probe knob: bypass the AGC curve entirely (gain state untouched)
    /// and apply `agc_makeup_gain` in its place, through the same `agc_mix`
    /// blend. false = stock. Only observed when `agc_enabled` is true.
    pub agc_bypass: bool,
    /// Linear makeup gain used when `agc_bypass` is set. 1.0 = unity.
    pub agc_makeup_gain: f32,
    /// INERT since the dual frozen-cascade transition law: coefficients no
    /// longer ramp, so there is no ramp length to scale. Field kept for FFI/
    /// ABI stability.
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

/// WIDTH GUARD band — the spatial stage may only widen INSIDE this range.
///
/// Below 2 kHz the QSound width collapses the mono fold-down by 14-15 dB; above
/// 1 kHz it is already mono-clean. 2 kHz keeps a margin while preserving the
/// 1-4 kHz band where human localisation actually lives, so the effect stays
/// dramatic and stops being mono-suicidal. See `apply_width_guard`.
pub const WIDTH_GUARD_LO_HZ: f64 = 2_000.0;
/// Upper edge, just under the island's 19531 Hz Nyquist.
pub const WIDTH_GUARD_HI_HZ: f64 = 18_980.0;

/// Minimal RBJ biquad, used only by the width guard.
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

/// Output soft-limiter knee. Below this the stage is exactly transparent.
const SATURATE_KNEE: f32 = 0.9;

/// The AGC curve's first reduction tooth.
///
/// `BASE_AGC_TABLE[0]` and `[1]` are both 1.0001 (recovery) — the first value
/// below unity is at index 2. The index is `(gain·|x|) as int`, so the leveler
/// physically cannot reduce until `|x| >= 2.0`: **+6 dBFS**.
///
/// In a float engine where full scale is 1.0, that sits 6.9 dB *above*
/// `SATURATE_KNEE`. The leveler therefore handed the tanh a signal it had no
/// way to bring under the knee, and the tanh ended up doing all the level
/// control. Measured in `diag_limiter_handoff` on a real resonant body: the
/// curve alone distorts at -22.7 dBc, but curve+tanh distorts at -12.3 dBc —
/// the "safety net" was *adding* 10.4 dB of distortion, at the post-filter
/// output, which is precisely the stage that must stay clean.
const AGC_FIRST_TOOTH: f32 = 2.0;

/// Pre-AGC scale that lands the curve's first tooth **on** the saturator's knee.
///
/// IMPORTANT — this is NOT a ROM constant. The EmulatorX.dll AGC
/// (`FUN_1802c04e0`, read from trench_re_vault) indexes the table with
/// `(int)(|sample| * agc_gain) & 0xf` — the raw sample, no pre-scale. The binary
/// needs none because its samples already sit in an integer-magnitude domain
/// where `|x|` reaches the table's teeth (2..15). Our float engine normalises to
/// +/-1.0, so without a bridge `|x|*gain` floors to index 0/1 (the two 1.0001
/// no-reduction teeth) and the verified curve never engages — see
/// `diag_pre_agc_scaling`.
///
/// So AGC_DRIVE is a clean-room DOMAIN ADAPTATION, and the value is a voicing
/// choice: it lands the curve's first tooth on the saturator knee, so the
/// verified leveler owns steady-state level and the saturator only catches the
/// leveler's attack overshoot (no lookahead; measured 1.64x on ring-in).
/// `diag_limiter_handoff` shows this is the optimum — distortion at the curve's
/// own floor, peak as loud as possible (0.92) without waking the tanh. The AGC
/// MATH itself is bit-exact to the binary (verified line-by-line); only this
/// pre-scale is ours.
pub const AGC_DRIVE: f32 = AGC_FIRST_TOOTH / SATURATE_KNEE; // 2.222...

/// How long the coefficients take to reach a new corner.
///
/// Ghidra confirms the X3 ramps coefficients per sample, and the deltas are
/// recomputed each control block. If the ramp length EQUALS the control block
/// (32 samples ≈ 0.8 ms at the island rate) the coefficients land exactly on
/// target every block — a hard, fast, linear snap.
///
/// Making the ramp LONGER than the control block turns it into an exponential
/// approach: each 32-sample block closes `BLOCK_SIZE / ramp` of the remaining
/// distance, because the deltas are recomputed from the CURRENT coefficients.
/// That is what an analog control lag actually feels like — and it is the
/// difference between a morph that steps and a morph that glides.
///
/// It also smooths the host's morph quantisation for free: a DAW only hands us
/// one morph value per buffer, so at 512 samples the morph itself updates at
/// ~86 Hz. A ramp longer than that interval turns those steps into a slide.
///
/// 80 ms is DERIVED, not tuned — it is set by the resonators themselves.
///
/// A pole at radius r rings with a time constant `tau = -1 / (fs * ln r)`. The
/// shipping roster's Q100 stages sit at r ~ 0.9989, so **tau = 23.3 ms** (median
/// AND p90 — the bodies share a Q law; worst case 39.9 ms). That is how long the
/// filter's stored energy takes to decay, and therefore how fast the filter can
/// physically respond to anything at all.
///
/// Move the coefficients FASTER than tau and the ring cannot follow: the old
/// resonance decays while a new one builds elsewhere, and you hear a crossfade
/// between two static filters. That is exactly what the dual frozen cascade did
/// explicitly, and what a one-control-block snap does implicitly — same failure,
/// different mechanism.
///
/// Move them SLOWER than tau and the stored energy is CARRIED: the pole drags the
/// ringing with it and shifts its pitch on the way. That is what a physical
/// resonator does when it changes shape — a bottle filling, a tube lengthening.
/// The air inside does not stop and restart. It glides.
///
/// 80 ms = 3.44 x tau. Tyson picked it by ear from a level-matched A/B of
/// 0.8/5/10/20/40/80 ms before any of this was computed. The ear found the
/// physics. `render_ramp_taste` regenerates that A/B.
///
/// The onset is still immediate (the approach is exponential, so it starts moving
/// on the first sample) — this lengthens the SETTLE, not the attack, so a ZAP-style
/// morph swipe still hits.
pub const COEFF_RAMP_SECONDS: f64 = 0.080;

/// Output soft-limiter — the safety net for the AGC's attack overshoot.
///
/// Transparent below the knee. It is NOT a level control: if this stage is
/// working continuously, the gain structure upstream is wrong (see `AGC_DRIVE`).
#[inline]
fn saturate(x: f32) -> f32 {
    let a = x.abs();
    if a <= SATURATE_KNEE {
        x
    } else {
        x.signum()
            * (SATURATE_KNEE
                + (1.0 - SATURATE_KNEE) * ((a - SATURATE_KNEE) / (1.0 - SATURATE_KNEE)).tanh())
    }
}

/// Stereo Filter Engine — handles dual cascades, Mackie saturation, and QSound.
pub struct FilterEngine {
    cascade_l: Cascade,
    cascade_r: Cascade,
    /// Coefficient ramp length in samples (see `COEFF_RAMP_SECONDS`). Longer
    /// than `BLOCK_SIZE` = an exponential glide toward each new corner.
    coeff_ramp_samples: usize,
    /// Phase within the fixed 32-sample control grid, CONTINUOUS across host
    /// blocks. This is the real E3 fix.
    ///
    /// E3 correctly found that coefficient ramping was block-size dependent —
    /// but the cause was ramping over the HOST block length, so a 512-sample
    /// buffer and a 16-sample buffer ramped over different distances. The
    /// response was to delete the ramp and crossfade two frozen cascades
    /// instead. That is NOT what the machine does: Ghidra confirms the X3 does
    /// "per-sample additive coefficient ramping" (5 deltas added to each stage's
    /// coefficients after every sample). Deleting it is why a moving morph
    /// stepped instead of glided.
    ///
    /// Ramping over a FIXED 32-sample grid whose phase survives block
    /// boundaries is deterministic by construction — faithful AND buffer-
    /// independent. `BLOCK_SIZE` was already 32 and already unused.
    control_phase: usize,
    // Audio-thread-owned. New bodies arrive via `CartridgeMailbox` (a sibling
    // field of `EngineHandle`, never inside this `&mut`-borrowed struct) and are
    // installed at a block boundary; the displaced box is handed back to the
    // message thread to free, so no allocation/free ever runs on the audio thread.
    cartridge: Option<Box<Cartridge>>,
    sample_rate: f64,

    // Output Gain & Ramping
    output_gain: f32,
    target_output_gain: f32,
    delta_output_gain: f32,

    // Drive & Saturation
    pre_drive_gain: f32,
    slam_drive: f32,
    target_slam_drive: f32,
    delta_slam_drive: f32,
    input_mode: InputMode,
    desk_drive_configured: bool,
    desk_drive_l: DeskDrive,
    desk_drive_r: DeskDrive,
    cvsd_l: CvsdInput,
    cvsd_r: CvsdInput,

    // AGC & Clean-up
    agc_gain: f32,
    agc_mix: f32,
    active_agc_table: [f32; 16],
    /// Pre-AGC scale: the cascade output is multiplied by this BEFORE `agc_step`
    /// and divided back after — it moves the signal into the integer-magnitude
    /// domain the verified table is indexed in, without altering the curve.
    /// Defaults to `AGC_DRIVE`, which lands the curve's first tooth on the
    /// saturator's knee so the leveler (not the tanh) owns steady-state level.
    agc_drive: f32,
    dc_blocker_l: DcBlocker,
    dc_blocker_r: DcBlocker,

    // Spatialization
    spatial: QSoundSpatial,
    pub trench_matrix: TrenchMatrix,
    spatial_mode: SpatialMode,
    // WIDTH GUARD — band-limits what the spatial stage ADDS (see apply_width_guard).
    width_dry_l: Vec<f32>,
    width_dry_r: Vec<f32>,
    width_hp_l: GuardBiquad,
    width_lp_l: GuardBiquad,
    width_hp_r: GuardBiquad,
    width_lp_r: GuardBiquad,
    space: f32,

    /// AMOUNT — the honest dose. 1.0 = full body, 0.0 = flat/identity. Applied
    /// as a linear per-stage coefficient blend toward `PASSTHROUGH_COEFFS` in
    /// `set_parameters` (Cascade itself stays frozen/untouched), so the on-
    /// screen curve (read from the same cascade coefficients) moves with it.
    amount: f32,

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
            debug: DebugToggles::default(),
        }
    }

    pub fn prepare(&mut self, sample_rate: f64) {
        self.sample_rate = sample_rate;
        self.control_phase = 0;
        // Never shorter than one control block, or the ramp would overshoot.
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

    /// Single-threaded / test convenience: install a cartridge immediately and
    /// drop whatever it displaces on the caller's thread. The runtime audio path
    /// does NOT use this — it installs from the mailbox via `install_cartridge`.
    pub fn load_cartridge(&mut self, cart: Cartridge) {
        let _ = self.install_cartridge(Box::new(cart));
    }

    /// Install a boxed cartridge and return the one it displaces (if any) WITHOUT
    /// dropping it — the caller decides where the free happens. On the audio
    /// thread the returned box is routed back to the message thread via the
    /// mailbox's garbage slot; nothing is deallocated here.
    ///
    /// Side effects mirror the old `load_cartridge`: recompute the fixed pre-drive
    /// and clear any baked spatial profile (5D is a runtime-only toggle). Both are
    /// allocation-free, so this is safe to call at a block boundary.
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

    /// AMOUNT — honest dose. 1.0 = full body (default), 0.0 = flat/identity.
    pub fn set_amount(&mut self, amount: f32) {
        self.amount = amount.clamp(0.0, 1.0);
    }

    /// Pre-AGC scale (≥ 1.0). 1.0 = identity (curve stays asleep in float domain);
    /// higher drives the cascade into the AGC table's teeth so it compresses.
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

        // AMOUNT — honest dose. Linear per-stage blend of the decoded corner
        // toward PASSTHROUGH_COEFFS (identity). Cascade itself is untouched/
        // frozen; this only changes what target coefficients it's handed, so
        // the UI curve (read from these same coefficients) moves with it too.
        // Stability is free: the direct-form (a1,a2) stability region is the
        // convex triangle |a2|<1, a1<1+a2, a1>-(1+a2), which contains the
        // origin (identity) — a linear blend from any stable point toward the
        // origin stays inside the triangle at every step.
        let corner = if self.amount < 1.0 {
            let a = self.amount as f64;
            let mut blended = corner;
            for stage in blended.iter_mut() {
                for i in 0..NUM_COEFFS {
                    stage[i] = a * stage[i] + (1.0 - a) * PASSTHROUGH_COEFFS[i];
                }
            }
            // Gain compensation: NOT "match the α=1 level" (that would make
            // amount=0 louder than dry, contradicting "0 = flat/identity").
            // The two endpoints are already correct by construction (blended
            // == corner at a=1, blended == identity with peak 1.0 at a=0) —
            // what needs correcting is the MIDDLE, because gain is a
            // nonlinear function of the coefficients being blended linearly.
            // Target: peak taper is linear in dB from 0 dB (a=0) to the
            // full-strength peak's dB (a=1); compensate only the deviation
            // from that straight line at the current `a`.
            let peak_full = compute_cascade_peak(&corner, self.sample_rate).max(1.0e-6);
            let peak_blended = compute_cascade_peak(&blended, self.sample_rate).max(1.0e-6);
            let expected_db = a as f32 * 20.0 * peak_full.log10();
            let actual_db = 20.0 * peak_blended.log10();
            boost *= 10.0_f32.powf((expected_db - actual_db) / 20.0);
            blended
        } else {
            corner
        };

        // Per-sample additive coefficient ramping — the X3's control law, from
        // Ghidra: "after each sample, 5 delta values are added to each active
        // stage's 5 coefficients." The deltas are recomputed from the CURRENT
        // coefficients every control block, so any float drift self-corrects.
        //
        // Stability is free: the direct-form (a1,a2) region is the convex
        // triangle |a2|<1, a1<1+a2, a1>-(1+a2). A straight line between two
        // stable corners cannot leave a convex set, so the ramp is stable at
        // every intermediate sample.
        // Everything at control rate glides on the same lag — coefficients, body
        // gain and SLAM. A machine where one of them snaps while the others slide
        // reads as cheap; moving them together is what feels expensive.
        let ramp = chunk_size.max(BLOCK_SIZE);
        self.cascade_l.set_targets(&corner, ramp);
        self.cascade_r.set_targets(&corner, ramp);

        self.target_output_gain = boost;
        self.delta_output_gain = (boost - self.output_gain) / ramp as f32;
        self.delta_slam_drive = (self.target_slam_drive - self.slam_drive) / ramp as f32;
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
                // DEBUG probe path: skip the curve, apply fixed makeup through
                // the same mix law. Gain state is left untouched.
                let mk = self.debug.agc_makeup_gain;
                sl += (sl * mk - sl) * self.agc_mix;
                sr += (sr * mk - sr) * self.agc_mix;
            } else if self.debug.agc_rate_scale == 1.0 && self.debug.agc_max_cut_db == f32::INFINITY
            {
                // Stock path (bit-identical to pre-knob behavior).
                // Scale into the AGC's integer-magnitude domain, apply the curve,
                // scale back. `agc_drive == 1.0` is exact identity (null parity).
                let d = self.agc_drive;
                let (agc_l, agc_r) =
                    agc_step_stereo(sl * d, sr * d, &mut self.agc_gain, &self.active_agc_table);
                let agc_l = agc_l / d;
                let agc_r = agc_r / d;
                sl += (agc_l - sl) * self.agc_mix;
                sr += (agc_r - sr) * self.agc_mix;
            } else {
                // DEBUG probe path: same law with adaptation-rate scale and/or
                // gain-floor clamp. Index law identical (`(gain·|x|) as int & 0xF`).
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

        // 5. Output Gain
        self.output_gain += self.delta_output_gain;
        sl *= self.output_gain;
        sr *= self.output_gain;

        // 6. DC Blocker
        if self.debug.dc_block_enabled {
            sl = self.dc_blocker_l.process(sl);
            sr = self.dc_blocker_r.process(sr);
        }

        // 7. Output saturation — final safety stage (see `saturate`). Catches the
        // AGC-wrap spikes that otherwise hard-clip at the host.
        if self.debug.saturation_enabled {
            sl = saturate(sl);
            sr = saturate(sr);
        }

        (sl, sr)
    }

    fn snap_to_target(&mut self) {
        self.output_gain = self.target_output_gain;
        self.delta_output_gain = 0.0;
        self.slam_drive = self.target_slam_drive;
        self.delta_slam_drive = 0.0;
        if self.input_mode == InputMode::MackieDeskSlam {
            self.configure_desk_drive();
        }
    }

    /// Process stereo buffers in place.
    pub fn process_block(&mut self, left: &mut [f32], right: &mut [f32], morph: f64, q: f64) {
        if self.cartridge.is_none() {
            return;
        }

        let len = left.len().min(right.len());

        // Fixed 32-sample control grid, phase-CONTINUOUS across host blocks.
        //
        // The old loop restarted the grid at every process_block call and ramped
        // over `remaining.min(BLOCK_SIZE)` — so a host block of, say, 100 samples
        // produced chunks of 32/32/32/4, and the 4-sample chunk ramped four times
        // faster. THAT is what made the ramp block-size dependent (E3), not the
        // ramp itself. Carrying the phase across calls means every control block
        // is exactly BLOCK_SIZE samples regardless of what the host hands us, so
        // the output is identical at any buffer size.
        for i in 0..len {
            if self.control_phase == 0 {
                // Deltas are recomputed from the CURRENT state every control
                // block, so the approach is exponential and self-correcting —
                // no snapping, and float drift can never accumulate.
                self.set_parameters(morph, q, self.coeff_ramp_samples);
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

        // 7. Spatial Stage (Final payload) — selectable.
        if self.debug.spatial_enabled && self.spatial_mode != SpatialMode::Off {
            // Snapshot the pre-spatial signal so the WIDTH GUARD below can isolate
            // exactly what the spatial stage added.
            self.width_dry_l.clear();
            self.width_dry_r.clear();
            self.width_dry_l.extend_from_slice(left);
            self.width_dry_r.extend_from_slice(right);

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

    /// WIDTH GUARD — keeps the spatial stage from destroying the mono fold-down.
    ///
    /// Measured on real decorrelated stereo, QSound at full space collapsed the
    /// mono sum by 14-15 dB from 20 Hz to 500 Hz (and 9 dB to 1 kHz), while being
    /// perfectly mono-clean above 1 kHz. All the cancellation lived in the low
    /// end; none of the effect needs to. Left alone it would gut ORBIT on a club
    /// rig, a phone, or any mono bus.
    ///
    /// This runs OUTSIDE `qsound_spatial` on purpose. That model is a null-verified
    /// re-capture of the real thing and must stay byte-exact — band-limiting inside
    /// it broke its own azimuth/bounds tests. So the guard sits here, as a product
    /// safety layer, and the model underneath is untouched.
    ///
    /// It filters ONLY what the spatial stage ADDED (`wet - dry`). The dry signal
    /// passes through at every frequency, so the SOURCE's own stereo image survives
    /// intact — band-limiting the total side channel instead would have collapsed
    /// the user's own low-end stereo, a worse bug than the one being fixed.
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

/// Lock-free, single-producer (message thread) / single-consumer (audio thread)
/// hand-off for body swaps. It lives BESIDE the `FilterEngine` in `EngineHandle`,
/// never inside it, so the audio thread can hold `&mut FilterEngine` exclusively
/// while the message thread touches only these atomics — no aliasing UB.
///
/// `pending`: producer publishes a new `Box<Cartridge>`; consumer takes it.
/// `garbage`: consumer hands the displaced cartridge back; producer frees it.
/// The consumer only takes a pending cartridge when `garbage` is empty, so a box
/// is never dropped on the audio thread and the single garbage slot is never
/// overwritten.
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

    /// Producer (message thread). Takes ownership of `cart`. Frees any retired
    /// cartridge first, then publishes; if a previous pending was never consumed
    /// (rapid re-stage) it is reclaimed here too. Never touches the engine.
    pub fn stage(&self, cart: Box<Cartridge>) {
        self.reclaim();
        let prev = self.pending.swap(Box::into_raw(cart), Ordering::AcqRel);
        if !prev.is_null() {
            drop(unsafe { Box::from_raw(prev) });
        }
    }

    /// Producer (message thread). Free the cartridge the audio thread retired, if
    /// any. Safe to call on a timer to release memory promptly between swaps.
    pub fn reclaim(&self) {
        let g = self.garbage.swap(ptr::null_mut(), Ordering::AcqRel);
        if !g.is_null() {
            drop(unsafe { Box::from_raw(g) });
        }
    }

    /// Consumer (audio thread). Returns the staged cartridge to install — but
    /// only when the garbage slot is free to receive the box it will displace.
    /// Otherwise returns `None` and leaves the pending cartridge in place
    /// (install deferred a few blocks until the producer reclaims). This is what
    /// guarantees the audio thread never frees and never overwrites garbage.
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

    /// Consumer (audio thread). Hand a displaced cartridge back to the producer.
    /// Only reached after `take()` confirmed garbage was empty, so the swap-out
    /// is always null.
    fn retire(&self, old: Box<Cartridge>) {
        let prev = self.garbage.swap(Box::into_raw(old), Ordering::AcqRel);
        debug_assert!(
            prev.is_null(),
            "garbage slot overwritten: producer fell behind take()'s guard"
        );
        if !prev.is_null() {
            // Defensive (release builds): reclaim rather than leak.
            drop(unsafe { Box::from_raw(prev) });
        }
    }
}

impl Drop for CartridgeMailbox {
    fn drop(&mut self) {
        // Exclusive access at drop: free anything still parked in either slot.
        let p = self.pending.swap(ptr::null_mut(), Ordering::AcqRel);
        if !p.is_null() {
            drop(unsafe { Box::from_raw(p) });
        }
        self.reclaim();
    }
}

/// The opaque object behind the FFI `*mut c_void` engine handle.
///
/// CRITICAL: the FFI must NEVER form `&EngineHandle` / `&mut EngineHandle`. It
/// projects to the disjoint fields directly through the raw pointer — the audio
/// thread borrows `&mut handle.engine`, while any thread may touch
/// `handle.mailbox` through its atomics. Splitting the borrow this way is what
/// keeps single-thread ownership of the engine sound.
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

/// Audio-thread step: install a staged body (if one is ready) at the block
/// boundary, routing the displaced cartridge back to the message thread to free.
/// Allocation-free. Takes the engine and mailbox as separate borrows so callers
/// never have to form a whole-`EngineHandle` reference.
pub fn install_pending(engine: &mut FilterEngine, mailbox: &CartridgeMailbox) {
    if let Some(new_cart) = mailbox.take() {
        if let Some(old) = engine.install_cartridge(new_cart) {
            mailbox.retire(old);
        }
    }
}

/// Peak |H(e^jω)| across 1025 linearly-spaced bins from DC to Nyquist,
/// evaluated on the cascade target as direct-form biquads
/// `(b0, b1, b2, a1, a2)` = `(c0, c1, c2, c3, c4)`.
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
            // Direct biquad form — see trench-core doctrine and
            // SESSION_STATE rev 4 truth on `compiled-v1` kernel mapping.
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
        // No cartridge → process_block is a no-op.
        assert_eq!(l, l_copy);
        assert_eq!(r, r_copy);
    }

    #[test]
    fn passthrough_cartridge_preserves_energy() {
        let mut engine = FilterEngine::new();
        engine.prepare(44100.0);
        engine.load_cartridge(make_passthrough_cartridge());

        // Impulse through passthrough stages + DC blocker. Energy should
        // survive the DC blocker to within a few percent for an impulse.
        let mut l = vec![0.0_f32; 256];
        let mut r = vec![0.0_f32; 256];
        l[0] = 1.0;
        r[0] = 1.0;
        let input_sum_sq: f32 =
            l.iter().map(|&s| s * s).sum::<f32>() + r.iter().map(|&s| s * s).sum::<f32>();

        engine.process_block(&mut l, &mut r, 0.5, 0.5);

        let output_sum_sq: f32 =
            l.iter().map(|&s| s * s).sum::<f32>() + r.iter().map(|&s| s * s).sum::<f32>();
        assert!(
            (output_sum_sq - input_sum_sq).abs() < 0.1,
            "impulse energy drifted: in={input_sum_sq} out={output_sum_sq}"
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
        // One resonant kernel row, five passthrough rows. All four corners are
        // identical so only the engine amount control is under test.
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

        // Ramp is chunk_size-length; process enough samples for it to settle.
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
        engine.set_amount(1.0); // default, but explicit for clarity

        // Coefficients now GLIDE to their target over COEFF_RAMP_SECONDS rather
        // than snapping (see `COEFF_RAMP_SECONDS` — the X3 ramps per sample).
        // Run long enough for the exponential approach to settle before reading
        // them, or we would be asserting against a coefficient still in flight.
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

        let tail = BLOCK_SIZE * 4; // past the coefficient ramp
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
        // "Does it tame the curve?" -- checks the actual peak |H(e^jw)| at each
        // amount step, not just the two endpoints. A real taper should shrink
        // monotonically from the full-strength peak down to 1.0 (0 dB, flat)
        // as amount decreases, with no bump/overshoot in the middle.
        let steps = [1.0f32, 0.75, 0.5, 0.25, 0.0];
        let mut peaks_db = Vec::new();

        for &amt in &steps {
            let mut engine = FilterEngine::new();
            engine.prepare(44100.0);
            engine.load_cartridge(make_resonant_cartridge());
            engine.set_amount(amt);

            // Long enough for the coefficient glide to settle — see the note in
            // `amount_one_leaves_cascade_targets_at_full_strength`.
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

        // Endpoints: full strength has real resonance (> 0 dB); flat is exactly 0 dB.
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

        // Monotonic: each step's peak must be <= the previous (small slack for
        // floating-point noise). This is the actual "tames the curve" claim.
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
        // Compile-time sanity: corners are [[f64; 5]; NUM_STAGES].
        use crate::cascade::{NUM_COEFFS, NUM_STAGES};
        let _: [[f64; NUM_COEFFS]; NUM_STAGES] = [[0.0; NUM_COEFFS]; NUM_STAGES];
    }

    #[test]
    fn agc_drive_unity_is_identity_higher_compresses() {
        // Drives a steady 0.7 through a passthrough cartridge (saturate/DC off)
        // so only the AGC can change the level. Unity drive = float-domain no-op
        // (passes through); a higher drive scales into the table's teeth.
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
        assert!(
            (unity - 0.7).abs() < 0.02,
            "unity drive must pass 0.7 ~untouched (AGC asleep in float domain), got {unity}"
        );
        assert!(
            driven < unity * 0.85,
            "agc_drive=8 must visibly compress; got driven={driven} vs unity={unity}"
        );
    }

    /// Render audition WAVs: the SAME body + pink + morph sweep at three
    /// `agc_drive` settings — 1 (dead/clean), 4 (engaged), 8 (heavy) — so the
    /// AGC's contribution to the character can be A/B'd by ear. Boost is unity;
    /// `agc_drive` is the only difference. Uses the declared clean-room body and
    /// writes 48 kHz mono WAVs under `target/agc_audition/`. Run:
    ///   cargo test -p trench-core render_agc_audition -- --ignored --nocapture
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

        // Minimal 16-bit mono WAV writer (no external dep).
        let write_wav = |path: &std::path::Path, samples: &[f32]| {
            let data_len = (samples.len() * 2) as u32;
            let mut b: Vec<u8> = Vec::with_capacity(44 + data_len as usize);
            b.extend_from_slice(b"RIFF");
            b.extend_from_slice(&(36 + data_len).to_le_bytes());
            b.extend_from_slice(b"WAVE");
            b.extend_from_slice(b"fmt ");
            b.extend_from_slice(&16u32.to_le_bytes());
            b.extend_from_slice(&1u16.to_le_bytes()); // PCM
            b.extend_from_slice(&1u16.to_le_bytes()); // mono
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

            // Fresh pink seed per drive → identical noise across files (fair A/B).
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
                let morph = off as f64 / total as f64; // sweep 0 -> 1
                eng.process_block(&mut l, &mut r, morph, 0.5);
                wet.extend_from_slice(&l);
                off += len;
            }

            // Linear resample EMU -> 48 kHz for clean playback.
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

    /// Diagnostic: the verified AGC curve indexes off `(gain·|x|) as int & 0xF`,
    /// so in the float domain (|x| < 1) it floors to index 0 and never engages.
    /// This takes a real resonant body's RAW cascade output and sweeps a PRE-AGC
    /// scale factor, measuring how hard the curve compresses (dB after rescaling)
    /// and the min gain it reaches — i.e. where the real character actually
    /// starts. Run:
    ///   cargo test -p trench-core diag_pre_agc_scaling -- --ignored --nocapture
    #[test]
    #[ignore = "diagnostic: pre-AGC scale vs AGC engagement"]
    fn diag_pre_agc_scaling() {
        use crate::agc::{active_agc_table, agc_step};
        use crate::cartridge::Cartridge;

        const BODY: &[u8; 240] = include_bytes!("../tests/fixtures/sf_mouth_frame.body240");
        let bytes = BODY.as_slice();

        // Raw cascade output: AGC / saturate / DC all OFF, unity boost, q1 (hot).
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

    /// Diagnostic: the limiter handoff.
    ///
    /// `BASE_AGC_TABLE[0..=1]` are both 1.0001 — the table's first reduction
    /// tooth is index 2, so the AGC curve cannot engage below |x| = 2.0 (+6
    /// dBFS). `saturate()`'s knee is 0.9 (-0.9 dBFS). The two limiters disagree
    /// about "loud" by 6.9 dB and the crude one fires first, so the tanh does
    /// all the level control and the verified curve never gets a turn.
    ///
    /// This drives a real resonant body into that gap and reports who is doing
    /// the limiting and what it costs. `resid` is everything that is not the
    /// fundamental (harmonics + fold products) relative to it.
    ///   cargo test -p trench-core --lib diag_limiter_handoff -- --ignored --nocapture
    #[test]
    #[ignore = "diagnostic: which limiter is doing the work"]
    fn diag_limiter_handoff() {
        const SR: f64 = 39_062.5;
        const TAIL: usize = 12_288;

        let run = |cycles: f64, drive: f32, agc: bool, sat: bool, amp: f32| -> Probe {
            probe_body(cycles, Some(drive), agc, sat, amp)
        };

        // Find where this body is actually hot — that is where the limiters meet.
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
        println!("AGC first tooth = |x| >= 2.0 (+6.0 dBFS)   saturate() knee = 0.9 (-0.9 dBFS)");
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

        // `attack` is measured with the saturator OFF, so it shows what the AGC
        // alone lets through during ring-in — a feedback leveler has no
        // lookahead, so this is the overshoot the saturator legitimately exists
        // to catch.
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

    /// The AGC is the verified 16-value curve, and `AGC_DRIVE` does not replace
    /// it — it only moves the signal into the integer-magnitude domain the table
    /// is indexed in. Proof: the active table at the island rate is
    /// `BASE_AGC_TABLE` value-for-value, and the shipped drive lands the signal
    /// on the table's real teeth (indices 2+) instead of the two 1.0001
    /// no-reduction entries it used to be stuck on.
    ///   cargo test -p trench-core --lib diag_agc_curve -- --ignored --nocapture
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
        println!("AGC_DRIVE = AGC_FIRST_TOOTH / SATURATE_KNEE = {AGC_FIRST_TOOTH} / {SATURATE_KNEE} = {AGC_DRIVE:.4}\n");

        // The curve is identical in both cases. What changes is WHERE the leveler
        // settles on it — and therefore whether the tanh downstream has to finish
        // the job. A feedback leveler correctly spends most of its life in the
        // no-reduction zone, tapping tooth 2 just often enough to hold its gain;
        // the number that matters is the peak it hands to the saturator.
        const HOT_CYCLES: f64 = 964.0; // ~3064 Hz — this body's resonance, +36 dBFS raw
        println!("what the leveler hands to the saturator (knee = {SATURATE_KNEE}):");
        for &(label, drive) in &[("OLD  (drive 1.0)", 1.0f32), ("SHIPPED", AGC_DRIVE)] {
            let leveller = probe_body(HOT_CYCLES, Some(drive), true, false, 1.0);
            let shipped = probe_body(HOT_CYCLES, Some(drive), true, true, 1.0);
            // The honest test is not the raw peak but whether the tanh actually
            // changes anything once it sees the signal.
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

    /// Diagnostic: why a morph sweep went from inert to musical.
    ///
    /// A morph sweep drags a resonant peak across the source's spectrum, so it is
    /// a violent LEVEL gesture by nature. The question is what rides that ride.
    ///
    /// A clipper is memoryless: it kills the PEAK and keeps the sustain — it eats
    /// exactly the bloom that carries a filter's character — and it pins every
    /// morph position to the same ceiling, so the sweep has no dynamic contour at
    /// all. A leveler has TIME: the bloom passes through before the gain catches
    /// up, then it ducks and releases. That is the opposite dynamic shape, and it
    /// is the one the hardware had.
    ///
    /// Crest factor is the tell. 3.01 dB = a sine. ~1 dB = a square wave.
    ///   cargo test -p trench-core --lib diag_morph_musicality -- --ignored --nocapture
    #[test]
    #[ignore = "diagnostic: why morph became musical"]
    fn diag_morph_musicality() {
        use crate::cartridge::Cartridge;

        const SR: f64 = 39_062.5;
        const N: usize = 8192;

        // Harmonically rich source, so a sweeping resonance always has something
        // to grab — this is what a morph sweep actually meets in a mix.
        let saw: Vec<f32> = (0..N)
            .map(|i| {
                let ph = (110.0 * i as f64 / SR).fract();
                ((ph * 2.0 - 1.0) * 0.7) as f32
            })
            .collect();

        // (rms, crest dB) at one morph position
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
            eng.process_block(&mut l, &mut r, morph, 1.0); // settle
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

    /// Diagnostic: is the identity body actually a bypass?
    ///
    /// The cascade is identity, but the leveler and the saturator are still in
    /// the chain. The leveler's first tooth now sits at `SATURATE_KNEE`, so ANY
    /// signal peaking above 0.9 engages it — flat body or not. This measures the
    /// null residual against the dry input, so "No filter" can be honest about
    /// what it is.
    ///   cargo test -p trench-core --lib diag_identity_transparency -- --ignored --nocapture
    #[test]
    #[ignore = "diagnostic: is the identity body a true bypass"]
    fn diag_identity_transparency() {
        use crate::cartridge::Cartridge;

        const SR: f64 = 39_062.5;
        const N: usize = 8192;
        const IDENTITY: &[u8; 240] = include_bytes!("../../plugin/assets/bodies/identity.body240");

        // Null the identity body with each post-cascade stage isolated, so we
        // learn WHICH stage breaks the bypass rather than just that it is broken.
        let run = |amp: f32, agc: bool, sat: bool, dc: bool| -> (f32, f64) {
            let mut eng = FilterEngine::new();
            eng.prepare(SR);
            eng.load_cartridge(
                Cartridge::from_body_bytes("identity", IDENTITY.as_slice(), 1.0).unwrap(),
            );
            eng.debug.agc_enabled = agc;
            eng.debug.saturation_enabled = sat;
            eng.debug.dc_block_enabled = dc;

            // Harmonically rich, so this is not a best case.
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

    /// E3 REGRESSION GUARD — a moving morph must be bit-identical at any buffer size.
    ///
    /// E3 (2026-07) found coefficient ramping was host-block dependent (worst
    /// 512-vs-16 null: -2.6 dBFS) and the response was to delete the ramp and
    /// crossfade two frozen cascades. But Ghidra says the X3 DOES ramp
    /// per-sample, and deleting it is what made a moving morph step instead of
    /// glide.
    ///
    /// The actual bug was ramping over the HOST block: a 100-sample buffer gave
    /// chunks of 32/32/32/4, and the 4-sample chunk ramped 8x faster. The fix is
    /// a fixed 32-sample control grid whose phase survives block boundaries — so
    /// the ramp is faithful AND deterministic. This locks that door.
    #[test]
    fn moving_morph_is_identical_at_any_buffer_size() {
        use crate::cartridge::Cartridge;
        const BODY: &[u8; 240] = include_bytes!("../tests/fixtures/sf_mouth_frame.body240");
        const N: usize = 8192;

        // The morph value is held CONSTANT. That is deliberate: the host hands us
        // one morph value per buffer, so a MOVING morph is quantised to the host
        // block rate by the API itself — a 16-sample buffer genuinely receives
        // different automation than a 512-sample one, and no engine can null
        // across that. What must be block-size independent is the RAMP: the
        // cascade starts at identity and glides to the corner, and that glide
        // must be identical no matter how the host chops the audio.
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

    /// The saturator is a safety net, not a level control.
    ///
    /// The AGC curve cannot reduce until `|x| >= AGC_FIRST_TOOTH` (2.0), but the
    /// tanh's knee is `SATURATE_KNEE` (0.9). If the pre-AGC scale does not close
    /// that 6.9 dB gap, the leveler settles ABOVE the knee, the tanh ends up
    /// doing all the level control, and it *adds* distortion instead of catching
    /// overshoot — post-filter output clipping, the one thing the E-mu path is
    /// supposed to avoid.
    ///
    /// Measured with the old `agc_drive = 1.0`: -12.3 dBc with both stages
    /// against -22.7 dBc for the leveler alone — the "net" was 10.4 dB WORSE
    /// than no net at all. This locks that door.
    #[test]
    fn saturator_never_adds_distortion_to_the_leveller() {
        // ~3064 Hz: this body's resonance, +36 dBFS raw on a full-scale input.
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
        /// Worst peak during ring-in, before the leveler has caught up.
        attack: f32,
    }

    /// Steady-state probe on the clean-room resonant body at the island rate.
    /// `cycles` picks a bin-aligned tone (`f = SR * cycles / TAIL`) so the
    /// fundamental lands exactly on a DFT bin and the residual is not polluted
    /// by leakage. `drive: None` leaves the engine's shipped default.
    /// `resid_dbc` is everything that is NOT the fundamental — harmonics, fold
    /// products, DC — relative to it.
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

        // Settle: let the corner transition finish and the cascade ring in.
        let mut sl: Vec<f32> = (0..WARMUP).map(tone).collect();
        let mut sr_ = sl.clone();
        eng.process_block(&mut sl, &mut sr_, 0.5, 1.0);
        let attack = sl.iter().fold(0.0f32, |m, &s| m.max(s.abs()));

        // Measure: TAIL is a whole number of cycles, continuing the tone's phase.
        let mut l: Vec<f32> = (0..TAIL).map(|i| tone(WARMUP + i)).collect();
        let mut r = l.clone();
        eng.process_block(&mut l, &mut r, 0.5, 1.0);

        // Best-fit fundamental by projection; residual = everything else.
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

    /// Render the SAME morph sweep at several coefficient-ramp lengths so the
    /// ramp time can be chosen by ear instead of by my guess.
    ///
    /// 0.8 ms  = the X3's own hard snap (ramp == one control block)
    /// 20 ms   = current default
    /// 80 ms   = slow, expensive, syrupy
    ///
    /// Level-matched. Nothing else differs.
    ///   cargo test -p trench-core --lib render_ramp_taste -- --ignored --nocapture
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
            // override the ramp for this take
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
                // morph sweeps 0 -> 1 -> 0 so the ramp is exercised both ways
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
            // resample -> 44.1k, peak-normalise so the A/B is honest
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

    /// Render the stages Tyson has never heard: SLAM and QSound.
    ///
    /// SLAM lives in C++ (`SlamStage.h`) so its law is mirrored here for the
    /// audition ONLY — drive = 10^(12*s/20), then a HARD clip at +/-1.0. Not
    /// shipped code; the plug-in still owns the real one.
    ///
    /// Also renders `mackity_saturate` — the soft Mackie desk model that already
    /// exists in `desk_drive.rs` and is wired to an input mode that is hard-wired
    /// off. It is the curve SLAM arguably should be.
    ///   cargo test -p trench-core --lib render_stage_taste -- --ignored --nocapture
    #[test]
    #[ignore = "renders SLAM / QSound / soft-desk auditions"]
    fn render_stage_taste() {
        const SR: f64 = 39_062.5;
        const OUT: u32 = 44_100;
        const SECS: f64 = 6.0;
        const HB: usize = 256;

        let body = std::fs::read("../filters/bodies/CAVL_mason_jar_to_stone_pipe.body240").unwrap();
        let n = (SECS * SR) as usize;

        // slam: 0 = off. `hard` = the shipped C++ law; false = the soft Mackie curve.
        let render = |slam: f32, hard: bool, qsound: bool| -> (Vec<f32>, Vec<f32>) {
            let mut eng = FilterEngine::new();
            eng.prepare(SR);
            eng.load_cartridge(Cartridge::from_body_bytes("d", &body, 1.0).unwrap());
            eng.set_spatial_mode(if qsound { SpatialMode::QSound } else { SpatialMode::Off });
            if qsound { eng.set_space(1.0); }

            let mut rng = 0x2545_F491_4F6C_DD1Du64;
            let mut pb = [0f64; 7];
            let mut pr = [0f64; 7];   // independent pink state for the RIGHT channel
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
                // DECORRELATED right channel - the old harness cloned left, so every
                // render came out mono and the QSound reading was measured against a
                // mono source (a far harsher test than real material).
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
                    let drive = 10f32.powf(12.0 * slam / 20.0);   // SlamStage.h: 0..+12 dB
                    for v in l.iter_mut().chain(r.iter_mut()) {
                        let x = *v * drive;
                        *v = if hard {
                            x.clamp(-1.0, 1.0)                     // shipped: HARD clip
                        } else {
                            mackity_saturate(x as f64) as f32      // the soft desk curve
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
            let g = 0.5012 / pk;                       // level-match every take to -6 dBFS
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
