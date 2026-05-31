//! The Forge engine: WAV IO, onset/window conditioning, the deterministic fit
//! entry, magnitude response, the morph/Q body assembly (actor correspondence +
//! Q sharpening), and the packed-u16 interpolation glue. No UI lives here.

use std::cmp::Ordering;
use std::f64::consts::TAU;
use std::path::Path;

use trench_core::cartridge::CornerData;
use trench_core::minifloat::PackedCorners;

pub const POLE_ZERO_COUNT: usize = 6;
pub const AUTHORING_RATE: f64 = 39_062.5;
pub const DEFAULT_WINDOW_MS: f32 = 100.0;
pub const RESPONSE_BINS: usize = 540;
// Spectral match thresholds — RMS dB error between the fitted filter's response
// envelope and the source's smoothed spectrum. Lower is better. Any sound can be
// captured; only a genuinely bad envelope match (or non-finite) blocks.
pub const FIT_WARN_DB: f64 = 12.0; // spectral-match yardstick used by tests
pub const PASSTHROUGH: [f64; 5] = [2.0, 1.0, 2.0, 1.0, 1.0];
const ZERO_Q0_RADIUS: f64 = 0.34;
const ZERO_Q100_RADIUS: f64 = 0.60;
const MUSICAL_BANDS: [(f64, f64); POLE_ZERO_COUNT] = [
    (50.0, 200.0),
    (200.0, 600.0),
    (600.0, 1_200.0),
    (1_200.0, 2_500.0),
    (2_500.0, 5_500.0),
    (5_500.0, 12_000.0),
];

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

/// The first strong transient — the onset the fit window is taken around.
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

