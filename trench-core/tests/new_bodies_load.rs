//! Verify the 4 newly-authored TRENCH ship bodies load correctly via the
//! engine's `Cartridge::from_json`. These live as binary data in juce-shell
//! but the source-of-truth JSON is at juce-shell/assets/cartridges/.

use trench_core::cartridge::Cartridge;

const BODY_FILES: &[(&str, &str)] = &[
    (
        "Speaker Knockerz",
        "../juce-shell/assets/cartridges/speaker_knockerz.json",
    ),
    (
        "Aluminum Siding",
        "../juce-shell/assets/cartridges/aluminum_siding.json",
    ),
    (
        "Small Talk Ah-Ee",
        "../juce-shell/assets/cartridges/small_talk_ah_ee.json",
    ),
    (
        "Cul-De-Sac",
        "../juce-shell/assets/cartridges/cul_de_sac.json",
    ),
];

#[test]
fn all_new_bodies_parse() {
    for (name, path) in BODY_FILES {
        let json =
            std::fs::read_to_string(path).unwrap_or_else(|e| panic!("read {name} at {path}: {e}"));
        let _cart = Cartridge::from_json(&json).unwrap_or_else(|e| panic!("parse {name}: {e}"));
    }
}

#[test]
fn cartridges_interpolate_at_grid_corners_without_panic() {
    for (name, path) in BODY_FILES {
        let json = std::fs::read_to_string(path).unwrap();
        let cart = Cartridge::from_json(&json).expect(name);
        for (m, q) in &[(0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (0.25, 0.75)] {
            let _corner = cart.interpolate(*m, *q);
            let _boost = cart.interpolate_boost(*m, *q);
        }
    }
}
