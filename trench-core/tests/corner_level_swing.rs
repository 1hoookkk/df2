//! Measure the real per-corner OUTPUT LEVEL swing across the 4 ROM bodies, on
//! pink noise, through the faithful chain (agc=1.0, slam=0). This sizes the
//! per-corner makeup needed to honour the product contract ("gain-managed across
//! corners") without touching the hardware-faithful coefficients.
//!
//! Run: cargo test -p trench-core --test corner_level_swing -- --ignored --nocapture

use trench_core::{Cartridge, FilterEngine, InputMode};

const BODIES: &[&str] = &[
    "P2k_013_talking_hedz",
    "P2k_003_millennium",
    "P2k_031_ear_bender",
    "P2k_029_lucifer_s_q",
];

// The 4 packed corners + center.
const CORNERS: &[(&str, f64, f64)] = &[
    ("M0/Q0  ", 0.0, 0.0),
    ("M100/Q0", 1.0, 0.0),
    ("M0/Q100", 0.0, 1.0),
    ("M1/Q1  ", 1.0, 1.0),
    ("CENTER ", 0.5, 0.5),
];

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

// Paul Kellet pink-noise filter on a deterministic white LCG, scaled to rms ~0.25.
struct Pink {
    rng: u32,
    b0: f32,
    b1: f32,
    b2: f32,
}
impl Pink {
    fn new(seed: u32) -> Self {
        Self { rng: seed, b0: 0.0, b1: 0.0, b2: 0.0 }
    }
    fn next(&mut self) -> f32 {
        self.rng = self.rng.wrapping_mul(1664525).wrapping_add(1013904223);
        let white = ((self.rng >> 8) as f32 / (1u32 << 24) as f32) * 2.0 - 1.0;
        self.b0 = 0.99765 * self.b0 + white * 0.0990460;
        self.b1 = 0.96300 * self.b1 + white * 0.2965164;
        self.b2 = 0.57000 * self.b2 + white * 1.0526913;
        (self.b0 + self.b1 + self.b2 + white * 0.1848) * 0.25
    }
}

fn rms(buf: &[f32]) -> f32 {
    if buf.is_empty() {
        return 0.0;
    }
    let s: f64 = buf.iter().map(|&x| (x as f64) * (x as f64)).sum();
    (s / buf.len() as f64).sqrt() as f32
}

fn corner_rms(bytes: &[u8], morph: f64, q: f64, in_pink: &[f32]) -> f32 {
    let sr = 39_062.5f64;
    let cart = Cartridge::from_body_bytes("p", bytes, 1.0).expect("load");
    let mut eng = FilterEngine::new();
    eng.prepare(sr);
    eng.load_cartridge(cart);
    eng.debug.agc_enabled = true;
    eng.set_agc_drive(1.0); // faithful
    eng.set_input_mode(InputMode::MackieDeskSlam);
    eng.set_slam_drive(0.0); // clean
    let mut out = Vec::with_capacity(in_pink.len());
    let block = 256usize;
    let mut off = 0usize;
    while off < in_pink.len() {
        let len = block.min(in_pink.len() - off);
        let mut l = in_pink[off..off + len].to_vec();
        let mut r = l.clone();
        eng.process_block(&mut l, &mut r, morph, q);
        out.extend_from_slice(&l);
        off += len;
    }
    // skip the first 2000 samples (filter settling) for a clean steady-state rms
    rms(&out[2000.min(out.len())..])
}

#[test]
#[ignore = "diagnostic: per-corner output level swing on pink noise"]
fn corner_level_swing() {
    let sr = 39_062.5f64;
    let n = (sr * 2.0) as usize;
    let mut pink = Pink::new(0x1234_5678);
    let input: Vec<f32> = (0..n).map(|_| pink.next()).collect();
    let in_rms = rms(&input);
    println!("\nPink input rms = {in_rms:.4}. Chain = faithful (agc 1.0, slam 0). Output dB vs input:\n");

    for name in BODIES {
        let bytes = std::fs::read(body_path(name)).expect("read");
        let mut dbs = Vec::new();
        print!("{name:24}");
        for (_lbl, m, q) in CORNERS {
            let r = corner_rms(&bytes, *m, *q, &input);
            let db = 20.0 * (r / in_rms).max(1e-6).log10();
            dbs.push(db);
            print!(" {db:>6.1}");
        }
        // swing across the 4 packed corners (exclude center)
        let corner_dbs = &dbs[0..4];
        let max = corner_dbs.iter().cloned().fold(f32::MIN, f32::max);
        let min = corner_dbs.iter().cloned().fold(f32::MAX, f32::min);
        println!("   | swing {:>4.1} dB", max - min);
    }
    print!("{:24}", "");
    for (lbl, _, _) in CORNERS {
        print!(" {:>6}", lbl.trim());
    }
    println!("\n");
    println!("=> per-corner makeup boost = 10^(-dB/20) brings each corner toward 0 dB (unity vs input).");
}