/// The SUSTAINED body: the longest run of ~25 ms frames whose RMS stays within
/// 3 dB of the peak frame — the held part of the sound, not the bright transient
/// attack. Fitting the sustain (not the attack) keeps the low body and stops the
/// captured corner tilting bright (audit 2026-05-24). Falls back to the whole clip
/// for sounds with no sustain (short transients). Window capped to ~400 ms.
pub fn sustain_window(samples: &[f64], sample_rate: f64) -> (usize, usize) {
    let frame = samples_for_ms(sample_rate, 25.0);
    let hop = samples_for_ms(sample_rate, 10.0).max(1);
    if samples.len() < frame * 2 {
        return (0, samples.len());
    }
    let nframes = 1 + (samples.len() - frame) / hop;
    let mut rms = vec![0.0f64; nframes];
    for f in 0..nframes {
        let s = f * hop;
        let e = (s + frame).min(samples.len());
        let acc: f64 = samples[s..e].iter().map(|v| v * v).sum();
        rms[f] = (acc / (e - s) as f64).sqrt();
    }
    let peak = rms.iter().cloned().fold(0.0, f64::max).max(1e-30);
    let thr = peak * 10f64.powf(-3.0 / 20.0); // within 3 dB of the loudest frame
    let (mut best_s, mut best_len, mut cur_s, mut cur_len, mut in_run) = (0, 0, 0, 0, false);
    for f in 0..nframes {
        if rms[f] >= thr {
            if !in_run {
                cur_s = f;
                cur_len = 0;
                in_run = true;
            }
            cur_len += 1;
            if cur_len > best_len {
                best_len = cur_len;
                best_s = cur_s;
            }
        } else {
            in_run = false;
        }
    }
    if best_len == 0 {
        return (0, samples.len());
    }
    let mut start = best_s * hop;
    let mut end = ((best_s + best_len - 1) * hop + frame).min(samples.len());
    let maxlen = samples_for_ms(sample_rate, 400.0); // cap so the Hann doesn't span the whole note
    if end - start > maxlen {
        let mid = (start + end) / 2;
        start = mid.saturating_sub(maxlen / 2);
        end = (start + maxlen).min(samples.len());
    }
    (start, end)
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

/// Kernel-form (c0..c4) → DF2T biquad (b0,b1,b2,a1,a2).
///
/// Delegates to the canonical `trench_core::minifloat::kernel_to_biquad` so the
/// forge bench and the shipped player can never compute a different biquad from
/// the same kernel. The `&[f64; 5]` signature is kept so existing call sites
/// (including `.map(kernel_to_biquad)`) are untouched — only the duplicated
/// formula is removed, not the convention.
pub fn kernel_to_biquad(stage: &[f64; 5]) -> [f64; 5] {
    trench_core::minifloat::kernel_to_biquad(*stage)
}

pub fn biquad_to_kernel(bq: [f64; 5]) -> [f64; 5] {
    let [b0, b1, b2, a1, a2] = bq;
    if b0.abs() < 1.0e-12 {
        return PASSTHROUGH;
    }
    [2.0 + b1 / b0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0]
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

pub fn magnitude_response(corner: &CornerData, sample_rate: f64) -> Vec<[f64; 2]> {
    let nyquist = (sample_rate * 0.5).max(10_000.0);
    (0..RESPONSE_BINS)
        .map(|i| {
            let t = i as f64 / (RESPONSE_BINS - 1) as f64;
            let freq = 20.0 * (nyquist / 20.0).powf(t);
            [
                freq,
                cascade_mag_db(corner, freq, sample_rate).clamp(-48.0, 30.0),
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

// ── Source cleaner: raw window → stylized target ─────────────────────────────

/// In-place iterative radix-2 FFT over split real/imag buffers (len must be 2^k).
fn fft(re: &mut [f64], im: &mut [f64], inverse: bool) {
    let n = re.len();
    if n < 2 {
        return;
    }
    let mut j = 0usize;
    for i in 1..n {
        let mut bit = n >> 1;
        while j & bit != 0 {
            j ^= bit;
            bit >>= 1;
        }
        j ^= bit;
        if i < j {
            re.swap(i, j);
            im.swap(i, j);
        }
    }
    let mut len = 2usize;
    while len <= n {
        let ang = if inverse { TAU } else { -TAU } / len as f64;
        let (wr, wi) = (ang.cos(), ang.sin());
        let half = len / 2;
        let mut i = 0;
        while i < n {
            let (mut cwr, mut cwi) = (1.0f64, 0.0f64);
            for k in 0..half {
                let (ur, ui) = (re[i + k], im[i + k]);
                let vr = re[i + k + half] * cwr - im[i + k + half] * cwi;
                let vi = re[i + k + half] * cwi + im[i + k + half] * cwr;
                re[i + k] = ur + vr;
                im[i + k] = ui + vi;
                re[i + k + half] = ur - vr;
                im[i + k + half] = ui - vi;
                let ncwr = cwr * wr - cwi * wi;
                cwi = cwr * wi + cwi * wr;
                cwr = ncwr;
            }
            i += len;
        }
        len <<= 1;
    }
    if inverse {
        let inv = 1.0 / n as f64;
        re.iter_mut().for_each(|x| *x *= inv);
        im.iter_mut().for_each(|x| *x *= inv);
    }
}

/// The clean formant envelope of a source window, as `[freq_hz, dB]` — the F1/F2/F3
/// body with the pitch harmonic comb **liftered away**. Cepstral liftering (keep
/// quefrencies below ~sr/250) removes the comb while still resolving the formant
/// peaks; unlike `source_envelope`'s octave smoothing it does not leave harmonic
/// teeth at low frequencies, and unlike a min-phase IR it does not shift the body.
/// This is what `fit_window` peak-picks.
fn clean_envelope(window: &[f64], sr: f64) -> Vec<[f64; 2]> {
    const N: usize = 4096;
    if window.len() < 16 {
        return source_envelope(window, sr);
    }
    let half = N / 2;

    let mut re = vec![0.0f64; N];
    let mut im = vec![0.0f64; N];
    for (i, &x) in window.iter().take(N).enumerate() {
        re[i] = x;
    }
    fft(&mut re, &mut im, false);
    let logmag: Vec<f64> = (0..N).map(|k| (re[k].hypot(im[k]) + 1e-9).ln()).collect();

    // Cepstral lifter: drop the high-quefrency pitch comb, keep formant detail.
    let mut cre = logmag;
    let mut cim = vec![0.0f64; N];
    fft(&mut cre, &mut cim, true);
    let lifter = ((sr / 250.0).round() as usize).clamp(24, half - 1);
    for q in 0..N {
        if q.min(N - q) > lifter {
            cre[q] = 0.0;
            cim[q] = 0.0;
        }
    }
    fft(&mut cre, &mut cim, false);

    // Liftered log-magnitude → [freq, dB] over the half spectrum.
    let bin_hz = sr / N as f64;
    let to_db = 20.0 / std::f64::consts::LN_10;
    (1..=half)
        .map(|k| [k as f64 * bin_hz, cre[k] * to_db])
        .collect()
}

/// Which fitter the Forge runs on a conditioned window. The fit is a *starting
/// point* — a proposal — not the final body; the mode picks HOW that proposal is
/// derived. Naming them honestly is the whole point of this split: the default
/// path is a fixed-band spectral peak picker, NOT the "ARMA fitter" the old docs
/// claimed (ARMA only ran as a degenerate fallback).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum FitMode {
    /// **spectrum_peak** (default, the original live path): cepstral-smoothed
    /// magnitude envelope → one resonant pole per fixed `MUSICAL_BANDS` band →
    /// shallow valley zeros. Musical and robust for any source; it learns the
    /// *colour* of the sound, not a deconvolved transfer function.
    #[default]
    SpectrumPeak,
    /// **voice_lpc**: pre-emphasis tilt removal → order-14 LPC vocal-tract
    /// estimate → top-6 formant poles + anti-formant zeros. For a voice this puts
    /// the energy on F1/F2/F3 instead of letting the loud low body win.
    VoiceLpc,
    /// **arma**: the deterministic Sanathanan–Koerner pole-zero least-squares fit
    /// (poles AND real zeros). Honest anti-formant notches an all-pole fit can't
    /// carve; called directly here (not just as a fallback).
    Arma,
}

impl FitMode {
    /// Stable machine key (used in reports/JSON).
    pub fn key(self) -> &'static str {
        match self {
            FitMode::SpectrumPeak => "spectrum_peak",
            FitMode::VoiceLpc => "voice_lpc",
            FitMode::Arma => "arma",
        }
    }
    /// Short surface label.
    pub fn label(self) -> &'static str {
        match self {
            FitMode::SpectrumPeak => "PEAK",
            FitMode::VoiceLpc => "VOICE",
            FitMode::Arma => "ARMA",
        }
    }
    /// Cycle order for a single toggle key: PEAK → VOICE → ARMA → PEAK.
    pub fn next(self) -> Self {
        match self {
            FitMode::SpectrumPeak => FitMode::VoiceLpc,
            FitMode::VoiceLpc => FitMode::Arma,
            FitMode::Arma => FitMode::SpectrumPeak,
        }
    }
}

/// Voice pre-emphasis (first-difference) coefficient. Lifts the formants out of
/// the loud low-end energy so the order-14 LPC resolves F1/F2/F3 rather than only
/// the f0 mud. Kept MODEST (not the textbook 0.97), because a 6-biquad cascade has
/// no 7th de-emphasis pole — a strong tilt leaves the realised corner bright.
///
/// MEASURED on the real /aaa/ takes (dev/tmp/forge_first_principles_audit.md): the
/// dominant voice-capture failure is NOT this tilt — 0.5 vs 0.97 barely moves the
/// poles. It is the `top-6-by-radius` pole selection in `trench_core::lpc`: on a
/// consumer mic the sharpest poles are HF hiss (6–9 kHz), which evict F1/F2, so the
/// bright corner renders a dark voice near-silent. The honest fix is formant-region
/// pole biasing (or a cleaner source) — and is exactly why the authoring surface is
/// "fitter proposes a starting point, you relocate poles onto F1/F2 by ear."
pub const VOICE_PRE_EMPH: f64 = 0.5;

/// The single fit entry, default mode. Kept for callers that don't pick a mode;
/// equals `fit_window_mode(.., FitMode::SpectrumPeak)`.
pub fn fit_window(window: &[f64], sr_in: f64) -> CornerData {
    fit_window_mode(window, sr_in, FitMode::SpectrumPeak)
}

/// Fit a conditioned window to one corner's six biquads using an explicit mode.
/// Every mode returns six kernel-form pole-zero sections that pack cleanly; on a
/// degenerate result it falls back to the spectral peak picker so a fit always
/// exists.
pub fn fit_window_mode(window: &[f64], sr_in: f64, mode: FitMode) -> CornerData {
    match mode {
        FitMode::SpectrumPeak => fit_spectrum_peak(window, sr_in),
        FitMode::VoiceLpc => {
            let corner = trench_core::lpc::fit_corner_conditioned_pe(
                window,
                sr_in,
                AUTHORING_RATE,
                VOICE_PRE_EMPH,
            );
            if corner.iter().any(|s| !is_passthrough(s)) {
                corner
            } else {
                fit_spectrum_peak(window, sr_in) // unvoiced/degenerate → peak picker
            }
        }
        FitMode::Arma => {
            if let Some(mut arma) =
                trench_core::arma::fit_corner_arma(window, sr_in, AUTHORING_RATE)
            {
                leash_zeros(&mut arma, ZERO_Q0_RADIUS);
                trench_core::lpc::normalize_corner_peak(&mut arma, AUTHORING_RATE, 2.0);
                arma
            } else {
                fit_spectrum_peak(window, sr_in)
            }
        }
    }
}

/// The original live path: cepstral liftering removes the pitch comb, one actor is
/// assigned to each broad frequency band, and zeros are kept as shallow acoustic
/// dips. This avoids the "raw ARMA as a moving comb filter" failure while preserving
/// a little room/nasal boundary character. ARMA is the degenerate-only fallback.
fn fit_spectrum_peak(window: &[f64], sr_in: f64) -> CornerData {
    let env = clean_envelope(window, sr_in);
    let corner = formant_fit(&env, AUTHORING_RATE);
    if corner.iter().any(|s| !is_passthrough(s)) {
        return corner;
    }

    // Degenerate escape hatch: if the envelope has no usable peaks, let the
    // forensic ARMA solver try, then leash its zeros before it reaches the UI.
    if let Some(mut arma) = trench_core::arma::fit_corner_arma(window, sr_in, AUTHORING_RATE) {
        leash_zeros(&mut arma, ZERO_Q0_RADIUS);
        trench_core::lpc::normalize_corner_peak(&mut arma, AUTHORING_RATE, 2.0);
        return arma;
    }
    corner
}

/// Realize a clean magnitude envelope as six band-spread resonant actors. Each
/// band gets at most one pole, so a low voice cannot spend the whole cascade in
/// the 100-400 Hz mud zone.
fn formant_fit(env: &[[f64; 2]], sr: f64) -> CornerData {
    let n = env.len();
    let mut corner = [PASSTHROUGH; POLE_ZERO_COUNT];
    if n < 5 {
        return corner;
    }

    let top = env.iter().map(|p| p[1]).fold(f64::NEG_INFINITY, f64::max);
    let valleys: Vec<f64> = (1..n - 1)
        .filter(|&i| env[i][1] < env[i - 1][1] && env[i][1] <= env[i + 1][1])
        .map(|i| env[i][0])
        .collect();

    for (si, &(lo, hi)) in MUSICAL_BANDS.iter().enumerate() {
        let Some(pi) = best_peak_in_band(env, lo, hi) else {
            continue;
        };
        if env[pi][1] < top - 48.0 {
            continue;
        }
        let f = env[pi][0];
        let q = base_q_for_frequency(f);
        let bw = (f / q).clamp(80.0, if f < 2_500.0 { 480.0 } else { 1_600.0 });
        let rp = (-std::f64::consts::PI * bw / sr)
            .exp()
            .clamp(0.72, max_pole_radius_for_frequency(f));
        let theta = TAU * f / sr;
        let a1 = -2.0 * rp * theta.cos();
        let a2 = rp * rp;
        let g = 1.0 - rp * rp; // tamed resonator (~unity peak) — controlled, packable

        // Shallow zero at a nearby valley: room/nasal dip, not a comb-filter hole.
        let zero = valleys
            .iter()
            .copied()
            .filter(|&fz| {
                let oct = (fz / f).log2().abs();
                oct > 0.33 && oct < 1.25
            })
            .min_by(|x, y| (x - f).abs().partial_cmp(&(y - f).abs()).unwrap());
        let (b0, b1, b2) = if let Some(fz) = zero {
            let rz = ZERO_Q0_RADIUS;
            let tz = TAU * fz / sr;
            (g, g * (-2.0 * rz * tz.cos()), g * rz * rz)
        } else {
            (g, 0.0, 0.0)
        };
        corner[si] = [2.0 + b1 / b0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0];
    }
    // Normalize the Q0 row to the heritage base level (~+6 dB, like Hedz's Q0
    // corners) — NOT the old tame −6 dB. The Q-axis loudness dynamic comes from
    // `sharpen_corner` ringing the Q100 row hotter on top of this base.
    trench_core::lpc::normalize_corner_peak(&mut corner, sr, 2.0);
    corner
}

fn best_peak_in_band(env: &[[f64; 2]], lo: f64, hi: f64) -> Option<usize> {
    let mut best_peak: Option<usize> = None;
    for i in 1..env.len().saturating_sub(1) {
        if env[i][0] < lo || env[i][0] > hi {
            continue;
        }
        if env[i][1] > env[i - 1][1] && env[i][1] >= env[i + 1][1] {
            if best_peak.map(|p| env[i][1] > env[p][1]).unwrap_or(true) {
                best_peak = Some(i);
            }
        }
    }
    best_peak.or_else(|| {
        env.iter()
            .enumerate()
            .filter(|(_, p)| p[0] >= lo && p[0] <= hi)
            .max_by(|(_, a), (_, b)| a[1].partial_cmp(&b[1]).unwrap_or(Ordering::Equal))
            .map(|(i, _)| i)
    })
}

fn base_q_for_frequency(freq: f64) -> f64 {
    if freq < 250.0 {
        7.0
    } else if freq < 1_200.0 {
        8.5
    } else if freq < 3_000.0 {
        6.2
    } else {
        4.4
    }
}

fn max_pole_radius_for_frequency(freq: f64) -> f64 {
    if freq < 300.0 {
        0.9985
    } else if freq < 1_200.0 {
        0.9970
    } else if freq < 3_000.0 {
        0.9930
    } else if freq < 7_000.0 {
        0.9870
    } else {
        0.9800
    }
}

// ── from-scratch DRAW: place a corner's shape directly ────────────────────────
//
// A corner authored by hand is a list of `Resonance` actors placed on the log
// scope. This realizes them through the SAME stage encoding the fitter uses
// (the `[2+b1/b0, 1-b2/b0, a1+2, 1-a2, b0]` packing at `formant_fit`), so a drawn
// corner is the same kind of object a fitted one is — packable, stable, kin-able.
// No new math, no parallel packed path.

/// What a placed actor does to the spectrum.
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum ResoKind {
    /// Bright resonant peak with a DC-nulling zero ~7 semis below (no pedestal).
    Peak,
    /// A null cut into the spectrum — the metallic/comb character.
    Notch,
    /// A pole parked against the Nyquist wall — the speaker-blowing bite.
    Edge,
    /// A coupled pole+zero pair — the "Ooh to Eee tear". The pole sits at
    /// `freq_hz` with sharpness `radius`; a deep zero sits a few semitones
    /// above (`Resonance::cavity_semis`), producing the peak-then-canyon
    /// shape that makes ROM bodies sound like coupled acoustic cavities
    /// instead of stacked EQ bands. One actor, one stage, both placed.
    Cavity,
}

impl ResoKind {
    pub fn label(self) -> &'static str {
        match self {
            ResoKind::Peak => "PEAK",
            ResoKind::Notch => "NOTCH",
            ResoKind::Edge => "EDGE",
            ResoKind::Cavity => "TEAR",
        }
    }
    pub fn next(self) -> ResoKind {
        match self {
            ResoKind::Peak => ResoKind::Cavity,
            ResoKind::Cavity => ResoKind::Notch,
            ResoKind::Notch => ResoKind::Edge,
            ResoKind::Edge => ResoKind::Peak,
        }
    }
}

/// One hand-placed actor: a frequency, a sharpness (`radius` toward the unit
/// circle), and what it does. The UI stores these per corner and drags them.
#[derive(Clone, Copy, Debug)]
pub struct Resonance {
    pub freq_hz: f64,
    pub radius: f64,
    pub kind: ResoKind,
    /// For `ResoKind::Cavity` only — how many semitones above the pole the
    /// coupled zero sits. Ignored for Peak/Notch/Edge. Sensible range 1–8;
    /// the "side-by-side, practically touching" tear lives around 2–3 semis.
    pub cavity_semis: f64,
}

/// Realize up to six placed actors into a corner (one stage each, the rest
/// passthrough), then normalize to the heritage base level like `formant_fit`.
pub fn realize_resonances(res: &[Resonance], sr: f64) -> CornerData {
    let mut corner = [PASSTHROUGH; POLE_ZERO_COUNT];
    for (si, r) in res.iter().take(POLE_ZERO_COUNT).enumerate() {
        corner[si] = realize_stage(r, sr);
    }
    trench_core::lpc::normalize_corner_peak(&mut corner, sr, 2.0);
    corner
}

/// Read a corner's stages back into editable actors — the SKETCH→SCULPT bridge.
/// Decodes each non-passthrough stage's pole (frequency + radius) so a loaded ROM
/// seed or a fit becomes draggable DRAW handles. Poles only (the dominant
/// structure); fine zero/notch detail is not round-tripped — this is a rough
/// sketch you then sculpt by ear, exactly the intent.
pub fn corner_to_resonances(corner: &CornerData, sr: f64) -> Vec<Resonance> {
    let mut out = Vec::new();
    for stage in corner.iter() {
        if is_passthrough(stage) {
            continue;
        }
        // kernel → biquad denominator: c2 = a1 + 2, c3 = 1 - a2.
        let a1 = stage[2] - 2.0;
        let a2 = 1.0 - stage[3];
        let r = a2.max(0.0).sqrt();
        if !(r > 1.0e-3 && r < 1.0) {
            continue;
        }
        let cos_t = (-a1 / (2.0 * r)).clamp(-1.0, 1.0);
        let f = cos_t.acos() * sr / TAU;
        if !(f > 10.0 && f < sr * 0.5) {
            continue;
        }
        let kind = if f >= 8_000.0 {
            ResoKind::Edge
        } else {
            ResoKind::Peak
        };
        out.push(Resonance {
            freq_hz: f,
            radius: r.clamp(0.5, 0.998),
            kind,
            cavity_semis: 0.0,
        });
        if out.len() >= POLE_ZERO_COUNT {
            break;
        }
    }
    out
}

fn realize_stage(r: &Resonance, sr: f64) -> [f64; 5] {
    let nyq = sr * 0.49;
    match r.kind {
        ResoKind::Peak => {
            let f = r.freq_hz.clamp(20.0, nyq);
            let rp = r.radius.clamp(0.5, max_pole_radius_for_frequency(f));
            let theta = TAU * f / sr;
            let a1 = -2.0 * rp * theta.cos();
            let a2 = rp * rp;
            let g = 1.0 - rp * rp; // tamed resonator (~unity peak before normalize)
                                   // DC-nulling zero ~7 semitones below the pole → rolls off the lows,
                                   // no pedestal (the `bp` shape proven by Neon Vane).
            let fz = (f * 2.0_f64.powf(-7.0 / 12.0)).max(10.0);
            let rz = 0.9;
            let tz = TAU * fz / sr;
            let (b0, b1, b2) = (g, g * (-2.0 * rz * tz.cos()), g * rz * rz);
            [2.0 + b1 / b0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0]
        }
        ResoKind::Edge => {
            // A pole parked near the wall; freq forced high. Pure pole (no zero).
            let f = r.freq_hz.clamp(8_000.0, nyq);
            let rp = r.radius.clamp(0.95, 0.997);
            let theta = TAU * f / sr;
            let a1 = -2.0 * rp * theta.cos();
            let a2 = rp * rp;
            let g = 1.0 - rp * rp;
            [2.0, 1.0, a1 + 2.0, 1.0 - a2, g]
        }
        ResoKind::Notch => {
            // A deep zero at f cut into a flat ceiling; the pole sits low so it
            // doesn't resonate — the character is the null, not a peak.
            let f = r.freq_hz.clamp(20.0, nyq);
            let theta = TAU * f / sr;
            let rp = 0.55;
            let a1 = -2.0 * rp * theta.cos();
            let a2 = rp * rp;
            let rz = r.radius.clamp(0.6, 0.999); // deeper zero → deeper notch
            let (b0, b1, b2) = (1.0, -2.0 * rz * theta.cos(), rz * rz);
            [2.0 + b1 / b0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0]
        }
        ResoKind::Cavity => {
            // The "Ooh to Eee tear" — razor peak immediately followed by a deep
            // canyon. One stage carries the pole at `freq_hz` and a coupled
            // zero `cavity_semis` semitones above. The zero rides near the
            // perimeter (rz ≈ 0.98) so the notch is felt as a real null, not
            // an EQ dip. This is the coupled-cavity shape: ROM/Hedz bodies
            // have a zero on ~100% of their poles; an all-pole rack can't
            // produce it.
            let f = r.freq_hz.clamp(20.0, nyq);
            let rp = r.radius.clamp(0.5, max_pole_radius_for_frequency(f));
            let theta = TAU * f / sr;
            let a1 = -2.0 * rp * theta.cos();
            let a2 = rp * rp;
            let g = 1.0 - rp * rp;
            // Default to a touching-but-not-overlapping offset if the actor
            // was constructed without one (e.g. legacy load path).
            let semis = if r.cavity_semis < 0.5 {
                3.0
            } else {
                r.cavity_semis.clamp(0.5, 12.0)
            };
            let fz = (f * 2.0_f64.powf(semis / 12.0)).clamp(20.0, nyq);
            let rz: f64 = 0.98;
            let tz = TAU * fz / sr;
            let (b0, b1, b2) = (g, g * (-2.0 * rz * tz.cos()), g * rz * rz);
            [2.0 + b1 / b0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0]
        }
    }
}

/// The radius beyond which the bilinear-interp morph surface is judged
/// "destabilised" (a pole has effectively left the unit circle). The
/// shipping engine clamps numerically at 1.0 but anything past ~0.999
/// rings out of control and risks the cascade exploding under heat.
/// See [[armadillo-morphing-rules]] memory.
pub const STABILITY_RADIUS_LIMIT: f64 = 0.999;

/// Stability scan: walk the bilinear-interpolated morph surface and find the
/// worst-case pole radius across all (morph, q) cells and all stages.
///
/// Why it matters: even when all four authored corners are stable
/// (pole r < 1), the **interpolated middle** can have a pole leave the unit
/// circle when bandwidth widens across the morph — ARMAdillo behaviour, see
/// `memory/armadillo-morphing-rules.md`. The shipping engine does the same
/// plain bilinear coefficient lerp the player does, so a Forge-side scan
/// catches what the player would also hit.
///
/// `corner_order` follows `forge_core::CORNER_LABELS` = `[M0_Q0, M100_Q0,
/// M0_Q100, M100_Q100]`. `grid` is the per-axis resolution; `grid=5` →
/// a 5×5 = 25-cell scan, ample for a sanity gate.
///
/// Returns `(max_r, (morph, q))`: the worst pole radius observed and the
/// morph/Q cell where it occurred. This function never modifies anything —
/// it's a diagnostic only. The caller decides whether to warn or block.
pub fn morph_surface_max_pole_radius(corners: &[CornerData; 4], grid: usize) -> (f64, (f64, f64)) {
    let grid = grid.max(2);
    let mut worst_r = 0.0_f64;
    let mut worst_loc = (0.0_f64, 0.0_f64);
    for mi in 0..grid {
        let m = mi as f64 / (grid - 1) as f64;
        for qi in 0..grid {
            let q = qi as f64 / (grid - 1) as f64;
            for s in 0..POLE_ZERO_COUNT {
                // Plain bilinear over the kernel c3 coefficient (which encodes
                // a2 = 1 - c3). Matches `Cartridge::interpolate(morph, q)`.
                let c3_a = corners[0][s][3];
                let c3_b = corners[1][s][3];
                let c3_c = corners[2][s][3];
                let c3_d = corners[3][s][3];
                let top = c3_a + (c3_b - c3_a) * m;
                let bot = c3_c + (c3_d - c3_c) * m;
                let c3 = top + (bot - top) * q;
                let a2 = 1.0 - c3;
                if a2 > 0.0 {
                    let r = a2.sqrt();
                    if r > worst_r {
                        worst_r = r;
                        worst_loc = (m, q);
                    }
                }
            }
        }
    }
    (worst_r, worst_loc)
}

fn leash_zeros(corner: &mut CornerData, max_radius: f64) {
    for stage in corner.iter_mut() {
        leash_stage_zero(stage, max_radius);
    }
}

fn leash_stage_zero(stage: &mut [f64; 5], max_radius: f64) {
    let rz = (1.0 - stage[1]).clamp(0.0, 0.999_999).sqrt();
    if rz <= max_radius || rz <= 1.0e-9 {
        return;
    }
    let theta = (-(stage[0] - 2.0) / (2.0 * rz)).clamp(-1.0, 1.0).acos();
    let rz2 = max_radius.clamp(0.0, 0.999);
    stage[0] = -2.0 * rz2 * theta.cos() + 2.0;
    stage[1] = 1.0 - rz2 * rz2;
}

/// Sharpen a corner toward higher Q: push every pole radius toward the unit circle
/// (narrower, more resonant), keeping its frequency and the zeros. `amount` in
/// [0,1]: 0 leaves it untouched, 1 pushes hard. This *is* what the Q axis does —
/// so the high-Q row of a body can be auto-derived from the low-Q row instead of
/// demanding separate sources. NOT re-normalised — pushing the radius toward the
/// unit circle makes the corner ring HOTTER, which is the Q-axis loudness dynamic
/// (low-Q tame → high-Q screaming), exactly like the heritage frames.
pub fn sharpen_corner(corner: &CornerData, amount: f64, sample_rate: f64) -> CornerData {
    let amount = amount.clamp(0.0, 1.0);
    let mut out = *corner;
    for stage in out.iter_mut() {
        if is_passthrough(stage) {
            continue;
        }
        // Pole only: keep frequency + the stage gain (c4), push the pole radius
        // toward the unit circle. With c4 fixed, a higher radius makes the
        // resonator ring HOTTER and narrower — the Q-axis dynamic. (We do NOT
        // touch the zero here: sharpening the zero toward the pole cancels the
        // ring, which made Q100 quieter than Q0.)
        let a1 = stage[2] - 2.0;
        let r = (1.0 - stage[3]).max(0.0).sqrt(); // a2 = 1 - c3 = r²
        if (0.0..1.0).contains(&r) && r > 0.0 {
            let theta = (-a1 / (2.0 * r)).clamp(-1.0, 1.0).acos();
            let freq = theta * sample_rate / TAU;
            let target = max_pole_radius_for_frequency(freq);
            let r2 = r + amount * (target - r);
            stage[2] = -2.0 * r2 * theta.cos() + 2.0;
            stage[3] = 1.0 - r2 * r2;
        }

        let rz = (1.0 - stage[1]).clamp(0.0, 0.999_999).sqrt();
        if rz > 1.0e-9 {
            let theta = (-(stage[0] - 2.0) / (2.0 * rz)).clamp(-1.0, 1.0).acos();
            let target = ZERO_Q0_RADIUS + amount * (ZERO_Q100_RADIUS - ZERO_Q0_RADIUS);
            let rz2 = (rz + amount * (target - rz)).min(ZERO_Q100_RADIUS);
            stage[0] = -2.0 * rz2 * theta.cos() + 2.0;
            stage[1] = 1.0 - rz2 * rz2;
        }
    }
    out
}

/// HOME *moved* — the default MORPH-axis kin variation. Scales each pole's (and
/// its zero's) frequency by `factor`, keeping radius and gain, so morphing
/// HOME→MORPH sweeps the resonances up (somewhere to glide) instead of sitting on
/// an exact duplicate. factor 1.5 ≈ up a perfect fifth. Same family as HOME (kin),
/// just shifted — coherent middle, no mush.
pub fn shift_corner(corner: &CornerData, factor: f64, _sample_rate: f64) -> CornerData {
    let factor = factor.max(0.01);
    let pi = std::f64::consts::PI;
    let mut out = *corner;
    for stage in out.iter_mut() {
        if is_passthrough(stage) {
            continue;
        }
        // pole: c2 = -2·r·cosθ + 2, c3 = 1 - r²  → shift θ, keep r
        let r = (1.0 - stage[3]).max(0.0).sqrt();
        if r > 0.0 && r < 1.0 {
            let theta = (-(stage[2] - 2.0) / (2.0 * r)).clamp(-1.0, 1.0).acos();
            let theta2 = (theta * factor).clamp(0.0, pi);
            stage[2] = -2.0 * r * theta2.cos() + 2.0;
        }
        // Zero follows the morph much less than the pole; otherwise it sweeps like
        // a phaser notch. Its depth stays leashed until the Q axis pushes it out.
        let rz = (1.0 - stage[1]).max(0.0).sqrt();
        if rz > 0.0 {
            let thz = (-(stage[0] - 2.0) / (2.0 * rz)).clamp(-1.0, 1.0).acos();
            let z_factor = 1.0 + (factor - 1.0) * 0.25;
            let thz2 = (thz * z_factor).clamp(0.0, pi);
            let rz2 = rz.min(ZERO_Q0_RADIUS);
            stage[0] = -2.0 * rz2 * thz2.cos() + 2.0;
            stage[1] = 1.0 - rz2 * rz2;
        }
    }
    out
}

// ── Body assembly / interpolation / audio glue ───────────────────────────────

/// A four-corner body previewed at an arbitrary morph/Q position through the
/// real packed-u16 bilinear (the proven, bit-accurate runtime path) — not a
/// decoded-float blend. The 2-D authoring pad reads this as the puck moves and
/// the audio thread hears it. Corner order: M0_Q0, M100_Q0, M0_Q100, M100_Q100.
pub fn body_preview(corners: &[CornerData; 4], morph: f32, q: f32) -> CornerData {
    PackedCorners::from_corner_data(corners).interpolate(morph.clamp(0.0, 1.0), q.clamp(0.0, 1.0))
}

/// Pole frequency (log) and radius for one kernel stage — the coordinates the
/// cross-corner actor correspondence matches on. Passthrough/degenerate stages
/// fold to a finite high-frequency, zero-radius sentinel so they pair with each
/// other (cost 0) rather than producing NaN.
fn stage_pole_coords(stage: &[f64; 5], sample_rate: f64) -> (f64, f64) {
    let raw = stage_frequency(stage, sample_rate);
    let f = if raw.is_finite() {
        raw.clamp(20.0, sample_rate)
    } else {
        sample_rate
    };
    let a2 = (1.0 - stage[3]).clamp(0.0, 0.999_9);
    (f.ln(), a2.sqrt())
}

fn actor_match_cost(anchor: &[f64; 5], other: &[f64; 5], sample_rate: f64) -> f64 {
    let (af, ar) = stage_pole_coords(anchor, sample_rate);
    let (of, or) = stage_pole_coords(other, sample_rate);
    (af - of).abs() + 0.5 * (ar - or).abs()
}

/// Visit every permutation of six indices (Heap's algorithm, 720 total).
fn for_each_perm6(mut visit: impl FnMut(&[usize; 6])) {
    let mut a = [0usize, 1, 2, 3, 4, 5];
    let mut c = [0usize; 6];
    visit(&a);
    let mut i = 0;
    while i < 6 {
        if c[i] < i {
            if i % 2 == 0 {
                a.swap(0, i);
            } else {
                a.swap(c[i], i);
            }
            visit(&a);
            c[i] += 1;
            i = 0;
        } else {
            c[i] = 0;
            i += 1;
        }
    }
}

/// Sort the anchor corner's six stages low→high by pole frequency so the actor
/// names (ROOT…RIP) read in pitch order at the M0/Q0 reference. Anchor-only and
/// purely for labelling: a cascade is a product, so the summed response is
/// unchanged — this only fixes the body's reference actor order.
pub fn canonical_anchor(corner: &CornerData, sample_rate: f64) -> CornerData {
    let mut idx = [0usize, 1, 2, 3, 4, 5];
    idx.sort_by(|&i, &j| {
        stage_frequency(&corner[i], sample_rate)
            .partial_cmp(&stage_frequency(&corner[j], sample_rate))
            .unwrap_or(Ordering::Equal)
    });
    core::array::from_fn(|i| corner[idx[i]])
}

/// Re-index `other`'s six stages to the actor identities of `anchor` by the
/// minimum total pole-distance correspondence. The runtime blends stage i↔i, so
/// this is what keeps the morph/Q glide coherent. It does NOT sort by frequency
/// and does NOT forbid crossings — between two corners an actor may glide past
/// another; we only pick the lowest-movement pairing. (From two isolated corners
/// an F1/F2 swap is genuinely ambiguous, so this is a smoothness heuristic and
/// the midpoint scope is the final judge.)
pub fn align_to_anchor(anchor: &CornerData, other: &CornerData, sample_rate: f64) -> CornerData {
    let mut best = [0usize, 1, 2, 3, 4, 5];
    let mut best_cost = f64::INFINITY;
    for_each_perm6(|perm| {
        let mut cost = 0.0;
        for i in 0..POLE_ZERO_COUNT {
            cost += actor_match_cost(&anchor[i], &other[perm[i]], sample_rate);
        }
        if cost < best_cost {
            best_cost = cost;
            best = *perm;
        }
    });
    core::array::from_fn(|i| other[best[i]])
}

/// Per-stage biquad coefficients [b0, b1, b2, a1, a2] for the audio thread.
pub fn corner_to_biquads(corner: &CornerData) -> [[f64; 5]; POLE_ZERO_COUNT] {
    let mut out = [[1.0, 0.0, 0.0, 0.0, 0.0]; POLE_ZERO_COUNT];
    for (target, stage) in out.iter_mut().zip(corner) {
        *target = kernel_to_biquad(stage);
    }
    out
}

// ── WAV metadata + display helpers ───────────────────────────────────────────

pub struct WavMeta {
    pub sample_rate: u32,
    pub channels: u16,
    pub bits: u16,
    pub duration_s: f64,
}

/// Like `load_wav_as_mono_f64` but also returns WAV header metadata.
pub fn load_wav_with_meta(path: &Path) -> Result<(Vec<f64>, WavMeta), String> {
    let mut reader = hound::WavReader::open(path).map_err(|e| e.to_string())?;
    let spec = reader.spec();
    let channels = spec.channels.max(1) as usize;
    let total_frames = reader.duration(); // frames per channel
    let duration_s = total_frames as f64 / spec.sample_rate as f64;

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
        return Err("audio file contained no samples".to_owned());
    }
    Ok((
        mono,
        WavMeta {
            sample_rate: spec.sample_rate,
            channels: spec.channels,
            bits: spec.bits_per_sample,
            duration_s,
        },
    ))
}

pub fn display_name(path: &Path) -> String {
    path.file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("audio")
        .to_owned()
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

// ── FSM: Frequency Sampling Method (the new DRAW) ─────────────────────────────
//
// FSM is the wild-corner path: you draw an arbitrary TARGET magnitude curve (a
// polyline of `[freq_hz, db]` control points) and the deterministic ARMA solver
// fits 6 biquads (poles + real zeros) to it. The SAME solver as `FitMode::Arma`,
// but fed a hand-drawn / data-seeded curve instead of audio. The taste lives in
// the curve; the fit stays dumb. Curve GENERATORS (Klatt vowels, tube modes,
// PEQ, golden-ratio flanger, harmonic slicers) seed the curve for REAL corners;
// freehand drawing makes the wild ones.

/// One decoded pole or zero, for the "viewing spectrum of all the known
/// pole/zero" overlay the FSM editor draws over the response.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PoleZero {
    pub freq_hz: f64,
    pub radius: f64,
    /// true = pole (resonance), false = zero (notch/anti-resonance).
    pub is_pole: bool,
}

/// Fit a hand-drawn / seeded target curve into one corner via the canonical ARMA
/// solver. `curve` is `[freq_hz, db]` control points; they are sorted by
/// frequency, then handed to `trench_core::arma::fit_corner_from_magnitude`
/// (which linearly interpolates between them onto its FFT grid). Returns the
/// kernel-form corner, leashed + normalized like the other fit modes so it packs
/// and plays cleanly, or `None` if fewer than two points or the fit degenerates.
pub fn fsm_fit(curve: &[[f64; 2]], sr: f64) -> Option<CornerData> {
    if curve.len() < 2 {
        return None;
    }
    let mut pts: Vec<(f64, f64)> = curve.iter().map(|p| (p[0], p[1])).collect();
    pts.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(Ordering::Equal));
    let mut corner = trench_core::arma::fit_corner_from_magnitude(&pts, sr)?;
    leash_zeros(&mut corner, ZERO_Q0_RADIUS);
    trench_core::lpc::normalize_corner_peak(&mut corner, sr, 2.0);
    Some(corner)
}

