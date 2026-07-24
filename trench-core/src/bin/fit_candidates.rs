#![recursion_limit = "512"]
use trench_core::arma::{
    fit_corner_from_magnitude, fit_corner_profiled_with_report, peak_normalize_curve_db,
    PackedRefinementReport, ResidualLaneBand, MACRO_SMOOTHING_OCTAVES,
    PROFILER_HARD_CEILING_DB, PROFILER_HARD_CEILING_PENALTY_WEIGHT,
    PROFILER_TARGET_REFERENCE_DB, YW_DAMPING_SCALE, YW_SHARP_RADIUS_MAX,
};
use trench_core::cascade::{NUM_COEFFS, NUM_STAGES};
use trench_core::minifloat::{encode, stage_words_to_biquad};
use trench_core::response::biquad_cascade_complex;
use trench_core::stage_law::{
    geometry_from_words, words_from_roots, RootPair, StageRoots, STAGE_SR,
};
const POLE_R_MAX: f64 = 0.9999;
fn fail(msg: &str) -> ! {
    eprintln!("REFUSED: {msg}");
    std::process::exit(1);
}
const RIDGE_SEP_OCT: f64 = 0.5;
const RIDGE_ZERO_R_GAP: f64 = 0.05;
#[derive(Clone, Copy)]
struct LaneBox {
    law: &'static str,
    hz: (f64, f64),
    r: (f64, f64),
}
const ANATOMY: [LaneBox; 6] = [
    LaneBox {
        law: "low_zero_sub_cut",
        hz: (60.0, 400.0),
        r: (0.90, 0.99),
    },
    LaneBox {
        law: "local_peak_notch",
        hz: (150.0, 1000.0),
        r: (0.93, 0.995),
    },
    LaneBox {
        law: "local_peak_notch",
        hz: (400.0, 2500.0),
        r: (0.93, 0.995),
    },
    LaneBox {
        law: "local_peak_notch",
        hz: (900.0, 5000.0),
        r: (0.93, 0.995),
    },
    LaneBox {
        law: "local_peak_notch",
        hz: (2000.0, 9000.0),
        r: (0.93, 0.995),
    },
    LaneBox {
        law: "high_zero_cliff",
        hz: (2500.0, 9000.0),
        r: (0.88, 0.98),
    },
];
fn lane_roots(li: usize, p: &[f64; 4]) -> StageRoots {
    let b = ANATOMY[li];
    let pole_hz = p[0].clamp(b.hz.0, b.hz.1);
    let pole_r = p[1].clamp(b.r.0, b.r.1);
    match b.law {
        "local_peak_notch" => StageRoots {
            pole_hz,
            pole_r,
            zero_hz: pole_hz,
            zero_r: p[2].clamp(0.0, pole_r - RIDGE_ZERO_R_GAP),
            scale: p[3].clamp(0.02, 4.0),
        },
        "low_zero_sub_cut" => StageRoots {
            pole_hz,
            pole_r,
            zero_hz: p[2].clamp(20.0, pole_hz / 2f64.powf(RIDGE_SEP_OCT)),
            zero_r: 0.99,
            scale: p[3].clamp(0.02, 4.0),
        },
        _ => StageRoots {
            pole_hz,
            pole_r,
            zero_hz: p[2].clamp(pole_hz * 2f64.powf(RIDGE_SEP_OCT), 18_000.0),
            zero_r: 0.93,
            scale: p[3].clamp(0.02, 4.0),
        },
    }
}
fn cascade_db(lanes: &[[f64; 4]; 6], freqs: &[f64], out: &mut [f64]) {
    let mut rows = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
    for (li, p) in lanes.iter().enumerate() {
        rows[li] = lane_roots(li, p).biquad();
    }
    for (i, &f) in freqs.iter().enumerate() {
        let (re, im) = biquad_cascade_complex(&rows, f, STAGE_SR);
        out[i] = 10.0 * (re * re + im * im + 1e-30).log10();
    }
}
fn objective(lanes: &[[f64; 4]; 6], freqs: &[f64], dbs: &[f64], buf: &mut [f64]) -> f64 {
    cascade_db(lanes, freqs, buf);
    let mut acc = 0.0;
    for (got, want) in buf.iter().zip(dbs) {
        let e = got - want;
        acc += e * e;
    }
    acc / freqs.len() as f64
}
const PEAK_W: f64 = 4.0;
fn peak_weights(dbs: &[f64]) -> Vec<f64> {
    let mut sorted: Vec<f64> = dbs.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let med = sorted[sorted.len() / 2];
    let max = sorted[sorted.len() - 1];
    let span = (max - med).max(1e-6);
    dbs.iter()
        .map(|&d| 1.0 + PEAK_W * ((d - med) / span).clamp(0.0, 1.0))
        .collect()
}
fn formant_roots(p: &[f64; 5]) -> StageRoots {
    let zero_r = p[3].clamp(0.0, 0.98);
    let parked = zero_r < 0.05;
    StageRoots {
        pole_hz: p[0].clamp(60.0, 9000.0),
        pole_r: p[1].clamp(0.93, 0.995),
        zero_hz: if parked {
            0.0
        } else {
            p[2].clamp(30.0, 18_000.0)
        },
        zero_r: if parked { 0.0 } else { zero_r },
        scale: p[4].clamp(0.02, 4.0),
    }
}
fn formant_objective(
    lanes: &[[f64; 5]; 6],
    freqs: &[f64],
    dbs: &[f64],
    w: &[f64],
    buf: &mut [f64],
) -> f64 {
    let mut rows = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
    for (li, p) in lanes.iter().enumerate() {
        rows[li] = formant_roots(p).biquad();
    }
    for (i, &f) in freqs.iter().enumerate() {
        let (re, im) = biquad_cascade_complex(&rows, f, STAGE_SR);
        buf[i] = 10.0 * (re * re + im * im + 1e-30).log10();
    }
    let mut acc = 0.0;
    let mut wsum = 0.0;
    for i in 0..freqs.len() {
        let e = buf[i] - dbs[i];
        acc += w[i] * e * e;
        wsum += w[i];
    }
    acc / wsum
}
fn extrema(freqs: &[f64], dbs: &[f64], maxima: bool, count: usize, sep_oct: f64) -> Vec<f64> {
    let mut cands: Vec<(f64, f64)> = Vec::new();
    for i in 1..freqs.len() - 1 {
        let hit = if maxima {
            dbs[i] > dbs[i - 1] && dbs[i] >= dbs[i + 1]
        } else {
            dbs[i] < dbs[i - 1] && dbs[i] <= dbs[i + 1]
        };
        if hit && freqs[i] >= 60.0 && freqs[i] <= 9000.0 {
            cands.push((dbs[i], freqs[i]));
        }
    }
    if maxima {
        cands.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    } else {
        cands.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
    }
    let mut picked: Vec<f64> = Vec::new();
    for (_, hz) in cands {
        if picked.iter().all(|&p| (hz / p).log2().abs() >= sep_oct) {
            picked.push(hz);
            if picked.len() == count {
                break;
            }
        }
    }
    picked
}
fn formant_fit(freqs: &[f64], dbs: &[f64]) -> [StageRoots; 6] {
    let peaks = extrema(freqs, dbs, true, 6, 0.3);
    let valleys = extrema(freqs, dbs, false, 6, 0.3);
    let w = peak_weights(dbs);
    let mut lanes: [[f64; 5]; 6] = [[0.0; 5]; 6];
    for li in 0..6 {
        let ph = peaks
            .get(li)
            .copied()
            .unwrap_or(200.0 * 2f64.powi(li as i32));
        let (zh, zr) = match valleys.get(li) {
            Some(&v) => (v, 0.85),
            None => (1000.0, 0.0),
        };
        lanes[li] = [ph, 0.97, zh, zr, 1.0];
    }
    let mut buf = vec![0.0f64; freqs.len()];
    let align = |lanes: &mut [[f64; 5]; 6], buf: &mut [f64]| {
        let mut rows = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
        for (li, p) in lanes.iter().enumerate() {
            rows[li] = formant_roots(p).biquad();
        }
        let mut off = 0.0;
        for (i, &f) in freqs.iter().enumerate() {
            let (re, im) = biquad_cascade_complex(&rows, f, STAGE_SR);
            buf[i] = 10.0 * (re * re + im * im + 1e-30).log10();
            off += dbs[i] - buf[i];
        }
        let per = 10f64.powf(off / freqs.len() as f64 / (20.0 * 6.0));
        for l in lanes.iter_mut() {
            l[4] = (l[4] * per).clamp(0.02, 4.0);
        }
    };
    align(&mut lanes, &mut buf);
    let mut best = formant_objective(&lanes, freqs, dbs, &w, &mut buf);
    let mut oct_step = 0.4f64;
    let mut r_step = 0.02f64;
    let mut db_step = 3.0f64;
    for _round in 0..7 {
        let mut improved = true;
        while improved {
            improved = false;
            for li in 0..6 {
                for pi in 0..5 {
                    for dir in [1.0f64, -1.0] {
                        let mut trial = lanes;
                        match pi {
                            0 => trial[li][0] *= 2f64.powf(oct_step * dir),
                            1 => trial[li][1] += r_step * dir,
                            2 => trial[li][2] *= 2f64.powf(oct_step * dir),
                            3 => trial[li][3] += r_step * 2.0 * dir,
                            _ => trial[li][4] *= 10f64.powf(db_step * dir / 20.0),
                        }
                        let cost = formant_objective(&trial, freqs, dbs, &w, &mut buf);
                        if cost + 1e-9 < best {
                            best = cost;
                            lanes = trial;
                            improved = true;
                        }
                    }
                }
            }
        }
        align(&mut lanes, &mut buf);
        best = formant_objective(&lanes, freqs, dbs, &w, &mut buf);
        oct_step *= 0.5;
        r_step *= 0.5;
        db_step *= 0.5;
    }
    let mut out = [StageRoots::IDENTITY; 6];
    for li in 0..6 {
        out[li] = formant_roots(&lanes[li]);
    }
    out
}
fn seed_peaks(freqs: &[f64], dbs: &[f64]) -> Vec<f64> {
    let mut cands: Vec<(f64, f64)> = Vec::new();
    for i in 1..freqs.len() - 1 {
        if dbs[i] > dbs[i - 1] && dbs[i] >= dbs[i + 1] && freqs[i] >= 150.0 && freqs[i] <= 9000.0 {
            cands.push((dbs[i], freqs[i]));
        }
    }
    cands.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    let mut picked: Vec<f64> = Vec::new();
    for (_, hz) in cands {
        if picked
            .iter()
            .all(|&p| (hz / p).log2().abs() >= RIDGE_SEP_OCT)
        {
            picked.push(hz);
            if picked.len() == 4 {
                break;
            }
        }
    }
    let defaults = [400.0, 900.0, 2000.0, 4500.0];
    for d in defaults {
        if picked.len() < 4
            && picked
                .iter()
                .all(|&p| (d / p).log2().abs() >= RIDGE_SEP_OCT)
        {
            picked.push(d);
        }
    }
    picked.sort_by(|a, b| a.partial_cmp(b).unwrap());
    picked
}
fn anatomy_fit(freqs: &[f64], dbs: &[f64]) -> [StageRoots; 6] {
    let peaks = seed_peaks(freqs, dbs);
    let mut lanes: [[f64; 4]; 6] = [[0.0; 4]; 6];
    lanes[0] = [120.0, 0.95, 50.0, 1.0];
    for (k, &hz) in peaks.iter().enumerate() {
        let b = ANATOMY[1 + k];
        lanes[1 + k] = [hz.clamp(b.hz.0, b.hz.1), 0.97, 0.6, 1.0];
    }
    lanes[5] = [4000.0, 0.93, 12_000.0, 1.0];
    let mut buf = vec![0.0f64; freqs.len()];
    let align = |lanes: &mut [[f64; 4]; 6], buf: &mut [f64]| {
        cascade_db(lanes, freqs, buf);
        let off: f64 = buf.iter().zip(dbs).map(|(g, w)| w - g).sum::<f64>() / freqs.len() as f64;
        let per = 10f64.powf(off / (20.0 * 6.0));
        for l in lanes.iter_mut() {
            l[3] = (l[3] * per).clamp(0.02, 4.0);
        }
    };
    align(&mut lanes, &mut buf);
    let mut best = objective(&lanes, freqs, dbs, &mut buf);
    let mut oct_step = 0.4f64;
    let mut r_step = 0.02f64;
    let mut db_step = 3.0f64;
    for _round in 0..7 {
        let mut improved = true;
        while improved {
            improved = false;
            for li in 0..6 {
                for pi in 0..4 {
                    for dir in [1.0f64, -1.0] {
                        let mut trial = lanes;
                        match pi {
                            0 => trial[li][0] *= 2f64.powf(oct_step * dir),
                            1 => trial[li][1] += r_step * dir,
                            2 => {
                                if ANATOMY[li].law == "local_peak_notch" {
                                    trial[li][2] += r_step * dir;
                                } else {
                                    trial[li][2] *= 2f64.powf(oct_step * dir);
                                }
                            }
                            _ => trial[li][3] *= 10f64.powf(db_step * dir / 20.0),
                        }
                        let cost = objective(&trial, freqs, dbs, &mut buf);
                        if cost + 1e-9 < best {
                            best = cost;
                            lanes = trial;
                            improved = true;
                        }
                    }
                }
            }
        }
        align(&mut lanes, &mut buf);
        best = objective(&lanes, freqs, dbs, &mut buf);
        oct_step *= 0.5;
        r_step *= 0.5;
        db_step *= 0.5;
    }
    let mut out = [StageRoots::IDENTITY; 6];
    for li in 0..6 {
        out[li] = lane_roots(li, &lanes[li]);
    }
    out
}
fn main() {
    let mut args: Vec<String> = std::env::args().collect();
    let anatomy = args.iter().any(|a| a == "--anatomy");
    let formant = args.iter().any(|a| a == "--formant");
    let mut poles_first = args.iter().any(|a| a == "--poles-first");
    let profile_plan = args.iter().position(|a| a == "--stage-plan").map(|index| {
        if index + 1 >= args.len() {
            fail("--stage-plan requires a registered-lanes JSON path");
        }
        let path = args.remove(index + 1);
        args.remove(index);
        poles_first = true;
        path
    });
    args.retain(|a| a != "--anatomy" && a != "--formant" && a != "--poles-first");
    let (inp, outp) = match &args[..] {
        [_, i, o] => (i.clone(), o.clone()),
        _ => {
            eprintln!("usage: fit-candidates <in.tf.json> <out.json> [--poles-first|--stage-plan registered.json|--formant|--anatomy]");
            std::process::exit(2);
        }
    };
    let v: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(&inp).unwrap_or_else(|e| fail(&format!("read {inp}: {e}"))),
    )
    .unwrap_or_else(|e| fail(&format!("{inp} is not JSON: {e}")));
    let arr = |key: &str| -> Vec<f64> {
        v.get(key)
            .and_then(|a| a.as_array())
            .unwrap_or_else(|| {
                fail(&format!(
                    "{inp}: missing array '{key}' (expected tf_ingest TF JSON)"
                ))
            })
            .iter()
            .map(|x| x.as_f64().unwrap_or(f64::NAN))
            .collect()
    };
    let freqs = arr("freqs_hz");
    let dbs = arr("mag_db");
    if freqs.len() != dbs.len() || freqs.len() < 2 {
        fail("freqs_hz/mag_db must be equal-length arrays with at least 2 points");
    }
    for (i, (&f, &d)) in freqs.iter().zip(&dbs).enumerate() {
        if !f.is_finite() || !d.is_finite() {
            fail(&format!("nonfinite TF data at index {i}"));
        }
        if f <= 0.0 {
            fail(&format!("frequency {f} at index {i} must be > 0"));
        }
        if i > 0 && f <= freqs[i - 1] {
            fail(&format!(
                "frequencies must be strictly ascending (index {i}: {} -> {f})",
                freqs[i - 1]
            ));
        }
    }
    let raw_curve: Vec<(f64, f64)> = freqs.iter().copied().zip(dbs.iter().copied()).collect();
    let (input_curve, target_peak_db, target_alignment_offset_db) =
        peak_normalize_curve_db(&raw_curve).unwrap_or_else(|| {
            fail("target peak normalization failed: no finite sample in the profiler fit band")
        });
    let aligned_dbs: Vec<f64> = input_curve.iter().map(|(_, db)| *db).collect();
    let profile_bands = profile_plan.as_ref().map(|path| {
        let plan_doc: serde_json::Value = serde_json::from_str(
            &std::fs::read_to_string(path)
                .unwrap_or_else(|e| fail(&format!("read stage plan {path}: {e}"))),
        )
        .unwrap_or_else(|e| fail(&format!("{path} is not JSON: {e}")));
        let stages = plan_doc
            .get("stage_plan")
            .and_then(|value| value.as_array())
            .unwrap_or_else(|| fail(&format!("{path}: missing stage_plan array")));
        if stages.len() != NUM_STAGES {
            fail(&format!(
                "{path}: stage_plan must contain exactly {NUM_STAGES} lanes"
            ));
        }
        let source = |slot: usize| {
            stages[slot]
                .get("analysis")
                .and_then(|value| value.get("source"))
                .and_then(|value| value.as_str())
                .unwrap_or_else(|| {
                    fail(&format!(
                        "{path}: stage_plan[{slot}].analysis.source missing"
                    ))
                })
        };
        if source(0) != "macro_body" || (1..NUM_STAGES).any(|slot| source(slot) != "residual") {
            fail(&format!(
                "{path}: profiler ownership must be slot 0 = macro_body, slots 1..5 = residual"
            ));
        }
        let read_band = |slot: usize, key: &str| -> (f64, f64) {
            let values = stages[slot]
                .get("analysis")
                .and_then(|value| value.get(key))
                .and_then(|value| value.as_array())
                .unwrap_or_else(|| {
                    fail(&format!(
                        "{path}: stage_plan[{slot}].analysis.{key} missing"
                    ))
                });
            if values.len() != 2 {
                fail(&format!(
                    "{path}: stage_plan[{slot}].analysis.{key} must be [minimum, maximum]"
                ));
            }
            let lo = values[0].as_f64().unwrap_or(f64::NAN);
            let hi = values[1].as_f64().unwrap_or(f64::NAN);
            if !(lo.is_finite() && hi.is_finite() && 55.0 <= lo && lo < hi && hi <= 10_500.0) {
                fail(&format!(
                    "{path}: invalid stage_plan[{slot}].analysis.{key} [{lo}, {hi}]"
                ));
            }
            (lo, hi)
        };
        let read_radius = |slot: usize, key: &str, maximum: f64| -> (f64, f64) {
            let values = stages[slot]
                .get("analysis")
                .and_then(|value| value.get(key))
                .and_then(|value| value.as_array())
                .unwrap_or_else(|| {
                    fail(&format!(
                        "{path}: stage_plan[{slot}].analysis.{key} missing"
                    ))
                });
            if values.len() != 2 {
                fail(&format!(
                    "{path}: stage_plan[{slot}].analysis.{key} must be [minimum, maximum]"
                ));
            }
            let lo = values[0].as_f64().unwrap_or(f64::NAN);
            let hi = values[1].as_f64().unwrap_or(f64::NAN);
            if !(lo.is_finite() && hi.is_finite() && 0.0 <= lo && lo <= hi && hi <= maximum) {
                fail(&format!(
                    "{path}: invalid stage_plan[{slot}].analysis.{key} [{lo}, {hi}]"
                ));
            }
            (lo, hi)
        };
        std::array::from_fn(|index| ResidualLaneBand {
            pole_hz: read_band(index + 1, "pole_band_hz"),
            zero_hz: read_band(index + 1, "zero_band_hz"),
            pole_r: read_radius(index + 1, "pole_radius", YW_SHARP_RADIUS_MAX),
            zero_r: read_radius(index + 1, "zero_radius", 0.995),
        })
    });
    let kernel_to_words = |kernel: &[f64; 5]| -> [u16; 5] {
        let [c0, c1, c2, c3, c4] = *kernel;
        [
            encode((c0 - c1) / 4.0),
            encode(c1),
            encode((c2 - c3) / 4.0),
            encode(c3),
            encode(c4 / 4.0),
        ]
    };
    let mut refinement_report: Option<PackedRefinementReport> = None;
    let words_list: Vec<[u16; 5]> = if poles_first {
        let corner = if let Some(bands) = &profile_bands {
            let (corner, report) = fit_corner_profiled_with_report(&input_curve, STAGE_SR, bands)
                .unwrap_or_else(|| fail("packed-domain profiled fit returned None"));
            refinement_report = Some(report);
            Some(corner)
        } else {
            trench_core::arma::fit_corner_poles_first(&input_curve, STAGE_SR)
        }
        .unwrap_or_else(|| fail("poles-first acoustic profiler returned None (missing feature in an authored band or degenerate fit)"));
        corner.iter().map(kernel_to_words).collect()
    } else if formant {
        formant_fit(&freqs, &aligned_dbs)
            .iter()
            .map(words_from_roots)
            .collect()
    } else if anatomy {
        anatomy_fit(&freqs, &aligned_dbs)
            .iter()
            .map(words_from_roots)
            .collect()
    } else {
        let corner = fit_corner_from_magnitude(&input_curve, STAGE_SR)
            .unwrap_or_else(|| fail("fit_corner_from_magnitude returned None (degenerate fit)"));
        corner.iter().map(kernel_to_words).collect()
    };
    if let Some(bands) = &profile_bands {
        for (index, band) in bands.iter().enumerate() {
            let slot = index + 1;
            let geometry = geometry_from_words(words_list[slot]);
            let (pole_hz, pole_r) = match geometry.pole {
                RootPair::Conjugate { hz, r } => (hz, r),
                _ => fail(&format!(
                    "packed slot {slot} lost its conjugate pole topology"
                )),
            };
            let (zero_hz, zero_r) = match geometry.zero {
                RootPair::Conjugate { hz, r } => (hz, r),
                _ => fail(&format!(
                    "packed slot {slot} lost its conjugate zero topology"
                )),
            };
            if !(band.pole_hz.0 <= pole_hz
                && pole_hz <= band.pole_hz.1
                && band.pole_r.0 <= pole_r
                && pole_r <= band.pole_r.1)
            {
                fail(&format!(
                    "packed slot {slot} pole escaped Stage Plan bounds: {pole_hz:.3} Hz r={pole_r:.6}"
                ));
            }
            if !(band.zero_hz.0 <= zero_hz
                && zero_hz <= band.zero_hz.1
                && band.zero_r.0 <= zero_r
                && zero_r <= band.zero_r.1)
            {
                fail(&format!(
                    "packed slot {slot} zero escaped Stage Plan bounds: {zero_hz:.3} Hz r={zero_r:.6}"
                ));
            }
        }
    }
    let mut stages_json = Vec::with_capacity(NUM_STAGES);
    let mut rows = [[0.0f64; NUM_COEFFS]; NUM_STAGES];
    for (si, &words) in words_list.iter().enumerate() {
        rows[si] = stage_words_to_biquad(words);
        let g = geometry_from_words(words);
        let gate = |p: &RootPair, side: &str, rmax: f64| match p {
            RootPair::Conjugate { hz, r } => {
                if !hz.is_finite() || !r.is_finite() || *r > rmax {
                    fail(&format!("stage {si} {side}: conjugate hz={hz} r={r} outside contract (r_max {rmax})"));
                }
            }
            RootPair::RealPair { root_a, root_b } => {
                if !root_a.is_finite()
                    || !root_b.is_finite()
                    || (side == "pole" && (root_a.abs() > rmax || root_b.abs() > rmax))
                {
                    fail(&format!(
                        "stage {si} {side}: real roots [{root_a}, {root_b}] outside contract"
                    ));
                }
            }
            RootPair::Degenerate => {}
        };
        gate(&g.pole, "pole", POLE_R_MAX);
        gate(&g.zero, "zero", f64::INFINITY);
        if !g.scale.is_finite() || g.scale < 0.0 || g.scale > 4.0 {
            fail(&format!("stage {si}: SCALE {} outside [0, 4]", g.scale));
        }
        let pair_json = |p: &RootPair| match p {
            RootPair::Conjugate { hz, r } => (serde_json::json!({ "hz": hz, "r": r }), "conjugate"),
            RootPair::RealPair { root_a, root_b } => (
                serde_json::json!({ "real_roots": [root_a, root_b] }),
                "real_pair",
            ),
            RootPair::Degenerate => (serde_json::json!({ "hz": 0.0, "r": 0.0 }), "degenerate"),
        };
        let (pole, pole_t) = pair_json(&g.pole);
        let (zero, zero_t) = pair_json(&g.zero);
        let identity = matches!(g.pole, RootPair::Degenerate)
            && matches!(g.zero, RootPair::Degenerate)
            && g.scale == 1.0;
        stages_json.push(serde_json::json!({
            "topology": { "pole": pole_t, "zero": zero_t },
            "state": if identity { "identity" } else { "active" },
            "pole": pole,
            "zero": zero,
            "scale": g.scale,
            "packed_words": words,
        }));
    }
    let mut sum2 = 0.0f64;
    let mut mx = 0.0f64;
    for (&f, &d) in freqs.iter().zip(&aligned_dbs) {
        let (re, im) = biquad_cascade_complex(&rows, f, STAGE_SR);
        let got = 10.0 * (re * re + im * im + 1e-30).log10();
        let e = (got - d).abs();
        sum2 += e * e;
        mx = mx.max(e);
    }
    let rms = (sum2 / freqs.len() as f64).sqrt();
    let out = serde_json::json!({
        "tool": "fit-candidates",
        "tool_version": 6,
        "fitter": if poles_first {
            "acoustic profiler: peak-aligned shape fit + macro peel + five band-owned Yule-Walker residual lanes + explicit zeros + packed-runtime bounded refinement"
        } else if formant {
            "T4 formant fit: poles chase peaks, zeros untethered (valleys or parked), peak-weighted cost"
        } else if anatomy {
            "anatomy-constrained pattern search over stage_law (T3 sub-cut / 4x T1 ridge / T2 cliff)"
        } else {
            "arma::fit_corner_from_magnitude (trench-core)"
        },
        "anatomy": anatomy,
        "formant": formant,
        "profile_stage_plan": profile_plan,
        "runtime_sr_hz": STAGE_SR,
        "n_points": freqs.len(),
        "target_alignment": {
            "method": "peak_normalize",
            "reference_db": PROFILER_TARGET_REFERENCE_DB,
            "source_peak_db_in_fit_band": target_peak_db,
            "applied_offset_db": target_alignment_offset_db,
            "fit_gain_policy": "target acoustic gain excluded from RMS; preset amp volume/patchcord owns physical level",
        },
        "stages": stages_json,
        "fit": {
            "residual_rms_db": rms,
            "residual_max_db": mx,
            "computed_by": "response::biquad_cascade_complex over the quantized packed words against the peak-aligned target",
            "pole_pass": if poles_first { "one fitted macro-body stage; 24th-order Yule-Walker over measured-minus-macro residual; five residual formant centres; authored pole bands when a Stage Plan is supplied; frequencies and radii locked before zero fitting" } else { "mode-specific" },
            "zero_pass": if poles_first { "inverted residual feature extraction; authored zero bands when a Stage Plan is supplied, otherwise three inter-formant valleys plus low/high residual basins; centres fixed; depth-only deterministic solve" } else { "mode-specific" },
            "macro_smoothing_octaves": if poles_first { MACRO_SMOOTHING_OCTAVES } else { 0.0 },
            "yw_pole_damping_scale": if poles_first { YW_DAMPING_SCALE } else { 1.0 },
            "yw_pole_radius_cap": if poles_first { YW_SHARP_RADIUS_MAX } else { 0.0 },
            "packed_refinement": refinement_report.map(|report| serde_json::json!({
                "algorithm": "bounded deterministic coordinate descent over packed/runtime-decoded response",
                "grid": "256 logarithmic rows from 55 Hz to 10.5 kHz",
                "weights": "0.2x outside 60 Hz..10 kHz; 2x from 1..5 kHz; additional 5x for positive shape error at target-local peaks >= 2 dB",
                "target_alignment": "candidate and target peaks are aligned for shape cost; physical target gain is excluded",
                "hard_ceiling_db": PROFILER_HARD_CEILING_DB,
                "hard_ceiling_penalty_weight": PROFILER_HARD_CEILING_PENALTY_WEIGHT,
                "hard_ceiling_grid": "512 logarithmic rows from 20 Hz to 0.499 * runtime sample rate",
                "acceptance": "weighted shape objective (RMS plus hard-ceiling penalty) must fall and plain shape RMS may not exceed the packed seed; SCALE is not searched",
                "evaluations": report.evaluations,
                "weighted_objective_before_db": report.weighted_objective_before_db,
                "weighted_objective_after_db": report.weighted_objective_after_db,
                "weighted_rms_before_db": report.weighted_rms_before_db,
                "weighted_rms_after_db": report.weighted_rms_after_db,
                "plain_rms_before_db": report.plain_rms_before_db,
                "plain_rms_after_db": report.plain_rms_after_db,
                "max_overshoot_before_db": report.max_overshoot_before_db,
                "max_overshoot_after_db": report.max_overshoot_after_db,
                "hard_ceiling_penalty_before": report.hard_ceiling_penalty_before,
                "hard_ceiling_penalty_after": report.hard_ceiling_penalty_after,
                "max_ceiling_excess_before_db": report.max_ceiling_excess_before_db,
                "max_ceiling_excess_after_db": report.max_ceiling_excess_after_db,
            })),
        },
    });
    std::fs::write(&outp, serde_json::to_string_pretty(&out).unwrap())
        .unwrap_or_else(|e| fail(&format!("write {outp}: {e}")));
    println!(
        "fit {inp}: {} stages, peak-aligned residual rms {rms:.2} dB max {mx:.2} dB (target offset {target_alignment_offset_db:+.2} dB)",
        NUM_STAGES
    );
}
