//! Runtime evidence for the approved Motion Take.
//!
//! This binary renders the real `FilterEngine` output. It does not draw a
//! coefficient response plot and it never normalizes a render. The output WAVs
//! are raw 32-bit float mono files so they can be judged by ear in a DAW.

use std::f64::consts::PI;
use std::path::{Path, PathBuf};

use trench_core::cartridge::Cartridge;
use trench_core::engine::{DebugToggles, FilterEngine};
use trench_core::minifloat::{pole_radius, PackedCorners};
use trench_core::motion::path_value_timed;

const SR: f64 = 39_062.5;
const BLOCK: usize = 128;
const BODY: &str = "filters/bodies/CAVL_mason_jar_to_stone_pipe.body240";
const OUT: &str = "out/motion_gap_proof";

const TIMING_PATH: [f32; 18] = [
    0.00, 0.00, 0.00, 0.11, 0.18, 0.24, 0.29, 0.76, 0.62, 0.34, 0.14, 0.86, 0.72, 0.58, 0.22, 1.00,
    0.00, 0.00,
];

const JOINT_PATH: [f32; 15] = [
    0.00, 0.00, 0.00, 0.18, 0.30, 0.20, 0.45, 0.72, 0.68, 0.73, 0.18, 0.84, 1.00, 0.00, 0.00,
];

const RAMP_PATH: [f32; 12] = [
    0.00, 0.00, 0.00, 0.08, 0.70, 0.55, 0.92, 0.70, 0.55, 1.00, 0.00, 0.00,
];

#[derive(Clone, Copy, Debug)]
struct Metrics {
    peak: f64,
    rms: f64,
    crest_db: f64,
    probes_db: [f64; 4],
}

#[derive(Clone, Debug)]
struct BodyRank {
    path: PathBuf,
    radius: f64,
    tau_ms: f64,
}

fn main() {
    let command = std::env::args().nth(1).unwrap_or_else(|| "all".to_string());
    std::fs::create_dir_all(OUT).expect("create proof directory");

    match command.as_str() {
        "timing" => prove_timing(),
        "ramp" => prove_ramp(),
        "joint" => prove_joint(),
        "strike" => prove_strike(),
        "all" => {
            prove_timing();
            prove_ramp();
            prove_joint();
            prove_strike();
        }
        other => panic!("unknown proof '{other}', use timing, ramp, joint, strike, or all"),
    }
}

fn make_engine(body_path: &str, body_only: bool) -> FilterEngine {
    let bytes = std::fs::read(body_path).expect("body exists");
    let mut engine = FilterEngine::new();
    engine.prepare(SR);
    engine.load_cartridge(
        Cartridge::from_body_bytes(body_path, &bytes, 1.0).expect("valid 240-byte body"),
    );
    if body_only {
        let mut debug = DebugToggles::default();
        debug.agc_enabled = false;
        debug.saturation_enabled = false;
        debug.spatial_enabled = false;
        engine.debug = debug;
    }
    engine
}

fn source_sample(index: usize, rng: &mut u64, lp: &mut [f64; 4]) -> f32 {
    *rng = rng
        .wrapping_mul(6_364_136_223_846_793_005)
        .wrapping_add(1_442_695_040_888_963_407);
    let noise = ((*rng >> 40) as f64 / (1u64 << 23) as f64) - 1.0;
    let t = index as f64 / SR;

    // A quiet broadband bed plus a sparse strike-like pulse makes both the
    // spectral and transient effects audible without per-render level matching.
    lp[0] = 0.996 * lp[0] + noise * 0.04;
    lp[1] = 0.965 * lp[1] + noise * 0.08;
    lp[2] = 0.82 * lp[2] + noise * 0.16;
    lp[3] = 0.35 * lp[3] + noise * 0.28;
    let bed = (lp[0] + lp[1] + lp[2] + lp[3]) * 0.004;
    let tone = (2.0 * PI * 220.0 * t).sin() * 0.003;
    let pulse_period = (SR * 0.5) as usize;
    let pulse = if index % pulse_period == 0 { 0.08 } else { 0.0 };
    (bed + tone + pulse) as f32
}

fn render_path(
    path: &[f32],
    closed: bool,
    grid_steps: usize,
    seconds: f64,
    duration_seconds: f64,
    base_morph: f32,
    base_q: f32,
    body_only: bool,
) -> Vec<f32> {
    let mut engine = make_engine(BODY, body_only);
    let count = (seconds * SR) as usize;
    let mut output = Vec::with_capacity(count);
    let mut rng = 0x2545_F491_4F6C_DD1Du64;
    let mut lp = [0.0f64; 4];
    let mut offset = 0usize;

    while offset < count {
        let len = BLOCK.min(count - offset);
        let mut left = Vec::with_capacity(len);
        for i in 0..len {
            left.push(source_sample(offset + i, &mut rng, &mut lp));
        }
        let mut right = left.clone();
        let phase = (offset + len / 2) as f64 / SR / duration_seconds;
        let (morph, q) = path_value_timed(path, phase, closed, base_morph, base_q, 1.0, grid_steps);
        engine.process_block(&mut left, &mut right, morph as f64, q as f64);
        output.extend_from_slice(&left);
        offset += len;
    }
    output
}

