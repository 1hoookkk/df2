//! Diagnostic: dump FilterEngine output at M0_Q0 through Talking Hedz so
//! it can be nulled against the canonical WAV outside the test harness.
//!
//! Run with: cargo test -p trench-core --test hedz_engine_dump -- --ignored --nocapture
//! Writes target/hedz_engine_{corner}.f32 and the exact dry input used.

use std::fs;
use std::path::PathBuf;

use trench_core::{Cartridge, FilterEngine};

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
}

fn read_wav_f32(path: &std::path::Path) -> Option<Vec<f32>> {
    let mut r = hound::WavReader::open(path).ok()?;
    let spec = r.spec();
    if spec.sample_format != hound::SampleFormat::Float || spec.bits_per_sample != 32 {
        return None;
    }
    let ch = spec.channels as usize;
    let samples: Vec<f32> = r
        .samples::<f32>()
        .filter_map(|s| s.ok())
        .step_by(ch)
        .collect();
    Some(samples)
}

fn dump(path: &PathBuf, buf: &[f32]) {
    let mut bytes = Vec::with_capacity(buf.len() * 4);
    for &s in buf {
        bytes.extend_from_slice(&s.to_le_bytes());
    }
    fs::write(path, &bytes).expect("write dump");
}

#[test]
#[ignore]
fn dump_filter_engine_hedz_corners() {
    let hedz_path = repo_root()
        .join("trench-juce")
        .join("cartridges")
        .join("heritage")
        .join("Talking_Hedz.json");
    let json = fs::read_to_string(&hedz_path).expect("read Talking_Hedz.json");
    let cart = Cartridge::from_json(&json).expect("parse Talking_Hedz.json");

    let dry_path = PathBuf::from(r"C:/Users/hooki/trenchwork_clean/ref/bypassed-pinknoise.wav");
    let dry = read_wav_f32(&dry_path).expect("read dry");

    let target = repo_root().join("target");
    fs::create_dir_all(&target).ok();
    dump(&target.join("hedz_engine_dry.f32"), &dry);

    for (label, morph, q) in [("M0_Q0", 0.0f64, 0.0f64), ("M100_Q100", 1.0, 1.0)] {
        let mut engine = FilterEngine::new();
        engine.prepare(44100.0);
        engine.debug.agc_enabled = false;
        engine.debug.dc_block_enabled = false;
        // The legacy `output_gain_clamp_enabled` toggle no longer exists in
        // `DebugToggles`. Closest functional equivalent for "let the cascade
        // through unmolested" is leaving the saturation post-stage on but
        // skipping spatial — `spatial_enabled = false` matches the original
        // intent of keeping the dump faithful to the bare cascade chain.
        engine.debug.spatial_enabled = false;
        engine.load_cartridge(cart.clone());
        let mut left = dry.clone();
        let mut right = dry.clone();
        engine.process_block(&mut left, &mut right, morph, q);
        let p = target.join(format!("hedz_engine_{label}.f32"));
        dump(&p, &left);
        eprintln!("wrote {} ({} samples)", p.display(), left.len());
    }
}
