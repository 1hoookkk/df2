//! Motor modulation primitive.
//!
//! Ported from `archive/trench-atlas/src/motor.rs`. A Motor is an authored
//! morph driver: it defines a home point on the (morph, q) surface, a vector
//! to travel along under force, rise/fall timing, a force curve character,
//! and an LFO rate/depth. Motors are the mechanism that turns a static body
//! into an instrument the user plays.
//!
//! The `vector_morph`/`vector_q` pair supports diagonal trajectories on the
//! (m, q) surface. Non-zero `vector_q` is the vehicle for exploiting the
//! `Δmq` cross-term identified in `docs/modulation_exploration.md` as the
//! highest-yield research bet for TRENCH modulation.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct MotorId(pub u32);

impl Motor {
    /// Position on the (morph, q) surface at force `t ∈ [0, 1]`.
    /// Returns `(morph, q)` with each component clamped to `[0, 1]`.
    pub fn position_at(&self, t: f32) -> (f32, f32) {
        let m = (self.home_morph + self.vector_morph * t).clamp(0.0, 1.0);
        let q = (self.home_q + self.vector_q * t).clamp(0.0, 1.0);
        (m, q)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ForceCurve {
    Linear,
    Exponential,
    Logarithmic,
    SCurve,
    Impulse,
    Breathing,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Motor {
    pub id: MotorId,
    pub name: String,
    pub home_morph: f32,
    pub home_q: f32,
    pub vector_morph: f32,
    pub vector_q: f32,
    pub rise_ms: f32,
    pub fall_ms: f32,
    pub curve: ForceCurve,
    pub lfo_rate_hz: f32,
    pub lfo_depth: f32,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn motor_serde_roundtrip() {
        let m = Motor {
            id: MotorId(1),
            name: "Snap-Rip".to_string(),
            home_morph: 0.0,
            home_q: 0.0,
            vector_morph: 0.8,
            vector_q: -0.6,
            rise_ms: 18.0,
            fall_ms: 420.0,
            curve: ForceCurve::Impulse,
            lfo_rate_hz: 0.0,
            lfo_depth: 0.0,
        };
        let json = serde_json::to_string(&m).unwrap();
        let back: Motor = serde_json::from_str(&json).unwrap();
        assert_eq!(back.id, m.id);
        assert_eq!(back.name, m.name);
        assert_eq!(back.vector_morph, 0.8);
        assert_eq!(back.vector_q, -0.6);
        assert!(matches!(back.curve, ForceCurve::Impulse));
    }

    #[test]
    fn diagonal_motor_has_nonzero_q_vector() {
        let m = Motor {
            id: MotorId(42),
            name: "Diagonal".to_string(),
            home_morph: 0.0,
            home_q: 0.0,
            vector_morph: 0.5,
            vector_q: -0.5,
            rise_ms: 25.0,
            fall_ms: 300.0,
            curve: ForceCurve::SCurve,
            lfo_rate_hz: 0.0,
            lfo_depth: 0.0,
        };
        assert!(m.vector_q.abs() > f32::EPSILON);
        assert!(m.vector_morph.abs() > f32::EPSILON);
    }
}
