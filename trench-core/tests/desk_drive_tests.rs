use std::f32::consts::PI;

use trench_core::desk_drive::{DeskDrive, SUPPORTED_MODEL};
use trench_core::{Cartridge, FilterEngine, InputMode};

fn coherent_sine(sample_rate: f32, bin: usize, len: usize, amplitude: f32) -> Vec<f32> {
    let freq = sample_rate * bin as f32 / len as f32;
    (0..len)
        .map(|i| amplitude * (2.0 * PI * freq * i as f32 / sample_rate).sin())
        .collect()
}

fn bin_magnitude(signal: &[f32], bin: usize) -> f32 {
    let len = signal.len() as f32;
    let step = 2.0 * PI * bin as f32 / len;
    let mut re = 0.0f32;
    let mut im = 0.0f32;
    for (n, &sample) in signal.iter().enumerate() {
        let phase = step * n as f32;
        re += sample * phase.cos();
        im -= sample * phase.sin();
    }
    (re * re + im * im).sqrt() / len
}

fn passthrough_cart_with_drive(input_gain_db: f32) -> Cartridge {
    let json = format!(
        r#"{{
            "format": "compiled-v1",
            "name": "passthrough",
            "sampleRate": 44100,
            "drive": {{ "input_gain_dB": {input_gain_db}, "model": "{model}" }},
            "keyframes": [
                {{"label":"M0_Q0","morph":0.0,"q":0.0,"boost":1.0,"stages":[
                    {{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},{{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},
                    {{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},{{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},
                    {{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},{{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}}
                ]}},
                {{"label":"M0_Q100","morph":0.0,"q":1.0,"boost":1.0,"stages":[
                    {{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},{{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},
                    {{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},{{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},
                    {{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},{{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}}
                ]}},
                {{"label":"M100_Q0","morph":1.0,"q":0.0,"boost":1.0,"stages":[
                    {{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},{{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},
                    {{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},{{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},
                    {{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},{{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}}
                ]}},
                {{"label":"M100_Q100","morph":1.0,"q":1.0,"boost":1.0,"stages":[
                    {{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},{{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},
                    {{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},{{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},
                    {{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}},{{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}}
                ]}}
            ]
        }}"#,
        model = SUPPORTED_MODEL
    );
    Cartridge::from_json(&json).expect("passthrough cart")
}

#[test]
fn desk_drive_is_exact_bypass_at_zero_db() {
    let mut drive = DeskDrive::new();
    drive.configure(0.0, SUPPORTED_MODEL);
    let input = [-1.0f32, -0.5, -0.125, 0.0, 0.125, 0.5, 1.0];
    for sample in input {
        assert_eq!(drive.process(sample), sample);
    }
}

#[test]
fn desk_drive_generates_harmonics_when_driven() {
    let mut drive = DeskDrive::new();
    drive.configure(12.0, SUPPORTED_MODEL);
    assert!(drive.is_active());

    let input = coherent_sine(48_000.0, 37, 4096, 0.6);
    let output: Vec<f32> = input.iter().map(|&s| drive.process(s)).collect();

    let fundamental = bin_magnitude(&output, 37);
    let harmonics = bin_magnitude(&output, 74)
        + bin_magnitude(&output, 111)
        + bin_magnitude(&output, 148)
        + bin_magnitude(&output, 185);

    assert!(fundamental > 0.01, "fundamental too small: {fundamental}");
    assert!(
        harmonics / fundamental > 0.02,
        "harmonic ratio too small: fundamental={fundamental}, harmonics={harmonics}"
    );
}

#[test]
fn filter_engine_applies_selectable_pre_cascade_desk_drive() {
    let input = coherent_sine(44_100.0, 41, 4096, 0.55);

    let mut dry_engine = FilterEngine::new();
    dry_engine.prepare(44100.0);
    dry_engine.debug.agc_enabled = false;
    dry_engine.debug.dc_block_enabled = false;
    dry_engine.debug.spatial_enabled = false;
    dry_engine.load_cartridge(passthrough_cart_with_drive(0.0));
    dry_engine.set_input_mode(InputMode::None);
    let mut dry_l = input.clone();
    let mut dry_r = input.clone();
    dry_engine.process_block(&mut dry_l, &mut dry_r, 0.0, 0.0);

    let mut wet_engine = FilterEngine::new();
    wet_engine.prepare(44100.0);
    wet_engine.debug.agc_enabled = false;
    wet_engine.debug.dc_block_enabled = false;
    wet_engine.debug.spatial_enabled = false;
    wet_engine.load_cartridge(passthrough_cart_with_drive(0.0));
    wet_engine.set_slam_drive(0.35);
    wet_engine.set_input_mode(InputMode::MackieDeskSlam);
    let mut wet_l = input.clone();
    let mut wet_r = input.clone();
    wet_engine.process_block(&mut wet_l, &mut wet_r, 0.0, 0.0);

    let dry_wet_tail_delta = dry_l
        .iter()
        .zip(wet_l.iter())
        .skip(256)
        .map(|(&a, &b)| (a - b).abs())
        .fold(0.0f32, f32::max);

    assert!(
        dry_l.iter().all(|s| s.is_finite()) && wet_l.iter().all(|s| s.is_finite()),
        "engine produced non-finite output"
    );
    assert!(
        dry_wet_tail_delta > 1e-3,
        "pre-cascade drive path did not alter the rendered signal: {dry_wet_tail_delta}"
    );
}

#[test]
fn filter_engine_applies_selectable_pre_cascade_cvsd() {
    let input = coherent_sine(44_100.0, 23, 2048, 0.4);

    let mut dry_engine = FilterEngine::new();
    dry_engine.prepare(44100.0);
    dry_engine.debug.agc_enabled = false;
    dry_engine.debug.dc_block_enabled = false;
    dry_engine.debug.spatial_enabled = false;
    dry_engine.load_cartridge(passthrough_cart_with_drive(0.0));
    let mut dry_l = input.clone();
    let mut dry_r = input.clone();
    dry_engine.process_block(&mut dry_l, &mut dry_r, 0.0, 0.0);

    let mut wet_engine = FilterEngine::new();
    wet_engine.prepare(44100.0);
    wet_engine.debug.agc_enabled = false;
    wet_engine.debug.dc_block_enabled = false;
    wet_engine.debug.spatial_enabled = false;
    wet_engine.load_cartridge(passthrough_cart_with_drive(0.0));
    wet_engine.set_input_mode(InputMode::Cvsd);
    let mut wet_l = input.clone();
    let mut wet_r = input.clone();
    wet_engine.process_block(&mut wet_l, &mut wet_r, 0.0, 0.0);

    let max_delta = dry_l
        .iter()
        .zip(wet_l.iter())
        .skip(128)
        .map(|(&a, &b)| (a - b).abs())
        .fold(0.0f32, f32::max);

    assert!(
        wet_l.iter().all(|s| s.is_finite()),
        "CVSD output was non-finite"
    );
    assert!(
        max_delta > 1e-3,
        "CVSD input path did not alter signal: {max_delta}"
    );
}
