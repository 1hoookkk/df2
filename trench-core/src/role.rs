//! Per-stage frequency role classification.
//!
//! Ported from `archive/pre-runtime/trench-forge/src/coordination.rs:38`.
//! A `Role` is the intended spectral function of a cascade stage based on
//! its center frequency. Roles are the coarse vocabulary that coordinated
//! cascade solvers use to assign zero placement strategies per stage.
//!
//! Bands match the P2K corpus analysis in the archive:
//!
//! | Role      | Range        | Strategy                                |
//! |-----------|--------------|------------------------------------------|
//! | Anchor    | < 200 Hz     | Foundation LP, no independent zeros     |
//! | LowMid    | 200–900 Hz   | Partial zero-forcing (interior zero)    |
//! | Character | 900–3000 Hz  | Full zero-forcing (unit-circle zero)    |
//! | Air       | > 3000 Hz    | Full zero-forcing (unit-circle zero)    |

use serde::{Deserialize, Serialize};

/// Frequency role for a stage in a skeleton plan.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Role {
    /// `< 200 Hz` — foundation LP, no independent zeros.
    Anchor,
    /// `200–900 Hz` — partial zero-forcing (interior zero).
    LowMid,
    /// `900–3000 Hz` — full zero-forcing (unit-circle zero).
    Character,
    /// `> 3000 Hz` — full zero-forcing (unit-circle zero).
    Air,
}

impl Role {
    /// Classify a stage's role from its center frequency in Hz.
    ///
    /// Band boundaries are locked to the P2K corpus pattern analysis:
    /// `200`, `900`, and `3000` Hz. Do not adjust without re-running the
    /// corpus analysis that derived them.
    pub fn classify(freq_hz: f64) -> Self {
        if freq_hz < 200.0 {
            Role::Anchor
        } else if freq_hz < 900.0 {
            Role::LowMid
        } else if freq_hz < 3000.0 {
            Role::Character
        } else {
            Role::Air
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn boundaries_match_p2k_corpus_bands() {
        assert_eq!(Role::classify(20.0), Role::Anchor);
        assert_eq!(Role::classify(199.999), Role::Anchor);
        assert_eq!(Role::classify(200.0), Role::LowMid);
        assert_eq!(Role::classify(899.999), Role::LowMid);
        assert_eq!(Role::classify(900.0), Role::Character);
        assert_eq!(Role::classify(2999.999), Role::Character);
        assert_eq!(Role::classify(3000.0), Role::Air);
        assert_eq!(Role::classify(19000.0), Role::Air);
    }

    #[test]
    fn role_serde_roundtrip() {
        for r in [Role::Anchor, Role::LowMid, Role::Character, Role::Air] {
            let json = serde_json::to_string(&r).unwrap();
            let back: Role = serde_json::from_str(&json).unwrap();
            assert_eq!(back, r);
        }
    }

    #[test]
    fn sub_bass_is_anchor() {
        // Speaker Knockerz's "sub never disappears" invariant lives here:
        // any stage tracking the 40 Hz fundamental is an Anchor role.
        assert_eq!(Role::classify(40.0), Role::Anchor);
        assert_eq!(Role::classify(60.0), Role::Anchor);
        assert_eq!(Role::classify(150.0), Role::Anchor);
    }

    #[test]
    fn vocal_formant_band_is_character() {
        // Small Talk Ah-Ee's formant pair F1≈500 Hz, F2≈1500 Hz:
        // F1 lands in LowMid, F2 lands in Character.
        assert_eq!(Role::classify(500.0), Role::LowMid);
        assert_eq!(Role::classify(1500.0), Role::Character);
        assert_eq!(Role::classify(2500.0), Role::Character);
    }
}
