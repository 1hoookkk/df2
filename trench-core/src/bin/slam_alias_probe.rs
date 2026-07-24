use trench_core::desk_drive::DeskDrive;
fn goertzel(buf: &[f64], fs: f64, f: f64) -> f64 {
    let w = 2.0 * std::f64::consts::PI * (f / fs);
    let coeff = 2.0 * w.cos();
    let (mut s1, mut s2) = (0.0f64, 0.0f64);
    for &x in buf {
        let s0 = x + coeff * s1 - s2;
        s2 = s1;
        s1 = s0;
    }
    let real = s1 - s2 * w.cos();
    let imag = s2 * w.sin();
    (real * real + imag * imag).sqrt() / (buf.len() as f64 / 2.0)
}
fn fold(f: f64, fs: f64) -> f64 {
    let mut g = f % fs;
    if g > fs / 2.0 {
        g = fs - g;
    }
    g.abs()
}
fn run(fs: f64, f0: f64, slam: f32, amp: f64) {
    let n = fs as usize;
    let warm = 8192usize;
    let mut dd = DeskDrive::new();
    dd.prepare(fs as f32);
    dd.configure("desk_slam_v1");
    assert!(dd.is_active(), "desk drive must be active");
    let mut out = Vec::with_capacity(n);
    for i in 0..(n + warm) {
        let t = i as f64 / fs;
        let x = (2.0 * std::f64::consts::PI * f0 * t).sin() * amp;
        let y = dd.process(x as f32, slam) as f64;
        if i >= warm {
            out.push(y);
        }
    }
    let fund = goertzel(&out, fs, f0);
    let dbc = |m: f64| 20.0 * (m / fund).max(1.0e-12).log10();
    println!("--- fs={fs} Hz  f0={f0} Hz  slam={slam}  amp={amp} ---");
    for k in [3.0, 5.0, 7.0] {
        let f = k * f0;
        if f < fs / 2.0 {
            println!("  harmonic {k}f0 @ {:>6.0} Hz : {:>6.1} dBc", f, dbc(goertzel(&out, fs, f)));
        }
    }
    let mut worst = -200.0f64;
    let mut worst_hz = 0.0;
    for k in [5.0, 7.0, 9.0, 11.0, 13.0, 15.0] {
        let f = fold(k * f0, fs);
        if ((f / f0).round() * f0 - f).abs() < 0.5 {
            continue;
        }
        let d = dbc(goertzel(&out, fs, f));
        println!("  ALIAS  {k}f0 -> {:>6.0} Hz : {:>6.1} dBc", f, d);
        if d > worst {
            worst = d;
            worst_hz = f;
        }
    }
    println!("  >>> worst alias spur: {:.1} dBc @ {:.0} Hz\n", worst, worst_hz);
}
fn run_raw(fs: f64, f0: f64, drive: f64, oversample: bool) {
    use trench_core::desk_drive::mackity_saturate;
    use trench_core::oversample::Oversampler4x;
    let n = fs as usize;
    let warm = 8192usize;
    let mut os = Oversampler4x::new();
    let mut out = Vec::with_capacity(n);
    for i in 0..(n + warm) {
        let t = i as f64 / fs;
        let x = (2.0 * std::f64::consts::PI * f0 * t).sin() * 0.5;
        let y = if oversample {
            let up = os.upsample(x);
            os.downsample(&[
                mackity_saturate(up[0] * drive),
                mackity_saturate(up[1] * drive),
                mackity_saturate(up[2] * drive),
                mackity_saturate(up[3] * drive),
            ])
        } else {
            mackity_saturate(x * drive)
        };
        if i >= warm {
            out.push(y);
        }
    }
    let fund = goertzel(&out, fs, f0);
    let dbc = |m: f64| 20.0 * (m / fund).max(1.0e-12).log10();
    let mut worst = -200.0f64;
    let mut worst_hz = 0.0;
    for k in [5.0, 7.0, 9.0, 11.0, 13.0, 15.0] {
        let f = fold(k * f0, fs);
        if ((f / f0).round() * f0 - f).abs() < 0.5 {
            continue;
        }
        let d = dbc(goertzel(&out, fs, f));
        if d > worst {
            worst = d;
            worst_hz = f;
        }
    }
    println!(
        "  OUTPUT desk fs={fs} drive={drive:.2} os={oversample:<5} : worst alias {:.1} dBc @ {:.0} Hz",
        worst, worst_hz
    );
}
fn main() {
    println!("=== ISLAND (default) 39062.5 Hz — the shipping default ===");
    run(39062.5, 5500.0, 0.9, 0.5);
    run(39062.5, 5500.0, 0.3, 0.5);
    println!("=== HD ISLAND 78125 Hz — the 2x option ===");
    run(78125.0, 11000.0, 0.9, 0.5);
    run(78125.0, 11000.0, 0.3, 0.5);
    println!("=== DEFAULT SLAM (output desk, host rate) — the audible one ===");
    let drive_max = 10f64.powf(12.0 / 20.0);
    let drive_mid = 10f64.powf(6.0 / 20.0);
    for &fs in &[48000.0, 96000.0] {
        run_raw(fs, 7333.0, drive_max, false);
        run_raw(fs, 7333.0, drive_max, true);
        run_raw(fs, 7333.0, drive_mid, false);
        run_raw(fs, 7333.0, drive_mid, true);
    }
}
