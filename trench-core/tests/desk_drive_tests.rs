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
fn desk_drive_keeps_subtle_character_at_zero_slam() {
    let mut drive = DeskDrive::new();
    drive.configure(SUPPORTED_MODEL);
    assert!(drive.is_active());

    let input = coherent_sine(48_000.0, 31, 4096, 0.72);
    let output: Vec<f32> = input.iter().map(|&s| drive.process(s, 0.0)).collect();
    let max_tail_delta = input
        .iter()
        .zip(output.iter())
        .skip(256)
        .map(|(&dry, &wet)| (dry - wet).abs())
        .fold(0.0f32, f32::max);

    assert!(
        max_tail_delta > 0.005,
        "zero-slam Mackie path should still add unity-trim desk character: {max_tail_delta}"
    );
    assert!(
        output.iter().all(|s| s.is_finite()),
        "zero-slam Mackie path produced non-finite output"
    );
}

#[test]
fn desk_drive_unknown_model_bypasses() {
    let mut drive = DeskDrive::new();
    drive.configure("unknown");
    assert!(!drive.is_active());

    for sample in [-1.0f32, -0.5, -0.125, 0.0, 0.125, 0.5, 1.0] {
        assert_eq!(drive.process(sample, 1.0), sample);
    }
}

#[test]
fn desk_drive_generates_harmonics_when_driven() {
    let mut drive = DeskDrive::new();
    drive.configure(SUPPORTED_MODEL);
    assert!(drive.is_active());

    let input = coherent_sine(48_000.0, 37, 4096, 0.6);
    let output: Vec<f32> = input.iter().map(|&s| drive.process(s, 0.35)).collect();

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
fn desk_drive_does_not_force_converter_grid() {
    let mut drive = DeskDrive::new();
    drive.configure(SUPPORTED_MODEL);

    let input = coherent_sine(48_000.0, 29, 2048, 0.7);
    let scale = 524_287.0f32;
    let mut off_grid = 0usize;
    for sample in input {
        let output = drive.process(sample, 0.50);
        let grid = output * scale;
        if (grid - grid.round()).abs() > 0.02 {
            off_grid += 1;
        }
    }

    assert!(
        off_grid > 256,
        "desk slam should be analog saturation, not forced 20-bit quantization: off_grid={off_grid}"
    );
}

#[test]
fn desk_drive_tames_ultrasonic_edge_like_mackity_input_stage() {
    let mut drive = DeskDrive::new();
    drive.prepare(48_000.0);
    drive.configure(SUPPORTED_MODEL);

    let low_input = coherent_sine(48_000.0, 43, 4096, 0.35);
    let high_input = coherent_sine(48_000.0, 1900, 4096, 0.35);

    let low_output: Vec<f32> = low_input.iter().map(|&s| drive.process(s, 0.50)).collect();

    drive.reset();
    let high_output: Vec<f32> = high_input.iter().map(|&s| drive.process(s, 0.50)).collect();

    let low_fundamental = bin_magnitude(&low_output, 43);
    let high_fundamental = bin_magnitude(&high_output, 1900);

    assert!(
        high_fundamental < low_fundamental * 0.45,
        "ultrasonic Mackity filters did not tame high edge: low={low_fundamental}, high={high_fundamental}"
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
