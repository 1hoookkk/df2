//! LPC capture: reduce a recorded sound (vowel, metal tube, resonant body) to
//! its six dominant resonances — the actors of one corner.
//!
//! Pure-Rust LPC extraction: resample to
//! 16 kHz, find the steady-state region, conditional pre-emphasis, Hamming
//! window, 12th-order autocorrelation LPC (Levinson-Durbin), root the LPC
//! polynomial (Durand-Kerner), keep the top-6 resonant poles in the formant
//! band, then re-home each pole as a biquad at the runtime coefficient rate.
//!
//! All-pole model: vowels and struck/blown resonators are dominated by
//! resonances (poles); zeros are left at the origin. No external deps.

use crate::cartridge::CornerData;
use crate::cascade::NUM_STAGES;

// Analysis spans the full TRENCH actor range (sub→air), not just the voice
// formant band — so bright material (hats, metal, breath) can populate the
// air/RIP actor instead of being capped off at 7 kHz.
const ANALYSIS_SR: f64 = 22050.0;
const LPC_ORDER: usize = 14;
// TRANSPARENCY (audit 2026-05-24): 0.0 = fit the RAW envelope. Pre-emphasis (0.97)
// brightens the analysed spectrum to help estimate high formants, but the realised
// filter is built straight from those poles with NO de-emphasis — and a 6-biquad
// cascade has no room for a 7th de-emphasis pole — so any pre-emphasis tilts the
// captured corner ~6 dB/oct bright and discards the low body (the "no body" the
// user heard). 0.0 captures the true low body faithfully. NOTE: this changes the
// old 2026-05-22 Talking-Hedz match, which was tuned to the brightened spectrum.
const PRE_EMPH: f64 = 0.0;
const FRAME_MS: f64 = 25.0;
const HOP_MS: f64 = 10.0;
const PEAK_RMS_TOL_DB: f64 = 3.0;
const F_MIN_HZ: f64 = 90.0;
// The packed runtime response and authoring grid both retain measured actors
// through 16 kHz. Keeping the LPC candidate ceiling at 10 kHz silently drops
// a real high actor from bright measured sources and makes the six-lane
// contract impossible to satisfy.
const F_MAX_HZ: f64 = 16000.0;
const N_KEEP: usize = 6;
const PASSTHROUGH: [f64; 5] = [2.0, 1.0, 2.0, 1.0, 1.0];

#[derive(Clone, Copy, Debug)]
pub struct Pole {
    pub freq_hz: f64,
    pub radius: f64,
    pub bw_hz: f64,
}

// ── minimal complex ──────────────────────────────────────────────────────────
#[derive(Clone, Copy)]
struct C {
    re: f64,
    im: f64,
}
impl C {
    fn new(re: f64, im: f64) -> Self {
        C { re, im }
    }
    fn add(self, o: C) -> C {
        C::new(self.re + o.re, self.im + o.im)
    }
    fn sub(self, o: C) -> C {
        C::new(self.re - o.re, self.im - o.im)
    }
    fn mul(self, o: C) -> C {
        C::new(
            self.re * o.re - self.im * o.im,
            self.re * o.im + self.im * o.re,
        )
    }
    fn div(self, o: C) -> C {
        let d = o.re * o.re + o.im * o.im;
        C::new(
            (self.re * o.re + self.im * o.im) / d,
            (self.im * o.re - self.re * o.im) / d,
        )
    }
    fn abs(self) -> f64 {
        self.re.hypot(self.im)
    }
    fn angle(self) -> f64 {
        self.im.atan2(self.re)
    }
}

// ── resample (linear) to 16 kHz ──────────────────────────────────────────────
fn resample_linear(x: &[f64], sr_in: f64, sr_out: f64) -> Vec<f64> {
    if (sr_in - sr_out).abs() < 1.0 || x.len() < 2 {
        return x.to_vec();
    }
    let ratio = sr_in / sr_out;
    let n_out = ((x.len() as f64) / ratio).floor() as usize;
    let mut out = Vec::with_capacity(n_out);
    for i in 0..n_out {
        let pos = i as f64 * ratio;
        let i0 = pos.floor() as usize;
        let frac = pos - i0 as f64;
        let a = x[i0];
        let b = if i0 + 1 < x.len() { x[i0 + 1] } else { a };
        out.push(a + (b - a) * frac);
    }
    out
}

