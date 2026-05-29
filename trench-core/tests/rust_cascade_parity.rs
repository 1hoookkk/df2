//! Rust cascade parity render — feeds the real skin-13 ROM corner words
//! through the actual `trench-core` `Cascade` and writes the M50/Q50 render.
//!
//! Run with:
//!   cargo test -p trench-core --features packed_interp --test rust_cascade_parity -- --nocapture
//!
//! Pipeline (mirrors `tools/rom_corner_audit.py`'s Python `scipy.sosfilt` path):
//!   skin13_corners_rom.bin (240 raw ROM u16)
//!     -> PackedCorners::from_rom_bytes
//!     -> interpolate(0.5, 0.5)                 morph-first u16 bilinear, c4=4*d4
//!     -> kernel_to_biquad                      Rossum kernel -> DF2T biquad form
//!     -> Cascade (fixed coefficients, zero state)
//!
//! Output: `../dev/tmp/rust_cascade_parity/rust_rom_m50q50.wav`
//!   32-bit float, mono, 44100 Hz — written verbatim (NOT peak-normalised) so
//!   `tools/rust_cascade_parity.py` can null it against the Python -95 dB
//!   reference and the X3 wet without quantisation loss.
//!
//! Verification only. Touches no frozen decision: no cartridge asset, no
//! cartridge format, no cascade topology change.

#[cfg(feature = "packed_interp")]
mod parity {
    use hound::{SampleFormat, WavReader, WavSpec, WavWriter};
    use std::path::{Path, PathBuf};
    use trench_core::cascade::{Cascade, BLOCK_SIZE};
    use trench_core::minifloat::PackedCorners;
    use trench_core::CornerData;

    const SR: u32 = 44100;
    const DRY_PATH: &str = r"C:\Users\hooki\Downloads\222323232.wav";
    const ROM_REL: &str = "../dev/tmp/cheat_engine_dump/skin13_corners_rom.bin";
    const OUT_REL: &str = "../dev/tmp/rust_cascade_parity/rust_rom_m50q50.wav";

    /// Convert the interpolated Rossum kernel form [c0..c4] to the DF2T biquad
    /// form the `Cascade` expects: [b0, b1, b2, a1, a2] with
    ///   H(z) = (b0 + b1 z⁻¹ + b2 z⁻²) / (1 + a1 z⁻¹ + a2 z⁻²)
    ///
    /// Identical mapping to `tools/coefficient_field_bakeoff.py::kernel_to_sos`
    /// (minus the constant 1.0 denominator slot).
    fn kernel_to_biquad(k: &CornerData) -> CornerData {
        let mut out = [[0.0f64; 5]; 6];
        for si in 0..6 {
            let [c0, c1, c2, c3, c4] = k[si];
            out[si][0] = c4; // b0
            out[si][1] = (c0 - 2.0) * c4; // b1
            out[si][2] = (1.0 - c1) * c4; // b2
            out[si][3] = c2 - 2.0; // a1
            out[si][4] = 1.0 - c3; // a2
        }
        out
    }

    /// Load channel 0 of a float32 WAV as mono f32. Matches the channel pick of
    /// the Python `verified_packed_audit.load_mono` (`data[:, 0]`). The dry is
    /// already float32, so no normalisation is applied.
    fn load_mono_f32(path: &Path) -> Vec<f32> {
        let mut reader =
            WavReader::open(path).unwrap_or_else(|e| panic!("open {}: {e}", path.display()));
        let spec = reader.spec();
        assert_eq!(
            spec.sample_rate,
            SR,
            "{}: unexpected sample rate",
            path.display()
        );
        assert_eq!(
            spec.sample_format,
            SampleFormat::Float,
            "{}: expected float WAV",
            path.display()
        );
        let interleaved: Vec<f32> = reader
            .samples::<f32>()
            .map(|s| s.expect("read sample"))
            .collect();
        let ch = spec.channels as usize;
        interleaved.iter().step_by(ch).copied().collect()
    }