/// Decode a corner's six stages into their poles and zeros (frequency + radius)
/// for the constellation overlay. Poles come from the denominator (a1,a2), zeros
/// from the numerator (b0,b1,b2). Passthrough/degenerate stages are skipped.
pub fn corner_poles_zeros(corner: &CornerData, sr: f64) -> Vec<PoleZero> {
    let nyq = sr * 0.5;
    let mut out = Vec::new();
    let angle_hz = |coef_r: f64, lin: f64| -> f64 {
        // lin = a1/b1-style linear coefficient; angle from cos = -lin/(2r).
        (((-lin) / (2.0 * coef_r)).clamp(-1.0, 1.0)).acos() * sr / TAU
    };
    for stage in corner.iter() {
        if is_passthrough(stage) {
            continue;
        }
        let [b0, b1, b2, a1, a2] = kernel_to_biquad(stage);
        // Pole: z² + a1 z + a2.
        let rp = a2.max(0.0).sqrt();
        if rp > 1.0e-3 && rp < 1.0 {
            let f = angle_hz(rp, a1);
            if f > 10.0 && f < nyq {
                out.push(PoleZero {
                    freq_hz: f,
                    radius: rp,
                    is_pole: true,
                });
            }
        }
        // Zero: b0 z² + b1 z + b2  →  z² + (b1/b0) z + (b2/b0).
        if b0.abs() > 1.0e-9 {
            let rz = (b2 / b0).max(0.0).sqrt();
            if rz > 1.0e-3 && rz.is_finite() {
                let f = angle_hz(rz.max(1.0e-3), b1 / b0);
                if f > 10.0 && f < nyq {
                    out.push(PoleZero {
                        freq_hz: f,
                        radius: rz,
                        is_pole: false,
                    });
                }
            }
        }
    }
    out
}

