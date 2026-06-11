//! model.rs — the root-domain six-stage composer (v0 of the coefficient forge).
//!
//! This is the editable authoring substrate from
//! `gpt55-pro-report-coefficient-forge-spec.md`: a body is four corners
//! (`M0_S0, M1_S0, M0_S1, M1_S1`), each corner is six serialized DF2T stages,
//! each stage is a pole pair + an optional zero pair + section gain.
//!
//! The math here is ONLY root → kernel `[c0..c4]` (the authoring half). Packing
//! (`kernel → u16 words`), the 240-byte layout, packed-domain interpolation, and
//! the response plot all stay owned by `trench_core` — this module never
//! reimplements them. Verified lossless end-to-end by `probe.rs` (round-trip
//! ≤0.06 dB across the musical range; gain ceiling g=4.0).

use serde::{Deserialize, Serialize};
use std::f64::consts::TAU;

use trench_core::cartridge::CornerData;
use trench_core::cascade::NUM_STAGES;
use trench_core::minifloat::{pole_radius, PackedCorners, BODY_BYTES};
use trench_core::response::{biquad_cascade_mag_db, log_frequency_grid};

/// Authoring sample rate (the E-mu chip rate the body is compiled against).
pub const AUTHORING_SR: f64 = 39_062.5;
/// Hard section-gain ceiling. Above this `c4/4` clamps in the packer and the
/// plot lies (OBSERVED in `probe.rs`: g=5 → 1.94 dB round-trip error).
pub const GAIN_MAX: f64 = 4.0;
/// Pole radius the bilinear morph middle must stay under to be stable.
pub const RMAX: f64 = 0.999;
/// The identity (passthrough) kernel: flat 0 dB.
const PASS_KERNEL: [f64; 5] = [2.0, 1.0, 2.0, 1.0, 1.0];

fn clamp_freq(f: f64, sr: f64) -> f64 {
    f.clamp(20.0, sr * 0.49)
}

// ── root-domain ─────────────────────────────────────────────────────────────

/// A second-order root pair — pole or zero. Stored in musical coordinates, not
/// coefficients. `Complex` is a conjugate pair (resonance/notch); `Real` is two
/// real roots in `(-1, 1)` (used for DC/Nyquist zeros and broad slopes).
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Roots {
    Complex { freq_hz: f64, radius: f64 },
    Real { a: f64, b: f64 },
}

impl Roots {
    /// Recover a root pair from monic coefficients
    /// `1 + c1*z^-1 + c2*z^-2`.
    fn from_coeffs(c1: f64, c2: f64, sr: f64) -> Self {
        let disc = c1 * c1 - 4.0 * c2;
        if disc < -1.0e-10 {
            let radius = c2.max(0.0).sqrt();
            let angle = if radius > 1.0e-12 {
                (-c1 / (2.0 * radius)).clamp(-1.0, 1.0).acos()
            } else {
                0.0
            };
            Roots::Complex {
                freq_hz: angle * sr / TAU,
                radius,
            }
        } else {
            let root_disc = disc.max(0.0).sqrt();
            Roots::Real {
                a: (-c1 + root_disc) * 0.5,
                b: (-c1 - root_disc) * 0.5,
            }
        }
    }

    /// Monic 2nd-order coefficients `(k1, k2)` for `1 + k1·z⁻¹ + k2·z⁻²`.
    /// A pole supplies `(a1, a2)`; a zero supplies the monic numerator `(b1, b2)`.
    fn coeffs(self, sr: f64) -> (f64, f64) {
        match self {
            Roots::Complex { freq_hz, radius } => {
                let w = TAU * clamp_freq(freq_hz, sr) / sr;
                (-2.0 * radius * w.cos(), radius * radius)
            }
            Roots::Real { a, b } => (-(a + b), a * b),
        }
    }

    /// Largest root magnitude — the value the stability gate watches.
    pub fn max_radius(self) -> f64 {
        match self {
            Roots::Complex { radius, .. } => radius.abs(),
            Roots::Real { a, b } => a.abs().max(b.abs()),
        }
    }
}

/// One serialized DF2T stage actor. Holds an editable pole, an explicit zero,
/// section gain, and the bookkeeping the spec calls for (role/lock/provenance).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Stage {
    pub enabled: bool,
    pub role: String,
    pub locked: bool,
    pub pole: Roots,
    pub zero: Option<Roots>,
    /// Section gain `g` = numerator scale `b0`. Range `[0, GAIN_MAX]`.
    pub gain: f64,
    pub provenance: String,
}

impl Stage {
    /// Neutral zero pair: explicit, visible in the authoring model, and compiles
    /// to the same numerator as the old missing-zero representation.
    pub fn neutral_zero(freq_hz: f64) -> Roots {
        Roots::Complex {
            freq_hz,
            radius: 0.0,
        }
    }

    pub fn ensure_zero(&mut self) {
        if self.zero.is_none() {
            let freq_hz = match self.pole {
                Roots::Complex { freq_hz, .. } => freq_hz,
                Roots::Real { .. } => 1000.0,
            };
            self.zero = Some(Self::neutral_zero(freq_hz));
        }
    }

    /// A compiled-identity stage: flat, valid, holds its serialized slot.
    pub fn identity() -> Self {
        Self {
            enabled: true,
            role: "—".into(),
            locked: false,
            pole: Roots::Complex {
                freq_hz: 1000.0,
                radius: 0.0,
            },
            zero: Some(Self::neutral_zero(1000.0)),
            gain: 1.0,
            provenance: "identity".into(),
        }
    }

