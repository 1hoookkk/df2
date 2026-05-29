//! Audit (not a gate): measure the df2 VST engine's output level for normal
//! input, to locate the "so distorted" report. Replicates the shipping gain
//! staging — a resonant cartridge with boost ×4 (the common shipping value),
//! AGC on by default — and reports output peak / RMS / % of samples past full
//! scale (|out| > 1.0 = the host clips it).
//!   cargo test -p trench-core --test audio_headroom_audit -- --nocapture --ignored

use trench_core::{lpc, Cartridge, FilterEngine};

fn resonator(x: &[f64], f: f64, r: f64, sr: f64) -> Vec<f64> {
    let theta = 2.0 * std::f64::consts::PI * f / sr;
    let (a1, a2, b0) = (-2.0 * r * theta.cos(), r * r, 1.0 - r);
    let (mut y1, mut y2) = (0.0, 0.0);
    let mut out = vec![0.0; x.len()];
    for (i, &xi) in x.iter().enumerate() {
        let y = b0 * xi - a1 * y1 - a2 * y2;
        out[i] = y;
        y2 = y1;
        y1 = y;
    }
    out
}

fn cartridge_with_boost(corner: &[[f64; 5]; 6], boost: f64) -> String {
    let labels = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
    let mut kfs = Vec::new();
    for lbl in labels {
        let mut stages = Vec::new();
        for k in corner.iter() {
            stages.push(serde_json::json!({"c0":k[0],"c1":k[1],"c2":k[2],"c3":k[3],"c4":k[4]}));
        }
        for _ in 6..12 {
            stages.push(serde_json::json!({"c0":2.0,"c1":1.0,"c2":2.0,"c3":1.0,"c4":1.0}));
        }
        kfs.push(serde_json::json!({"label":lbl,"boost":boost,"stages":stages}));
    }
    serde_json::json!({"format":"compiled-v1","name":"audit","sampleRate":39062.5,"stages":12,"keyframes":kfs}).to_string()
}

fn white(n: usize, amp: f32) -> Vec<f32> {
    let mut seed = 0x1234_ABCDu64;
    (0..n)
        .map(|_| {
            seed = seed
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            (((seed >> 33) as f32 / (1u64 << 31) as f32) - 1.0) * amp
        })
        .collect()
}

fn measure(label: &str, boost: f64, amp: f32) {
    // a two-formant resonant corner — what the engine is built to play
    let sr = 16000.0;
    let noise: Vec<f64> = white(24000, 1.0).iter().map(|&v| v as f64).collect();
    let corner = lpc::fit_corner(
        &resonator(&resonator(&noise, 650.0, 0.97, sr), 1700.0, 0.96, sr),
        sr,
        39062.5,
    );
    let cart = Cartridge::from_json(&cartridge_with_boost(&corner, boost)).unwrap();

    let mut eng = FilterEngine::new();
    eng.load_cartridge(cart);

    let mut l = white(48_000, amp);
    let mut r = l.clone();
    eng.process_block(&mut l, &mut r, 0.5, 0.5);

    let peak = l.iter().fold(0.0f32, |m, &v| m.max(v.abs()));
    let rms = (l.iter().map(|&v| v * v).sum::<f32>() / l.len() as f32).sqrt();
    let clipped = l.iter().filter(|&&v| v.abs() > 1.0).count();
    let pct = 100.0 * clipped as f32 / l.len() as f32;
    println!(
        "{label:<28} in_amp {amp:.2}  boost ×{boost:.0}  ->  out peak {peak:6.2}  rms {rms:5.2}  clipped {pct:5.1}%"
    );
}

#[test]
#[ignore]
fn engine_output_headroom() {
    println!("\n(|out|>1.0 means the host hard-clips it = audible distortion)\n");
    measure("shipping (boost4, in 0dBFS)", 4.0, 1.0);
    measure("shipping (boost4, in -6dBFS)", 4.0, 0.5);
    measure("shipping (boost4, in -12dBFS)", 4.0, 0.25);
    measure("boost1 ref (in -6dBFS)", 1.0, 0.5);
    println!();
}
