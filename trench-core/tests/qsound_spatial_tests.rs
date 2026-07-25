//! Behavioural tests for `trench_core::qsound_spatial`.
//!
//! We probe structural invariants (bypass, symmetry, sign conventions,
//! stability) rather than matching a proprietary coefficient table.
//!
//! Capture provenance (2026-07-02): the ITD/ILD law coefficients in
//! `canonical_profile` below are the values re-fit from a CLEAN 31-point
//! pan-grid capture of the vendor `QMixer.dll` rendered offline by
//! `Qcreator.exe`; the process was verified LINEAR. ITD law units are microseconds; the ILD
//! law is dB; both use six azimuth harmonics `[sin(az)..sin(6az)]`. The
//! `band_coeffs` here remain a constructed L/R-symmetric fixture (the real
//! per-ear band law is L/R-independent and lives in the fit report) so the
//! strict channel-mirror invariant stays exact.

use trench_core::cartridge::{BandChannelCoeffs, BandCoeffs, SpatialProfile};
use trench_core::qsound_spatial::QSoundSpatial;

const SR: f32 = 48_000.0;

/// Measurement-fit test profile. Trailing elevation cross-terms round to zero.
fn canonical_profile(az_rad: f32, distance_m: f32, el_rad: f32) -> SpatialProfile {
    SpatialProfile {
        azimuth: az_rad,
        distance: distance_m,
        elevation: el_rad,
        // Fitted from the clean pan-grid re-capture (microseconds; six
        // azimuth harmonics).
        itd_coeffs: [
            -714.271_2,
            1275.442_3,
            -1301.714_0,
            891.666_7,
            -462.902_1,
            149.969_9,
        ],
        // Fitted ILD law (dB; six azimuth harmonics), MAE 0.78 dB vs measured.
        ild_coeffs: [
            -712.840_3, 1080.508_8, -965.443_6, 597.945_7, -249.361_1, 53.300_0,
        ],
        band_coeffs: BandCoeffs {
            l: BandChannelCoeffs {
                low: [
                    -72.211_726,
                    0.386_310,
                    -1.609_965,
                    -2.942_365,
                    4.905_630,
                    0.894_425,
                    -1.686_776,
                    -0.082_666,
                    0.833_466,
                    0.0,
                    0.0,
                    0.0,
                ],
                mid: [
                    -74.892_487,
                    0.460_364,
                    -1.645_200,
                    -2.794_224,
                    9.547_364,
                    1.100_615,
                    -2.989_885,
                    -0.168_168,
                    1.485_241,
                    0.0,
                    0.0,
                    0.0,
                ],
                high: [
                    -73.911_507,
                    0.438_043,
                    -1.634_712,
                    -2.835_356,
                    8.046_734,
                    1.041_892,
                    -2.546_882,
                    -0.132_837,
                    1.302_472,
                    0.0,
                    0.0,
                    0.0,
                ],
            },
            r: BandChannelCoeffs {
                low: [
                    -72.211_726,
                    0.386_310,
                    -1.609_965,
                    2.942_365,
                    4.905_630,
                    -0.894_425,
                    -1.686_776,
                    0.082_666,
                    0.833_466,
                    0.0,
                    0.0,
                    0.0,
                ],
                mid: [
                    -74.892_487,
                    0.460_364,
                    -1.645_200,
                    2.794_224,
                    9.547_364,
                    -1.100_615,
                    -2.989_885,
                    0.168_168,
                    1.485_241,
                    0.0,
                    0.0,
                    0.0,
                ],
                high: [
                    -73.911_507,
                    0.438_043,
                    -1.634_712,
                    2.835_356,
                    8.046_734,
                    -1.041_892,
                    -2.546_882,
                    0.132_837,
                    1.302_472,
                    0.0,
                    0.0,
                    0.0,
                ],
            },
        },
    }
}

#[test]
fn space_zero_is_bit_identical_bypass() {
    // Goldentruth: at SPACE=0 the processor must pass stereo input
    // unchanged. No delay, no gain, no filter — not a near-zero mix but
    // the literal input samples. This is the "no math path" branch.
    let mut stage = QSoundSpatial::new(SR);
    stage.set_profile(&canonical_profile(0.5, 1.0, 0.0));
    stage.set_space(0.0);

    let mut l: Vec<f32> = (0..1024).map(|i| (i as f32 * 0.013).sin()).collect();
    let mut r: Vec<f32> = (0..1024).map(|i| (i as f32 * 0.017).cos()).collect();
    let l_in = l.clone();
    let r_in = r.clone();

    stage.process_stereo(&mut l, &mut r);

    for i in 0..l.len() {
        assert_eq!(l[i], l_in[i], "L sample {i} drifted at SPACE=0");
        assert_eq!(r[i], r_in[i], "R sample {i} drifted at SPACE=0");
    }
}