    /// Compile this stage to kernel form `[c0,c1,c2,c3,c4]` (what the packer
    /// consumes). A disabled stage compiles to passthrough.
    pub fn to_kernel(&self, sr: f64) -> [f64; 5] {
        if !self.enabled {
            return PASS_KERNEL;
        }
        let (a1, a2) = self.pole.coeffs(sr);
        let (b1, b2) = self
            .zero
            .unwrap_or_else(|| Self::neutral_zero(1000.0))
            .coeffs(sr);
        let g = self.gain.clamp(0.0, GAIN_MAX);
        [2.0 + b1, 1.0 - b2, a1 + 2.0, 1.0 - a2, g]
    }

    /// Import a deterministic generator row into the editable root-domain
    /// representation. This is the inverse of `to_kernel`; packing remains
    /// owned by `trench_core`.
    pub fn from_kernel(kernel: [f64; 5], sr: f64, role: &str, provenance: &str) -> Self {
        if kernel
            .iter()
            .zip(PASS_KERNEL.iter())
            .all(|(a, b)| (a - b).abs() < 1.0e-10)
        {
            return Self::identity();
        }
        let pole = Roots::from_coeffs(kernel[2] - 2.0, 1.0 - kernel[3], sr);
        let b1 = kernel[0] - 2.0;
        let b2 = 1.0 - kernel[1];
        let zero = if b1.abs() < 1.0e-10 && b2.abs() < 1.0e-10 {
            Some(Self::neutral_zero(match pole {
                Roots::Complex { freq_hz, .. } => freq_hz,
                Roots::Real { .. } => 1000.0,
            }))
        } else {
            Some(Roots::from_coeffs(b1, b2, sr))
        };
        Self {
            enabled: true,
            role: role.into(),
            locked: false,
            pole,
            zero,
            gain: kernel[4].clamp(0.0, GAIN_MAX),
            provenance: provenance.into(),
        }
    }
}

/// Six serialized stages = one corner.
pub type Corner = [Stage; NUM_STAGES];

fn blank_corner() -> Corner {
    std::array::from_fn(|_| Stage::identity())
}

fn body_id(name: &str) -> String {
    let mut out = String::new();
    let mut underscore = false;
    for ch in name.chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch.to_ascii_lowercase());
            underscore = false;
        } else if !underscore && !out.is_empty() {
            out.push('_');
            underscore = true;
        }
    }
    out.trim_matches('_').to_string()
}

// ── body ──────────────────────────────────────────────────────────────────

/// The editable `.df2forge.json` document. `corners` are in runtime order:
/// `[0]=M0_S0, [1]=M1_S0, [2]=M0_S1, [3]=M1_S1`.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ForgeBody {
    pub format_version: u32,
    pub body_id: String,
    pub body_name: String,
    pub authoring_sample_rate: f64,
    pub notes: String,
    pub corners: [Corner; 4],
    /// Legacy import flag for old bodies that duplicated the Secondary edge.
    /// Normal authoring treats the four corners as distinct variants.
    pub secondary_degenerate: bool,
    pub constructor_history: Vec<String>,
}

/// Corner index ↔ (morph, secondary) grid point and label.
pub const CORNER_LABELS: [&str; 4] = ["M0_S0", "M1_S0", "M0_S1", "M1_S1"];

impl ForgeBody {
    /// An all-identity four-corner board.
    pub fn blank(name: &str) -> Self {
        Self {
            format_version: 1,
            body_id: body_id(name),
            body_name: name.to_string(),
            authoring_sample_rate: AUTHORING_SR,
            notes: String::new(),
            corners: std::array::from_fn(|_| blank_corner()),
            secondary_degenerate: false,
            constructor_history: Vec::new(),
        }
    }

    /// First-run starter: a single bandpass actor in lane 1 whose centre sweeps
    /// 400 Hz → 2500 Hz across MORPH. Lawful, deterministic
    /// — gives the hero plot a moving resonance to show immediately.
    pub fn starter() -> Self {
        let mut b = Self::blank("Starter");
        let centers = [400.0, 2500.0, 400.0, 2500.0];
        for (ci, &c) in centers.iter().enumerate() {
            b.corners[ci][1] = constructors::bp_window(c, 220.0);
            b.corners[ci][1].role = "BAND".into();
        }
        b.constructor_history
            .push("starter: BP window, centre sweep 400→2500".into());
        b
    }

    /// Lift a deterministic starter plane into ordinary editable lanes.
    /// Generator scripts propose a body; the Forge immediately owns the rows.
    pub fn from_corner_data(name: &str, kernels: [CornerData; 4], notes: &str) -> Self {
        let mut b = Self::blank(name);
        for (ci, corner) in kernels.iter().enumerate() {
            for (si, stage) in corner.iter().enumerate() {
                b.corners[ci][si] =
                    Stage::from_kernel(*stage, b.authoring_sample_rate, "ACTOR", notes);
            }
        }
        b.secondary_degenerate = false;
        b.notes = notes.into();
        b.constructor_history.push(format!("starter plane: {name}"));
        b
    }

    /// Load a compiled `.body240` back into editable root-domain lanes. Each
    /// stored corner is decoded verbatim (`corner_kernel`) and lifted into
    /// Stages — the inverse of `compile`, through the same owned packer, so a
    /// generated body opens as six editable lanes that play immediately.
    pub fn from_body240(name: &str, bytes: &[u8]) -> Result<Self, String> {
        let packed = PackedCorners::from_body_bytes(bytes).map_err(|e| e.to_string())?;
        let kernels: [CornerData; 4] = std::array::from_fn(|ci| packed.corner_kernel(ci));
        Ok(Self::from_corner_data(name, kernels, "loaded .body240"))
    }

