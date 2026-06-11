//! Packed-ROM authority gate for Talking Hedz.
//!
//! This test intentionally guards the P2K ROM bank:
//! `ref/presets/P2k_013_talking_hedz.bin`. It does not validate the retired
//! MorphDesigner-derived float fixture, and it must not assert Q collapse.

use trench_core::cascade::NUM_STAGES;
use trench_core::hedz_rom::{
    decoded_corners, packed_corners, HEDZ_BOOSTS, HEDZ_NAME, HEDZ_PACKED_WORDS,
};
use trench_core::minifloat::{PackedCorners, BODY_BYTES};
use trench_core::Cartridge;

const ROM_BYTES: &[u8; BODY_BYTES] = include_bytes!("../../ref/presets/P2k_013_talking_hedz.bin");

#[test]
fn hedz_packed_words_match_canonical_rom_body() {
    let parsed = PackedCorners::from_body_bytes(ROM_BYTES).expect("parse canonical Hedz body");
    assert_eq!(
        parsed.words, HEDZ_PACKED_WORDS,
        "hedz_rom.rs must mirror ref/presets/P2k_013_talking_hedz.bin exactly"
    );
    assert_eq!(packed_corners(), parsed);
}

#[test]
fn hedz_rom_has_six_stages_per_corner() {
    for (i, corner) in HEDZ_PACKED_WORDS.iter().enumerate() {
        assert_eq!(
            corner.len(),
            NUM_STAGES,
            "corner {i} has {} stages, expected {NUM_STAGES}",
            corner.len()
        );
    }
}

#[test]
fn hedz_rom_q_axis_is_live() {
    assert_ne!(
        HEDZ_PACKED_WORDS[0], HEDZ_PACKED_WORDS[2],
        "M0_Q0 and M0_Q100 must stay distinct for real P2K Hedz"
    );
    assert_ne!(
        HEDZ_PACKED_WORDS[1], HEDZ_PACKED_WORDS[3],
        "M100_Q0 and M100_Q100 must stay distinct for real P2K Hedz"
    );
}

#[test]
fn hedz_cartridge_builder_uses_packed_rom_words() {
    let cart = Cartridge::hedz_rom();
    assert_eq!(cart.name, HEDZ_NAME);
    assert_eq!(cart.boosts, HEDZ_BOOSTS);

    let packed = cart
        .packed
        .as_ref()
        .expect("Hedz must use packed ROM interpolation, not legacy float stages");
    assert_eq!(packed.words, HEDZ_PACKED_WORDS);
    assert_eq!(cart.corners, decoded_corners());
}

#[test]
fn hedz_interpolated_corners_match_decoded_rom_words() {
    let cart = Cartridge::hedz_rom();
    let decoded = decoded_corners();
    let positions = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)];

    for (ci, (morph, q)) in positions.iter().copied().enumerate() {
        assert_eq!(
            cart.interpolate(morph, q),
            decoded[ci],
            "corner {ci} must decode from packed ROM words at M={morph} Q={q}"
        );
    }
}
