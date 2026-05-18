use trench_core::{Cartridge, Cascade, BLOCK_SIZE};

fn load_audit_cartridge() -> Cartridge {
    // Distinct 6-stage/4-corner body so morph/q movement changes runtime coefficients.
    let json = r#"{
      "version": "compiled-v1",
      "name": "AuditBody",
      "corners": {
        "M0_Q0": [
          [0.950, 0.0, 0.0, 0.0, 0.0],
          [0.960, 0.0, 0.0, 0.0, 0.0],
          [0.970, 0.0, 0.0, 0.0, 0.0],
          [0.980, 0.0, 0.0, 0.0, 0.0],
          [0.990, 0.0, 0.0, 0.0, 0.0],
          [1.000, 0.0, 0.0, 0.0, 0.0]
        ],
        "M100_Q0": [
          [1.020, 0.0, 0.0, 0.0, 0.0],
          [1.030, 0.0, 0.0, 0.0, 0.0],
          [1.040, 0.0, 0.0, 0.0, 0.0],
          [1.050, 0.0, 0.0, 0.0, 0.0],
          [1.060, 0.0, 0.0, 0.0, 0.0],
          [1.070, 0.0, 0.0, 0.0, 0.0]
        ],
        "M0_Q100": [
          [0.900, 0.0, 0.0, 0.0, 0.0],
          [0.910, 0.0, 0.0, 0.0, 0.0],
          [0.920, 0.0, 0.0, 0.0, 0.0],
          [0.930, 0.0, 0.0, 0.0, 0.0],
          [0.940, 0.0, 0.0, 0.0, 0.0],
          [0.950, 0.0, 0.0, 0.0, 0.0]
        ],
        "M100_Q100": [
          [1.100, 0.0, 0.0, 0.0, 0.0],
          [1.110, 0.0, 0.0, 0.0, 0.0],
          [1.120, 0.0, 0.0, 0.0, 0.0],
          [1.130, 0.0, 0.0, 0.0, 0.0],
          [1.140, 0.0, 0.0, 0.0, 0.0],
          [1.150, 0.0, 0.0, 0.0, 0.0]
        ]
      }
    }"#;
    Cartridge::from_json(json).expect("audit cartridge should parse")
}

fn make_input_signal(samples: usize) -> Vec<f32> {
    // Deterministic, broadband input with no external fixtures.
    let mut seed: u32 = 0x1234_5678;
    let mut out = Vec::with_capacity(samples);
    for i in 0..samples {
        seed = seed.wrapping_mul(1664525).wrapping_add(1013904223);
        let noise = ((seed >> 8) as f32 / ((u32::MAX >> 8) as f32)) * 2.0 - 1.0;
        let sine = (2.0 * std::f32::consts::PI * 220.0 * (i as f32 / 44_100.0)).sin();
        out.push(0.15 * noise + 0.10 * sine);
    }
    out
}

fn automation_at(sample_index: usize, total_samples: usize) -> (f64, f64) {
    let denom = total_samples.saturating_sub(1).max(1) as f64;
    let t = sample_index as f64 / denom;
    let morph = t.clamp(0.0, 1.0);
    let q = (1.0 - 0.85 * t).clamp(0.0, 1.0);
    (morph, q)
}

/// Mirror of current `trench-plugin/src/lib.rs::process` semantics relevant to morph/q:
/// - morph/q are sampled once per outer process call (host block),
/// - interpolation is computed once from that pair,
/// - the inner audio loop re-slices by `BLOCK_SIZE` and ramps toward the same target.
fn render_like_current_plugin(
    cartridge: &Cartridge,
    input: &[f32],
    host_block_size: usize,
) -> Vec<f32> {
    let mut out = input.to_vec();
    let mut cascade = Cascade::new();
    let total = out.len();

    let mut block_start = 0usize;
    while block_start < total {
        let outer_len = (total - block_start).min(host_block_size.max(1));
        let (morph, q) = automation_at(block_start, total);
        let coeffs = cartridge.interpolate(morph, q);
        let boost = cartridge.interpolate_boost(morph, q);

        let mut inner_start = 0usize;
        while inner_start < outer_len {
            let inner_len = (outer_len - inner_start).min(BLOCK_SIZE);
            cascade.set_targets(&coeffs, inner_len);
            cascade.set_boost(boost, inner_len);

            let start = block_start + inner_start;
            let end = start + inner_len;
            cascade.process_block_mono(&mut out[start..end]);

            inner_start += inner_len;
        }

        block_start += outer_len;
    }

    out
}

fn diff_metrics(reference: &[f32], candidate: &[f32]) -> (f64, f64) {
    assert_eq!(reference.len(), candidate.len());
    let mut max_abs = 0.0f64;
    let mut sum_sq = 0.0f64;
    for (a, b) in reference.iter().zip(candidate.iter()) {
        let d = (*a as f64 - *b as f64).abs();
        if d > max_abs {
            max_abs = d;
        }
        sum_sq += d * d;
    }
    let rms = (sum_sq / reference.len() as f64).sqrt();
    (max_abs, rms)
}

#[test]
fn block_size_dependence_for_morph_q_automation() {
    let cartridge = load_audit_cartridge();
    let input = make_input_signal(44_100); // 1 second @ 44.1k
    let block_sizes = [16usize, 32, 64, 128, 256, 512];

    let mut rendered: Vec<(usize, Vec<f32>)> = Vec::new();
    for block_size in block_sizes {
        let audio = render_like_current_plugin(&cartridge, &input, block_size);
        rendered.push((block_size, audio));
    }

    let reference = &rendered[0].1; // 16-sample host block as highest control-rate in this sweep
    let mut worst_max_abs = 0.0f64;
    for (block_size, audio) in rendered.iter().skip(1) {
        let (max_abs, rms) = diff_metrics(reference, audio);
        println!(
            "host_block={} vs 16: max_abs={:.9e}, rms={:.9e}",
            block_size, max_abs, rms
        );
        if max_abs > worst_max_abs {
            worst_max_abs = max_abs;
        }
    }

    assert!(
        worst_max_abs > 1e-7,
        "Expected host block size to change rendered output under process-latched automation"
    );
}