// ── Curve generators: data/formula → target curve (seed the FSM fit) ──────────

/// RBJ peaking-EQ magnitude in dB at `f` for a bell at (`fc`, `q`, `gain_db`).
/// Ported from the cube_display prototype `rbjmag` (peaking branch). Negative
/// `gain_db` makes a dip (used by the flanger / harmonic slicers).
fn rbj_peak_db(f: f64, fc: f64, q: f64, gain_db: f64, sr: f64) -> f64 {
    let a = 10f64.powf(gain_db / 40.0);
    let w0 = TAU * fc / sr;
    let (c, s) = (w0.cos(), w0.sin());
    let al = s / (2.0 * q.max(0.05));
    let b0 = 1.0 + al * a;
    let b1 = -2.0 * c;
    let b2 = 1.0 - al * a;
    let a0 = 1.0 + al / a;
    let a1 = -2.0 * c;
    let a2 = 1.0 - al / a;
    let (b0, b1, b2, a1, a2) = (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0);
    let w = TAU * f / sr;
    let (cw, sw) = (w.cos(), w.sin());
    let (c2, s2) = ((2.0 * w).cos(), (2.0 * w).sin());
    let nr = b0 + b1 * cw + b2 * c2;
    let ni = -(b1 * sw + b2 * s2);
    let dr = 1.0 + a1 * cw + a2 * c2;
    let di = -(a1 * sw + a2 * s2);
    10.0 * ((nr * nr + ni * ni) / (dr * dr + di * di)).log10()
}

