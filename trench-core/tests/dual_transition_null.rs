//! E3 acceptance: the dual frozen-cascade transition law must be block-size
//! invariant. Gate: 16-vs-512 host-block null better than −60 dBFS on the
//! E3 test set (4 signals × 4 automation durations × 2 directions).
//!
//! E3 proved no engine can null across block sizes if the CONTROL INPUT
//! itself is sampled at block rate (the target values seen differ), so the
//! engine-side invariance statement is: given the SAME control event
//! stream, audio chunking must not change the output. Control here is the
//! E3 morph automation one-pole smoothed at a fixed 512-sample cadence and
//! delivered identically to both runs; only the audio chunking differs.
//! The old ramped-coefficient path fails this exact protocol (its ramp
//! lengths follow chunk size); E3 measured its worst null at −2.640 dBFS.
//!
//! Fixture: sf_mouth_frame.body240 — the E3 body, clean-room provenance,
//! SHA-256 45C74AE7BF9AB2696A3A57E93FBFCD1E9E721EAEB840B48B3F967DEA1C244B89.

use trench_core::{Cartridge, FilterEngine};

const SR: f64 = 39_062.5;
const TOTAL_SECONDS: f64 = 0.65;
const TRANSITION_START_SECONDS: f64 = 0.20;
const CONTROL_TAU_SECONDS: f64 = 0.035;
const CONTROL_CADENCE: usize = 512;
const DURATIONS_MS: [u32; 4] = [1, 10, 35, 100];
const GATE_DBFS: f64 = -60.0;

const BODY: &[u8; 240] = include_bytes!("fixtures/sf_mouth_frame.body240");

fn requested_morph(sample: usize, duration_ms: u32, reverse: bool) -> f64 {
    let start = (TRANSITION_START_SECONDS * SR).round() as usize;
    let n = ((duration_ms as f64 / 1000.0) * SR).round().max(1.0) as usize;
    let forward = if sample <= start {
        0.0
    } else if sample >= start + n {
        1.0
    } else {
        (sample - start) as f64 / n as f64
    };
    if reverse {
        1.0 - forward
    } else {
        forward
    }
}

/// One smoothed morph value per 512-sample control period — the shared
/// control event stream for every block size.
fn control_stream(n: usize, duration_ms: u32, reverse: bool) -> Vec<f64> {
    let alpha = 1.0 - (-(CONTROL_CADENCE as f64 / SR) / CONTROL_TAU_SECONDS).exp();
    let mut m = if reverse { 1.0 } else { 0.0 };
    (0..n.div_ceil(CONTROL_CADENCE))
        .map(|ci| {
            let target = requested_morph(ci * CONTROL_CADENCE, duration_ms, reverse);
            m += (target - m) * alpha;
            m.clamp(0.0, 1.0)
        })
        .collect()
}