// ── longest steady-state run (RMS within tol of peak) ────────────────────────
fn steady_state(x: &[f64], sr: f64) -> (usize, usize) {
    let frame_n = (FRAME_MS * 1e-3 * sr).round() as usize;
    let hop_n = (HOP_MS * 1e-3 * sr).round().max(1.0) as usize;
    if x.len() < frame_n || frame_n == 0 {
        return (0, x.len());
    }
    let n_frames = 1 + (x.len() - frame_n) / hop_n;
    let mut rms = Vec::with_capacity(n_frames);
    let mut peak = 1e-30f64;
    for f in 0..n_frames {
        let s = f * hop_n;
        let e = s + frame_n;
        let mut acc = 0.0;
        for &v in &x[s..e] {
            acc += v * v;
        }
        let r = (acc / frame_n as f64 + 1e-30).sqrt();
        peak = peak.max(r);
        rms.push(r);
    }
    let thr_db = -PEAK_RMS_TOL_DB;
    let above: Vec<bool> = rms
        .iter()
        .map(|r| 20.0 * (r / peak + 1e-30).log10() >= thr_db)
        .collect();
    let (mut best_start, mut best_len, mut cur) = (0usize, 0usize, None::<usize>);
    for (i, &v) in above.iter().enumerate() {
        if v {
            cur.get_or_insert(i);
        } else if let Some(c) = cur.take() {
            if i - c > best_len {
                best_start = c;
                best_len = i - c;
            }
        }
    }
    if let Some(c) = cur {
        if above.len() - c > best_len {
            best_start = c;
            best_len = above.len() - c;
        }
    }
    if best_len == 0 {
        return (0, x.len());
    }
    let s = best_start * hop_n;
    let e = ((best_start + best_len - 1) * hop_n + frame_n).min(x.len());
    (s, e)
}

// ── autocorrelation LPC via Levinson-Durbin ──────────────────────────────────
fn lpc_levinson(x: &[f64], order: usize) -> Option<Vec<f64>> {
    let n = x.len();
    if n <= order {
        return None;
    }
    let mut r = vec![0.0f64; order + 1];
    for (k, rk) in r.iter_mut().enumerate() {
        let mut acc = 0.0;
        for i in k..n {
            acc += x[i] * x[i - k];
        }
        *rk = acc;
    }
    if r[0] <= 0.0 {
        return None;
    }
    let mut a = vec![0.0f64; order + 1];
    a[0] = 1.0;
    let mut e = r[0];
    for i in 1..=order {
        // reflection coefficient (uses current a[1..i])
        let mut acc = r[i];
        for j in 1..i {
            acc += a[j] * r[i - j];
        }
        let k = -acc / e;
        // update with a fresh copy so the recursion reads OLD coefficients
        let prev = a.clone();
        for j in 1..i {
            a[j] = prev[j] + k * prev[i - j];
        }
        a[i] = k;
        e *= 1.0 - k * k;
        if e <= 0.0 {
            e = 1e-12;
        }
    }
    Some(a)
}

