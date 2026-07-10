//! FORGE MODEL — the design source of truth.
//!
//! A [`Design`] is modes with identity at multiple anchors:
//! each [`Anchor`] is a pose of the same ordered modes at one (morph, q)
//! wheel position, and each [`Mode`] is a pole pair + zero pair + gain.
//! The 240-byte packed body is a PROJECTION of this model (see
//! [`packed::project`]), never the model itself.
//!
//! Mode identity = index. `anchors[a].modes[i]` and `anchors[b].modes[i]`
//! are the SAME mode at two poses — that is the lane correspondence law.

use serde::{Deserialize, Serialize};

pub mod packed;

pub use trench_core::compiler::AUTHORING_SR;

const TAU: f64 = std::f64::consts::TAU;

/// A quadratic's roots: a conjugate pair at (hz, r), or two real roots when
/// the pair has split onto the real axis. `Pair { r: 0.0 }` means no roots
/// (a constant numerator / no zero).
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub enum RootPair {
    Pair { hz: f64, r: f64 },
    Split { z1: f64, z2: f64 },
}

impl RootPair {
    /// Monic quadratic coefficients (a1, a2) of z² + a1·z + a2.
    pub fn quad(&self) -> (f64, f64) {
        match *self {
            RootPair::Pair { hz, r } => {
                let w = TAU * hz / AUTHORING_SR;
                (-2.0 * r * w.cos(), r * r)
            }
            RootPair::Split { z1, z2 } => (-(z1 + z2), z1 * z2),
        }
    }

    /// Factor a monic quadratic z² + a1·z + a2 back into roots.
    pub fn from_quad(a1: f64, a2: f64) -> Self {
        let disc = a1 * a1 - 4.0 * a2;
        if disc < 0.0 {
            let r = a2.sqrt();
            let hz = (-a1 / (2.0 * r)).clamp(-1.0, 1.0).acos() * AUTHORING_SR / TAU;
            RootPair::Pair { hz, r }
        } else if a1 == 0.0 && a2 == 0.0 {
            RootPair::Pair { hz: 0.0, r: 0.0 }
        } else {
            let s = disc.sqrt();
            RootPair::Split {
                z1: (-a1 + s) / 2.0,
                z2: (-a1 - s) / 2.0,
            }
        }
    }

    /// Largest root magnitude (the stability radius for a pole pair).
    pub fn radius(&self) -> f64 {
        match *self {
            RootPair::Pair { r, .. } => r.abs(),
            RootPair::Split { z1, z2 } => z1.abs().max(z2.abs()),
        }
    }
}

/// One mode: a pole pair, a zero pair, and the section gain (b0).
/// `active` is reserved for mode activation (surface it3); the packed
/// projection treats `active <= 0` as an identity section and anything
/// else as fully on.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct Mode {
    pub pole: RootPair,
    pub zero: RootPair,
    pub gain: f64,
    #[serde(default = "one")]
    pub active: f64,
}

fn one() -> f64 {
    1.0
}

/// The identity section: passes audio through untouched.
pub const IDENTITY: Mode = Mode {
    pole: RootPair::Pair { hz: 0.0, r: 0.0 },
    zero: RootPair::Pair { hz: 0.0, r: 0.0 },
    gain: 1.0,
    active: 1.0,
};

impl Mode {
    /// The section as an a0-normalized biquad row [b0, b1, b2, a1, a2].
    pub fn biquad(&self) -> [f64; 5] {
        if self.active <= 0.0 {
            return [1.0, 0.0, 0.0, 0.0, 0.0];
        }
        let (a1, a2) = self.pole.quad();
        let (n1, n2) = self.zero.quad();
        [self.gain, self.gain * n1, self.gain * n2, a1, a2]
    }

    /// A conjugate pole + conjugate zero mode with the DC-normalized gain
    /// law the legacy authoring path uses — byte-identical to what the
    /// forge-zero surface packs, because it routes through the one owner
    /// (`trench_core::compiler::stage_biquad`).
    pub fn pole_zero(pole_hz: f64, pole_r: f64, zero_hz: f64, zero_r: f64) -> Self {
        Mode::from_biquad(trench_core::compiler::stage_biquad(&[
            1.0,
            pole_hz,
            pole_r,
            1.0,
            if zero_r > 0.0001 { 1.0 } else { 0.0 },
            zero_hz,
            zero_r,
        ]))
    }

    /// Recover a mode from a biquad row. A `b0 == 0` row (a silenced
    /// section) keeps its pole and reports a rootless zero.
    pub fn from_biquad(b: [f64; 5]) -> Self {
        let zero = if b[0] == 0.0 {
            RootPair::Pair { hz: 0.0, r: 0.0 }
        } else {
            RootPair::from_quad(b[1] / b[0], b[2] / b[0])
        };
        Mode {
            pole: RootPair::from_quad(b[3], b[4]),
            zero,
            gain: b[0],
            active: 1.0,
        }
    }
}

