//! End-to-end data-path check for the Forge: a captured sound → LPC fit → the
//! compiled-v1 cartridge the Forge writes → re-loaded by the runtime. Proves
//! capture → fit → cartridge → player round-trips and interpolates finite.

use trench_core::{lpc, Cartridge};

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

// Replicate the Forge's export_cartridge: 4 corners × 12 stages (6 fit + 6 passthrough).
fn forge_cartridge(corner: &[[f64; 5]; 6]) -> String {
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
        kfs.push(serde_json::json!({"label":lbl,"boost":1.0,"stages":stages}));
    }
    serde_json::json!({"format":"compiled-v1","name":"roundtrip","sampleRate":39062.5,"stages":12,"keyframes":kfs}).to_string()
}

#[test]
fn capture_fit_cartridge_roundtrips() {
    // synth a two-formant resonant sound (the kind the fitter is built for)
    let sr = 16000.0;
    let n = 24000;
    let mut seed = 0xABCD_1234u64;
    let mut noise = vec![0.0f64; n];
    for v in noise.iter_mut() {
        seed = seed
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        *v = ((seed >> 33) as f64 / (1u64 << 31) as f64) - 1.0;
    }
    let stage1 = resonator(&noise, 650.0, 0.97, sr);
    let x = resonator(&stage1, 1700.0, 0.96, sr);

    // capture → fit
    let corner = lpc::fit_corner(&x, sr, 39062.5);

    // fit → cartridge JSON (Forge format) → runtime load
    let json = forge_cartridge(&corner);
    let cart = Cartridge::from_json(&json).expect("Forge cartridge should parse in the runtime");

    // interpolation must be finite across the whole morph/cavity surface
    for (m, q) in [
        (0.0, 0.0),
        (1.0, 0.0),
        (0.0, 1.0),
        (1.0, 1.0),
        (0.5, 0.5),
        (0.3, 0.7),
    ] {
        let c = cart.interpolate(m, q);
        for stage in &c {
            for v in stage {
                assert!(v.is_finite(), "non-finite coeff at morph={m} q={q}");
            }
            // stability: pole radius^2 = 1 - c3 must stay < 1
            assert!(1.0 - stage[3] < 1.0, "unstable pole at morph={m} q={q}");
        }
    }
}