fn rms(x: &[f32]) -> f32 {
    let s: f32 = x.iter().map(|&v| v * v).sum();
    (s / x.len() as f32).sqrt()
}

/// Deterministic white-ish noise for RMS / correlation probes. xorshift32
/// is enough — we only need a broadband stimulus, not cryptographic quality.
fn noise(n: usize) -> Vec<f32> {
    let mut state: u32 = 0x1234_5678;
    (0..n)
        .map(|_| {
            state ^= state << 13;
            state ^= state >> 17;
            state ^= state << 5;
            (state as i32 as f32) / (i32::MAX as f32)
        })
        .collect()
}

#[test]
fn at_center_pose_processes_signal_but_keeps_l_equal_r() {
    // az=0, el=0, dist=1 is the "no spatialisation" pose: ITD and ILD law
    // evaluate to 0 (sin-features zero), and the band-law sin-features are
    // zero so the shelves applied to L and R are identical. This is a
    // stricter two-part probe: (a) SPACE=1 must route through the full
    // path (output diverges from dry input by any band-shelf delta, no
    // matter how small), AND (b) the two channels must be sample-exact
    // because the centre pose is L/R symmetric by construction.
    let mut stage = QSoundSpatial::new(SR);
    stage.set_profile(&canonical_profile(0.0, 1.0, 0.0));
    stage.set_space(1.0);

    let input = noise(48_000);
    let mut l = input.clone();
    let mut r = input.clone();
    stage.process_stereo(&mut l, &mut r);

    // (a) Confirm the stage actually ran — max |wet - dry| must be > 0 on
    // a broadband stimulus. This rules out the "silently bypasses" bug
    // that made the previous version of this test pass trivially.
    let max_delta = input
        .iter()
        .zip(l.iter())
        .map(|(a, b)| (a - b).abs())
        .fold(0.0_f32, f32::max);
    assert!(
        max_delta > 1e-5,
        "center-pose processing left the signal unchanged (max |wet-dry| = {max_delta:.2e}); expected the band-law shelves to apply",
    );

    // (b) Left / right must be sample-identical at the centre pose.
    for i in 0..l.len() {
        assert_eq!(
            l[i], r[i],
            "L[{i}] != R[{i}] at centre pose: expected sample-exact L/R symmetry",
        );
    }
}

#[test]
fn positive_azimuth_makes_right_channel_louder() {
    // Addendum target: at az=+π/3, R_gain_dB > L_gain_dB (broadband) by
    // at least 2 dB, one-sided. This is the ILD-law sign check — without
    // applying the ILD split the two channels would differ only by the
    // shelf-delta (fraction of a dB) and the test would fail.
    let mut stage = QSoundSpatial::new(SR);
    stage.set_profile(&canonical_profile(std::f32::consts::FRAC_PI_3, 1.0, 0.0));
    stage.set_space(1.0);

    let input = noise(48_000);
    let mut l = input.clone();
    let mut r = input.clone();
    stage.process_stereo(&mut l, &mut r);

    let l_db = 20.0 * rms(&l).log10();
    let r_db = 20.0 * rms(&r).log10();
    let delta = r_db - l_db;
    assert!(
        delta >= 2.0,
        "az=+π/3: expected R >= L by at least 2 dB, got {delta:.3} dB (L={l_db:.2} dB, R={r_db:.2} dB)",
    );
}

/// Index of the largest |sample| in a buffer.
fn argmax_abs(x: &[f32]) -> usize {
    let mut best = 0;
    let mut best_v = 0.0_f32;
    for (i, &v) in x.iter().enumerate() {
        let av = v.abs();
        if av > best_v {
            best_v = av;
            best = i;
        }
    }
    best
}