/// One pose of the design's modes at a wheel position.
/// morph and q are wheel coordinates in 0..=1 — positions, never sound.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Anchor {
    pub morph: f64,
    pub q: f64,
    pub modes: Vec<Mode>,
}

/// The design: named, multi-anchor, modes aligned by index across anchors.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Design {
    pub name: String,
    pub anchors: Vec<Anchor>,
}

impl Design {
    pub fn to_json(&self) -> String {
        serde_json::to_string_pretty(self).expect("Design serializes")
    }

    pub fn from_json(s: &str) -> Result<Self, serde_json::Error> {
        serde_json::from_str(s)
    }

    /// The anchor at a wheel corner, if one is authored there.
    pub fn anchor_at(&self, morph: f64, q: f64) -> Option<&Anchor> {
        self.anchors
            .iter()
            .find(|a| (a.morph - morph).abs() < 1e-9 && (a.q - q).abs() < 1e-9)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn root_pair_quad_roundtrip_conjugate() {
        let p = RootPair::Pair { hz: 740.0, r: 0.97 };
        let (a1, a2) = p.quad();
        match RootPair::from_quad(a1, a2) {
            RootPair::Pair { hz, r } => {
                assert!((hz - 740.0).abs() < 1e-6, "hz={hz}");
                assert!((r - 0.97).abs() < 1e-12, "r={r}");
            }
            other => panic!("expected Pair, got {other:?}"),
        }
    }

    #[test]
    fn root_pair_quad_roundtrip_split() {
        let p = RootPair::Split { z1: 0.8, z2: 0.3 };
        let (a1, a2) = p.quad();
        match RootPair::from_quad(a1, a2) {
            RootPair::Split { z1, z2 } => {
                assert!((z1 - 0.8).abs() < 1e-12);
                assert!((z2 - 0.3).abs() < 1e-12);
            }
            other => panic!("expected Split, got {other:?}"),
        }
    }

    #[test]
    fn rootless_pair_is_constant_quad() {
        let p = RootPair::Pair { hz: 0.0, r: 0.0 };
        assert_eq!(p.quad(), (0.0, 0.0));
        assert_eq!(RootPair::from_quad(0.0, 0.0), p);
    }

    #[test]
    fn mode_biquad_roundtrip() {
        let m = Mode {
            pole: RootPair::Pair { hz: 740.0, r: 0.97 },
            zero: RootPair::Pair { hz: 1480.0, r: 0.90 },
            gain: 0.75,
            active: 1.0,
        };
        let b = m.biquad();
        let m2 = Mode::from_biquad(b);
        let b2 = m2.biquad();
        for k in 0..5 {
            assert!(
                (b[k] - b2[k]).abs() < 1e-12,
                "coeff {k}: {} vs {}",
                b[k],
                b2[k]
            );
        }
    }

    #[test]
    fn identity_mode_is_identity_biquad() {
        assert_eq!(IDENTITY.biquad(), [1.0, 0.0, 0.0, 0.0, 0.0]);
    }

    #[test]
    fn inactive_mode_projects_as_identity() {
        let mut m = IDENTITY;
        m.pole = RootPair::Pair { hz: 500.0, r: 0.9 };
        m.active = 0.0;
        assert_eq!(m.biquad(), [1.0, 0.0, 0.0, 0.0, 0.0]);
    }

    #[test]
    fn design_json_roundtrip() {
        let d = Design {
            name: "test".into(),
            anchors: vec![Anchor {
                morph: 0.0,
                q: 0.0,
                modes: vec![
                    Mode {
                        pole: RootPair::Pair { hz: 740.0, r: 0.97 },
                        zero: RootPair::Split { z1: 0.5, z2: 0.2 },
                        gain: 1.25,
                        active: 1.0,
                    },
                    IDENTITY,
                ],
            }],
        };
        let d2 = Design::from_json(&d.to_json()).unwrap();
        assert_eq!(d, d2);
    }

    #[test]
    fn anchor_at_finds_corners() {
        let d = Design {
            name: "t".into(),
            anchors: vec![
                Anchor { morph: 0.0, q: 0.0, modes: vec![] },
                Anchor { morph: 1.0, q: 0.0, modes: vec![] },
            ],
        };
        assert!(d.anchor_at(0.0, 0.0).is_some());
        assert!(d.anchor_at(1.0, 0.0).is_some());
        assert!(d.anchor_at(0.0, 1.0).is_none());
    }
}
