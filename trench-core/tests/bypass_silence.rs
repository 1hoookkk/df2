//! Verify the Bypass boot body produces zero output from zero input through
//! the full engine path (cascade + AGC + saturate + output gain + DC blocker).
//!
//! If this fails, the static the user hears in FL is NOT from body coefficients
//! — it is from some stage that produces non-zero output from zero input. That
//! must be debugged in trench-core, not the JUCE shell.

use std::path::PathBuf;
use trench_core::Cartridge;
use trench_core::FilterEngine;

fn bypass_bytes() -> Vec<u8> {
    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.pop(); // up from trench-core/
    p.push("bodies/bypass.body240");
    std::fs::read(&p).expect("read bodies/bypass.body240")
}

#[test]
fn bypass_zero_in_zero_out() {
    let bytes = bypass_bytes();
    assert_eq!(bytes.len(), 240);

    let cart = Cartridge::from_body_bytes("bypass", &bytes, 1.0).unwrap();
    let mut engine = FilterEngine::new();
    engine.prepare(44_100.0);
    engine.load_cartridge(cart);

    // Feed 4096 samples of pure silence through the engine at morph=0, q=0.
    let mut l = vec![0.0f32; 4096];
    let mut r = vec![0.0f32; 4096];
    engine.process_block(&mut l, &mut r, 0.0, 0.0);

    let max_l = l.iter().map(|x| x.abs()).fold(0.0f32, f32::max);
    let max_r = r.iter().map(|x| x.abs()).fold(0.0f32, f32::max);
    assert_eq!(
        max_l, 0.0,
        "Bypass with zero input must produce zero output (left), got max={max_l}"
    );
    assert_eq!(
        max_r, 0.0,
        "Bypass with zero input must produce zero output (right), got max={max_r}"
    );
}

#[test]
fn bypass_low_noise_does_not_self_excite() {
    // Feed a -90 dB noise floor in (~3.16e-5 amplitude) and verify the output
    // RMS does not exceed the input RMS by more than 1 dB. AGC should not
    // amplify the noise floor with an identity body.
    let bytes = bypass_bytes();
    let cart = Cartridge::from_body_bytes("bypass", &bytes, 1.0).unwrap();
    let mut engine = FilterEngine::new();
    engine.prepare(44_100.0);
    engine.load_cartridge(cart);

    // Deterministic LCG noise at -90 dBFS.
    let mut seed: u32 = 0xDEADBEEF;
    let amp = 3.16e-5_f32;
    let n = 8192;
    let mut l = Vec::with_capacity(n);
    let mut r = Vec::with_capacity(n);
    for _ in 0..n {
        seed = seed.wrapping_mul(1_103_515_245).wrapping_add(12345);
        let v = ((seed >> 16) as f32 / 32768.0 - 1.0) * amp;
        l.push(v);
        r.push(v);
    }
    let in_rms = (l.iter().map(|x| x * x).sum::<f32>() / n as f32).sqrt();
    engine.process_block(&mut l, &mut r, 0.0, 0.0);
    let out_rms = (l.iter().map(|x| x * x).sum::<f32>() / n as f32).sqrt();

    let ratio_db = 20.0 * (out_rms / in_rms).log10();
    assert!(
        ratio_db < 1.0,
        "Bypass amplified noise floor by {ratio_db:.2} dB (in_rms={in_rms:e}, out_rms={out_rms:e}) — \
         AGC or some other stage is generating gain on near-silence"
    );
}
