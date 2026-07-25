//! BITE contract: drive 0 is BIT-EXACT the linear cascade; drive > 0 generates
//! harmonics between the stages (and only then).

use trench_core::cartridge::Cartridge;
use trench_core::engine::FilterEngine;
use trench_core::stage_law::{words_from_roots, StageRoots, STAGE_SR};

fn test_body() -> Vec<u8> {
    // a resonant stage so the junction actually sees a hot peak
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
    for _ in 0..4 {
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
    let cart = Cartridge::from_body_bytes("bite_test", &test_body(), 0.0).expect("cart");
    eng.load_cartridge(cart);
    eng
}

fn render_sine(eng: &mut FilterEngine, hz: f64, blocks: usize) -> Vec<f32> {
    let mut out = Vec::new();
    let mut phase = 0.0f64;
    for _ in 0..blocks {
        let mut l = [0.0f32; 64];
        let mut r = [0.0f32; 64];
        for i in 0..64 {
            phase += core::f64::consts::TAU * hz / STAGE_SR;
            l[i] = (phase.sin() * 0.5) as f32;
            r[i] = l[i];
        }
        eng.process_block(&mut l, &mut r, 0.5, 0.5);
        out.extend_from_slice(&l);
    }
    out
}

#[test]
fn drive_zero_is_bit_exact() {
    let mut a = prepared_engine();
    let mut b = prepared_engine();
    b.set_interstage_drive(0.0);
    assert_eq!(
        render_sine(&mut a, 987.0, 60),
        render_sine(&mut b, 987.0, 60),
        "drive 0 must be bit-exact the linear cascade"
    );
}

fn goertzel(x: &[f32], hz: f64) -> f64 {
    let w = core::f64::consts::TAU * hz / STAGE_SR;
    let coeff = 2.0 * w.cos();
    let (mut s1, mut s2) = (0.0f64, 0.0f64);
    for &v in x {
        let s0 = v as f64 + coeff * s1 - s2;
        s2 = s1;
        s1 = s0;
    }
    (s1 * s1 + s2 * s2 - coeff * s1 * s2).sqrt() / (x.len() as f64 / 2.0)
}

#[test]
fn drive_generates_harmonics() {
    let f0 = 987.0;
    let mut lin = prepared_engine();
    let clean = render_sine(&mut lin, f0, 200);
    let mut hot = prepared_engine();
    hot.set_interstage_drive(0.8);
    let driven = render_sine(&mut hot, f0, 200);

    let tail = &clean[clean.len() - 4096..];
    let tail_hot = &driven[driven.len() - 4096..];
    let h1 = goertzel(tail_hot, f0).max(1e-12);
    let h3_clean = goertzel(tail, 3.0 * f0) / goertzel(tail, f0).max(1e-12);
    let h3_hot = goertzel(tail_hot, 3.0 * f0) / h1;
    let clean_db = 20.0 * h3_clean.max(1e-12).log10();
    let hot_db = 20.0 * h3_hot.max(1e-12).log10();
    assert!(
        hot_db > clean_db + 20.0,
        "drive 0.8 should raise H3 well above the linear floor: clean {clean_db:.1} dBc, hot {hot_db:.1} dBc"
    );
}

#[test]
fn aliasing_probe_5k_drive08() {
    // 5 kHz sine, drive 0.8: harmonics 10k/15k live below Nyquist (19531);
    // 20k/25k/30k fold to 19062.5 / 14062.5 / 9062.5. Report dBc honestly.
    let mut eng = prepared_engine();
    eng.set_interstage_drive(0.8);
    let out = render_sine(&mut eng, 5000.0, 400);
    let tail = &out[out.len() - 8192..];
    let h1 = goertzel(tail, 5000.0).max(1e-12);
    for (label, hz) in [
        ("H2 10k", 10000.0),
        ("H3 15k", 15000.0),
        ("fold H4 -> 19062.5", 19062.5),
        ("fold H5 -> 14062.5", 14062.5),
        ("fold H6 -> 9062.5", 9062.5),
    ] {
        let dbc = 20.0 * (goertzel(tail, hz) / h1).max(1e-12).log10();
        println!("{label}: {dbc:6.1} dBc");
    }
    println!("(gate: report only — the ear and the HD island own the verdict)");
}