    /// Render `dry` through a fixed-coefficient `Cascade` with zero state.
    ///
    /// The coefficient ramp is warmed up on 32 samples of silence (which keeps
    /// the DF2T state at exactly zero), then `set_targets` is called again to
    /// drive the residual ramp deltas to ~0. The dry signal therefore sees
    /// fixed coefficients from sample 0 — equivalent to `scipy.sosfilt` with
    /// zero initial conditions. No boost (cartridge boost = 1.0), no peak
    /// normalisation: the output is the raw cascade render.
    fn render_fixed(coeffs: &CornerData, dry: &[f32]) -> (Vec<f32>, bool) {
        let mut cascade = Cascade::new();
        cascade.set_targets(coeffs, BLOCK_SIZE);

        let mut warmup = [0.0f32; BLOCK_SIZE];
        cascade.process_block_mono(&mut warmup);
        assert!(
            warmup.iter().all(|&s| s == 0.0),
            "warmup on silence must keep cascade state at zero"
        );
        cascade.set_targets(coeffs, BLOCK_SIZE); // residual deltas -> ~0

        let mut out = dry.to_vec();
        cascade.process_block_mono(&mut out);
        for s in &mut out {
            if !s.is_finite() {
                *s = 0.0;
            }
        }
        (out, cascade.take_instability_flag())
    }

    fn write_wav_f32(path: &Path, samples: &[f32]) {
        std::fs::create_dir_all(path.parent().unwrap()).expect("create output dir");
        let spec = WavSpec {
            channels: 1,
            sample_rate: SR,
            bits_per_sample: 32,
            sample_format: SampleFormat::Float,
        };
        let mut w = WavWriter::create(path, spec).expect("create wav");
        for &s in samples {
            w.write_sample(s).expect("write sample");
        }
        w.finalize().expect("finalize wav");
    }

    #[test]
    fn render_rom_m50q50() {
        // ── 1. raw ROM corner words -> PackedCorners ──────────────────────
        let rom_path = PathBuf::from(ROM_REL);
        let rom_bytes = std::fs::read(&rom_path).unwrap_or_else(|e| {
            panic!(
                "read {}: {e} — run tools/rom_corner_audit.py first",
                rom_path.display()
            )
        });
        assert_eq!(rom_bytes.len(), 240, "ROM corner block must be 240 bytes");
        let packed = PackedCorners::from_rom_bytes(&rom_bytes).expect("parse ROM corners");

        // ── 2. interpolate at M=0.5, Q=0.5 (morph-first u16 bilinear) ─────
        let kernel = packed.interpolate(0.5, 0.5);
        // ── 3. kernel -> DF2T biquad form ─────────────────────────────────
        let biquad = kernel_to_biquad(&kernel);

        println!("M50/Q50 interpolated coefficients (DF2T biquad form):");
        println!("  stage  b0          b1          b2          a1          a2");
        for (si, s) in biquad.iter().enumerate() {
            println!(
                "  {si:>5}  {:>10.6}  {:>10.6}  {:>10.6}  {:>10.6}  {:>10.6}",
                s[0], s[1], s[2], s[3], s[4]
            );
        }

        // ── 4. render the real dry through the Rust Cascade ───────────────
        let dry_path = PathBuf::from(DRY_PATH);
        let dry = load_mono_f32(&dry_path);
        println!(
            "\ndry: {} samples ({:.2} s)",
            dry.len(),
            dry.len() as f32 / SR as f32
        );

        let (render, unstable) = render_fixed(&biquad, &dry);
        let peak = render.iter().map(|&x| x.abs()).fold(0.0f32, f32::max);
        let nonzero = render.iter().filter(|&&x| x != 0.0).count();
        println!(
            "render: {} samples, peak {:.6}, {} non-zero, instability_flag = {}",
            render.len(),
            peak,
            nonzero,
            unstable
        );

        assert!(
            !unstable,
            "M50/Q50 cascade went unstable — coefficients should be pole-stable"
        );
        assert!(render.len() == dry.len(), "render length must match dry");
        assert!(
            peak > 0.0 && peak.is_finite(),
            "render is silent or non-finite"
        );

        // ── 5. write the render verbatim for the Python parity harness ────
        let out_path = PathBuf::from(OUT_REL);
        write_wav_f32(&out_path, &render);
        println!("\nwrote Rust cascade render -> {}", out_path.display());
        println!("next: python tools/rust_cascade_parity.py");
    }
}
