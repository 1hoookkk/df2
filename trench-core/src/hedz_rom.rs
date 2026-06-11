//! Talking Hedz P2K ROM cartridge.
//!
//! This module intentionally points at the provenance-bearing 240-byte P2K
//! ROM bank, not the older MorphDesigner-derived float fixture. The byte
//! source is `ref/presets/P2k_013_talking_hedz.bin`, verified against both the
//! Cheat Engine live object dump and a fresh static extraction from
//! `EmulatorX.dll`.

use crate::cartridge::{CornerData, NUM_CORNERS};
use crate::cascade::{NUM_COEFFS, NUM_STAGES};
use crate::minifloat::{stage_words_to_biquad, PackedCorners, PackedStage};

pub const HEDZ_NAME: &str = "Talking Hedz";

/// P2K ROM skins carry no separate post-cascade heritage boost in the packed
/// bank path. The derived JSON cartridges use `boost = 1.0` on all corners.
pub const HEDZ_BOOSTS: [f64; NUM_CORNERS] = [1.0; NUM_CORNERS];

pub const HEDZ_ROM_SHA256: &str =
    "e686bf124086bf79e598850d803b606a6c0b89a0622ef0bf428dc617a2fb777a";

pub const HEDZ_PACKED_WORDS: [[PackedStage; NUM_STAGES]; NUM_CORNERS] = [
    [
        [27900, 53244, 60668, 47356, 53754],
        [37116, 51964, 34044, 46332, 53754],
        [43516, 50172, 40956, 46844, 53754],
        [48124, 48124, 45564, 35068, 53754],
        [57852, 60412, 53244, 51708, 53754],
        [57084, 496, 16891, 41468, 53754],
    ],
    [
        [41724, 52220, 59388, 49916, 53424],
        [33276, 49916, 16891, 40956, 53424],
        [45308, 56060, 45564, 45564, 53424],
        [47612, 51964, 47100, 44540, 53424],
        [54780, 61693, 53500, 53244, 53424],
        [65277, 496, 42236, 35836, 53424],
    ],
    [
        [27644, 54012, 61693, 28668, 53646],
        [36860, 52220, 34812, 27900, 53646],
        [43004, 49916, 40444, 27644, 53646],
        [47612, 47100, 45052, 27388, 53646],
        [57852, 61180, 52732, 36348, 53646],
        [56316, 496, 13561, 27644, 53646],
    ],
    [
        [41212, 50940, 60412, 27900, 53341],
        [33020, 49404, 16377, 25852, 53341],
        [44028, 56060, 44540, 26876, 53341],
        [46332, 51964, 45820, 27388, 53341],
        [54012, 62205, 52732, 48124, 53341],
        [65277, 496, 40444, 28156, 53341],
    ],
];

pub fn packed_corners() -> PackedCorners {
    PackedCorners {
        words: HEDZ_PACKED_WORDS,
    }
}

pub fn decoded_corners() -> [CornerData; NUM_CORNERS] {
    let mut corners = [[[0.0; NUM_COEFFS]; NUM_STAGES]; NUM_CORNERS];
    for ci in 0..NUM_CORNERS {
        for si in 0..NUM_STAGES {
            corners[ci][si] = stage_words_to_biquad(HEDZ_PACKED_WORDS[ci][si]);
        }
    }
    corners
}
