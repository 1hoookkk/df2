use std::f64::consts::PI;
use trench_core::minifloat::PackedCorners;
const FS: f64 = 39062.5;
fn stage_db(c: &[f64; 5], w: f64) -> f64 {
    let (cw, sw) = (w.cos(), w.sin());
    let (c2, s2) = ((2.0 * w).cos(), (2.0 * w).sin());
    let num_re = c[0] + c[1] * cw + c[2] * c2;
    let num_im = -(c[1] * sw + c[2] * s2);
    let den_re = 1.0 + c[3] * cw + c[4] * c2;
    let den_im = -(c[3] * sw + c[4] * s2);
    let num = (num_re * num_re + num_im * num_im).sqrt();
    let den = (den_re * den_re + den_im * den_im).sqrt();
    20.0 * (num / den.max(1.0e-12)).max(1.0e-12).log10()
}
fn corner_stats(coeffs: &[[f64; 5]; 6]) -> (f64, f64, f64) {
    let n = 256usize;
    let (f_lo, f_hi) = (30.0f64, 19_200.0f64);
    let mut db: Vec<f64> = (0..n)
        .map(|i| {
            let f = f_lo * (f_hi / f_lo).powf(i as f64 / (n - 1) as f64);
            let w = 2.0 * PI * f / FS;
            coeffs.iter().map(|s| stage_db(s, w)).sum()
        })
        .collect();
    let crown = db.iter().cloned().fold(f64::MIN, f64::max);
    db.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let floor = db[n / 2];
    (crown, floor, crown - floor)
}
fn main() {
    let path = std::env::args().nth(1).expect("usage: corner_contrast <body240>");
    let bytes = std::fs::read(&path).expect("read body240");
    assert_eq!(bytes.len(), 240, "body240 must be 240 bytes");
    let mut words = [[[0u16; 5]; 6]; 4];
    let mut k = 0;
    for c in 0..4 {
        for s in 0..6 {
            for w in 0..5 {
                words[c][s][w] = u16::from_le_bytes([bytes[k], bytes[k + 1]]);
                k += 2;
            }
        }
    }
    let packed = PackedCorners { words };
    println!("{path}");
    println!("  corner        crown    floor  contrast");
    for (label, m, q) in [
        ("M0_Q0   ", 0.0f32, 0.0f32),
        ("M100_Q0 ", 1.0, 0.0),
        ("M0_Q100 ", 0.0, 1.0),
        ("M100_Q100", 1.0, 1.0),
    ] {
        let coeffs = packed.interpolate_biquad(m, q);
        let (crown, floor, contrast) = corner_stats(&coeffs);
        println!("  {label}  {:>6.1}  {:>6.1}  {:>6.1} dB", crown, floor, contrast);
    }
}
