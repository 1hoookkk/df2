// Peak/Shelf Morph authoring grammar (the Dillusion workflow).
//
// A patch is two morph frames — LOW and HIGH — each described by three
// controls (FREQ Hz, SHELF −64..+63, PEAK dB), plus global PRESSURE (Q /
// resonance amount, shapes the Q100 corners) and MASTER (overall level).
//
// compile_peak_shelf() turns a patch into exactly six pole-zero sections:
// the LOW frame fills corners C0 (M0 Q0) and C2 (M0 Q100), the HIGH frame
// fills C1 (M100 Q0) and C3 (M100 Q100); PRESSURE is applied to C2/C3 only.
// Section index is the morph pairing — lane i of the LOW frame morphs into
// lane i of the HIGH frame. Every lane is a pole+zero pair (the cascade is
// serial; a zeroless section's rolloff would bury everything behind it).
//
// Stability is judged downstream by the 17×17 packed audit on the real
// packed words. This compiler clamps to the format's hard limits (RP_MAX,
// RZ_MAX) and does nothing else to "fix" a dangerous patch — the lamp and
// KEEP refusal are the truth tellers, never a silent rescue here.

use serde::{Deserialize, Serialize};

use crate::{CornerStage, Section, CORNERS, F_MAX, F_MIN, GAIN_DB_MAX, GAIN_DB_MIN, RP_MAX, RZ_MAX};

#[derive(Clone, Copy, Serialize, Deserialize)]
pub struct FrameControls {
    /// the frame's main frequency (cutoff / band center / knee, per SHELF)
    pub freq_hz: f32,
    /// −64 low-pass ↔ 0 mid shelf ↔ +63 high-pass (hardware range)
    pub shelf: f32,
    /// frame emphasis in dB: resonant boost (+) or dip (−) at the action
    pub peak_db: f32,
}

#[derive(Clone, Serialize, Deserialize)]
pub struct PeakShelfPatch {
    pub name: String,
    pub low: FrameControls,
    pub high: FrameControls,
    /// runtime position between the frames (not baked into corners)
    pub morph: f32,
    /// 0..1 — pole radius / zero focus on the Q100 corners
    pub pressure: f32,
    /// flat level policy spread across the lanes, audited post-pack
    pub master_peak_db: f32,
}

impl Default for PeakShelfPatch {
    fn default() -> Self {
        Self {
            name: "peak shelf".into(),
            low: FrameControls {
                freq_hz: 320.0,
                shelf: -32.0,
                peak_db: 4.0,
            },
            high: FrameControls {
                freq_hz: 2400.0,
                shelf: 16.0,
                peak_db: 6.0,
            },
            morph: 0.0,
            // full baked Q contrast: the runtime PRESSURE axis (Q0 → Q100)
            // sweeps from the tame rows into these — pressure here is how far
            // the Q100 corners go, not where the knob sits
            pressure: 1.0,
            master_peak_db: 0.0,
        }
    }
}

/// SHELF region weights: a plain crossfade between three textbook behaviors.
/// s = shelf/64 ∈ [−1, +1); the partition always sums to 1.
pub fn shelf_weights(shelf: f32) -> (f32, f32, f32) {
    let s = (shelf / 64.0).clamp(-1.0, 1.0);
    let w_lp = (-s / 0.6).clamp(0.0, 1.0);
    let w_hp = (s / 0.6).clamp(0.0, 1.0);
    let w_ms = (1.0 - w_lp - w_hp).max(0.0);
    (w_lp, w_ms, w_hp)
}

/// Pole radius that puts a resonant boost of `db` over the lane's flat
/// baseline against a fixed zero at radius `rz` (peak height ≈
/// 20·log10((1−rz)/(1−rp)) for a pole/zero pair sharing a frequency).
fn radius_for_boost(db: f32, rz: f32) -> f32 {
    let rp = 1.0 - (1.0 - rz) / 10f32.powf(db / 20.0);
    rp.clamp(0.5, RP_MAX)
}

