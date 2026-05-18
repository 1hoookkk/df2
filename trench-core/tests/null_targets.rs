//! Null-target measurements.
//!
//! Static null target:  passthrough, steady state,        residual < -120 dBFS.
//! Dynamic null target: passthrough, ramp engaged,        residual <  -90 dBFS.
//!
//! Both tests feed the real trench-core cascade. The static test leaves the
//! cascade in its default (identity) state. The dynamic test calls
//! `set_targets` on every control block with `ramp_samples = BLOCK_SIZE` so
//! the coefficient-ramping pipeline is exercised end-to-end while the target
//! stays identity.

use trench_core::{Cascade, BLOCK_SIZE};

const PASS_STAGE: [f64; 5] = [1.0, 0.0, 0.0, 0.0, 0.0];
const PASS_CORNER: [[f64; 5]; 6] = [PASS_STAGE; 6];

fn make_noise(n: usize) -> Vec<f32> {
    let mut seed: u32 = 0xC0FF_EE42;
    let mut out = Vec::with_capacity(n);
    for _ in 0..n {
        seed = seed.wrapping_mul(1_103_515_245).wrapping_add(12_345);
        let u = (seed >> 8) as f32 / ((u32::MAX >> 8) as f32);
        out.push((u * 2.0 - 1.0) * 0.5);
    }
    out
}

fn peak_dbfs(residual: &[f32]) -> f64 {
    let peak = residual.iter().map(|&x| x.abs()).fold(0.0f32, f32::max) as f64;
    if peak <= 0.0 {
        -300.0
    } else {
        20.0 * peak.log10()
    }
}

#[test]
fn static_null_passthrough() {
    let mut cascade = Cascade::new();

    let n = BLOCK_SIZE * 256;
    let input = make_noise(n);
    let mut output = input.clone();
    cascade.process_block_mono(&mut output);

    assert!(
        !cascade.take_instability_flag(),
        "cascade reported instability during static null"
    );

    let residual: Vec<f32> = input
        .iter()
        .zip(output.iter())
        .map(|(&i, &o)| o - i)
        .collect();
    let db = peak_dbfs(&residual);
    eprintln!("static null peak residual: {db:+.1} dBFS");
    assert!(
        db < -120.0,
        "static null target missed: peak residual {db:+.1} dBFS (target < -120 dBFS)"
    );
}

#[test]
fn dynamic_null_passthrough_ramped() {
    let mut cascade = Cascade::new();

    let n = BLOCK_SIZE * 256;
    let input = make_noise(n);
    let mut output = input.clone();

    let blocks = output.len() / BLOCK_SIZE;
    for b in 0..blocks {
        cascade.set_targets(&PASS_CORNER, BLOCK_SIZE);
        cascade.set_boost(1.0, BLOCK_SIZE);
        let slice = &mut output[b * BLOCK_SIZE..(b + 1) * BLOCK_SIZE];
        cascade.process_block_mono(slice);
    }

    assert!(
        !cascade.take_instability_flag(),
        "cascade reported instability during dynamic null"
    );

    let residual: Vec<f32> = input
        .iter()
        .zip(output.iter())
        .map(|(&i, &o)| o - i)
        .collect();
    let db = peak_dbfs(&residual);
    eprintln!("dynamic null peak residual: {db:+.1} dBFS");
    assert!(
        db < -90.0,
        "dynamic null target missed: peak residual {db:+.1} dBFS (target < -90 dBFS)"
    );
}
