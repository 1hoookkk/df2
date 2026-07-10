//! The 240-byte packed projection — the V1 ship target.
//!
//! `project` compiles a design's four corner anchors into the exact packed
//! body; `import` reads a packed body back as a verbatim model instance.
//! Word math stays owned by trench-core (`biquad_to_words`, minifloat codec)
//! — this module never re-implements the codec.

use crate::{Design, Mode, IDENTITY};
use trench_core::compiler::{biquad_to_words, STAGES};
use trench_core::minifloat::{stage_words_to_biquad, PackedCorners, BODY_BYTES};

/// Canonical corner order as (morph, q) wheel positions:
/// M0_Q0, M100_Q0, M0_Q100, M100_Q100.
pub const CORNERS: [(f64, f64); 4] = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)];

/// Project the design's four corner anchors into the 240-byte packed body.
///
/// Requires an authored anchor at every corner (Q corners are authored,
/// never derived) and at most 6 modes per anchor; missing stages pad with
/// the identity section.
pub fn project(design: &Design) -> Result<[u8; BODY_BYTES], String> {
    let mut body = [0u8; BODY_BYTES];
    let mut out = 0usize;
    for (morph, q) in CORNERS {
        let anchor = design
            .anchor_at(morph, q)
            .ok_or_else(|| format!("no anchor at morph {morph} q {q} — corners are authored"))?;
        if anchor.modes.len() > STAGES {
            return Err(format!(
                "anchor at morph {morph} q {q} has {} modes; packed projection holds {STAGES}",
                anchor.modes.len()
            ));
        }
        for si in 0..STAGES {
            let mode = anchor.modes.get(si).copied().unwrap_or(IDENTITY);
            for word in biquad_to_words(mode.biquad()) {
                body[out] = (word & 0xff) as u8;
                body[out + 1] = (word >> 8) as u8;
                out += 2;
            }
        }
    }
    Ok(body)
}

/// Import a 240-byte packed body verbatim as a model instance:
/// four corner anchors, six modes each, roots factored from the decoded rows.
pub fn import(name: &str, bytes: &[u8]) -> Result<Design, String> {
    let pc = PackedCorners::from_body_bytes(bytes).map_err(str::to_owned)?;
    let anchors = CORNERS
        .iter()
        .enumerate()
        .map(|(ci, &(morph, q))| crate::Anchor {
            morph,
            q,
            modes: (0..STAGES)
                .map(|si| Mode::from_biquad(stage_words_to_biquad(pc.words[ci][si])))
                .collect(),
        })
        .collect();
    Ok(Design {
        name: name.to_owned(),
        anchors,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Anchor;

    fn four_corner_design(modes: Vec<Mode>) -> Design {
        Design {
            name: "t".into(),
            anchors: CORNERS
                .iter()
                .map(|&(morph, q)| Anchor {
                    morph,
                    q,
                    modes: modes.clone(),
                })
                .collect(),
        }
    }

    #[test]
    fn project_requires_all_four_corners() {
        let mut d = four_corner_design(vec![IDENTITY]);
        d.anchors.remove(2); // drop M0_Q100
        assert!(project(&d).is_err());
    }

    #[test]
    fn project_rejects_seven_modes() {
        let d = four_corner_design(vec![IDENTITY; 7]);
        assert!(project(&d).is_err());
    }

    #[test]
    fn empty_anchor_projects_as_all_identity() {
        let d = four_corner_design(vec![]);
        let body = project(&d).unwrap();
        let expected = biquad_to_words([1.0, 0.0, 0.0, 0.0, 0.0]);
        for stage in body.chunks_exact(10) {
            for (wi, wb) in stage.chunks_exact(2).enumerate() {
                assert_eq!(u16::from_le_bytes([wb[0], wb[1]]), expected[wi]);
            }
        }
    }

    #[test]
    fn import_project_roundtrip_synthetic() {
        let m = Mode {
            pole: crate::RootPair::Pair { hz: 740.0, r: 0.97 },
            zero: crate::RootPair::Pair { hz: 1480.0, r: 0.90 },
            gain: 0.11,
            active: 1.0,
        };
        let body = project(&four_corner_design(vec![m])).unwrap();
        let d = import("t", &body).unwrap();
        let body2 = project(&d).unwrap();
        assert_eq!(body, body2);
    }
}
