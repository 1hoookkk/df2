use trench_core::trench_matrix::TrenchMatrix;

#[test]
fn space_zero_is_passthrough() {
    let mut m = TrenchMatrix::new(48000.0);
    m.space = 0.0;
    m.mu = 99.0; // would blow up if applied
    let mut l = vec![0.1, -0.2, 0.3, -0.4];
    let mut r = vec![0.5, 0.6, -0.7, 0.8];
    let l_in = l.clone();
    let r_in = r.clone();
    m.process_stereo(&mut l, &mut r);
    assert_eq!(l, l_in);
    assert_eq!(r, r_in);
}

#[test]
fn mid_is_undisturbed() {
    // M/S architecture only touches the side. L_out + R_out = L_in + R_in
    // must hold for any (mu, space, delay, allpass_g).
    let mut m = TrenchMatrix::new(48000.0);
    m.space = 1.0;
    m.mu = -3.0;
    m.target_delay_samples = 17;
    m.allpass_delay_samples = 11;
    m.allpass_g = 0.7;
    let mut l: Vec<f32> = (0..512).map(|i| (i as f32 * 0.013).sin() * 0.4).collect();
    let mut r: Vec<f32> = (0..512).map(|i| (i as f32 * 0.019).cos() * 0.3).collect();
    let sum_in: Vec<f32> = l.iter().zip(r.iter()).map(|(a, b)| a + b).collect();
    m.process_stereo(&mut l, &mut r);
    for i in 0..l.len() {
        let sum_out = l[i] + r[i];
        assert!(
            (sum_out - sum_in[i]).abs() < 1e-5,
            "mid drifted at i={i}: in={} out={}",
            sum_in[i],
            sum_out,
        );
    }
}

#[test]
fn mu_zero_collapses_to_mono() {
    // effective_mu = 1 + space*(mu - 1). At space=1, mu=0 → effective_mu=0,
    // side is killed → both channels equal mid.
    let mut m = TrenchMatrix::new(48000.0);
    m.space = 1.0;
    m.mu = 0.0;
    let mut l = vec![0.1, -0.2, 0.3, -0.4, 0.5];
    let mut r = vec![0.5, 0.6, -0.7, 0.8, -0.9];
    let mids: Vec<f32> = l.iter().zip(r.iter()).map(|(a, b)| 0.5 * (a + b)).collect();
    m.process_stereo(&mut l, &mut r);
    for i in 0..l.len() {
        assert!((l[i] - mids[i]).abs() < 1e-6, "L[{i}] != mid");
        assert!((r[i] - mids[i]).abs() < 1e-6, "R[{i}] != mid");
    }
}

#[test]
fn extreme_mu_stays_finite() {
    let mut m = TrenchMatrix::new(48000.0);
    m.space = 1.0;
    m.mu = -8.0;
    m.target_delay_samples = 32;
    m.allpass_delay_samples = 13;
    m.allpass_g = 0.95;
    let mut l = vec![0.5_f32; 4096];
    let mut r = vec![-0.5_f32; 4096];
    m.process_stereo(&mut l, &mut r);
    assert!(
        l.iter().all(|s| s.is_finite()),
        "L produced non-finite samples"
    );
    assert!(
        r.iter().all(|s| s.is_finite()),
        "R produced non-finite samples"
    );
}
