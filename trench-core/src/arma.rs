//! Deterministic ARMA (pole-zero) corner fit.
//!
//! Fits a 6-biquad cascade — numerator `B(z)` and denominator `A(z)`, each order
//! 12 — to a dropped sound's spectral envelope by frequency-domain least squares
//! (Sanathanan–Koerner / Steiglitz–McBride iteration against a *minimum-phase*
//! target built from the magnitude). Unlike all-pole LPC, the moving-average part
//! places real **zeros**: the anti-formant notches and bitey upper teeth of
//! E-mu/X3 frames (DJ Alkaline et al.) that an all-pole fit physically cannot
//! carve.
//!
//! The unconstrained ARMA path is a deterministic translator. The profiled path
//! additionally runs a bounded coordinate refiner after feature extraction;
//! every proposal is packed, runtime-decoded, law-checked, and measured.
//!
//! Pure Rust, no deps. The Forge calls [`fit_corner_arma`]; on any non-finite or
//! degenerate result the caller falls back to the LPC path, so the ARMA fit can
//! only improve on it, never regress below it.

use crate::cartridge::CornerData;
use crate::cascade::{NUM_COEFFS, NUM_STAGES};
use crate::lpc::levinson_from_autocorr;
use crate::minifloat::{pole_radius, PackedCorners};
use crate::response::biquad_cascade_mag_db;
use crate::stage_law::{geometry_from_words, RootPair};
use std::f64::consts::PI;

#[cfg(test)]
const ANALYSIS_SR: f64 = 22_050.0;
const ORDER: usize = 2 * NUM_STAGES; // 12 → six biquads
const N_FFT: usize = 4096;
const N_FIT: usize = 256; // log-spaced fit frequencies
const SK_ITERS: usize = 6;
const F_MIN: f64 = 55.0;
const F_MAX: f64 = 10_500.0;
const PASSTHROUGH: [f64; NUM_COEFFS] = [2.0, 1.0, 2.0, 1.0, 1.0];

/// The profiler's target domain is shape-only. Physical preset/output gain is
/// authored outside the pole-zero body, so every measured target is peak
/// aligned to this reference before fitting or reporting RMS.
pub const PROFILER_TARGET_REFERENCE_DB: f64 = 0.0;

/// Absolute packed-response safety ceiling used by the profiler's
/// analysis-by-synthesis refinement. This is intentionally independent of the
/// target's measured gain.
pub const PROFILER_HARD_CEILING_DB: f64 = 15.0;
pub const PROFILER_HARD_CEILING_PENALTY_WEIGHT: f64 = 100.0;
const PROFILER_CEILING_GRID_POINTS: usize = 512;

/// Peak-align a measured magnitude curve for profiler fitting.
///
/// Returns `(aligned_curve, source_peak_db, applied_offset_db)`. The peak is
/// measured only over the profiler's owned 55 Hz..10.5 kHz band; the same
/// additive offset is then applied to every input row so the target's physical
/// gain cannot enter a pole/zero RMS cost.
pub fn peak_normalize_curve_db(
    curve: &[(f64, f64)],
) -> Option<(Vec<(f64, f64)>, f64, f64)> {
    if curve.is_empty()
        || curve
            .iter()
            .any(|(frequency, db)| !frequency.is_finite() || *frequency <= 0.0 || !db.is_finite())
    {
        return None;
    }
    let source_peak_db = curve
        .iter()
        .filter(|(frequency, _)| (F_MIN..=F_MAX).contains(frequency))
        .map(|(_, db)| *db)
        .reduce(f64::max)?;
    let applied_offset_db = PROFILER_TARGET_REFERENCE_DB - source_peak_db;
    let aligned = curve
        .iter()
        .map(|(frequency, db)| (*frequency, *db + applied_offset_db))
        .collect();
    Some((aligned, source_peak_db, applied_offset_db))
}

// Keep authored proposals a fraction inside hard Stage Plan faces. A value on
// the exact face can quantize to the other side even though the float proposal
// was legal. This is not a tolerance on certification: packed geometry is
// still checked against the exact authored bounds below.
const PACKED_HZ_GUARD_OCT: f64 = 1.0 / 4096.0;
const PACKED_RADIUS_GUARD: f64 = 1e-5;

fn guarded_hz(value: f64, bounds: (f64, f64)) -> f64 {
    let lower = bounds.0 * 2f64.powf(PACKED_HZ_GUARD_OCT);
    let upper = bounds.1 * 2f64.powf(-PACKED_HZ_GUARD_OCT);
    if lower <= upper {
        value.clamp(lower, upper)
    } else {
        bounds.0.max(1e-9) * (bounds.1 / bounds.0.max(1e-9)).sqrt()
    }
}

fn guarded_radius(value: f64, bounds: (f64, f64)) -> f64 {
    let lower = bounds.0 + PACKED_RADIUS_GUARD;
    let upper = bounds.1 - PACKED_RADIUS_GUARD;
    if lower <= upper {
        value.clamp(lower, upper)
    } else {
        0.5 * (bounds.0 + bounds.1)
    }
}

// ── minimal complex ───────────────────────────────────────────────────────────
#[derive(Clone, Copy)]
struct Cx {
    re: f64,
    im: f64,
}
impl Cx {
    const ZERO: Cx = Cx { re: 0.0, im: 0.0 };
    fn new(re: f64, im: f64) -> Self {
        Cx { re, im }
    }
    /// e^{jθ}
    fn expj(theta: f64) -> Self {
        Cx::new(theta.cos(), theta.sin())
    }
    fn add(self, o: Cx) -> Cx {
        Cx::new(self.re + o.re, self.im + o.im)
    }
    fn sub(self, o: Cx) -> Cx {
        Cx::new(self.re - o.re, self.im - o.im)
    }
    fn mul(self, o: Cx) -> Cx {
        Cx::new(
            self.re * o.re - self.im * o.im,
            self.re * o.im + self.im * o.re,
        )
    }
    fn scale(self, s: f64) -> Cx {
        Cx::new(self.re * s, self.im * s)
    }
    fn conj(self) -> Cx {
        Cx::new(self.re, -self.im)
    }
    fn abs(self) -> f64 {
        self.re.hypot(self.im)
    }
    fn abs2(self) -> f64 {
        self.re * self.re + self.im * self.im
    }
    fn div(self, o: Cx) -> Cx {
        let d = o.abs2().max(1e-300);
        Cx::new(
            (self.re * o.re + self.im * o.im) / d,
            (self.im * o.re - self.re * o.im) / d,
        )
    }
    fn cexp(self) -> Cx {
        // e^{re + j im}
        Cx::expj(self.im).scale(self.re.exp())
    }
}

// ── iterative radix-2 FFT (in place) ───────────────────────────────────────────
fn fft(buf: &mut [Cx], inverse: bool) {
    let n = buf.len();
    if n < 2 {
        return;
    }
    // bit reversal
    let mut j = 0usize;
    for i in 1..n {
        let mut bit = n >> 1;
        while j & bit != 0 {
            j ^= bit;
            bit >>= 1;
        }
        j ^= bit;
        if i < j {
            buf.swap(i, j);
        }
    }
    let mut len = 2;
    while len <= n {
        let ang = if inverse {
            2.0 * PI / len as f64
        } else {
            -2.0 * PI / len as f64
        };
        let wlen = Cx::expj(ang);
        let half = len / 2;
        let mut i = 0;
        while i < n {
            let mut w = Cx::new(1.0, 0.0);
            for k in 0..half {
                let u = buf[i + k];
                let v = buf[i + k + half].mul(w);
                buf[i + k] = u.add(v);
                buf[i + k + half] = u.sub(v);
                w = w.mul(wlen);
            }
            i += len;
        }
        len <<= 1;
    }
    if inverse {
        let inv = 1.0 / n as f64;
        for x in buf.iter_mut() {
            *x = x.scale(inv);
        }
    }
}

// ── linear resample ─────────────────────────────────────────────────────────
fn resample(x: &[f64], sr_in: f64, sr_out: f64) -> Vec<f64> {
    if (sr_in - sr_out).abs() < 1.0 || x.len() < 2 {
        return x.to_vec();
    }
    let ratio = sr_in / sr_out;
    let n = ((x.len() as f64) / ratio).floor() as usize;
    (0..n)
        .map(|i| {
            let pos = i as f64 * ratio;
            let i0 = pos.floor() as usize;
            let f = pos - i0 as f64;
            let a = x[i0];
            let b = if i0 + 1 < x.len() { x[i0 + 1] } else { a };
            a + (b - a) * f
        })
        .collect()
}

// ── solve a small real linear system (Gaussian elimination, partial pivot) ─────
fn solve(mut a: Vec<Vec<f64>>, mut b: Vec<f64>) -> Option<Vec<f64>> {
    let n = b.len();
    for col in 0..n {
        let mut piv = col;
        let mut best = a[col][col].abs();
        for r in (col + 1)..n {
            if a[r][col].abs() > best {
                best = a[r][col].abs();
                piv = r;
            }
        }
        if best < 1e-18 {
            return None;
        }
        a.swap(col, piv);
        b.swap(col, piv);
        let d = a[col][col];
        for r in (col + 1)..n {
            let f = a[r][col] / d;
            if f != 0.0 {
                for c in col..n {
                    a[r][c] -= f * a[col][c];
                }
                b[r] -= f * b[col];
            }
        }
    }
    let mut x = vec![0.0; n];
    for i in (0..n).rev() {
        let mut s = b[i];
        for c in (i + 1)..n {
            s -= a[i][c] * x[c];
        }
        x[i] = s / a[i][i];
    }
    Some(x)
}

// ── roots of a real polynomial, coeffs high→low (Durand-Kerner) ────────────────
fn roots(coeffs: &[f64]) -> Vec<Cx> {
    // strip leading zeros
    let mut c = coeffs;
    while c.len() > 1 && c[0].abs() < 1e-15 {
        c = &c[1..];
    }
    let p = c.len() - 1;
    if p == 0 {
        return vec![];
    }
    let lead = c[0];
    let monic: Vec<Cx> = c.iter().map(|&v| Cx::new(v / lead, 0.0)).collect();
    let eval = |z: Cx| -> Cx {
        let mut acc = Cx::ZERO;
        for cc in &monic {
            acc = acc.mul(z).add(*cc);
        }
        acc
    };
    let seed = Cx::new(0.4, 0.9);
    let mut zs = Vec::with_capacity(p);
    let mut cur = Cx::new(1.0, 0.0);
    for _ in 0..p {
        zs.push(cur);
        cur = cur.mul(seed);
    }
    for _ in 0..500 {
        let mut maxd = 0.0f64;
        for i in 0..p {
            let zi = zs[i];
            let mut den = Cx::new(1.0, 0.0);
            for (j, &zj) in zs.iter().enumerate() {
                if j != i {
                    den = den.mul(zi.sub(zj));
                }
            }
            if den.abs() < 1e-300 {
                continue;
            }
            let step = eval(zi).div(den);
            zs[i] = zi.sub(step);
            maxd = maxd.max(step.abs());
        }
        if maxd < 1e-13 {
            break;
        }
    }
    zs
}

