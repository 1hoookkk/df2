use std::f64::consts::TAU;
use std::path::Path;
use serde_json::{json, Value};
use trench_core::arma::fit_corner_from_magnitude;
use trench_core::cascade::{NUM_COEFFS, NUM_STAGES};
use trench_core::minifloat::{encode, pole_radius, PackedCorners};
use trench_core::response::biquad_cascade_complex;
use trench_core::stage_law::{geometry_from_words, words_from_roots, RootPair, StageRoots, STAGE_SR};
const POLE_HZ_MIN: f64 = 60.0;
const POLE_HZ_MAX: f64 = 12_000.0;
const ZERO_HZ_MIN: f64 = 60.0;
const ZERO_HZ_MAX: f64 = 12_000.0;
const POLE_R_MIN: f64 = 0.55;
const POLE_R_MAX: f64 = 0.995;
const ZERO_R_MIN: f64 = 0.05;
const ZERO_R_MAX: f64 = 0.995;
const SCALE_MIN: f64 = 0.01;
const SCALE_MAX: f64 = 4.0;
const PHASE_WEIGHT: f64 = 1.0;
const INVALID_COST: f64 = 1.0e12;
#[derive(Clone, Copy, Debug)]
struct Params {
    pole_hz: f64,
    pole_r: f64,
    zero_hz: f64,
    zero_r: f64,
    scale: f64,
}
#[derive(Clone, Debug)]
struct Metrics {
    cost: f64,
    magnitude_rms_db: f64,
    phase_rms_rad: f64,
    magnitude_max_db: f64,
    max_pole_radius: f64,
    words: [[u16; NUM_COEFFS]; NUM_STAGES],
    packed: PackedCorners,
    valid_conjugate: bool,
}
fn fail(message: impl AsRef<str>) -> ! {
    eprintln!("REFUSED: {}", message.as_ref());
    std::process::exit(1);
}
fn finite_array(value: &Value, key: &str) -> Vec<f64> {
    value
        .get(key)
        .and_then(Value::as_array)
        .unwrap_or_else(|| fail(format!("missing array '{key}'")))
        .iter()
        .enumerate()
        .map(|(index, item)| {
            let number = item
                .as_f64()
                .unwrap_or_else(|| fail(format!("{key}[{index}] is not a number")));
            if !number.is_finite() {
                fail(format!("{key}[{index}] is nonfinite"));
            }
            number
        })
        .collect()
}
fn wrap_pi(value: f64) -> f64 {
    let mut result = value % TAU;
    if result > std::f64::consts::PI {
        result -= TAU;
    }
    if result < -std::f64::consts::PI {
        result += TAU;
    }
    result
}
fn kernel_to_words(kernel: [f64; NUM_COEFFS]) -> [u16; NUM_COEFFS] {
    let [c0, c1, c2, c3, c4] = kernel;
    [
        encode((c0 - c1) / 4.0),
        encode(c1),
        encode((c2 - c3) / 4.0),
        encode(c3),
        encode(c4 / 4.0),
    ]
}
fn pair_json(pair: RootPair) -> Value {
    match pair {
        RootPair::Conjugate { hz, r } => json!({"hz": hz, "r": r}),
        RootPair::RealPair { root_a, root_b } => json!({"real_roots": [root_a, root_b]}),
        RootPair::Degenerate => json!({"hz": 0.0, "r": 0.0}),
    }
}
fn topology(pair: RootPair) -> &'static str {
    match pair {
        RootPair::Conjugate { .. } => "conjugate",
        RootPair::RealPair { .. } => "real_pair",
        RootPair::Degenerate => "degenerate",
    }
}
fn roots_from_geometry(words: [u16; NUM_COEFFS]) -> Option<Params> {
    let geometry = geometry_from_words(words);
    let pole = match geometry.pole {
        RootPair::Conjugate { hz, r } => (hz, r),
        RootPair::Degenerate => (POLE_HZ_MIN, POLE_R_MIN),
        RootPair::RealPair { .. } => return None,
    };
    let zero = match geometry.zero {
        RootPair::Conjugate { hz, r } => (hz.max(ZERO_HZ_MIN), r.max(ZERO_R_MIN)),
        RootPair::Degenerate => (ZERO_HZ_MIN, ZERO_R_MIN),
        RootPair::RealPair { .. } => return None,
    };
    Some(Params {
        pole_hz: pole.0.clamp(POLE_HZ_MIN, POLE_HZ_MAX),
        pole_r: pole.1.clamp(POLE_R_MIN, POLE_R_MAX),
        zero_hz: zero.0.clamp(ZERO_HZ_MIN, ZERO_HZ_MAX),
        zero_r: zero.1.clamp(ZERO_R_MIN, ZERO_R_MAX),
        scale: geometry.scale.clamp(SCALE_MIN, SCALE_MAX),
    })
}
fn default_seed() -> [Params; NUM_STAGES] {
    let frequencies = [90.0, 250.0, 650.0, 1_500.0, 3_500.0, 7_500.0];
    std::array::from_fn(|index| Params {
        pole_hz: frequencies[index],
        pole_r: 0.93,
        zero_hz: frequencies[index],
        zero_r: 0.75,
        scale: 1.0,
    })
}
fn magnitude_seed(freqs: &[f64], target_db: &[f64]) -> Option<[Params; NUM_STAGES]> {
    let curve: Vec<(f64, f64)> = freqs.iter().copied().zip(target_db.iter().copied()).collect();
    let corner = fit_corner_from_magnitude(&curve, STAGE_SR)?;
    let mut result = default_seed();
    for (index, kernel) in corner.iter().enumerate() {
        let words = kernel_to_words(*kernel);
        if let Some(params) = roots_from_geometry(words) {
            result[index] = params;
        }
    }
    Some(result)
}
fn stage_roots(params: Params) -> StageRoots {
    StageRoots {
        pole_hz: params.pole_hz.clamp(POLE_HZ_MIN, POLE_HZ_MAX),
        pole_r: params.pole_r.clamp(POLE_R_MIN, POLE_R_MAX),
        zero_hz: params.zero_hz.clamp(ZERO_HZ_MIN, ZERO_HZ_MAX),
        zero_r: params.zero_r.clamp(ZERO_R_MIN, ZERO_R_MAX),
        scale: params.scale.clamp(SCALE_MIN, SCALE_MAX),
    }
}
fn make_packed(params: &[Params; NUM_STAGES]) -> (PackedCorners, [[u16; NUM_COEFFS]; NUM_STAGES], bool) {
    let words = std::array::from_fn(|index| words_from_roots(&stage_roots(params[index])));
    let packed = PackedCorners { words: [words; 4] };
    let mut conjugate = true;
    for stage in words {
        let geometry = geometry_from_words(stage);
        if matches!(geometry.pole, RootPair::RealPair { .. })
            || matches!(geometry.zero, RootPair::RealPair { .. })
        {
            conjugate = false;
        }
    }
    (packed, words, conjugate)
}
fn evaluate(params: &[Params; NUM_STAGES], freqs: &[f64], target: &[(f64, f64)]) -> Metrics {
    let (packed, words, valid_conjugate) = make_packed(params);
    let rows = packed.interpolate_biquad(0.0, 0.0);
    let mut sum_mag = 0.0;
    let mut sum_phase = 0.0;
    let mut max_mag: f64 = 0.0;
    let mut max_radius: f64 = 0.0;
    for row in rows {
        max_radius = max_radius.max(pole_radius(row[3], row[4]));
    }
    if !valid_conjugate || !max_radius.is_finite() || max_radius >= 1.0 {
        return Metrics {
            cost: INVALID_COST,
            magnitude_rms_db: f64::INFINITY,
            phase_rms_rad: f64::INFINITY,
            magnitude_max_db: f64::INFINITY,
            max_pole_radius: max_radius,
            words,
            packed,
            valid_conjugate,
        };
    }
    for (index, &frequency) in freqs.iter().enumerate() {
        let (got_re, got_im) = biquad_cascade_complex(&rows, frequency, STAGE_SR);
        if !got_re.is_finite() || !got_im.is_finite() {
            return Metrics {
                cost: INVALID_COST,
                magnitude_rms_db: f64::INFINITY,
                phase_rms_rad: f64::INFINITY,
                magnitude_max_db: f64::INFINITY,
                max_pole_radius: max_radius,
                words,
                packed,
                valid_conjugate,
            };
        }
        let (target_re, target_im) = target[index];
        let got_db = 20.0 * (got_re.hypot(got_im).max(1.0e-12)).log10();
        let target_db = 20.0 * (target_re.hypot(target_im).max(1.0e-12)).log10();
        let magnitude_error = got_db - target_db;
        let phase_error = wrap_pi(got_im.atan2(got_re) - target_im.atan2(target_re));
        sum_mag += magnitude_error * magnitude_error;
        sum_phase += phase_error * phase_error;
        max_mag = max_mag.max(magnitude_error.abs());
    }
    let n = freqs.len() as f64;
    let magnitude_rms_db = (sum_mag / n).sqrt();
    let phase_rms_rad = (sum_phase / n).sqrt();
    Metrics {
        cost: magnitude_rms_db * magnitude_rms_db + PHASE_WEIGHT * phase_rms_rad * phase_rms_rad,
        magnitude_rms_db,
        phase_rms_rad,
        magnitude_max_db: max_mag,
        max_pole_radius: max_radius,
        words,
        packed,
        valid_conjugate,
    }
}
fn clamp_param(params: &mut Params, index: usize) {
    match index {
        0 => params.pole_hz = params.pole_hz.clamp(POLE_HZ_MIN, POLE_HZ_MAX),
        1 => params.pole_r = params.pole_r.clamp(POLE_R_MIN, POLE_R_MAX),
        2 => params.zero_hz = params.zero_hz.clamp(ZERO_HZ_MIN, ZERO_HZ_MAX),
        3 => params.zero_r = params.zero_r.clamp(ZERO_R_MIN, ZERO_R_MAX),
        4 => params.scale = params.scale.clamp(SCALE_MIN, SCALE_MAX),
        _ => unreachable!(),
    }
}
fn shift_param(params: &mut Params, index: usize, octaves: f64, radius: f64, gain_db: f64, direction: f64) {
    match index {
        0 => params.pole_hz *= 2.0f64.powf(direction * octaves),
        1 => params.pole_r += direction * radius,
        2 => params.zero_hz *= 2.0f64.powf(direction * octaves),
        3 => params.zero_r += direction * radius,
        4 => params.scale *= 10.0f64.powf(direction * gain_db / 20.0),
        _ => unreachable!(),
    }
    clamp_param(params, index);
}
fn optimize(
    mut current: [Params; NUM_STAGES],
    freqs: &[f64],
    target: &[(f64, f64)],
) -> ([Params; NUM_STAGES], Metrics) {
    let mut best = evaluate(&current, freqs, target);
    for (octaves, radius, gain_db) in [(0.40, 0.04, 3.0), (0.20, 0.02, 1.5), (0.10, 0.01, 0.75), (0.05, 0.005, 0.375), (0.025, 0.0025, 0.1875)] {
        loop {
            let mut improved = false;
            for stage in 0..NUM_STAGES {
                for parameter in 0..5 {
                    for direction in [-1.0, 1.0] {
                        let mut trial = current;
                        shift_param(&mut trial[stage], parameter, octaves, radius, gain_db, direction);
                        let metrics = evaluate(&trial, freqs, target);
                        if metrics.cost + 1.0e-10 < best.cost {
                            current = trial;
                            best = metrics;
                            improved = true;
                        }
                    }
                }
            }
            if !improved {
                break;
            }
        }
    }
    (current, best)
}
fn value_params(params: &[Params; NUM_STAGES]) -> Value {
    Value::Array(
        params
            .iter()
            .map(|p| json!({
                "pole_hz": p.pole_hz,
                "pole_r": p.pole_r,
                "zero_hz": p.zero_hz,
                "zero_r": p.zero_r,
                "scale": p.scale,
            }))
            .collect(),
    )
}
fn value_stages(metrics: &Metrics) -> Value {
    Value::Array(
        metrics
            .words
            .iter()
            .map(|words| {
                let geometry = geometry_from_words(*words);
                json!({
                    "topology": {"pole": topology(geometry.pole), "zero": topology(geometry.zero)},
                    "state": if matches!(geometry.pole, RootPair::Degenerate) && matches!(geometry.zero, RootPair::Degenerate) && geometry.scale == 1.0 { "identity" } else { "active" },
                    "pole": pair_json(geometry.pole),
                    "zero": pair_json(geometry.zero),
                    "scale": geometry.scale,
                    "packed_words": words,
                })
            })
            .collect(),
    )
}
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let (input_path, output_path) = match args.as_slice() {
        [_, input, output] => (input, output),
        _ => {
            eprintln!("usage: fit-complex-candidates <in.complex_tf.json> <out.json>");
            std::process::exit(2);
        }
    };
    let input_text = std::fs::read_to_string(input_path)
        .unwrap_or_else(|error| fail(format!("read {input_path}: {error}")));
    let input: Value = serde_json::from_str(&input_text)
        .unwrap_or_else(|error| fail(format!("{input_path} is not JSON: {error}")));
    let freqs = finite_array(&input, "freqs_hz");
    let h_re = finite_array(&input, "h_re");
    let h_im = finite_array(&input, "h_im");
    if freqs.len() < 12 || h_re.len() != freqs.len() || h_im.len() != freqs.len() {
        fail("freqs_hz, h_re, and h_im must have equal lengths with at least 12 points");
    }
    for (index, pair) in freqs.windows(2).enumerate() {
        if pair[0] <= 0.0 || pair[1] <= pair[0] || pair[1] >= STAGE_SR * 0.5 {
            fail(format!("invalid frequency ordering/band at index {index}: {} -> {}", pair[0], pair[1]));
        }
    }
    if freqs[0] <= 0.0 || freqs[0] >= STAGE_SR * 0.5 {
        fail("first frequency is outside the runtime band");
    }
    let target: Vec<(f64, f64)> = h_re.iter().copied().zip(h_im.iter().copied()).collect();
    let target_db: Vec<f64> = target
        .iter()
        .map(|(re, im)| 20.0 * re.hypot(*im).max(1.0e-12).log10())
        .collect();
    let mut seeds = vec![default_seed()];
    if let Some(seed) = magnitude_seed(&freqs, &target_db) {
        seeds.push(seed);
    }
    let mut selected = None;
    for seed in seeds {
        let (params, metrics) = optimize(seed, &freqs, &target);
        if selected.as_ref().is_none_or(|(_, best): &( [Params; NUM_STAGES], Metrics) | metrics.cost < best.cost) {
            selected = Some((params, metrics));
        }
    }
    let (params, metrics) = selected.unwrap_or_else(|| fail("no optimization seed"));
    let mut real_rows = Vec::new();
    for (index, words) in metrics.words.iter().enumerate() {
        let geometry = geometry_from_words(*words);
        if matches!(geometry.pole, RootPair::RealPair { .. }) || matches!(geometry.zero, RootPair::RealPair { .. }) {
            real_rows.push(index);
        }
    }
    let status = if metrics.valid_conjugate {
        "PACKED_CONJUGATE"
    } else {
        "REFUSED_REAL_ROOT_ROW"
    };
    let curve = (0..freqs.len())
        .map(|index| {
            let rows = metrics.packed.interpolate_biquad(0.0, 0.0);
            let (re, im) = biquad_cascade_complex(&rows, freqs[index], STAGE_SR);
            json!({
                "freq_hz": freqs[index],
                "target_re": target[index].0,
                "target_im": target[index].1,
                "packed_re": re,
                "packed_im": im,
                "target_mag_db": target_db[index],
                "packed_mag_db": 20.0 * re.hypot(im).max(1.0e-12).log10(),
                "phase_error_rad": wrap_pi(im.atan2(re) - target[index].1.atan2(target[index].0)),
            })
        })
        .collect::<Vec<_>>();
    let output = json!({
        "tool": "fit-complex-candidates",
        "tool_version": 1,
        "runtime_sr_hz": STAGE_SR,
        "source": input.get("source").cloned().unwrap_or(Value::Null),
        "fit_input": Path::new(input_path).to_string_lossy(),
        "objective": {
            "magnitude_error": "RMS dB",
            "phase_error": "wrapped RMS radians",
            "phase_weight": PHASE_WEIGHT,
            "quantization": "every trial is words_from_roots -> PackedCorners::interpolate_biquad",
            "gain_policy": "absolute target magnitude retained; SCALE is searched within the packed range",
        },
        "status": status,
        "representability": {
            "conjugate_editor": metrics.valid_conjugate,
            "real_root_rows": real_rows,
            "body240": false,
            "body240_reason": "one measured response is one authored corner; four-corner registration is a separate explicit step",
        },
        "fit": {
            "magnitude_rms_db": metrics.magnitude_rms_db,
            "phase_rms_rad": metrics.phase_rms_rad,
            "magnitude_max_db": metrics.magnitude_max_db,
            "objective": metrics.cost,
            "max_pole_radius": metrics.max_pole_radius,
            "sampled_stability": metrics.max_pole_radius < 1.0,
        },
        "stage_order": "fitter-owned single-corner order; no cross-corner lane correspondence asserted",
        "continuous_seed_params": value_params(&params),
        "stages": value_stages(&metrics),
        "curve": curve,
    });
    std::fs::write(output_path, serde_json::to_string_pretty(&output).unwrap() + "\n")
        .unwrap_or_else(|error| fail(format!("write {output_path}: {error}")));
    println!(
        "fit {input_path}: {status} mag_rms {:.3} dB phase_rms {:.4} rad max_r {:.6}",
        metrics.magnitude_rms_db, metrics.phase_rms_rad, metrics.max_pole_radius
    );
}
