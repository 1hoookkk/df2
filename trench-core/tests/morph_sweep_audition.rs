//! Morph-sweep audition — the simplest end-to-end test of encoded-domain
//! interpolation: render the real dry at five morph positions and listen.
//!
//! Run with:
//!   cargo test -p trench-core --features packed_interp --test morph_sweep_audition -- --nocapture
//!
//! Talking Hedz ROM corners. The dry is rendered through the verified
//! encoded-domain interpolation (morph-first u16 lerp, c4=4*d4) and the
//! actual `trench-core` Cascade, for morph in {0, .25, .5, .75, 1.0} at
//! both Q=0 and Q=1.0. Output WAVs `m{morph}_q{q}.wav` under
//! ../dev/tmp/morph_sweep_audition/ — exercises both the morph and the Q
//! interpolation axes. Auditioning is the gate (CLAUDE.md).
//!
//! Verification only. No cartridge asset / format / topology change.

#[cfg(feature = "packed_interp")]
mod audition {
    use hound::{SampleFormat, WavReader, WavSpec, WavWriter};
    use std::path::{Path, PathBuf};
    use trench_core::cascade::{Cascade, BLOCK_SIZE};
    use trench_core::minifloat::PackedCorners;
    use trench_core::CornerData;

    const SR: u32 = 44100;
    const DRY_PATH: &str = r"C:\Users\hooki\Downloads\222323232.wav";
    const ROM_REL: &str = "../dev/tmp/cheat_engine_dump/skin13_corners_rom.bin";
    const OUT_DIR: &str = "../dev/tmp/morph_sweep_audition";

    /// Rossum kernel [c0..c4] -> DF2T biquad form [b0,b1,b2,a1,a2].
    fn kernel_to_biquad(k: &CornerData) -> CornerData {
        let mut out = [[0.0f64; 5]; 6];
        for si in 0..6 {
            let [c0, c1, c2, c3, c4] = k[si];
            out[si] = [c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, c2 - 2.0, 1.0 - c3];
        }
        out
    }

    fn load_mono_f32(path: &Path) -> Vec<f32> {
        let mut reader = WavReader::open(path)
            .unwrap_or_else(|e| panic!("open {}: {e}", path.display()));
        let spec = reader.spec();
        assert_eq!(spec.sample_rate, SR);
        assert_eq!(spec.sample_format, SampleFormat::Float);
        let interleaved: Vec<f32> =
            reader.samples::<f32>().map(|s| s.expect("sample")).collect();
        interleaved.iter().step_by(spec.channels as usize).copied().collect()
    }

    /// Fixed-coefficient Cascade render: warm the ramp up on silence so the
    /// signal sees fixed coefficients from sample 0 (zero state).
    fn render_fixed(coeffs: &CornerData, dry: &[f32]) -> (Vec<f32>, bool) {
        let mut cascade = Cascade::new();
        cascade.set_targets(coeffs, BLOCK_SIZE);
        let mut warmup = [0.0f32; BLOCK_SIZE];
        cascade.process_block_mono(&mut warmup);
        cascade.set_targets(coeffs, BLOCK_SIZE);
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
        std::fs::create_dir_all(path.parent().unwrap()).expect("create dir");
        let spec = WavSpec {
            channels: 1,
            sample_rate: SR,
            bits_per_sample: 32,
            sample_format: SampleFormat::Float,
        };
        let mut w = WavWriter::create(path, spec).expect("create wav");
        for &s in samples {
            w.write_sample(s).expect("write");
        }
        w.finalize().expect("finalize");
    }

    #[test]
    fn render_morph_sweep() {
        let rom_bytes = std::fs::read(PathBuf::from(ROM_REL)).unwrap_or_else(|e| {
            panic!("read {ROM_REL}: {e} — run tools/rom_corner_audit.py first")
        });
        let packed = PackedCorners::from_rom_bytes(&rom_bytes).expect("parse ROM");
        let dry = load_mono_f32(&PathBuf::from(DRY_PATH));
        let out_dir = PathBuf::from(OUT_DIR);

        println!("\nmorph sweep — Talking Hedz, encoded-domain interpolation");
        println!("dry: {} samples ({:.2} s)\n", dry.len(), dry.len() as f32 / SR as f32);

        let mut count = 0;
        for &q in &[0.0f32, 1.0] {
            for &morph in &[0.0f32, 0.12, 0.25, 0.5, 0.75, 1.0] {
                let kernel = packed.interpolate(morph, q);
                let biquad = kernel_to_biquad(&kernel);
                let (render, unstable) = render_fixed(&biquad, &dry);
                assert!(!unstable, "m{morph} q{q}: cascade went unstable");
                let peak = render.iter().map(|&x| x.abs()).fold(0.0f32, f32::max);
                let name = format!(
                    "m{:03}_q{:03}.wav",
                    (morph * 100.0).round() as i32,
                    (q * 100.0).round() as i32,
                );
                write_wav_f32(&out_dir.join(&name), &render);
                println!("  morph {morph:.2}  Q {q:.2}  ->  {name}  (peak {peak:.4})");
                count += 1;
            }
        }

        println!("\nwrote {count} WAVs to {}", out_dir.display());
        println!("Q=0 row: the morph sweep already auditioned. Q=1.0 row: new.");
    }
}