/// Whether a root list is poles (denominator) or zeros (numerator): the two are
/// brought inside the unit circle differently — see [`to_quadratics`].
#[derive(Clone, Copy, PartialEq)]
enum RootKind {
    Pole,
    Zero,
}

/// Group ALL roots of a polynomial into monic second-order sections `[1, q1, q2]`
/// — conjugate pairs become `[1, -2Re, |z|²]`, leftover real roots are paired two
/// at a time. Using every root means the product of the sections equals the
/// original polynomial (up to its leading gain), so the realized cascade response
/// is `B/A` exactly — no dropped poles or zeros.
///
/// Roots are brought inside the unit circle so the kernel coefficients land in the
/// packable minifloat box (`c1=1-|z|²∈[0,1]`, `c3=1-|pole|²∈[0,1]`):
/// - **Poles** on/outside the circle are scaled just inside (`0.999/r`) — a
///   stability fix (a pole outside diverges).
/// - **Zeros** outside the circle are reflected to their min-phase image
///   `1/conj(z) = z/|z|²`. This is *magnitude-preserving* up to a constant gain
///   (absorbed by `normalize_peak`): the LS solve for `B(z)` can land spurious
///   roots outside the circle even though the fit target is minimum-phase, and an
///   order-12 numerator over-modelling a simpler source invents huge real zeros
///   (|z|≫1) that otherwise blow `c0/c1` far past [0,1]. Reflecting restores the
///   min-phase realisation the target intended — not character shaping.
fn to_quadratics(rs: &[Cx], kind: RootKind) -> Vec<[f64; 3]> {
    let fix = |z: Cx| -> Cx {
        match kind {
            RootKind::Pole => {
                let r = z.abs();
                // Authoring resonance cap. 0.999 ≈ 12 Hz bandwidth — a runaway
                // whistle that transient/noisy sources fit invents (the ~100 dB
                // over-reach). 0.995 ≈ 60 Hz — a musical formant. The captured
                // corner must not start as a scream at Morph0/Q0; the Q axis
                // sharpens it from here when the player wants it.
                const RMAX: f64 = 0.999;
                if r >= RMAX {
                    z.scale(RMAX / r.max(1e-12))
                } else {
                    z
                }
            }
            RootKind::Zero => {
                let r2 = z.abs2();
                if r2 > 1.0 {
                    z.scale(1.0 / r2) // 1/conj(z): reflect inside, |z|→1/|z|
                } else {
                    z
                }
            }
        }
    };
    let mut taken = vec![false; rs.len()];
    let mut out = Vec::new();
    for i in 0..rs.len() {
        if taken[i] {
            continue;
        }
        taken[i] = true;
        let zi = fix(rs[i]);
        if zi.im.abs() > 1e-7 {
            // complex → consume its nearest unused conjugate as the pair
            let conj = zi.conj();
            let mut bestj = None;
            let mut bestd = f64::INFINITY;
            for (j, &zj) in rs.iter().enumerate() {
                if taken[j] {
                    continue;
                }
                let d = zj.sub(conj).abs();
                if d < bestd {
                    bestd = d;
                    bestj = Some(j);
                }
            }
            if let Some(j) = bestj {
                taken[j] = true;
            }
            out.push([1.0, -2.0 * zi.re, zi.abs2()]);
        } else {
            // real → pair with the next unused real root
            let mut r2 = 0.0;
            for (j, &zj) in rs.iter().enumerate() {
                if taken[j] || zj.im.abs() > 1e-7 {
                    continue;
                }
                taken[j] = true;
                r2 = fix(zj).re;
                break;
            }
            let r1 = zi.re;
            out.push([1.0, -(r1 + r2), r1 * r2]);
        }
    }
    out
}

/// A section's resonant angle (∝ frequency) — for ordering sections only.
fn quad_freq(q: &[f64; 3]) -> f64 {
    let r = q[2].max(0.0).sqrt();
    if r <= 1e-9 {
        return 0.0;
    }
    (-q[1] / (2.0 * r)).clamp(-1.0, 1.0).acos()
}

/// Fit a recorded sound to one corner as a six-section pole-zero cascade, in
/// kernel form. `samples` is the already-windowed slice the Forge wants fit.
/// Returns `None` if the fit is degenerate (caller falls back to LPC).
pub fn fit_corner_arma(samples: &[f64], sr_in: f64, runtime_sr: f64) -> Option<CornerData> {
    if samples.len() < 64 {
        return None;
    }
    // Author in the runtime z-plane (the E-mu rate the cartridge plays at), NOT a
    // separate analysis rate — otherwise every pole/zero warps by runtime/analysis
    // when played. (LPC already places poles at runtime_sr; this matches it.)
    let x = resample(samples, sr_in, runtime_sr);
    if x.len() < 32 {
        return None;
    }

    // ── magnitude spectrum (zero-padded FFT of the conditioned slice) ──
    let mut buf = vec![Cx::ZERO; N_FFT];
    for (i, &v) in x.iter().take(N_FFT).enumerate() {
        buf[i] = Cx::new(v, 0.0);
    }
    fft(&mut buf, false);
    let mut logmag = vec![0.0f64; N_FFT];
    for k in 0..N_FFT {
        logmag[k] = (buf[k].abs() + 1e-9).ln();
    }
    arma_fit_from_logmag(&logmag, runtime_sr)
}

/// Factorize a clean TARGET magnitude curve (sorted `(freq_hz, db)` points) into
/// one corner — the response-first path. The SAME ARMA solver, fed an audited
/// target instead of messy audio: the taste lives in the curve, the fit stays
/// dumb (no anatomy heuristics, no per-stage roles). This is how a "Target
/// Template" becomes a 6-stage cascade.
pub fn fit_corner_from_magnitude(curve: &[(f64, f64)], runtime_sr: f64) -> Option<CornerData> {
    if curve.len() < 2 {
        return None;
    }
    let half = N_FFT / 2;
    let bin_hz = runtime_sr / N_FFT as f64;
    let mut logmag = vec![0.0f64; N_FFT];
    for k in 0..N_FFT {
        let kk = if k <= half { k } else { N_FFT - k }; // symmetric spectrum
        logmag[k] = interp_db(curve, kk as f64 * bin_hz) * std::f64::consts::LN_10 / 20.0;
    }
    arma_fit_from_logmag(&logmag, runtime_sr)
}

pub const YW_DAMPING_SCALE: f64 = 0.75;
pub const YW_SHARP_RADIUS_MAX: f64 = 0.9985;
pub const MACRO_SMOOTHING_OCTAVES: f64 = 1.0;

/// Reduce pole damping without moving its frequency. The global expansion is
/// deliberately mild; a selected mountain may request a narrower measured
/// bandwidth, but never a broader one. This prevents broad body modes from
/// becoming artificial whistles while restoring genuinely high-Q formants.
fn sharpen_yw_radius(radius: f64, measured_radius: f64) -> f64 {
    let radius = radius.clamp(0.0, 1.0);
    if measured_radius <= 0.0 {
        radius
    } else {
        radius
            .powf(YW_DAMPING_SCALE)
            .max(measured_radius)
            .min(YW_SHARP_RADIUS_MAX)
    }
}

/// Fit one conjugate pole/zero stage to a heavily smoothed macro contour.
/// Frequencies are represented in octaves during the deterministic bounded
/// search. The returned response includes its best gain offset; the final
/// six-stage gain solve redistributes that scalar without changing the shape.
fn fit_macro_stage(
    macro_db: &[f64],
    fit_freq: &dyn Fn(usize) -> f64,
    runtime_sr: f64,
) -> ([f64; 4], Vec<f64>) {
    let stage_db = |p: &[f64; 4], i: usize| -> f64 {
        let pole_hz = 2f64.powf(p[0]).clamp(F_MIN, F_MAX);
        let pole_r = p[1].clamp(0.0, 0.98);
        let zero_hz = 2f64.powf(p[2]).clamp(F_MIN, F_MAX);
        let zero_r = p[3].clamp(0.0, 0.98);
        let w = 2.0 * PI * fit_freq(i) / runtime_sr;
        let wp = 2.0 * PI * pole_hz / runtime_sr;
        let wz = 2.0 * PI * zero_hz / runtime_sr;
        let z1 = Cx::expj(-w);
        let z2 = Cx::expj(-2.0 * w);
        let num = Cx::new(1.0, 0.0)
            .add(z1.scale(-2.0 * zero_r * wz.cos()))
            .add(z2.scale(zero_r * zero_r));
        let den = Cx::new(1.0, 0.0)
            .add(z1.scale(-2.0 * pole_r * wp.cos()))
            .add(z2.scale(pole_r * pole_r));
        20.0 * num.div(den).abs().max(1e-12).log10()
    };
    let evaluate = |p: &[f64; 4]| -> (f64, f64) {
        let offset = (0..N_FIT)
            .map(|i| macro_db[i] - stage_db(p, i))
            .sum::<f64>()
            / N_FIT as f64;
        let cost = (0..N_FIT)
            .map(|i| (stage_db(p, i) + offset - macro_db[i]).powi(2))
            .sum::<f64>()
            / N_FIT as f64;
        (cost, offset)
    };

    let freq_seed = [
        70.0f64, 120.0, 220.0, 400.0, 800.0, 1_600.0, 3_500.0, 8_000.0,
    ];
    let radius_seed = [0.0f64, 0.5, 0.8, 0.95];
    let mut best = [220.0f64.log2(), 0.8, 1_600.0f64.log2(), 0.8];
    let mut best_cost = f64::INFINITY;
    for &pole_hz in &freq_seed {
        for &pole_r in &radius_seed {
            for &zero_hz in &freq_seed {
                for &zero_r in &radius_seed {
                    let trial = [pole_hz.log2(), pole_r, zero_hz.log2(), zero_r];
                    let (cost, _) = evaluate(&trial);
                    if cost < best_cost {
                        best = trial;
                        best_cost = cost;
                    }
                }
            }
        }
    }
    for (frequency_step, radius_step) in [
        (0.50, 0.20),
        (0.25, 0.10),
        (0.125, 0.05),
        (0.0625, 0.025),
        (0.03125, 0.0125),
    ] {
        let mut improved = true;
        while improved {
            improved = false;
            for parameter in 0..4 {
                let step = if parameter == 0 || parameter == 2 {
                    frequency_step
                } else {
                    radius_step
                };
                for direction in [-1.0, 1.0] {
                    let mut trial = best;
                    trial[parameter] += direction * step;
                    if parameter == 0 || parameter == 2 {
                        trial[parameter] = trial[parameter].clamp(F_MIN.log2(), F_MAX.log2());
                    } else {
                        trial[parameter] = trial[parameter].clamp(0.0, 0.98);
                    }
                    let (cost, _) = evaluate(&trial);
                    if cost + 1e-12 < best_cost {
                        best = trial;
                        best_cost = cost;
                        improved = true;
                    }
                }
            }
        }
    }
    let (_, offset) = evaluate(&best);
    let response = (0..N_FIT).map(|i| stage_db(&best, i) + offset).collect();
    (
        [2f64.powf(best[0]), best[1], 2f64.powf(best[2]), best[3]],
        response,
    )
}

