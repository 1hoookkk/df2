//! Render a fast A/B page for the Mackie desk-slam input stage.
//!
//! Run:
//!   cargo test --test desk_slam_audition -- --ignored --nocapture

use std::f32::consts::PI;
use std::path::Path;

use trench_core::desk_drive::{DeskDrive, SUPPORTED_MODEL};
use trench_core::{Cartridge, FilterEngine, InputMode};

const SR: u32 = 48_000;

#[test]
#[ignore = "renders desk-slam WAVs to dev/tmp/desk_slam_audition"]
fn render_desk_slam_audition() {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let out = root.join("dev/tmp/desk_slam_audition");
    std::fs::create_dir_all(&out).expect("mkdir audition dir");

    let source = synth_break_source(7.5);
    let pink = synth_pink_noise(7.5);
    let mackie_subtle = render_mackie_stage(&source, 0.0);
    let mackie_medium = render_mackie_stage(&source, 0.35);
    let mackie_hard = render_mackie_stage(&source, 0.80);
    let plugin_subtle = render_plugin_path(&root, &source, 0.0);
    let plugin_medium = render_plugin_path(&root, &source, 0.35);
    let plugin_hard = render_plugin_path(&root, &source, 0.80);
    let pink_mackie_subtle = render_mackie_stage(&pink, 0.0);
    let pink_mackie_medium = render_mackie_stage(&pink, 0.35);
    let pink_mackie_hard = render_mackie_stage(&pink, 0.80);
    let pink_plugin_subtle = render_plugin_path(&root, &pink, 0.0);
    let pink_plugin_medium = render_plugin_path(&root, &pink, 0.35);
    let pink_plugin_hard = render_plugin_path(&root, &pink, 0.80);

    write_wav(&out.join("00_dry_source.wav"), &source);
    write_wav(&out.join("01_mackie_stage_subtle.wav"), &mackie_subtle);
    write_wav(&out.join("02_mackie_stage_medium.wav"), &mackie_medium);
    write_wav(&out.join("03_mackie_stage_hard.wav"), &mackie_hard);
    write_wav(&out.join("04_plugin_path_subtle.wav"), &plugin_subtle);
    write_wav(&out.join("05_plugin_path_medium.wav"), &plugin_medium);
    write_wav(&out.join("06_plugin_path_hard.wav"), &plugin_hard);
    write_wav(&out.join("10_pink_dry.wav"), &pink);
    write_wav(
        &out.join("11_pink_mackie_stage_subtle.wav"),
        &pink_mackie_subtle,
    );
    write_wav(
        &out.join("12_pink_mackie_stage_medium.wav"),
        &pink_mackie_medium,
    );
    write_wav(
        &out.join("13_pink_mackie_stage_hard.wav"),
        &pink_mackie_hard,
    );
    write_wav(
        &out.join("14_pink_plugin_path_subtle.wav"),
        &pink_plugin_subtle,
    );
    write_wav(
        &out.join("15_pink_plugin_path_medium.wav"),
        &pink_plugin_medium,
    );
    write_wav(&out.join("16_pink_plugin_path_hard.wav"), &pink_plugin_hard);

    let html = r#"<!doctype html>
<meta charset="utf-8">
<title>TRENCH Mackie SLAM audition</title>
<style>
body{margin:0;background:#101113;color:#d8d2c7;font:14px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;padding:24px}
h1{font-size:16px;font-weight:500;margin:0 0 10px;color:#f0dfaa}
h2{font-size:13px;font-weight:500;margin:26px 0 6px;color:#cfc4a0}
.meta{color:#9b9388;margin:0 0 18px;max-width:900px}
.row{display:grid;grid-template-columns:230px minmax(260px,560px);gap:18px;align-items:center;border-top:1px solid #2a2b2f;padding:12px 0}
.name{color:#f0dfaa}.hint{color:#8a847c;font-size:12px;margin-top:3px}
audio{width:100%;height:32px}
</style>
<h1>TRENCH Mackie SLAM audition</h1>
<p class="meta">Same generated drum/reese source. Mackie stage clips are the new input stage alone. Plugin path clips run the bypass body through the shipped engine with MackieDeskSlam plus the same AGC drive mapping the faceplate uses. SLAM 0 is the always-on unity-trim desk character.</p>
<h2>Drum/Reese Source</h2>
<div class="row"><div><div class="name">00 dry source</div><div class="hint">no processing</div></div><audio controls src="00_dry_source.wav"></audio></div>
<div class="row"><div><div class="name">01 Mackie subtle</div><div class="hint">desk input stage, slam 0.00</div></div><audio controls src="01_mackie_stage_subtle.wav"></audio></div>
<div class="row"><div><div class="name">02 Mackie medium</div><div class="hint">desk input stage, slam 0.35</div></div><audio controls src="02_mackie_stage_medium.wav"></audio></div>
<div class="row"><div><div class="name">03 Mackie hard</div><div class="hint">desk input stage, slam 0.80</div></div><audio controls src="03_mackie_stage_hard.wav"></audio></div>
<div class="row"><div><div class="name">04 Plugin subtle</div><div class="hint">runtime path, slam 0.00</div></div><audio controls src="04_plugin_path_subtle.wav"></audio></div>
<div class="row"><div><div class="name">05 Plugin medium</div><div class="hint">runtime path, slam 0.35</div></div><audio controls src="05_plugin_path_medium.wav"></audio></div>
<div class="row"><div><div class="name">06 Plugin hard</div><div class="hint">runtime path, slam 0.80</div></div><audio controls src="06_plugin_path_hard.wav"></audio></div>
<h2>Pink Noise</h2>
<div class="row"><div><div class="name">10 pink dry</div><div class="hint">no processing</div></div><audio controls src="10_pink_dry.wav"></audio></div>
<div class="row"><div><div class="name">11 pink Mackie subtle</div><div class="hint">desk input stage, slam 0.00</div></div><audio controls src="11_pink_mackie_stage_subtle.wav"></audio></div>
<div class="row"><div><div class="name">12 pink Mackie medium</div><div class="hint">desk input stage, slam 0.35</div></div><audio controls src="12_pink_mackie_stage_medium.wav"></audio></div>
<div class="row"><div><div class="name">13 pink Mackie hard</div><div class="hint">desk input stage, slam 0.80</div></div><audio controls src="13_pink_mackie_stage_hard.wav"></audio></div>
<div class="row"><div><div class="name">14 pink Plugin subtle</div><div class="hint">runtime path, slam 0.00</div></div><audio controls src="14_pink_plugin_path_subtle.wav"></audio></div>
<div class="row"><div><div class="name">15 pink Plugin medium</div><div class="hint">runtime path, slam 0.35</div></div><audio controls src="15_pink_plugin_path_medium.wav"></audio></div>
<div class="row"><div><div class="name">16 pink Plugin hard</div><div class="hint">runtime path, slam 0.80</div></div><audio controls src="16_pink_plugin_path_hard.wav"></audio></div>
"#;
    let page = out.join("audition.html");
    std::fs::write(&page, html).expect("write html");
    println!("open: {}", page.display());
}

fn render_mackie_stage(source: &[f32], slam: f32) -> Vec<f32> {
    let mut drive = DeskDrive::new();
    drive.prepare(SR as f32);
    drive.configure(SUPPORTED_MODEL);
    source.iter().map(|&s| drive.process(s, slam)).collect()
}

fn render_plugin_path(root: &Path, source: &[f32], slam: f32) -> Vec<f32> {
    let body = std::fs::read(root.join("bodies/bypass.body240")).expect("read bypass body");
    let cart = Cartridge::from_body_bytes("bypass", &body, 1.0).expect("load bypass body");

    let mut engine = FilterEngine::new();
    engine.prepare(SR as f64);
    engine.load_cartridge(cart);
    engine.debug.spatial_enabled = false;
    engine.set_input_mode(InputMode::MackieDeskSlam);
    engine.set_slam_drive(slam);
    engine.set_agc_drive(1.0 + slam * 7.0);

    let mut left = source.to_vec();
    let mut right = source.to_vec();
    engine.process_block(&mut left, &mut right, 0.0, 0.0);
    left
}

fn synth_break_source(seconds: f32) -> Vec<f32> {
    let n = (seconds * SR as f32) as usize;
    let mut out = Vec::with_capacity(n);
    let mut rng = 0x1234_5678u32;
    let bpm = 172.0f32;
    let beat_secs = 60.0 / bpm;

    for i in 0..n {
        let t = i as f32 / SR as f32;
        let beat_pos = t / beat_secs;
        let beat = beat_pos.floor() as usize;
        let local = (beat_pos - beat as f32) * beat_secs;
        let bar_beat = beat % 4;

        let mut sample = 0.0f32;

        if matches!(bar_beat, 0 | 3) {
            let env = (-local * 17.0).exp();
            let phase = 2.0 * PI * (52.0 * local + 65.0 * (1.0 - (-local * 9.0).exp()) / 9.0);
            sample += phase.sin() * env * 0.78;
        }

        if bar_beat == 2 {
            let env = (-local * 20.0).exp();
            sample += noise(&mut rng) * env * 0.50;
            sample += (2.0 * PI * 190.0 * local).sin() * env * 0.18;
        }

        let eighth_pos = (beat_pos * 2.0).fract() * beat_secs * 0.5;
        let hat_env = (-eighth_pos * 85.0).exp();
        sample += noise(&mut rng) * hat_env * 0.12;

        let saw_a = 2.0 * ((t * 55.0).fract()) - 1.0;
        let saw_b = 2.0 * ((t * 55.7).fract()) - 1.0;
        sample += (saw_a - saw_b) * 0.13;

        out.push((sample * 0.82).clamp(-0.98, 0.98));
    }

    out
}

fn synth_pink_noise(seconds: f32) -> Vec<f32> {
    let n = (seconds * SR as f32) as usize;
    let mut out = Vec::with_capacity(n);
    let mut rng = 0x8765_4321u32;
    let mut b0 = 0.0f32;
    let mut b1 = 0.0f32;
    let mut b2 = 0.0f32;
    let mut b3 = 0.0f32;
    let mut b4 = 0.0f32;
    let mut b5 = 0.0f32;
    let mut b6 = 0.0f32;

    for _ in 0..n {
        let white = noise(&mut rng);
        b0 = 0.99886 * b0 + white * 0.0555179;
        b1 = 0.99332 * b1 + white * 0.0750759;
        b2 = 0.96900 * b2 + white * 0.1538520;
        b3 = 0.86650 * b3 + white * 0.3104856;
        b4 = 0.55000 * b4 + white * 0.5329522;
        b5 = -0.7616 * b5 - white * 0.0168980;
        let pink = b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362;
        b6 = white * 0.115926;
        out.push(pink);
    }

    let peak = out.iter().fold(0.0f32, |m, &s| m.max(s.abs()));
    if peak > 0.0 {
        for sample in &mut out {
            *sample = (*sample / peak) * 0.55;
        }
    }
    out
}

fn noise(state: &mut u32) -> f32 {
    *state ^= *state << 13;
    *state ^= *state >> 17;
    *state ^= *state << 5;
    (*state as f32 / u32::MAX as f32) * 2.0 - 1.0
}

fn write_wav(path: &Path, samples: &[f32]) {
    let peak = samples.iter().fold(0.0f32, |m, &s| m.max(s.abs()));
    let gain = if peak > 0.99 { 0.99 / peak } else { 1.0 };

    let spec = hound::WavSpec {
        channels: 1,
        sample_rate: SR,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };
    let mut writer = hound::WavWriter::create(path, spec).expect("create wav");
    for &sample in samples {
        let q = (sample * gain).clamp(-1.0, 1.0) * i16::MAX as f32;
        writer.write_sample(q as i16).expect("write sample");
    }
    writer.finalize().expect("finalize wav");
}
