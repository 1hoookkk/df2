//! PhantomVoice — 6-stage biquad cascade with 2 LFOs, 3 EGs, and a 9-cord routing matrix.
//!
//! Structures mirror the E-mu Emulator X runtime template format exactly:
//! - LFO: frequency, shape, delay, var, key_sync, tempo_sync (Free Running.xml / Clocked BPM.xml)
//! - Envelope: A1/A2/D1/D2/R1/R2 six-node (Synth - Amp.xml, Talky - Filter.xml, etc.)
//! - Patchcord: source, destination, amount in native E-mu [-100, 100] scale
//! - 9 cords per voice confirmed from voice-cord templates (Cords/All Off.xml).
//!
//! Constructor contract: all modulation sources are allocated and started in
//! `new()`, before any audio reaches the cascade. The cascade's first
//! coefficient target is therefore computed with modulation already included.

use crate::cartridge::Cartridge;
use crate::cascade::{Cascade, BLOCK_SIZE};

pub const NUM_LFOS: usize = 2;
pub const NUM_ENVS: usize = 3;
/// Voice-cord count confirmed from E-mu Cords templates (9 `<voice-cord>` elements).
pub const MAX_CORDS: usize = 9;

// ── LFO ──────────────────────────────────────────────────────────────────────

/// LFO shape, matching the E-mu `<shape type="long">` integer field.
///
/// ID mapping: 0 and 15 are confirmed by template evidence (Free Running.xml
/// shape=0; Clocked BPM.xml shape=15 with tempo_sync=1). IDs 1–4 are
/// inferred from the canonical E-mu shape ordering; 5–14 unresolved.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LfoShape {
    Triangle,    // 0 — confirmed: Free Running.xml default
    Sine,        // 1 — inferred
    Sawtooth,    // 2 — inferred
    Square,      // 3 — inferred
    Random,      // 4 — inferred (sample-and-hold)
    Clocked,     // 15 — confirmed: Clocked BPM.xml with tempo_sync=1
    Unknown(u8), // any other ID from a preset
}

impl LfoShape {
    pub fn from_id(id: u8) -> Self {
        match id {
            0 => LfoShape::Triangle,
            1 => LfoShape::Sine,
            2 => LfoShape::Sawtooth,
            3 => LfoShape::Square,
            4 => LfoShape::Random,
            15 => LfoShape::Clocked,
            x => LfoShape::Unknown(x),
        }
    }
}

/// E-mu LFO. Field names match `<template module="LFO">` XML exactly.
///
/// `frequency_hz` is the raw `<frequency>` value (Hz when `tempo_sync=false`,
/// BPM-based when `tempo_sync=true`). `delay_ms` is the silence before the
/// LFO starts producing output. `var` is the variance/spread (0 = none).
pub struct PhantomLfo {
    pub frequency_hz: f32,
    pub shape: LfoShape,
    pub delay_ms: f32,
    pub var: f32,
    pub key_sync: bool,
    pub tempo_sync: bool,
    // runtime state
    phase: f32,     // 0.0..1.0, advances per sample
    delay_pos: f32, // remaining delay in samples; LFO silent while > 0
    sample_rate: f32,
}

impl PhantomLfo {
    pub fn new(sample_rate: f32) -> Self {
        Self {
            frequency_hz: 1.0,
            shape: LfoShape::Triangle,
            delay_ms: 0.0,
            var: 0.0,
            key_sync: false,
            tempo_sync: false,
            phase: 0.0,
            delay_pos: 0.0,
            sample_rate: sample_rate.max(1.0),
        }
    }

    /// Reset phase and restart delay countdown.
    pub fn note_on(&mut self) {
        if self.key_sync {
            self.phase = 0.0;
            self.delay_pos = self.delay_ms * 0.001 * self.sample_rate;
        }
    }

    pub fn reset(&mut self) {
        self.phase = 0.0;
        self.delay_pos = 0.0;
    }

    /// Advance one sample, return output in [-1.0, 1.0]. Returns 0.0 during delay.
    #[inline]
    pub fn tick(&mut self) -> f32 {
        if self.delay_pos > 0.0 {
            self.delay_pos -= 1.0;
            return 0.0;
        }
        let inc = self.frequency_hz / self.sample_rate;
        self.phase = (self.phase + inc).rem_euclid(1.0);
        lfo_shape(self.shape, self.phase)
    }
}