fn make_signals(n: usize) -> Vec<(&'static str, Vec<f32>)> {
    use std::f64::consts::PI;
    let t0 = (TRANSITION_START_SECONDS * SR).round() as usize;
    let mut out = Vec::new();

    let mut impulse = vec![0.0f32; n];
    for (offset_s, amp) in [(-0.040, 1.0f32), (0.002, -0.75), (0.055, 0.5)] {
        let idx = (t0 as f64 + offset_s * SR).round().max(0.0) as usize;
        if idx < n {
            impulse[idx] = amp * 0.25;
        }
    }
    out.push(("impulse", impulse));

    let mut sine = vec![0.0f32; n];
    let begin = (t0 as f64 - 0.100 * SR).round().max(0.0) as usize;
    let end = ((t0 as f64 + 0.180 * SR).round() as usize).min(n);
    for (i, s) in sine.iter_mut().enumerate().take(end).skip(begin) {
        let u = (i - begin) as f64 / (end - begin).max(1) as f64;
        let env = (PI * u).sin().powi(2);
        let t = i as f64 / SR;
        *s = (env
            * (0.74 * (2.0 * PI * 620.0 * t).sin() + 0.26 * (2.0 * PI * 1900.0 * t).sin())
            * 0.25) as f32;
    }
    out.push(("sine_burst", sine));

    let mut pink = vec![0.0f32; n];
    let mut seed: u32 = 0xA57E_19D3;
    let (mut b0, mut b1, mut b2) = (0.0f64, 0.0, 0.0);
    for x in &mut pink {
        seed = seed.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
        let white = ((seed >> 8) as f64 / ((u32::MAX >> 8) as f64)) * 2.0 - 1.0;
        b0 = 0.99886 * b0 + white * 0.0555179;
        b1 = 0.96900 * b1 + white * 0.1538520;
        b2 = 0.55000 * b2 + white * 0.5329522;
        *x = ((b0 + b1 + b2 + white * 0.5362) * 0.08) as f32;
    }
    out.push(("pink_noise", pink));

    let mut perc = vec![0.0f32; n];
    let starts = [
        (t0 as f64 - 0.065 * SR).round() as usize,
        (t0 as f64 + 0.070 * SR).round() as usize,
    ];
    let mut pseed: u32 = 0xC0FF_EE11;
    for (hit, &start) in starts.iter().enumerate() {
        for i in start..n {
            let dt = (i - start) as f64 / SR;
            if dt > 0.24 {
                break;
            }
            pseed = pseed.wrapping_mul(1_103_515_245).wrapping_add(12_345);
            let noise = ((pseed >> 9) as f64 / ((u32::MAX >> 9) as f64)) * 2.0 - 1.0;
            let env = (-dt * (22.0 + hit as f64 * 8.0)).exp();
            let modes = (2.0 * PI * 115.0 * dt).sin()
                + 0.62 * (2.0 * PI * 730.0 * dt).sin()
                + 0.38 * (2.0 * PI * 2450.0 * dt).sin();
            perc[i] += (env * (0.72 * modes + 0.28 * noise) * 0.25) as f32;
        }
    }
    out.push(("percussive_decay", perc));

    out
}

fn engine() -> FilterEngine {
    let cart = Cartridge::from_body_bytes("E3 sf_mouth_frame", BODY, 1.0).expect("body load");
    assert_eq!(
        cart.packed.to_rom_bytes(),
        *BODY,
        "must preserve packed bytes"
    );
    let mut e = FilterEngine::new();
    e.prepare(SR);
    e.debug.agc_enabled = false;
    e.debug.dc_block_enabled = false;
    e.debug.saturation_enabled = false;
    e.debug.spatial_enabled = false;
    e.set_amount(1.0);
    e.load_cartridge(cart);
    e
}

/// Render through the production engine at one audio block size, driven by
/// the shared control stream.
fn render(input: &[f32], control: &[f64], block: usize) -> Vec<f32> {
    let mut e = engine();
    let mut left = input.to_vec();
    let mut right = input.to_vec();
    let mut offset = 0usize;
    while offset < left.len() {
        let len = (left.len() - offset).min(block);
        let morph = control[offset / CONTROL_CADENCE];
        e.process_block(
            &mut left[offset..offset + len],
            &mut right[offset..offset + len],
            morph,
            0.0,
        );
        offset += len;
    }
    assert_eq!(
        left.iter().filter(|x| !x.is_finite()).count(),
        0,
        "nonfinite output"
    );
    left
}

fn dbfs(v: f64) -> f64 {
    20.0 * v.abs().max(1.0e-15).log10()
}

#[test]
fn dual_law_block_null_beats_minus_60_dbfs_on_e3_set() {
    let n = (TOTAL_SECONDS * SR).round() as usize;
    let mut worst = f64::NEG_INFINITY;
    for (name, signal) in make_signals(n) {
        for duration_ms in DURATIONS_MS {
            for reverse in [false, true] {
                let control = control_stream(n, duration_ms, reverse);
                let a = render(&signal, &control, 16);
                let b = render(&signal, &control, 512);
                let peak = a
                    .iter()
                    .zip(&b)
                    .map(|(x, y)| (*x as f64 - *y as f64).abs())
                    .fold(0.0, f64::max);
                let null = dbfs(peak);
                worst = worst.max(null);
                assert!(
                    null < GATE_DBFS,
                    "{name} {duration_ms}ms reverse={reverse}: 16-vs-512 null {null:.2} dBFS \
                     exceeds {GATE_DBFS} dBFS gate"
                );
            }
        }
    }
    println!("worst 16-vs-512 null across E3 set: {worst:.2} dBFS");
}
