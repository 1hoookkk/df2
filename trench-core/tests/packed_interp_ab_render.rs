//! Packed-domain vs decoded-float A/B audition renders.
//!
//! Run with:
//!   cargo test -p trench-core --features packed_interp --test packed_interp_ab_render -- --nocapture
//!
//! Writes 4 WAVs to `../dev/tmp/packed_interp_ab/<timestamp>/`:
//!   packed_midpoint.wav            — packed  @ M=0.5  Q=0.5
//!   float_midpoint.wav             — float   @ M=0.5  Q=0.5
//!   packed_offset_near_mid.wav     — packed  @ M=0.46875  Q=0.46875
//!   float_offset_near_mid.wav      — float   @ M=0.46875  Q=0.46875
//!
//! Signal: deterministic pink noise, 3 s, 44100 Hz.
//! Cascade path: Rust trench-core Cascade (the actual runtime path).
//!
//! Source: ref/p2k_skins/00_talking_hedz.json (P2K format, has Q variation).
//! Packed words are derived-packed-canonical.
//!
//! Note: hedz_rom.rs is Q-collapsed (Q0==Q100), so packed and float give
//! identical results for that data. The P2K JSON has distinct Q corners.

#[cfg(feature = "packed_interp")]
mod ab_render {
    use hound::{SampleFormat, WavSpec, WavWriter};
    use std::f32::consts::TAU;
    use std::path::{Path, PathBuf};
    use trench_core::cascade::{Cascade, BLOCK_SIZE};
    use trench_core::cartridge::Cartridge;
    use trench_core::minifloat::PackedCorners;
    use trench_core::CornerData;

    const SR: u32 = 44100;
    const DURATION_S: f32 = 3.0;
    const AMPLITUDE: f32 = 0.25;

    // ── signal generation ─────────────────────────────────────────────────

    /// Deterministic approximate pink noise (Paul Kellet IIR on white).
    /// Broadband — excites all formants simultaneously. Seeded so renders
    /// are identical across runs.
    fn make_pink_noise() -> Vec<f32> {
        let n = (DURATION_S * SR as f32).round() as usize;
        let mut out = Vec::with_capacity(n);
        let (mut b0, mut b1, mut b2, mut b3, mut b4, mut b5, mut b6) =
            (0.0f32, 0.0f32, 0.0f32, 0.0f32, 0.0f32, 0.0f32, 0.0f32);
        // LCG — same seed every run
        let mut s: u64 = 0x517cc1b727220a95;
        for _ in 0..n {
            s = s.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            let w = (s >> 33) as f32 / 2_147_483_647.0 - 1.0; // [-1, 1]
            b0 = 0.99886 * b0 + w * 0.0555179;
            b1 = 0.99332 * b1 + w * 0.0750759;
            b2 = 0.96900 * b2 + w * 0.1538520;
            b3 = 0.86650 * b3 + w * 0.3104856;
            b4 = 0.55000 * b4 + w * 0.5329522;
            b5 = -0.7616 * b5 - w * 0.0168980;
            let pink = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.11;
            b6 = w * 0.115926;
            out.push(AMPLITUDE * pink);
        }
        out
    }

    // ── coefficient conversion ────────────────────────────────────────────

    /// Convert Python `stage_to_kernel` form [c0..c4] to Rust Cascade biquad form.
    ///
    /// Python encodes:  c2 = 2+a1,  c3 = 1−r²,  b0=c4,  b1=(c0−2)*c4,  b2=(1−c1)*c4
    /// Rust cascade expects [b0, b1, b2, a1, a2] where H(z) = (b0+b1z⁻¹+b2z⁻²)/(1+a1z⁻¹+a2z⁻²)
    fn kernel_to_biquad(k: &CornerData) -> CornerData {
        let mut out = [[0.0f64; 5]; 6];
        for si in 0..6 {
            let [c0, c1, c2, c3, c4] = k[si];
            out[si][0] = c4;               // b0
            out[si][1] = (c0 - 2.0) * c4; // b1
            out[si][2] = (1.0 - c1) * c4; // b2
            out[si][3] = c2 - 2.0;        // a1
            out[si][4] = 1.0 - c3;        // a2
        }
        out
    }