// ── roots of monic polynomial (Durand-Kerner) ────────────────────────────────
// coeffs `a` are A(z) = 1 + a1 z^-1 + ... + ap z^-p; roots of z^p + a1 z^(p-1) + ... + ap.
fn roots(a: &[f64]) -> Vec<C> {
    let p = a.len() - 1; // degree
    if p == 0 {
        return vec![];
    }
    // monic coeffs high→low: [1, a1, a2, ..., ap]
    let coeffs: Vec<C> = a.iter().map(|&c| C::new(c, 0.0)).collect();
    let eval = |z: C| -> C {
        let mut acc = C::new(0.0, 0.0);
        for c in &coeffs {
            acc = acc.mul(z).add(*c);
        }
        acc
    };
    // init: (0.4 + 0.9i)^k
    let seed = C::new(0.4, 0.9);
    let mut zs = Vec::with_capacity(p);
    let mut cur = C::new(1.0, 0.0);
    for _ in 0..p {
        zs.push(cur);
        cur = cur.mul(seed);
    }
    for _ in 0..200 {
        let mut max_step = 0.0f64;
        for i in 0..p {
            let zi = zs[i];
            let mut denom = C::new(1.0, 0.0);
            for (j, &zj) in zs.iter().enumerate() {
                if j != i {
                    denom = denom.mul(zi.sub(zj));
                }
            }
            if denom.abs() < 1e-30 {
                continue;
            }
            let step = eval(zi).div(denom);
            zs[i] = zi.sub(step);
            max_step = max_step.max(step.abs());
        }
        if max_step < 1e-12 {
            break;
        }
    }
    zs
}

// Shared analysis: condition the sound and run order-`LPC_ORDER` LPC.
// Returns (LPC polynomial A(z), kept resonant poles).
fn analyze_lpc(samples: &[f64], sr_in: f64) -> Option<(Vec<f64>, Vec<Pole>)> {
    analyze_lpc_pe(samples, sr_in, PRE_EMPH, LPC_ORDER, false)
}

// As `analyze_lpc`, but with explicit pre-emphasis, LPC order, and a
// `conditioned` flag for the authoring path. When `conditioned` is true the
// caller has already cut and windowed the exact slice it wants fit (the Forge):
// we then skip the internal steady-state hunt and the second window. That
// matters — re-windowing an already-windowed slice (and steady-state-trimming a
// tapered one to its centre) collapses the effective length and fattens every
// pole. One window, one slice, faithful bandwidths.
fn analyze_lpc_pe(
    samples: &[f64],
    sr_in: f64,
    pre_emph: f64,
    order: usize,
    conditioned: bool,
) -> Option<(Vec<f64>, Vec<Pole>)> {
    let x = resample_linear(samples, sr_in, ANALYSIS_SR);
    let seg: Vec<f64> = if conditioned {
        x // exactly the caller's slice — no steady-state hunt
    } else {
        let (s, e) = steady_state(&x, ANALYSIS_SR);
        let seg = x[s..e].to_vec();
        if seg.len() <= order + 1 {
            x
        } else {
            seg
        }
    };
    // pre-emphasis (off by default; flattens source tilt when used)
    let mut pre = vec![0.0f64; seg.len()];
    pre[0] = seg[0];
    for i in 1..seg.len() {
        pre[i] = seg[i] - pre_emph * seg[i - 1];
    }
    // Window once. A conditioned slice is already windowed by the caller, so
    // windowing again here would just narrow the effective length.
    if !conditioned {
        let n = pre.len();
        for (i, v) in pre.iter_mut().enumerate() {
            let w = 0.54 - 0.46 * (2.0 * std::f64::consts::PI * i as f64 / (n as f64 - 1.0)).cos();
            *v *= w;
        }
    }
    let a = lpc_levinson(&pre, order)?;
    let mut cand: Vec<Pole> = Vec::new();
    for z in roots(&a) {
        if z.im <= 0.0 {
            continue; // one per conjugate pair
        }
        let r = z.abs();
        if !(r > 0.0 && r < 1.0) {
            continue;
        }
        let f = z.angle() * ANALYSIS_SR / (2.0 * std::f64::consts::PI);
        if f < F_MIN_HZ || f > F_MAX_HZ {
            continue;
        }
        let bw = -ANALYSIS_SR / std::f64::consts::PI * r.ln();
        cand.push(Pole {
            freq_hz: f,
            radius: r,
            bw_hz: bw,
        });
    }
    cand.sort_by(|p, q| q.radius.partial_cmp(&p.radius).unwrap()); // strongest first
    cand.truncate(N_KEEP);
    cand.sort_by(|p, q| p.freq_hz.partial_cmp(&q.freq_hz).unwrap()); // ascending freq
    Some((a, cand))
}

