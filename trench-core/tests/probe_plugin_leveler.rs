//! PLUGIN LEVELER ATTRIBUTION — which stage eats the dynamics?
//!
//! The probe_real_material ladder claimed the 13.5 dB leveling span "survives"
//! slam=0 / nosat / agc-cap individually. That was false evidence: in that
//! ladder (a) `set_slam_drive` is a no-op in InputMode::None, and (b) the -1.0
//! "nosat" sentinel was passed to `set_agc_drive` (clamped to 1.0) and
//! `debug.saturation_enabled` was never touched. This probe runs the REAL
//! combination matrix on the shipping-plugin chain:
//!
//!   clean input -> cascade -> AGC(drive 1.0) -> boost -> DC -> saturate(0.9)
//!               -> [C++ post-engine SLAM pressure: +12dB*s into knee-0.72 tanh]
//!
//! The post-engine SLAM stage lives in juce-shell/source/dsp/SlamStage.h
//! (slamOutputPressureBlockStereo); its law is replicated here exactly so the
//! Rust probe finally measures the chain the plugin actually ships.
//!
//! Run: cargo test -p trench-core --test probe_plugin_leveler -- --ignored --nocapture

use trench_core::{Cartridge, FilterEngine, InputMode};

const SR_EMU: f64 = 39_062.5;
const BLOCK: usize = 256;

fn rms(x: &[f32]) -> f32 {
    (x.iter().map(|s| s * s).sum::<f32>() / x.len().max(1) as f32).sqrt()
}

/// Exact replica of trench::slamOutputPressureBlockStereo (SlamStage.h):
/// drive = 10^(12*s/20), knee 0.72, tanh rounding above the knee. slam<=1e-4 = bypass.
fn slam_output_pressure(l: &mut [f32], r: &mut [f32], slam: f32) {
    let s = slam.clamp(0.0, 1.0);
    if s <= 1.0e-4 {
        return;
    }
    let drive = 10f32.powf(12.0 * s / 20.0);
    const KNEE: f32 = 0.72;
    let lim = |x: f32| {
        let a = x.abs();
        if a <= KNEE {
            x
        } else {
            x.signum() * (KNEE + (1.0 - KNEE) * ((a - KNEE) / (1.0 - KNEE)).tanh())
        }
    };
    for (a, b) in l.iter_mut().zip(r.iter_mut()) {
        *a = lim(*a * drive);
        *b = lim(*b * drive);
    }
}

/// Pink-ish noise, identical generator to the probe_real_material ladder.
fn pink(amp: f32, seed_k: u64) -> Vec<f32> {
    let mut s = 0x9E3779B9u64 + seed_k;
    let mut b0 = 0f32;
    let n = (SR_EMU * 0.8) as usize;
    (0..n)
        .map(|_| {
            s ^= s << 13;
            s ^= s >> 7;
            s ^= s << 17;
            let w = ((s as f64 / u64::MAX as f64) as f32 - 0.5) * 2.0;
            b0 = 0.99 * b0 + 0.05 * w;
            (b0 * 6.0 + w * 0.25) * amp
        })
        .collect()
}

/// Low-crest signal: 220 Hz sine.
fn sine(amp: f32) -> Vec<f32> {
    let n = (SR_EMU * 0.8) as usize;
    (0..n)
        .map(|i| (2.0 * std::f64::consts::PI * 220.0 * i as f64 / SR_EMU).sin() as f32 * amp)
        .collect()
}

#[derive(Clone, Copy)]
struct Cfg {
    name: &'static str,
    agc: bool,
    agc_cap_db: f32, // INFINITY = uncapped
    sat: bool,
    slam: f32, // post-engine C++ stage
}

