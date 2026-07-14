//! Render a raw before/after proof for the Motion Take prototype.
//!
//! This is intentionally a small deterministic harness. It uses the same
//! `FilterEngine` and `motion::path_value` that the processor path uses, keeps
//! the input level fixed, and never normalizes either render after the fact.

use std::f64::consts::PI;

use trench_core::cartridge::Cartridge;
use trench_core::engine::FilterEngine;
use trench_core::keyframe::{keyframe_loop_value_mode, LoopMode};
use trench_core::motion::path_value;

const SR: f64 = 39_062.5;
const BPM: f64 = 120.0;
const BEATS_PER_BAR: f64 = 4.0;
const SECONDS: f64 = 8.0;
const BLOCK: usize = 128;

const TAKE_PATH: [f32; 12] = [
    0.00, 0.00, 0.30, 0.15, 0.60, 0.45, 0.80, 0.20, 0.40, -0.25, 0.00, 0.00,
];

const RISER_PATH: [f32; 6] = [0.00, 0.00, 0.40, 0.20, 0.80, 0.45];

#[derive(Clone, Copy)]
struct Metrics {
    peak: f64,
    rms: f64,
    crest_db: f64,
    probes_db: [f64; 4],
}

fn source_sample(index: usize, rng: &mut u64, lp: &mut [f64; 6]) -> f32 {
    *rng = rng
        .wrapping_mul(6_364_136_223_846_793_005)
        .wrapping_add(1_442_695_040_888_963_407);
    let noise = ((*rng >> 40) as f64 / (1u64 << 23) as f64) - 1.0;
    let t = index as f64 / SR;
    let pulse_phase = (t * 2.0).fract();
    let pulse = if pulse_phase < 0.035 {
        (1.0 - pulse_phase / 0.035).powi(2)
    } else {
        0.0
    };

    lp[0] = 0.99886 * lp[0] + noise * 0.0555179;
    lp[1] = 0.99332 * lp[1] + noise * 0.0750759;
    lp[2] = 0.96900 * lp[2] + noise * 0.1538520;
    lp[3] = 0.86650 * lp[3] + noise * 0.3104856;
    lp[4] = 0.55000 * lp[4] + noise * 0.5329522;
    lp[5] = -0.7616 * lp[5] - noise * 0.0168980;
    let bed = (lp[0] + lp[1] + lp[2] + lp[3] + lp[4] + lp[5]) * 0.012;
    let tone = (2.0 * PI * 220.0 * t).sin() * 0.003;
    (bed + tone + pulse * 0.02) as f32
}

fn render(kind: RenderKind) -> Vec<f32> {
    let body = std::fs::read("filters/bodies/CAVL_mason_jar_to_stone_pipe.body240")
        .expect("canonical body is present");
    let mut engine = FilterEngine::new();
    engine.prepare(SR);
    engine.load_cartridge(Cartridge::from_body_bytes("motion-proof", &body, 1.0).unwrap());

    let count = (SECONDS * SR) as usize;
    let mut output = Vec::with_capacity(count);
    let mut rng = 0x2545_F491_4F6C_DD1Du64;
    let mut lp = [0.0f64; 6];
    let mut offset = 0usize;
    while offset < count {
        let len = BLOCK.min(count - offset);
        let mut left = Vec::with_capacity(len);
        for i in 0..len {
            left.push(source_sample(offset + i, &mut rng, &mut lp));
        }
        let mut right = left.clone();
        let ppq = (offset + len / 2) as f64 / SR * BPM / 60.0;
        let (morph, q) = match kind {
            RenderKind::LegacyPendulum => (
                keyframe_loop_value_mode(0.20, 0.80, 2.0, ppq, BEATS_PER_BAR, LoopMode::Pendulum)
                    as f64,
                0.35,
            ),
            RenderKind::MotionTake => {
                let phase = ppq / (2.0 * BEATS_PER_BAR);
                let (m, q) = path_value(&TAKE_PATH, phase, true, 0.20, 0.35, 1.0);
                (m as f64, q as f64)
            }
            RenderKind::MotionRiser => {
                let phase = ppq / (4.0 * BEATS_PER_BAR);
                let (m, q) = path_value(&RISER_PATH, phase, false, 0.20, 0.35, 1.0);
                (m as f64, q as f64)
            }
        };
        engine.process_block(&mut left, &mut right, morph, q);
        output.extend_from_slice(&left);
        offset += len;
    }
    output
}

#[derive(Clone, Copy)]
enum RenderKind {
    LegacyPendulum,
    MotionTake,
    MotionRiser,
}