fn render_ramp_case(fast: bool, body_only: bool) -> Vec<f32> {
    let mut engine = make_engine(BODY, body_only);
    let seconds = 3.0;
    let count = (seconds * SR) as usize;
    let start = 0.75;
    let duration = if fast { 0.012 } else { 1.0 };
    let mut output = Vec::with_capacity(count);
    let mut rng = 0x2545_F491_4F6C_DD1Du64;
    let mut lp = [0.0f64; 4];
    let mut offset = 0usize;

    while offset < count {
        let len = BLOCK.min(count - offset);
        let mut left = Vec::with_capacity(len);
        for i in 0..len {
            left.push(source_sample(offset + i, &mut rng, &mut lp));
        }
        let mut right = left.clone();
        let t = (offset + len / 2) as f64 / SR;
        let phase = if t <= start {
            0.0
        } else {
            ((t - start) / duration).clamp(0.0, 1.0)
        };
        let (morph, q) = path_value_timed(&RAMP_PATH, phase, false, 0.15, 0.35, 1.0, 0);
        engine.process_block(&mut left, &mut right, morph as f64, q as f64);
        output.extend_from_slice(&left);
        offset += len;
    }
    output
}

fn render_base(seconds: f64, body_only: bool) -> Vec<f32> {
    let mut engine = make_engine(BODY, body_only);
    let count = (seconds * SR) as usize;
    let mut output = Vec::with_capacity(count);
    let mut rng = 0x2545_F491_4F6C_DD1Du64;
    let mut lp = [0.0f64; 4];
    let mut offset = 0usize;
    while offset < count {
        let len = BLOCK.min(count - offset);
        let mut left = Vec::with_capacity(len);
        for i in 0..len {
            left.push(source_sample(offset + i, &mut rng, &mut lp));
        }
        let mut right = left.clone();
        engine.process_block(&mut left, &mut right, 0.15, 0.35);
        output.extend_from_slice(&left);
        offset += len;
    }
    output
}

fn render_strike(body_path: &str, body_only: bool) -> Vec<f32> {
    let mut engine = make_engine(body_path, body_only);
    let seconds = 2.0;
    let count = (seconds * SR) as usize;
    let mut output = Vec::with_capacity(count);
    let mut offset = 0usize;
    while offset < count {
        let len = BLOCK.min(count - offset);
        let mut left = vec![0.0f32; len];
        if offset == 0 {
            left[0] = 0.25;
        }
        let mut right = left.clone();
        engine.process_block(&mut left, &mut right, 0.5, 1.0);
        output.extend_from_slice(&left);
        offset += len;
    }
    output
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
    Metrics {
        peak,
        rms,
        crest_db: 20.0 * (peak / rms.max(1.0e-15)).log10(),
        probes_db: [125.0, 500.0, 2_000.0, 8_000.0].map(|hz| goertzel_db(samples, hz)),
    }
}

fn goertzel_db(samples: &[f32], hz: f64) -> f64 {
    goertzel_db_window(samples, hz, 0, samples.len())
}

fn goertzel_db_window(samples: &[f32], hz: f64, start: usize, end: usize) -> f64 {
    let start = start.min(samples.len());
    let end = end.min(samples.len()).max(start + 1).min(samples.len());
    let window = end.saturating_sub(start).max(1);
    let omega = 2.0 * PI * hz / SR;
    let mut re = 0.0;
    let mut im = 0.0;
    for (i, &sample) in samples[start..end].iter().enumerate() {
        let w = 0.5 - 0.5 * (2.0 * PI * i as f64 / window as f64).cos();
        let phase = omega * i as f64;
        let x = sample as f64 * w;
        re += x * phase.cos();
        im -= x * phase.sin();
    }
    let amplitude = (re * re + im * im).sqrt() * 2.0 / window as f64;
    20.0 * amplitude.max(1.0e-15).log10()
}

fn rms_window(samples: &[f32], start: usize, end: usize) -> f64 {
    let start = start.min(samples.len());
    let end = end.min(samples.len()).max(start + 1).min(samples.len());
    let sum = samples[start..end]
        .iter()
        .map(|&x| (x as f64) * (x as f64))
        .sum::<f64>();
    (sum / (end - start).max(1) as f64).sqrt()
}

fn peak_after(samples: &[f32], start: usize, end: usize) -> f64 {
    samples[start.min(samples.len())..end.min(samples.len())]
        .iter()
        .map(|&x| x.abs() as f64)
        .fold(0.0, f64::max)
}