    /// Compile a single corner to kernel-form `CornerData`.
    pub fn corner_kernel(&self, ci: usize) -> CornerData {
        let sr = self.authoring_sample_rate;
        let mut c = [[0.0f64; 5]; NUM_STAGES];
        for si in 0..NUM_STAGES {
            c[si] = self.corners[ci][si].to_kernel(sr);
        }
        c
    }

    /// Return the literal shared section gain when all six lanes match.
    pub fn corner_uniform_gain(&self, ci: usize) -> Option<f64> {
        let gain = self.corners[ci][0].gain;
        self.corners[ci]
            .iter()
            .all(|stage| (stage.gain - gain).abs() < 1.0e-12)
            .then_some(gain)
    }

    /// Write the same literal section gain into all six serialized lanes.
    pub fn set_corner_gain(&mut self, ci: usize, gain: f64) {
        let gain = gain.clamp(0.0, GAIN_MAX);
        for stage in &mut self.corners[ci] {
            stage.gain = gain;
        }
    }

    /// Full compile: root domain → packed 240-byte body + always-on audit.
    pub fn compile(&self) -> Compiled {
        let kernels: [CornerData; 4] = std::array::from_fn(|ci| self.corner_kernel(ci));
        let packed = PackedCorners::from_corner_data(&kernels);
        let bytes = packed.to_rom_bytes();
        let mut audit = Audit::run(&packed, self.authoring_sample_rate);
        if self.secondary_degenerate {
            audit
                .warnings
                .push("Secondary remains degenerate: expand it before final authoring".into());
            audit.warnings.sort();
            audit.warnings.dedup();
        }
        Compiled {
            packed,
            bytes,
            audit,
        }
    }

    /// Clone the current MORPH edge (S0 corners) into the Secondary edge (S1),
    /// then mark Secondary as no longer degenerate so it can be edited freely.
    pub fn expand_secondary(&mut self) {
        self.corners[2] = self.corners[0].clone();
        self.corners[3] = self.corners[1].clone();
        self.secondary_degenerate = false;
        self.constructor_history.push("expand secondary".into());
    }
}

// ── compile output + audit ──────────────────────────────────────────────────

pub struct Compiled {
    pub packed: PackedCorners,
    pub bytes: [u8; BODY_BYTES],
    pub audit: Audit,
}

pub const AUDIT_GRID_SIDE: usize = 5;

#[derive(Clone, Debug, Default)]
pub struct AuditPoint {
    pub morph: f32,
    pub secondary: f32,
    pub max_pole_radius: f64,
    pub peak_db: f64,
    /// Largest RMS response change to an adjacent 5x5 grid point.
    pub local_response_delta_db: f64,
}

/// Always-on packed-runtime audit. Hard `errors` block export; `warnings`
/// inform taste but never reject. Computed through the release FFI path
/// (`interpolate_biquad`), never an approximate authoring plot.
#[derive(Clone, Debug, Default)]
pub struct Audit {
    pub errors: Vec<String>,
    pub warnings: Vec<String>,
    pub max_pole_radius: f64,
    pub peak_db: f64,
    pub max_local_response_delta_db: f64,
    pub points: Vec<AuditPoint>,
}

impl Audit {
    pub fn pass(&self) -> bool {
        self.errors.is_empty()
    }

    pub fn point(&self, x: usize, y: usize) -> &AuditPoint {
        &self.points[y * AUDIT_GRID_SIDE + x]
    }