#[derive(Clone, Copy, Debug)]
struct PackedRefinementMetrics {
    objective: f64,
    weighted_rms_db: f64,
    plain_rms_db: f64,
    max_overshoot_db: f64,
    ceiling_penalty: f64,
    max_ceiling_excess_db: f64,
}

fn hard_ceiling_metrics(rows: &CornerData, runtime_sr: f64) -> (f64, f64) {
    let low_hz: f64 = 20.0;
    let high_hz = (runtime_sr * 0.499).max(low_hz * 2.0);
    let mut penalty_sum = 0.0;
    let mut max_excess = 0.0f64;
    let mut sample_count = 0usize;
    let mut visit = |frequency: f64| {
        if !(low_hz..=high_hz).contains(&frequency) {
            return;
        }
        let db = biquad_cascade_mag_db(rows, frequency, runtime_sr);
        if !db.is_finite() {
            penalty_sum = f64::INFINITY;
            max_excess = f64::INFINITY;
            return;
        }
        let excess = (db - PROFILER_HARD_CEILING_DB).max(0.0);
        penalty_sum += excess * excess;
        max_excess = max_excess.max(excess);
        sample_count += 1;
    };
    for index in 0..PROFILER_CEILING_GRID_POINTS {
        let t = index as f64 / (PROFILER_CEILING_GRID_POINTS - 1) as f64;
        let frequency = low_hz * (high_hz / low_hz).powf(t);
        visit(frequency);
    }
    // A log grid can still step over a razor resonance. Always inspect each
    // decoded pole centre and nearby quarter-twelfth-octave samples as well.
    for stage in rows.iter() {
        let pole_r = stage[4].sqrt();
        if !(pole_r > 0.0 && pole_r < 1.0 && stage[3].is_finite()) {
            continue;
        }
        let pole_hz = (-stage[3] / (2.0 * pole_r))
            .clamp(-1.0, 1.0)
            .acos()
            * runtime_sr
            / (2.0 * PI);
        for offset_oct in [-1.0 / 12.0, -1.0 / 24.0, 0.0, 1.0 / 24.0, 1.0 / 12.0] {
            visit(pole_hz * 2f64.powf(offset_oct));
        }
    }
    if sample_count == 0 {
        return (f64::INFINITY, f64::INFINITY);
    }
    (
        penalty_sum / sample_count as f64,
        max_excess,
    )
}

fn packed_refinement_metrics(
    corner: &CornerData,
    target_db: &[f64],
    frequencies: &[f64],
    runtime_sr: f64,
) -> Option<PackedRefinementMetrics> {
    if target_db.is_empty() || target_db.len() != frequencies.len() {
        return None;
    }
    let packed = PackedCorners::from_corner_data(&[*corner; 4]);
    let runtime = packed.interpolate_biquad(0.0, 0.0);
    if runtime.iter().any(|stage| {
        stage.iter().any(|value| !value.is_finite()) || pole_radius(stage[3], stage[4]) >= 1.0
    }) {
        return None;
    }

    let target_peak_db = target_db.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let got: Vec<f64> = frequencies
        .iter()
        .map(|&frequency| biquad_cascade_mag_db(&runtime, frequency, runtime_sr))
        .collect();
    if got.iter().any(|value| !value.is_finite()) || !target_peak_db.is_finite() {
        return None;
    }
    // Remove candidate gain from the shape cost as well. The target is already
    // peak-aligned; aligning the candidate peak makes SCALE a canonical body
    // reference, never a carrier of the source's physical loudness.
    let got_peak_db = got.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let candidate_shape_offset_db = target_peak_db - got_peak_db;

    let mut weighted_sum = 0.0;
    let mut weight_sum = 0.0;
    let mut plain_sum = 0.0;
    let mut max_overshoot = 0.0f64;
    // Six log-grid samples are approximately 1/6 octave at N_FIT=256.
    const SHOULDER: usize = 6;
    for i in 0..target_db.len() {
        let error = got[i] + candidate_shape_offset_db - target_db[i];
        let lo = i.saturating_sub(SHOULDER);
        let hi = (i + SHOULDER).min(target_db.len() - 1);
        let prominence = target_db[i] - 0.5 * (target_db[lo] + target_db[hi]);
        let mut weight = if frequencies[i] < 60.0 || frequencies[i] > 10_000.0 {
            0.2
        } else if (1_000.0..=5_000.0).contains(&frequencies[i]) {
            2.0
        } else {
            1.0
        };
        if error > 0.0 && prominence >= 2.0 {
            weight *= 5.0;
        }
        weighted_sum += weight * error * error;
        weight_sum += weight;
        plain_sum += error * error;
        max_overshoot = max_overshoot.max(error);
    }
    let weighted_rms_db = (weighted_sum / weight_sum.max(1e-30)).sqrt();
    let plain_rms_db = (plain_sum / target_db.len() as f64).sqrt();
    let (ceiling_penalty, max_ceiling_excess_db) = hard_ceiling_metrics(&runtime, runtime_sr);
    Some(PackedRefinementMetrics {
        objective: weighted_rms_db
            + PROFILER_HARD_CEILING_PENALTY_WEIGHT * ceiling_penalty,
        weighted_rms_db,
        plain_rms_db,
        max_overshoot_db: max_overshoot,
        ceiling_penalty,
        max_ceiling_excess_db,
    })
}

/// Two-step poles-first fit (Yule-Walker/LPC + valley-constrained zeros).
///
/// Step 1 — MACRO BODY: one bounded pole/zero stage fits a heavily smoothed
/// contour. Step 2 — RESIDUAL POLES: Levinson-Durbin solves the Yule-Walker
/// equations for a 24th-order candidate bank. Five modes registered to the
/// highest residual formant crests are LOCKED.
/// Step 3 — ZEROS SECOND: zero centres are fixed in residual inter-formant and
/// exterior valleys. A deterministic depth-only solve shapes those basins;
/// near-pole zeros are reassigned instead of cancelling a locked crest.
#[derive(Clone, Copy, Debug)]
pub struct ResidualLaneBand {
    pub pole_hz: (f64, f64),
    pub zero_hz: (f64, f64),
    pub pole_r: (f64, f64),
    pub zero_r: (f64, f64),
}

#[derive(Clone, Copy, Debug)]
pub struct PackedRefinementReport {
    pub evaluations: usize,
    pub weighted_objective_before_db: f64,
    pub weighted_objective_after_db: f64,
    pub weighted_rms_before_db: f64,
    pub weighted_rms_after_db: f64,
    pub plain_rms_before_db: f64,
    pub plain_rms_after_db: f64,
    pub max_overshoot_before_db: f64,
    pub max_overshoot_after_db: f64,
    pub hard_ceiling_penalty_before: f64,
    pub hard_ceiling_penalty_after: f64,
    pub max_ceiling_excess_before_db: f64,
    pub max_ceiling_excess_after_db: f64,
}

pub fn fit_corner_poles_first(curve: &[(f64, f64)], runtime_sr: f64) -> Option<CornerData> {
    fit_corner_poles_first_impl(curve, runtime_sr, None).map(|result| result.0)
}

/// Stage-plan-aware profiler. Slot 0 owns the fitted macro-body stage; the five
/// supplied bands own slots 1..5 in exactly the supplied order. No sorting or
/// cross-band reassignment is permitted.
pub fn fit_corner_profiled(
    curve: &[(f64, f64)],
    runtime_sr: f64,
    bands: &[ResidualLaneBand; NUM_STAGES - 1],
) -> Option<CornerData> {
    fit_corner_profiled_with_report(curve, runtime_sr, bands).map(|result| result.0)
}

pub fn fit_corner_profiled_with_report(
    curve: &[(f64, f64)],
    runtime_sr: f64,
    bands: &[ResidualLaneBand; NUM_STAGES - 1],
) -> Option<(CornerData, PackedRefinementReport)> {
    let (corner, report) = fit_corner_poles_first_impl(curve, runtime_sr, Some(bands))?;
    Some((corner, report?))
}

