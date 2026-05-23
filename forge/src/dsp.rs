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

pub fn hf_fraction(window: &[f64], sample_rate: f64) -> f64 {
    if window.len() < 8 {
        return 0.5;
    }
    let fc = 2_500.0_f64.min(sample_rate * 0.45);
    let dt = 1.0 / sample_rate;
    let rc = 1.0 / (TAU * fc);
    let alpha = rc / (rc + dt);
    let mut hp_prev = 0.0;
    let mut x_prev = window[0];
    let mut hi = 0.0f64;
    let mut tot = 1.0e-30f64;
    for &x in &window[1..] {
        let hp = alpha * (hp_prev + x - x_prev);
        hp_prev = hp;
        x_prev = x;
        hi += hp * hp;
        tot += x * x;
    }
    (hi / tot).sqrt()
}

/// Choose the fit's brightness tilt (pre-emphasis, in [0, 0.97]) from the
/// source's high-frequency fraction. Dark sources (a vowel's body in the
/// low-mids) get little tilt so their low formant (F1) survives instead of being
/// traded for a spurious air-band pole; bright material gets the full speech tilt
/// so the six actors spread across the band. The Forge sets this per corner on
/// load; the INSPECT TILT control overrides it.
pub fn auto_pre_emph(window: &[f64], sample_rate: f64) -> f64 {
    let frac = hf_fraction(window, sample_rate);
    let t = ((frac - 0.10) / (0.32 - 0.10)).clamp(0.0, 1.0);
    0.97 * (t * t * (3.0 - 2.0 * t))
}

/// The single fit entry: a conditioned window → one corner's six biquads. Uses the
/// deterministic ARMA pole-zero fit (real zeros — notches/teeth), falling back to
/// LPC (with auto brightness tilt) only if ARMA returns a degenerate result.
pub fn fit_window(window: &[f64], sr_in: f64) -> CornerData {
    trench_core::arma::fit_corner_arma(window, sr_in, AUTHORING_RATE).unwrap_or_else(|| {
        let pe = auto_pre_emph(window, sr_in);
        trench_core::lpc::fit_corner_pe(window, sr_in, AUTHORING_RATE, pe)
    })
}

/// Sharpen a corner toward higher Q: push every pole radius toward the unit circle
/// (narrower, more resonant), keeping its frequency and the zeros. `amount` in
/// [0,1]: 0 leaves it untouched, 1 pushes hard. This *is* what the Q axis does —
/// so the high-Q row of a body can be auto-derived from the low-Q row instead of
/// demanding separate sources. Re-normalised so Q changes character, not level.
pub fn sharpen_corner(corner: &CornerData, amount: f64, sample_rate: f64) -> CornerData {
    let amount = amount.clamp(0.0, 1.0);
    let mut out = *corner;
    for stage in out.iter_mut() {
        if is_passthrough(stage) {
            continue;
        }
        let a1 = stage[2] - 2.0; // pole part of the kernel
        let a2 = (1.0 - stage[3]).max(0.0);
        let r = a2.sqrt();
        if !(0.0..1.0).contains(&r) || r <= 0.0 {
            continue;
        }
        let theta = (-a1 / (2.0 * r)).clamp(-1.0, 1.0).acos();
        let r2 = r + amount * (0.9985 - r); // toward the unit circle
        stage[2] = -2.0 * r2 * theta.cos() + 2.0;
        stage[3] = 1.0 - r2 * r2;
    }
    trench_core::lpc::normalize_corner_peak(&mut out, sample_rate, 0.5);
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

// ── Waveform downsampling (display) ─────────────────────────────────────────

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

// ── C++ export ──────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

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

    /// Diagnostic (not a gate): where do the six actors actually land for a dark
    /// vowel through the LIVE fit, and how does pre-emphasis move them? Run:
    /// cargo test -p trench-forge dump_oo_conditioning -- --nocapture
    #[test]
    fn dump_oo_conditioning() {
        let dir = env!("CARGO_MANIFEST_DIR");
        let path = std::path::Path::new(dir).join("test_sounds").join("vowel_oo.wav");
        let Ok((samples, sr)) = load_wav_as_mono_f64(&path) else {
            println!("(missing vowel_oo)");
            return;
        };
        let onset = detect_onset(&samples, sr);
        let wlen = samples_for_ms(sr, DEFAULT_WINDOW_MS);
        let start = onset.min(samples.len().saturating_sub(wlen));
        let win = condition_fit_window(&samples[start..(start + wlen).min(samples.len())], false);

        println!(
            "  brightness frac={:.3} → auto pre_emph={:.2}",
            hf_fraction(&win, sr),
            auto_pre_emph(&win, sr)
        );
        let live = trench_core::lpc::fit_corner(&win, sr, AUTHORING_RATE);
        let actors: Vec<String> = live
            .iter()
            .map(|s| {
                if is_passthrough(s) {
                    "—".to_owned()
                } else {
                    format!("{:.0}Hz", stage_frequency(s, AUTHORING_RATE))
                }
            })
            .collect();
        println!("\nLPC fit_corner (pre_emph 0.97) actors: {}", actors.join("  "));

        match trench_core::arma::fit_corner_arma(&win, sr, AUTHORING_RATE) {
            Some(c) => {
                let pz: Vec<String> = c
                    .iter()
                    .map(|s| {
                        if is_passthrough(s) {
                            "—".to_owned()
                        } else {
                            format!("p{:.0}", stage_frequency(s, AUTHORING_RATE))
                        }
                    })
                    .collect();
                println!("LIVE ARMA fit (pole Hz): {}", pz.join("  "));
            }
            None => println!("LIVE ARMA fit: degenerate → LPC fallback"),
        }

        for pe in [0.0, 0.3, 0.5, 0.7, 0.9, 0.97] {
            let (poles, _) = trench_core::lpc::extract_poles_and_valleys_pe(&samples, sr, pe, 0);
            let fs: Vec<String> = poles.iter().map(|p| format!("{:.0}", p.freq_hz)).collect();
            println!("  pre_emph {pe:>4}: poles {}", fs.join(", "));
        }
    }

}