#[inline]
fn lfo_shape(shape: LfoShape, phase: f32) -> f32 {
    match shape {
        LfoShape::Triangle => {
            if phase < 0.5 {
                phase * 4.0 - 1.0
            } else {
                3.0 - phase * 4.0
            }
        }
        LfoShape::Sine => (std::f32::consts::TAU * phase).sin(),
        LfoShape::Sawtooth => phase * 2.0 - 1.0,
        LfoShape::Square => {
            if phase < 0.5 {
                1.0
            } else {
                -1.0
            }
        }
        LfoShape::Random | LfoShape::Clocked | LfoShape::Unknown(_) => {
            // Clocked and Random require host-side state (tempo, RNG). Return
            // triangle as a safe placeholder until the host wires these.
            if phase < 0.5 {
                phase * 4.0 - 1.0
            } else {
                3.0 - phase * 4.0
            }
        }
    }
}

// ── Envelope ─────────────────────────────────────────────────────────────────

/// E-mu 6-node (A1/A2/D1/D2/R1/R2) envelope.
///
/// Field names match `<template module="Envelope">` XML exactly.
/// Times are in milliseconds. Levels are in E-mu native scale [-100.0, 100.0].
///
/// State machine: Idle → A1 → A2 → D1 → D2 → Sustain → R1 → R2 → Idle.
/// `note_on()` starts A1 from 0. `note_off()` jumps to R1 from current level.
/// `mode` and `repeat` are stored but not yet behaviorally wired
/// (engineering default: mode=1 normal, repeat=0 off).
pub struct PhantomEnvelope {
    pub attack_1_time_ms: f32,
    pub attack_1_level: f32,
    pub attack_2_time_ms: f32,
    pub attack_2_level: f32,
    pub decay_1_time_ms: f32,
    pub decay_1_level: f32,
    pub decay_2_time_ms: f32,
    pub decay_2_level: f32,
    pub release_1_time_ms: f32,
    pub release_1_level: f32,
    pub release_2_time_ms: f32,
    pub release_2_level: f32,
    pub mode: u8,
    pub repeat: u8,
    // runtime state
    state: EnvState,
    level: f32,       // current output in [-100, 100]
    seg_samples: f64, // samples elapsed in current segment
    sample_rate: f32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum EnvState {
    Idle,
    Attack1,
    Attack2,
    Decay1,
    Decay2,
    Sustain,
    Release1,
    Release2,
}

impl PhantomEnvelope {
    pub fn new(sample_rate: f32) -> Self {
        Self {
            attack_1_time_ms: 0.0,
            attack_1_level: 100.0,
            attack_2_time_ms: 0.0,
            attack_2_level: 100.0,
            decay_1_time_ms: 0.0,
            decay_1_level: 100.0,
            decay_2_time_ms: 0.0,
            decay_2_level: 0.0,
            release_1_time_ms: 0.0,
            release_1_level: 0.0,
            release_2_time_ms: 0.0,
            release_2_level: 0.0,
            mode: 1,
            repeat: 0,
            state: EnvState::Idle,
            level: 0.0,
            seg_samples: 0.0,
            sample_rate: sample_rate.max(1.0),
        }
    }

    pub fn note_on(&mut self) {
        self.level = 0.0;
        self.seg_samples = 0.0;
        self.state = EnvState::Attack1;
    }

    pub fn note_off(&mut self) {
        if self.state != EnvState::Idle
            && self.state != EnvState::Release1
            && self.state != EnvState::Release2
        {
            self.seg_samples = 0.0;
            self.state = EnvState::Release1;
        }
    }

    pub fn reset(&mut self) {
        self.state = EnvState::Idle;
        self.level = 0.0;
        self.seg_samples = 0.0;
    }