#[test]
fn positive_azimuth_delays_left_channel_more_than_right() {
    // Addendum target: at az=+π/3, L-ear delay > R-ear delay. Right-ear-
    // lead convention means R arrives first, so on an impulse input the
    // argmax of L must land at a later sample than the argmax of R. Test
    // threshold: lag_l - lag_r >= 1 sample (prevents the "no delay" bug;
    // the parametric model puts the separation at ~5 samples at +60°).
    let mut stage = QSoundSpatial::new(SR);
    stage.set_profile(&canonical_profile(std::f32::consts::FRAC_PI_3, 1.0, 0.0));
    stage.set_space(1.0);

    let mut l = vec![0.0_f32; 256];
    let mut r = vec![0.0_f32; 256];
    l[10] = 1.0;
    r[10] = 1.0;

    stage.process_stereo(&mut l, &mut r);

    let lag_l = argmax_abs(&l) as isize;
    let lag_r = argmax_abs(&r) as isize;
    assert!(
        lag_l - lag_r >= 1,
        "az=+π/3: expected argmax(L) > argmax(R), got lag_l={lag_l}, lag_r={lag_r}",
    );
}

#[test]
fn azimuth_sign_flip_mirrors_channels() {
    // Addendum strict target: L(−az) == R(+az) within 1e-5. All three
    // laws (ITD, ILD, band) are odd functions of sin(az), so swapping
    // az sign must produce a bitwise channel mirror — anything larger
    // than FP round-off signals an implementation asymmetry.
    let az = std::f32::consts::FRAC_PI_3;

    let mut plus = QSoundSpatial::new(SR);
    plus.set_profile(&canonical_profile(az, 1.0, 0.0));
    plus.set_space(1.0);

    let mut minus = QSoundSpatial::new(SR);
    minus.set_profile(&canonical_profile(-az, 1.0, 0.0));
    minus.set_space(1.0);

    let input = noise(8_192);
    let mut l_plus = input.clone();
    let mut r_plus = input.clone();
    plus.process_stereo(&mut l_plus, &mut r_plus);

    let mut l_minus = input.clone();
    let mut r_minus = input.clone();
    minus.process_stereo(&mut l_minus, &mut r_minus);

    let mut max_err = 0.0_f32;
    for i in 0..input.len() {
        let e1 = (l_minus[i] - r_plus[i]).abs();
        let e2 = (r_minus[i] - l_plus[i]).abs();
        max_err = max_err.max(e1).max(e2);
    }
    assert!(
        max_err <= 1.0e-5,
        "azimuth sign flip did not mirror channels: max |L(-az)-R(+az)| = {max_err:.3e}",
    );
}

#[test]
fn full_scale_azimuth_sweep_never_exceeds_unity_peak() {
    // Addendum strict target: "No denormal / clipping on all ±60° sweeps
    // with full-scale input — peak ≤ +0 dBFS". The ILD law puts ~+2 dB of
    // broadband boost on the leading ear at ±60°, which on a ±1 input
    // would push that ear to ~1.26 → clip. The processor must
    // compensate (attenuate the contralateral ear, not boost the
    // ipsilateral one) so peak stays ≤ 1.0 on both channels.
    let fullscale = noise(48_000);
    let fs_peak = fullscale.iter().map(|v| v.abs()).fold(0.0_f32, f32::max);
    assert!(
        (fs_peak - 1.0).abs() < 0.05,
        "test precondition: stimulus peak must be ~1.0, got {fs_peak}",
    );

    // Sweep in 10° steps across ±60°. Fresh stage per pose so delay-line
    // and biquad state from the previous azimuth don't leak into the peak
    // measurement — that's a cartridge-change scenario in the real
    // runtime, where the engine resets cascade state on `loadCartridge`.
    for deg in (-60..=60).step_by(10) {
        let az = (deg as f32).to_radians();
        let mut stage = QSoundSpatial::new(SR);
        stage.set_profile(&canonical_profile(az, 1.0, 0.0));
        stage.set_space(1.0);

        let mut l = fullscale.clone();
        let mut r = fullscale.clone();
        stage.process_stereo(&mut l, &mut r);

        let peak = l
            .iter()
            .chain(r.iter())
            .fold(0.0_f32, |m, &v| m.max(v.abs()));
        assert!(
            peak.is_finite() && peak <= 1.0,
            "az={deg}°: peak output = {peak:.6} > 1.0 (or non-finite)",
        );
    }
}

fn correlation(l: &[f32], r: &[f32]) -> f32 {
    let ll: f32 = l.iter().map(|v| v * v).sum();
    let rr: f32 = r.iter().map(|v| v * v).sum();
    let lr: f32 = l.iter().zip(r.iter()).map(|(a, b)| a * b).sum();
    if ll <= 1e-30 || rr <= 1e-30 {
        return 0.0;
    }
    lr / (ll * rr).sqrt()
}

