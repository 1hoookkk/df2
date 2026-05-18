//! Cross-language parity gate for the baked Talking Hedz cartridge.
//!
//! **What this test proves.** The integer heritage grid in
//! `cartridges/factory/_source/heritage_designer_sections.json`, compiled through
//! the stdlib DF2T emulator in `authoring/compilers/bake_hedz_const.py`, produces
//! the same audio sample-for-sample as the Rust `Cascade` when fed
//! the same static coefficients and the same unit impulse. If this
//! test fails, one of these has drifted:
//!
//!  1. `authoring/compilers/bake_hedz_const.py` — the Python compile or DF2T math
//!  2. `runtime/trench-core/src/cascade.rs` — the Rust DF2T math
//!  3. `runtime/trench-core/src/hedz_rom.rs` — the committed const coefficients
//!  4. `runtime/trench-core/src/hedz_golden.rs` — the committed expected outputs
//!
//! Root-cause the drift. Do not loosen the tolerance — `2e-5` is
//! already the f32 rounding ceiling for a 6-stage IIR resonator
//! cascade at 256 samples with nontrivial boost.
//!
//! **What this test does NOT prove.** It does not assert fidelity to
//! the E-mu hardware. The `Talking Hedz` runtime filter famously
//! drops one stage and hard-converts another into a low-pass bracket
//! (`docs/looperator/talking_hedz_x3_surfaces.md:25-28`), so a
//! bit-exact match against `reference/canonical_audio/P2k_013_*.wav` is a
//! separate problem and a separate test. This one only locks the
//! Python→Rust bytes-and-math chain.

use trench_core::cascade::NUM_STAGES;
use trench_core::hedz_golden::{
    HEDZ_GOLDEN_LEN, HEDZ_GOLDEN_M0_Q0, HEDZ_GOLDEN_M0_Q100, HEDZ_GOLDEN_M100_Q0,
    HEDZ_GOLDEN_M100_Q100,
};
use trench_core::hedz_rom::{HEDZ_BOOSTS, HEDZ_CORNERS};
use trench_core::{Cartridge, Cascade};

/// Peak-error tolerance, matched to the bake script's f32 rounding.
/// Every sample is independently f32-cast in the Python DF2T emulator
/// (`tools/bake_hedz_const.py::run_impulse`). The Rust `Cascade`
/// internally runs f64 math on direct-form biquads. Static-coefficient
/// matches should be well under this ceiling.
const TOLERANCE: f32 = 2e-5;

/// Static-coefficient DF2T drive for the parity check.
///
/// `Cascade` always ramps coefficients: `process_sample` does
/// `coeffs[i] += deltas[i]` every sample unconditionally, and there is
/// no public API to zero the deltas after a snap. So to match the
/// Python bake's static coefficients, we re-pin `set_targets(_, 1)`
/// and `set_boost(_, 1)` before every sample. On the first tick that
/// produces `delta = target - passthrough`; after the tick `coeffs ==
/// target`, so the next re-pin produces `delta = 0`, and from sample
/// 1 onwards the ramp is a no-op. This is not how the plugin uses the
/// cascade in production — in production `set_targets` is called once
/// per 32-sample block and the ramps are real. This test specifically
/// isolates the static case so it measures only the DF2T math, not
/// the ramp.
fn drive_impulse(corner_index: usize) -> Vec<f32> {
    let mut cascade = Cascade::new();
    let corner = &HEDZ_CORNERS[corner_index];
    let boost = HEDZ_BOOSTS[corner_index];

    let mut out = vec![0.0_f32; HEDZ_GOLDEN_LEN];
    for n in 0..HEDZ_GOLDEN_LEN {
        cascade.set_targets(corner, 1);
        cascade.set_boost(boost, 1);
        let x = if n == 0 { 1.0_f32 } else { 0.0_f32 };
        let mut sample = [x];
        cascade.process_block_mono(&mut sample);
        out[n] = sample[0];
    }
    out
}

fn assert_matches_golden(corner_index: usize, label: &str, golden: &[f32]) {
    let actual = drive_impulse(corner_index);
    assert_eq!(
        actual.len(),
        golden.len(),
        "{label}: length mismatch (actual {} vs golden {})",
        actual.len(),
        golden.len(),
    );

    let mut max_err = 0.0_f32;
    let mut worst_idx = 0;
    for (i, (a, g)) in actual.iter().zip(golden.iter()).enumerate() {
        let err = (a - g).abs();
        if err > max_err {
            max_err = err;
            worst_idx = i;
        }
    }

    assert!(
        max_err <= TOLERANCE,
        "{label}: peak error {max_err:.3e} > tolerance {TOLERANCE:.3e} at sample {worst_idx} \
         (Rust {rust:.6e}, Python {py:.6e}). Root-cause the drift — do not loosen the tolerance.",
        rust = actual[worst_idx],
        py = golden[worst_idx],
    );
}

#[test]
fn hedz_rom_has_six_active_stages_per_corner() {
    // Sanity: the bake script is supposed to write six stages per
    // corner. Anything else means the const array layout drifted.
    for (i, corner) in HEDZ_CORNERS.iter().enumerate() {
        assert_eq!(
            corner.len(),
            NUM_STAGES,
            "corner {i} has {} stages, expected {NUM_STAGES}",
            corner.len(),
        );
    }
}

#[test]
fn hedz_rom_q_axis_is_collapsed() {
    // Talking Hedz is a morph-only heritage body — Q0 and Q100 at each
    // morph endpoint must be byte-identical by construction.
    assert_eq!(HEDZ_CORNERS[0], HEDZ_CORNERS[2], "M0_Q0 != M0_Q100");
    assert_eq!(HEDZ_CORNERS[1], HEDZ_CORNERS[3], "M100_Q0 != M100_Q100");
}

#[test]
fn hedz_cartridge_builder_wires_const_through() {
    // Cartridge::hedz_rom() must carry the const arrays verbatim.
    let cart = Cartridge::hedz_rom();
    assert_eq!(cart.name, "Talking Hedz");
    assert_eq!(cart.corners, HEDZ_CORNERS);
    assert_eq!(cart.boosts, HEDZ_BOOSTS);
}

#[test]
fn hedz_cascade_matches_python_golden_m0_q0() {
    assert_matches_golden(0, "M0_Q0", &HEDZ_GOLDEN_M0_Q0);
}

#[test]
fn hedz_cascade_matches_python_golden_m100_q0() {
    assert_matches_golden(1, "M100_Q0", &HEDZ_GOLDEN_M100_Q0);
}

#[test]
fn hedz_cascade_matches_python_golden_m0_q100() {
    assert_matches_golden(2, "M0_Q100", &HEDZ_GOLDEN_M0_Q100);
}

#[test]
fn hedz_cascade_matches_python_golden_m100_q100() {
    assert_matches_golden(3, "M100_Q100", &HEDZ_GOLDEN_M100_Q100);
}
