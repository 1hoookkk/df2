//! Diagnostic (not an assertion gate): synthesize the exact test sounds from
//! tools/make_test_sounds.py and measure how well the Forge fitter's extracted
//! poles cover the REAL formants and how sharp they are, sweeping pre-emphasis.
//! Run: cargo test -p trench-core --test oo_fit_diag -- --nocapture

use trench_core::lpc;

const SR: f64 = 44_100.0;
const RUNTIME_SR: f64 = 39_062.5;

fn resonator(x: &[f64], f: f64, bw: f64) -> Vec<f64> {
    let r = (-std::f64::consts::PI * bw / SR).exp();
    let th = 2.0 * std::f64::consts::PI * f / SR;
    let (a1, a2) = (-2.0 * r * th.cos(), r * r);
    let b0 = 1.0 - r;
    let mut y = vec![0.0; x.len()];
    let (mut y1, mut y2) = (0.0, 0.0);
    for i in 0..x.len() {
        let yi = b0 * x[i] - a1 * y1 - a2 * y2;
        y[i] = yi;
        y2 = y1;
        y1 = yi;
    }
    y
}

fn synth(formants: &[(f64, f64, f64)], dur: f64, f0: f64) -> Vec<f64> {
    let n = (SR * dur) as usize;
    let mut src = vec![0.0; n];
    let step = (SR / f0) as usize;
    let mut i = 0;
    while i < n {
        src[i] = 1.0;
        i += step;
    }
    let mut y = vec![0.0; n];
    for &(f, bw, g) in formants {
        let r = resonator(&src, f, bw);
        for k in 0..n {
            y[k] += g * r[k];
        }
    }
    normalize(&mut y);
    y
}

fn synth_noise(modes: &[(f64, f64, f64)], dur: f64) -> Vec<f64> {
    let n = (SR * dur) as usize;
    let mut seed = 7u64;
    let mut noise = vec![0.0; n];
    for v in noise.iter_mut() {
        seed = seed
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        let u = (seed >> 11) as f64 / (1u64 << 53) as f64;
        *v = u - 0.5;
    }
    let mut y = vec![0.0; n];
    for &(f, bw, g) in modes {
        let r = resonator(&noise, f, bw);
        for k in 0..n {
            y[k] += g * r[k];
        }
    }
    normalize(&mut y);
    y
}

fn normalize(y: &mut [f64]) {
    let peak = y.iter().fold(0.0_f64, |m, &v| m.max(v.abs())) + 1e-9;
    for v in y.iter_mut() {
        *v = *v / peak * 0.7;
    }
}

/// (captured, active_poles, spurious_count, low-formant runtime radius)
fn score(samples: &[f64], real_formants: &[f64], pre_emph: f64) -> (usize, usize, usize, f64) {
    let (poles, _) = lpc::extract_poles_and_valleys_pe(samples, SR, pre_emph, 0);
    let captured = real_formants
        .iter()
        .filter(|&&rf| poles.iter().any(|p| (p.freq_hz - rf).abs() / rf < 0.15))
        .count();
    let hi = real_formants.iter().cloned().fold(0.0_f64, f64::max);
    let spurious = poles.iter().filter(|p| p.freq_hz > hi * 1.5).count();
    let lo = real_formants.iter().cloned().fold(f64::INFINITY, f64::min);
    let low_rr = poles
        .iter()
        .min_by(|a, b| {
            (a.freq_hz - lo)
                .abs()
                .partial_cmp(&(b.freq_hz - lo).abs())
                .unwrap()
        })
        .map(|p| (-std::f64::consts::PI * p.bw_hz / RUNTIME_SR).exp())
        .unwrap_or(0.0);
    (captured, poles.len(), spurious, low_rr)
}

fn dump_poles(name: &str, samples: &[f64], real_formants: &[f64], pre_emph: f64) {
    let (poles, valleys) = lpc::extract_poles_and_valleys_pe(samples, SR, pre_emph, 0);
    println!("\n-- {name} @ pre_emph={pre_emph}  (real: {real_formants:?}) --");
    for (i, p) in poles.iter().enumerate() {
        let rr = (-std::f64::consts::PI * p.bw_hz / RUNTIME_SR).exp();
        println!(
            "  pole[{i}] f={:7.1}Hz  bw={:6.1}Hz  runtime_r={:.4}",
            p.freq_hz, p.bw_hz, rr
        );
    }
    print!("  valleys:");
    for v in valleys.iter().take(6) {
        print!(" {v:.0}");
    }
    println!();
}

fn sounds() -> Vec<(&'static str, Vec<f64>, Vec<f64>)> {
    vec![
        (
            "ah",
            synth(
                &[
                    (730.0, 80.0, 1.0),
                    (1090.0, 90.0, 0.6),
                    (2440.0, 120.0, 0.3),
                ],
                2.0,
                120.0,
            ),
            vec![730.0, 1090.0, 2440.0],
        ),
        (
            "ee",
            synth(
                &[
                    (270.0, 60.0, 1.0),
                    (2290.0, 100.0, 0.7),
                    (3010.0, 150.0, 0.3),
                ],
                2.0,
                120.0,
            ),
            vec![270.0, 2290.0, 3010.0],
        ),
        (
            "oo",
            synth(
                &[(300.0, 60.0, 1.0), (870.0, 80.0, 0.5), (2240.0, 120.0, 0.2)],
                2.0,
                120.0,
            ),
            vec![300.0, 870.0, 2240.0],
        ),
        (
            "eh",
            synth(
                &[
                    (530.0, 70.0, 1.0),
                    (1840.0, 100.0, 0.6),
                    (2480.0, 130.0, 0.3),
                ],
                2.0,
                120.0,
            ),
            vec![530.0, 1840.0, 2480.0],
        ),
        (
            "tube",
            synth_noise(
                &[
                    (220.0, 6.0, 1.0),
                    (540.0, 8.0, 0.8),
                    (980.0, 12.0, 0.6),
                    (1490.0, 16.0, 0.4),
                    (2300.0, 26.0, 0.25),
                ],
                2.0,
            ),
            vec![220.0, 540.0, 980.0, 1490.0, 2300.0],
        ),
    ]
}

#[test]
fn pre_emphasis_sweep() {
    let snd = sounds();
    let sweep = [0.0, 0.2, 0.4, 0.6, 0.8, 0.97];
    println!("\n===== PRE-EMPHASIS SWEEP (cap/total  s=spurious  r=low-formant radius) =====");
    print!("{:>10}", "");
    for pe in sweep {
        print!("{:>16}", format!("pe={pe}"));
    }
    println!();
    for (name, samples, formants) in &snd {
        print!("{name:>10}");
        for pe in sweep {
            let (cap, n, spur, rr) = score(samples, formants, pe);
            print!(
                "{:>18}",
                format!("{cap}/{} n{n} s{spur} r{rr:.3}", formants.len())
            );
        }
        println!();
    }
    println!("(cap=formants captured · n=active poles · s=spurious · r=low-formant radius)");
    println!("===== END SWEEP =====");
}

#[test]
fn dump_at_zero_preemph() {
    for (name, samples, formants) in &sounds() {
        dump_poles(name, samples, formants, 0.0);
    }
}
