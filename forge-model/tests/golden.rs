//! Golden tests for the packed projection.
//!
//! (a) forge-zero's one-mode pack reproduces bit-exact through the model.
//! (b) decode(P12 bytes) -> model -> project roundtrips within packed
//!     quantization. P12 = desk/sheets/VOWL_typed_p12.body240, the vowel-slot
//!     winner — a protected fixture, embedded at compile time, never
//!     regenerated.

use forge_model::packed::{import, project, CORNERS};
use forge_model::{Anchor, Design, Mode};

/// The protected P12 fixture (vowel-slot winner, Tyson's "A").
const P12: &[u8; 240] = include_bytes!("../../desk/sheets/VOWL_typed_p12.body240");

/// The rest of the ear-picked roster, staged in desk/finishing/.
const ROSTER: [(&str, &[u8; 240]); 3] = [
    ("VOWL_typed_p12", include_bytes!("../../desk/finishing/VOWL_typed_p12.body240")),
    ("PHON_SPLITTER", include_bytes!("../../desk/finishing/surv_PHON_SPLITTER.body240")),
    ("FUZZ_B_RAZOR", include_bytes!("../../desk/finishing/surv_FUZZ_B_RAZOR.body240")),
];

/// forge-zero's pack(): one mode in stage 0, stages 1-5 off, all 4 corners
/// identical, through trench_core::compiler::pack_body. Kept verbatim so the
/// golden reference is the surface's actual byte path.
fn forge_zero_pack(pole_hz: f64, pole_r: f64, zero_hz: f64, zero_r: f64) -> [u8; 240] {
    let mut params = Vec::with_capacity(168);
    for _corner in 0..4 {
        params.extend_from_slice(&[
            1.0,
            pole_hz,
            pole_r,
            1.0,
            if zero_r > 0.0001 { 1.0 } else { 0.0 },
            zero_hz,
            zero_r,
        ]);
        for _ in 1..6 {
            params.extend_from_slice(&[0.0, 1000.0, 0.5, 1.0, 0.0, 1000.0, 0.0]);
        }
    }
    trench_core::compiler::pack_body(&params)
}

fn one_mode_design(mode: Mode) -> Design {
    Design {
        name: "zero".into(),
        anchors: CORNERS
            .iter()
            .map(|&(morph, q)| Anchor {
                morph,
                q,
                modes: vec![mode],
            })
            .collect(),
    }
}

#[test]
fn forge_zero_one_mode_pack_is_bit_exact() {
    // forge-zero's default mode, plus a no-zero variant and a swept variant.
    for (ph, pr, zh, zr) in [
        (740.0, 0.97, 1480.0, 0.90),
        (740.0, 0.97, 1480.0, 0.0),
        (212.0, 0.9989, 6300.0, 0.42),
    ] {
        let reference = forge_zero_pack(ph, pr, zh, zr);
        let body = project(&one_mode_design(Mode::pole_zero(ph, pr, zh, zr)))
            .expect("projects");
        assert_eq!(
            body, reference,
            "one-mode pack diverged for pole {ph} Hz r{pr}, zero {zh} Hz r{zr}"
        );
    }
}

#[test]
fn p12_import_project_roundtrips_within_packed_quantization() {
    let design = import("VOWL_typed_p12", P12).expect("P12 imports");
    let body = project(&design).expect("P12 projects");

    // Word-level check: root factoring runs in f64, so re-encoding may land
    // one minifloat LSB away at worst. Count exact and off-by-one words.
    let mut off_by_one = 0usize;
    for (i, (got, want)) in body
        .chunks_exact(2)
        .zip(P12.chunks_exact(2))
        .enumerate()
    {
        let g = u16::from_le_bytes([got[0], got[1]]);
        let w = u16::from_le_bytes([want[0], want[1]]);
        let d = (g as i32 - w as i32).abs();
        assert!(
            d <= 1,
            "word {i}: got {g:#06x}, want {w:#06x} — outside packed quantization"
        );
        if d == 1 {
            off_by_one += 1;
        }
    }
    // Regression canary: today the roundtrip is byte-exact. If refactoring
    // introduces drift, this surfaces it even while the ±1 gate still passes.
    assert_eq!(off_by_one, 0, "{off_by_one}/120 words drifted one LSB");
}

#[test]
fn roster_bodies_import_as_model_instances_byte_exact() {
    // The whole ship roster is representable as forge-model Designs with no
    // loss: import -> project reproduces every body byte-for-byte.
    for (name, bytes) in ROSTER {
        let design = import(name, bytes).unwrap_or_else(|e| panic!("{name}: {e}"));
        assert_eq!(design.anchors.len(), 4, "{name}: 4 corner anchors");
        for a in &design.anchors {
            assert_eq!(a.modes.len(), 6, "{name}: 6 modes per anchor");
        }
        let body = project(&design).unwrap_or_else(|e| panic!("{name}: {e}"));
        assert_eq!(&body[..], &bytes[..], "{name}: roundtrip must be byte-exact");
    }
}