/// Extract the top-N resonant poles from a recorded sound.
pub fn extract_poles(samples: &[f64], sr_in: f64) -> Vec<Pole> {
    analyze_lpc(samples, sr_in)
        .map(|(_, p)| p)
        .unwrap_or_default()
}

/// Poles plus the spectral-valley (anti-resonance) frequencies, strongest first.
/// For callers that build their own pole-zero sections — e.g. the Forge, which
/// gives the zeros their bite (the character) rather than peak-taming each pole.
pub fn extract_poles_and_valleys(samples: &[f64], sr_in: f64) -> (Vec<Pole>, Vec<f64>) {
    match analyze_lpc(samples, sr_in) {
        Some((a, poles)) => (poles, valley_freqs(&a)),
        None => (Vec::new(), Vec::new()),
    }
}

/// Authoring extraction: the caller (the Forge) has already cut and windowed the
/// exact slice to fit, so skip the internal steady-state hunt and second window
/// — one window, one slice → faithful (sharp) bandwidths instead of fat poles.
pub fn extract_poles_and_valleys_conditioned(samples: &[f64], sr_in: f64) -> (Vec<Pole>, Vec<f64>) {
    match analyze_lpc_pe(samples, sr_in, PRE_EMPH, LPC_ORDER, true) {
        Some((a, poles)) => (poles, valley_freqs(&a)),
        None => (Vec::new(), Vec::new()),
    }
}

/// Diagnostic entry: same as `extract_poles_and_valleys` but with explicit
/// pre-emphasis and LPC order, for sweeping the conditioning that best preserves
/// both low and high formants at faithful bandwidth. Not part of the shipped fit
/// path. `order = 0` uses the shipped default.
#[doc(hidden)]
pub fn extract_poles_and_valleys_pe(
    samples: &[f64],
    sr_in: f64,
    pre_emph: f64,
    order: usize,
) -> (Vec<Pole>, Vec<f64>) {
    let order = if order == 0 { LPC_ORDER } else { order };
    match analyze_lpc_pe(samples, sr_in, pre_emph, order, false) {
        Some((a, poles)) => (poles, valley_freqs(&a)),
        None => (Vec::new(), Vec::new()),
    }
}

// Spectral valleys = the anti-resonances (zeros). The envelope is 1/|A(e^jw)|,
// so its valleys are the PEAKS of |A(e^jw)|. Returns valley frequencies (Hz),
// strongest first.
fn valley_freqs(a: &[f64]) -> Vec<f64> {
    let n = 600usize;
    let freqs: Vec<f64> = (0..n)
        .map(|i| F_MIN_HZ * (F_MAX_HZ / F_MIN_HZ).powf(i as f64 / (n - 1) as f64))
        .collect();
    let mag: Vec<f64> = freqs
        .iter()
        .map(|&f| {
            let w = 2.0 * std::f64::consts::PI * f / ANALYSIS_SR;
            let (mut re, mut im) = (0.0f64, 0.0f64);
            for (k, &ak) in a.iter().enumerate() {
                re += ak * (w * k as f64).cos();
                im -= ak * (w * k as f64).sin();
            }
            (re * re + im * im).sqrt() // |A| — peaks here = envelope valleys
        })
        .collect();
    let mut v: Vec<(f64, f64)> = Vec::new();
    for i in 1..n - 1 {
        if mag[i] > mag[i - 1] && mag[i] >= mag[i + 1] {
            v.push((freqs[i], mag[i]));
        }
    }
    v.sort_by(|x, y| y.1.partial_cmp(&x.1).unwrap()); // most prominent valleys first
    v.into_iter().map(|(f, _)| f).collect()
}

/// Fit a recorded sound to one corner: six pole-zero biquads (resonance +
/// adjacent anti-resonance) re-homed at the runtime rate, in kernel form.
pub fn fit_corner(samples: &[f64], sr_in: f64, runtime_sr: f64) -> CornerData {
    fit_corner_pe(samples, sr_in, runtime_sr, PRE_EMPH)
}

