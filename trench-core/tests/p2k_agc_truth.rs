//! Settle the AGC-drive value against the REAL P2K filters + the EmulatorX
//! ground truth (ref/ghidra_extracts/runtime_hacks.md: "the agc_drive pre-scale
//! is an authoring/audition control; it is NOT part of the observed DLL path").
//!
//! The DLL feeds the raw cascade straight into the 16-value table => faithful
//! agc_drive = 1.0. This probe shows what the real ROM bodies actually do at the
//! faithful 1.0 vs the non-hardware 4.0, so the choice is evidence-based.
//!
//! Run: cargo test -p trench-core --test p2k_agc_truth -- --ignored --nocapture

use trench_core::{Cartridge, FilterEngine, InputMode};

const BODIES: &[&str] = &[
    "P2k_013_talking_hedz", // default body (vowel/formant)
    "P2k_003_millennium",
    "P2k_031_ear_bender",
    "P2k_029_lucifer_s_q", // screamer
];

// HOME · MORPH · TENSION · MORPH+TENSION · MIDDLE
const POS: &[(f64, f64)] = &[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.5, 0.5)];

fn rms_peak(buf: &[f32]) -> (f32, f32) {
    if buf.is_empty() {
        return (0.0, 0.0);
    }
    let mut s = 0.0f64;
    let mut p = 0.0f32;
    for &x in buf {
        s += (x as f64) * (x as f64);
        p = p.max(x.abs());
    }
    ((s / buf.len() as f64).sqrt() as f32, p)
}

fn body_path(name: &str) -> std::path::PathBuf {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let dir = root.join("ref/p2k_variants").join(name);
    std::fs::read_dir(&dir)
        .expect("dir")
        .flatten()
        .map(|e| e.path())
        .find(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.starts_with("variant_0_") && n.ends_with(".bin"))
                .unwrap_or(false)
        })
        .expect("variant_0")
}

fn render(bytes: &[u8], morph: f64, q: f64, agc: Option<f32>, slam: f32) -> (f32, f32) {
    let sr = 39_062.5f64;
    let block = 256usize;
    let n = (sr * 1.0) as usize;
    let cart = Cartridge::from_body_bytes("p", bytes, 1.0).expect("load");
    let mut eng = FilterEngine::new();
    eng.prepare(sr);
    eng.load_cartridge(cart);
    match agc {
        Some(d) => {
            eng.debug.agc_enabled = true;
            eng.set_agc_drive(d);
        }
        None => {
            eng.debug.agc_enabled = false; // raw cascade (no leveling)
        }
    }
    eng.set_input_mode(InputMode::MackieDeskSlam);
    eng.set_slam_drive(slam);

    let mut phase = 0.0f64;
    let mut wet = Vec::with_capacity(n);
    let mut off = 0usize;
    while off < n {
        let len = block.min(n - off);
        let mut l: Vec<f32> = (0..len)
            .map(|_| {
                phase = (phase + 55.0 / sr).fract();
                ((phase * 2.0 - 1.0) as f32) * 0.5
            })
            .collect();
        let mut r = l.clone();
        eng.process_block(&mut l, &mut r, morph, q);
        wet.extend_from_slice(&l);
        off += len;
    }
    rms_peak(&wet)
}

#[test]
#[ignore = "diagnostic: real P2K filters under faithful AGC=1.0 vs non-hardware 4.0"]
fn p2k_agc_truth() {
    println!("\nINPUT = 55Hz saw @0.5 (rms 0.289). EmulatorX DLL has NO agc pre-scale => faithful agc=1.0.\n");
    for name in BODIES {
        let bytes = std::fs::read(body_path(name)).expect("read");
        println!("== {name} ==");
        println!("  pos(M,Q)   rawRMS rawPk |  agc1/slam0  agc1/slam.5 |  agc4/slam.5");
        for &(m, q) in POS {
            let (raw_r, raw_p) = render(&bytes, m, q, None, 0.0);
            let (a1s0_r, _) = render(&bytes, m, q, Some(1.0), 0.0);
            let (a1s5_r, a1s5_p) = render(&bytes, m, q, Some(1.0), 0.5);
            let (a4s5_r, _) = render(&bytes, m, q, Some(4.0), 0.5);
            println!(
                "  ({m:.0},{q:.0})      {raw_r:.3}  {raw_p:.2} |   {a1s0_r:.3}       {a1s5_r:.3}({a1s5_p:.2}) |   {a4s5_r:.3}"
            );
        }
        println!();
    }
}