    pub fn run(packed: &PackedCorners, sr: f64) -> Self {
        let grid = log_frequency_grid(20.0, sr * 0.5, 128);
        let mut errors = Vec::new();
        let mut warnings = Vec::new();
        let mut max_r = 0.0f64;
        let mut peak = f64::NEG_INFINITY;
        let mut points = Vec::with_capacity(AUDIT_GRID_SIDE * AUDIT_GRID_SIDE);
        let mut curves = Vec::with_capacity(AUDIT_GRID_SIDE * AUDIT_GRID_SIDE);
        let mut remote_zero = false;
        let mut fragile_cancellation = false;
        let mut low_pole_fusion = false;

        for y in 0..AUDIT_GRID_SIDE {
            for x in 0..AUDIT_GRID_SIDE {
                let m = x as f32 / (AUDIT_GRID_SIDE - 1) as f32;
                let q = y as f32 / (AUDIT_GRID_SIDE - 1) as f32;
                let label = format!("M{m:.2}_S{q:.2}");
                let decoded = packed.interpolate_biquad(m, q);
                let mut point_r = 0.0f64;
                let mut low_poles = Vec::new();
                for (si, st) in decoded.iter().enumerate() {
                    if !st.iter().all(|v| v.is_finite()) {
                        errors.push(format!("{label}: stage {} non-finite coeffs", si + 1));
                        continue;
                    }
                    let r = pole_radius(st[3], st[4]);
                    max_r = max_r.max(r);
                    point_r = point_r.max(r);
                    if r >= 1.0 {
                        errors.push(format!("{label}: stage {} UNSTABLE pole r={r:.4}", si + 1));
                    } else if r > RMAX {
                        warnings.push(format!("near-unit pole r={r:.4} (≥{RMAX})"));
                    }
                    let pole = Roots::from_coeffs(st[3], st[4], sr);
                    if let Roots::Complex {
                        freq_hz: pole_hz,
                        radius: pole_r,
                    } = pole
                    {
                        if pole_hz < 200.0 {
                            low_poles.push(pole_hz);
                        }
                        if st[0].abs() > 1.0e-12 {
                            let zero = Roots::from_coeffs(st[1] / st[0], st[2] / st[0], sr);
                            if let Roots::Complex {
                                freq_hz: zero_hz,
                                radius: zero_r,
                            } = zero
                            {
                                let distance_oct = (zero_hz / pole_hz).log2().abs();
                                remote_zero |= distance_oct > 1.5;
                                fragile_cancellation |=
                                    distance_oct < 0.08 && (zero_r - pole_r).abs() < 0.08;
                            }
                        }
                    }
                }
                low_poles.sort_by(f64::total_cmp);
                low_pole_fusion |= low_poles
                    .windows(2)
                    .any(|pair| (pair[1] / pair[0]).log2().abs() < 0.35);
                let mut point_peak = f64::NEG_INFINITY;
                let mut curve = Vec::with_capacity(grid.len());
                for &f in &grid {
                    let db = biquad_cascade_mag_db(&decoded, f, sr);
                    if !db.is_finite() {
                        errors.push(format!("{label}: non-finite response @ {f:.0} Hz"));
                        break;
                    }
                    peak = peak.max(db);
                    point_peak = point_peak.max(db);
                    curve.push(db);
                }
                points.push(AuditPoint {
                    morph: m,
                    secondary: q,
                    max_pole_radius: point_r,
                    peak_db: point_peak,
                    ..Default::default()
                });
                curves.push(curve);
            }
        }

        for y in 0..AUDIT_GRID_SIDE {
            for x in 0..AUDIT_GRID_SIDE {
                let i = y * AUDIT_GRID_SIDE + x;
                let mut local_delta = 0.0f64;
                for (nx, ny) in [
                    (x.checked_sub(1), Some(y)),
                    (Some(x + 1).filter(|&v| v < AUDIT_GRID_SIDE), Some(y)),
                    (Some(x), y.checked_sub(1)),
                    (Some(x), Some(y + 1).filter(|&v| v < AUDIT_GRID_SIDE)),
                ] {
                    if let (Some(nx), Some(ny)) = (nx, ny) {
                        local_delta = local_delta
                            .max(rms_delta(&curves[i], &curves[ny * AUDIT_GRID_SIDE + nx]));
                    }
                }
                points[i].local_response_delta_db = local_delta;
            }
        }
        let max_local_response_delta_db = points
            .iter()
            .map(|point| point.local_response_delta_db)
            .fold(0.0, f64::max);
        if peak > 36.0 {
            warnings.push(format!("large response headroom: peak {peak:.1} dB"));
        }
        if remote_zero {
            warnings.push("remote zero counterweight present".into());
        }
        if fragile_cancellation {
            warnings.push("fragile near pole-zero cancellation present".into());
        }
        if low_pole_fusion {
            warnings.push("sub-200 Hz pole fusion present".into());
        }
        if points[AUDIT_GRID_SIDE / 2 * AUDIT_GRID_SIDE + AUDIT_GRID_SIDE / 2]
            .local_response_delta_db
            > 10.0
        {
            warnings.push("strong midpoint emergence present".into());
        }
        warnings.sort();
        warnings.dedup();

        Audit {
            errors,
            warnings,
            max_pole_radius: max_r,
            peak_db: peak,
            max_local_response_delta_db,
            points,
        }
    }
}

fn rms_delta(a: &[f64], b: &[f64]) -> f64 {
    let n = a.len().min(b.len());
    if n == 0 {
        return 0.0;
    }
    (a.iter()
        .zip(b)
        .take(n)
        .map(|(a, b)| (a - b).powi(2))
        .sum::<f64>()
        / n as f64)
        .sqrt()
}

// ── lawful constructors ───────────────────────────────────────────────────────
//
// Each produces editable Stage rows — never a hidden macro. The UI inserts the
// returned rows into a corner; they immediately become ordinary lanes.
pub mod constructors {
    use super::*;

    /// Map a bandwidth in Hz to a pole radius (narrower = higher radius).
    fn radius_from_bw(bw_hz: f64, sr: f64) -> f64 {
        (-std::f64::consts::PI * bw_hz / sr).exp().clamp(0.5, RMAX)
    }

    /// Unity-DC section gain for a lowpass-shaped section (zeros at Nyquist).
    fn lp_unity_gain(a1: f64, a2: f64) -> f64 {
        ((1.0 + a1 + a2) / 4.0).clamp(0.0, GAIN_MAX)
    }
    /// Unity-Nyquist section gain for a highpass-shaped section (zeros at DC).
    fn hp_unity_gain(a1: f64, a2: f64) -> f64 {
        ((1.0 - a1 + a2) / 4.0).clamp(0.0, GAIN_MAX)
    }

    pub fn identity() -> Stage {
        Stage::identity()
    }

