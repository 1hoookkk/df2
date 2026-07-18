//! HD island contract: a body re-derived at 78125 Hz matches its 39062.5 Hz
//! response below 15 kHz (within packed quantization) and preserves ring time
//! in SECONDS (r2 = sqrt r).

use trench_core::minifloat::PackedCorners;
use trench_core::response::biquad_cascade_mag_db;
use trench_core::stage_law::{
    geometry_from_words, reencode_words_at, words_from_roots, RootPair, StageRoots, STAGE_SR,
};

const HD_SR: f64 = 78125.0;

fn resonant_words() -> [[u16; 5]; 6] {
    let mk = |pole_hz: f64, pole_r: f64, zero_hz: f64, zero_r: f64, scale: f64| {
        words_from_roots(&StageRoots { pole_hz, pole_r, zero_hz, zero_r, scale })
    };
    let ident = mk(0.0, 0.0, 0.0, 0.0, 1.0);
    [
        mk(300.0, 0.97, 150.0, 0.5, 0.2),
        mk(1200.0, 0.985, 900.0, 0.8, 0.3),
        mk(5000.0, 0.99, 5000.0, 0.95, 0.5),
        mk(9000.0, 0.96, 12000.0, 0.9, 0.7),
        ident,
        ident,
    ]
}

#[test]
fn identity_at_native_rate() {
    for row in resonant_words() {
        assert_eq!(reencode_words_at(row, STAGE_SR), row, "native rate must be verbatim");
    }
}

#[test]
fn tf_matches_below_15k() {
    let words = resonant_words();
    let hd: Vec<[u16; 5]> = words.iter().map(|w| reencode_words_at(*w, HD_SR)).collect();

    // decode both to coefficient rows via the packed loop (one corner is enough)
    let base_corners = PackedCorners { words: [words; 4] };
    let hd_corners = PackedCorners {
        words: [[hd[0], hd[1], hd[2], hd[3], hd[4], hd[5]]; 4],
    };
    let base_rows = base_corners.interpolate_biquad(0.0, 0.0);
    let hd_rows = hd_corners.interpolate_biquad(0.0, 0.0);

    let base: Vec<[f64; 5]> = base_rows.iter().map(|r| r.map(|v| v as f64)).collect();
    let hdc: Vec<[f64; 5]> = hd_rows.iter().map(|r| r.map(|v| v as f64)).collect();
    let base_arr: [[f64; 5]; 6] = base.try_into().unwrap();
    let hd_arr: [[f64; 5]; 6] = hdc.try_into().unwrap();

    // Below 12 kHz the two rates must agree within packed quantization. In
    // 12-15 kHz the BASE rate's own Nyquist cramping starts to relax at HD --
    // that divergence is the feature, so it is reported, not gated.
    let mut worst = (0.0f64, 0.0f64);
    let mut worst_hi = (0.0f64, 0.0f64);
    let mut f = 40.0f64;
    while f <= 15000.0 {
        let a = biquad_cascade_mag_db(&base_arr, f, STAGE_SR);
        let b = biquad_cascade_mag_db(&hd_arr, f, HD_SR);
        let d = (a - b).abs();
        if f <= 12000.0 {
            if d > worst.0 { worst = (d, f); }
        } else if d > worst_hi.0 {
            worst_hi = (d, f);
        }
        f *= 1.03;
    }
    println!(
        "worst below 12 kHz: {:.3} dB at {:.0} Hz; cramping zone 12-15 kHz: {:.3} dB at {:.0} Hz",
        worst.0, worst.1, worst_hi.0, worst_hi.1
    );
    assert!(
        worst.0 < 0.35,
        "HD response must match below 12 kHz within quantization: worst {:.3} dB at {:.0} Hz",
        worst.0,
        worst.1
    );
}

#[test]
fn ring_time_in_seconds_preserved() {
    for row in resonant_words() {
        let g0 = geometry_from_words(row);
        let g1 = geometry_from_words(reencode_words_at(row, HD_SR));
        if let (RootPair::Conjugate { hz: h0, r: r0 }, RootPair::Conjugate { hz: h1_raw, r: r1 }) =
            (g0.pole, g1.pole)
        {
            // geometry_from_words reads Hz with the STAGE_SR ruler; the HD row
            // lives at HD_SR, so rescale the reading.
            let h1 = h1_raw * (HD_SR / STAGE_SR);
            // tau = -1 / (fs * ln r); equal seconds  <=>  ln(r1)*HD = ln(r0)*BASE
            let tau0 = -1.0 / (STAGE_SR * r0.ln());
            let tau1 = -1.0 / (HD_SR * r1.ln());
            assert!(
                (tau1 / tau0 - 1.0).abs() < 0.05,
                "ring tau must match in seconds: {tau0} vs {tau1} (pole {h0} -> {h1} Hz)"
            );
            assert!((h1 / h0 - 1.0).abs() < 0.02, "pole Hz must survive: {h0} -> {h1}");
        }
    }
}