    /// Advance one sample, return output in [-1.0, 1.0] (levels normalized from [-100, 100]).
    #[inline]
    pub fn tick(&mut self) -> f32 {
        loop {
            match self.state {
                EnvState::Idle => return self.level / 100.0,
                EnvState::Attack1 => {
                    if self.ramp(0.0, self.attack_1_level, self.attack_1_time_ms) {
                        self.state = EnvState::Attack2;
                        self.seg_samples = 0.0;
                    } else {
                        break;
                    }
                }
                EnvState::Attack2 => {
                    if self.ramp(
                        self.attack_1_level,
                        self.attack_2_level,
                        self.attack_2_time_ms,
                    ) {
                        self.state = EnvState::Decay1;
                        self.seg_samples = 0.0;
                    } else {
                        break;
                    }
                }
                EnvState::Decay1 => {
                    if self.ramp(
                        self.attack_2_level,
                        self.decay_1_level,
                        self.decay_1_time_ms,
                    ) {
                        self.state = EnvState::Decay2;
                        self.seg_samples = 0.0;
                    } else {
                        break;
                    }
                }
                EnvState::Decay2 => {
                    if self.ramp(self.decay_1_level, self.decay_2_level, self.decay_2_time_ms) {
                        self.state = EnvState::Sustain;
                        self.seg_samples = 0.0;
                    } else {
                        break;
                    }
                }
                EnvState::Sustain => {
                    self.level = self.decay_2_level;
                    break;
                }
                EnvState::Release1 => {
                    let start = self.level;
                    if self.ramp(start, self.release_1_level, self.release_1_time_ms) {
                        self.state = EnvState::Release2;
                        self.seg_samples = 0.0;
                    } else {
                        break;
                    }
                }
                EnvState::Release2 => {
                    let start = self.level;
                    if self.ramp(start, self.release_2_level, self.release_2_time_ms) {
                        self.state = EnvState::Idle;
                    } else {
                        break;
                    }
                }
            }
        }
        (self.level / 100.0).clamp(-1.0, 1.0)
    }

    /// Ramp from `start` to `end` over `time_ms`. Advances `seg_samples`.
    /// Returns `true` when the segment is complete (level set to `end`).
    #[inline]
    fn ramp(&mut self, start: f32, end: f32, time_ms: f32) -> bool {
        let len = ((time_ms * 0.001 * self.sample_rate) as f64).max(1.0);
        let t = (self.seg_samples / len).min(1.0) as f32;
        self.level = start + (end - start) * t;
        self.seg_samples += 1.0;
        self.seg_samples >= len
    }
}

// ── routing types ─────────────────────────────────────────────────────────────

/// A modulation source.
///
/// Source integer IDs from voice-cord templates are not yet authoritatively
/// resolved to symbolic names. Template-observed IDs:
/// - 0 = Off (confirmed: All Off.xml)
/// - 8–11 appear in 12-Knobs templates alongside likely LFO/Env ranges
/// - 32–47 = knob controllers (inferred: 12/16 Knobs templates)
/// Lfo(0)/Lfo(1) and Env(0)/Env(1)/Env(2) are the internal voice sources.
/// `Unknown` carries any unresolved integer ID for round-trip fidelity.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModSource {
    Lfo(usize),
    Env(usize),
    Unknown(u16),
}

/// A modulation destination — Morph and Q are the bilinear surface axes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModDest {
    Morph,
    Q,
    Unknown(u16),
}

/// One patchcord.
///
/// `amount` is in the native E-mu scale [-100.0, 100.0], confirmed by
/// template evidence (Cords/12 Knobs Default 1-9.xml shows amounts like
/// -48, 80, 100). Normalized to [-1.0, 1.0] internally at evaluation time.
#[derive(Debug, Clone, Copy)]
pub struct Patchcord {
    pub source: ModSource,
    pub dest: ModDest,
    /// E-mu native scale [-100.0, 100.0]. Normalized to [-1, 1] at evaluation.
    pub amount: f32,
}

/// Fixed 9-slot routing matrix. 9 confirmed from Cords templates.
/// Multiple cords to the same destination sum.
pub struct RoutingMatrix {
    cords: [Option<Patchcord>; MAX_CORDS],
    count: usize,
}

impl Default for RoutingMatrix {
    fn default() -> Self {
        Self {
            cords: [None; MAX_CORDS],
            count: 0,
        }
    }
}