fn fit_corner_poles_first_impl(
    curve: &[(f64, f64)],
    runtime_sr: f64,
    bands: Option<&[ResidualLaneBand; NUM_STAGES - 1]>,
) -> Option<(CornerData, Option<PackedRefinementReport>)> {
    if curve.len() < 2 {
        return None;
    }
    let half = N_FFT / 2;
    let bin_hz = runtime_sr / N_FFT as f64;
    let fit_freq = |i: usize| -> f64 {
        let t = i as f64 / (N_FIT - 1) as f64;
        F_MIN * (F_MAX / F_MIN).powf(t)
    };
    let measured_db_raw: Vec<f64> = (0..N_FIT).map(|i| interp_db(curve, fit_freq(i))).collect();
    let measured_peak_db = measured_db_raw
        .iter()
        .copied()
        .fold(f64::NEG_INFINITY, f64::max);
    if !measured_peak_db.is_finite() {
        return None;
    }
    let measured_alignment_db = PROFILER_TARGET_REFERENCE_DB - measured_peak_db;
    let measured_db: Vec<f64> = measured_db_raw
        .iter()
        .map(|db| db + measured_alignment_db)
        .collect();

    // Peel a broad macro body from the untouched measured TF. The triangular
    // one-octave smoother follows global tilt and body width but cannot retain
    // narrow formants. Yule-Walker sees only the dB residual, so no arbitrary
    // pre-emphasis changes a crest's amplitude relative to its local body.
    let log_step_oct = (F_MAX / F_MIN).log2() / (N_FIT - 1) as f64;
    let macro_half = ((0.5 * MACRO_SMOOTHING_OCTAVES / log_step_oct).round() as usize).max(1);
    let macro_db: Vec<f64> = (0..N_FIT)
        .map(|i| {
            let lo = i.saturating_sub(macro_half);
            let hi = (i + macro_half).min(N_FIT - 1);
            let mut weighted = 0.0;
            let mut weight_sum = 0.0;
            for (j, &db) in measured_db.iter().enumerate().take(hi + 1).skip(lo) {
                let distance = i.abs_diff(j) as f64;
                let weight = (macro_half as f64 + 1.0 - distance).max(0.0);
                weighted += weight * db;
                weight_sum += weight;
            }
            weighted / weight_sum.max(1e-12)
        })
        .collect();
    let (macro_stage, fitted_macro_db) = fit_macro_stage(&macro_db, &fit_freq, runtime_sr);
    let residual_db: Vec<f64> = measured_db
        .iter()
        .zip(&fitted_macro_db)
        .map(|(measured, fitted_macro)| measured - fitted_macro)
        .collect();
    let residual_curve: Vec<(f64, f64)> =
        (0..N_FIT).map(|i| (fit_freq(i), residual_db[i])).collect();
    let mut logmag = vec![0.0f64; N_FFT];
    for k in 0..N_FFT {
        let kk = if k <= half { k } else { N_FFT - k };
        let source_hz = kk as f64 * bin_hz;
        logmag[k] = interp_db(&residual_curve, source_hz) * std::f64::consts::LN_10 / 20.0;
    }

    // min-phase formant envelope (identical cepstral liftering to the ARMA path)
    let mut cep = vec![Cx::ZERO; N_FFT];
    for k in 0..N_FFT {
        cep[k] = Cx::new(logmag[k], 0.0);
    }
    fft(&mut cep, true);
    let lifter = 64usize.min(half - 1);
    let mut mp = vec![Cx::ZERO; N_FFT];
    mp[0] = Cx::new(cep[0].re, 0.0);
    for n in 1..lifter {
        mp[n] = Cx::new(2.0 * cep[n].re, 0.0);
    }
    fft(&mut mp, false);
    let hmin: Vec<Cx> = (0..N_FFT).map(|k| mp[k].cexp()).collect();

    // Log-grid copy of the liftered acoustic envelope. Selection and the
    // second-pass error are both evaluated here so bass formants get the same
    // number of observations as upper formants.
    let env_db: Vec<f64> = (0..N_FIT)
        .map(|i| {
            let t = i as f64 / (N_FIT - 1) as f64;
            let f = F_MIN * (F_MAX / F_MIN).powf(t);
            let pos = f / bin_hz;
            let k0 = (pos.floor() as usize).min(half - 1);
            let frac = pos - k0 as f64;
            let m = hmin[k0].abs() * (1.0 - frac) + hmin[k0 + 1].abs() * frac;
            20.0 * m.max(1e-9).log10()
        })
        .collect();
    // Preserve the source's broad tilt and edge cuts in the zero/gain pass.
    // Cepstral liftering is excellent for locating formants but deliberately
    // rounds sharp low/high boundaries; fitting only that envelope caused the
    // orange response to become a broad shelf. A short log-grid average removes
    // harmonic teeth while retaining the measured acoustic contour.
    let fit_db: Vec<f64> = (0..N_FIT)
        .map(|i| {
            let lo = i.saturating_sub(3);
            let hi = (i + 3).min(N_FIT - 1);
            measured_db[lo..=hi].iter().sum::<f64>() / (hi - lo + 1) as f64
        })
        .collect();
    let measured_radius_at = |hz: f64| -> f64 {
        let index_at = |frequency: f64| -> usize {
            (((frequency / F_MIN).ln() / (F_MAX / F_MIN).ln()) * (N_FIT - 1) as f64)
                .round()
                .clamp(0.0, (N_FIT - 1) as f64) as usize
        };
        let centre = index_at(hz);
        let shoulder_oct = 1.0 / 6.0;
        let lo_shoulder = index_at(hz / 2f64.powf(shoulder_oct));
        let hi_shoulder = index_at(hz * 2f64.powf(shoulder_oct));
        let prominence =
            measured_db[centre] - 0.5 * (measured_db[lo_shoulder] + measured_db[hi_shoulder]);
        if prominence < 3.0 {
            return 0.0;
        }

        // Estimate the acoustic half-prominence width on the original measured
        // contour. Limiting the drop to 3 dB makes this the
        // familiar resonator bandwidth for strong peaks, while narrower
        // 3--6 dB mountains use half their measured prominence.
        let level = measured_db[centre] - (0.5 * prominence).min(3.0);
        let mut lo = centre;
        while lo > 0 && measured_db[lo] > level {
            lo -= 1;
        }
        let mut hi = centre;
        while hi < N_FIT - 1 && measured_db[hi] > level {
            hi += 1;
        }
        let bandwidth_hz = (fit_freq(hi) - fit_freq(lo)).max(20.0);
        let bandwidth_radius = (-PI * bandwidth_hz / runtime_sr).exp();
        // Width alone can turn a modest narrow crest into a whistle. Bound the
        // expansion by its measured prominence: 3 dB permits r=.93 and each
        // additional dB permits another .01, capped below the stability rim.
        let prominence_radius = (0.90 + 0.01 * prominence).clamp(0.90, 0.985);
        bandwidth_radius.min(prominence_radius)
    };
    // ── Step 2: TRUE YULE-WALKER LPC, THEN LOCK FIVE RESIDUAL MOUNTAINS ──
    // Wiener-Khinchin: the inverse FFT of |H|² is the autocorrelation sequence
    // Yule-Walker needs. A 24th-order analysis supplies a candidate bank; the
    // five pole pairs whose centres sit highest on the residual envelope win;
    // the sixth authored lane is already owned by the macro-body stage.
    // This avoids both failures of the old path: no linear-Hz bin-count bias,
    // and no dependence on finding six explicit local maxima after liftering.
    const LPC_ANALYSIS_ORDER: usize = 24;
    const MIN_POLE_SEPARATION_OCT: f64 = 1.0 / 4.0;
    const RESIDUAL_STAGES: usize = NUM_STAGES - 1;
    let mut power: Vec<Cx> = hmin
        .iter()
        .map(|h| Cx::new(h.abs2().max(1e-18), 0.0))
        .collect();
    fft(&mut power, true);
    let autocorr: Vec<f64> = power
        .iter()
        .take(LPC_ANALYSIS_ORDER + 1)
        .map(|v| v.re)
        .collect();
    let a_lpc = levinson_from_autocorr(&autocorr, LPC_ANALYSIS_ORDER)?;

    let env_at = |hz: f64| -> f64 {
        let x = ((hz / F_MIN).ln() / (F_MAX / F_MIN).ln()) * (N_FIT - 1) as f64;
        let i0 = x.floor().clamp(0.0, (N_FIT - 2) as f64) as usize;
        let t = (x - i0 as f64).clamp(0.0, 1.0);
        env_db[i0] * (1.0 - t) + env_db[i0 + 1] * t
    };
    let lpc_modes: Vec<(f64, f64)> = roots(&a_lpc)
        .into_iter()
        .filter(|z| z.im > 1e-7)
        .filter_map(|z| {
            let radius = z.abs();
            if !(radius > 0.0 && radius < 1.0) {
                return None;
            }
            let hz = z.im.atan2(z.re) * runtime_sr / (2.0 * PI);
            if !(F_MIN..=F_MAX).contains(&hz) {
                return None;
            }
            Some((hz, radius))
        })
        .collect();
    let score_mode = |hz: f64| -> f64 {
        // Rank by the liftered acoustic envelope, not raw harmonic teeth.
        // The lightly smoothed measured contour is retained for valleys and
        // broadband gain in Step 2.
        let shoulder =
            0.5 * (env_at(hz / 2f64.powf(1.0 / 6.0)) + env_at(hz * 2f64.powf(1.0 / 6.0)));
        let prominence = env_at(hz) - shoulder;
        env_at(hz) + 2.0 * prominence.max(0.0)
    };
    let mut pole_candidates: Vec<(f64, f64, f64)> = lpc_modes
        .iter()
        .map(|&(hz, radius)| (score_mode(hz), hz, radius))
        .collect();

    // Root angles from a finite-order LPC model can sit on a shoulder of a
    // broad measured formant. Add each explicit envelope crest as a refined
    // centre, borrowing bandwidth from the nearest Yule-Walker mode. This is
    // still LPC pole estimation—the measured maximum only registers the pole
    // to the acoustic mountain instead of leaving it half a bin down-slope.
    for peaks_db in [&env_db] {
        for i in 1..N_FIT - 1 {
            if !(peaks_db[i] > peaks_db[i - 1] && peaks_db[i] >= peaks_db[i + 1]) {
                continue;
            }
            let hz = fit_freq(i);
            let nearest = lpc_modes.iter().min_by(|a, b| {
                (hz / a.0)
                    .log2()
                    .abs()
                    .partial_cmp(&(hz / b.0).log2().abs())
                    .unwrap()
            });
            let radius = if let Some(&(mode_hz, mode_r)) = nearest {
                if (hz / mode_hz).log2().abs() <= 0.5 {
                    mode_r
                } else {
                    0.0
                }
            } else {
                0.0
            };
            let radius = if radius > 0.0 {
                radius
            } else {
                // Honest measured-bandwidth fallback when LPC has no nearby
                // complex mode (for example a broad body peak represented by a
                // real low-frequency pole).
                let top = peaks_db[i];
                let mut lo = i;
                while lo > 0 && peaks_db[lo] > top - 3.0 {
                    lo -= 1;
                }
                let mut hi = i;
                while hi < N_FIT - 1 && peaks_db[hi] > top - 3.0 {
                    hi += 1;
                }
                let bw = (fit_freq(hi) - fit_freq(lo)).clamp(20.0, hz);
                (-PI * bw / runtime_sr).exp()
            };
            if pole_candidates
                .iter()
                .all(|&(_, other, _)| (hz / other).log2().abs() > 1.0 / 48.0)
            {
                pole_candidates.push((score_mode(hz), hz, radius));
            }
        }
    }
    let mut poles: Vec<(f64, f64)> = Vec::with_capacity(RESIDUAL_STAGES);
    if let Some(lane_bands) = bands {
        for band in lane_bands {
            if !(band.pole_hz.0 >= F_MIN
                && band.pole_hz.0 < band.pole_hz.1
                && band.pole_hz.1 <= F_MAX)
                || !(0.0 <= band.pole_r.0
                    && band.pole_r.0 <= band.pole_r.1
                    && band.pole_r.1 <= YW_SHARP_RADIUS_MAX)
            {
                return None;
            }
            let &(_, hz, radius) = pole_candidates
                .iter()
                .filter(|candidate| candidate.1 >= band.pole_hz.0 && candidate.1 <= band.pole_hz.1)
                .max_by(|a, b| a.0.partial_cmp(&b.0).unwrap())?;
            poles.push((
                hz,
                sharpen_yw_radius(radius, measured_radius_at(hz))
                    .clamp(band.pole_r.0, band.pole_r.1),
            ));
        }
    } else {
        pole_candidates.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
        for &(_, hz, radius) in &pole_candidates {
            if poles
                .iter()
                .all(|&(other, _)| (hz / other).log2().abs() >= MIN_POLE_SEPARATION_OCT)
            {
                poles.push((
                    hz,
                    sharpen_yw_radius(radius, measured_radius_at(hz))
                        .clamp(0.5, YW_SHARP_RADIUS_MAX),
                ));
                if poles.len() == RESIDUAL_STAGES {
                    break;
                }
            }
        }
        // If the candidate bank contains a close doublet, relax separation
        // rather than inventing an identity/gain-only lane.
        if poles.len() < RESIDUAL_STAGES {
            for &(_, hz, radius) in &pole_candidates {
                if poles.iter().any(|&(other, _)| (hz - other).abs() < 1e-6) {
                    continue;
                }
                poles.push((
                    hz,
                    sharpen_yw_radius(radius, measured_radius_at(hz))
                        .clamp(0.5, YW_SHARP_RADIUS_MAX),
                ));
                if poles.len() == RESIDUAL_STAGES {
                    break;
                }
            }
        }
    }
    if poles.len() != RESIDUAL_STAGES {
        return None;
    }
    if bands.is_none() {
        poles.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
    }

    // ── Step 2: ZERO CENTRES IN MEASURED VALLEYS, POLES IMMUTABLE ──
    // Candidate inter-formant valleys come from the minima between the six
    // locked mountains; the final six also retain both exterior basins so the
    // source's broad low/high contour survives. Unlike the old unconstrained
    // B-polynomial solve, a zero can no longer wander onto a pole and erase the
    // formant we just selected.
    let nearest_index = |hz: f64| -> usize {
        (((hz / F_MIN).ln() / (F_MAX / F_MIN).ln()) * (N_FIT - 1) as f64)
            .round()
            .clamp(0.0, (N_FIT - 1) as f64) as usize
    };
    let valley_indices = if let Some(lane_bands) = bands {
        let mut selected = Vec::with_capacity(RESIDUAL_STAGES);
        for band in lane_bands {
            if !(band.zero_hz.0 >= F_MIN
                && band.zero_hz.0 < band.zero_hz.1
                && band.zero_hz.1 <= F_MAX)
                || !(0.0 <= band.zero_r.0
                    && band.zero_r.0 <= band.zero_r.1
                    && band.zero_r.1 <= 0.995)
            {
                return None;
            }
            // Keep one analysis-grid sample inside each authored edge so the
            // packed frequency word has room to quantize without escaping.
            let edge_lo = nearest_index(band.zero_hz.0);
            let edge_hi = nearest_index(band.zero_hz.1);
            let lo = (edge_lo + 1).min(edge_hi);
            let hi = edge_hi.saturating_sub(1).max(lo);
            selected.push(
                (lo..=hi).min_by(|&a, &b| residual_db[a].partial_cmp(&residual_db[b]).unwrap())?,
            );
        }
        selected
    } else {
        let mut interior_valleys = Vec::with_capacity(RESIDUAL_STAGES - 1);
        for pair in poles.windows(2) {
            // Keep a 1/8-octave exclusion around both locked pole centres.
            let lo = nearest_index(pair[0].0 * 2f64.powf(1.0 / 8.0)).min(N_FIT - 1);
            let hi = nearest_index(pair[1].0 / 2f64.powf(1.0 / 8.0)).min(N_FIT - 1);
            let (lo, hi) = if lo < hi {
                (lo, hi)
            } else {
                let mid = nearest_index((pair[0].0 * pair[1].0).sqrt());
                (mid, mid)
            };
            let valley =
                (lo..=hi).min_by(|&a, &b| residual_db[a].partial_cmp(&residual_db[b]).unwrap())?;
            interior_valleys.push(valley);
        }
        let first = nearest_index(poles[0].0 / 2f64.powf(1.0 / 8.0));
        let last = nearest_index(poles[RESIDUAL_STAGES - 1].0 * 2f64.powf(1.0 / 8.0));
        let low =
            (0..=first).min_by(|&a, &b| residual_db[a].partial_cmp(&residual_db[b]).unwrap())?;
        let high =
            (last..N_FIT).min_by(|&a, &b| residual_db[a].partial_cmp(&residual_db[b]).unwrap())?;
        interior_valleys.sort_by(|&a, &b| residual_db[a].partial_cmp(&residual_db[b]).unwrap());
        interior_valleys.truncate(RESIDUAL_STAGES - 2);
        interior_valleys.push(low);
        interior_valleys.push(high);
        interior_valleys.sort_unstable();
        interior_valleys
    };
    let legal_zero = |hz: f64| {
        (hz / macro_stage[0]).log2().abs() >= 1.0 / 12.0
            && poles
                .iter()
                .all(|&(pole_hz, _)| (hz / pole_hz).log2().abs() >= 1.0 / 12.0)
    };
    let mut zero_hz: Vec<f64> = valley_indices.into_iter().map(fit_freq).collect();
    for (zero_index, hz) in zero_hz.iter_mut().enumerate() {
        if legal_zero(*hz) {
            continue;
        }
        // Quantization and close pole doublets can erase the narrow nominal
        // exclusion interval. Re-register to the nearest legal measured basin;
        // duplication is preferable to either pole cancellation or an all-pole
        // gain-only lane.
        let original = *hz;
        let replacement = (0..N_FIT)
            .filter(|&i| {
                let frequency = fit_freq(i);
                let inside_authored_band = bands.map_or(true, |lane_bands| {
                    frequency > lane_bands[zero_index].zero_hz.0
                        && frequency < lane_bands[zero_index].zero_hz.1
                });
                inside_authored_band && legal_zero(frequency)
            })
            .min_by(|&a, &b| {
                let ca = (fit_freq(a) / original).log2().abs() + 0.01 * fit_db[a];
                let cb = (fit_freq(b) / original).log2().abs() + 0.01 * fit_db[b];
                ca.partial_cmp(&cb).unwrap()
            })?;
        *hz = fit_freq(replacement);
    }
    if bands.is_none() {
        zero_hz.sort_by(|a, b| a.partial_cmp(b).unwrap());
    }

    let make_corner = |trial_poles: &[(f64, f64)],
                       trial_zero_hz: &[f64],
                       trial_zero_r: &[f64],
                       gain: f64|
     -> CornerData {
        let mut out = [PASSTHROUGH; NUM_STAGES];
        let [macro_pole_hz, macro_pole_r, macro_zero_hz, macro_zero_r] = macro_stage;
        let macro_wp = 2.0 * PI * macro_pole_hz / runtime_sr;
        let macro_wz = 2.0 * PI * macro_zero_hz / runtime_sr;
        out[0] = [
            2.0 - 2.0 * macro_zero_r * macro_wz.cos(),
            1.0 - macro_zero_r * macro_zero_r,
            2.0 - 2.0 * macro_pole_r * macro_wp.cos(),
            1.0 - macro_pole_r * macro_pole_r,
            gain,
        ];
        for i in 0..RESIDUAL_STAGES {
            let (pole_hz, pole_r) = trial_poles[i];
            let wp = 2.0 * PI * pole_hz / runtime_sr;
            let wz = 2.0 * PI * trial_zero_hz[i] / runtime_sr;
            let rz = if let Some(lane_bands) = bands {
                trial_zero_r[i].clamp(lane_bands[i].zero_r.0, lane_bands[i].zero_r.1)
            } else {
                trial_zero_r[i].clamp(0.0, 0.995)
            };
            let a1 = -2.0 * pole_r * wp.cos();
            let a2 = pole_r * pole_r;
            let b1 = -2.0 * rz * wz.cos();
            let b2 = rz * rz;
            out[i + 1] = [2.0 + b1, 1.0 - b2, a1 + 2.0, 1.0 - a2, gain];
        }
        out
    };
    let response_db = |corner: &CornerData, i: usize| -> f64 {
        let w = 2.0 * PI * fit_freq(i) / runtime_sr;
        let z1 = Cx::expj(-w);
        let z2 = Cx::expj(-2.0 * w);
        let mut h = Cx::new(1.0, 0.0);
        for k in corner {
            let b0 = k[4];
            let num = Cx::new(b0, 0.0)
                .add(z1.scale((k[0] - 2.0) * b0))
                .add(z2.scale((1.0 - k[1]) * b0));
            let den = Cx::new(1.0, 0.0)
                .add(z1.scale(k[2] - 2.0))
                .add(z2.scale(1.0 - k[3]));
            h = h.mul(num.div(den));
        }
        20.0 * h.abs().max(1e-12).log10()
    };
    let shape_cost = |zero_r: &[f64]| -> (f64, f64) {
        let corner = make_corner(&poles, &zero_hz, zero_r, 1.0);
        let got: Vec<f64> = (0..N_FIT).map(|i| response_db(&corner, i)).collect();
        let offset = fit_db
            .iter()
            .zip(&got)
            .map(|(want, have)| want - have)
            .sum::<f64>()
            / N_FIT as f64;
        let cost = fit_db
            .iter()
            .zip(&got)
            .map(|(want, have)| (have + offset - want).powi(2))
            .sum::<f64>()
            / N_FIT as f64;
        (cost, offset)
    };

    // Deterministic coordinate descent changes zero DEPTH only. Pole centre,
    // pole radius, and every zero centre are frozen before this loop begins.
    let mut zero_r: Vec<f64> = (0..RESIDUAL_STAGES)
        .map(|i| {
            bands.map_or(0.85, |lane_bands| {
                0.85f64.clamp(lane_bands[i].zero_r.0, lane_bands[i].zero_r.1)
            })
        })
        .collect();
    let (mut best, _) = shape_cost(&zero_r);
    for step in [0.20, 0.10, 0.05, 0.025, 0.0125] {
        let mut improved = true;
        while improved {
            improved = false;
            for i in 0..RESIDUAL_STAGES {
                for direction in [-1.0, 1.0] {
                    let mut trial = zero_r.clone();
                    trial[i] = if let Some(lane_bands) = bands {
                        (trial[i] + direction * step)
                            .clamp(lane_bands[i].zero_r.0, lane_bands[i].zero_r.1)
                    } else {
                        (trial[i] + direction * step).clamp(0.0, 0.995)
                    };
                    let (cost, _) = shape_cost(&trial);
                    if cost + 1e-10 < best {
                        zero_r = trial;
                        best = cost;
                        improved = true;
                    }
                }
            }
        }
    }
    let (_, offset_db) = shape_cost(&zero_r);
    let per_stage_gain = 10f64
        .powf(offset_db / (20.0 * NUM_STAGES as f64))
        .clamp(1e-6, 4.0);
    let corner = make_corner(&poles, &zero_hz, &zero_r, per_stage_gain);
    if !corner.iter().flatten().all(|value| value.is_finite()) {
        return None;
    }
    let Some(lane_bands) = bands else {
        return Some((corner, None));
    };

    // Analysis-by-synthesis: every candidate is encoded to packed words,
    // decoded through PackedCorners, and measured on the runtime rows. The
    // design-space values are only proposal coordinates.
    let frequencies: Vec<f64> = (0..N_FIT).map(fit_freq).collect();
    let mut refined_poles = poles;
    let mut refined_zero_hz = zero_hz;
    let mut refined_zero_r = zero_r;
    for lane in 0..RESIDUAL_STAGES {
        refined_poles[lane].0 = guarded_hz(refined_poles[lane].0, lane_bands[lane].pole_hz);
        refined_poles[lane].1 = guarded_radius(refined_poles[lane].1, lane_bands[lane].pole_r);
        refined_zero_hz[lane] = guarded_hz(refined_zero_hz[lane], lane_bands[lane].zero_hz);
        refined_zero_r[lane] = guarded_radius(refined_zero_r[lane], lane_bands[lane].zero_r);
    }
    // Gain is fixed to the canonical shape-aligned reference established by
    // shape_cost. The AbS loop is not allowed to reintroduce source loudness
    // through SCALE.
    let total_gain_db = 20.0 * NUM_STAGES as f64 * per_stage_gain.log10();
    let evaluate = |trial_poles: &[(f64, f64)],
                    trial_zero_hz: &[f64],
                    trial_zero_r: &[f64]|
     -> Option<(CornerData, PackedRefinementMetrics)> {
        let gain = 10f64
            .powf(total_gain_db / (20.0 * NUM_STAGES as f64))
            .clamp(1e-6, 4.0);
        let candidate = make_corner(trial_poles, trial_zero_hz, trial_zero_r, gain);
        let packed = PackedCorners::from_corner_data(&[candidate; 4]);
        for (lane, bounds) in lane_bands.iter().enumerate() {
            let geometry = geometry_from_words(packed.words[0][lane + 1]);
            let (pole_hz, pole_r) = match geometry.pole {
                RootPair::Conjugate { hz, r } => (hz, r),
                _ => return None,
            };
            let (zero_hz, zero_r) = match geometry.zero {
                RootPair::Conjugate { hz, r } => (hz, r),
                _ => return None,
            };
            if !(bounds.pole_hz.0 <= pole_hz
                && pole_hz <= bounds.pole_hz.1
                && bounds.pole_r.0 <= pole_r
                && pole_r <= bounds.pole_r.1
                && bounds.zero_hz.0 <= zero_hz
                && zero_hz <= bounds.zero_hz.1
                && bounds.zero_r.0 <= zero_r
                && zero_r <= bounds.zero_r.1)
            {
                return None;
            }
        }
        let metrics =
            packed_refinement_metrics(&candidate, &measured_db, &frequencies, runtime_sr)?;
        Some((candidate, metrics))
    };
    let (mut refined_corner, before) = evaluate(
        &refined_poles,
        &refined_zero_hz,
        &refined_zero_r,
    )?;
    let mut current = before;
    let mut evaluations = 1usize;

    for (frequency_step_oct, radius_step) in [
        (1.0 / 24.0, 0.020),
        (1.0 / 48.0, 0.010),
        (1.0 / 96.0, 0.005),
        (1.0 / 192.0, 0.0025),
        (1.0 / 384.0, 0.001),
    ] {
        let mut improved = true;
        while improved {
            improved = false;
            // High lanes first: overlap overshoots are most expensive there.
            for lane in (0..RESIDUAL_STAGES).rev() {
                for coordinate in 0..4 {
                    for direction in [-1.0, 1.0] {
                        let mut trial_poles = refined_poles.clone();
                        let mut trial_zero_hz = refined_zero_hz.clone();
                        let mut trial_zero_r = refined_zero_r.clone();
                        match coordinate {
                            0 => {
                                trial_poles[lane].0 = guarded_hz(
                                    trial_poles[lane].0 * 2f64.powf(direction * frequency_step_oct),
                                    lane_bands[lane].pole_hz,
                                );
                            }
                            1 => {
                                trial_poles[lane].1 = guarded_radius(
                                    trial_poles[lane].1 + direction * radius_step,
                                    lane_bands[lane].pole_r,
                                );
                            }
                            2 => {
                                trial_zero_hz[lane] = guarded_hz(
                                    trial_zero_hz[lane] * 2f64.powf(direction * frequency_step_oct),
                                    lane_bands[lane].zero_hz,
                                );
                            }
                            _ => {
                                trial_zero_r[lane] = guarded_radius(
                                    trial_zero_r[lane] + direction * radius_step,
                                    lane_bands[lane].zero_r,
                                );
                            }
                        }
                        if trial_zero_hz.iter().any(|&zero| {
                            trial_poles
                                .iter()
                                .any(|&(pole, _)| (zero / pole).log2().abs() < 1.0 / 24.0)
                        }) {
                            continue;
                        }
                        evaluations += 1;
                        if let Some((candidate, metrics)) =
                            evaluate(&trial_poles, &trial_zero_hz, &trial_zero_r)
                        {
                            if metrics.objective + 1e-9 < current.objective
                                && metrics.plain_rms_db <= before.plain_rms_db + 1e-9
                            {
                                refined_poles = trial_poles;
                                refined_zero_hz = trial_zero_hz;
                                refined_zero_r = trial_zero_r;
                                refined_corner = candidate;
                                current = metrics;
                                improved = true;
                            }
                        }
                    }
                }
            }
        }
    }
    Some((
        refined_corner,
        Some(PackedRefinementReport {
            evaluations,
            weighted_objective_before_db: before.objective,
            weighted_objective_after_db: current.objective,
            weighted_rms_before_db: before.weighted_rms_db,
            weighted_rms_after_db: current.weighted_rms_db,
            plain_rms_before_db: before.plain_rms_db,
            plain_rms_after_db: current.plain_rms_db,
            max_overshoot_before_db: before.max_overshoot_db,
            max_overshoot_after_db: current.max_overshoot_db,
            hard_ceiling_penalty_before: before.ceiling_penalty,
            hard_ceiling_penalty_after: current.ceiling_penalty,
            max_ceiling_excess_before_db: before.max_ceiling_excess_db,
            max_ceiling_excess_after_db: current.max_ceiling_excess_db,
        }),
    ))
}

