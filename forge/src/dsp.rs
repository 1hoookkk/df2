//! All numeric work for the Forge: WAV IO, onset/window conditioning, the
//! six-actor fit support math, magnitude response, z-plane extraction, and the
//! response → shape features that drive the living mouth. No UI lives here.

use std::cmp::Ordering;
use std::f64::consts::{PI, TAU};
use std::path::Path;

use trench_core::cartridge::CornerData;
use trench_core::lpc;
use trench_core::minifloat::PackedCorners;

pub const POLE_ZERO_COUNT: usize = 6;
pub const AUTHORING_RATE: f64 = 39_062.5;
pub const DEFAULT_WINDOW_MS: f32 = 100.0;
pub const RESPONSE_BINS: usize = 540;
// Spectral match thresholds — RMS dB error between the fitted filter's response
// envelope and the source's smoothed spectrum. Lower is better. Any sound can be
// captured; only a genuinely bad envelope match (or non-finite) blocks.
pub const FIT_WARN_DB: f64 = 12.0; // ≤ this + formant lock = Ready
pub const FIT_BLOCK_DB: f64 = 18.0; // > this = Blocked
pub const PASSTHROUGH: [f64; 5] = [2.0, 1.0, 2.0, 1.0, 1.0];

// ── Quality gate ────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FitQuality {
    Ready,
    Review,
    Blocked,
}