    /// A single bandpass actor: pole pair at `center`, zeros pinned to DC and
    /// Nyquist (numerator `1 − z⁻²`), gain set for ≈unity peak.
    pub fn bp_window(center: f64, bw_hz: f64) -> Stage {
        let sr = AUTHORING_SR;
        let rp = radius_from_bw(bw_hz, sr);
        let a2 = rp * rp;
        // Section gain for a clear, no-pedestal band (≈+4 dB peak before the
        // author sharpens). The `1−a2` factor tracks the pole's narrowing so the
        // peak height stays roughly constant across bandwidths.
        let g = ((1.0 - a2) * 1.5).clamp(0.02, GAIN_MAX);
        Stage {
            enabled: true,
            role: "BAND".into(),
            locked: false,
            pole: Roots::Complex {
                freq_hz: center,
                radius: rp,
            },
            zero: Some(Roots::Real { a: 1.0, b: -1.0 }),
            gain: g.max(0.02),
            provenance: format!("bp_window c={center:.0} bw={bw_hz:.0}"),
        }
    }

    /// A lowpass cliff: `order/2` descending sections at `cutoff`. Staggered
    /// radii build a knee; zeros at Nyquist give the stopband; unity DC.
    pub fn lp_cliff(cutoff: f64, order: usize) -> Vec<Stage> {
        cliff(cutoff, order, true)
    }
    /// A highpass cliff: rising sections at `cutoff`, zeros at DC, unity HF.
    pub fn hp_cliff(cutoff: f64, order: usize) -> Vec<Stage> {
        cliff(cutoff, order, false)
    }

    fn cliff(cutoff: f64, order: usize, lowpass: bool) -> Vec<Stage> {
        let sr = AUTHORING_SR;
        let sections = (order / 2).clamp(1, NUM_STAGES);
        let w = TAU * clamp_freq(cutoff, sr) / sr;
        (0..sections)
            .map(|k| {
                // Stagger radius so the last section carries the resonant knee.
                let rp = (0.70 + 0.27 * (k as f64 / (sections.max(1)) as f64)).min(RMAX);
                let a1 = -2.0 * rp * w.cos();
                let a2 = rp * rp;
                let (zero, gain, role) = if lowpass {
                    (
                        Roots::Complex {
                            freq_hz: sr * 0.49,
                            radius: 1.0,
                        },
                        lp_unity_gain(a1, a2),
                        "LP",
                    )
                } else {
                    (
                        Roots::Real { a: 1.0, b: 1.0 }, // double zero at DC
                        hp_unity_gain(a1, a2),
                        "HP",
                    )
                };
                Stage {
                    enabled: true,
                    role: role.into(),
                    locked: false,
                    pole: Roots::Complex {
                        freq_hz: cutoff,
                        radius: rp,
                    },
                    zero: Some(zero),
                    gain: gain.max(0.02),
                    provenance: format!(
                        "{}_cliff fc={cutoff:.0} ord={order} sec={k}",
                        role.to_lowercase()
                    ),
                }
            })
            .collect()
    }

    /// An opposed hollow: two band actors flanking a gap. Two editable rows.
    pub fn opposed_hollow(low_center: f64, high_center: f64, bw_hz: f64) -> Vec<Stage> {
        let mut lo = bp_window(low_center, bw_hz);
        let mut hi = bp_window(high_center, bw_hz);
        lo.role = "HOLLOW-".into();
        hi.role = "HOLLOW+".into();
        lo.provenance = format!("opposed_hollow lo={low_center:.0}");
        hi.provenance = format!("opposed_hollow hi={high_center:.0}");
        vec![lo, hi]
    }

    /// A peak / canyon actor: one pole, one zero, one gain. `gain>1` = mountain;
    /// a zero with `rz→1` near the pole = a tear/notch.
    pub fn peak_canyon(fp: f64, rp: f64, fz: f64, rz: f64, gain: f64) -> Stage {
        Stage {
            enabled: true,
            role: if gain >= 1.0 {
                "PEAK".into()
            } else {
                "CANYON".into()
            },
            locked: false,
            pole: Roots::Complex {
                freq_hz: fp,
                radius: rp.clamp(0.0, RMAX),
            },
            zero: Some(Roots::Complex {
                freq_hz: fz,
                radius: rz.clamp(0.0, 0.999),
            }),
            gain: gain.clamp(0.0, GAIN_MAX),
            provenance: format!("peak_canyon fp={fp:.0} fz={fz:.0}"),
        }
    }

    /// One Peak/Shelf frame: the pole is the musical focus, while shelf moves
    /// its attached zero across a wide interval. Dragging the pole in the bench
    /// carries that interval with it.
    pub fn peak_shelf(freq: f64, shelf: f64, peak_db: f64, rp: f64) -> Stage {
        let s = (shelf / 64.0).clamp(-1.0, 1.0);
        let zfreq = (freq * 2f64.powf(-s * 4.0)).clamp(20.0, AUTHORING_SR * 0.49);
        let rz = (0.55 + 0.42 * s.abs()).min(0.999);
        Stage {
            enabled: true,
            role: "P/SHELF".into(),
            locked: false,
            pole: Roots::Complex {
                freq_hz: freq,
                radius: rp.min(RMAX),
            },
            zero: Some(Roots::Complex {
                freq_hz: zfreq,
                radius: rz,
            }),
            gain: 10f64.powf(peak_db / 20.0).clamp(0.0, GAIN_MAX),
            provenance: format!("peak_shelf f={freq:.0} shelf={shelf:+.0}"),
        }
    }

    /// Low body weight with a zero attached below the pole: no sub pedestal.
    pub fn sub_anchor(freq: f64, rp: f64, gain: f64) -> Stage {
        Stage {
            enabled: true,
            role: "SUB".into(),
            locked: false,
            pole: Roots::Complex {
                freq_hz: freq,
                radius: rp.min(RMAX),
            },
            zero: Some(Roots::Complex {
                freq_hz: freq * 0.5,
                radius: 0.6,
            }),
            gain: gain.clamp(0.0, GAIN_MAX),
            provenance: format!("sub_anchor f={freq:.0}"),
        }
    }

