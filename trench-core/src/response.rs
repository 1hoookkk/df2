//! Response-first authoring contract.
//!
//! The creative object is the full cascade magnitude surface over Morph x Q.
//! Stage rows are the packed realization of that target, not the design schema.

use crate::cartridge::CornerData;
use crate::cascade::NUM_COEFFS;
use crate::compiler;
use crate::minifloat::{kernel_to_biquad, PackedCorners};

const EPS: f64 = 1.0e-30;
const CORNER_LABELS: [&str; 4] = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
const AUDIT_GRID: usize = 5;
const AUDIT_BINS: usize = 512;
const CROWN_MIN_DB: f64 = -3.0;
const CROWN_MAX_DB: f64 = 36.0;
const CROWN_PARITY_MAX_DB: f64 = 30.0;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BandSpec {
    pub name: &'static str,
    pub lo_hz: f64,
    pub hi_hz: f64,
}

pub const RESPONSE_BANDS: [BandSpec; 4] = [
    BandSpec {
        name: "low",
        lo_hz: 20.0,
        hi_hz: 200.0,
    },
    BandSpec {
        name: "body",
        lo_hz: 200.0,
        hi_hz: 1_200.0,
    },
    BandSpec {
        name: "bite",
        lo_hz: 1_200.0,
        hi_hz: 5_500.0,
    },
    BandSpec {
        name: "air",
        lo_hz: 5_500.0,
        hi_hz: 16_000.0,
    },
];

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ResponsePoint {
    pub freq_hz: f64,
    pub db: f64,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ResponseCurve {
    pub sample_rate_hz: f64,
    pub points: Vec<ResponsePoint>,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct BandLevel {
    pub name: String,
    pub db: f64,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ResponseSummary {
    pub label: String,
    pub peak_db: f64,
    pub centroid_hz: f64,
    pub slope_db_per_octave: f64,
    pub bands: Vec<BandLevel>,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AxisMotion {
    pub axis: String,
    pub from: String,
    pub to: String,
    pub rms_delta_db: f64,
    pub centroid_delta_hz: f64,
    pub peak_delta_db: f64,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct PackingAudit {
    pub rms_db: f64,
    pub peak_db: f64,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ResponseSurfaceAudit {
    pub contract: String,
    pub sample_rate_hz: f64,
    pub grid_points: usize,
    pub corners: Vec<ResponseSummary>,
    pub motion: AxisMotion,
    pub q: AxisMotion,
    pub packing: PackingAudit,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct CascadeBandLevels {
    pub low_db: f64,
    pub mid_db: f64,
    pub high_db: f64,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct BodyAuditSample {
    pub label: String,
    pub morph: f64,
    pub q: f64,
    pub finite: bool,
    pub stable: bool,
    pub max_pole_radius: f64,
    pub crown_db: f64,
    pub floor_db: f64,
    pub span_db: f64,
    pub bands: CascadeBandLevels,
    pub peak_count: usize,
    pub valley_count: usize,
    pub total_gain_product: f64,
    pub total_gain_db: f64,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct BodyAuditWarning {
    pub label: String,
    pub sample: String,
    pub detail: String,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct BodyAuditGate {
    pub pass: bool,
    pub failures: Vec<String>,
    pub measured_crown_min_db: f64,
    pub measured_crown_max_db: f64,
    pub measured_crown_parity_db: f64,
    pub allowed_crown_min_db: f64,
    pub allowed_crown_max_db: f64,
    pub allowed_crown_parity_db: f64,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct BodyAuditRanking {
    pub hard_gate_pass: bool,
    pub crown_parity_db: f64,
    pub usable_headroom_db: f64,
    pub morph_contrast_db: f64,
    pub q_bloom_db: f64,
    pub peak_valley_clarity: f64,
    pub stability_margin: f64,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct BodyCascadeAudit {
    pub contract: String,
    pub body_bytes: usize,
    pub sha256_hint: String,
    pub sample_rate_hz: f64,
    pub response_bins: usize,
    pub samples: Vec<BodyAuditSample>,
    pub gate: BodyAuditGate,
    pub warnings: Vec<BodyAuditWarning>,
    pub ranking: BodyAuditRanking,
}

pub fn log_frequency_grid(lo_hz: f64, hi_hz: f64, points: usize) -> Vec<f64> {
    let points = points.max(2);
    let lo = lo_hz.max(1.0);
    let hi = hi_hz.max(lo + 1.0);
    (0..points)
        .map(|i| {
            let t = i as f64 / (points - 1) as f64;
            lo * (hi / lo).powf(t)
        })
        .collect()
}

pub fn compile_root_body_and_audit(
    params: &[f64],
) -> Result<([u8; compiler::BODY_LEN], BodyCascadeAudit), String> {
    if params.len() != compiler::PARAM_LEN {
        return Err(format!(
            "expected {} root-domain params, got {}",
            compiler::PARAM_LEN,
            params.len()
        ));
    }
    let body = compiler::pack_body(params);
    let audit = audit_body240(&body)?;
    Ok((body, audit))
}

pub fn audit_body240(bytes: &[u8]) -> Result<BodyCascadeAudit, String> {
    let packed = PackedCorners::from_body_bytes(bytes).map_err(|e| e.to_owned())?;
    let grid = log_frequency_grid(40.0, 16_000.0, AUDIT_BINS);
    let points = audit_points();
    let mut samples = Vec::with_capacity(points.len());
    let mut warnings = Vec::new();
    let mut wrap_hazard = false;

    for ci in 0..4 {
        for si in 0..crate::cascade::NUM_STAGES {
            for wi in 0..crate::cascade::NUM_COEFFS {
                let a = packed.words[0][si][wi] as i32;
                let b = packed.words[1][si][wi] as i32;
                let c = packed.words[2][si][wi] as i32;
                let d = packed.words[3][si][wi] as i32;
                let corner_word = packed.words[ci][si][wi];
                let _ = corner_word;
                if (b - a).abs() > i16::MAX as i32 || (d - c).abs() > i16::MAX as i32 {
                    wrap_hazard = true;
                }
            }
        }
    }

    for (label, morph, q) in points {
        let rows = packed.interpolate_biquad(morph as f32, q as f32);
        let sample = audit_sample(label, morph, q, &rows, &grid, &mut warnings);
        samples.push(sample);
    }

    let finite = samples.iter().all(|s| s.finite);
    let stable = samples.iter().all(|s| s.stable);
    let crown_min = samples
        .iter()
        .map(|s| s.crown_db)
        .fold(f64::INFINITY, f64::min);
    let crown_max = samples
        .iter()
        .map(|s| s.crown_db)
        .fold(f64::NEG_INFINITY, f64::max);
    let crown_parity = crown_max - crown_min;

    let mut failures = Vec::new();
    if bytes.len() != compiler::BODY_LEN {
        failures.push(format!(
            "body is {} bytes, expected {}",
            bytes.len(),
            compiler::BODY_LEN
        ));
    }
    if !finite {
        failures.push("nonfinite response on packed Morph×Q surface".to_owned());
    }
    if !stable {
        failures.push("unstable decoded pole on packed Morph×Q surface".to_owned());
    }
    if wrap_hazard {
        failures.push("i16 packed interpolation wrap hazard".to_owned());
    }
    if crown_min < CROWN_MIN_DB || crown_max > CROWN_MAX_DB {
        failures.push(format!(
            "whole-cascade crown outside band: min {crown_min:.2} dB, max {crown_max:.2} dB, allowed {CROWN_MIN_DB:.2}..{CROWN_MAX_DB:.2} dB"
        ));
    }
    if crown_parity > CROWN_PARITY_MAX_DB {
        failures.push(format!(
            "corner/midpoint crown parity {crown_parity:.2} dB exceeds {CROWN_PARITY_MAX_DB:.2} dB"
        ));
    }

    let morph_contrast = sample_delta(&samples, "M0_Q0", "M100_Q0");
    let q_bloom = sample_delta(&samples, "M0_Q0", "M0_Q100");
    let max_radius = samples
        .iter()
        .map(|s| s.max_pole_radius)
        .fold(0.0, f64::max);
    let peak_valley = samples
        .iter()
        .map(|s| (s.peak_count + s.valley_count) as f64)
        .sum::<f64>()
        / samples.len().max(1) as f64;

    Ok(BodyCascadeAudit {
        contract: "body240-cascade-product-gate-v1: 4 corners × 6 serial SOS, packed interpolation is authority".to_owned(),
        body_bytes: bytes.len(),
        sha256_hint: "".to_owned(),
        sample_rate_hz: compiler::AUTHORING_SR,
        response_bins: grid.len(),
        samples,
        gate: BodyAuditGate {
            pass: failures.is_empty(),
            failures,
            measured_crown_min_db: crown_min,
            measured_crown_max_db: crown_max,
            measured_crown_parity_db: crown_parity,
            allowed_crown_min_db: CROWN_MIN_DB,
            allowed_crown_max_db: CROWN_MAX_DB,
            allowed_crown_parity_db: CROWN_PARITY_MAX_DB,
        },
        warnings,
        ranking: BodyAuditRanking {
            hard_gate_pass: finite && stable && !wrap_hazard && crown_min >= CROWN_MIN_DB && crown_max <= CROWN_MAX_DB && crown_parity <= CROWN_PARITY_MAX_DB,
            crown_parity_db: crown_parity,
            usable_headroom_db: CROWN_MAX_DB - crown_max,
            morph_contrast_db: morph_contrast,
            q_bloom_db: q_bloom,
            peak_valley_clarity: peak_valley,
            stability_margin: 1.0 - max_radius,
        },
    })
}

fn audit_points() -> Vec<(String, f64, f64)> {
    let mut out: Vec<(String, f64, f64)> = vec![
        ("M0_Q0".to_owned(), 0.0, 0.0),
        ("M100_Q0".to_owned(), 1.0, 0.0),
        ("M0_Q100".to_owned(), 0.0, 1.0),
        ("M100_Q100".to_owned(), 1.0, 1.0),
        ("M50_Q0".to_owned(), 0.5, 0.0),
        ("M50_Q100".to_owned(), 0.5, 1.0),
        ("M0_Q50".to_owned(), 0.0, 0.5),
        ("M100_Q50".to_owned(), 1.0, 0.5),
        ("M50_Q50".to_owned(), 0.5, 0.5),
    ];
    for qi in 0..AUDIT_GRID {
        let q = qi as f64 / (AUDIT_GRID - 1) as f64;
        for mi in 0..AUDIT_GRID {
            let m = mi as f64 / (AUDIT_GRID - 1) as f64;
            if !out
                .iter()
                .any(|(_, em, eq)| (*em - m).abs() < 1e-9 && (*eq - q).abs() < 1e-9)
            {
                out.push((
                    format!(
                        "M{:03}_Q{:03}",
                        (m * 100.0).round() as i32,
                        (q * 100.0).round() as i32
                    ),
                    m,
                    q,
                ));
            }
        }
    }
    out
}

fn audit_sample(
    label: String,
    morph: f64,
    q: f64,
    rows: &[[f64; NUM_COEFFS]; crate::cascade::NUM_STAGES],
    grid: &[f64],
    warnings: &mut Vec<BodyAuditWarning>,
) -> BodyAuditSample {
    let mut db = Vec::with_capacity(grid.len());
    for &freq in grid {
        db.push(
            rows.iter()
                .map(|row| biquad_stage_mag_db(row, freq, compiler::AUTHORING_SR))
                .sum::<f64>(),
        );
    }
    let finite = rows.iter().flatten().all(|v| v.is_finite()) && db.iter().all(|v| v.is_finite());
    let mut max_pole_radius = 0.0f64;
    let mut poles = Vec::new();
    let mut total_gain_product = 1.0f64;
    for (si, row) in rows.iter().enumerate() {
        total_gain_product *= row[0].abs().max(EPS);
        let pole = pole_center_radius(row);
        if let Some((hz, radius)) = pole {
            max_pole_radius = max_pole_radius.max(radius);
            poles.push((hz, radius));
            if radius > 0.995 {
                warnings.push(warn(
                    "near-unit pole",
                    &label,
                    format!("stage {} pole radius {:.6}", si + 1, radius),
                ));
            }
        }
        if let Some((zhz, zr)) = zero_center_radius(row) {
            if !(40.0..=16_000.0).contains(&zhz) {
                warnings.push(warn(
                    "remote zero",
                    &label,
                    format!("stage {} zero {:.1} Hz r={:.5}", si + 1, zhz, zr),
                ));
            }
            if let Some((phz, pr)) = pole {
                if (zhz / phz).log2().abs() < 0.06 && (zr - pr).abs() < 0.04 {
                    warnings.push(warn(
                        "near pole-zero cancellation",
                        &label,
                        format!(
                            "stage {} pole {:.1} Hz r={:.5}, zero {:.1} Hz r={:.5}",
                            si + 1,
                            phz,
                            pr,
                            zhz,
                            zr
                        ),
                    ));
                }
            }
        }
    }
    poles.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    for pair in poles.windows(2) {
        if pair[1].0 - pair[0].0 < 200.0 {
            warnings.push(warn(
                "sub-200 Hz collision",
                &label,
                format!("{:.1} Hz and {:.1} Hz", pair[0].0, pair[1].0),
            ));
        }
    }
    let stable = max_pole_radius < 1.0;
    let crown = db.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let floor = db.iter().copied().fold(f64::INFINITY, f64::min);
    let span = crown - floor;
    if span > 90.0 {
        warnings.push(warn(
            "very high response span",
            &label,
            format!("{span:.2} dB"),
        ));
    }
    let bands = CascadeBandLevels {
        low_db: band_average(&db, grid, 40.0, 200.0),
        mid_db: band_average(&db, grid, 200.0, 2_000.0),
        high_db: band_average(&db, grid, 2_000.0, 16_000.0),
    };
    if bands.low_db > bands.mid_db + 12.0 && bands.low_db > bands.high_db + 12.0 {
        warnings.push(warn(
            "excessive low-band dominance",
            &label,
            format!(
                "low {:.2}, mid {:.2}, high {:.2} dB",
                bands.low_db, bands.mid_db, bands.high_db
            ),
        ));
    }
    let (peaks, valleys) = peak_valley_count(&db);
    BodyAuditSample {
        label,
        morph,
        q,
        finite,
        stable,
        max_pole_radius,
        crown_db: crown,
        floor_db: floor,
        span_db: span,
        bands,
        peak_count: peaks,
        valley_count: valleys,
        total_gain_product,
        total_gain_db: 20.0 * total_gain_product.max(EPS).log10(),
    }
}

pub fn kernel_response_curve(
    corner: &CornerData,
    sample_rate_hz: f64,
    grid: &[f64],
) -> ResponseCurve {
    ResponseCurve {
        sample_rate_hz,
        points: grid
            .iter()
            .map(|&freq_hz| ResponsePoint {
                freq_hz,
                db: kernel_cascade_mag_db(corner, freq_hz, sample_rate_hz),
            })
            .collect(),
    }
}

fn warn(label: &str, sample: &str, detail: String) -> BodyAuditWarning {
    BodyAuditWarning {
        label: label.to_owned(),
        sample: sample.to_owned(),
        detail,
    }
}

fn pole_center_radius(row: &[f64; NUM_COEFFS]) -> Option<(f64, f64)> {
    let a1 = row[3];
    let a2 = row[4];
    if !a1.is_finite() || !a2.is_finite() || a2 <= 0.0 {
        return None;
    }
    let r = a2.sqrt();
    if r <= 1e-12 {
        return None;
    }
    let c = (-a1 / (2.0 * r)).clamp(-1.0, 1.0);
    Some((c.acos() * compiler::AUTHORING_SR / std::f64::consts::TAU, r))
}

fn zero_center_radius(row: &[f64; NUM_COEFFS]) -> Option<(f64, f64)> {
    let b0 = row[0];
    let b1 = row[1];
    let b2 = row[2];
    if !b0.is_finite() || !b1.is_finite() || !b2.is_finite() || b0.abs() <= 1e-12 {
        return None;
    }
    let zr2 = b2 / b0;
    if zr2 <= 0.0 {
        return None;
    }
    let r = zr2.sqrt();
    if r <= 1e-12 {
        return None;
    }
    let c = ((b1 / b0) / (-2.0 * r)).clamp(-1.0, 1.0);
    Some((c.acos() * compiler::AUTHORING_SR / std::f64::consts::TAU, r))
}

fn band_average(db: &[f64], grid: &[f64], lo: f64, hi: f64) -> f64 {
    let mut sum = 0.0;
    let mut n = 0usize;
    for (&value, &freq) in db.iter().zip(grid.iter()) {
        if freq >= lo && freq < hi && value.is_finite() {
            sum += value;
            n += 1;
        }
    }
    if n == 0 {
        f64::NAN
    } else {
        sum / n as f64
    }
}

fn peak_valley_count(db: &[f64]) -> (usize, usize) {
    if db.len() < 3 {
        return (0, 0);
    }
    let mut peaks = 0usize;
    let mut valleys = 0usize;
    for i in 1..db.len() - 1 {
        let left = db[i - 1];
        let mid = db[i];
        let right = db[i + 1];
        if !left.is_finite() || !mid.is_finite() || !right.is_finite() {
            continue;
        }
        if mid > left && mid > right && mid - left.min(right) >= 1.5 {
            peaks += 1;
        }
        if mid < left && mid < right && left.max(right) - mid >= 1.5 {
            valleys += 1;
        }
    }
    (peaks, valleys)
}

fn sample_delta(samples: &[BodyAuditSample], a: &str, b: &str) -> f64 {
    let Some(sa) = samples.iter().find(|s| s.label == a) else {
        return 0.0;
    };
    let Some(sb) = samples.iter().find(|s| s.label == b) else {
        return 0.0;
    };
    (sb.crown_db - sa.crown_db).abs()
}

pub fn biquad_response_curve(
    corner: &CornerData,
    sample_rate_hz: f64,
    grid: &[f64],
) -> ResponseCurve {
    ResponseCurve {
        sample_rate_hz,
        points: grid
            .iter()
            .map(|&freq_hz| ResponsePoint {
                freq_hz,
                db: biquad_cascade_mag_db(corner, freq_hz, sample_rate_hz),
            })
            .collect(),
    }
}

pub fn summarize_curve(label: impl Into<String>, curve: &ResponseCurve) -> ResponseSummary {
    let peak_db = curve
        .points
        .iter()
        .map(|p| p.db)
        .fold(f64::NEG_INFINITY, f64::max);
    let centroid_hz = spectral_centroid_hz(curve);
    let slope_db_per_octave = slope_db_per_octave(curve);
    let bands = RESPONSE_BANDS
        .iter()
        .map(|b| BandLevel {
            name: b.name.to_owned(),
            db: average_band_db(curve, b.lo_hz, b.hi_hz),
        })
        .collect();
    ResponseSummary {
        label: label.into(),
        peak_db,
        centroid_hz,
        slope_db_per_octave,
        bands,
    }
}

pub fn audit_kernel_surface(
    corners: &[CornerData; 4],
    sample_rate_hz: f64,
    grid_points: usize,
) -> ResponseSurfaceAudit {
    let hi_hz = (sample_rate_hz * 0.5).min(16_000.0).max(8_000.0);
    let grid = log_frequency_grid(20.0, hi_hz, grid_points);
    let curves: Vec<_> = corners
        .iter()
        .map(|c| kernel_response_curve(c, sample_rate_hz, &grid))
        .collect();
    let summaries: Vec<_> = curves
        .iter()
        .zip(CORNER_LABELS)
        .map(|(curve, label)| summarize_curve(label, curve))
        .collect();
    let packed = PackedCorners::from_corner_data(corners);
    let packed_corners = [
        packed.interpolate(0.0, 0.0),
        packed.interpolate(1.0, 0.0),
        packed.interpolate(0.0, 1.0),
        packed.interpolate(1.0, 1.0),
    ];
    let packed_curves: Vec<_> = packed_corners
        .iter()
        .map(|c| kernel_response_curve(c, sample_rate_hz, &grid))
        .collect();

    ResponseSurfaceAudit {
        contract: "response-surface-v1: author magnitude/motion/Q first; pack stages last"
            .to_owned(),
        sample_rate_hz,
        grid_points: grid.len(),
        corners: summaries,
        motion: axis_motion("morph", 0, 1, &curves),
        q: axis_motion("q", 0, 2, &curves),
        packing: packing_audit(&curves, &packed_curves),
    }
}

pub fn kernel_cascade_mag_db(corner: &CornerData, frequency_hz: f64, sample_rate_hz: f64) -> f64 {
    corner
        .iter()
        .map(|stage| kernel_stage_mag_db(stage, frequency_hz, sample_rate_hz))
        .sum()
}

pub fn biquad_cascade_mag_db(corner: &CornerData, frequency_hz: f64, sample_rate_hz: f64) -> f64 {
    corner
        .iter()
        .map(|stage| biquad_stage_mag_db(stage, frequency_hz, sample_rate_hz))
        .sum()
}

pub fn kernel_stage_mag_db(
    stage: &[f64; NUM_COEFFS],
    frequency_hz: f64,
    sample_rate_hz: f64,
) -> f64 {
    biquad_stage_mag_db(&kernel_to_biquad(*stage), frequency_hz, sample_rate_hz)
}

pub fn biquad_stage_mag_db(
    stage: &[f64; NUM_COEFFS],
    frequency_hz: f64,
    sample_rate_hz: f64,
) -> f64 {
    let angle = std::f64::consts::TAU * frequency_hz / sample_rate_hz.max(1.0);
    let (cos1, sin1) = (angle.cos(), angle.sin());
    let (cos2, sin2) = ((2.0 * angle).cos(), (2.0 * angle).sin());
    let [b0, b1, b2, a1, a2] = *stage;
    let nr = b0 + b1 * cos1 + b2 * cos2;
    let ni = -b1 * sin1 - b2 * sin2;
    let dr = 1.0 + a1 * cos1 + a2 * cos2;
    let di = -a1 * sin1 - a2 * sin2;
    10.0 * (((nr * nr + ni * ni) + EPS) / ((dr * dr + di * di) + EPS)).log10()
}

/// Complex frequency response `H(e^{jω})` of one direct DF2T biquad row
/// `[b0,b1,b2,a1,a2]`, returned as `(re, im)`. This is the single owner of
/// per-stage complex response; [`biquad_stage_mag_db`] is exactly its
/// magnitude in dB. Used by the transfer-function oracle to compare a packed
/// candidate against a measured complex target without a second response
/// engine.
pub fn biquad_stage_complex(
    stage: &[f64; NUM_COEFFS],
    frequency_hz: f64,
    sample_rate_hz: f64,
) -> (f64, f64) {
    let angle = std::f64::consts::TAU * frequency_hz / sample_rate_hz.max(1.0);
    let (cos1, sin1) = (angle.cos(), angle.sin());
    let (cos2, sin2) = ((2.0 * angle).cos(), (2.0 * angle).sin());
    let [b0, b1, b2, a1, a2] = *stage;
    let nr = b0 + b1 * cos1 + b2 * cos2;
    let ni = -b1 * sin1 - b2 * sin2;
    let dr = 1.0 + a1 * cos1 + a2 * cos2;
    let di = -a1 * sin1 - a2 * sin2;
    let den = dr * dr + di * di + EPS;
    ((nr * dr + ni * di) / den, (ni * dr - nr * di) / den)
}

/// Complex frequency response of the six-stage serial cascade at one
/// frequency: the ordered product of the per-stage complex responses. `corner`
/// is direct DF2T rows (as returned by `PackedCorners::interpolate_biquad`).
pub fn biquad_cascade_complex(
    corner: &CornerData,
    frequency_hz: f64,
    sample_rate_hz: f64,
) -> (f64, f64) {
    let mut re = 1.0f64;
    let mut im = 0.0f64;
    for stage in corner.iter() {
        let (sr, si) = biquad_stage_complex(stage, frequency_hz, sample_rate_hz);
        let (pr, pi) = (re * sr - im * si, re * si + im * sr);
        re = pr;
        im = pi;
    }
    (re, im)
}

fn axis_motion(
    axis: &'static str,
    from_idx: usize,
    to_idx: usize,
    curves: &[ResponseCurve],
) -> AxisMotion {
    let from_summary = summarize_curve(CORNER_LABELS[from_idx], &curves[from_idx]);
    let to_summary = summarize_curve(CORNER_LABELS[to_idx], &curves[to_idx]);
    AxisMotion {
        axis: axis.to_owned(),
        from: from_summary.label,
        to: to_summary.label,
        rms_delta_db: curve_rms_delta_db(&curves[from_idx], &curves[to_idx]),
        centroid_delta_hz: to_summary.centroid_hz - from_summary.centroid_hz,
        peak_delta_db: to_summary.peak_db - from_summary.peak_db,
    }
}

fn packing_audit(target: &[ResponseCurve], packed: &[ResponseCurve]) -> PackingAudit {
    let mut acc = 0.0;
    let mut n = 0usize;
    let mut peak = 0.0f64;
    for (a, b) in target.iter().zip(packed) {
        for (pa, pb) in a.points.iter().zip(&b.points) {
            let d = pa.db - pb.db;
            acc += d * d;
            peak = peak.max(d.abs());
            n += 1;
        }
    }
    PackingAudit {
        rms_db: (acc / n.max(1) as f64).sqrt(),
        peak_db: peak,
    }
}

fn curve_rms_delta_db(a: &ResponseCurve, b: &ResponseCurve) -> f64 {
    let mut acc = 0.0;
    let mut n = 0usize;
    for (pa, pb) in a.points.iter().zip(&b.points) {
        let d = pa.db - pb.db;
        acc += d * d;
        n += 1;
    }
    (acc / n.max(1) as f64).sqrt()
}

fn average_band_db(curve: &ResponseCurve, lo_hz: f64, hi_hz: f64) -> f64 {
    let mut acc = 0.0;
    let mut n = 0usize;
    for p in &curve.points {
        if p.freq_hz >= lo_hz && p.freq_hz < hi_hz {
            acc += p.db;
            n += 1;
        }
    }
    if n == 0 {
        f64::NAN
    } else {
        acc / n as f64
    }
}

fn spectral_centroid_hz(curve: &ResponseCurve) -> f64 {
    let mut num = 0.0;
    let mut den = 0.0;
    for p in &curve.points {
        let w = 10.0f64.powf(p.db / 20.0);
        num += p.freq_hz * w;
        den += w;
    }
    if den <= EPS {
        0.0
    } else {
        num / den
    }
}

fn slope_db_per_octave(curve: &ResponseCurve) -> f64 {
    let n = curve.points.len();
    if n < 2 {
        return 0.0;
    }
    let xs: Vec<f64> = curve
        .points
        .iter()
        .map(|p| p.freq_hz.max(1.0).log2())
        .collect();
    let ys: Vec<f64> = curve.points.iter().map(|p| p.db).collect();
    let mx = xs.iter().sum::<f64>() / n as f64;
    let my = ys.iter().sum::<f64>() / n as f64;
    let mut num = 0.0;
    let mut den = 0.0;
    for (x, y) in xs.iter().zip(&ys) {
        num += (x - mx) * (y - my);
        den += (x - mx) * (x - mx);
    }
    if den <= EPS {
        0.0
    } else {
        num / den
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cascade::NUM_STAGES;

    const PASS_KERNEL: [f64; NUM_COEFFS] = [2.0, 1.0, 2.0, 1.0, 1.0];

    #[test]
    fn passthrough_kernel_is_flat_response() {
        let corner = [PASS_KERNEL; NUM_STAGES];
        let grid = log_frequency_grid(20.0, 16_000.0, 64);
        let curve = kernel_response_curve(&corner, 39_062.5, &grid);
        for p in curve.points {
            assert!(p.db.abs() < 1.0e-9, "{} Hz -> {} dB", p.freq_hz, p.db);
        }
    }

    #[test]
    fn surface_audit_reports_pack_roundtrip() {
        let corners = [[PASS_KERNEL; NUM_STAGES]; 4];
        let audit = audit_kernel_surface(&corners, 39_062.5, 64);
        assert_eq!(
            audit.contract,
            "response-surface-v1: author magnitude/motion/Q first; pack stages last"
        );
        assert!(audit.packing.rms_db < 1.0e-9);
        assert_eq!(audit.corners.len(), 4);
    }
}