/// As `fit_corner`, with an explicit brightness tilt (pre-emphasis applied before
/// the LPC). Lower tilt keeps a dark source's low-formant body — the F1 a high
/// tilt trades away for a spurious air-band pole — while higher tilt spreads
/// bright material across the band. The Forge sets this per corner from the
/// source's measured brightness, with a manual override in INSPECT.
pub fn fit_corner_pe(samples: &[f64], sr_in: f64, runtime_sr: f64, pre_emph: f64) -> CornerData {
    let Some((a, poles)) = analyze_lpc_pe(samples, sr_in, pre_emph, LPC_ORDER, false) else {
        return [PASSTHROUGH; NUM_STAGES];
    };
    let zeros = valley_freqs(&a);
    realize_poles_zeros(&poles, &zeros, runtime_sr)
}

/// VOICE fit from an ALREADY-conditioned (cut + windowed) slice, with explicit
/// pre-emphasis. This is the honest voice-capture path: pre-emphasis flattens the
/// glottal + radiation source tilt (~−6 dB/oct) so the order-`LPC_ORDER` LPC poles
/// land on the **vocal-tract formants** (F1/F2/F3…) instead of being dragged into
/// the loud low-end energy — the failure that made a dropped "aaa" capture as body
/// + hiss with no vowel. The `conditioned` flag means the caller (the Forge) has
/// already sliced and Hann-windowed exactly what it wants fit, so the internal
/// steady-state hunt and second window are skipped (one window → sharp, faithful
/// formant bandwidths instead of fattened poles).
///
/// NOTE the deliberate trade (audit 2026-05-24): a 6-biquad cascade has no room for
/// a 7th de-emphasis pole, so a non-zero `pre_emph` here leaves the realised corner
/// tilted brighter than the raw source. For VOICE that is the point — formants over
/// body. The neutral `fit_corner`/`fit_corner_conditioned` paths keep `PRE_EMPH=0`.
pub fn fit_corner_conditioned_pe(
    samples: &[f64],
    sr_in: f64,
    runtime_sr: f64,
    pre_emph: f64,
) -> CornerData {
    let Some((a, poles)) = analyze_lpc_pe(samples, sr_in, pre_emph, LPC_ORDER, true) else {
        return [PASSTHROUGH; NUM_STAGES];
    };
    let zeros = valley_freqs(&a);
    realize_poles_zeros(&poles, &zeros, runtime_sr)
}

/// Build the six pole-zero biquads (in kernel form) from a set of resonant poles
/// and spectral-valley zeros, then spread-normalize the cascade peak. Shared by
/// every LPC fit entry so the realization is owned in exactly one place.
fn realize_poles_zeros(poles: &[Pole], zeros: &[f64], runtime_sr: f64) -> CornerData {
    const Z_RADIUS: f64 = 0.93; // notch depth/character
    let mut corner: CornerData = [PASSTHROUGH; NUM_STAGES];
    for (i, p) in poles.iter().take(NUM_STAGES).enumerate() {
        // Natural radius from the captured bandwidth (varied Q = complexity).
        // The Forge's DEPTH control pushes these toward the unit circle later.
        let rp = (-std::f64::consts::PI * p.bw_hz / runtime_sr)
            .exp()
            .clamp(0.5, 0.997);
        let tp = 2.0 * std::f64::consts::PI * p.freq_hz / runtime_sr;
        let a1 = -2.0 * rp * tp.cos();
        let a2 = rp * rp;
        let g = 1.0 - rp * rp; // peak-tamed gain

        // nearest spectral valley → a zero, but only if it's clearly OFF the
        // pole (>~1/4 octave) so it carves a notch instead of cancelling it.
        let zero = zeros
            .iter()
            .copied()
            .filter(|&fz| (fz / p.freq_hz).log2().abs() > 0.25)
            .min_by(|x, y| {
                (x - p.freq_hz)
                    .abs()
                    .partial_cmp(&(y - p.freq_hz).abs())
                    .unwrap()
            });
        let (b0, b1, b2) = if let Some(fz) = zero {
            let tz = 2.0 * std::f64::consts::PI * fz / runtime_sr;
            (g, g * (-2.0 * Z_RADIUS * tz.cos()), g * Z_RADIUS * Z_RADIUS)
        } else {
            (g, 0.0, 0.0)
        };
        // kernel form (sos → kernel): c4=b0, c2=a1+2, c3=1-a2,
        //   c0 = 2 + b1/b0, c1 = 1 - b2/b0
        corner[i] = [2.0 + b1 / b0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0];
    }
    normalize_corner_peak(&mut corner, runtime_sr, 0.5);
    corner
}

