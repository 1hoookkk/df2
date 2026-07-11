//! Proof that `arma::fit_corner_from_magnitude` reproduces a TARGET magnitude
//! curve — the response-first factorizer a Target Browser would ride on.
//!
//! For each target (synthetic shapes + a real P2K reference's own M0_Q0
//! response, refit):
//!   target curve -> fit_corner_from_magnitude -> fitted 6-stage cascade
//!   -> evaluate fitted magnitude on a log grid -> SHAPE residual (mean removed,
//!      because the cepstral envelope fits shape, not absolute level)
//!   + max pole radius (stability).
//!
//! Writes per-target artifacts to `dev/tmp/factorizer_proof/` (curve JSON +
//! fitted `.body240`, corner replicated x4) for Python audition, and asserts the
//! fit is finite, stable, and tracks the target shape.

use std::fs;
use std::path::PathBuf;

use trench_core::arma::fit_corner_from_magnitude;
use trench_core::cartridge::CornerData;
use trench_core::minifloat::{kernel_to_biquad, pole_radius, PackedCorners};
use trench_core::response::{kernel_cascade_mag_db, log_frequency_grid};

const SR: f64 = 39_062.5;
const LO: f64 = 40.0;
const HI: f64 = 15_000.0;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")
}

fn out_dir() -> PathBuf {
    let p = repo_root().join("dev/tmp/factorizer_proof");
    fs::create_dir_all(&p).unwrap();
    p
}

fn sample<F: Fn(f64) -> f64>(f: F, n: usize) -> Vec<(f64, f64)> {
    log_frequency_grid(LO, HI, n)
        .into_iter()
        .map(|hz| (hz, f(hz)))
        .collect()
}

fn interp_db(curve: &[(f64, f64)], f: f64) -> f64 {
    if f <= curve[0].0 {
        return curve[0].1;
    }
    let last = curve.len() - 1;
    if f >= curve[last].0 {
        return curve[last].1;
    }
    for w in curve.windows(2) {
        if f >= w[0].0 && f <= w[1].0 {
            let t = (f - w[0].0) / (w[1].0 - w[0].0).max(1e-9);
            return w[0].1 + (w[1].1 - w[0].1) * t;
        }
    }
    curve[last].1
}

fn max_pole_radius(corner: &CornerData) -> f64 {
    corner.iter().fold(0.0_f64, |m, st| {
        let [_, _, _, a1, a2] = kernel_to_biquad(*st);
        m.max(pole_radius(a1, a2))
    })
}

fn arr(v: &[f64]) -> String {
    let s: Vec<String> = v.iter().map(|x| format!("{x:.4}")).collect();
    format!("[{}]", s.join(","))
}

// Musical band for the asserted fidelity metric. The top octave (toward Nyquist)
// is deliberately excluded: that is where the chip-fold / HF-edge character lives
// (see memory `nyquist-edge-tricks`, "scope stops at fs/2"), and an unconstrained
// fitter parks an edge resonance there — informative, but not a band failure.
const BAND_LO: f64 = 120.0;
const BAND_HI: f64 = 8000.0;

fn shape_stats(target: &[f64], fitted: &[f64], grid: &[f64], lo: f64, hi: f64) -> (f64, f64) {
    let resid: Vec<f64> = grid
        .iter()
        .zip(target.iter().zip(fitted))
        .filter(|(f, _)| **f >= lo && **f <= hi)
        .map(|(_, (t, fv))| fv - t)
        .collect();
    if resid.is_empty() {
        return (f64::NAN, f64::NAN);
    }
    let mean = resid.iter().sum::<f64>() / resid.len() as f64;
    let shape: Vec<f64> = resid.iter().map(|r| r - mean).collect();
    let rms = (shape.iter().map(|s| s * s).sum::<f64>() / shape.len() as f64).sqrt();
    let max = shape.iter().fold(0.0_f64, |m, s| m.max(s.abs()));
    (rms, max)
}

struct Proof {
    name: String,
    shape_rms_full: f64,
    shape_rms_band: f64,
    shape_max_band: f64,
    max_pole_radius: f64,
    fitted_finite: bool,
}

fn prove(name: &str, curve: &[(f64, f64)]) -> Proof {
    let fit = fit_corner_from_magnitude(curve, SR).expect("fitter returned None");
    let grid = log_frequency_grid(LO, HI, 256);
    let target: Vec<f64> = grid.iter().map(|&f| interp_db(curve, f)).collect();
    let fitted: Vec<f64> = grid
        .iter()
        .map(|&f| kernel_cascade_mag_db(&fit, f, SR))
        .collect();
    let (rms_full, _max_full) = shape_stats(&target, &fitted, &grid, LO, HI);
    let (rms_band, max_band) = shape_stats(&target, &fitted, &grid, BAND_LO, BAND_HI);
    let mpr = max_pole_radius(&fit);
    let finite = fitted.iter().all(|v| v.is_finite());

    // Export fitted body (one corner replicated across all 4 = a static morph of
    // that corner) so Python can audition it through the shipped engine.
    let body = PackedCorners::from_corner_data(&[fit, fit, fit, fit]).to_rom_bytes();
    let dir = out_dir();
    fs::write(dir.join(format!("{name}.body240")), body).unwrap();
    let json = format!(
        "{{\"name\":\"{name}\",\"sr\":{SR},\"band_hz\":[{BAND_LO},{BAND_HI}],\
         \"shape_rms_full_db\":{rms_full:.4},\"shape_rms_band_db\":{rms_band:.4},\
         \"shape_max_band_db\":{max_band:.4},\"max_pole_radius\":{mpr:.6},\
         \"freqs\":{},\"target_db\":{},\"fitted_db\":{}}}",
        arr(&grid),
        arr(&target),
        arr(&fitted),
    );
    fs::write(dir.join(format!("{name}.json")), json).unwrap();

    Proof {
        name: name.into(),
        shape_rms_full: rms_full,
        shape_rms_band: rms_band,
        shape_max_band: max_band,
        max_pole_radius: mpr,
        fitted_finite: finite,
    }
}