    /// Excavation actor: a deep zero with a deliberately broad supporting pole.
    pub fn carve(freq: f64, rz: f64) -> Stage {
        Stage {
            enabled: true,
            role: "CARVE".into(),
            locked: false,
            pole: Roots::Complex {
                freq_hz: freq,
                radius: 0.5,
            },
            zero: Some(Roots::Complex {
                freq_hz: freq,
                radius: rz.min(0.999),
            }),
            gain: 1.0,
            provenance: format!("carve f={freq:.0}"),
        }
    }

    /// Original three-row cavity grammar inspired by the clean-room type
    /// study: a broad body, a lower excavation, and an upper mountain. Negative
    /// spread crosses the pole and zero trajectories.
    pub fn spread_cavity(center: f64, spread_octaves: f64) -> Vec<Stage> {
        let ratio = 2f64.powf(spread_octaves);
        let low = (center / ratio).clamp(30.0, AUTHORING_SR * 0.45);
        let high = (center * ratio).clamp(30.0, AUTHORING_SR * 0.45);
        let mut body = peak_canyon(center, 0.82, center * 0.72, 0.45, 0.85);
        body.role = "CAVITY".into();
        let mut cut = carve(low, 0.975);
        cut.role = "CAVITY-".into();
        let mut peak = peak_canyon(high, 0.975, high * 0.55, 0.62, 1.35);
        peak.role = "CAVITY+".into();
        vec![body, cut, peak]
    }

    /// A wide pole/zero lever for contrary crossings and air-cap repairs.
    pub fn remote_counterweight(freq: f64, bright: bool) -> Stage {
        let (fz, rz, gain) = if bright {
            (freq * 0.16, 0.70, 1.35)
        } else {
            (freq * 4.0, 0.96, 0.72)
        };
        let mut s = peak_canyon(freq, 0.94, fz, rz, gain);
        s.role = if bright { "REMOTE+" } else { "REMOTE-" }.into();
        s.provenance = format!("remote_counterweight f={freq:.0} bright={bright}");
        s
    }

    /// Two broad counterweights that establish a spectral slope before local
    /// cavities are stamped into the remaining rows.
    pub fn tilt_frame(low: f64, high: f64) -> Vec<Stage> {
        let mut lo = peak_canyon(low, 0.80, high, 0.94, 0.82);
        lo.role = "TILT-".into();
        lo.provenance = format!("tilt_frame low={low:.0} high={high:.0}");
        let mut hi = peak_canyon(high, 0.82, low, 0.72, 1.22);
        hi.role = "TILT+".into();
        hi.provenance = format!("tilt_frame high={high:.0} low={low:.0}");
        vec![lo, hi]
    }

    /// A tilt-framed vocal surface: broad boundary rows, three local formant
    /// cavities, and one nasal excavation. Six normal editable rows.
    pub fn voice_frame() -> Vec<Stage> {
        let mut rows = tilt_frame(340.0, 6200.0);
        for (index, freq) in [520.0, 1450.0, 2850.0].into_iter().enumerate() {
            let mut row = peak_canyon(freq, 0.95 + index as f64 * 0.01, freq * 0.72, 0.68, 1.08);
            row.role = format!("FORMANT{}", index + 1);
            row.provenance = format!("voice_frame formant={} f={freq:.0}", index + 1);
            rows.push(row);
        }
        rows.push(nasal_excavation(980.0));
        rows
    }

    /// Three lowpass rows with explicit transmission zeros above the knee.
    /// This is elliptic-like authoring terrain, not a textbook prototype solver.
    pub fn elliptic_cliff(cutoff: f64) -> Vec<Stage> {
        let mut rows = lp_cliff(cutoff, 6);
        for (index, row) in rows.iter_mut().enumerate() {
            row.role = "ELLIPTIC".into();
            row.zero = Some(Roots::Complex {
                freq_hz: cutoff * (1.35 + 0.55 * index as f64),
                radius: 0.985,
            });
            row.provenance = format!("elliptic_cliff fc={cutoff:.0} zero={}", index + 1);
        }
        rows
    }

    /// Three staggered cliff rows with a resonant knee distribution. The
    /// resulting passband movement is intentionally ripple-like and editable.
    pub fn ripple_cliff(cutoff: f64) -> Vec<Stage> {
        let mut rows = lp_cliff(cutoff, 6);
        for (index, row) in rows.iter_mut().enumerate() {
            row.role = "RIPPLE".into();
            row.pole = Roots::Complex {
                freq_hz: cutoff * (0.88 + 0.12 * index as f64),
                radius: [0.78, 0.90, 0.965][index],
            };
            row.provenance = format!("ripple_cliff fc={cutoff:.0} sec={index}");
        }
        rows
    }

    /// Helmholtz-like low body: sub neck, broad cavity, and an upper wall mode.
    pub fn helmholtz_body(freq: f64) -> Vec<Stage> {
        let mut cavity = peak_canyon(freq * 2.4, 0.88, freq * 1.45, 0.58, 0.92);
        cavity.role = "HELMHOLTZ".into();
        let mut wall = peak_canyon(freq * 7.0, 0.95, freq * 3.6, 0.66, 1.08);
        wall.role = "WALL".into();
        vec![sub_anchor(freq, 0.95, 1.0), cavity, wall]
    }

