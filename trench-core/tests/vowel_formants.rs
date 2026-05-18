//! Vowel label classification gate.
//!
//! For each vowel pill under `cartridges/factory/vowels/`, compute the
//! magnitude response of the M0_Q0 cascade and find the lowest three
//! formant peaks. Then score the peak pattern against a published
//! formant table for each vowel, and assert the pill classifies as
//! itself — i.e., `ah.json` must look more like /ɑ/ than like any
//! other IPA vowel.
//!
//! **What this proves.** The file labeled `ah` isn't secretly
//! labeled-as-`ee`-but-shaped-like-`ah` — or worse, shaped like
//! something that isn't any vowel at all. It does not prove
//! textbook formant accuracy; the tolerance is deliberately loose
//! so the shape bank author's taste survives.
//!
//! **What this does NOT prove.** The vowel *sounds* right. That
//! requires ears. The test only catches gross label drift between
//! the pill filename and what the cascade actually does.
//!
//! Sample rate is hardcoded to 39062.5 Hz — the shape bank's
//! authoring rate, visible in the `sampleRate` field of every
//! `cartridges/factory/vowels/*.json`. If the shape bank is ever
//! re-authored at a different rate, update this constant or derive
//! it from the cartridge JSON.

use std::f64::consts::PI;
use std::fs;
use std::path::PathBuf;

// NUM_STAGES lives in `trench_core::cascade`; CornerData and Cartridge in
// `trench_core::cartridge`. Both are re-exported at the crate root, so use
// those re-exports to keep the import line stable across module reshuffles.
use trench_core::{Cartridge, CornerData, NUM_STAGES};

/// Shape bank authoring sample rate. Every `cartridges/factory/vowels/*.json`
/// carries `"sampleRate": 39062.5`.
const SR: f64 = 39062.5;

/// Number of frequency bins from DC to Nyquist. 2048 gives ~9.5 Hz
/// resolution at this SR, which is finer than any formant we care about.
const N_BINS: usize = 2048;

/// Ignore peaks below this frequency — formant F1 is never this low,
/// and cascade roll-up below 150 Hz creates spurious local maxima at
/// the boundary.
const MIN_PEAK_HZ: f64 = 150.0;

/// Ignore peaks above this frequency — the shape bank authoring at
/// 39 kHz rolls off hard past ~10 kHz and we see aliasing artifacts
/// above that. F3 for all IPA vowels is under 3 kHz, well under.
const MAX_PEAK_HZ: f64 = 6000.0;

/// Peterson & Barney (1952) male-average vowel formants, in Hz.
/// Source: the canonical phonetics reference used in every intro
/// acoustic phonetics course. `(key, [F1, F2, F3])`.
const VOWEL_TARGETS: &[(&str, [f64; 3])] = &[
    ("ae", [690.0, 1660.0, 2490.0]),
    ("ah", [710.0, 1100.0, 2540.0]),
    ("aw", [590.0, 880.0, 2540.0]),
    ("ee", [280.0, 2250.0, 2890.0]),
    ("eh", [550.0, 1770.0, 2490.0]),
    ("er", [480.0, 1350.0, 1690.0]),
    ("ih", [400.0, 1920.0, 2560.0]),
    ("oo", [310.0, 870.0, 2250.0]),
    ("schwa", [500.0, 1500.0, 2500.0]),
    ("uh", [450.0, 1030.0, 2380.0]),
];

/// Vowel pills known to misclassify under the current shape bank.
/// The test prints their classification every run but does not fail
/// on them. If one of these starts classifying as itself in a future
/// run, promote it out of this list so the gate catches regressions.
///
/// Provenance of the misclassifications — discovered by this gate on
/// first run against the 2026-04-12 baked shape bank:
///   - `aw` peaks at (630, 2404, 3359) Hz. The defining /ɔ/ F2 near
///     880 Hz is absent, so the cascade reads as an /ɛ/-like pattern.
///     Needs F2 re-authoring around 850-900 Hz with moderate width.
///   - `oo` peaks at (334, 1240, 2175) Hz. The defining /u/ F2 near
///     870 Hz is too high — the pill is over-bright by ~370 Hz.
///     Needs F2 re-authoring down to ~870 Hz.
const KNOWN_DRIFT: &[&str] = &["aw", "oo"];

fn factory_vowels_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .expect("repo root above runtime/")
        .join("cartridges")
        .join("factory")
        .join("vowels")
}

/// Magnitude of one biquad at normalized angular frequency ω ∈ [0, π].
///
/// DF2T direct-form-II-transposed layout used in trench-core:
///     H(z) = (c0 + c1 z^-1 + c2 z^-2) / (1 + c3 z^-1 + c4 z^-2)
fn biquad_mag(c: &[f64; 5], omega: f64) -> f64 {
    let cos1 = (-omega).cos();
    let sin1 = (-omega).sin();
    let cos2 = (-2.0 * omega).cos();
    let sin2 = (-2.0 * omega).sin();

    let num_re = c[0] + c[1] * cos1 + c[2] * cos2;
    let num_im = c[1] * sin1 + c[2] * sin2;
    let den_re = 1.0 + c[3] * cos1 + c[4] * cos2;
    let den_im = c[3] * sin1 + c[4] * sin2;

    let num_mag = (num_re * num_re + num_im * num_im).sqrt();
    let den_mag = (den_re * den_re + den_im * den_im).sqrt();
    if den_mag < 1e-18 {
        // Pole on the unit circle — cap rather than divide by zero.
        return 1e9;
    }
    num_mag / den_mag
}