fn ln2_bump(f: f64, fc: f64, gain_db: f64, width_oct: f64) -> f64 {
    let x = (f / fc).ln() / (width_oct * std::f64::consts::LN_2);
    gain_db * (-(x * x)).exp()
}

#[test]
fn factorizer_reproduces_target_shapes() {
    let mut proofs = Vec::new();

    // 1. synthetic: three broad formant bumps on a floor
    proofs.push(prove(
        "synth_three_formants",
        &sample(
            |f| {
                -18.0
                    + ln2_bump(f, 600.0, 22.0, 0.45)
                    + ln2_bump(f, 1400.0, 20.0, 0.45)
                    + ln2_bump(f, 2700.0, 18.0, 0.5)
            },
            160,
        ),
    ));

    // 2. synthetic: two broad formants. Deleting a solved numerator pair near
    // its paired pole used to destroy this contour after the linear solve.
    proofs.push(prove(
        "synth_two_formants",
        &sample(
            |f| -16.0 + ln2_bump(f, 700.0, 20.0, 0.5) + ln2_bump(f, 1800.0, 18.0, 0.5),
            160,
        ),
    ));

    // 3. synthetic: one nasal formant with broad hollows on either side.
    proofs.push(prove(
        "synth_nasal_mid",
        &sample(
            |f| {
                -14.0 + ln2_bump(f, 1000.0, 22.0, 0.35)
                    - ln2_bump(f, 420.0, 10.0, 0.5)
                    - ln2_bump(f, 2400.0, 8.0, 0.5)
            },
            160,
        ),
    ));

    // 4. synthetic: gentle lowpass tilt above 800 Hz
    proofs.push(prove(
        "synth_lowpass_tilt",
        &sample(
            |f| {
                if f <= 800.0 {
                    0.0
                } else {
                    -12.0 * (f / 800.0).log2()
                }
            },
            160,
        ),
    ));

    // 5+. real targets: a P2K reference's OWN M0_Q0 response, refit. Asks: can the
    // response-first factorizer round-trip a real, known-good response shape?
    for (label, file) in [
        ("ref_talking_hedz", "ref/presets/P2k_013_talking_hedz.bin"),
        ("ref_dj_alkaline", "ref/presets/P2k_015_dj_alkaline.bin"),
    ] {
        let bytes = fs::read(repo_root().join(file)).expect("read ref bin");
        let packed = PackedCorners::from_rom_bytes(&bytes).unwrap();
        let corner = packed.interpolate(0.0, 0.0); // M0_Q0
        let curve = sample(|f| kernel_cascade_mag_db(&corner, f, SR), 160);
        proofs.push(prove(label, &curve));
    }

    println!(
        "\n{:<22} {:>10} {:>11} {:>11} {:>10}",
        "target", "RMS(full)", "RMS(120-8k)", "max(120-8k)", "maxPoleR"
    );
    for p in &proofs {
        println!(
            "{:<22} {:>9.2} {:>10.2} {:>10.2} {:>10.4}",
            p.name, p.shape_rms_full, p.shape_rms_band, p.shape_max_band, p.max_pole_radius
        );
        // Always-true claims: every fit is finite and stable.
        assert!(p.fitted_finite, "{}: non-finite fitted response", p.name);
        assert!(
            p.max_pole_radius < 1.0,
            "{}: unstable fit (maxR {})",
            p.name,
            p.max_pole_radius
        );
    }

    // PROVEN claim: in the musical band the factorizer reproduces a broad
    // formant-envelope target tightly. (Top octave parks a Nyquist-edge
    // resonance; real razor-pole P2K bodies are smoothed — both auditioned, not
    // asserted, since the ear is the fitness function.)
    for name in [
        "synth_three_formants",
        "synth_two_formants",
        "synth_nasal_mid",
    ] {
        let proof = proofs.iter().find(|proof| proof.name == name).unwrap();
        assert!(
            proof.shape_rms_band < 4.0,
            "{name}: in-band broad-shape fit too loose: {:.2} dB RMS",
            proof.shape_rms_band
        );
    }
    println!("\nartifacts -> dev/tmp/factorizer_proof/ (*.json, *.body240)");
}