    pub fn nasal_excavation(freq: f64) -> Stage {
        let mut row = carve(freq, 0.985);
        row.role = "NASAL-".into();
        row.provenance = format!("nasal_excavation f={freq:.0}");
        row
    }

    pub fn notch_ladder(base: f64) -> Vec<Stage> {
        [1.0, 1.7, 2.9]
            .into_iter()
            .map(|ratio| {
                let freq = base * ratio;
                let mut row = carve(freq, 0.965);
                row.role = "NOTCH".into();
                row.provenance = format!("notch_ladder f={freq:.0}");
                row
            })
            .collect()
    }

    pub fn tooth_comb(base: f64) -> Vec<Stage> {
        [1.0, 1.52, 2.31, 3.51]
            .into_iter()
            .map(|ratio| {
                let freq = base * ratio;
                let mut row = peak_canyon(freq, 0.90, freq * 1.11, 0.93, 0.82);
                row.role = "TOOTH".into();
                row.provenance = format!("tooth_comb f={freq:.0}");
                row
            })
            .collect()
    }

    pub fn modal_snap(base: f64) -> Vec<Stage> {
        [1.0, 2.756, 5.404]
            .into_iter()
            .map(|ratio| {
                let freq = base * ratio;
                let mut row = peak_canyon(freq, 0.965, freq * 0.58, 0.62, 1.05);
                row.role = "MODE".into();
                row.provenance = format!("modal_snap f={freq:.0}");
                row
            })
            .collect()
    }
}