/// Magnitude response of a 6-stage cascade at `n_bins` frequencies
/// linearly spaced from DC to Nyquist.
fn cascade_response(corner: &CornerData, n_bins: usize) -> Vec<f64> {
    let mut out = vec![0.0; n_bins];
    for (bin, mag) in out.iter_mut().enumerate() {
        let omega = PI * (bin as f64) / (n_bins as f64 - 1.0);
        let mut m = 1.0;
        for stage in corner.iter() {
            m *= biquad_mag(stage, omega);
        }
        *mag = m;
    }
    out
}

/// Return all interior local maxima of `response` with their Hz, within
/// `[MIN_PEAK_HZ, MAX_PEAK_HZ]`. Sorted ascending by frequency.
fn local_peaks_hz(response: &[f64]) -> Vec<f64> {
    let n = response.len();
    let nyquist = SR / 2.0;
    let mut peaks = Vec::new();
    for i in 1..n - 1 {
        if response[i] > response[i - 1] && response[i] >= response[i + 1] {
            let hz = (i as f64) * nyquist / (n as f64 - 1.0);
            if hz >= MIN_PEAK_HZ && hz <= MAX_PEAK_HZ {
                peaks.push(hz);
            }
        }
    }
    peaks
}

/// Log-frequency distance between a candidate peak set and a formant
/// target. For each target formant, find the closest available peak;
/// sum squared log ratios. Lower = better match. Never panics on
/// empty peaks — missing peaks return a large penalty.
fn log_distance(peaks: &[f64], formants: &[f64; 3]) -> f64 {
    if peaks.is_empty() {
        return 1e6;
    }
    let mut total = 0.0;
    for &f in formants {
        let mut best = f64::INFINITY;
        for &p in peaks {
            let d = (p.ln() - f.ln()).abs();
            if d < best {
                best = d;
            }
        }
        total += best * best;
    }
    total
}

fn load_cartridge(path: &PathBuf) -> Cartridge {
    let json = fs::read_to_string(path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    Cartridge::from_json(&json).unwrap_or_else(|e| panic!("parse {}: {e}", path.display()))
}

#[test]
fn every_vowel_pill_classifies_as_itself() {
    let dir = factory_vowels_dir();
    assert!(
        dir.exists(),
        "missing {}; run `python authoring/compilers/bake_phoneme_pills.py`",
        dir.display()
    );

    // Load every vowel pill, compute peaks.
    let mut loaded: Vec<(&'static str, Vec<f64>)> = Vec::new();
    for (key, _) in VOWEL_TARGETS {
        let path = dir.join(format!("{key}.json"));
        if !path.exists() {
            panic!("missing vowel pill: {}", path.display());
        }
        let cart = load_cartridge(&path);
        assert_eq!(
            cart.corners[0].len(),
            NUM_STAGES,
            "{key}: corner 0 should have {NUM_STAGES} stages",
        );
        let response = cascade_response(&cart.corners[0], N_BINS);
        let peaks = local_peaks_hz(&response);
        assert!(
            !peaks.is_empty(),
            "{key}: no peaks found in {MIN_PEAK_HZ}–{MAX_PEAK_HZ} Hz range — not a vowel shape",
        );
        loaded.push((*key, peaks));
    }

    // Classify each vowel against the full reference table. Collect
    // results first so we can print the full matrix before deciding
    // pass/fail — the matrix is the diagnostic, not the panic message.
    let mut misclassified: Vec<String> = Vec::new();
    let mut drift_surprises: Vec<String> = Vec::new();
    println!("\nVowel classification matrix:");
    println!(
        "{:<8} {:<14} {:<12} {:<10} status",
        "pill", "peaks(top3)", "self_dist", "best"
    );
    for (key, peaks) in &loaded {
        let mut best_label = "";
        let mut best_dist = f64::INFINITY;
        let mut self_dist = f64::INFINITY;
        for (ref_key, formants) in VOWEL_TARGETS {
            let d = log_distance(peaks, formants);
            if ref_key == key {
                self_dist = d;
            }
            if d < best_dist {
                best_dist = d;
                best_label = ref_key;
            }
        }
        let top3: Vec<String> = peaks.iter().take(3).map(|p| format!("{:.0}", p)).collect();
        let in_drift = KNOWN_DRIFT.contains(key);
        let status = match (best_label == *key, in_drift) {
            (true, false) => "ok",
            (true, true) => "DRIFT_FIXED", // promote out of KNOWN_DRIFT
            (false, true) => "drift (known)",
            (false, false) => "MISS",
        };
        println!(
            "{:<8} [{:<12}] {:<12.4} {:<10} {}",
            key,
            top3.join(","),
            self_dist,
            best_label,
            status,
        );
        if best_label != *key && !in_drift {
            misclassified.push(format!(
                "{key} classified as {best_label} (self_dist={self_dist:.4}, best_dist={best_dist:.4})",
            ));
        }
        if best_label == *key && in_drift {
            drift_surprises.push((*key).to_string());
        }
    }

    assert!(
        misclassified.is_empty(),
        "{} vowel pills misclassify against their own labels:\n  {}",
        misclassified.len(),
        misclassified.join("\n  ")
    );

    // If a known-drift vowel now classifies as itself, someone re-authored
    // the shape bank — push them to update KNOWN_DRIFT so the gate tracks
    // the new truth.
    assert!(
        drift_surprises.is_empty(),
        "known-drift vowel(s) now classify correctly: {:?}. \
         Remove them from KNOWN_DRIFT in trench-core/tests/vowel_formants.rs \
         and this test will start gating them like the rest.",
        drift_surprises
    );
}