impl FitQuality {
    pub fn can_assign(self) -> bool {
        self == Self::Ready
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct ComplexPoint {
    pub re: f64,
    pub im: f64,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct Peak {
    pub freq_hz: f64,
    pub db: f64,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct Valley {
    pub freq_hz: f64,
    pub db: f64,
}

#[derive(Clone, Debug)]
pub struct StageDiagnostic {
    pub role: &'static str,
    pub pole_freq_hz: f64,
    pub pole_radius: f64,
    pub zero_freq_hz: f64,
    pub zero_radius: f64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TargetMode {
    LowQGraphic,
}

#[derive(Clone, Debug)]
pub struct FitOptions {
    pub max_passes: usize,
    pub target_peak: f64,
    pub target_mode: TargetMode,
}

impl Default for FitOptions {
    fn default() -> Self {
        Self {
            max_passes: 5,
            target_peak: 0.5,
            target_mode: TargetMode::LowQGraphic,
        }
    }
}

#[derive(Clone, Debug)]
pub struct FitDiagnostics {
    pub raw_source_db: Vec<[f64; 2]>,
    pub simplified_target_db: Vec<[f64; 2]>,
    pub source_peaks: Vec<Peak>,
    pub target_valleys: Vec<Valley>,
    pub fit_peaks: Vec<Peak>,
    pub stages: Vec<StageDiagnostic>,
    pub residual_db: f64,
    pub post_pack_residual_db: f64,
    pub formant_error: f64,
    pub max_pack_drift: f64,
    pub lpc_seed_residual_db: f64,
    pub rejection_reason: String,
}

impl Default for FitDiagnostics {
    fn default() -> Self {
        Self {
            raw_source_db: Vec::new(),
            simplified_target_db: Vec::new(),
            source_peaks: Vec::new(),
            target_valleys: Vec::new(),
            fit_peaks: Vec::new(),
            stages: Vec::new(),
            residual_db: f64::INFINITY,
            post_pack_residual_db: f64::INFINITY,
            formant_error: f64::INFINITY,
            max_pack_drift: f64::INFINITY,
            lpc_seed_residual_db: f64::INFINITY,
            rejection_reason: "not fitted".to_owned(),
        }
    }
}

#[derive(Clone, Debug)]
pub struct FitResult {
    pub corner: CornerData,
    pub quality: FitQuality,
    pub diagnostics: FitDiagnostics,
}

// ── WAV load ────────────────────────────────────────────────────────────────

pub fn load_wav_as_mono_f64(path: &Path) -> Result<(Vec<f64>, f64), String> {
    let mut reader = hound::WavReader::open(path).map_err(|e| e.to_string())?;
    let spec = reader.spec();
    let channels = spec.channels.max(1) as usize;
    let raw: Vec<f64> = match spec.sample_format {
        hound::SampleFormat::Float => reader
            .samples::<f32>()
            .map(|s| s.map(|v| v as f64))
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| e.to_string())?,
        hound::SampleFormat::Int => {
            let scale = 2_f64.powi(spec.bits_per_sample.saturating_sub(1) as i32);
            reader
                .samples::<i32>()
                .map(|s| s.map(|v| v as f64 / scale))
                .collect::<Result<Vec<_>, _>>()
                .map_err(|e| e.to_string())?
        }
    };

    let mono = if channels == 1 {
        raw
    } else {
        raw.chunks(channels)
            .map(|f| f.iter().sum::<f64>() / f.len() as f64)
            .collect()
    };

    if mono.is_empty() {
        Err("audio file contained no samples".to_owned())
    } else {
        Ok((mono, spec.sample_rate as f64))
    }
}

// ── Onset / window conditioning ─────────────────────────────────────────────

pub fn samples_for_ms(sample_rate: f64, ms: f32) -> usize {
    ((sample_rate * ms as f64 / 1_000.0).round() as usize).max(1)
}

/// Linear resample — used to bring an audition source clip to the audio device
/// rate so it loops at the right speed/pitch through the morph.
pub fn resample_linear(x: &[f64], sr_in: f64, sr_out: f64) -> Vec<f64> {
    if x.len() < 2 || (sr_in - sr_out).abs() < 1.0 {
        return x.to_vec();
    }
    let ratio = sr_in / sr_out;
    let n_out = ((x.len() as f64) / ratio).floor() as usize;
    (0..n_out)
        .map(|i| {
            let pos = i as f64 * ratio;
            let i0 = pos.floor() as usize;
            let frac = pos - i0 as f64;
            let a = x[i0];
            let b = if i0 + 1 < x.len() { x[i0 + 1] } else { a };
            a + (b - a) * frac
        })
        .collect()
}

pub fn detect_onset(samples: &[f64], sample_rate: f64) -> usize {
    if samples.is_empty() {
        return 0;
    }
    let peak = samples.iter().map(|s| s.abs()).fold(0.0_f64, f64::max);
    if peak <= 1.0e-9 {
        return 0;
    }
    let frame = ((sample_rate * 0.0015).round() as usize).clamp(8, 256);
    let mut energy: f64 = samples.iter().take(frame).map(|s| s * s).sum();
    let mut energy_peak = energy;
    for i in frame..samples.len() {
        energy += samples[i] * samples[i];
        energy -= samples[i - frame] * samples[i - frame];
        energy_peak = energy_peak.max(energy);
    }
    let amp_thresh = peak * 0.06;
    let energy_thresh = energy_peak * 0.015;
    let preroll = ((sample_rate * 0.001).round() as usize).max(1);
    energy = samples.iter().take(frame).map(|s| s * s).sum();
    for i in 0..samples.len() {
        if i >= frame {
            energy += samples[i] * samples[i];
            energy -= samples[i - frame] * samples[i - frame];
        }
        if samples[i].abs() >= amp_thresh || energy >= energy_thresh {
            return i.saturating_sub(preroll);
        }
    }
    samples
        .iter()
        .enumerate()
        .max_by(|(_, a), (_, b)| a.abs().partial_cmp(&b.abs()).unwrap_or(Ordering::Equal))
        .map(|(i, _)| i.saturating_sub(preroll))
        .unwrap_or(0)
}

pub fn condition_fit_window(raw: &[f64], zero_dither_truncation: bool) -> Vec<f64> {
    let n = raw.len().max(1);
    raw.iter()
        .enumerate()
        .map(|(i, s)| {
            let hann = if n <= 1 {
                1.0
            } else {
                0.5 - 0.5 * (TAU * i as f64 / (n - 1) as f64).cos()
            };
            let mut v = s.clamp(-1.0, 1.0) * hann;
            if zero_dither_truncation {
                v = (v * 32_768.0).trunc() / 32_768.0;
            }
            v
        })
        .collect()
}

// ── Kernel ⇄ biquad ─────────────────────────────────────────────────────────

pub fn is_passthrough(stage: &[f64; 5]) -> bool {
    stage
        .iter()
        .zip(PASSTHROUGH)
        .all(|(a, e)| (*a - e).abs() < 1.0e-8)
}

pub fn kernel_to_biquad(stage: &[f64; 5]) -> [f64; 5] {
    let [c0, c1, c2, c3, c4] = *stage;
    [c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, c2 - 2.0, 1.0 - c3]
}

pub fn biquad_to_kernel(bq: [f64; 5]) -> [f64; 5] {
    let [b0, b1, b2, a1, a2] = bq;
    if b0.abs() < 1.0e-12 {
        return PASSTHROUGH;
    }
    [2.0 + b1 / b0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0]
}

pub fn stabilize_clamp_sort_corner(corner: &mut CornerData, sample_rate: f64) {
    for stage in corner.iter_mut() {
        if is_passthrough(stage) {
            continue;
        }
        let [b0, b1, b2, a1, a2] = kernel_to_biquad(stage);
        let raw_radius = a2.abs().sqrt();
        if !raw_radius.is_finite() || raw_radius <= 0.0 {
            *stage = PASSTHROUGH;
            continue;
        }
        let reflected = if raw_radius > 1.0 {
            1.0 / raw_radius
        } else {
            raw_radius
        };
        let clamped = reflected.clamp(0.5, 0.9985);
        let theta = (-a1 / (2.0 * raw_radius)).clamp(-1.0, 1.0).acos();
        let clamped_a1 = -2.0 * clamped * theta.cos();
        let clamped_a2 = clamped * clamped;
        *stage = biquad_to_kernel([b0, b1, b2, clamped_a1, clamped_a2]);
    }
    corner.sort_by(|l, r| {
        stage_frequency(l, sample_rate)
            .partial_cmp(&stage_frequency(r, sample_rate))
            .unwrap_or(Ordering::Equal)
    });
}

/// Zero radius — how hard the anti-resonances bite. Close to 1 = deep, sharp
/// notches. This is where the character lives.
pub const ZERO_BITE: f64 = 0.995;
/// Pole radius (Q) is kept musical: strong, distinct resonance, never maxed.
/// Q drives the radius (captured bandwidth); these just bound it.
pub const POLE_Q_MIN: f64 = 0.93;
pub const POLE_Q_MAX: f64 = 0.998;

/// Build one corner as pole-zero second-order sections whose *series product*
/// is the captured pole-zero envelope. Each section: a resonance (pole pair,
/// radius = Q) with a biting anti-resonance (zero pair) at the nearest spectral
/// valley. Numerator is monic (`b0 = 1`) so the product reconstructs the
/// envelope — no per-stage peak-taming, which is what collapsed the cascade.
pub fn build_corner_pole_zero(poles: &[lpc::Pole], valleys: &[f64], runtime_sr: f64) -> CornerData {
    let mut corner = [PASSTHROUGH; POLE_ZERO_COUNT];
    // Each valley becomes at most ONE zero, paired to its nearest pole. Stacking
    // the same valley on every pole builds a catastrophic notch that eats the
    // band — which is exactly what was collapsing the fit.
    let mut used = vec![false; valleys.len()];
    for (i, p) in poles.iter().take(POLE_ZERO_COUNT).enumerate() {
        let r = (-PI * p.bw_hz / runtime_sr)
            .exp()
            .clamp(POLE_Q_MIN, POLE_Q_MAX);
        let tp = TAU * p.freq_hz / runtime_sr;
        let a1 = -2.0 * r * tp.cos();
        let a2 = r * r;

        // Nearest UNUSED valley between ¼ and ~1½ octaves of the pole → its notch.
        let mut pick: Option<usize> = None;
        let mut best = f64::INFINITY;
        for (vi, &fz) in valleys.iter().enumerate() {
            if used[vi] {
                continue;
            }
            let oct = (fz / p.freq_hz).log2().abs();
            if !(0.25..=1.5).contains(&oct) {
                continue;
            }
            let d = (fz - p.freq_hz).abs();
            if d < best {
                best = d;
                pick = Some(vi);
            }
        }
        let (b0, b1, b2) = match pick {
            Some(vi) => {
                used[vi] = true;
                let tz = TAU * valleys[vi] / runtime_sr;
                (1.0, -2.0 * ZERO_BITE * tz.cos(), ZERO_BITE * ZERO_BITE)
            }
            None => (1.0, 0.0, 0.0),
        };
        corner[i] = biquad_to_kernel([b0, b1, b2, a1, a2]);
    }
    corner
}

/// Clamp a corner's kernel coefficients into the range the packed-minifloat
/// morph (the frozen E-mu mechanism) can represent: `c1,c3 ∈ [0,1]`,
/// `c0 ∈ [c1, c1+4]`, `c2 ∈ [c3, c3+4]`, `c4 ∈ [0,4]`. Outside this range
/// `PackedCorners::from_corner_data` saturates the words and the morph decodes
/// to garbage. Conforming here means *what you author equals what packs equals
/// what plays*; the spectral gate then measures whatever the clamp cost.
pub fn conform_to_packable_range(corner: &mut CornerData) {
    const K: f64 = 4.0; // COMBINE_K
    for s in corner.iter_mut() {
        let c1 = s[1].clamp(0.0, 1.0);
        let c3 = s[3].clamp(0.0, 1.0);
        let c0 = s[0].clamp(c1, c1 + K);
        let c2 = s[2].clamp(c3, c3 + K);
        let c4 = s[4].clamp(0.0, K);
        *s = [c0, c1, c2, c3, c4];
    }
}

/// Bring the cascade peak to `target` by spreading the make-up gain across all
/// stages' `c4` (each kept ≤ 4 so it stays packable). `c4` scales a stage's
/// whole numerator, so this is pure level — the response shape is unchanged.
/// Fixes the silent morph: folding all gain into one stage overruns the
/// packable ceiling, so the packed corner decodes ~80 dB down.
pub fn normalize_peak_packable(corner: &mut CornerData, sample_rate: f64, target: f64) {
    // Unclamped peak — magnitude_response floors at −48 dB, which would hide how
    // much make-up gain a very quiet cascade actually needs.
    let nyq = (sample_rate * 0.5).max(10_000.0);
    let peak_db = (0..RESPONSE_BINS)
        .map(|i| {
            let t = i as f64 / (RESPONSE_BINS - 1) as f64;
            let f = 20.0 * (nyq / 20.0).powf(t);
            cascade_mag_db(corner, f, sample_rate)
        })
        .fold(f64::NEG_INFINITY, f64::max);
    let peak = 10_f64.powf(peak_db / 20.0);
    if !peak.is_finite() || peak <= 1.0e-12 {
        return;
    }
    let mut need = target / peak;
    if !need.is_finite() || need <= 0.0 {
        return;
    }
    let active: Vec<usize> = (0..POLE_ZERO_COUNT)
        .filter(|&i| !is_passthrough(&corner[i]) && corner[i][4] > 1.0e-9)
        .collect();
    let mut remaining = active.len();
    for &i in &active {
        if remaining == 0 {
            break;
        }
        let want = need.powf(1.0 / remaining as f64); // even split of what's left
        let c4 = corner[i][4];
        let headroom = (4.0 / c4).max(1.0e-9);
        let factor = want.min(headroom);
        corner[i][4] = (c4 * factor).clamp(0.0, 4.0);
        need /= factor;
        remaining -= 1;
    }
}

pub fn stage_frequency(stage: &[f64; 5], sample_rate: f64) -> f64 {
    if is_passthrough(stage) {
        return f64::INFINITY;
    }
    let [_, _, _, a1, a2] = kernel_to_biquad(stage);
    let radius = a2.max(0.0).sqrt();
    if radius <= 0.0 {
        return f64::INFINITY;
    }
    let theta = (-a1 / (2.0 * radius)).clamp(-1.0, 1.0).acos();
    theta * sample_rate / TAU
}

// ── ARMA fitter ─────────────────────────────────────────────────────────────

const FIT_BINS: usize = 168;
const FORMANT_MIN_HZ: f64 = 180.0;
const FORMANT_MAX_HZ: f64 = 8_000.0;
const FORMANT_TOLERANCE: f64 = 0.12;
const STAGE_ROLES: [&str; POLE_ZERO_COUNT] =
    ["Body", "Formant", "Second", "Valley", "Edge", "Scar"];

#[derive(Clone)]
struct FitTarget {
    freqs: Vec<f64>,
    src_db: Vec<f64>,
    raw_db: Vec<f64>,
    weights: Vec<f64>,
    source_peaks: Vec<Peak>,
    valleys: Vec<Valley>,
    mode: TargetMode,
}

#[derive(Clone)]
struct StageParams {
    pole_freq: f64,
    pole_radius: f64,
    zero_freq: f64,
    zero_radius: f64,
}

type CandidateParams = [StageParams; POLE_ZERO_COUNT];

#[derive(Clone)]
struct CandidateScore {
    score: f64,
    residual_db: f64,
    post_pack_residual_db: f64,
    formant_error: f64,
    max_pack_drift: f64,
    post_pack_corner: CornerData,
    fit_peaks: Vec<Peak>,
}

pub fn fit_corner_arma_from_window(
    window: &[f64],
    source_sr: f64,
    runtime_sr: f64,
    options: FitOptions,
) -> FitResult {
    if window.len() < 32 {
        return FitResult {
            corner: [PASSTHROUGH; POLE_ZERO_COUNT],
            quality: FitQuality::Blocked,
            diagnostics: FitDiagnostics {
                rejection_reason: "fit window too short".to_owned(),
                ..FitDiagnostics::default()
            },
        };
    }

    let target = make_fit_target(window, source_sr, runtime_sr, options.target_mode);
    let (seed_poles, seed_valleys) = lpc::extract_poles_and_valleys_conditioned(window, source_sr);

    let mut lpc_seed = build_corner_pole_zero(&seed_poles, &seed_valleys, runtime_sr);
    stabilize_clamp_sort_corner(&mut lpc_seed, runtime_sr);
    conform_to_packable_range(&mut lpc_seed);
    normalize_peak_packable(&mut lpc_seed, runtime_sr, options.target_peak);
    let lpc_score = score_post_pack_candidate(&lpc_seed, &target, runtime_sr);

    let mut best = lpc_score.clone();
    for cand in
        arma_fit_initial_candidates_from_lpc(&seed_poles, &seed_valleys, &target, runtime_sr)
    {
        let score = refine_candidate_against_envelope(
            cand,
            &target,
            runtime_sr,
            options.target_peak,
            options.max_passes,
        );
        if score.score < best.score {
            best = score;
        }
    }

    let mut final_corner = best.post_pack_corner;
    stabilize_clamp_sort_corner(&mut final_corner, runtime_sr);
    conform_to_packable_range(&mut final_corner);
    let final_score = score_post_pack_candidate(&final_corner, &target, runtime_sr);
    if final_score.score <= best.score * 1.05 {
        best = final_score;
    }

    let quality = fit_quality_from_score(&best, &target);
    let reason = fit_rejection_reason(quality, &best, &target);
    FitResult {
        corner: best.post_pack_corner,
        quality,
        diagnostics: FitDiagnostics {
            raw_source_db: target
                .freqs
                .iter()
                .zip(&target.raw_db)
                .map(|(&f, &d)| [f, d])
                .collect(),
            simplified_target_db: target
                .freqs
                .iter()
                .zip(&target.src_db)
                .map(|(&f, &d)| [f, d])
                .collect(),
            source_peaks: target.source_peaks,
            target_valleys: target.valleys,
            fit_peaks: best.fit_peaks,
            stages: stage_diagnostics(&best.post_pack_corner, runtime_sr),
            residual_db: best.residual_db,
            post_pack_residual_db: best.post_pack_residual_db,
            formant_error: best.formant_error,
            max_pack_drift: best.max_pack_drift,
            lpc_seed_residual_db: lpc_score.post_pack_residual_db,
            rejection_reason: reason,
        },
    }
}

fn accept_candidate(
    current: &mut CandidateParams,
    current_score: &mut CandidateScore,
    next: CandidateParams,
    target: &FitTarget,
    runtime_sr: f64,
    target_peak: f64,
) -> bool {
    let score = score_params_post_pack(&next, target, runtime_sr, target_peak);
    if score.score + 1.0e-6 < current_score.score {
        *current = next;
        *current_score = score;
        true
    } else {
        false
    }
}

fn make_fit_target(window: &[f64], source_sr: f64, runtime_sr: f64, mode: TargetMode) -> FitTarget {
    let hi = (source_sr * 0.5)
        .min(runtime_sr * 0.5)
        .min(19_531.0)
        .max(8_000.0);
    let mut freqs = Vec::with_capacity(FIT_BINS);
    let mut raw = Vec::with_capacity(FIT_BINS);
    for i in 0..FIT_BINS {
        let t = i as f64 / (FIT_BINS - 1) as f64;
        let f = 40.0 * (hi / 40.0).powf(t);
        freqs.push(f);
        raw.push(dft_mag_db(window, source_sr, f));
    }
    stylized_target_from_raw(freqs, raw, mode)
}

fn stylized_target_from_raw(freqs: Vec<f64>, raw: Vec<f64>, mode: TargetMode) -> FitTarget {
    let raw_db = smooth_log(&raw, 4);
    let heavy = smooth_log(&raw_db, 14);
    let tilt = tilt_line(&freqs, &heavy);
    let source_peaks = detect_stylized_peaks(&freqs, &raw_db);
    let valleys = detect_stylized_valleys(&freqs, &heavy, &source_peaks);
    let src_db = build_simplified_target(&freqs, &heavy, &tilt, &source_peaks, &valleys);
    let peak = src_db.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let weights = freqs
        .iter()
        .zip(&src_db)
        .map(|(&f, &db)| {
            let band = if (FORMANT_MIN_HZ..=FORMANT_MAX_HZ).contains(&f) {
                3.0
            } else if f < FORMANT_MIN_HZ {
                0.55
            } else {
                0.9
            };
            let energy = 10_f64.powf(((db - peak).max(-36.0)) / 20.0);
            band * (0.25 + energy)
        })
        .collect();
    FitTarget {
        freqs,
        src_db,
        raw_db,
        weights,
        source_peaks,
        valleys,
        mode,
    }
}

fn tilt_line(freqs: &[f64], db: &[f64]) -> Vec<f64> {
    let mut sw = 0.0;
    let mut sx = 0.0;
    let mut sy = 0.0;
    let mut sxx = 0.0;
    let mut sxy = 0.0;
    for (&f, &y) in freqs.iter().zip(db) {
        let x = (f / 1_000.0).ln();
        let w = if (80.0..=12_000.0).contains(&f) {
            1.0
        } else {
            0.35
        };
        sw += w;
        sx += w * x;
        sy += w * y;
        sxx += w * x * x;
        sxy += w * x * y;
    }
    let denom = (sw * sxx - sx * sx).abs().max(1.0e-9);
    let slope = (sw * sxy - sx * sy) / denom;
    let intercept = (sy - slope * sx) / sw.max(1.0e-9);
    freqs
        .iter()
        .map(|&f| intercept + slope * (f / 1_000.0).ln())
        .collect()
}

fn detect_stylized_peaks(freqs: &[f64], db: &[f64]) -> Vec<Peak> {
    let mut peaks = Vec::new();
    for i in 2..freqs.len().saturating_sub(2) {
        let f = freqs[i];
        if !(140.0..=12_500.0).contains(&f) {
            continue;
        }
        let d = db[i];
        if d >= db[i - 1] && d >= db[i - 2] && d > db[i + 1] && d > db[i + 2] {
            peaks.push(Peak { freq_hz: f, db: d });
        }
    }
    peaks.sort_by(|a, b| b.db.partial_cmp(&a.db).unwrap_or(Ordering::Equal));

    let mut picked = Vec::new();
    for p in peaks
        .iter()
        .copied()
        .filter(|p| p.freq_hz <= FORMANT_MAX_HZ)
    {
        if picked
            .iter()
            .all(|q: &Peak| (q.freq_hz / p.freq_hz).log2().abs() > 0.26)
        {
            picked.push(p);
        }
        if picked.len() >= 5 {
            break;
        }
    }

    for p in peaks.iter().copied().filter(|p| p.freq_hz > FORMANT_MAX_HZ) {
        if picked
            .iter()
            .all(|q: &Peak| (q.freq_hz / p.freq_hz).log2().abs() > 0.18)
        {
            picked.push(Peak {
                freq_hz: p.freq_hz,
                db: p.db - 2.5,
            });
        }
        if picked.iter().filter(|p| p.freq_hz > FORMANT_MAX_HZ).count() >= 2 {
            break;
        }
    }

    if picked.len() < 3 {
        for &f in &[260.0, 750.0, 1_900.0, 4_200.0, 7_200.0] {
            let db = interp_log(freqs, db, f);
            if picked
                .iter()
                .all(|p: &Peak| (p.freq_hz / f).log2().abs() > 0.30)
            {
                picked.push(Peak { freq_hz: f, db });
            }
        }
    }

    picked.sort_by(|a, b| a.freq_hz.partial_cmp(&b.freq_hz).unwrap_or(Ordering::Equal));
    picked.truncate(6);
    picked
}

fn detect_stylized_valleys(freqs: &[f64], db: &[f64], peaks: &[Peak]) -> Vec<Valley> {
    let mut valleys = Vec::new();
    for pair in peaks.windows(2) {
        let lo = pair[0].freq_hz.min(pair[1].freq_hz);
        let hi = pair[0].freq_hz.max(pair[1].freq_hz);
        let mut best = Valley {
            freq_hz: (lo * hi).sqrt(),
            db: f64::INFINITY,
        };
        for (&f, &d) in freqs.iter().zip(db) {
            if f > lo * 1.05 && f < hi / 1.05 && d < best.db {
                best = Valley { freq_hz: f, db: d };
            }
        }
        if best.db.is_finite() {
            valleys.push(best);
        }
    }

    let mut low_mid = Valley {
        freq_hz: 1_200.0,
        db: interp_log(freqs, db, 1_200.0),
    };
    for (&f, &d) in freqs.iter().zip(db) {
        if (800.0..=2_400.0).contains(&f) && d < low_mid.db {
            low_mid = Valley { freq_hz: f, db: d };
        }
    }
    if valleys
        .iter()
        .all(|v| (v.freq_hz / low_mid.freq_hz).log2().abs() > 0.22)
    {
        valleys.push(low_mid);
    }

    valleys.sort_by(|a, b| a.freq_hz.partial_cmp(&b.freq_hz).unwrap_or(Ordering::Equal));
    valleys.truncate(4);
    valleys
}

fn build_simplified_target(
    freqs: &[f64],
    heavy: &[f64],
    tilt: &[f64],
    peaks: &[Peak],
    valleys: &[Valley],
) -> Vec<f64> {
    let mean_offset =
        heavy.iter().zip(tilt).map(|(h, t)| h - t).sum::<f64>() / heavy.len().max(1) as f64;
    let mut out: Vec<f64> = tilt.iter().map(|d| d + mean_offset * 0.35).collect();

    for p in peaks {
        let base = interp_log(freqs, tilt, p.freq_hz);
        let amp = (p.db - base).clamp(2.0, if p.freq_hz > 5_000.0 { 8.0 } else { 13.5 });
        let width = if p.freq_hz < 800.0 {
            0.42
        } else if p.freq_hz < 4_000.0 {
            0.30
        } else {
            0.12
        };
        add_log_gaussian(&mut out, freqs, p.freq_hz, amp, width);
    }

    for v in valleys {
        let base = interp_log(freqs, heavy, v.freq_hz);
        let depth = (base - v.db + 2.0).clamp(2.0, 9.0);
        let width = if v.freq_hz < 2_000.0 { 0.24 } else { 0.12 };
        add_log_gaussian(&mut out, freqs, v.freq_hz, -depth, width);
    }

    let out = smooth_log(&out, 3);
    let max_raw = heavy.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    out.into_iter()
        .map(|d| d.clamp(max_raw - 42.0, max_raw + 16.0))
        .collect()
}

fn add_log_gaussian(out: &mut [f64], freqs: &[f64], center: f64, amp: f64, width_oct: f64) {
    let denom = 2.0 * width_oct * width_oct;
    for (y, &f) in out.iter_mut().zip(freqs) {
        let x = (f / center).log2();
        *y += amp * (-(x * x) / denom).exp();
    }
}

fn interp_log(freqs: &[f64], vals: &[f64], freq: f64) -> f64 {
    if freqs.is_empty() || vals.is_empty() {
        return 0.0;
    }
    if freq <= freqs[0] {
        return vals[0];
    }
    for i in 1..freqs.len() {
        if freq <= freqs[i] {
            let x0 = freqs[i - 1].ln();
            let x1 = freqs[i].ln();
            let t = ((freq.ln() - x0) / (x1 - x0).max(1.0e-9)).clamp(0.0, 1.0);
            return vals[i - 1] + (vals[i] - vals[i - 1]) * t;
        }
    }
    *vals.last().unwrap()
}

fn dft_mag_db(window: &[f64], sr: f64, freq: f64) -> f64 {
    let w = TAU * freq / sr;
    let (mut re, mut im) = (0.0_f64, 0.0_f64);
    for (k, &x) in window.iter().enumerate() {
        let a = w * k as f64;
        re += x * a.cos();
        im -= x * a.sin();
    }
    let mag = (re * re + im * im).sqrt() / window.len().max(1) as f64;
    20.0 * (mag + 1.0e-9).log10()
}

pub fn detect_formant_peaks(envelope: &[[f64; 2]]) -> Vec<Peak> {
    let mut peaks = Vec::new();
    for i in 1..envelope.len().saturating_sub(1) {
        let [f, db] = envelope[i];
        if !(FORMANT_MIN_HZ..=FORMANT_MAX_HZ).contains(&f) {
            continue;
        }
        if db >= envelope[i - 1][1] && db > envelope[i + 1][1] {
            peaks.push(Peak { freq_hz: f, db });
        }
    }
    peaks.sort_by(|a, b| b.db.partial_cmp(&a.db).unwrap_or(Ordering::Equal));

    let mut picked: Vec<Peak> = Vec::new();
    for peak in peaks {
        if picked
            .iter()
            .all(|p| (p.freq_hz / peak.freq_hz).log2().abs() > 0.28)
        {
            picked.push(peak);
        }
        if picked.len() >= 5 {
            break;
        }
    }

    if picked.len() < 3 {
        let mut fallback: Vec<Peak> = envelope
            .iter()
            .copied()
            .filter(|[f, _]| (FORMANT_MIN_HZ..=FORMANT_MAX_HZ).contains(f))
            .map(|[freq_hz, db]| Peak { freq_hz, db })
            .collect();
        fallback.sort_by(|a, b| b.db.partial_cmp(&a.db).unwrap_or(Ordering::Equal));
        for peak in fallback {
            if picked
                .iter()
                .all(|p| (p.freq_hz / peak.freq_hz).log2().abs() > 0.30)
            {
                picked.push(peak);
            }
            if picked.len() >= 5 {
                break;
            }
        }
    }

    picked.sort_by(|a, b| a.freq_hz.partial_cmp(&b.freq_hz).unwrap_or(Ordering::Equal));
    picked
}

fn detect_response_peaks(freqs: &[f64], db: &[f64]) -> Vec<Peak> {
    let envelope: Vec<[f64; 2]> = freqs.iter().zip(db).map(|(&f, &d)| [f, d]).collect();
    detect_formant_peaks(&envelope)
}

fn arma_fit_initial_candidates_from_lpc(
    poles: &[lpc::Pole],
    valleys: &[f64],
    target: &FitTarget,
    runtime_sr: f64,
) -> Vec<CandidateParams> {
    let mut out = Vec::new();
    out.push(params_from_poles_and_valleys(
        poles, valleys, target, runtime_sr, 0.88,
    ));
    out.push(params_from_source_peaks(target, runtime_sr, 0.82));
    out.push(params_from_source_peaks(target, runtime_sr, 0.94));
    out
}

fn refine_candidate_against_envelope(
    mut cand: CandidateParams,
    target: &FitTarget,
    runtime_sr: f64,
    target_peak: f64,
    max_passes: usize,
) -> CandidateScore {
    let mut score = score_params_post_pack(&cand, target, runtime_sr, target_peak);
    for pass in 0..max_passes {
        let freq_step = [0.18, 0.11, 0.065, 0.038, 0.022]
            .get(pass)
            .copied()
            .unwrap_or(0.018);
        let radius_step = [0.018, 0.011, 0.007, 0.004, 0.0025]
            .get(pass)
            .copied()
            .unwrap_or(0.002);
        let zero_radius_step = [0.055, 0.034, 0.022, 0.014, 0.008]
            .get(pass)
            .copied()
            .unwrap_or(0.006);
        let mut improved = false;

        for stage in 0..POLE_ZERO_COUNT {
            for dir in [-1.0, 1.0] {
                let mut next = cand.clone();
                next[stage].pole_freq *= 2.0_f64.powf(dir * freq_step);
                clamp_stage_params(&mut next[stage], runtime_sr, target.mode);
                if accept_candidate(&mut cand, &mut score, next, target, runtime_sr, target_peak) {
                    improved = true;
                }

                let mut next = cand.clone();
                next[stage].zero_freq *= 2.0_f64.powf(dir * freq_step);
                clamp_stage_params(&mut next[stage], runtime_sr, target.mode);
                if accept_candidate(&mut cand, &mut score, next, target, runtime_sr, target_peak) {
                    improved = true;
                }

                let mut next = cand.clone();
                next[stage].pole_radius += dir * radius_step;
                clamp_stage_params(&mut next[stage], runtime_sr, target.mode);
                if accept_candidate(&mut cand, &mut score, next, target, runtime_sr, target_peak) {
                    improved = true;
                }

                let mut next = cand.clone();
                next[stage].zero_radius += dir * zero_radius_step;
                clamp_stage_params(&mut next[stage], runtime_sr, target.mode);
                if accept_candidate(&mut cand, &mut score, next, target, runtime_sr, target_peak) {
                    improved = true;
                }
            }
        }

        let mut source_peaks = target.source_peaks.clone();
        source_peaks.sort_by(|a, b| b.db.partial_cmp(&a.db).unwrap_or(Ordering::Equal));
        for peak in source_peaks.iter().take(5) {
            for stage in 0..POLE_ZERO_COUNT {
                let mut next = cand.clone();
                next[stage].pole_freq = peak.freq_hz;
                next[stage].pole_radius = next[stage].pole_radius.max(0.90);
                next[stage].zero_freq = nearest_envelope_valley(peak.freq_hz, target);
                clamp_stage_params(&mut next[stage], runtime_sr, target.mode);
                if accept_candidate(&mut cand, &mut score, next, target, runtime_sr, target_peak) {
                    improved = true;
                }
            }
        }

        if !improved && pass >= 2 {
            break;
        }
    }
    score
}

fn params_from_poles_and_valleys(
    poles: &[lpc::Pole],
    valleys: &[f64],
    target: &FitTarget,
    runtime_sr: f64,
    zero_radius: f64,
) -> CandidateParams {
    let mut used = vec![false; valleys.len()];
    let mut stages = default_params(runtime_sr);
    for i in 0..POLE_ZERO_COUNT {
        let pole = poles.get(i);
        let freq = pole
            .map(|p| p.freq_hz)
            .or_else(|| target.source_peaks.get(i).map(|p| p.freq_hz))
            .unwrap_or(160.0 * 1.72_f64.powi(i as i32));
        let radius = pole
            .map(|p| (-PI * p.bw_hz / runtime_sr).exp().clamp(0.78, 0.965))
            .unwrap_or(0.90);
        let zero_freq = nearest_unused_valley(freq, valleys, &mut used)
            .unwrap_or_else(|| nearest_envelope_valley(freq, target));
        stages[i] = StageParams {
            pole_freq: freq,
            pole_radius: radius,
            zero_freq,
            zero_radius,
        };
        clamp_stage_params(&mut stages[i], runtime_sr, target.mode);
    }
    stages
}

fn params_from_source_peaks(
    target: &FitTarget,
    runtime_sr: f64,
    zero_radius: f64,
) -> CandidateParams {
    let mut stages = default_params(runtime_sr);
    for i in 0..POLE_ZERO_COUNT {
        let freq = target
            .source_peaks
            .get(i)
            .map(|p| p.freq_hz)
            .unwrap_or_else(|| 180.0 * 1.62_f64.powi(i as i32));
        stages[i] = StageParams {
            pole_freq: freq,
            pole_radius: if freq < 5_000.0 { 0.92 } else { 0.86 },
            zero_freq: nearest_envelope_valley(freq, target),
            zero_radius,
        };
        clamp_stage_params(&mut stages[i], runtime_sr, target.mode);
    }
    stages
}

fn default_params(runtime_sr: f64) -> CandidateParams {
    core::array::from_fn(|i| {
        let mut p = StageParams {
            pole_freq: 160.0 * 1.75_f64.powi(i as i32),
            pole_radius: 0.94,
            zero_freq: 260.0 * 1.75_f64.powi(i as i32),
            zero_radius: 0.80,
        };
        clamp_stage_params(&mut p, runtime_sr, TargetMode::LowQGraphic);
        p
    })
}

fn nearest_unused_valley(freq: f64, valleys: &[f64], used: &mut [bool]) -> Option<f64> {
    let mut pick = None;
    let mut best = f64::INFINITY;
    for (i, &fz) in valleys.iter().enumerate() {
        if used[i] {
            continue;
        }
        let oct = (fz / freq).log2().abs();
        if !(0.18..=1.7).contains(&oct) {
            continue;
        }
        let d = (fz / freq).ln().abs();
        if d < best {
            best = d;
            pick = Some(i);
        }
    }
    pick.map(|i| {
        used[i] = true;
        valleys[i]
    })
}

fn nearest_envelope_valley(freq: f64, target: &FitTarget) -> f64 {
    let mut best_freq = (freq * 1.28).min(target.freqs.last().copied().unwrap_or(freq));
    let mut best_db = f64::INFINITY;
    for i in 1..target.freqs.len().saturating_sub(1) {
        let f = target.freqs[i];
        let oct = (f / freq).log2().abs();
        if !(0.18..=1.6).contains(&oct) {
            continue;
        }
        let db = target.src_db[i];
        if db < best_db {
            best_db = db;
            best_freq = f;
        }
    }
    best_freq
}

fn clamp_stage_params(p: &mut StageParams, runtime_sr: f64, mode: TargetMode) {
    let hi = (runtime_sr * 0.48).min(18_000.0);
    p.pole_freq = p.pole_freq.clamp(45.0, hi);
    p.zero_freq = p.zero_freq.clamp(45.0, hi);
    match mode {
        TargetMode::LowQGraphic => {
            p.pole_radius = p.pole_radius.clamp(0.62, 0.985);
            p.zero_radius = p.zero_radius.clamp(0.0, 0.965);
        }
    }
}

fn params_to_corner(params: &CandidateParams, runtime_sr: f64, target_peak: f64) -> CornerData {
    let mut corner = [PASSTHROUGH; POLE_ZERO_COUNT];
    for (stage, p) in corner.iter_mut().zip(params.iter()) {
        let tp = TAU * p.pole_freq / runtime_sr;
        let tz = TAU * p.zero_freq / runtime_sr;
        let a1 = -2.0 * p.pole_radius * tp.cos();
        let a2 = p.pole_radius * p.pole_radius;
        let b0 = 1.0;
        let b1 = -2.0 * p.zero_radius * tz.cos();
        let b2 = p.zero_radius * p.zero_radius;
        *stage = biquad_to_kernel([b0, b1, b2, a1, a2]);
    }
    stabilize_clamp_sort_corner(&mut corner, runtime_sr);
    conform_to_packable_range(&mut corner);
    normalize_peak_packable(&mut corner, runtime_sr, target_peak);
    corner
}

fn score_params_post_pack(
    params: &CandidateParams,
    target: &FitTarget,
    runtime_sr: f64,
    target_peak: f64,
) -> CandidateScore {
    let corner = params_to_corner(params, runtime_sr, target_peak);
    score_post_pack_candidate(&corner, target, runtime_sr)
}

fn score_post_pack_candidate(
    corner: &CornerData,
    target: &FitTarget,
    runtime_sr: f64,
) -> CandidateScore {
    let body = [*corner, *corner, *corner, *corner];
    let post = PackedCorners::from_corner_data(&body).interpolate(0.0, 0.0);
    let max_pack_drift = corner
        .iter()
        .flatten()
        .zip(post.iter().flatten())
        .map(|(a, b)| (a - b).abs())
        .fold(0.0_f64, f64::max);

    let response: Vec<f64> = target
        .freqs
        .iter()
        .map(|&f| cascade_mag_db(&post, f, runtime_sr))
        .collect();
    let fit_peaks = detect_response_peaks(&target.freqs, &response);
    let residual = weighted_residual_db(&target.src_db, &response, &target.weights);
    let formant_error = formant_peak_error(&target.source_peaks, &fit_peaks);
    let nonfinite =
        response.iter().any(|v| !v.is_finite()) || post.iter().flatten().any(|v| !v.is_finite());
    let notch_penalty = impossible_notch_penalty(&response);
    let drift_penalty = (max_pack_drift / 0.02).max(0.0);
    let score = if nonfinite {
        f64::INFINITY
    } else {
        residual + 14.0 * formant_error + 1.5 * notch_penalty + drift_penalty
    };

    CandidateScore {
        score,
        residual_db: spectral_residual_from_target(corner, target, runtime_sr),
        post_pack_residual_db: residual,
        formant_error,
        max_pack_drift,
        post_pack_corner: post,
        fit_peaks,
    }
}

fn weighted_residual_db(src: &[f64], fit: &[f64], weights: &[f64]) -> f64 {
    let wsum: f64 = weights.iter().sum();
    if wsum <= 1.0e-12 || src.len() != fit.len() {
        return f64::INFINITY;
    }
    let offset = src
        .iter()
        .zip(fit)
        .zip(weights)
        .map(|((&s, &f), &w)| w * (s - f))
        .sum::<f64>()
        / wsum;
    let acc = src
        .iter()
        .zip(fit)
        .zip(weights)
        .map(|((&s, &f), &w)| {
            let e = s - f - offset;
            w * e * e
        })
        .sum::<f64>();
    (acc / wsum).sqrt()
}

fn spectral_residual_from_target(corner: &CornerData, target: &FitTarget, runtime_sr: f64) -> f64 {
    let response: Vec<f64> = target
        .freqs
        .iter()
        .map(|&f| cascade_mag_db(corner, f, runtime_sr))
        .collect();
    weighted_residual_db(&target.src_db, &response, &target.weights)
}

fn formant_peak_error(source: &[Peak], fit: &[Peak]) -> f64 {
    if source.is_empty() {
        return 0.0;
    }
    if fit.is_empty() {
        return 4.0;
    }
    let mut strongest: Vec<Peak> = source
        .iter()
        .copied()
        .filter(|p| p.freq_hz <= FORMANT_MAX_HZ)
        .collect();
    if strongest.is_empty() {
        return 0.0;
    }
    strongest.sort_by(|a, b| b.db.partial_cmp(&a.db).unwrap_or(Ordering::Equal));
    let n = strongest.len().min(5);
    let tol = (1.0 + FORMANT_TOLERANCE).ln();
    let mut acc = 0.0;
    for src in strongest.iter().take(n) {
        let best = fit
            .iter()
            .filter(|p| p.freq_hz <= FORMANT_MAX_HZ)
            .map(|p| (p.freq_hz / src.freq_hz).ln().abs())
            .fold(f64::INFINITY, f64::min);
        let normalized = (best / tol).min(4.0);
        acc += normalized * normalized;
    }
    (acc / n as f64).sqrt()
}

fn impossible_notch_penalty(response: &[f64]) -> f64 {
    if response.is_empty() {
        return 0.0;
    }
    let max = response.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let min = response.iter().copied().fold(f64::INFINITY, f64::min);
    ((max - min - 78.0) / 18.0).max(0.0)
}

fn fit_quality_from_score(score: &CandidateScore, target: &FitTarget) -> FitQuality {
    if !score.score.is_finite()
        || !score.post_pack_residual_db.is_finite()
        || score.post_pack_residual_db > FIT_BLOCK_DB
        || score.fit_peaks.is_empty()
    {
        FitQuality::Blocked
    } else if score.post_pack_residual_db <= FIT_WARN_DB
        && score.formant_error <= 1.0
        && required_formants_inside_tolerance(&target.source_peaks, &score.fit_peaks)
    {
        FitQuality::Ready
    } else {
        FitQuality::Review
    }
}

fn required_formants_inside_tolerance(source: &[Peak], fit: &[Peak]) -> bool {
    let mut strongest: Vec<Peak> = source
        .iter()
        .copied()
        .filter(|p| p.freq_hz <= FORMANT_MAX_HZ)
        .collect();
    strongest.sort_by(|a, b| b.db.partial_cmp(&a.db).unwrap_or(Ordering::Equal));
    let need = strongest.len().min(3);
    if need == 0 {
        return true;
    }
    let tol = (1.0 + FORMANT_TOLERANCE).ln();
    strongest.iter().take(need).all(|src| {
        fit.iter()
            .any(|p| (p.freq_hz / src.freq_hz).ln().abs() <= tol)
    })
}

fn fit_rejection_reason(quality: FitQuality, score: &CandidateScore, target: &FitTarget) -> String {
    match quality {
        FitQuality::Ready => {
            "accepted: post-pack residual and formants are inside the ready gate".to_owned()
        }
        FitQuality::Review => {
            if !required_formants_inside_tolerance(&target.source_peaks, &score.fit_peaks) {
                format!(
                    "review: fitted peaks miss one or more source formants by more than +/-{:.0}%",
                    FORMANT_TOLERANCE * 100.0
                )
            } else {
                format!(
                    "review: post-pack residual {:.1} dB is above ready gate",
                    score.post_pack_residual_db
                )
            }
        }
        FitQuality::Blocked => {
            if score.fit_peaks.is_empty() {
                "blocked: candidate produced no usable peaks below 5 kHz".to_owned()
            } else if !score.post_pack_residual_db.is_finite() {
                "blocked: non-finite post-pack score".to_owned()
            } else {
                format!(
                    "blocked: post-pack residual {:.1} dB is above block gate",
                    score.post_pack_residual_db
                )
            }
        }
    }
}

fn stage_diagnostics(corner: &CornerData, sample_rate: f64) -> Vec<StageDiagnostic> {
    corner
        .iter()
        .enumerate()
        .filter_map(|(i, stage)| {
            if is_passthrough(stage) {
                return None;
            }
            let [b0, _b1, b2, _a1, a2] = kernel_to_biquad(stage);
            let pole_radius = a2.max(0.0).sqrt();
            let zero_radius = if b0.abs() > 1.0e-12 {
                (b2 / b0).max(0.0).sqrt()
            } else {
                0.0
            };
            Some(StageDiagnostic {
                role: STAGE_ROLES[i.min(STAGE_ROLES.len() - 1)],
                pole_freq_hz: stage_frequency(stage, sample_rate),
                pole_radius,
                zero_freq_hz: zero_frequency(stage, sample_rate),
                zero_radius,
            })
        })
        .collect()
}

fn zero_frequency(stage: &[f64; 5], sample_rate: f64) -> f64 {
    let [b0, b1, b2, _, _] = kernel_to_biquad(stage);
    if b0.abs() <= 1.0e-12 {
        return f64::INFINITY;
    }
    let radius = (b2 / b0).max(0.0).sqrt();
    if radius <= 1.0e-12 {
        return f64::INFINITY;
    }
    let theta = (-(b1 / b0) / (2.0 * radius)).clamp(-1.0, 1.0).acos();
    theta * sample_rate / TAU
}

// ── Render / residual ───────────────────────────────────────────────────────

/// Spectral match: RMS dB error between the fitted filter's response envelope
/// and the source's smoothed magnitude spectrum, over the shared band. This is
/// the right yardstick for "does this filter capture this sound's colour" — it
/// works for any source (loop, tone, transient), not only impulse responses.
/// Gain-independent (means are aligned). Lower is better.
pub fn spectral_residual_db(window: &[f64], sr_in: f64, corner: &CornerData, sr_filt: f64) -> f64 {
    const BINS: usize = 96;
    let n = window.len();
    if n < 16 {
        return f64::INFINITY;
    }
    let nyq = (sr_in * 0.5).min(sr_filt * 0.5).max(8_000.0);
    let mut src = Vec::with_capacity(BINS);
    let mut filt = Vec::with_capacity(BINS);
    for i in 0..BINS {
        let t = i as f64 / (BINS - 1) as f64;
        let freq = 20.0 * (nyq / 20.0).powf(t);
        // Direct DFT magnitude of the (already Hann-windowed) source at `freq`.
        let w = TAU * freq / sr_in;
        let (mut re, mut im) = (0.0_f64, 0.0_f64);
        for (k, &x) in window.iter().enumerate() {
            let a = w * k as f64;
            re += x * a.cos();
            im -= x * a.sin();
        }
        let mag = (re * re + im * im).sqrt() / n as f64;
        src.push(20.0 * (mag + 1.0e-9).log10());
        filt.push(cascade_mag_db(corner, freq, sr_filt));
    }
    // Smooth the source spectrum into an envelope (≈ 2/3-octave) before comparing.
    let src = smooth_log(&src, 3);
    // Energy-weighted dB error: weight each bin by the source's magnitude there,
    // so deep inter-harmonic nulls (near-silent, irrelevant) don't dominate — we
    // score the match where the sound actually has energy (the formant peaks).
    let w: Vec<f64> = src.iter().map(|d| 10_f64.powf(d / 20.0)).collect();
    let wsum: f64 = w.iter().sum();
    if wsum <= 1.0e-12 {
        return f64::INFINITY;
    }
    let offset: f64 = (0..BINS).map(|k| w[k] * (src[k] - filt[k])).sum::<f64>() / wsum;
    let acc: f64 = (0..BINS)
        .map(|k| {
            let e = src[k] - filt[k] - offset;
            w[k] * e * e
        })
        .sum();
    (acc / wsum).sqrt()
}

/// The source's smoothed magnitude envelope as `[freq_hz, dB]` points, for
/// overlaying behind the fitted curve so the parse (fit-vs-source) is visible.
pub fn source_envelope(window: &[f64], sr_in: f64) -> Vec<[f64; 2]> {
    const BINS: usize = 96;
    let n = window.len();
    if n < 16 {
        return Vec::new();
    }
    let hi = (sr_in * 0.5).min(19_531.0).max(8_000.0);
    let mut raw = Vec::with_capacity(BINS);
    let mut freqs = Vec::with_capacity(BINS);
    for i in 0..BINS {
        let t = i as f64 / (BINS - 1) as f64;
        let f = 20.0 * (hi / 20.0).powf(t);
        let w = TAU * f / sr_in;
        let (mut re, mut im) = (0.0_f64, 0.0_f64);
        for (k, &x) in window.iter().enumerate() {
            let a = w * k as f64;
            re += x * a.cos();
            im -= x * a.sin();
        }
        let mag = (re * re + im * im).sqrt() / n as f64;
        raw.push(20.0 * (mag + 1.0e-9).log10());
        freqs.push(f);
    }
    let sm = smooth_log(&raw, 5);
    freqs.into_iter().zip(sm).map(|(f, d)| [f, d]).collect()
}

fn smooth_log(v: &[f64], radius: usize) -> Vec<f64> {
    (0..v.len())
        .map(|i| {
            let lo = i.saturating_sub(radius);
            let hi = (i + radius + 1).min(v.len());
            v[lo..hi].iter().sum::<f64>() / (hi - lo).max(1) as f64
        })
        .collect()
}

// ── Z-plane ─────────────────────────────────────────────────────────────────

pub fn z_plane_points(corner: &CornerData) -> ([ComplexPoint; 6], [ComplexPoint; 6]) {
    let mut poles = [ComplexPoint::default(); 6];
    let mut zeros = [ComplexPoint::default(); 6];
    for (i, stage) in corner.iter().take(POLE_ZERO_COUNT).enumerate() {
        let [b0, b1, b2, a1, a2] = kernel_to_biquad(stage);
        poles[i] = conjugate_pair_root(a1, a2);
        zeros[i] = if b0.abs() > 1.0e-12 {
            conjugate_pair_root(b1 / b0, b2 / b0)
        } else {
            ComplexPoint::default()
        };
    }
    (poles, zeros)
}

pub fn conjugate_pair_root(linear: f64, quadratic: f64) -> ComplexPoint {
    let re = -linear * 0.5;
    let im_sq = (quadratic - re * re).max(0.0);
    ComplexPoint {
        re,
        im: im_sq.sqrt(),
    }
}

pub fn circle_points(radius: f64, steps: usize) -> Vec<[f64; 2]> {
    (0..=steps)
        .map(|i| {
            let a = TAU * i as f64 / steps as f64;
            [radius * a.cos(), radius * a.sin()]
        })
        .collect()
}

// ── Magnitude response ──────────────────────────────────────────────────────

pub fn magnitude_response(corner: &CornerData, sample_rate: f64) -> Vec<[f64; 2]> {
    let nyquist = (sample_rate * 0.5).max(10_000.0);
    (0..RESPONSE_BINS)
        .map(|i| {
            let t = i as f64 / (RESPONSE_BINS - 1) as f64;
            let freq = 20.0 * (nyquist / 20.0).powf(t);
            [
                freq,
                cascade_mag_db(corner, freq, sample_rate).clamp(-48.0, 24.0),
            ]
        })
        .collect()
}

pub fn cascade_mag_db(corner: &CornerData, frequency: f64, sample_rate: f64) -> f64 {
    corner
        .iter()
        .map(|stage| stage_mag_db(stage, frequency, sample_rate))
        .sum()
}

/// One stage's magnitude in dB. `cascade_mag_db` is the sum of this over stages,
/// so plotting each stage separately decomposes the response into its actors.
pub fn stage_mag_db(stage: &[f64; 5], frequency: f64, sample_rate: f64) -> f64 {
    let angle = TAU * frequency / sample_rate.max(1.0);
    let (cos1, sin1) = (angle.cos(), angle.sin());
    let (cos2, sin2) = ((2.0 * angle).cos(), (2.0 * angle).sin());
    let [b0, b1, b2, a1, a2] = kernel_to_biquad(stage);
    let nr = b0 + b1 * cos1 + b2 * cos2;
    let ni = -b1 * sin1 - b2 * sin2;
    let dr = 1.0 + a1 * cos1 + a2 * cos2;
    let di = -a1 * sin1 - a2 * sin2;
    let num = nr * nr + ni * ni;
    let den = dr * dr + di * di;
    10.0 * ((num + 1.0e-30) / (den + 1.0e-30)).log10()
}

/// The six named actors (ROOT…RIP = the first six stages), each as its own dB
/// curve on the same log-frequency grid `magnitude_response` uses. Summed, these
/// equal the full response; drawn separately, they show which actor owns which
/// part of the shape — and, at the midpoint, which one is misplaced.
pub fn actor_magnitude_responses(
    corner: &CornerData,
    sample_rate: f64,
) -> [Vec<[f64; 2]>; POLE_ZERO_COUNT] {
    let nyquist = (sample_rate * 0.5).max(10_000.0);
    core::array::from_fn(|stage| {
        let kernel = corner[stage];
        (0..RESPONSE_BINS)
            .map(|i| {
                let t = i as f64 / (RESPONSE_BINS - 1) as f64;
                let freq = 20.0 * (nyquist / 20.0).powf(t);
                [freq, stage_mag_db(&kernel, freq, sample_rate).clamp(-48.0, 24.0)]
            })
            .collect()
    })
}

/// A four-corner body's response at the morph/Q midpoint, through the real
/// packed-u16 bilinear (the proven, bit-accurate runtime path) — not a
/// decoded-float blend. This is the position that tells whether the corners were
/// authored coherently: at the corners any fit looks right, only the middle exposes it.
pub fn body_midpoint(corners: &[CornerData; 4]) -> CornerData {
    PackedCorners::from_corner_data(corners).interpolate(0.5_f32, 0.5_f32)
}

/// The Talking Hedz calibration truth at M50/Q50, decoded from the **verbatim**
/// 240-byte E-mu ROM block (skin 13) — `from_rom_bytes`, not the 6-dp JSON that
/// caps at −53.75 dB. This is the −95.41 dB bit-accurate midpoint the authored
/// body is judged against. Reference/dev only — never ships; returns None if the
/// block isn't present in this checkout.
pub fn hedz_rom_midpoint() -> Option<CornerData> {
    const ROM: &str = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../dev/tmp/cheat_engine_dump/skin13_corners_rom.bin"
    );
    let bytes = std::fs::read(ROM).ok()?;
    PackedCorners::from_rom_bytes(&bytes)
        .ok()
        .map(|p| p.interpolate(0.5_f32, 0.5_f32))
}

// ── Interpolation / audio glue ──────────────────────────────────────────────

pub fn two_anchor_preview(low: &CornerData, high: &CornerData, morph: f32) -> CornerData {
    let body = [*low, *high, *low, *high];
    PackedCorners::from_corner_data(&body).interpolate(morph.clamp(0.0, 1.0), 0.0)
}

/// Per-stage biquad coefficients [b0, b1, b2, a1, a2] for the audio thread.
pub fn corner_to_biquads(corner: &CornerData) -> [[f64; 5]; POLE_ZERO_COUNT] {
    let mut out = [[1.0, 0.0, 0.0, 0.0, 0.0]; POLE_ZERO_COUNT];
    for (target, stage) in out.iter_mut().zip(corner) {
        *target = kernel_to_biquad(stage);
    }
    out
}

// ── Waveform downsampling (display) ─────────────────────────────────────────

pub fn downsample_plot(samples: &[f64], offset: usize) -> Vec<[f64; 2]> {
    const WAVEFORM_LIMIT: usize = 16_384;
    let stride = samples.len().div_ceil(WAVEFORM_LIMIT).max(1);
    samples
        .iter()
        .enumerate()
        .step_by(stride)
        .map(|(i, s)| [(offset + i) as f64, s.clamp(-1.0, 1.0)])
        .collect()
}

// ── Text helpers ────────────────────────────────────────────────────────────

pub fn display_name(path: &Path) -> String {
    path.file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("audio")
        .to_owned()
}

pub fn format_residual(residual: f64) -> String {
    if residual.is_finite() {
        format!("{residual:.1} dB")
    } else {
        "--.- dB".to_owned()
    }
}

pub fn trim_label(label: &str, max_chars: usize) -> String {
    if label.chars().count() <= max_chars {
        return label.to_owned();
    }
    let mut s = label
        .chars()
        .take(max_chars.saturating_sub(1))
        .collect::<String>();
    s.push('…');
    s
}

// ── C++ export ──────────────────────────────────────────────────────────────

pub fn cpp_df2t_output(corner: &CornerData) -> String {
    let mut rows = [
        Vec::with_capacity(POLE_ZERO_COUNT),
        Vec::with_capacity(POLE_ZERO_COUNT),
        Vec::with_capacity(POLE_ZERO_COUNT),
        Vec::with_capacity(POLE_ZERO_COUNT),
        Vec::with_capacity(POLE_ZERO_COUNT),
    ];
    for stage in corner {
        let [b0, b1, b2, a1, a2] = kernel_to_biquad(stage);
        rows[0].push(b0);
        rows[1].push(b1);
        rows[2].push(b2);
        rows[3].push(a1);
        rows[4].push(a2);
    }
    let fmt = |v: &[f64]| {
        v.iter()
            .map(|x| format!("{x:.17}"))
            .collect::<Vec<_>>()
            .join(", ")
    };
    format!(
        "double b_0[6] = {{{}}};\ndouble b_1[6] = {{{}}};\ndouble b_2[6] = {{{}}};\ndouble a_1[6] = {{{}}};\ndouble a_2[6] = {{{}}};\n",
        fmt(&rows[0]),
        fmt(&rows[1]),
        fmt(&rows[2]),
        fmt(&rows[3]),
        fmt(&rows[4]),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Diagnostic (not a gate): run the REAL Forge ARMA authoring pipeline on
    /// the test vowels and print post-pack fit diagnostics. Run:
    /// cargo test -p trench-forge dump_real_fit_pipeline -- --nocapture
    #[test]
    fn dump_real_fit_pipeline() {
        let dir = env!("CARGO_MANIFEST_DIR");
        for name in ["vowel_oo", "vowel_eh", "vowel_ah", "vowel_ee", "tube_metal"] {
            let path = std::path::Path::new(dir)
                .join("test_sounds")
                .join(format!("{name}.wav"));
            let Ok((samples, sr)) = load_wav_as_mono_f64(&path) else {
                println!("(missing {name})");
                continue;
            };
            let onset = detect_onset(&samples, sr);
            let wlen = samples_for_ms(sr, DEFAULT_WINDOW_MS);
            let start = onset.min(samples.len().saturating_sub(wlen));
            let end = (start + wlen).min(samples.len());
            let fit_window = condition_fit_window(&samples[start..end], false);
            let fit =
                fit_corner_arma_from_window(&fit_window, sr, AUTHORING_RATE, FitOptions::default());
            let corner = fit.corner;

            // peak frequency of the final response
            let resp = magnitude_response(&corner, AUTHORING_RATE);
            let peak_f = resp
                .iter()
                .max_by(|a, b| a[1].partial_cmp(&b[1]).unwrap())
                .map(|p| p[0])
                .unwrap_or(0.0);
            println!(
                "\n== {name}  quality={:?}  residual={:.1}dB  post-pack={:.1}dB  formant={:.2}  drift={:.5}  response-peak={peak_f:.0}Hz ==",
                fit.quality,
                fit.diagnostics.residual_db,
                fit.diagnostics.post_pack_residual_db,
                fit.diagnostics.formant_error,
                fit.diagnostics.max_pack_drift,
            );
            println!(
                "  source peaks: {}",
                fit.diagnostics
                    .source_peaks
                    .iter()
                    .map(|p| format!("{:.0}", p.freq_hz))
                    .collect::<Vec<_>>()
                    .join(", ")
            );
            println!(
                "  fit peaks:    {}",
                fit.diagnostics
                    .fit_peaks
                    .iter()
                    .map(|p| format!("{:.0}", p.freq_hz))
                    .collect::<Vec<_>>()
                    .join(", ")
            );
            println!("  reason: {}", fit.diagnostics.rejection_reason);
            for (i, stage) in corner.iter().enumerate() {
                if is_passthrough(stage) {
                    continue;
                }
                let [b0, _b1, b2, _a1, a2] = kernel_to_biquad(stage);
                let pole_r = a2.max(0.0).sqrt();
                let zero_r = if b0.abs() > 1e-9 {
                    (b2 / b0).max(0.0).sqrt()
                } else {
                    0.0
                };
                let f = stage_frequency(stage, AUTHORING_RATE);
                let bw = -AUTHORING_RATE / std::f64::consts::PI * pole_r.max(1e-9).ln();
                println!(
                    "  actor[{i}] f={f:7.1}Hz  pole_r={pole_r:.4} (bw {bw:5.0}Hz)  zero_r={zero_r:.4}",
                    f = f,
                );
            }
        }
    }

    #[test]
    fn onset_tracks_first_transient_body() {
        let sr = 10_000.0;
        let mut samples = vec![0.0; 2_000];
        samples[740] = 0.8;
        samples[741] = 0.4;
        let onset = detect_onset(&samples, sr);
        assert!((730..=740).contains(&onset), "onset={onset}");
    }

    #[test]
    fn spectral_residual_is_low_for_self_fit() {
        // A filter's own impulse response should match its envelope tightly.
        let mut corner = [PASSTHROUGH; POLE_ZERO_COUNT];
        // one resonant stage (kernel form for a pole pair)
        corner[0] = biquad_to_kernel([1.0, 0.0, 0.0, -1.3, 0.8]);
        let sr = 39_062.5;
        // Build the filter's impulse response as the "source".
        let mut state = [[0.0_f64; 2]; POLE_ZERO_COUNT];
        let bq: Vec<[f64; 5]> = corner.iter().map(kernel_to_biquad).collect();
        let ir: Vec<f64> = (0..2048)
            .map(|idx| {
                let mut s = if idx == 0 { 1.0 } else { 0.0 };
                for (i, [b0, b1, b2, a1, a2]) in bq.iter().copied().enumerate() {
                    let y = b0 * s + state[i][0];
                    state[i][0] = b1 * s - a1 * y + state[i][1];
                    state[i][1] = b2 * s - a2 * y;
                    s = if y.is_finite() { y } else { 0.0 };
                }
                s
            })
            .collect();
        let err = spectral_residual_db(&ir, sr, &corner, sr);
        assert!(err < FIT_WARN_DB, "spectral err={err}");
    }

    fn synthetic_freq_grid() -> Vec<f64> {
        (0..FIT_BINS)
            .map(|i| {
                let t = i as f64 / (FIT_BINS - 1) as f64;
                40.0_f64 * (19_531.0_f64 / 40.0_f64).powf(t)
            })
            .collect()
    }

    fn add_env_peak(raw: &mut [f64], freqs: &[f64], center: f64, amp: f64, width_oct: f64) {
        add_log_gaussian(raw, freqs, center, amp, width_oct);
    }

    #[test]
    fn dj_alkaline_like_target_is_graphic_low_q_not_chatter() {
        let freqs = synthetic_freq_grid();
        let mut raw: Vec<f64> = freqs
            .iter()
            .map(|&f| -30.0 - 7.0 * (f / 500.0).log10())
            .collect();
        add_env_peak(&mut raw, &freqs, 900.0, 7.0, 0.34);
        add_env_peak(&mut raw, &freqs, 2_600.0, -9.0, 0.18);
        add_env_peak(&mut raw, &freqs, 4_800.0, 5.0, 0.16);
        add_env_peak(&mut raw, &freqs, 7_200.0, 6.0, 0.055);
        add_env_peak(&mut raw, &freqs, 8_700.0, 4.0, 0.050);
        add_env_peak(&mut raw, &freqs, 9_900.0, 3.5, 0.045);

        let target = stylized_target_from_raw(freqs, raw, TargetMode::LowQGraphic);
        assert!(
            (3..=6).contains(&target.source_peaks.len()),
            "peaks={:?}",
            target.source_peaks
        );
        assert!(
            target
                .valleys
                .iter()
                .any(|v| (1_500.0..=3_500.0).contains(&v.freq_hz)),
            "valleys={:?}",
            target.valleys
        );
        assert!(
            target.source_peaks.iter().any(|p| p.freq_hz > 4_000.0),
            "no simplified high teeth: {:?}",
            target.source_peaks
        );
    }

    #[test]
    fn vowel_like_target_preserves_main_landmarks() {
        let freqs = synthetic_freq_grid();
        let mut raw: Vec<f64> = freqs
            .iter()
            .map(|&f| -36.0 - 4.0 * (f / 1_000.0).log10())
            .collect();
        for (f, amp, w) in [(330.0, 8.0, 0.20), (930.0, 7.0, 0.19), (2_420.0, 6.0, 0.18)] {
            add_env_peak(&mut raw, &freqs, f, amp, w);
        }

        let target = stylized_target_from_raw(freqs, raw, TargetMode::LowQGraphic);
        for want in [330.0, 930.0, 2_420.0] {
            assert!(
                target
                    .source_peaks
                    .iter()
                    .any(|p| (p.freq_hz / want).ln().abs() <= (1.18_f64).ln()),
                "missed {want}Hz: {:?}",
                target.source_peaks
            );
        }
    }

    #[test]
    fn post_pack_response_stays_close_to_simplified_target() {
        let freqs = synthetic_freq_grid();
        let mut raw: Vec<f64> = freqs
            .iter()
            .map(|&f| -32.0 - 5.0 * (f / 800.0).log10())
            .collect();
        add_env_peak(&mut raw, &freqs, 700.0, 7.0, 0.28);
        add_env_peak(&mut raw, &freqs, 1_700.0, -5.0, 0.20);
        add_env_peak(&mut raw, &freqs, 3_400.0, 5.0, 0.22);
        add_env_peak(&mut raw, &freqs, 6_500.0, 4.0, 0.09);
        let target = stylized_target_from_raw(freqs, raw, TargetMode::LowQGraphic);

        let params = params_from_source_peaks(&target, AUTHORING_RATE, 0.82);
        let score = refine_candidate_against_envelope(params, &target, AUTHORING_RATE, 0.5, 5);
        assert!(
            score.post_pack_residual_db < 16.0,
            "post-pack residual={:.2}, peaks={:?}, fit={:?}",
            score.post_pack_residual_db,
            target.source_peaks,
            score.fit_peaks
        );
        for stage in stage_diagnostics(&score.post_pack_corner, AUTHORING_RATE) {
            assert!(
                stage.pole_radius <= 0.986,
                "ultra narrow stage survived: {:?}",
                stage
            );
        }
    }

    #[test]
    fn review_quality_does_not_auto_assign() {
        assert!(FitQuality::Ready.can_assign());
        assert!(!FitQuality::Review.can_assign());
        assert!(!FitQuality::Blocked.can_assign());
    }
}