// ── tests: the spec's v0 acceptance criteria ────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;

    /// Coherence test: one high-Q resonance moving 400 Hz → 4000 Hz across MORPH.
    /// Does the packed minifloat-word lerp keep the peak ON the log-octave line and
    /// keep its height, or does it sag in the middle (coefficient-coupling warp)?
    /// Run: cargo test --manifest-path forge-clean/Cargo.toml coherence_single_peak -- --nocapture --ignored
    #[test]
    #[ignore]
    fn coherence_single_peak_warp() {
        let sr = AUTHORING_SR;
        let (f0, f1, r, g) = (400.0, 4000.0, 0.97, 1.0);
        let mut b = ForgeBody::blank("coherence");
        b.secondary_degenerate = false;
        // Same actor (same radius, same gain, zeros at DC+Nyquist) at both MORPH ends.
        for (ci, fp) in [(0usize, f0), (1, f1), (2, f0), (3, f1)] {
            b.corners[ci][0] = Stage {
                enabled: true,
                role: "BAND".into(),
                locked: false,
                pole: Roots::Complex {
                    freq_hz: fp,
                    radius: r,
                },
                zero: Some(Roots::Real { a: 1.0, b: -1.0 }),
                gain: g,
                provenance: "coherence".into(),
            };
        }
        let c = b.compile();
        let grid = log_frequency_grid(20.0, sr * 0.5, 2048);
        println!("\n morph |  peak Hz | target Hz | error(oct) | peak dB");
        println!("-------+----------+-----------+------------+--------");
        for m in [0.0f32, 0.25, 0.5, 0.75, 1.0] {
            let decoded = c.packed.interpolate_biquad(m, 0.0);
            let (mut pf, mut pdb) = (0.0f64, f64::NEG_INFINITY);
            for &f in &grid {
                let db = biquad_cascade_mag_db(&decoded, f, sr);
                if db > pdb {
                    pdb = db;
                    pf = f;
                }
            }
            // Log-octave (geometric) target for a perfectly coherent sweep.
            let target = f0 * (f1 / f0).powf(m as f64);
            let err_oct = (pf / target).log2();
            println!(" {m:>4.2}  | {pf:>8.1} | {target:>9.1} | {err_oct:>+10.3} | {pdb:>6.2}");
        }
        println!();
    }

    fn corner_curve(body: &ForgeBody, ci: usize) -> Vec<f64> {
        let c = body.compile();
        let decoded = c.packed.interpolate_biquad(
            if ci & 1 == 1 { 1.0 } else { 0.0 },
            if ci & 2 == 2 { 1.0 } else { 0.0 },
        );
        let grid = log_frequency_grid(20.0, AUTHORING_SR * 0.5, 64);
        grid.iter()
            .map(|&f| biquad_cascade_mag_db(&decoded, f, AUTHORING_SR))
            .collect()
    }

    #[test]
    fn blank_body_compiles_to_240_bytes_and_is_flat() {
        let b = ForgeBody::blank("t");
        let c = b.compile();
        assert_eq!(c.bytes.len(), BODY_BYTES);
        assert_eq!(BODY_BYTES, 240);
        assert!(c.audit.pass(), "blank body must pass: {:?}", c.audit.errors);
        assert!(b.corners.iter().flatten().all(|stage| stage.zero.is_some()));
        // all-identity → flat 0 dB everywhere
        for db in corner_curve(&b, 0) {
            assert!(db.abs() < 1e-6, "blank corner not flat: {db} dB");
        }
    }

    #[test]
    fn imported_zero_less_rows_get_explicit_neutral_zeros() {
        let stage = Stage::from_kernel(PASS_KERNEL, AUTHORING_SR, "IDENT", "test");
        assert!(matches!(
            stage.zero,
            Some(Roots::Complex { radius: 0.0, .. })
        ));
        assert_eq!(stage.to_kernel(AUTHORING_SR), PASS_KERNEL);
    }

    #[test]
    fn editing_a_zero_changes_the_packed_runtime_plot() {
        // Acceptance: "edit a zero independently and see the packed-runtime plot change."
        let mut b = ForgeBody::blank("t");
        b.corners[0][0] = constructors::peak_canyon(1000.0, 0.97, 1000.0, 0.5, 1.0);
        let before = corner_curve(&b, 0);
        // Move ONLY the zero radius (deepen the tear); pole untouched.
        if let Some(Roots::Complex { radius, .. }) = &mut b.corners[0][0].zero {
            *radius = 0.97;
        }
        let after = corner_curve(&b, 0);
        let max_delta = before
            .iter()
            .zip(&after)
            .map(|(a, c)| (a - c).abs())
            .fold(0.0, f64::max);
        assert!(
            max_delta > 1.0,
            "moving the zero barely changed the plot: {max_delta} dB"
        );
    }

    #[test]
    fn six_pole_cliff_creates_three_editable_rows() {
        // Acceptance: "insert a 6-pole cliff and see three editable serialized rows."
        let rows = constructors::lp_cliff(1200.0, 6);
        assert_eq!(rows.len(), 3);
        assert!(rows
            .iter()
            .all(|s| s.enabled && matches!(s.pole, Roots::Complex { .. })));
    }

    #[test]
    fn opposed_hollow_creates_two_rows() {
        // Acceptance: "create an opposed hollow and see both rows."
        let rows = constructors::opposed_hollow(500.0, 3000.0, 300.0);
        assert_eq!(rows.len(), 2);
    }

    #[test]
    fn unstable_pole_is_rejected_by_the_export_gate() {
        // Acceptance: "reject unstable or nonfinite exports."
        let mut b = ForgeBody::blank("t");
        // Force a pole on the unit circle (radius 1.0) → must fail the gate.
        b.corners[0][0].pole = Roots::Complex {
            freq_hz: 800.0,
            radius: 1.0,
        };
        b.corners[1][0].pole = Roots::Complex {
            freq_hz: 800.0,
            radius: 1.0,
        };
        b.corners[2][0].pole = Roots::Complex {
            freq_hz: 800.0,
            radius: 1.0,
        };
        b.corners[3][0].pole = Roots::Complex {
            freq_hz: 800.0,
            radius: 1.0,
        };
        let c = b.compile();
        assert!(
            !c.audit.pass(),
            "radius-1.0 pole should fail the stability gate"
        );
        assert!(c.audit.errors.iter().any(|e| e.contains("UNSTABLE")));
    }

    #[test]
    fn json_round_trips() {
        let b = ForgeBody::starter();
        let json = serde_json::to_string_pretty(&b).unwrap();
        let back: ForgeBody = serde_json::from_str(&json).unwrap();
        assert_eq!(back.compile().bytes, b.compile().bytes);
    }

    #[test]
    fn corner_energy_sets_a_coherent_six_lane_baseline() {
        let mut b = ForgeBody::starter();
        b.set_corner_gain(0, 1.75);
        assert!(b.corners[0]
            .iter()
            .all(|stage| (stage.gain - 1.75).abs() < 1.0e-12));
        assert_eq!(b.corner_uniform_gain(0), Some(1.75));
        b.corners[0][2].gain = 0.5;
        assert_eq!(b.corner_uniform_gain(0), None);
    }

    #[test]
    fn packed_runtime_audit_is_a_dense_five_by_five_map() {
        let c = ForgeBody::starter().compile();
        assert_eq!(c.audit.points.len(), AUDIT_GRID_SIDE * AUDIT_GRID_SIDE);
        assert_eq!(c.audit.point(2, 2).morph, 0.5);
        assert_eq!(c.audit.point(2, 2).secondary, 0.5);
        assert!(!c
            .audit
            .warnings
            .iter()
            .any(|warning| warning.contains("Secondary remains degenerate")));
    }

    #[test]
    fn packed_runtime_audit_surfaces_authored_risk_warnings() {
        let mut body = ForgeBody::blank("warning surface");
        body.secondary_degenerate = false;
        for ci in 0..4 {
            body.corners[ci][0] = constructors::peak_canyon(95.0, 0.90, 1500.0, 0.70, 1.0);
            body.corners[ci][1] = constructors::peak_canyon(112.0, 0.90, 112.0, 0.87, 1.0);
        }
        let compiled = body.compile();
        assert!(compiled.audit.pass(), "{:?}", compiled.audit.errors);
        for warning in [
            "remote zero counterweight present",
            "fragile near pole-zero cancellation present",
            "sub-200 Hz pole fusion present",
        ] {
            assert!(
                compiled.audit.warnings.iter().any(|item| item == warning),
                "missing warning {warning:?}: {:?}",
                compiled.audit.warnings
            );
        }
    }

    #[test]
    fn generated_kernel_rows_round_trip_through_editable_roots() {
        let kernels = crate::generators::generate(crate::generators::Architecture::EarBender);
        let body = ForgeBody::from_corner_data("Ear Bender", kernels, "test");
        let recovered: [CornerData; 4] = std::array::from_fn(|ci| body.corner_kernel(ci));
        for (want_corner, got_corner) in kernels.iter().zip(recovered.iter()) {
            for (want, got) in want_corner.iter().zip(got_corner.iter()) {
                for (a, b) in want.iter().zip(got.iter()) {
                    assert!((a - b).abs() < 1.0e-8, "kernel import drift: {a} vs {b}");
                }
            }
        }
    }
}