fn interp_db(curve: &[(f64, f64)], f: f64) -> f64 {
    if f <= curve[0].0 {
        return curve[0].1;
    }
    let last = curve.len() - 1;
    if f >= curve[last].0 {
        return curve[last].1;
    }
    for w in curve.windows(2) {
        if f >= w[0].0 && f <= w[1].0 {
            let t = if w[1].0 > w[0].0 {
                (f - w[0].0) / (w[1].0 - w[0].0)
            } else {
                0.0
            };
            return w[0].1 + (w[1].1 - w[0].1) * t;
        }
    }
    curve[last].1
}

/// The ARMA solve from a log-magnitude spectrum onward — shared by the audio fit
/// (`fit_corner_arma`) and the target-curve factorizer (`fit_corner_from_magnitude`).
fn arma_fit_from_logmag(logmag: &[f64], runtime_sr: f64) -> Option<CornerData> {
    let half = N_FFT / 2;
    let bin_hz = runtime_sr / N_FFT as f64;

    // ── minimum-phase FORMANT-ENVELOPE target via cepstral liftering ──
    // Real cepstrum of the raw log-magnitude, keep only the LOW quefrencies (the
    // formant envelope), drop the high quefrencies (the pitch comb). A low-pitched
    // voice has dense harmonics the old 1/24-oct smoothing couldn't bridge, so ARMA
    // fit the loud harmonics + HF junk instead of the formants. The lifter hands it
    // the envelope to fit — the same liftering that surfaces formants cleanly.
    let mut cep = vec![Cx::ZERO; N_FFT];
    for k in 0..N_FFT {
        cep[k] = Cx::new(logmag[k], 0.0); // |buf[k]| is already symmetric (real input)
    }
    fft(&mut cep, true); // real cepstrum
    let lifter = 64usize.min(half - 1); // keep formant envelope, cut the pitch comb
    let mut mp = vec![Cx::ZERO; N_FFT];
    mp[0] = Cx::new(cep[0].re, 0.0);
    for n in 1..lifter {
        mp[n] = Cx::new(2.0 * cep[n].re, 0.0); // min-phase fold, low-quefrency only
    }
    fft(&mut mp, false); // = log of the min-phase envelope
    let hmin: Vec<Cx> = (0..N_FFT).map(|k| mp[k].cexp()).collect();

    // ── log-spaced fit frequencies + sampled target ──
    let mut omega = vec![0.0f64; N_FIT];
    let mut htarget = vec![Cx::ZERO; N_FIT];
    let mut weight = vec![0.0f64; N_FIT];
    for i in 0..N_FIT {
        let t = i as f64 / (N_FIT - 1) as f64;
        let f = F_MIN * (F_MAX / F_MIN).powf(t);
        let w = 2.0 * PI * f / runtime_sr;
        omega[i] = w;
        // sample hmin at bin position (linear interp)
        let pos = f / bin_hz;
        let k0 = pos.floor() as usize;
        let frac = pos - k0 as f64;
        let h = if k0 + 1 <= half {
            hmin[k0].scale(1.0 - frac).add(hmin[k0 + 1].scale(frac))
        } else {
            hmin[half]
        };
        htarget[i] = h;
        // TRANSPARENCY weighting (audit 2026-05-24): weight the LS by the SOURCE's
        // own magnitude, so the loud body/formants are matched and the quiet high
        // band stops dominating the equation-error solve. Uniform log weighting
        // (formerly here) was measured tilting bodied sources +20..+60 dB BRIGHT and
        // discarding the low body — the opposite of transparent. The bright tilt the
        // old comment feared comes from over-weighting the QUIET highs, not from
        // honouring energy; weighting toward the source envelope is what matches it.
        // A small floor keeps notches/valleys represented.
        weight[i] = h.abs().max(1e-4);
    }

    // ── Sanathanan–Koerner iteration: solve for a[1..=ORDER], b[0..=ORDER] ──
    // Model H(w) ≈ B(w)/A(w); each iter minimises Σ_k W_k |B - H·A|² with
    // W_k = weight_k / |A_prev(w_k)|² (A_prev = 1 on the first pass = Levi).
    let p = (ORDER + 1) + ORDER; // unknowns: b_0..b_ORDER, a_1..a_ORDER
                                 // precompute e^{-jwl} for each freq and lag
    let mut ejw = vec![vec![Cx::ZERO; ORDER + 1]; N_FIT];
    for i in 0..N_FIT {
        for l in 0..=ORDER {
            ejw[i][l] = Cx::expj(-omega[i] * l as f64);
        }
    }
    let mut a_prev = vec![0.0f64; ORDER + 1]; // a_prev[0]=1
    a_prev[0] = 1.0;
    let mut best: Option<(Vec<f64>, Vec<f64>)> = None;
    for _iter in 0..SK_ITERS {
        let mut ata = vec![vec![0.0f64; p]; p];
        let mut atb = vec![0.0f64; p];
        for i in 0..N_FIT {
            // A_prev(w_i)
            let mut ap = Cx::ZERO;
            for m in 0..=ORDER {
                ap = ap.add(ejw[i][m].scale(a_prev[m]));
            }
            let wk = weight[i] / ap.abs2().max(1e-12);
            let sw = wk.sqrt();
            // complex design row R (len p) and rhs
            let mut row = vec![Cx::ZERO; p];
            for l in 0..=ORDER {
                row[l] = ejw[i][l].scale(sw); // b_l
            }
            let h = htarget[i];
            for m in 1..=ORDER {
                row[ORDER + m] = h.mul(ejw[i][m]).scale(-sw); // a_m
            }
            let rhs = h.scale(sw);
            // accumulate Re(R^H R) and Re(R^H rhs)
            for r in 0..p {
                let rr = row[r].conj();
                atb[r] += rr.mul(rhs).re;
                for cc in r..p {
                    let v = rr.mul(row[cc]).re;
                    ata[r][cc] += v;
                    if cc != r {
                        ata[cc][r] += v;
                    }
                }
            }
        }
        for d in 0..p {
            ata[d][d] += 1e-7; // tiny ridge for conditioning
        }
        let Some(sol) = solve(ata, atb) else { break };
        let mut bco = vec![0.0f64; ORDER + 1];
        let mut aco = vec![0.0f64; ORDER + 1];
        aco[0] = 1.0;
        for l in 0..=ORDER {
            bco[l] = sol[l];
        }
        for m in 1..=ORDER {
            aco[m] = sol[ORDER + m];
        }
        if !bco.iter().chain(aco.iter()).all(|v| v.is_finite()) {
            break;
        }
        a_prev = aco.clone();
        best = Some((bco, aco));
    }
    let (bco, aco) = best?;

    // ── faithful 6-biquad realization of B(z)/A(z) ──
    // Group EVERY denominator root and EVERY numerator root into second-order
    // sections, so the cascade response equals B/A exactly (no dropped poles or
    // zeros). Order both lists by resonant frequency (conditioning only — the
    // overall response is invariant to section ordering), then section i = the
    // i-th numerator over the i-th denominator. The overall gain (B's leading
    // coeff) is absorbed by the peak normalisation below.
    let mut den = to_quadratics(&roots(&aco), RootKind::Pole);
    let mut num = to_quadratics(&roots(&bco), RootKind::Zero);
    if den.is_empty() {
        return None;
    }
    den.sort_by(|a, b| quad_freq(a).partial_cmp(&quad_freq(b)).unwrap());
    num.sort_by(|a, b| quad_freq(a).partial_cmp(&quad_freq(b)).unwrap());
    while den.len() < NUM_STAGES {
        den.push([1.0, 0.0, 0.0]);
    }
    while num.len() < NUM_STAGES {
        num.push([1.0, 0.0, 0.0]);
    }
    den.truncate(NUM_STAGES);
    num.truncate(NUM_STAGES);

    let mut corner: CornerData = [PASSTHROUGH; NUM_STAGES];
    for i in 0..NUM_STAGES {
        let [_, a1, a2] = den[i];
        let [_, b1, b2] = num[i]; // monic numerator (b0 = 1); level set below
                                  // kernel form: c0 = 2 + b1/b0, c1 = 1 - b2/b0, c2 = a1 + 2, c3 = 1 - a2, c4 = b0
        corner[i] = [2.0 + b1, 1.0 - b2, a1 + 2.0, 1.0 - a2, 1.0];
    }
    normalize_peak(&mut corner, runtime_sr, 0.5);
    if corner.iter().flatten().all(|v| v.is_finite()) {
        Some(corner)
    } else {
        None
    }
}