fn null_difference_db(reference: &[f32], other: &[f32], start: usize, end: usize) -> f64 {
    let start = start.min(reference.len()).min(other.len());
    let end = end
        .min(reference.len())
        .min(other.len())
        .max(start + 1)
        .min(reference.len().min(other.len()));
    let mut diff_sq = 0.0;
    let mut ref_sq = 0.0;
    for (&a, &b) in reference[start..end].iter().zip(&other[start..end]) {
        let d = b as f64 - a as f64;
        diff_sq += d * d;
        ref_sq += a as f64 * a as f64;
    }
    20.0 * (diff_sq / ref_sq.max(1.0e-30)).sqrt().log10()
}

fn write_float_wav(path: impl AsRef<Path>, samples: &[f32]) {
    let data_bytes = (samples.len() * std::mem::size_of::<f32>()) as u32;
    let mut wav = Vec::with_capacity(44 + data_bytes as usize);
    wav.extend_from_slice(b"RIFF");
    wav.extend_from_slice(&(36 + data_bytes).to_le_bytes());
    wav.extend_from_slice(b"WAVEfmt ");
    wav.extend_from_slice(&16u32.to_le_bytes());
    wav.extend_from_slice(&3u16.to_le_bytes());
    wav.extend_from_slice(&1u16.to_le_bytes());
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

fn prove_timing() {
    let free = render_path(&TIMING_PATH, true, 0, 8.0, 2.0, 0.20, 0.35, false);
    let grid = render_path(&TIMING_PATH, true, 8, 8.0, 2.0, 0.20, 0.35, false);
    write_float_wav(format!("{OUT}/timing_free.wav"), &free);
    write_float_wav(format!("{OUT}/timing_grid_8.wav"), &grid);
    println!("\nGAP 1 — human timing vs grid (real FilterEngine output, raw, unnormalized)");
    print_metrics("free timing", metrics(&free));
    print_metrics("grid-locked timing (8 subdivisions)", metrics(&grid));
    println!(
        "free-vs-grid null: {:.2} dB over full render; files: {OUT}/timing_free.wav, {OUT}/timing_grid_8.wav",
        null_difference_db(&free, &grid, 0, free.len())
    );
    println!(
        "recorded event times: [0.000, 0.110, 0.290, 0.340, 0.720, 1.000]; grid times: [0.000, 0.125, 0.250, 0.375, 0.750, 1.000]"
    );
}

fn prove_ramp() {
    let fast = render_ramp_case(true, false);
    let slow = render_ramp_case(false, false);
    let base = render_base(3.0, false);
    let start = (0.75 * SR) as usize;
    let end = (1.75 * SR) as usize;
    write_float_wav(format!("{OUT}/ramp_fast_jab.wav"), &fast);
    write_float_wav(format!("{OUT}/ramp_slow_sweep.wav"), &slow);
    write_float_wav(format!("{OUT}/ramp_base_reference.wav"), &base);
    println!("\nGAP 2 — 80 ms coefficient ramp against fast and slow takes");
    print_metrics("fast 12 ms jab", metrics(&fast));
    print_metrics("slow 1 s sweep", metrics(&slow));
    println!(
        "motion-vs-base output difference over movement window: fast={:.2} dB, slow={:.2} dB",
        null_difference_db(&base, &fast, start, end),
        null_difference_db(&base, &slow, start, end)
    );
    let fast_early = rms_window(&fast, start, start + (0.020 * SR) as usize);
    let fast_late = rms_window(
        &fast,
        start + (0.080 * SR) as usize,
        start + (0.160 * SR) as usize,
    );
    let slow_early = rms_window(&slow, start, start + (0.020 * SR) as usize);
    let slow_mid = rms_window(
        &slow,
        start + (0.400 * SR) as usize,
        start + (0.500 * SR) as usize,
    );
    println!(
        "output RMS windows: fast[0-20ms]={:.6}, fast[80-160ms]={:.6}; slow[0-20ms]={:.6}, slow[400-500ms]={:.6}",
        fast_early, fast_late, slow_early, slow_mid
    );
    println!(
        "files: {OUT}/ramp_fast_jab.wav, {OUT}/ramp_slow_sweep.wav, {OUT}/ramp_base_reference.wav"
    );
}

fn prove_joint() {
    let joint = render_path(&JOINT_PATH, true, 0, 8.0, 2.0, 0.15, 0.20, false);
    let morph_only: Vec<f32> = JOINT_PATH
        .chunks_exact(3)
        .flat_map(|p| [p[0], p[1], 0.0])
        .collect();
    let q_only: Vec<f32> = JOINT_PATH
        .chunks_exact(3)
        .flat_map(|p| [p[0], 0.0, p[2]])
        .collect();
    let morph = render_path(&morph_only, true, 0, 8.0, 2.0, 0.15, 0.20, false);
    let q = render_path(&q_only, true, 0, 8.0, 2.0, 0.15, 0.20, false);
    write_float_wav(format!("{OUT}/joint_morph_q_take.wav"), &joint);
    write_float_wav(format!("{OUT}/joint_morph_only_reference.wav"), &morph);
    write_float_wav(format!("{OUT}/joint_q_only_reference.wav"), &q);
    println!("\nHEADLINE — joint Morph×Q Motion Take");
    print_metrics("joint Morph×Q", metrics(&joint));
    println!(
        "joint-vs-Morph-only null: {:.2} dB; joint-vs-Q-only null: {:.2} dB",
        null_difference_db(&morph, &joint, 0, joint.len()),
        null_difference_db(&q, &joint, 0, joint.len())
    );
    println!(
        "by-ear files: {OUT}/joint_morph_q_take.wav, {OUT}/joint_morph_only_reference.wav, {OUT}/joint_q_only_reference.wav"
    );
}

fn rank_bodies() -> Vec<BodyRank> {
    let mut ranks = Vec::new();
    let entries = std::fs::read_dir("filters/bodies").expect("body directory exists");
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|x| x.to_str()) != Some("body240") {
            continue;
        }
        let Ok(bytes) = std::fs::read(&path) else {
            continue;
        };
        let Ok(packed) = PackedCorners::from_body_bytes(&bytes) else {
            continue;
        };
        let rows = packed.interpolate_biquad(0.5, 1.0);
        let radius = rows
            .iter()
            .map(|row| pole_radius(row[3], row[4]))
            .fold(0.0, f64::max);
        let tau_ms = if radius > 0.0 && radius < 1.0 {
            -1_000.0 / (SR * radius.ln())
        } else {
            f64::INFINITY
        };
        ranks.push(BodyRank {
            path,
            radius,
            tau_ms,
        });
    }
    ranks.sort_by(|a, b| b.radius.partial_cmp(&a.radius).unwrap());
    ranks
}