fn run_chain(bytes: &[u8], cfg: &Cfg, input: &[f32], morph: f64, q: f64) -> f32 {
    let cart = Cartridge::from_body_bytes("P2k_013_talking_hedz", bytes, 1.0).expect("cart");
    let mut eng = FilterEngine::new();
    eng.prepare(SR_EMU);
    eng.load_cartridge(cart);
    eng.debug.agc_enabled = cfg.agc;
    eng.debug.agc_max_cut_db = cfg.agc_cap_db;
    eng.debug.saturation_enabled = cfg.sat;
    eng.set_agc_drive(1.0); // plugin value (hardware-faithful identity pre-scale)
    eng.set_input_mode(InputMode::None);
    eng.set_slam_drive(0.0); // no-op in None mode anyway; plugin sends 0 to the engine

    let mut wet: Vec<f32> = Vec::with_capacity(input.len());
    let mut off = 0usize;
    while off < input.len() {
        let len = BLOCK.min(input.len() - off);
        let mut l = input[off..off + len].to_vec();
        let mut r = l.clone();
        eng.process_block(&mut l, &mut r, morph, q);
        slam_output_pressure(&mut l, &mut r, cfg.slam);
        wet.extend_from_slice(&l);
        off += len;
    }
    20.0 * (rms(&wet) / rms(input).max(1e-9)).log10()
}

#[test]
#[ignore = "attribution matrix for the shipping-plugin dynamics leveler"]
fn probe_plugin_leveler() {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let dir = root.join("ref/p2k_variants/P2k_013_talking_hedz");
    let body_path = std::fs::read_dir(&dir)
        .expect("variants dir")
        .flatten()
        .map(|e| e.path())
        .find(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.starts_with("variant_0_") && n.ends_with(".bin"))
                .unwrap_or(false)
        })
        .expect("talking hedz body");
    let bytes = std::fs::read(&body_path).expect("read body");

    const INF: f32 = f32::INFINITY;
    let cfgs: &[Cfg] = &[
        // full shipping chain
        Cfg { name: "SHIP (agc+sat+slam.25)", agc: true, agc_cap_db: INF, sat: true, slam: 0.25 },
        // engine-only (what probe_real_material actually measured)
        Cfg { name: "engine (agc+sat)", agc: true, agc_cap_db: INF, sat: true, slam: 0.0 },
        // solo stages
        Cfg { name: "AGC only", agc: true, agc_cap_db: INF, sat: false, slam: 0.0 },
        Cfg { name: "SAT only", agc: false, agc_cap_db: INF, sat: true, slam: 0.0 },
        Cfg { name: "SLAM.25 only", agc: false, agc_cap_db: INF, sat: false, slam: 0.25 },
        // leave-one-out from full chain
        Cfg { name: "SHIP - agc", agc: false, agc_cap_db: INF, sat: true, slam: 0.25 },
        Cfg { name: "SHIP - sat", agc: true, agc_cap_db: INF, sat: false, slam: 0.25 },
        Cfg { name: "SHIP - slam", agc: true, agc_cap_db: INF, sat: true, slam: 0.0 },
        // the COMBINED toggle the old ladder claimed to test
        Cfg { name: "cap8 + nosat + slam0", agc: true, agc_cap_db: 8.0, sat: false, slam: 0.0 },
        Cfg { name: "cap8 + sat + slam.25", agc: true, agc_cap_db: 8.0, sat: true, slam: 0.25 },
        // everything off = linearity check (span must be ~0)
        Cfg { name: "ALL OFF (linear?)", agc: false, agc_cap_db: INF, sat: false, slam: 0.0 },
    ];

    for &(morph, q) in &[(0.5f64, 0.5f64), (0.85, 0.3)] {
        for &sig in &["pink", "sine"] {
            println!("\n=== (morph,q)=({morph},{q})  signal={sig} ===");
            println!("{:>24}  in-24  in-12   in-0  | span dB", "config");
            for cfg in cfgs {
                let mut gains = Vec::new();
                for (k, in_db) in [-24.0f32, -12.0, 0.0].iter().enumerate() {
                    let amp = 10f32.powf(in_db / 20.0) * 0.7;
                    let input = if sig == "pink" { pink(amp, k as u64) } else { sine(amp) };
                    gains.push(run_chain(&bytes, cfg, &input, morph, q));
                }
                let span = (gains[0] - gains[2]).abs();
                println!(
                    "{:>24}: {:+6.1} {:+6.1} {:+6.1} | {:5.1}",
                    cfg.name, gains[0], gains[1], gains[2], span
                );
            }
        }
    }
}
