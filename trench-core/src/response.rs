//! Response-first authoring contract.
//!
//! The creative object is the full cascade magnitude surface over Morph x Q.
//! Stage rows are the packed realization of that target, not the design schema.

use crate::cartridge::CornerData;
use crate::cascade::NUM_COEFFS;
use crate::minifloat::{kernel_to_biquad, PackedCorners};

const EPS: f64 = 1.0e-30;
const CORNER_LABELS: [&str; 4] = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];

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