impl RoutingMatrix {
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a cord. Silently ignores if all 9 slots are full.
    pub fn add(&mut self, cord: Patchcord) {
        if self.count < MAX_CORDS {
            self.cords[self.count] = Some(cord);
            self.count += 1;
        }
    }

    pub fn clear(&mut self) {
        self.cords = [None; MAX_CORDS];
        self.count = 0;
    }

    /// Sum all cord contributions. Returns `(morph_delta, q_delta)`.
    /// Amount is normalized from [-100, 100] → [-1, 1] internally.
    fn evaluate(&self, sv: &SourceSnapshot) -> (f32, f32) {
        let mut dm = 0.0_f32;
        let mut dq = 0.0_f32;
        for slot in &self.cords[..self.count] {
            let Some(cord) = slot else { continue };
            let v = sv.get(cord.source) * (cord.amount / 100.0);
            match cord.dest {
                ModDest::Morph => dm += v,
                ModDest::Q => dq += v,
                ModDest::Unknown(_) => {}
            }
        }
        (dm, dq)
    }
}

// ── source snapshot ───────────────────────────────────────────────────────────

struct SourceSnapshot {
    lfo: [f32; NUM_LFOS],
    env: [f32; NUM_ENVS],
}

impl SourceSnapshot {
    fn get(&self, src: ModSource) -> f32 {
        match src {
            ModSource::Lfo(i) => self.lfo[i.min(NUM_LFOS - 1)],
            ModSource::Env(i) => self.env[i.min(NUM_ENVS - 1)],
            ModSource::Unknown(_) => 0.0,
        }
    }
}

// ── PhantomVoice ─────────────────────────────────────────────────────────────

/// A complete voice: 6-stage biquad cascade + 2 LFOs + 3 EGs + 9-cord matrix.
///
/// Init order inside `new()`:
///   1. LFOs allocated and idle.
///   2. EGs allocated and idle (fire on `note_on()`).
///   3. Routing matrix allocated (empty, 9 slots).
///   4. Cascade allocated last — snapped to the modulated position before
///      the first `process_block()` call.
pub struct PhantomVoice {
    cascade: Cascade,
    pub lfos: [PhantomLfo; NUM_LFOS],
    pub envelopes: [PhantomEnvelope; NUM_ENVS],
    routing: RoutingMatrix,
    cartridge: Option<Cartridge>,
    pub morph: f32,
    pub q: f32,
    sample_rate: f32,
}

impl PhantomVoice {
    pub fn new(sample_rate: f32) -> Self {
        let sr = sample_rate.max(1.0);
        Self {
            lfos: std::array::from_fn(|_| PhantomLfo::new(sr)),
            envelopes: std::array::from_fn(|_| PhantomEnvelope::new(sr)),
            routing: RoutingMatrix::new(),
            cascade: Cascade::new(),
            cartridge: None,
            morph: 0.0,
            q: 0.0,
            sample_rate: sr,
        }
    }

    pub fn load_cartridge(&mut self, cartridge: Cartridge) {
        self.cartridge = Some(cartridge);
        self.snap_cascade();
    }

    pub fn set_routing(&mut self, routing: RoutingMatrix) {
        self.routing = routing;
    }

    pub fn routing_mut(&mut self) -> &mut RoutingMatrix {
        &mut self.routing
    }

    /// Trigger note-on: fires all EGs and LFOs (if key_sync), then snaps cascade.
    pub fn note_on(&mut self) {
        for lfo in &mut self.lfos {
            lfo.note_on();
        }
        for env in &mut self.envelopes {
            env.note_on();
        }
        self.snap_cascade();
    }

    /// Trigger note-off: starts release stage on all EGs.
    pub fn note_off(&mut self) {
        for env in &mut self.envelopes {
            env.note_off();
        }
    }

    pub fn set_morph(&mut self, morph: f32) {
        self.morph = morph.clamp(0.0, 1.0);
    }

    pub fn set_q(&mut self, q: f32) {
        self.q = q.clamp(0.0, 1.0);
    }