    // ── cascade render ────────────────────────────────────────────────────

    /// Process dry through a Cascade with fixed coefficients and boost.
    ///
    /// Warms up the ramp on 32 samples of silence so the coefficient ramp
    /// completes before the signal arrives — prevents the ramp transient from
    /// flushing the high-Q cascade state to zero.
    /// Normalises to peak 0.99 if the cascade gain clips.
    fn render(coeffs: &CornerData, boost: f64, dry: &[f32]) -> Vec<f32> {
        let mut cascade = Cascade::new();
        cascade.set_targets(coeffs, BLOCK_SIZE);
        cascade.set_boost(boost, BLOCK_SIZE);

        // Ramp on silence, then re-set targets to zero residual deltas.
        // Without the second set_targets, the deltas overshoot past the target
        // on the first signal block, pushing poles outside the unit circle.
        let mut warmup = vec![0.0f32; BLOCK_SIZE];
        cascade.process_block_mono(&mut warmup);
        cascade.set_targets(coeffs, BLOCK_SIZE); // now at target: deltas → 0
        cascade.set_boost(boost, BLOCK_SIZE);    // same

        let mut out = dry.to_vec();
        let n = out.len();
        let mut pos = 0;
        while pos < n {
            let chunk = (n - pos).min(BLOCK_SIZE);
            cascade.process_block_mono(&mut out[pos..pos + chunk]);
            pos += chunk;
        }

        // Flush non-finite samples then normalise to peak 0.99.
        for s in &mut out {
            if !s.is_finite() {
                *s = 0.0;
            }
        }
        let peak = out.iter().map(|&x| x.abs()).fold(0.0f32, f32::max);
        if peak > 0.99 {
            let scale = 0.99 / peak;
            for s in &mut out {
                *s *= scale;
            }
        }

        out
    }

    // ── WAV I/O ───────────────────────────────────────────────────────────

    fn write_wav(path: &Path, samples: &[f32]) {
        std::fs::create_dir_all(path.parent().unwrap()).expect("create output dir");
        let spec = WavSpec {
            channels: 1,
            sample_rate: SR,
            bits_per_sample: 16,
            sample_format: SampleFormat::Int,
        };
        let mut w = WavWriter::create(path, spec).expect("create wav");
        for &s in samples {
            let pcm = (s.clamp(-1.0, 1.0) * 32767.0) as i16;
            w.write_sample(pcm).expect("write sample");
        }
        w.finalize().expect("finalize wav");
    }

    // ── null depth ────────────────────────────────────────────────────────

    fn null_depth_db(a: &[f32], b: &[f32]) -> f64 {
        let n = a.len().min(b.len());
        let ref_rms = (a[..n].iter().map(|&x| (x as f64).powi(2)).sum::<f64>() / n as f64)
            .sqrt()
            .max(1e-30);
        let res_rms = (a[..n]
            .iter()
            .zip(b[..n].iter())
            .map(|(&x, &y)| ((x as f64) - (y as f64)).powi(2))
            .sum::<f64>()
            / n as f64)
            .sqrt()
            .max(1e-30);
        20.0 * (res_rms / ref_rms).log10()
    }

    // ── test ──────────────────────────────────────────────────────────────