#[test]
fn space_of_one_reduces_lr_correlation() {
    // Plan target: L/R correlation on a mono source must drop from ~1.0
    // (bypass) to a materially lower value once SPACE=1 routes through
    // the ITD + ILD + shelf path at an off-centre pose. This is the
    // end-to-end "it actually stereoises" check.
    let input = noise(48_000);

    // Reference: stage at SPACE=0 leaves L=R=input → correlation = 1.
    let mut dry = QSoundSpatial::new(SR);
    dry.set_profile(&canonical_profile(std::f32::consts::FRAC_PI_3, 1.0, 0.0));
    dry.set_space(0.0);
    let mut dry_l = input.clone();
    let mut dry_r = input.clone();
    dry.process_stereo(&mut dry_l, &mut dry_r);
    let dry_corr = correlation(&dry_l, &dry_r);

    // Wet: same pose, SPACE=1.
    let mut wet = QSoundSpatial::new(SR);
    wet.set_profile(&canonical_profile(std::f32::consts::FRAC_PI_3, 1.0, 0.0));
    wet.set_space(1.0);
    let mut wet_l = input.clone();
    let mut wet_r = input.clone();
    wet.process_stereo(&mut wet_l, &mut wet_r);
    let wet_corr = correlation(&wet_l, &wet_r);

    assert!(
        (dry_corr - 1.0).abs() < 1e-5,
        "SPACE=0 should leave identical L/R — got correlation {dry_corr:.6}",
    );
    assert!(
        wet_corr < dry_corr - 0.05,
        "SPACE=1 should reduce L/R correlation by > 0.05; got dry={dry_corr:.4}, wet={wet_corr:.4}",
    );
}

#[test]
fn fallback_space_zero_is_bit_identical_bypass() {
    // The runtime 5D/Space toggle uses the profile-less fallback path. At
    // SPACE=0 it must pass stereo input through untouched — the literal input
    // samples — regardless of the fallback pan. Complements the profile-path
    // bypass test above so both code paths are pinned.
    let mut stage = QSoundSpatial::new(SR);
    stage.set_fallback_pan(1.0);
    stage.set_space(0.0);

    let mut l: Vec<f32> = (0..777).map(|i| (i as f32 * 0.011).sin() * 0.8).collect();
    let mut r: Vec<f32> = (0..777).map(|i| (i as f32 * 0.019).cos() * 0.8).collect();
    let l_in = l.clone();
    let r_in = r.clone();

    stage.process_stereo(&mut l, &mut r);

    for i in 0..l.len() {
        assert_eq!(l[i], l_in[i], "fallback L sample {i} drifted at SPACE=0");
        assert_eq!(r[i], r_in[i], "fallback R sample {i} drifted at SPACE=0");
    }
}

#[test]
fn output_is_finite_and_bounded_over_full_space_sweep() {
    // Re-capture lock-in gate: with the fitted profile laws, output must stay
    // finite and peak-bounded (<= 1.0 + small Lagrange/shelf overshoot) across
    // the whole SPACE 0..1 range at an off-centre pose on a full-scale
    // stimulus. This guards against the fitted coefficients (which are large,
    // being the min-norm 6-harmonic solution) producing a level explosion or
    // NaN anywhere on the dry->wet crossfade.
    let input = noise(24_000);
    let fs_peak = input.iter().map(|v| v.abs()).fold(0.0_f32, f32::max);
    assert!((fs_peak - 1.0).abs() < 0.05, "stimulus must be ~full-scale");

    for step in 0..=10 {
        let space = step as f32 / 10.0;
        let mut stage = QSoundSpatial::new(SR);
        stage.set_profile(&canonical_profile(std::f32::consts::FRAC_PI_3, 1.0, 0.0));
        stage.set_space(space);

        let mut l = input.clone();
        let mut r = input.clone();
        stage.process_stereo(&mut l, &mut r);

        let peak = l
            .iter()
            .chain(r.iter())
            .fold(0.0_f32, |m, &v| m.max(v.abs()));
        assert!(
            peak.is_finite(),
            "SPACE={space}: non-finite output (peak={peak})",
        );
        // Crossfade of a bounded dry (<=1) with a peak-guarded wet (<=1) can
        // only stay within a hair of unity; allow the documented Lagrange +
        // shelf-ripple overshoot headroom.
        assert!(
            peak <= 1.10,
            "SPACE={space}: peak {peak:.5} exceeded crossfade bound",
        );
    }
}