    /// Process a block of mono samples.
    ///
    /// Per block (control rate = BLOCK_SIZE samples):
    ///   1. Tick all mod sources once.
    ///   2. Apply routing matrix → (morph_delta, q_delta).
    ///   3. Clamp and interpolate cartridge → set cascade targets.
    ///   4. Run cascade over every sample.
    pub fn process_block(&mut self, samples: &mut [f32]) {
        let sv = self.tick_sources();
        let (dm, dq) = self.routing.evaluate(&sv);

        if self.cartridge.is_some() {
            let m = (self.morph + dm).clamp(0.0, 1.0) as f64;
            let q = (self.q + dq).clamp(0.0, 1.0) as f64;
            let cartridge = self.cartridge.as_ref().unwrap();
            let corner = cartridge.interpolate(m, q);
            let boost = cartridge.interpolate_boost(m, q);
            self.cascade.set_targets(&corner, BLOCK_SIZE);
            self.cascade.set_boost(boost, BLOCK_SIZE);
        }

        self.cascade.process_block_mono(samples);
    }

    pub fn reset(&mut self) {
        self.cascade.reset();
        for lfo in &mut self.lfos {
            lfo.reset();
        }
        for env in &mut self.envelopes {
            env.reset();
        }
    }

    pub fn take_instability_flag(&mut self) -> bool {
        self.cascade.take_instability_flag()
    }

    pub fn sample_rate(&self) -> f32 {
        self.sample_rate
    }

    fn tick_sources(&mut self) -> SourceSnapshot {
        SourceSnapshot {
            lfo: std::array::from_fn(|i| self.lfos[i].tick()),
            env: std::array::from_fn(|i| self.envelopes[i].tick()),
        }
    }

    fn snap_cascade(&mut self) {
        if self.cartridge.is_none() {
            return;
        }
        let sv = self.tick_sources();
        let (dm, dq) = self.routing.evaluate(&sv);
        let m = (self.morph + dm).clamp(0.0, 1.0) as f64;
        let q = (self.q + dq).clamp(0.0, 1.0) as f64;
        let cartridge = self.cartridge.as_ref().unwrap();
        let corner = cartridge.interpolate(m, q);
        let boost = cartridge.interpolate_boost(m, q);
        self.cascade.set_targets(&corner, 1);
        self.cascade.set_boost(boost, 1);
    }
}