    #[test]
    fn render_ab_wavs() {
        // Load the pre-compiled cartridge (stage_to_kernel c0..c4 convention,
        // all-positive values in minifloat range). Generated from P2K JSON by
        // tools/bake_cartridge.py. Has real Q variation so packed ≠ float.
        let json_path = PathBuf::from("../dev/bake/00_talking_hedz_compiled.json");
        if !json_path.exists() {
            panic!(
                "dev/bake/00_talking_hedz_compiled.json not found. \
                 Run: python tools/bake_cartridge.py"
            );
        }
        let json = std::fs::read_to_string(&json_path).expect("read cartridge json");
        let cartridge = Cartridge::from_json(&json).expect("parse cartridge json");
        let packed = PackedCorners::from_corner_data(&cartridge.corners);

        // Hedz boost is uniform 4.0; use it for both paths.
        let boost = cartridge.interpolate_boost(0.5, 0.5);

        let dry = make_pink_noise();

        // ── render points ──
        let points: &[(&str, f32, f32)] = &[
            ("midpoint",         0.5f32,    0.5f32),
            ("offset_near_mid",  0.46875,   0.46875),
        ];

        // Output under workspace root
        let timestamp = chrono_like_timestamp();
        let out_dir = PathBuf::from("../dev/tmp/packed_interp_ab").join(&timestamp);

        println!("\noutput directory: {}", out_dir.display());
        println!("{:<28} {:<12} {:<12}  null(packed vs float)", "point", "morph", "q");
        println!("{}", "-".repeat(70));

        for &(label, morph, q) in points {
            // Decoded-float path: interpolate in float, convert kernel→biquad, render
            let coeffs_float_kernel = cartridge.interpolate(morph as f64, q as f64);
            let coeffs_float = kernel_to_biquad(&coeffs_float_kernel);
            let wet_float = render(&coeffs_float, boost, &dry);

            // Packed-domain path: interpolate in packed u16, convert kernel→biquad, render
            let coeffs_packed_kernel = packed.interpolate(morph, q);
            let coeffs_packed = kernel_to_biquad(&coeffs_packed_kernel);
            let wet_packed = render(&coeffs_packed, boost, &dry);

            // Coefficient diff for cross-check
            let max_coeff_diff = coeffs_float.iter().zip(coeffs_packed.iter())
                .flat_map(|(af, ap)| af.iter().zip(ap.iter()).map(|(a, b)| (a - b).abs()))
                .fold(0.0f64, f64::max);
            println!("  max|biquad coeff diff|={max_coeff_diff:.4}");

            let null_db = null_depth_db(&wet_packed, &wet_float);

            write_wav(
                &out_dir.join(format!("packed_{label}.wav")),
                &wet_packed,
            );
            write_wav(
                &out_dir.join(format!("float_{label}.wav")),
                &wet_float,
            );

            println!(
                "{:<28} {:<12.5} {:<12.5}  {null_db:.2} dB",
                label, morph, q
            );

            // Assert the paths diverge — quantisation should produce audible difference.
            // < −60 dB would mean they're effectively identical. > −30 dB = audible gap.
            assert!(
                null_db > -60.0,
                "{label}: packed and decoded-float are suspiciously identical ({null_db:.2} dB); \
                 check that packed words encoded from compiled c0..c4 corners are non-trivial"
            );
        }

        // Write a brief manifest
        let manifest = format!(
            "packed_interp A/B render\n\
             timestamp: {timestamp}\n\
             cartridge: 00_talking_hedz_compiled.json (stage_to_kernel c0..c4, derived-packed-canonical)\n\
             signal: {DURATION_S}s pink noise @ {SR} Hz\n\
             \n\
             files:\n\
             {}\n",
            points
                .iter()
                .flat_map(|(label, morph, q)| {
                    [
                        format!("  packed_{label}.wav  M={morph:.5} Q={q:.5}"),
                        format!("  float_{label}.wav   M={morph:.5} Q={q:.5}"),
                    ]
                })
                .collect::<Vec<_>>()
                .join("\n")
        );
        std::fs::write(out_dir.join("MANIFEST.txt"), manifest).expect("write manifest");

        println!("\nwrote {} WAVs to {}", points.len() * 2, out_dir.display());
        println!("listen in order: float_midpoint → packed_midpoint");
        println!("question: does packed recover Aee/body emergence at M=0.5 Q=0.5?");
    }

    /// Produce a compact timestamp string without pulling in chrono.
    fn chrono_like_timestamp() -> String {
        use std::time::{SystemTime, UNIX_EPOCH};
        let secs = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        // YYYYMMDD_HHMMSS approximation from Unix seconds
        let s = secs % 86400;
        let d = secs / 86400;
        let h = s / 3600;
        let m = (s % 3600) / 60;
        let sec = s % 60;
        // Days since epoch → approximate date (good enough for a folder name)
        // Use a simple offset: 2026-01-01 = day 20454 from 1970-01-01
        let year_day = d.saturating_sub(20454);
        let year = 2026 + year_day / 365;
        let yday = year_day % 365;
        format!("{year}{:03}_{h:02}{m:02}{sec:02}", yday)
    }
}