fn strike_decay_ms(samples: &[f32]) -> (f64, f64, f64) {
    let peak = peak_after(samples, (0.001 * SR) as usize, (0.020 * SR) as usize).max(1.0e-12);
    let mut last_40 = 0usize;
    let mut last_60 = 0usize;
    for (i, &sample) in samples.iter().enumerate() {
        let db = 20.0 * ((sample.abs() as f64) / peak).max(1.0e-15).log10();
        if db >= -20.0 {
            last_40 = i;
        }
        if db >= -40.0 {
            last_60 = i;
        }
    }
    let rms_20 = rms_window(samples, 0, (0.020 * SR) as usize);
    let rms_100 = rms_window(samples, (0.100 * SR) as usize, (0.200 * SR) as usize);
    (
        last_40 as f64 * 1_000.0 / SR,
        last_60 as f64 * 1_000.0 / SR,
        rms_100 / rms_20.max(1.0e-15),
    )
}

fn prove_strike() {
    let ranks = rank_bodies();
    let best = ranks.first().expect("at least one body");
    let best_name = best.path.to_string_lossy();
    let body_solo = render_strike(&best_name, true);
    let product = render_strike(&best_name, false);
    write_float_wav(format!("{OUT}/strike_body_solo.wav"), &body_solo);
    write_float_wav(format!("{OUT}/strike_product_output.wav"), &product);
    let (solo_40, solo_60, solo_tail_ratio) = strike_decay_ms(&body_solo);
    let (product_40, product_60, product_tail_ratio) = strike_decay_ms(&product);
    println!("\nGAP 3 — ZAP strike decay on the highest-radius shipped body");
    println!(
        "selected body: {} | max pole radius at M50/Q100={:.7} | pole tau={:.2} ms",
        best_name, best.radius, best.tau_ms
    );
    println!(
        "body-solo decay: above -20 dB until {:.2} ms, above -40 dB until {:.2} ms, 100-200ms/first-20ms RMS ratio={:.6}",
        solo_40, solo_60, solo_tail_ratio
    );
    println!(
        "product output decay: above -20 dB until {:.2} ms, above -40 dB until {:.2} ms, 100-200ms/first-20ms RMS ratio={:.6}",
        product_40, product_60, product_tail_ratio
    );
    print_metrics("body-solo strike", metrics(&body_solo));
    print_metrics("product strike", metrics(&product));
    println!(
        "top three radius candidates: {}",
        ranks
            .iter()
            .take(3)
            .map(|r| format!("{} ({:.7}, {:.1}ms)", r.path.display(), r.radius, r.tau_ms))
            .collect::<Vec<_>>()
            .join("; ")
    );
    println!("files: {OUT}/strike_body_solo.wav, {OUT}/strike_product_output.wav");
}