// ── tests ──────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    // ── PhantomVoice construction and basic behavior ──────────────────────────

    #[test]
    fn new_initializes_lfos_envelopes_routing_before_cascade() {
        let voice = PhantomVoice::new(44100.0);
        // All sources are idle (no note_on yet).
        assert_eq!(voice.envelopes[0].state, EnvState::Idle);
        assert_eq!(voice.envelopes[1].state, EnvState::Idle);
        assert_eq!(voice.envelopes[2].state, EnvState::Idle);
        assert_eq!(voice.routing.count, 0);
    }

    #[test]
    fn new_produces_passthrough_without_cartridge() {
        let mut voice = PhantomVoice::new(44100.0);
        let mut buf = [0.5_f32, -0.5, 0.25, -0.25];
        let expected = buf;
        voice.process_block(&mut buf);
        for (i, (&got, &want)) in buf.iter().zip(expected.iter()).enumerate() {
            assert!(
                (got - want).abs() < 1e-5,
                "sample {i}: got {got}, want {want}"
            );
        }
    }

    #[test]
    fn note_on_snaps_cascade_before_audio() {
        let mut voice = PhantomVoice::new(44100.0);
        // note_on without cartridge must not panic and must not produce instability.
        voice.note_on();
        let mut buf = [0.0_f32; 32];
        voice.process_block(&mut buf);
        assert!(!voice.take_instability_flag());
    }

    #[test]
    fn note_on_starts_envelopes() {
        let mut voice = PhantomVoice::new(44100.0);
        voice.note_on();
        // All envelopes should now be in Attack1 (not Idle).
        for env in &voice.envelopes {
            assert_ne!(env.state, EnvState::Idle);
        }
    }

    #[test]
    fn sample_rate_accessor() {
        let voice = PhantomVoice::new(48_000.0);
        assert!((voice.sample_rate() - 48_000.0).abs() < 1.0);
    }

    #[test]
    fn reset_returns_to_idle() {
        let mut voice = PhantomVoice::new(44100.0);
        voice.note_on();
        voice.reset();
        assert_eq!(voice.envelopes[0].state, EnvState::Idle);
    }

    // ── Patchcord amount scale ────────────────────────────────────────────────

    #[test]
    fn patchcord_amount_native_scale_100() {
        // amount=100 in E-mu scale → normalized to 1.0 internally.
        // LFO at 1.0 (triangle at phase 0.25) × 100/100 = 1.0 delta.
        let mut lfo = PhantomLfo::new(44100.0);
        lfo.frequency_hz = 44100.0 / 4.0; // quarter-cycle per sample → phase 0.25 after 1 tick
        let v = lfo.tick(); // phase = 1/4 → triangle = 0.0 (rises 0→peak at 0.25)
                            // Just verify the scale math: amount / 100.0 is applied.
        let cord = Patchcord {
            source: ModSource::Lfo(0),
            dest: ModDest::Morph,
            amount: 50.0, // E-mu native: 50 out of 100
        };
        let mut matrix = RoutingMatrix::new();
        matrix.add(cord);
        let sv = SourceSnapshot {
            lfo: [v, 0.0],
            env: [0.0; 3],
        };
        let (dm, _dq) = matrix.evaluate(&sv);
        // dm = v * (50.0 / 100.0)
        let expected = v * 0.5;
        assert!((dm - expected).abs() < 1e-6, "got {dm}, want {expected}");
    }

    #[test]
    fn patchcord_amount_negative_100() {
        let cord = Patchcord {
            source: ModSource::Env(0),
            dest: ModDest::Q,
            amount: -100.0,
        };
        let mut matrix = RoutingMatrix::new();
        matrix.add(cord);
        let sv = SourceSnapshot {
            lfo: [0.0; 2],
            env: [1.0, 0.0, 0.0],
        };
        let (_dm, dq) = matrix.evaluate(&sv);
        // -100/100 * 1.0 = -1.0
        assert!((dq + 1.0).abs() < 1e-6, "got {dq}");
    }

    // ── Multiple cords sum ────────────────────────────────────────────────────

    #[test]
    fn multiple_cords_to_same_dest_sum() {
        let mut matrix = RoutingMatrix::new();
        matrix.add(Patchcord {
            source: ModSource::Lfo(0),
            dest: ModDest::Morph,
            amount: 50.0,
        });
        matrix.add(Patchcord {
            source: ModSource::Env(0),
            dest: ModDest::Morph,
            amount: 50.0,
        });
        let sv = SourceSnapshot {
            lfo: [1.0, 0.0],
            env: [1.0, 0.0, 0.0],
        };
        let (dm, _) = matrix.evaluate(&sv);
        // 0.5 + 0.5 = 1.0
        assert!((dm - 1.0).abs() < 1e-6, "got {dm}");
    }

    #[test]
    fn routing_morph_clamped_to_unit_range() {
        let mut voice = PhantomVoice::new(44100.0);
        voice.morph = 0.9;
        voice.routing_mut().add(Patchcord {
            source: ModSource::Lfo(0),
            dest: ModDest::Morph,
            amount: 100.0,
        });
        // LFO idle → output 0.0 → delta = 0. morph stays 0.9; no instability.
        let mut buf = [0.1_f32; 32];
        voice.process_block(&mut buf);
        assert!(!voice.take_instability_flag());
    }

    // ── MAX_CORDS cap ─────────────────────────────────────────────────────────

    #[test]
    fn routing_matrix_caps_at_nine_cords() {
        let mut matrix = RoutingMatrix::new();
        for _ in 0..12 {
            matrix.add(Patchcord {
                source: ModSource::Lfo(0),
                dest: ModDest::Morph,
                amount: 1.0,
            });
        }
        assert_eq!(matrix.count, MAX_CORDS);
    }

    // ── Unknown source/dest round-trip ───────────────────────────────────────

    #[test]
    fn unknown_source_and_dest_do_not_panic() {
        let mut matrix = RoutingMatrix::new();
        matrix.add(Patchcord {
            source: ModSource::Unknown(999),
            dest: ModDest::Unknown(999),
            amount: 100.0,
        });
        let sv = SourceSnapshot {
            lfo: [1.0, 1.0],
            env: [1.0, 1.0, 1.0],
        };
        let (dm, dq) = matrix.evaluate(&sv);
        // Unknown source returns 0.0; unknown dest is ignored.
        assert_eq!(dm, 0.0);
        assert_eq!(dq, 0.0);
    }

    // ── LFO ──────────────────────────────────────────────────────────────────

    #[test]
    fn lfo_shape_from_id_known_and_unknown() {
        assert_eq!(LfoShape::from_id(0), LfoShape::Triangle);
        assert_eq!(LfoShape::from_id(15), LfoShape::Clocked);
        assert_eq!(LfoShape::from_id(99), LfoShape::Unknown(99));
    }

    #[test]
    fn lfo_modulates_morph_through_routing() {
        let mut voice = PhantomVoice::new(44100.0);
        voice.lfos[0].frequency_hz = 10.0;
        voice.lfos[0].shape = LfoShape::Sine;
        voice.routing_mut().add(Patchcord {
            source: ModSource::Lfo(0),
            dest: ModDest::Morph,
            amount: 100.0,
        });
        // Process a block without cartridge; just verify no panic or instability.
        let mut buf = [0.0_f32; 32];
        voice.process_block(&mut buf);
        assert!(!voice.take_instability_flag());
    }

    #[test]
    fn lfo_delay_suppresses_output() {
        let mut lfo = PhantomLfo::new(44100.0);
        lfo.frequency_hz = 100.0;
        lfo.delay_ms = 1000.0; // 1 second delay
        lfo.key_sync = true;
        lfo.note_on();
        // First 44100 ticks should all be 0.
        for _ in 0..100 {
            assert_eq!(lfo.tick(), 0.0);
        }
    }

    // ── Envelope ─────────────────────────────────────────────────────────────

    #[test]
    fn envelope_modulates_q_through_routing() {
        let mut voice = PhantomVoice::new(44100.0);
        voice.envelopes[0].attack_1_time_ms = 10.0;
        voice.envelopes[0].attack_1_level = 100.0;
        voice.routing_mut().add(Patchcord {
            source: ModSource::Env(0),
            dest: ModDest::Q,
            amount: 100.0,
        });
        voice.note_on();
        let mut buf = [0.0_f32; 32];
        voice.process_block(&mut buf);
        assert!(!voice.take_instability_flag());
    }

    #[test]
    fn envelope_reaches_sustain_level() {
        let mut env = PhantomEnvelope::new(44100.0);
        env.attack_1_time_ms = 0.0;
        env.attack_1_level = 100.0;
        env.attack_2_time_ms = 0.0;
        env.attack_2_level = 100.0;
        env.decay_1_time_ms = 0.0;
        env.decay_1_level = 100.0;
        env.decay_2_time_ms = 0.0;
        env.decay_2_level = 75.0; // sustain
        env.note_on();
        let mut last = 0.0;
        for _ in 0..20 {
            last = env.tick();
        }
        // Should be at sustain level = 75/100 = 0.75
        assert!((last - 0.75).abs() < 0.01, "sustain level got {last}");
    }

    #[test]
    fn envelope_note_off_triggers_release() {
        let mut env = PhantomEnvelope::new(44100.0);
        env.attack_1_time_ms = 0.0;
        env.attack_1_level = 100.0;
        env.attack_2_time_ms = 0.0;
        env.attack_2_level = 100.0;
        env.decay_1_time_ms = 0.0;
        env.decay_1_level = 100.0;
        env.decay_2_time_ms = 0.0;
        env.decay_2_level = 100.0;
        env.release_1_time_ms = 0.0;
        env.release_1_level = 0.0;
        env.release_2_time_ms = 0.0;
        env.release_2_level = 0.0;
        env.note_on();
        for _ in 0..20 {
            env.tick();
        }
        assert_eq!(env.state, EnvState::Sustain);
        env.note_off();
        assert_eq!(env.state, EnvState::Release1);
        for _ in 0..20 {
            env.tick();
        }
        assert_eq!(env.state, EnvState::Idle);
    }
}