fn metrics(samples: &[f32]) -> Metrics {
    let mut peak = 0.0f64;
    let mut sum_sq = 0.0f64;
    for &sample in samples {
        let x = sample as f64;
        peak = peak.max(x.abs());
        sum_sq += x * x;
    }
    let rms = (sum_sq / samples.len().max(1) as f64).sqrt();
    let crest_db = 20.0 * (peak / rms.max(1.0e-15)).log10();
    let probes = [125.0, 500.0, 2_000.0, 8_000.0].map(|hz| goertzel_db(samples, hz));
    Metrics {
        peak,
        rms,
        crest_db,
        probes_db: probes,
    }
}

fn goertzel_db(samples: &[f32], hz: f64) -> f64 {
    let window = 8_192.min(samples.len());
    let start = samples.len() - window;
    let omega = 2.0 * PI * hz / SR;
    let mut re = 0.0;
    let mut im = 0.0;
    for (i, &sample) in samples[start..].iter().enumerate() {
        let w = 0.5 - 0.5 * (2.0 * PI * i as f64 / window as f64).cos();
        let phase = omega * i as f64;
        let x = sample as f64 * w;
        re += x * phase.cos();
        im -= x * phase.sin();
    }
    let amplitude = (re * re + im * im).sqrt() * 2.0 / window as f64;
    20.0 * amplitude.max(1.0e-15).log10()
}

fn null_difference_db(before: &[f32], after: &[f32]) -> f64 {
    let mut diff_sq = 0.0;
    let mut ref_sq = 0.0;
    for (&a, &b) in before.iter().zip(after) {
        let d = b as f64 - a as f64;
        diff_sq += d * d;
        ref_sq += a as f64 * a as f64;
    }
    20.0 * (diff_sq / ref_sq.max(1.0e-30)).sqrt().log10()
}

fn write_float_wav(path: &str, samples: &[f32]) {
    let data_bytes = (samples.len() * std::mem::size_of::<f32>()) as u32;
    let mut wav = Vec::with_capacity(44 + data_bytes as usize);
    wav.extend_from_slice(b"RIFF");
    wav.extend_from_slice(&(36 + data_bytes).to_le_bytes());
    wav.extend_from_slice(b"WAVEfmt ");
    wav.extend_from_slice(&16u32.to_le_bytes());
    wav.extend_from_slice(&3u16.to_le_bytes()); // IEEE float
    wav.extend_from_slice(&1u16.to_le_bytes()); // mono
    wav.extend_from_slice(&(SR as u32).to_le_bytes());
    wav.extend_from_slice(&((SR as u32) * 4).to_le_bytes());
    wav.extend_from_slice(&4u16.to_le_bytes());
    wav.extend_from_slice(&32u16.to_le_bytes());
    wav.extend_from_slice(b"data");
    wav.extend_from_slice(&data_bytes.to_le_bytes());
    for &sample in samples {
        wav.extend_from_slice(&sample.to_le_bytes());
    }
    std::fs::write(path, wav).expect("write proof wav");
}

fn print_metrics(label: &str, value: Metrics) {
    println!(
        "{label}: peak={:.6} rms={:.6} crest={:.2} dBFS probes[125,500,2k,8k]=[{:.2},{:.2},{:.2},{:.2}] dBFS",
        value.peak,
        value.rms,
        value.crest_db,
        value.probes_db[0],
        value.probes_db[1],
        value.probes_db[2],
        value.probes_db[3],
    );
}

fn main() {
    let out = "out/motion_take_proof";
    std::fs::create_dir_all(out).expect("create proof directory");

    let before = render(RenderKind::LegacyPendulum);
    let after = render(RenderKind::MotionTake);
    let riser = render(RenderKind::MotionRiser);
    let before_metrics = metrics(&before);
    let after_metrics = metrics(&after);
    let riser_metrics = metrics(&riser);

    write_float_wav(&format!("{out}/before_legacy_pendulum.wav"), &before);
    write_float_wav(&format!("{out}/after_motion_take_closed.wav"), &after);
    write_float_wav(&format!("{out}/after_motion_take_open_riser.wav"), &riser);

    println!("Motion Take proof — fixed input, raw float output, no normalization");
    print_metrics("before legacy pendulum", before_metrics);
    print_metrics("after closed Motion Take", after_metrics);
    print_metrics("after open Motion Take riser", riser_metrics);
    println!(
        "closed-vs-legacy null difference: {:.2} dB (difference energy / legacy energy)",
        null_difference_db(&before, &after)
    );
    println!("proof files: {out}");
}