/// One frame → six lane postures (pole_hz, pole_r, zero_hz, zero_r, gain_db).
/// Roles, in cascade order: low shelf · bass · peak · notch · high peak ·
/// high cut. Constants are ear-tunable; the role structure is the contract.
fn frame_lanes(fc: &FrameControls, master_db: f32) -> [CornerStage; 6] {
    let f = fc.freq_hz.clamp(F_MIN, F_MAX);
    let g = fc.peak_db.clamp(GAIN_DB_MIN, GAIN_DB_MAX);
    let (w_lp, w_ms, w_hp) = shelf_weights(fc.shelf);
    let lane_gain = (master_db / 6.0).clamp(GAIN_DB_MIN, GAIN_DB_MAX);
    let hz = |v: f32| v.clamp(F_MIN, F_MAX);

    // 1 · low shelf — second-order tilt step from the pole/zero frequency
    // ratio: zero above pole = step down into the highs (low-pass-like),
    // zero below pole = step up (high-pass-like), ratio 1 = flat hand-off
    // to the peak lane in the mid-shelf region.
    let tilt_ratio = 4.0 * w_lp + 1.0 * w_ms + 0.25 * w_hp;
    let shelf_lane = CornerStage {
        pole_hz: f,
        pole_r: 0.85,
        zero_hz: hz(f * tilt_ratio),
        zero_r: 0.85,
        gain_db: lane_gain,
    };

    // 2 · bass — flat-topped low hold (the booms stay uncut while the upper
    // lanes sweep): a modest fixed boost bump at max(70, f/4).
    let bass_lane = CornerStage {
        pole_hz: hz((f * 0.25).max(70.0)),
        pole_r: 0.90,
        zero_hz: hz((f * 0.25).max(70.0)),
        zero_r: 0.82,
        gain_db: lane_gain,
    };

    // 3 · peak — the frame's main emphasis at FREQ; PEAK dB sets the boost
    // (or dip when negative) through the pole/zero radius gap, scaled by the
    // mid-shelf weight so it hands off to the tilt lanes at the extremes.
    let peak_db = g * (0.35 + 0.65 * w_ms);
    let peak_lane = if peak_db >= 0.0 {
        CornerStage {
            pole_hz: f,
            pole_r: radius_for_boost(peak_db, 0.85),
            zero_hz: f,
            zero_r: 0.85,
            gain_db: lane_gain,
        }
    } else {
        CornerStage {
            pole_hz: f,
            pole_r: 0.85,
            zero_hz: f,
            zero_r: radius_for_boost(-peak_db, 0.85).min(RZ_MAX),
            gain_db: lane_gain,
        }
    };

    // 4 · notch — a moving anti-resonance above the action; deepest in the
    // blend regions where the tilt and peak lanes trade places.
    let notch_depth = 0.93 + 0.04 * (1.0 - w_ms);
    let notch_lane = CornerStage {
        pole_hz: hz(f * 1.6),
        pole_r: 0.80,
        zero_hz: hz(f * 1.6),
        zero_r: notch_depth.min(RZ_MAX),
        gain_db: lane_gain,
    };

    // 5 · high peak — edge energy in the high-pass region.
    let edge_db = (g * 0.7 * w_hp).max(0.0);
    let edge_lane = CornerStage {
        pole_hz: hz((f * 3.0).min(8000.0)),
        pole_r: radius_for_boost(edge_db, 0.85),
        zero_hz: hz((f * 3.0).min(8000.0)),
        zero_r: 0.85,
        gain_db: lane_gain,
    };

    // 6 · high cut — gentle restraint step above 10 kHz so the cascade
    // doesn't ship raw air.
    let cut_lane = CornerStage {
        pole_hz: 10_000.0,
        pole_r: 0.75,
        zero_hz: 14_000.0,
        zero_r: 0.75,
        gain_db: lane_gain,
    };

    [
        shelf_lane, bass_lane, peak_lane, notch_lane, edge_lane, cut_lane,
    ]
}

/// PRESSURE on a Q0 lane → its Q100 posture. Pole radii close on 1 with the
/// measured Q-link shape (factor 0.35 at full pressure — the proven rule);
/// the notch zero focuses deeper; gain gets a half-compensating trim so the
/// bloom gets sharper *and* louder without instantly clipping. A level
/// policy only — instability stays visible to the packed audit.
fn pressurize(lane: CornerStage, pressure: f32, is_notch: bool) -> CornerStage {
    let p = pressure.clamp(0.0, 1.0);
    let mut out = lane;
    let r0 = lane.pole_r;
    out.pole_r = (1.0 - (1.0 - r0) * (1.0 - 0.65 * p)).clamp(0.5, RP_MAX);
    if is_notch {
        out.zero_r = (1.0 - (1.0 - lane.zero_r) * (1.0 - 0.5 * p)).clamp(0.0, RZ_MAX);
    }
    let trim = 0.5 * p * 20.0 * ((1.0 - r0) / (1.0 - out.pole_r)).log10();
    out.gain_db = (lane.gain_db - trim).clamp(GAIN_DB_MIN, GAIN_DB_MAX);
    out
}

pub const LANE_ROLES: [&str; 6] = ["low shelf", "bass", "peak", "notch", "high peak", "high cut"];
const NOTCH_LANE: usize = 3;

/// Compile the patch to the six runtime sections. Corners: C0 = low frame
/// Q0, C1 = high frame Q0, C2 = low frame Q100, C3 = high frame Q100.
pub fn compile_peak_shelf(patch: &PeakShelfPatch) -> Vec<Section> {
    let low = frame_lanes(&patch.low, patch.master_peak_db);
    let high = frame_lanes(&patch.high, patch.master_peak_db);
    (0..6)
        .map(|i| {
            let is_notch = i == NOTCH_LANE;
            let mut corners = [low[i]; CORNERS];
            corners[1] = high[i];
            corners[2] = pressurize(low[i], patch.pressure, is_notch);
            corners[3] = pressurize(high[i], patch.pressure, is_notch);
            Section {
                on: true,
                locked: false,
                role: LANE_ROLES[i].to_string(),
                corners,
            }
        })
        .collect()
}