// Scale the cascade so its peak magnitude ≈ `target` — keeps audio at a sane,
// consistent level across corners (and through the morph). The scalar gain is
// spread evenly across the active stages (`g^(1/n)` per stage), not dumped on
// one: the cascade is a product, so this is the same response with the gain
// merely relocated, but it keeps every c4 inside the packable [0,4] minifloat
// box instead of letting one stage's gain overflow and pack to silence.
pub fn normalize_corner_peak(corner: &mut CornerData, sr: f64, target: f64) {
    let mag_at = |k: &[f64; 5], w: f64| -> f64 {
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
    for i in 0..96 {
        let f = 40.0 * (16000.0f64 / 40.0).powf(i as f64 / 95.0);
        let w = 2.0 * std::f64::consts::PI * f / sr;
        let mut mag = 1.0;
        for k in corner.iter() {
            mag *= mag_at(k, w);
        }
        peak = peak.max(mag);
    }
    let g = target / peak;
    let passth = |k: &[f64; 5]| {
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

    // Drive white noise through two known resonators (r<1) — the faithful
    // "vowel / resonant body" case — and confirm LPC recovers the peaks.
    fn resonator(x: &[f64], f: f64, r: f64, sr: f64) -> Vec<f64> {
        let theta = 2.0 * std::f64::consts::PI * f / sr;
        let a1 = -2.0 * r * theta.cos();
        let a2 = r * r;
        let b0 = 1.0 - r;
        let (mut y1, mut y2) = (0.0, 0.0);
        let mut out = vec![0.0; x.len()];
        for (i, &xi) in x.iter().enumerate() {
            let y = b0 * xi - a1 * y1 - a2 * y2;
            out[i] = y;
            y2 = y1;
            y1 = y;
        }
        out
    }
    #[test]
    fn recovers_planted_formants() {
        let sr = 16000.0;
        let n = 24000;
        let (f1, f2) = (700.0, 1800.0);
        // deterministic white noise
        let mut seed = 0x1234_5678u64;
        let mut noise = vec![0.0f64; n];
        for v in noise.iter_mut() {
            seed = seed
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            *v = ((seed >> 33) as f64 / (1u64 << 31) as f64) - 1.0;
        }
        let a = resonator(&noise, f1, 0.97, sr);
        let x = resonator(&a, f2, 0.96, sr);
        let poles = extract_poles(&x, sr);
        assert!(!poles.is_empty(), "no poles found");
        let near = |target: f64| poles.iter().any(|p| (p.freq_hz - target).abs() < 180.0);
        let got: Vec<f64> = poles.iter().map(|p| p.freq_hz.round()).collect();
        assert!(near(f1), "missed F1≈700: {got:?}");
        assert!(near(f2), "missed F2≈1800: {got:?}");
    }

    #[test]
    fn fit_corner_is_finite_and_stable() {
        let sr = 16000.0;
        let n = 8000;
        let mut x = vec![0.0f64; n];
        for (i, xi) in x.iter_mut().enumerate() {
            let t = i as f64 / sr;
            *xi = (2.0 * std::f64::consts::PI * 800.0 * t).sin()
                + 0.4 * (2.0 * std::f64::consts::PI * 2500.0 * t).sin();
        }
        let corner = fit_corner(&x, sr, 39062.5);
        for stage in &corner {
            for c in stage {
                assert!(c.is_finite());
            }
            // a2 = 1 - c3 must be < 1 (stable pole)
            assert!(1.0 - stage[3] < 1.0);
        }
    }
}