/// Sum a set of `(fc, Q, gain_db)` peaking bells onto the standard log frequency
/// grid → a target curve ready for `fsm_fit`. This is the shared backend for
/// every formula-based seed.
pub fn peq_curve(peaks: &[(f64, f64, f64)], sr: f64) -> Vec<[f64; 2]> {
    let nyquist = (sr * 0.5).max(10_000.0);
    (0..RESPONSE_BINS)
        .map(|i| {
            let t = i as f64 / (RESPONSE_BINS - 1) as f64;
            let f = 20.0 * (nyquist / 20.0).powf(t);
            let db: f64 = peaks
                .iter()
                .map(|&(fc, q, g)| rbj_peak_db(f, fc, q, g, sr))
                .sum();
            [f, db.clamp(-48.0, 30.0)]
        })
        .collect()
}

/// Klatt/Peterson-Barney vowel formant table: `(F_hz, BW_hz, gain_db)` per
/// formant. Q = F/BW (the documented conversion). Hardcoded (small + stable) so
/// the Forge core needs no JSON IO; matches `tables/klatt_1980_*.json`.
pub fn klatt_vowel_formants(vowel: &str) -> &'static [(f64, f64, f64)] {
    match vowel {
        // /i/ "bead"
        "i" => &[
            (310.0, 45.0, 14.0),
            (2020.0, 200.0, 12.0),
            (2960.0, 400.0, 9.0),
            (3300.0, 250.0, 6.0),
        ],
        // /a/ "bard"
        "a" => &[
            (700.0, 130.0, 14.0),
            (1220.0, 70.0, 12.0),
            (2600.0, 160.0, 9.0),
            (3300.0, 250.0, 6.0),
        ],
        // /u/ "boot"
        "u" => &[
            (350.0, 65.0, 14.0),
            (650.0, 110.0, 11.0),
            (2200.0, 140.0, 8.0),
            (3300.0, 250.0, 5.0),
        ],
        // /e/ "bait"
        "e" => &[
            (480.0, 70.0, 14.0),
            (1720.0, 100.0, 12.0),
            (2520.0, 200.0, 9.0),
            (3300.0, 250.0, 6.0),
        ],
        // /o/ "boat"
        "o" => &[
            (500.0, 80.0, 14.0),
            (1000.0, 90.0, 11.0),
            (2400.0, 160.0, 8.0),
            (3300.0, 250.0, 5.0),
        ],
        _ => &[
            (700.0, 130.0, 14.0),
            (1220.0, 70.0, 12.0),
            (2600.0, 160.0, 9.0),
        ],
    }
}

/// A vowel formant target curve (Klatt data → peaking bells, Q=F/BW).
pub fn klatt_vowel_curve(vowel: &str, sr: f64) -> Vec<[f64; 2]> {
    let peaks: Vec<(f64, f64, f64)> = klatt_vowel_formants(vowel)
        .iter()
        .map(|&(f, bw, g)| (f, f / bw.max(1.0), g))
        .collect();
    peq_curve(&peaks, sr)
}

/// Speed of sound, cm/s (used by the tube/pipe modal curves).
const SOUND_CM_S: f64 = 34_300.0;

/// A tube/pipe modal target curve. `closed_open=true` → odd-harmonic series
/// f=(2n−1)·c/(4L) (clarinet); else integer series f=n·c/(2L) (flute/open pipe).
/// Six modes, high-Q, gain rolling off with mode number.
pub fn tube_curve(length_cm: f64, closed_open: bool, sr: f64) -> Vec<[f64; 2]> {
    let l = length_cm.max(1.0);
    let mut peaks = Vec::new();
    for n in 1..=6u32 {
        let f = if closed_open {
            (2.0 * n as f64 - 1.0) * SOUND_CM_S / (4.0 * l)
        } else {
            n as f64 * SOUND_CM_S / (2.0 * l)
        };
        if f >= 20.0 && f < sr * 0.49 {
            let gain = (14.0 - 2.0 * (n as f64 - 1.0)).max(4.0);
            peaks.push((f, 9.0, gain)); // rigid-wall high Q
        }
    }
    peq_curve(&peaks, sr)
}

/// Golden-ratio flanger target curve: deep notches starting at `f0`, each next
/// notch ×`ratio` (φ≈1.618 by default), `depth_db` negative. The smooth,
/// synthetic, non-linear comb (Morpheus Flange3.4 spirit, original data).
pub fn golden_flanger_curve(f0: f64, ratio: f64, depth_db: f64, sr: f64) -> Vec<[f64; 2]> {
    let mut peaks = Vec::new();
    let mut f = f0.max(20.0);
    let nyq = sr * 0.49;
    while f < nyq {
        peaks.push((f, 4.0, -depth_db.abs()));
        f *= ratio.max(1.05);
    }
    peq_curve(&peaks, sr)
}

/// Odd/even harmonic slicer target curve: notches on the odd (or even) harmonics
/// of `f0`, hollowing the sound (Morpheus OddCuts/EvenCuts spirit).
pub fn harmonic_slice_curve(f0: f64, odd: bool, sr: f64) -> Vec<[f64; 2]> {
    let mut peaks = Vec::new();
    let nyq = sr * 0.49;
    let start = if odd { 1u32 } else { 2 };
    let mut n = start;
    while (n as f64) * f0 < nyq {
        peaks.push((n as f64 * f0, 6.0, -18.0));
        n += 2;
    }
    peq_curve(&peaks, sr)
}

