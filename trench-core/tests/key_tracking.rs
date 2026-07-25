//! KEY TRACKING contract: ratio 1.0 is bit-exact off; ratio r moves every
//! conjugate resonance's frequency by exactly r and leaves radii alone.

use trench_core::cartridge::Cartridge;
use trench_core::engine::FilterEngine;
use trench_core::stage_law::{words_from_roots, StageRoots, STAGE_SR};

const TAU: f64 = core::f64::consts::PI * 2.0;

fn test_body() -> Vec<u8> {
    // one resonant stage at 1000 Hz r=0.98 + five identity stages, all corners
    let active = words_from_roots(&StageRoots {
        pole_hz: 1000.0,
        pole_r: 0.98,
        zero_hz: 250.0,
        zero_r: 0.5,
        scale: 0.1,
    });
    let ident = words_from_roots(&StageRoots {
        pole_hz: 0.0,
        pole_r: 0.0,
        zero_hz: 0.0,
        zero_r: 0.0,
        scale: 1.0,
    });
    let mut bytes = Vec::with_capacity(240);
    for _corner in 0..4 {
        for s in 0..6 {
            for w in if s == 0 { active } else { ident } {
                bytes.extend_from_slice(&w.to_le_bytes());
            }
        }
    }
    bytes
}

fn prepared_engine() -> FilterEngine {
    let mut eng = FilterEngine::new();
    eng.prepare(STAGE_SR);
    let cart = Cartridge::from_body_bytes("kt_test", &test_body(), 0.0).expect("cart");
    eng.load_cartridge(cart);
    eng
}

fn render(eng: &mut FilterEngine, blocks: usize) -> Vec<f32> {
    let mut out = Vec::new();
    let mut rng: u32 = 0x12345678;
    for _ in 0..blocks {
        let mut l = [0.0f32; 64];
        let mut r = [0.0f32; 64];
        for i in 0..64 {
            rng = rng.wrapping_mul(1664525).wrapping_add(1013904223);
            l[i] = (rng >> 8) as f32 / (1 << 24) as f32 - 0.5;
            r[i] = l[i];
        }
        eng.process_block(&mut l, &mut r, 0.5, 0.5);
        out.extend_from_slice(&l);
    }
    out
}

#[test]
fn ratio_one_is_bit_exact() {
    let mut a = prepared_engine();
    let mut b = prepared_engine();
    b.set_pitch_ratio(1.0);
    assert_eq!(render(&mut a, 40), render(&mut b, 40), "ratio 1.0 must be bit-exact off");
}

fn measure_resonance(eng: &mut FilterEngine) -> (f64, f64) {
    let _ = render(eng, 4000); // the coeff ramp converges geometrically - land it fully
    let mut coeffs = [[0.0f32; 5]; 6];
    let mut boost = 0.0f32;
    eng.get_coeffs_for_ui(&mut coeffs, &mut boost);
    // find the resonant stage (the identity stages have a2 == 0)
    let stage = coeffs
        .iter()
        .max_by(|a, b| a[4].abs().partial_cmp(&b[4].abs()).unwrap())
        .unwrap();
    let (a1, a2) = (stage[3] as f64, stage[4] as f64);
    let r = a2.sqrt();
    let hz = (-a1 / (2.0 * r)).clamp(-1.0, 1.0).acos() * STAGE_SR / TAU;
    (hz, r)
}

#[test]
fn ratio_moves_frequency_keeps_radius() {
    let ratio = 1.5f64; // a fifth
    let (hz_base, r_base) = measure_resonance(&mut prepared_engine());
    let mut eng = prepared_engine();
    eng.set_pitch_ratio(ratio as f32);
    let (hz, r) = measure_resonance(&mut eng);
    let measured_ratio = hz / hz_base;
    assert!(
        (measured_ratio - ratio).abs() < 0.02,
        "transpose ratio should be {ratio}, measured {measured_ratio} ({hz_base} -> {hz} Hz)"
    );
    assert!((r - r_base).abs() < 0.005, "radius must survive transpose: {r_base} -> {r}");
}