/// Scale the cascade so its peak magnitude ≈ `target`. The scalar gain is spread
/// evenly across the active sections (`g^(1/n)` per stage) rather than dumped on
/// one — the cascade is a product, so this is the *same* transfer function with
/// the gain merely relocated, but it keeps every `c4` inside the packable [0,4]
/// box instead of letting one stage's gain underflow/overflow the minifloat.
fn normalize_peak(corner: &mut CornerData, sr: f64, target: f64) {
    let mag_at = |k: &[f64; NUM_COEFFS], w: f64| -> f64 {
        let (c0, c1, c2, c3, c4) = (k[0], k[1], k[2], k[3], k[4]);
        let (b0, b1, b2, a1, a2) = (c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, c2 - 2.0, 1.0 - c3);
        let (cw, c2w, sw, s2w) = (w.cos(), (2.0 * w).cos(), w.sin(), (2.0 * w).sin());
        let nr = b0 + b1 * cw + b2 * c2w;
        let ni = -b1 * sw - b2 * s2w;
        let dr = 1.0 + a1 * cw + a2 * c2w;
        let di = -a1 * sw - a2 * s2w;
        ((nr * nr + ni * ni) / (dr * dr + di * di + 1e-30)).sqrt()
    };
    let mut peak = 1e-9f64;
    for i in 0..128 {
        let f = 40.0 * (16_000.0f64 / 40.0).powf(i as f64 / 127.0);
        let w = 2.0 * PI * f / sr;
        let mut mag = 1.0;
        for k in corner.iter() {
            mag *= mag_at(k, w);
        }
        peak = peak.max(mag);
    }
    let g = target / peak;
    let passth = |k: &[f64; NUM_COEFFS]| {
        (k[0] - 2.0).abs() < 1e-9
            && (k[1] - 1.0).abs() < 1e-9
            && (k[2] - 2.0).abs() < 1e-9
            && (k[3] - 1.0).abs() < 1e-9
            && (k[4] - 1.0).abs() < 1e-9
    };
    let n_active = corner.iter().filter(|k| !passth(k)).count();
    if n_active == 0 {
        return;
    }
    let per = g.powf(1.0 / n_active as f64);
    for k in corner.iter_mut() {
        if !passth(k) {
            k[4] *= per;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // magnitude (dB) of a kernel-form cascade at one frequency
    fn cascade_db(corner: &CornerData, f: f64, sr: f64) -> f64 {
        let w = 2.0 * PI * f / sr;
        let mut mag = 1.0;
        for k in corner.iter() {
            let (c0, c1, c2, c3, c4) = (k[0], k[1], k[2], k[3], k[4]);
            let (b0, b1, b2, a1, a2) = (c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, c2 - 2.0, 1.0 - c3);
            let (cw, c2w, sw, s2w) = (w.cos(), (2.0 * w).cos(), w.sin(), (2.0 * w).sin());
            let nr = b0 + b1 * cw + b2 * c2w;
            let ni = -b1 * sw - b2 * s2w;
            let dr = 1.0 + a1 * cw + a2 * c2w;
            let di = -a1 * sw - a2 * s2w;
            mag *= ((nr * nr + ni * ni) / (dr * dr + di * di + 1e-30)).sqrt();
        }
        20.0 * (mag + 1e-12).log10()
    }

    // impulse response of a known pole/zero cascade (DF2T biquads)
    fn ir(biquads: &[[f64; 5]], n: usize) -> Vec<f64> {
        let mut state = vec![[0.0f64; 2]; biquads.len()];
        (0..n)
            .map(|idx| {
                let mut s = if idx == 0 { 1.0 } else { 0.0 };
                for (i, &[b0, b1, b2, a1, a2]) in biquads.iter().enumerate() {
                    let y = b0 * s + state[i][0];
                    state[i][0] = b1 * s - a1 * y + state[i][1];
                    state[i][1] = b2 * s - a2 * y;
                    s = y;
                }
                s
            })
            .collect()
    }

    fn biquad(fp: f64, rp: f64, fz: f64, rz: f64, sr: f64) -> [f64; 5] {
        let tp = 2.0 * PI * fp / sr;
        let tz = 2.0 * PI * fz / sr;
        [
            1.0,
            -2.0 * rz * tz.cos(),
            rz * rz,
            -2.0 * rp * tp.cos(),
            rp * rp,
        ]
    }

    #[test]
    fn fft_roundtrip() {
        let mut buf: Vec<Cx> = (0..64)
            .map(|i| Cx::new((i as f64 * 0.3).sin(), 0.0))
            .collect();
        let orig = buf.clone();
        fft(&mut buf, false);
        fft(&mut buf, true);
        for (a, b) in orig.iter().zip(&buf) {
            assert!((a.re - b.re).abs() < 1e-9, "fft roundtrip drift");
        }
    }

    #[test]
    fn recovers_notch_and_peaks() {
        // a body resonance, a high resonance, and a DEEP notch between them.
        let sr = ANALYSIS_SR;
        let truth = [
            biquad(500.0, 0.95, 0.0, 0.0, sr),      // body pole
            biquad(3200.0, 0.92, 0.0, 0.0, sr),     // upper pole
            biquad(1500.0, 0.5, 1500.0, 0.985, sr), // sharp notch at 1500
        ];
        let src = ir(&truth, 4096);
        let corner = fit_corner_arma(&src, sr, sr).expect("arma fit");

        // truth response (normalised peak) vs fit, sampled across the band
        let truth_corner: CornerData = {
            let mut c = [PASSTHROUGH; NUM_STAGES];
            for (i, bq) in truth.iter().enumerate() {
                let [b0, b1, b2, a1, a2] = *bq;
                c[i] = [2.0 + b1 / b0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0];
            }
            normalize_peak(&mut c, sr, 0.5);
            c
        };

        for f in [
            200.0, 500.0, 800.0, 1100.0, 1500.0, 2000.0, 2600.0, 3200.0, 4500.0, 7000.0,
        ] {
            println!(
                "  {f:6.0}Hz  fit {:7.1}  truth {:7.1}",
                cascade_db(&corner, f, sr),
                cascade_db(&truth_corner, f, sr)
            );
        }
        // 1) the fit must carve a notch near 1500 Hz: a local min clearly below the
        //    two resonances that flank it (the 500 body and the 3200 upper peak).
        let n = cascade_db(&corner, 1500.0, sr);
        let body = cascade_db(&corner, 500.0, sr);
        let upper = cascade_db(&corner, 3200.0, sr);
        assert!(
            n < body - 8.0 && n < upper - 8.0,
            "no notch at 1500: notch={n:.1} body={body:.1} upper={upper:.1}"
        );

        // 2) broad SHAPE agreement with truth (gain-independent — the product
        //    normalises level separately, so align the means and measure contour).
        let diffs: Vec<f64> = (0..60)
            .map(|i| {
                let f = 100.0 * (9000.0f64 / 100.0).powf(i as f64 / 59.0);
                cascade_db(&corner, f, sr) - cascade_db(&truth_corner, f, sr)
            })
            .collect();
        let mean = diffs.iter().sum::<f64>() / diffs.len() as f64;
        let rms =
            (diffs.iter().map(|d| (d - mean).powi(2)).sum::<f64>() / diffs.len() as f64).sqrt();
        assert!(
            rms < 4.0,
            "envelope shape RMS too high (gain-independent): {rms:.2} dB"
        );
    }

    #[test]
    fn macro_peel_keeps_five_residual_mountains_after_packing() {
        let sr = 39_062.5;
        let planted = [800.0, 1700.0, 3200.0, 5500.0, 8500.0];
        let valleys = [1200.0, 2350.0, 4200.0, 6800.0, 10_300.0];
        let curve: Vec<(f64, f64)> = (0..512)
            .map(|i| {
                let f = F_MIN * (F_MAX / F_MIN).powf(i as f64 / 511.0);
                let mut db = -18.0 - 6.0 * (f / 1000.0).log2();
                for &peak in &planted {
                    db += 15.0 * (-0.5 * ((f / peak).log2() / 0.10).powi(2)).exp();
                }
                for &valley in &valleys {
                    db -= 7.0 * (-0.5 * ((f / valley).log2() / 0.08).powi(2)).exp();
                }
                (f, db)
            })
            .collect();

        let fitted = fit_corner_poles_first(&curve, sr).expect("two-step fit");
        assert_eq!(
            fitted,
            fit_corner_poles_first(&curve, sr).expect("repeat two-step fit"),
            "the fitter must be deterministic"
        );

        // Inspect the exact quantized/runtime-decoded result, not only the
        // design coefficients used by the solver.
        let packed = crate::minifloat::PackedCorners::from_corner_data(&[fitted; 4]);
        let runtime = packed.interpolate_biquad(0.0, 0.0);
        let mut pole_hz = Vec::new();
        let mut zero_hz = Vec::new();
        for (stage_index, stage) in runtime.iter().enumerate() {
            let pole_r = stage[4].sqrt();
            let pole_disc = stage[3] * stage[3] - 4.0 * stage[4];
            assert!(pole_disc < 0.0, "every lane must retain a conjugate pole");
            assert!(pole_r < 1.0, "packed pole must be stable: r={pole_r}");
            pole_hz.push((-stage[3] / (2.0 * pole_r)).clamp(-1.0, 1.0).acos() * sr / (2.0 * PI));

            let b0 = stage[0];
            let z1 = stage[1] / b0;
            let z2 = stage[2] / b0;
            let zero_r = z2.max(0.0).sqrt();
            if stage_index > 0 && z1 * z1 - 4.0 * z2 < 0.0 && zero_r > 0.05 {
                zero_hz.push((-z1 / (2.0 * zero_r)).clamp(-1.0, 1.0).acos() * sr / (2.0 * PI));
            }
        }
        assert_eq!(pole_hz.len(), NUM_STAGES);
        for &want in &planted {
            let nearest = pole_hz
                .iter()
                .map(|&got| (got / want).log2().abs())
                .fold(f64::INFINITY, f64::min);
            assert!(
                nearest < 0.30,
                "no locked pole near planted mountain {want} Hz; got {pole_hz:?}"
            );
        }
        for &zero in &zero_hz {
            let nearest = pole_hz
                .iter()
                .map(|&pole| (zero / pole).log2().abs())
                .fold(f64::INFINITY, f64::min);
            assert!(
                nearest >= 0.06,
                "valley zero {zero} Hz cancels a locked pole"
            );
        }

        let packed_db: Vec<f64> = (0..256)
            .map(|i| {
                let f = F_MIN * (F_MAX / F_MIN).powf(i as f64 / 255.0);
                crate::response::biquad_cascade_mag_db(&runtime, f, sr)
            })
            .collect();
        let span = packed_db.iter().copied().fold(f64::NEG_INFINITY, f64::max)
            - packed_db.iter().copied().fold(f64::INFINITY, f64::min);
        assert!(
            span > 12.0,
            "packed response collapsed toward a flat line: {span:.2} dB span"
        );

        for &want in &planted[2..] {
            let shoulder = 2f64.powf(1.0 / 6.0);
            let centre = crate::response::biquad_cascade_mag_db(&runtime, want, sr);
            let sides = 0.5
                * (crate::response::biquad_cascade_mag_db(&runtime, want / shoulder, sr)
                    + crate::response::biquad_cascade_mag_db(&runtime, want * shoulder, sr));
            assert!(
                centre > sides + 2.0,
                "packed upper formant at {want} Hz is too smooth: {:.2} dB prominence",
                centre - sides
            );
        }
    }

    #[test]
    fn profiler_peak_alignment_removes_target_gain() {
        let curve = vec![(40.0, -20.0), (100.0, -4.0), (1_000.0, 12.0), (20_000.0, -8.0)];
        let (aligned, peak, offset) = peak_normalize_curve_db(&curve).expect("peak alignment");
        assert_eq!(peak, 12.0);
        assert_eq!(offset, -12.0);
        assert_eq!(aligned[2].1, PROFILER_TARGET_REFERENCE_DB);

        let shifted: Vec<(f64, f64)> = curve.iter().map(|(f, db)| (*f, db - 17.0)).collect();
        let (shifted_aligned, shifted_peak, shifted_offset) =
            peak_normalize_curve_db(&shifted).expect("shifted peak alignment");
        assert_eq!(shifted_peak, -5.0);
        assert_eq!(shifted_offset, 5.0);
        for ((f_a, db_a), (f_b, db_b)) in aligned.iter().zip(shifted_aligned) {
            assert_eq!(*f_a, f_b);
            assert!((db_a - db_b).abs() < 1e-12);
        }
    }

    #[test]
    fn profiler_hard_ceiling_penalizes_absolute_resonance() {
        let sr = 39_062.5;
        let mut identity = [[1.0, 0.0, 0.0, 0.0, 0.0]; NUM_STAGES];
        let (identity_penalty, identity_excess) = hard_ceiling_metrics(&identity, sr);
        assert_eq!(identity_penalty, 0.0);
        assert_eq!(identity_excess, 0.0);

        let pole_hz = 1_000.0;
        let pole_r = 0.997;
        let pole_w = 2.0 * PI * pole_hz / sr;
        identity[0] = [
            1.0,
            0.0,
            0.0,
            -2.0 * pole_r * pole_w.cos(),
            pole_r * pole_r,
        ];
        let (penalty, excess) = hard_ceiling_metrics(&identity, sr);
        assert!(excess > 15.0, "expected resonance above +15 dB, got {excess:.2} dB");
        assert!(penalty > 0.0);
    }

    #[test]
    fn sharpening_is_explicit_and_bounded() {
        let broad = 0.90;
        assert_eq!(sharpen_yw_radius(broad, 0.0), broad);
        assert!(sharpen_yw_radius(broad, 0.95) >= 0.95);
        assert_eq!(sharpen_yw_radius(0.9999, 0.9999), YW_SHARP_RADIUS_MAX);
    }

    #[test]
    fn profiled_bands_own_lane_order_after_packing() {
        let sr = 39_062.5;
        let peaks = [800.0, 1700.0, 3200.0, 5500.0, 8500.0];
        let valleys = [1200.0, 2350.0, 4200.0, 6800.0, 10_000.0];
        let curve: Vec<(f64, f64)> = (0..512)
            .map(|i| {
                let f = F_MIN * (F_MAX / F_MIN).powf(i as f64 / 511.0);
                let mut db = -12.0 - 6.0 * (f / 1_000.0).log2();
                for &peak in &peaks {
                    db += 15.0 * (-0.5 * ((f / peak).log2() / 0.09).powi(2)).exp();
                }
                for &valley in &valleys {
                    db -= 6.0 * (-0.5 * ((f / valley).log2() / 0.08).powi(2)).exp();
                }
                (f, db)
            })
            .collect();
        let bands = [
            ResidualLaneBand {
                pole_hz: (650.0, 1_000.0),
                zero_hz: (1_000.0, 1_400.0),
                pole_r: (0.8, 0.99),
                zero_r: (0.1, 0.98),
            },
            ResidualLaneBand {
                pole_hz: (1_400.0, 2_100.0),
                zero_hz: (2_100.0, 2_700.0),
                pole_r: (0.8, 0.99),
                zero_r: (0.1, 0.98),
            },
            ResidualLaneBand {
                pole_hz: (2_700.0, 3_700.0),
                zero_hz: (3_700.0, 4_700.0),
                pole_r: (0.8, 0.99),
                zero_r: (0.1, 0.98),
            },
            ResidualLaneBand {
                pole_hz: (4_700.0, 6_200.0),
                zero_hz: (6_200.0, 7_500.0),
                pole_r: (0.8, 0.99),
                zero_r: (0.1, 0.98),
            },
            ResidualLaneBand {
                pole_hz: (7_500.0, 9_500.0),
                zero_hz: (9_500.0, 10_400.0),
                pole_r: (0.8, 0.99),
                zero_r: (0.1, 0.98),
            },
        ];
        let (fitted, report) =
            fit_corner_profiled_with_report(&curve, sr, &bands).expect("profiled fit");
        assert!(report.evaluations > 1);
        assert!(
            report.weighted_rms_after_db < report.weighted_rms_before_db,
            "packed refiner did not improve its weighted objective: {report:?}"
        );
        assert!(
            report.plain_rms_after_db <= report.plain_rms_before_db + 1e-9,
            "weighted optimization regressed plain RMS: {report:?}"
        );
        let packed = crate::minifloat::PackedCorners::from_corner_data(&[fitted; 4]);
        let runtime = packed.interpolate_biquad(0.0, 0.0);
        for (lane, band) in runtime[1..].iter().zip(&bands) {
            let pole_r = lane[4].sqrt();
            let pole_hz = (-lane[3] / (2.0 * pole_r)).clamp(-1.0, 1.0).acos() * sr / (2.0 * PI);
            assert!(
                pole_hz >= band.pole_hz.0 && pole_hz <= band.pole_hz.1,
                "packed lane escaped authored pole band {:?}: {pole_hz}",
                band.pole_hz
            );
            let zero_r = (lane[2] / lane[0]).max(0.0).sqrt();
            let zero_hz = (-(lane[1] / lane[0]) / (2.0 * zero_r))
                .clamp(-1.0, 1.0)
                .acos()
                * sr
                / (2.0 * PI);
            assert!(
                zero_hz >= band.zero_hz.0 && zero_hz <= band.zero_hz.1,
                "packed lane escaped authored zero band {:?}: {zero_hz}",
                band.zero_hz
            );
        }
    }
}
