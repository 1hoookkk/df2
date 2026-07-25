// AMOUNT law proof: scaling pole/zero radii by k (a1'=k·a1, a2'=k²·a2,
// b0'=b0^k) tapers a resonant stage WITHOUT moving its centre frequency —
// the perceptual "less of the same filter" contract the UI promises.

fn mag_at(stage: &[f64; 5], w: f64) -> f64 {
    // |H(e^jw)| with z^-1 = cos(w) - j sin(w), no complex crate needed.
    let (c1, s1) = (w.cos(), -w.sin());
    let (c2, s2) = ((2.0 * w).cos(), -(2.0 * w).sin());
    let nr = stage[0] + stage[1] * c1 + stage[2] * c2;
    let ni = stage[1] * s1 + stage[2] * s2;
    let dr = 1.0 + stage[3] * c1 + stage[4] * c2;
    let di = stage[3] * s1 + stage[4] * s2;
    ((nr * nr + ni * ni) / (dr * dr + di * di)).sqrt()
}

fn peak_bin(stage: &[f64; 5], n: usize) -> (usize, f64) {
    let mut best = (0usize, 0.0f64);
    for i in 1..n {
        let w = std::f64::consts::PI * (i as f64) / (n as f64);
        let m = mag_at(stage, w);
        if m > best.1 {
            best = (i, m);
        }
    }
    best
}

fn amount_blend(stage: &[f64; 5], k: f64) -> [f64; 5] {
    let b0 = stage[0];
    let b0k = if b0 > 0.0 { b0.powf(k) } else { k * b0 + (1.0 - k) };
    let ratio = if b0.abs() > 1.0e-12 { b0k / b0 } else { 0.0 };
    [
        b0k,
        stage[1] * k * ratio,
        stage[2] * k * k * ratio,
        stage[3] * k,
        stage[4] * k * k,
    ]
}

#[test]
fn amount_keeps_centre_frequency_and_tapers() {
    // Resonant pole pair: theta = 0.3*pi, r = 0.96, unity zeros, gain 2.
    let (theta, r) = (0.3 * std::f64::consts::PI, 0.96f64);
    let full = [2.0, 0.0, 0.0, -2.0 * r * theta.cos(), r * r];

    let n = 8192;
    let (_, mag_full) = peak_bin(&full, n);

    let pole_angle = |st: &[f64; 5]| (-st[3] / (2.0 * st[4].sqrt())).acos();

    let mut prev_mag = mag_full;
    for &k in &[0.75, 0.5, 0.25] {
        let blended = amount_blend(&full, k);
        // The pole ANGLE (the authored centre frequency) is preserved exactly.
        let drift = (pole_angle(&blended) - theta).abs();
        assert!(drift < 1.0e-9, "k={k}: pole angle drifted {drift} rad");
        // Resonance tapers monotonically.
        let (_, mag_k) = peak_bin(&blended, n);
        assert!(mag_k < prev_mag, "k={k}: magnitude did not taper");
        prev_mag = mag_k;
    }

    // k=0 is the exact identity biquad.
    let idn = amount_blend(&full, 0.0);
    assert_eq!(idn, [1.0, 0.0, 0.0, 0.0, 0.0]);

    // Sanity: the old raw-coefficient lerp DID move the pole angle
    // (documents why it was replaced).
    let old = [
        0.5 * full[0] + 0.5,
        0.5 * full[1],
        0.5 * full[2],
        0.5 * full[3],
        0.5 * full[4],
    ];
    let old_drift = (pole_angle(&old) - theta).abs();
    assert!(
        old_drift > 0.05,
        "expected the old lerp to detune (it moved {old_drift} rad)"
    );
}