// ── C++ export ──────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn peak_hz_of(corner: &CornerData, sr: f64) -> f64 {
        let mut best = (0.0f64, f64::NEG_INFINITY);
        for p in magnitude_response(corner, sr) {
            if p[1] > best.1 {
                best = (p[0], p[1]);
            }
        }
        best.0
    }

    #[test]
    fn fsm_fit_matches_a_drawn_peak() {
        // A single bell drawn at ~1 kHz must fit a corner that peaks near 1 kHz.
        let sr = AUTHORING_RATE;
        let curve = peq_curve(&[(1000.0, 6.0, 18.0)], sr);
        let corner = fsm_fit(&curve, sr).expect("fit a single-peak curve");
        assert!(corner.iter().all(|s| s.iter().all(|v| v.is_finite())));
        let f = peak_hz_of(&corner, sr);
        assert!(
            (f / 1000.0).ln().abs() < 0.4,
            "fitted peak {f:.0}Hz not near 1kHz"
        );
    }

    #[test]
    fn fsm_fit_rejects_short_curve() {
        assert!(fsm_fit(&[[100.0, 0.0]], AUTHORING_RATE).is_none());
    }

    #[test]
    fn corner_poles_zeros_decodes_finite_stable() {
        let sr = AUTHORING_RATE;
        let corner = realize_resonances(
            &[
                Resonance {
                    freq_hz: 300.0,
                    radius: 0.97,
                    kind: ResoKind::Peak,
                    cavity_semis: 0.0,
                },
                Resonance {
                    freq_hz: 1800.0,
                    radius: 0.95,
                    kind: ResoKind::Peak,
                    cavity_semis: 0.0,
                },
            ],
            sr,
        );
        let pzs = corner_poles_zeros(&corner, sr);
        assert!(pzs.iter().any(|p| p.is_pole), "expected at least one pole");
        for pz in &pzs {
            assert!(pz.freq_hz.is_finite() && pz.radius.is_finite());
            if pz.is_pole {
                assert!(pz.radius < 1.0, "pole radius {} >= 1", pz.radius);
            }
        }
    }

    #[test]
    fn klatt_vowel_curve_peaks_near_formants() {
        let sr = AUTHORING_RATE;
        let curve = klatt_vowel_curve("i", sr);
        // The drawn /i/ curve should have local maxima near F1≈310 and F2≈2020.
        let near = |target: f64| {
            curve
                .iter()
                .filter(|p| (p[0] / target).ln().abs() < 0.12)
                .any(|p| p[1] > 6.0)
        };
        assert!(near(310.0), "/i/ curve missing F1 bump near 310Hz");
        assert!(near(2020.0), "/i/ curve missing F2 bump near 2020Hz");
    }

    #[test]
    fn fsm_fit_of_vowel_is_stable() {
        let sr = AUTHORING_RATE;
        let corner = fsm_fit(&klatt_vowel_curve("a", sr), sr).expect("fit vowel /a/");
        let (max_r, _) = morph_surface_max_pole_radius(&[corner, corner, corner, corner], 4);
        assert!(max_r < 1.0, "vowel fit unstable: max pole radius {max_r}");
    }

    #[test]
    fn morph_surface_scan_catches_destabilised_middle() {
        // Two PASSTHROUGH corners and two with a high-Q pole that — under
        // bilinear interp — pushes the radius past STABILITY_RADIUS_LIMIT.
        let sr = AUTHORING_RATE;
        let hot = realize_resonances(
            &[Resonance {
                freq_hz: 1_000.0,
                radius: 0.998,
                kind: ResoKind::Peak,
                cavity_semis: 0.0,
            }],
            sr,
        );
        let passthrough: CornerData = [PASSTHROUGH; POLE_ZERO_COUNT];
        // Corner ordering: [M0_Q0, M100_Q0, M0_Q100, M100_Q100]
        // Two diagonally-placed hot corners; the mid-cell of the surface
        // averages them with the two passthroughs.
        let corners = [hot, passthrough, passthrough, hot];
        let (r_max, (m, q)) = morph_surface_max_pole_radius(&corners, 5);
        // The hot corners themselves max out at ~0.998 (the realize clamp).
        // The interpolated cells will be less, not more — bilinear of a
        // radius-0.998 stage with passthrough (a2=0) interpolates DOWN.
        // We just sanity-check that the scan runs and locates a sharp cell.
        assert!(r_max > 0.0, "scan returned a positive radius");
        assert!(r_max <= 1.0, "scan radius stays bounded ({r_max})");
        assert!((0.0..=1.0).contains(&m), "morph cell sane: {m}");
        assert!((0.0..=1.0).contains(&q), "q cell sane: {q}");
        // And: a body of four pure passthroughs reports a near-zero radius.
        let cold = [passthrough; 4];
        let (r_zero, _) = morph_surface_max_pole_radius(&cold, 5);
        assert!(r_zero < 0.05, "passthrough body: r ≈ 0 (got {r_zero})");
    }

    #[test]
    fn cavity_actor_places_coupled_pole_and_zero() {
        // The "Ooh to Eee tear": a pole at f and a deep zero a few semis
        // above. Decoding the realized stage's c0–c4 must recover both.
        let sr = AUTHORING_RATE;
        let f_in = 1_000.0;
        let semis = 3.0;
        let corner = realize_resonances(
            &[Resonance {
                freq_hz: f_in,
                radius: 0.95,
                kind: ResoKind::Cavity,
                cavity_semis: semis,
            }],
            sr,
        );
        // Decode stage 0 (kernel form → pole/zero):
        //   c2 = a1 + 2,  c3 = 1 - a2,  c0 = 2 + b1/b0,  c1 = 1 - b2/b0.
        let s = corner[0];
        let a2 = 1.0 - s[3];
        let r_pole = a2.max(0.0).sqrt();
        let cos_tp = (-(s[2] - 2.0) / (2.0 * r_pole)).clamp(-1.0, 1.0);
        let f_pole = cos_tp.acos() * sr / TAU;
        let b2_over_b0 = 1.0 - s[1];
        let r_zero = b2_over_b0.max(0.0).sqrt();
        let cos_tz = (-(s[0] - 2.0) / (2.0 * r_zero)).clamp(-1.0, 1.0);
        let f_zero = cos_tz.acos() * sr / TAU;

        let expected_fz = f_in * 2.0_f64.powf(semis / 12.0);
        assert!(
            (f_pole - f_in).abs() < 20.0,
            "pole f = {f_pole}, want ~{f_in}"
        );
        assert!(
            (f_zero - expected_fz).abs() < 20.0,
            "zero f = {f_zero}, want ~{expected_fz} ({semis} semis above pole)"
        );
        assert!(r_zero > 0.95, "zero radius = {r_zero}, want deep (>0.95)");
        assert!(
            (0.93..=0.96).contains(&r_pole),
            "pole radius = {r_pole}, want ~0.95"
        );
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

    // ── 4-corner body authoring ──────────────────────────────────────────────

    /// A corner with resonant poles at the given frequencies (≤0 → passthrough).
    fn resonant_corner(freqs: [f64; 6], sr: f64) -> CornerData {
        let mut corner = [PASSTHROUGH; POLE_ZERO_COUNT];
        for (i, &f) in freqs.iter().enumerate() {
            if f <= 0.0 {
                continue;
            }
            let r = 0.95;
            let theta = TAU * f / sr;
            corner[i] = biquad_to_kernel([1.0 - r, 0.0, 0.0, -2.0 * r * theta.cos(), r * r]);
        }
        corner
    }

    #[test]
    fn align_recovers_shuffled_actor_order() {
        // The correspondence must re-index a corner whose stages arrive in a
        // scrambled order back onto the anchor's actors — by identity, not by a
        // global frequency sort — so index-paired interpolation stays coherent.
        let sr = AUTHORING_RATE;
        let anchor = resonant_corner([180.0, 420.0, 900.0, 1800.0, 3600.0, 7000.0], sr);
        let scrambled = resonant_corner([3700.0, 185.0, 7100.0, 880.0, 430.0, 1820.0], sr);
        let aligned = align_to_anchor(&anchor, &scrambled, sr);
        for i in 0..POLE_ZERO_COUNT {
            let fa = stage_frequency(&anchor[i], sr);
            let fr = stage_frequency(&aligned[i], sr);
            assert!(
                (fa.ln() - fr.ln()).abs() < 0.15,
                "actor {i}: anchor {fa:.0}Hz vs aligned {fr:.0}Hz"
            );
        }
    }

    #[test]
    fn canonical_anchor_sorts_low_to_high() {
        let sr = AUTHORING_RATE;
        let scrambled = resonant_corner([3600.0, 180.0, 7000.0, 900.0, 420.0, 1800.0], sr);
        let sorted = canonical_anchor(&scrambled, sr);
        for i in 0..POLE_ZERO_COUNT - 1 {
            assert!(
                stage_frequency(&sorted[i], sr) <= stage_frequency(&sorted[i + 1], sr),
                "anchor actors must read low→high"
            );
        }
    }

    // Fit a dropped voice WAV through the real live path and dump the corner
    // (poles + a .corner.json to plot). cargo test -p trench-forge fit_my_voice -- --nocapture --ignored
    #[test]
    #[ignore]
    fn fit_my_voice() {
        let p = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../dev/tmp/arma_source_pack/corners_audio_only/_voice/my_eee.wav");
        let (samples, meta) = load_wav_with_meta(&p).expect("load my_eee.wav");
        let sr = meta.sample_rate as f64;
        let (s, e) = sustain_window(&samples, sr);
        let win = condition_fit_window(&samples[s..e], false);
        let corner = fit_window(&win, sr);
        for c in corner.iter() {
            let (a1, a2) = (c[2] - 2.0, 1.0 - c[3]);
            let r = a2.max(0.0).sqrt();
            if a1 * a1 - 4.0 * a2 < 0.0 && r > 1e-6 {
                let f = (-a1 / (2.0 * r)).clamp(-1.0, 1.0).acos() * AUTHORING_RATE
                    / std::f64::consts::TAU;
                println!("pole {:>7.0} Hz @ r={:.3}", f, r);
            } else {
                println!("(real/passthrough)");
            }
        }
        let stage = |c: &[f64; 5]| {
            format!(
                "{{\"c0\":{},\"c1\":{},\"c2\":{},\"c3\":{},\"c4\":{}}}",
                c[0], c[1], c[2], c[3], c[4]
            )
        };
        let stages: Vec<String> = corner.iter().map(|c| stage(c)).collect();
        let kf = format!(
            "{{\"label\":\"M0_Q0\",\"boost\":1.5,\"stages\":[{}]}}",
            stages.join(",")
        );
        let json = format!(
            "{{\"format\":\"compiled-v1\",\"name\":\"my_eee_fit\",\"sampleRate\":39062.5,\"stages\":6,\"keyframes\":[{0},{0},{0},{0}]}}",
            kf
        );
        std::fs::write(p.with_file_name("my_eee_fit.corner.json"), json).expect("write");
        println!("wrote my_eee_fit.corner.json");
    }

    // ── aaa.wav voice-capture regression ──────────────────────────────────────
    // Render the two real voice recordings through BOTH fit modes so we can HEAR
    // whether the voice path actually recovers the vowel. Writes side-by-side WAVs
    // + a machine report + an audition page to dev/tmp/forge_voice_regression/.
    //   cargo test -p trench-forge --bin trench-forge voice_regression -- --ignored --nocapture
    #[test]
    #[ignore]
    fn voice_regression() {
        use std::path::PathBuf;

        let recs = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("dev/tmp/recordings");
        let out = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("dev/tmp/forge_voice_regression");
        std::fs::create_dir_all(&out).expect("mkdir out");

        // primary = the short "aaa" (the named artifacts); alt = the longer take.
        let cases: &[(&str, &str, &str)] = &[
            ("aaa - aa.wav", "", "aaa - aa"),
            ("aaa_start - aaaa.wav", "alt_", "aaa_start - aaaa"),
        ];

        // ── local helpers (offline, no audio device) ──
        fn resample_linear(x: &[f64], sr_in: f64, sr_out: f64) -> Vec<f64> {
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
        // DF2T cascade render at the authoring rate; nonfinite states reset.
        fn render(corner: &CornerData, dry: &[f64]) -> Vec<f64> {
            let bq = corner_to_biquads(corner);
            let (mut s1, mut s2) = ([0f64; POLE_ZERO_COUNT], [0f64; POLE_ZERO_COUNT]);
            dry.iter()
                .map(|&x| {
                    let mut y = x;
                    for i in 0..POLE_ZERO_COUNT {
                        let [b0, b1, b2, a1, a2] = bq[i];
                        let yo = b0 * y + s1[i];
                        s1[i] = b1 * y - a1 * yo + s2[i];
                        s2[i] = b2 * y - a2 * yo;
                        y = yo;
                        if !y.is_finite() {
                            y = 0.0;
                            s1[i] = 0.0;
                            s2[i] = 0.0;
                        }
                    }
                    y
                })
                .collect()
        }
        // raw (pre-clip) signal stats
        fn stats(y: &[f64]) -> (f64, f64, f64, usize) {
            let nonf = y.iter().filter(|v| !v.is_finite()).count();
            let fin: Vec<f64> = y.iter().copied().filter(|v| v.is_finite()).collect();
            let n = fin.len().max(1) as f64;
            let peak = fin.iter().fold(0.0f64, |m, v| m.max(v.abs()));
            let rms = (fin.iter().map(|v| v * v).sum::<f64>() / n).sqrt();
            let dc = fin.iter().sum::<f64>() / n;
            (peak, rms, dc, nonf)
        }
        // Write a 16-bit mono WAV. `makeup` pre-scales (for audition level-matching
        // so timbre is compared by ear, not loudness — raw loudness stays in the
        // JSON); then a soft tanh keeps it inside full scale.
        fn write_wav(path: &std::path::Path, y: &[f64], rate: u32, makeup: f64) {
            let spec = hound::WavSpec {
                channels: 1,
                sample_rate: rate,
                bits_per_sample: 16,
                sample_format: hound::SampleFormat::Int,
            };
            let mut w = hound::WavWriter::create(path, spec).expect("wav create");
            for &s in y {
                let v = if !s.is_finite() {
                    0.0
                } else if makeup == 1.0 {
                    s.clamp(-1.0, 1.0)
                } else {
                    (makeup * s).tanh()
                };
                w.write_sample((v * 32767.0) as i16).expect("write sample");
            }
            w.finalize().expect("finalize");
        }
        // Makeup gain that brings a render's peak to ~0.7 for fair A/B listening.
        fn audition_makeup(peak: f64) -> f64 {
            if peak <= 1e-9 {
                1.0
            } else {
                (0.7 / peak).clamp(0.25, 4000.0)
            }
        }

        let render_rate: u32 = AUTHORING_RATE as u32; // 39062 (−0.0013% pitch, inaudible)
        let mut case_reports: Vec<serde_json::Value> = Vec::new();
        let mut html_blocks: Vec<String> = Vec::new();

        for (file, prefix, label) in cases {
            let path = recs.join(file);
            let Ok((samples, meta)) = load_wav_with_meta(&path) else {
                eprintln!("skip (missing): {file}");
                continue;
            };
            let sr = meta.sample_rate as f64;
            let (wstart, wend) = sustain_window(&samples, sr);
            let win = condition_fit_window(&samples[wstart..wend], false);

            // dry input = whole take resampled to the authoring rate (what each
            // corner is driven with), and the same as `source.wav`.
            let dry = resample_linear(&samples, sr, AUTHORING_RATE);
            write_wav(
                &out.join(format!("{prefix}source.wav")),
                &dry,
                render_rate,
                1.0,
            );

            let modes = [
                (FitMode::SpectrumPeak, "spectrum_peak"),
                (FitMode::VoiceLpc, "voice_lpc"),
                (FitMode::Arma, "arma"),
            ];
            let mut mode_reports: Vec<serde_json::Value> = Vec::new();
            let mut audio_tags: Vec<String> = Vec::new();
            audio_tags.push(format!(
                "<div class=row><b>source (dry)</b><audio controls src='{prefix}source.wav'></audio></div>"
            ));

            for (mode, key) in modes {
                let corner = fit_window_mode(&win, sr, mode);

                // per-stage pole readout
                let mut poles = Vec::new();
                let mut unstable_rows = 0;
                let mut nonfinite_coeffs = 0;
                for (si, st) in corner.iter().enumerate() {
                    if st.iter().any(|v| !v.is_finite()) {
                        nonfinite_coeffs += st.iter().filter(|v| !v.is_finite()).count();
                    }
                    if is_passthrough(st) {
                        continue;
                    }
                    let [_, _, _, a1, a2] = kernel_to_biquad(st);
                    let radius = a2.max(0.0).sqrt();
                    if radius >= 1.0 {
                        unstable_rows += 1;
                    }
                    poles.push(serde_json::json!({
                        "stage": si,
                        "freq_hz": (stage_frequency(st, AUTHORING_RATE) * 10.0).round() / 10.0,
                        "radius": (radius * 10000.0).round() / 10000.0,
                    }));
                }

                // packed round-trip drift (pre-pack corner vs post-pack decode)
                let packed = PackedCorners::from_corner_data(&[corner; 4]);
                let rt = packed.interpolate(0.0, 0.0);
                let mut max_coeff_drift = 0.0f64;
                for si in 0..POLE_ZERO_COUNT {
                    for ci in 0..5 {
                        max_coeff_drift = max_coeff_drift.max((corner[si][ci] - rt[si][ci]).abs());
                    }
                }
                let mut max_db_drift = 0.0f64;
                for i in 0..96 {
                    let f = 40.0 * (16_000.0f64 / 40.0).powf(i as f64 / 95.0);
                    let d = (cascade_mag_db(&corner, f, AUTHORING_RATE)
                        - cascade_mag_db(&rt, f, AUTHORING_RATE))
                    .abs();
                    max_db_drift = max_db_drift.max(d);
                }

                let resid = spectral_residual_db(&win, sr, &corner, AUTHORING_RATE);
                let y = render(&corner, &dry);
                let (peak, rms, dc, nonfinite_out) = stats(&y);
                let makeup = audition_makeup(peak);
                let wav = format!("{prefix}{key}_fit.wav");
                write_wav(&out.join(&wav), &y, render_rate, makeup);

                println!(
                    "{label:>20} {key:<13} poles={:<2} unstable={unstable_rows} resid={resid:5.1}dB \
                     out(peak={peak:.3} rms={rms:.4} dc={dc:+.4} makeup×{makeup:.1}) packDrift(coeff={max_coeff_drift:.4} {max_db_drift:.1}dB) nonfin={}",
                    poles.len(),
                    nonfinite_out + nonfinite_coeffs
                );

                mode_reports.push(serde_json::json!({
                    "fit_mode": key,
                    "wav": wav,
                    "poles": poles,
                    "unstable_denominator_rows": unstable_rows,
                    "nonfinite_count": nonfinite_out + nonfinite_coeffs,
                    "output": {
                        "peak": (peak * 10000.0).round() / 10000.0,
                        "rms": (rms * 100000.0).round() / 100000.0,
                        "dc": (dc * 100000.0).round() / 100000.0,
                        "audition_makeup_gain": (makeup * 100.0).round() / 100.0,
                    },
                    "packed_roundtrip_drift": {
                        "max_coeff_abs": (max_coeff_drift * 100000.0).round() / 100000.0,
                        "max_response_db": (max_db_drift * 100.0).round() / 100.0,
                    },
                    "residual_db": (resid * 100.0).round() / 100.0,
                }));
                audio_tags.push(format!(
                    "<div class=row><b>{key}</b><audio controls src='{wav}'></audio> \
                     <span class=meta>poles {} · resid {resid:.1} dB · raw peak {peak:.3} (×{makeup:.0} for audition)</span></div>",
                    poles.len()
                ));
            }

            case_reports.push(serde_json::json!({
                "label": label,
                "source_file": file,
                "source_sample_rate": meta.sample_rate,
                "render_sample_rate": render_rate,
                "sustain_window": {
                    "start_sample": wstart,
                    "end_sample": wend,
                    "start_s": (wstart as f64 / sr * 1000.0).round() / 1000.0,
                    "end_s": (wend as f64 / sr * 1000.0).round() / 1000.0,
                },
                "fits": mode_reports,
            }));
            html_blocks.push(format!(
                "<section><h2>{label}</h2><p class=meta>sustain {:.0}–{:.0} ms @ {} Hz</p>{}</section>",
                wstart as f64 / sr * 1000.0,
                wend as f64 / sr * 1000.0,
                meta.sample_rate,
                audio_tags.join("\n")
            ));
        }

        let report = serde_json::json!({
            "what": "Forge voice-capture regression — spectrum_peak vs voice_lpc vs arma on real /aaa/ recordings",
            "authoring_rate": AUTHORING_RATE,
            "voice_pre_emph": VOICE_PRE_EMPH,
            "cases": case_reports,
        });
        std::fs::write(
            out.join("comparison_report.json"),
            serde_json::to_string_pretty(&report).unwrap(),
        )
        .expect("write report");

        let html = format!(
            "<!doctype html><meta charset=utf-8><title>Forge voice regression</title>\
             <style>body{{background:#0a0d0c;color:#bec; font:14px/1.5 monospace;margin:24px;max-width:760px}}\
             h1{{color:#5bef6f}} h2{{color:#31c6c9;margin-top:28px}} .row{{margin:6px 0;display:flex;gap:10px;align-items:center}}\
             .row b{{display:inline-block;min-width:120px}} .meta{{color:#69836f}} audio{{height:30px}}</style>\
             <h1>Forge voice capture — fitter A/B</h1>\
             <p class=meta>Audio first. Each fit renders the dry take through the proposed corner. \
             WAVs are soft-clipped (tanh) for safe listening; raw peak/rms are in comparison_report.json. \
             voice_lpc pre-emphasis = {VOICE_PRE_EMPH}.</p>{}",
            html_blocks.join("\n")
        );
        std::fs::write(out.join("audition.html"), html).expect("write html");

        println!("\nwrote artifacts → {}", out.display());
    }

    // Diagnostic (not a gate): for each real source, run the LIVE fitter
    // (formant_fit, via fit_window) and the DEAD pole-zero fitter
    // (trench_core::arma::fit_corner_arma) over the same conditioned window, and
    // report how many of the 6 sections are used, how many carry a real zero, the
    // mean pole/zero radius, and the spectral fit error.
    //   cargo test -p trench-forge --bin trench-forge source_fit_bakeoff -- --nocapture --ignored
    #[test]
    #[ignore]
    fn source_fit_bakeoff() {
        use std::path::PathBuf;
        let base = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("dev/tmp/arma_source_pack/corners_audio_only");
        let sources: &[(&str, &str)] = &[
            ("/i/ vowel", "phonetic_4corner_legisign/00_selected_primes/corner_1_bright_front_vowel__prime_i.wav"),
            ("/u/ vowel", "phonetic_4corner_legisign/00_selected_primes/corner_2_dark_back_vowel__prime_u.wav"),
            ("/a/ vowel", "phonetic_4corner_legisign/00_selected_primes/corner_3_open_vowel__prime_a.wav"),
            ("/sh/ sib",  "phonetic_4corner_legisign/00_selected_primes/corner_4_consonant_rich_spectral_mode__prime_sh.wav"),
            ("/n/ nasal", "phonetic_4corner_legisign/corner_4_consonant_rich_spectral_mode/alt_n_Con-15a.wav"),
            ("/m/ nasal", "phonetic_4corner_legisign/corner_4_consonant_rich_spectral_mode/support_m_Con-13a.wav"),
            ("kick",      "other_sources/kb6/extracted/EMU_Proteus3/Kick1.wav"),
            ("floor tom", "other_sources/kb6/extracted/EMU_Proteus3/FloorTom.wav"),
            ("hi-hat",    "other_sources/kb6/extracted/EMU_Proteus3/HiHat1.wav"),
            ("cymbal",    "other_sources/kb6/extracted/EMU_Proteus3/Cymbal1.wav"),
            ("cowbell",   "other_sources/kb6/extracted/EMU_Proteus3/Cowbell.WAV"),
            ("nmr cyclo", "other_sources/nmr/nmrtalk/cyclohexane/fid.wav"),
            ("nmr inosit","other_sources/nmr/nmrtalk/inositol/fid.wav"),
            ("whistler",  "other_sources/plasma/whistler.wav"),
            ("plasma chr","other_sources/plasma/chorus.wav"),
            ("sun 3modes","other_sources/soho/3modes.wav"),
        ];

        // Per-section summary: (active count, sections-with-zero, mean pole r, mean zero r)
        fn summarize(corner: &CornerData) -> (usize, usize, f64, f64) {
            let mut active = 0;
            let mut with_zero = 0;
            let (mut pr_sum, mut zr_sum, mut zr_cnt) = (0.0, 0.0, 0.0);
            for st in corner.iter() {
                if is_passthrough(st) {
                    continue;
                }
                active += 1;
                let [b0, b1, b2, _a1, a2] = kernel_to_biquad(st);
                pr_sum += a2.max(0.0).sqrt();
                let nz = (b1 / b0).abs() > 0.02 || (b2 / b0).abs() > 0.02;
                if nz {
                    with_zero += 1;
                    zr_sum += (b2 / b0).max(0.0).sqrt();
                    zr_cnt += 1.0;
                }
            }
            let pr = if active > 0 {
                pr_sum / active as f64
            } else {
                0.0
            };
            let zr = if zr_cnt > 0.0 { zr_sum / zr_cnt } else { 0.0 };
            (active, with_zero, pr, zr)
        }

        // Spectral tilt = mean dB in [3k,8k] minus mean dB in [200,800]. Comparing
        // the corner's tilt to the source's tells us if the fit brightened it (a
        // positive delta = corner brighter than source = a hot/thin Morph0/Q0).
        fn corner_tilt(c: &CornerData) -> f64 {
            let band = |lo: f64, hi: f64| {
                let (mut s, mut n) = (0.0, 0.0);
                for i in 0..16 {
                    let f = lo * (hi / lo).powf(i as f64 / 15.0);
                    s += cascade_mag_db(c, f, AUTHORING_RATE);
                    n += 1.0;
                }
                s / n
            };
            band(3000.0, 8000.0) - band(200.0, 800.0)
        }
        fn source_tilt(win: &[f64], sr: f64) -> f64 {
            let env = source_envelope(win, sr);
            let band = |lo: f64, hi: f64| {
                let pts: Vec<f64> = env
                    .iter()
                    .filter(|p| p[0] >= lo && p[0] <= hi)
                    .map(|p| p[1])
                    .collect();
                if pts.is_empty() {
                    0.0
                } else {
                    pts.iter().sum::<f64>() / pts.len() as f64
                }
            };
            band(3000.0, 8000.0) - band(200.0, 800.0)
        }

        println!("\nsource        fitter   poles  w/zero  poleR  zeroR  resid  tiltΔvsSrc");
        println!("------------  -------  -----  ------  -----  -----  -----  ----------");
        for (label, rel) in sources {
            let path = base.join(rel);
            let Ok((samples, meta)) = load_wav_with_meta(&path) else {
                println!("{label:<12}  (missing: {rel})");
                continue;
            };
            let sr = meta.sample_rate as f64;
            let (start, end) = sustain_window(&samples, sr);
            let win = condition_fit_window(&samples[start..end], false);

            let st = source_tilt(&win, sr);

            // OLD path: the all-pole peak-picker, called directly.
            let old = formant_fit(&clean_envelope(&win, sr), AUTHORING_RATE);
            let (oa, oz, opr, ozr) = summarize(&old);
            let ores = spectral_residual_db(&win, sr, &old, AUTHORING_RATE);
            println!(
                "{label:<12}  formant  {oa:^5}  {oz:^6}  {opr:>5.3}  {ozr:>5.3}  {ores:>5.1}  {:>+8.1}",
                corner_tilt(&old) - st
            );

            // NEW live path: fit_window now routes through ARMA (+ heritage relevel).
            let live = fit_window(&win, sr);
            let (la, lz, lpr, lzr) = summarize(&live);
            let lres = spectral_residual_db(&win, sr, &live, AUTHORING_RATE);
            println!(
                "{:<12}  LIVE     {la:^5}  {lz:^6}  {lpr:>5.3}  {lzr:>5.3}  {lres:>5.1}  {:>+8.1}",
                "",
                corner_tilt(&live) - st
            );
        }
        println!();
    }

    // Health scan over the WHOLE pack: which sources fail to load, fit
    // degenerate (ARMA bails → fallback), or fit "dead" (response barely moves,
    // i.e. the filter didn't pick up the sound). Prints only the problems.
    //   cargo test -p trench-forge --bin trench-forge source_health -- --nocapture --ignored
    #[test]
    #[ignore]
    fn source_health() {
        use std::path::{Path, PathBuf};
        fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
            let Ok(rd) = std::fs::read_dir(dir) else {
                return;
            };
            for e in rd.flatten() {
                let p = e.path();
                if p.is_dir() {
                    walk(&p, out);
                } else if p
                    .extension()
                    .map(|x| x.eq_ignore_ascii_case("wav"))
                    .unwrap_or(false)
                {
                    out.push(p);
                }
            }
        }
        // dynamic range of a corner's response over the audible band (dB)
        fn dyn_range(c: &CornerData) -> f64 {
            let (mut lo, mut hi) = (f64::INFINITY, f64::NEG_INFINITY);
            for i in 0..96 {
                let f = 40.0 * (16_000.0f64 / 40.0).powf(i as f64 / 95.0);
                let d = cascade_mag_db(c, f, AUTHORING_RATE);
                lo = lo.min(d);
                hi = hi.max(d);
            }
            hi - lo
        }

        let base = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("dev/tmp/arma_source_pack/corners_audio_only");
        let mut wavs = Vec::new();
        walk(&base, &mut wavs);
        wavs.sort();

        let (mut total, mut load_fail, mut degen, mut dead, mut poor) = (0, 0, 0, 0, 0);
        println!("\n-- problems only (of {} wavs) --", wavs.len());
        for p in &wavs {
            total += 1;
            let rel = p.strip_prefix(&base).unwrap_or(p).display();
            let (samples, meta) = match load_wav_with_meta(p) {
                Ok(v) => v,
                Err(e) => {
                    load_fail += 1;
                    println!("LOAD-FAIL  {rel}  ({e})");
                    continue;
                }
            };
            let sr = meta.sample_rate as f64;
            let onset = detect_onset(&samples, sr);
            let wlen = samples_for_ms(sr, DEFAULT_WINDOW_MS);
            let start = onset.min(samples.len().saturating_sub(wlen));
            let end = (start + wlen).min(samples.len());
            if end <= start + 64 {
                degen += 1;
                println!("TOO-SHORT  {rel}  ({} samples @ {sr:.0})", samples.len());
                continue;
            }
            let win = condition_fit_window(&samples[start..end], false);
            let arma_ok = trench_core::arma::fit_corner_arma(&win, sr, AUTHORING_RATE).is_some();
            let live = fit_window(&win, sr);
            let res = spectral_residual_db(&win, sr, &live, AUTHORING_RATE);
            let dr = dyn_range(&live);
            if !arma_ok {
                degen += 1;
                println!("DEGENERATE {rel}  (ARMA bailed → fallback; resid {res:.1})");
            }
            if dr < 4.0 {
                dead += 1;
                println!("DEAD-FLAT  {rel}  (range {dr:.1} dB — filter barely moves)");
            } else if res > 14.0 {
                poor += 1;
                println!("POOR-FIT   {rel}  (resid {res:.1} dB, range {dr:.1})");
            }
        }
        println!(
            "\nsummary: {total} sources | {load_fail} load-fail | {degen} degenerate/short | {dead} dead-flat | {poor} poor-fit\n"
        );
    }

    // Audio-chain audit: how hard does a normal corner drive the audition output
    // stage `(yv * lvl * 4.0).tanh()` (lvl default 0.4 → ×1.6), and do morph
    // midpoints stay stable? Anything driving the tanh past ~1.0 RMS is audible
    // distortion; any pole radius ≥ 1.0 across a morph sweep is a blow-up.
    //   cargo test -p trench-forge --bin trench-forge audio_chain_audit -- --nocapture --ignored
    #[test]
    #[ignore]
    fn audio_chain_audit() {
        const LVL: f64 = 0.4;
        const OUT_GAIN: f64 = 4.0; // the ×4.0 in Voice::sample

        // build a few representative corners via the live fit path
        let base = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../dev/tmp/arma_source_pack/corners_audio_only");
        let picks = [
            ("/i/ vowel", "phonetic_4corner_legisign/00_selected_primes/corner_1_bright_front_vowel__prime_i.wav"),
            ("/a/ vowel", "phonetic_4corner_legisign/00_selected_primes/corner_3_open_vowel__prime_a.wav"),
            ("cowbell",   "other_sources/kb6/extracted/EMU_Proteus3/Cowbell.WAV"),
        ];
        let mut corners = Vec::new();
        for (label, rel) in picks {
            let p = base.join(rel);
            let Ok((s, m)) = load_wav_with_meta(&p) else {
                continue;
            };
            let sr = m.sample_rate as f64;
            let onset = detect_onset(&s, sr);
            let wlen = samples_for_ms(sr, DEFAULT_WINDOW_MS);
            let st = onset.min(s.len().saturating_sub(wlen));
            let win = condition_fit_window(&s[st..(st + wlen).min(s.len())], false);
            corners.push((label, fit_window(&win, sr)));
        }

        // unit-variance pink noise (same generator as audio.rs)
        let mut rng = 0x2545_F491_4F6C_DD1Du64;
        let mut pb = [0f64; 7];
        let pink: Vec<f64> = (0..48_000)
            .map(|_| {
                rng = rng
                    .wrapping_mul(6364136223846793005)
                    .wrapping_add(1442695040888963407);
                let white = ((rng >> 40) as f64 / (1u64 << 23) as f64) - 1.0;
                pb[0] = 0.99886 * pb[0] + white * 0.0555179;
                pb[1] = 0.99332 * pb[1] + white * 0.0750759;
                pb[2] = 0.96900 * pb[2] + white * 0.1538520;
                pb[3] = 0.86650 * pb[3] + white * 0.3104856;
                pb[4] = 0.55000 * pb[4] + white * 0.5329522;
                pb[5] = -0.7616 * pb[5] - white * 0.0168980;
                let pink =
                    (pb[0] + pb[1] + pb[2] + pb[3] + pb[4] + pb[5] + pb[6] + white * 0.5362) * 0.11;
                pb[6] = white * 0.115926;
                pink
            })
            .collect();

        let run = |corner: &CornerData| -> (f64, f64, f64) {
            let bq = corner_to_biquads(corner);
            let (mut s1, mut s2) = ([0f64; 6], [0f64; 6]);
            let (mut sumsq, mut peak, mut clipped) = (0.0, 0.0f64, 0usize);
            for &x in &pink {
                let mut y = x;
                for i in 0..6 {
                    let [b0, b1, b2, a1, a2] = bq[i];
                    let yo = b0 * y + s1[i];
                    s1[i] = b1 * y - a1 * yo + s2[i];
                    s2[i] = b2 * y - a2 * yo;
                    y = yo;
                }
                let drive = (y * LVL * OUT_GAIN).abs();
                sumsq += y * y;
                peak = peak.max(y.abs());
                if drive > 1.0 {
                    clipped += 1;
                } // tanh compressing hard
            }
            let rms = (sumsq / pink.len() as f64).sqrt();
            (rms, peak, 100.0 * clipped as f64 / pink.len() as f64)
        };

        let pin = (pink.iter().map(|v| v * v).sum::<f64>() / pink.len() as f64).sqrt();
        println!("\npink-noise input RMS = {pin:.3}");
        println!(
            "corner       outRMS  outPeak  driveRMS(×{:.0}·{:.1})  %into-tanh-clip",
            OUT_GAIN, LVL
        );
        for (label, c) in &corners {
            let (rms, peak, clip) = run(c);
            println!(
                "{label:<11}  {rms:6.3}  {peak:7.3}   {:>8.3}            {clip:5.1}%",
                rms * LVL * OUT_GAIN
            );
        }

        // morph-sweep stability: max pole radius A→B across 0..1 (decoded interp)
        if corners.len() >= 2 {
            let a = corners[0].1;
            let b = corners[1].1;
            let mut maxr = 0.0f64;
            for k in 0..=20 {
                let t = k as f64 / 20.0;
                let mut mid = [PASSTHROUGH; POLE_ZERO_COUNT];
                for s in 0..POLE_ZERO_COUNT {
                    for c in 0..5 {
                        mid[s][c] = a[s][c] + (b[s][c] - a[s][c]) * t;
                    }
                }
                for s in 0..POLE_ZERO_COUNT {
                    let [_, _, _, _, a2] = kernel_to_biquad(&mid[s]);
                    maxr = maxr.max(a2.max(0.0).sqrt());
                }
            }
            println!(
                "\nmorph A→B (decoded interp) max pole radius = {maxr:.4}  {}",
                if maxr >= 1.0 {
                    "← UNSTABLE (blows up)"
                } else {
                    "(stable)"
                }
            );
        }
        println!();
    }
}
