//! Post-cascade QSound-style spatial stage: ITD + ILD + band-law shelves,
//! crossfaded with the dry signal by a `SPACE` parameter.
//!
//! Reference: `docs/archive/qsound_spatial.md` (canonical recon model) and
//! `docs/archive/qsound_spatial_addendum.md` (engineering recommendations
//! after the capture defect was identified). Per the addendum the numeric
//! ground truth is not trustworthy — we implement the parametric model
//! exactly and expose ITD/shelf corner tuning constants so the DSP can be
//! re-fit once a clean capture is available.

use crate::cartridge::{BandChannelCoeffs, BandLawCoeffs12, LawCoeffs6, SpatialProfile};

/// Maximum per-channel delay line length in samples. Caps the fractional
/// ITD at ~2.7 ms (well beyond the largest real head-side ITD) so the ring
/// buffer remains cheap to allocate per instance.
const MAX_DELAY_SAMPLES: usize = 128;

/// Tuning scalar converting the `itd_law` output to integer-ish samples of
/// inter-aural delay. The capture defect flagged in the addendum means this
/// factor is not pinned down — 5 samples at az=+π/3 maps the raw law's
/// ≈2666 through 2666 * (5 / 2666) = 5. Kept as a TODO constant until a
/// clean re-capture locks the unit; exposed so per-body retuning is cheap.
// TODO(qsound_spatial): replace with the factor chosen from the clean
// re-capture described in `qsound_spatial_addendum.md` §"Re-capture
// requirements before final Task 8 lock-in".
pub const ITD_SAMPLES_PER_LAW_UNIT: f32 = 1.0 / 533.2;

/// Low-shelf corner (Hz). Per addendum the 3-band dataset splits around
/// 400 Hz and 2500 Hz; these are engineering defaults until a clean capture
/// pins them.
// TODO(qsound_spatial): verify against re-capture.
pub const LOW_SHELF_CORNER_HZ: f32 = 400.0;

/// High-shelf corner (Hz).
// TODO(qsound_spatial): verify against re-capture.
pub const HIGH_SHELF_CORNER_HZ: f32 = 2_500.0;

/// Clean vendor-engine fallback calibration recovered from QCreator/QMixer.dll
/// at the exaggerated +90-degree position. The QCreator fixture was rendered
/// at 11025 Hz from a 0.5-amplitude mono impulse. Dividing its left PCM16
/// samples by 16384 converts the response into unity-input FIR coefficients.
const FALLBACK_QRIGHT90_NATIVE_SAMPLE_RATE: f32 = 11_025.0;
const FALLBACK_QRIGHT90_R_GAIN: f32 = 16_382.0 / 16_384.0;
const FALLBACK_QRIGHT90_L_PCM16: [i16; 23] = [
    0, -9616, -3474, -1891, -356, 1151, 937, 672, 282, -51, -156, -160, -100, -31, 10, 27, 25, 14,
    3, -2, -4, -3, -2,
];

fn fallback_qright90_l_ir(sample_rate: f32) -> Vec<f32> {
    let ratio = (sample_rate / FALLBACK_QRIGHT90_NATIVE_SAMPLE_RATE).max(1e-6);
    let output_len = (((FALLBACK_QRIGHT90_L_PCM16.len() - 1) as f32 * ratio).ceil() as usize) + 1;
    (0..output_len)
        .map(|index| {
            let source_pos =
                (index as f32 / ratio).min((FALLBACK_QRIGHT90_L_PCM16.len() - 1) as f32);
            let lower = source_pos.floor() as usize;
            let upper = (lower + 1).min(FALLBACK_QRIGHT90_L_PCM16.len() - 1);
            let frac = source_pos - lower as f32;
            let lower_sample = FALLBACK_QRIGHT90_L_PCM16[lower] as f32;
            let upper_sample = FALLBACK_QRIGHT90_L_PCM16[upper] as f32;
            (lower_sample + frac * (upper_sample - lower_sample)) / 16_384.0 / ratio
        })
        .collect()
}

// ── Fractional delay line (4-point Lagrange interpolation) ──

#[derive(Debug, Clone)]
struct FractionalDelay {
    buffer: Vec<f32>,
    write_idx: usize,
    delay_samples: f32,
}

impl FractionalDelay {
    fn new(max_delay: usize) -> Self {
        // +4 samples for the 4-point Lagrange stencil.
        Self {
            buffer: vec![0.0; max_delay + 4],
            write_idx: 0,
            delay_samples: 0.0,
        }
    }

    fn set_delay(&mut self, delay_samples: f32) {
        let max = (self.buffer.len() - 4) as f32;
        self.delay_samples = delay_samples.clamp(0.0, max);
    }

    fn process(&mut self, x: f32) -> f32 {
        let cap = self.buffer.len();
        self.buffer[self.write_idx] = x;

        // Read position `delay_samples` back from `write_idx`, wrapped.
        let rpos = self.write_idx as f32 + cap as f32 - self.delay_samples;
        let rpos_wrapped = rpos - (rpos / cap as f32).floor() * cap as f32;
        let i_floor = rpos_wrapped.floor() as isize;
        let frac = rpos_wrapped - i_floor as f32;

        // 4-point Lagrange with nodes at offsets [-1, 0, +1, +2] from i_floor.
        // frac ∈ [0, 1) represents the sample position between node 0 and 1.
        let cap_i = cap as isize;
        let get = |off: isize| -> f32 {
            let idx = (i_floor + off).rem_euclid(cap_i) as usize;
            self.buffer[idx]
        };
        let y0 = get(-1);
        let y1 = get(0);
        let y2 = get(1);
        let y3 = get(2);
        let c0 = -frac * (frac - 1.0) * (frac - 2.0) / 6.0;
        let c1 = (frac + 1.0) * (frac - 1.0) * (frac - 2.0) / 2.0;
        let c2 = -(frac + 1.0) * frac * (frac - 2.0) / 2.0;
        let c3 = (frac + 1.0) * frac * (frac - 1.0) / 6.0;
        let y = c0 * y0 + c1 * y1 + c2 * y2 + c3 * y3;

        self.write_idx = (self.write_idx + 1) % cap;
        y
    }

    fn reset(&mut self) {
        self.buffer.iter_mut().for_each(|s| *s = 0.0);
        self.write_idx = 0;
    }
}

// ── Biquad (direct-form II transposed, same layout as trench-core cascade) ──

#[derive(Debug, Clone, Copy, Default)]
struct Biquad {
    b0: f32,
    b1: f32,
    b2: f32,
    a1: f32,
    a2: f32,
    w1: f32,
    w2: f32,
}

impl Biquad {
    fn set_identity(&mut self) {
        self.b0 = 1.0;
        self.b1 = 0.0;
        self.b2 = 0.0;
        self.a1 = 0.0;
        self.a2 = 0.0;
    }

    fn process(&mut self, x: f32) -> f32 {
        let y = self.b0 * x + self.w1;
        self.w1 = self.b1 * x - self.a1 * y + self.w2;
        self.w2 = self.b2 * x - self.a2 * y;
        y
    }

    fn reset_state(&mut self) {
        self.w1 = 0.0;
        self.w2 = 0.0;
    }
}

/// RBJ cookbook low-shelf (S=1). Gain in dB.
fn low_shelf_coeffs(gain_db: f32, corner_hz: f32, sr: f32) -> Biquad {
    let a = 10_f32.powf(gain_db / 40.0);
    let w0 = 2.0 * std::f32::consts::PI * corner_hz / sr;
    let cos_w = w0.cos();
    let sin_w = w0.sin();
    let alpha = sin_w * 0.5 * ((a + 1.0 / a) * (1.0 / 1.0 - 1.0) + 2.0).sqrt();
    let two_sqrt_a_alpha = 2.0 * a.sqrt() * alpha;

    let b0 = a * ((a + 1.0) - (a - 1.0) * cos_w + two_sqrt_a_alpha);
    let b1 = 2.0 * a * ((a - 1.0) - (a + 1.0) * cos_w);
    let b2 = a * ((a + 1.0) - (a - 1.0) * cos_w - two_sqrt_a_alpha);
    let a0 = (a + 1.0) + (a - 1.0) * cos_w + two_sqrt_a_alpha;
    let a1 = -2.0 * ((a - 1.0) + (a + 1.0) * cos_w);
    let a2 = (a + 1.0) + (a - 1.0) * cos_w - two_sqrt_a_alpha;

    Biquad {
        b0: b0 / a0,
        b1: b1 / a0,
        b2: b2 / a0,
        a1: a1 / a0,
        a2: a2 / a0,
        w1: 0.0,
        w2: 0.0,
    }
}

/// RBJ cookbook high-shelf (S=1). Gain in dB.
fn high_shelf_coeffs(gain_db: f32, corner_hz: f32, sr: f32) -> Biquad {
    let a = 10_f32.powf(gain_db / 40.0);
    let w0 = 2.0 * std::f32::consts::PI * corner_hz / sr;
    let cos_w = w0.cos();
    let sin_w = w0.sin();
    let alpha = sin_w * 0.5 * ((a + 1.0 / a) * (1.0 / 1.0 - 1.0) + 2.0).sqrt();
    let two_sqrt_a_alpha = 2.0 * a.sqrt() * alpha;

    let b0 = a * ((a + 1.0) + (a - 1.0) * cos_w + two_sqrt_a_alpha);
    let b1 = -2.0 * a * ((a - 1.0) + (a + 1.0) * cos_w);
    let b2 = a * ((a + 1.0) + (a - 1.0) * cos_w - two_sqrt_a_alpha);
    let a0 = (a + 1.0) - (a - 1.0) * cos_w + two_sqrt_a_alpha;
    let a1 = 2.0 * ((a - 1.0) - (a + 1.0) * cos_w);
    let a2 = (a + 1.0) - (a - 1.0) * cos_w - two_sqrt_a_alpha;

    Biquad {
        b0: b0 / a0,
        b1: b1 / a0,
        b2: b2 / a0,
        a1: a1 / a0,
        a2: a2 / a0,
        w1: 0.0,
        w2: 0.0,
    }
}

// ── Band-law feature evaluation ──

fn eval_itd_ild_features(az: f32, el: f32) -> [f32; 6] {
    let s1 = az.sin();
    let s2 = (2.0 * az).sin();
    let s3 = (3.0 * az).sin();
    let s4 = (4.0 * az).sin();
    let s5 = (5.0 * az).sin();
    let el_cross = az.sin() * el.abs() / 30.0;
    [s1, s2, s3, s4, s5, el_cross]
}

fn dot6(coeffs: &LawCoeffs6, features: &[f32; 6]) -> f32 {
    (0..6).map(|i| coeffs[i] * features[i]).sum()
}

fn eval_band_features(az: f32, el: f32, dist_m: f32) -> [f32; 12] {
    let l = (dist_m.max(1e-6) / 0.25).log2();
    [
        1.0,
        l,
        l * l,
        az.sin(),
        az.cos(),
        (2.0 * az).sin(),
        (2.0 * az).cos(),
        (3.0 * az).sin(),
        (3.0 * az).cos(),
        el / 30.0,
        az.sin() * el / 30.0,
        az.cos() * el / 30.0,
    ]
}

fn dot12(coeffs: &BandLawCoeffs12, features: &[f32; 12]) -> f32 {
    (0..12).map(|i| coeffs[i] * features[i]).sum()
}

#[derive(Debug, Clone, Copy, Default)]
struct ChannelShelves {
    low_db: f32,
    high_db: f32,
}

fn eval_channel_shelves(band: &BandChannelCoeffs, features: &[f32; 12]) -> ChannelShelves {
    let low = dot12(&band.low, features);
    let mid = dot12(&band.mid, features);
    let high = dot12(&band.high, features);
    // Per addendum §"Engineering recommendation": apply shelves as deltas
    // against the mid band. The absolute mid level is a global baseline
    // that would otherwise collapse the signal by ≈ −73 dB; it is handled
    // (or discarded) outside the shelf pair.
    ChannelShelves {
        low_db: low - mid,
        high_db: high - mid,
    }
}

// ── Main processor ──

pub struct QSoundSpatial {
    sample_rate: f32,
    space: f32,
    fallback_pan: f32,
    profile: Option<SpatialProfile>,
    // ITD one-sided delay lines. Right-ear-lead convention: positive itd
    // delays L, leaves R passthrough; negative itd does the opposite.
    delay_l: FractionalDelay,
    delay_r: FractionalDelay,
    l_low: Biquad,
    l_high: Biquad,
    r_low: Biquad,
    r_high: Biquad,
    fallback_shadow_ir: Vec<f32>,
    fallback_mono_history: Vec<f32>,
    fallback_mono_write_idx: usize,
    // Broadband per-channel linear gain from the ILD law.
    gain_l: f32,
    gain_r: f32,
    dirty: bool,
}

impl QSoundSpatial {
    pub fn new(sample_rate: f32) -> Self {
        let fallback_shadow_ir = fallback_qright90_l_ir(sample_rate);
        let mut this = Self {
            sample_rate,
            space: 0.0,
            fallback_pan: 1.0,
            profile: None,
            delay_l: FractionalDelay::new(MAX_DELAY_SAMPLES),
            delay_r: FractionalDelay::new(MAX_DELAY_SAMPLES),
            l_low: Biquad::default(),
            l_high: Biquad::default(),
            r_low: Biquad::default(),
            r_high: Biquad::default(),
            fallback_mono_history: vec![0.0; fallback_shadow_ir.len()],
            fallback_shadow_ir,
            fallback_mono_write_idx: 0,
            gain_l: 1.0,
            gain_r: 1.0,
            dirty: true,
        };
        this.l_low.set_identity();
        this.l_high.set_identity();
        this.r_low.set_identity();
        this.r_high.set_identity();
        this
    }

    pub fn set_profile(&mut self, profile: &SpatialProfile) {
        self.profile = Some(profile.clone());
        self.dirty = true;
    }

    pub fn clear_profile(&mut self) {
        self.profile = None;
        self.dirty = true;
    }

    pub fn set_space(&mut self, space: f32) {
        self.space = space.clamp(0.0, 1.0);
    }

    /// Set the local-recreation pan when no cartridge spatial profile is
    /// loaded. `-1` is exaggerated left, `0` is dry mono center, and `+1`
    /// is the clean QCreator/QMixer.dll right-90 fixture. The default is
    /// `+1` so the 5D toggle uses the requested extreme QSound-right behavior
    /// without a second UI control.
    pub fn set_fallback_pan(&mut self, pan: f32) {
        self.fallback_pan = pan.clamp(-1.0, 1.0);
    }

    /// Zero all delay-line and biquad state. Use on cartridge swap or
    /// sample-rate change; safe on the audio thread (no allocation —
    /// buffers are pre-sized at `new`).
    pub fn reset(&mut self) {
        self.delay_l.reset();
        self.delay_r.reset();
        self.l_low.reset_state();
        self.l_high.reset_state();
        self.r_low.reset_state();
        self.r_high.reset_state();
        self.fallback_mono_history
            .iter_mut()
            .for_each(|sample| *sample = 0.0);
        self.fallback_mono_write_idx = 0;
    }

    fn recompute(&mut self) {
        let Some(ref p) = self.profile else {
            return;
        };
        let itd_ild_features = eval_itd_ild_features(p.azimuth, p.elevation);
        let ild_law_db = dot6(&p.ild_coeffs, &itd_ild_features);

        // ITD: convert the raw law output to samples via the tuning scalar.
        // Positive → L lags R; negative → R lags L. One-sided: only the
        // lagging ear sees delay, the leading ear passes straight through.
        let itd_law = dot6(&p.itd_coeffs, &itd_ild_features);
        let itd_samples = itd_law * ITD_SAMPLES_PER_LAW_UNIT;
        if itd_samples >= 0.0 {
            self.delay_l.set_delay(itd_samples);
            self.delay_r.set_delay(0.0);
        } else {
            self.delay_l.set_delay(0.0);
            self.delay_r.set_delay(-itd_samples);
        }

        let band_features = eval_band_features(p.azimuth, p.elevation, p.distance);
        let l_shelf = eval_channel_shelves(&p.band_coeffs.l, &band_features);
        let r_shelf = eval_channel_shelves(&p.band_coeffs.r, &band_features);

        self.l_low = low_shelf_coeffs(l_shelf.low_db, LOW_SHELF_CORNER_HZ, self.sample_rate);
        self.l_high = high_shelf_coeffs(l_shelf.high_db, HIGH_SHELF_CORNER_HZ, self.sample_rate);
        self.r_low = low_shelf_coeffs(r_shelf.low_db, LOW_SHELF_CORNER_HZ, self.sample_rate);
        self.r_high = high_shelf_coeffs(r_shelf.high_db, HIGH_SHELF_CORNER_HZ, self.sample_rate);

        // ILD broadband gain: attenuate the contralateral ear by the full
        // ILD law so the leading ear is 0 dB and the lagging ear is
        // -|ild_law_db|. This preserves the L/R imbalance while avoiding
        // any positive gain — a prerequisite for the full-scale-peak
        // stability target.
        let mut l_broadband_db = if ild_law_db >= 0.0 { -ild_law_db } else { 0.0 };
        let mut r_broadband_db = if ild_law_db < 0.0 { ild_law_db } else { 0.0 };

        // Guard against shelves pushing the per-channel response above
        // 0 dB at any frequency. Worst-case is a broadband stimulus with
        // content concentrated where *both* shelves boost, so subtract
        // `max(0, low) + max(0, high)` from the broadband gain. Shelves
        // with negative gain cut, so they can't drive peak above unity.
        // `PEAK_SAFETY_DB` absorbs 4-point Lagrange overshoot on
        // fractional ITD (worst-case ~6% ≈ 0.5 dB when `frac≈0.5` on
        // wideband noise), RBJ shelf passband ripple near the corners,
        // and residual biquad startup — ≈1 dB is inaudible as a
        // global pan-stage trim but keeps `peak ≤ +0 dBFS` strict on
        // full-scale noise across the full ±60° sweep.
        const PEAK_SAFETY_DB: f32 = 1.0;
        l_broadband_db -= l_shelf.low_db.max(0.0) + l_shelf.high_db.max(0.0) + PEAK_SAFETY_DB;
        r_broadband_db -= r_shelf.low_db.max(0.0) + r_shelf.high_db.max(0.0) + PEAK_SAFETY_DB;

        self.gain_l = 10_f32.powf(l_broadband_db / 20.0);
        self.gain_r = 10_f32.powf(r_broadband_db / 20.0);

        self.dirty = false;
    }

    pub fn process_stereo(&mut self, l: &mut [f32], r: &mut [f32]) {
        if self.space == 0.0 {
            return;
        }
        if self.profile.is_none() {
            self.process_fallback_stereo(l, r);
            return;
        }
        if self.dirty {
            self.recompute();
        }
        debug_assert_eq!(l.len(), r.len(), "stereo buffers must be same length");

        let n = l.len().min(r.len());
        for i in 0..n {
            let dry_l = l[i];
            let dry_r = r[i];
            let delayed_l = self.delay_l.process(dry_l);
            let delayed_r = self.delay_r.process(dry_r);
            let shelf_l = self.l_high.process(self.l_low.process(delayed_l));
            let shelf_r = self.r_high.process(self.r_low.process(delayed_r));
            let wet_l = shelf_l * self.gain_l;
            let wet_r = shelf_r * self.gain_r;
            l[i] = dry_l + self.space * (wet_l - dry_l);
            r[i] = dry_r + self.space * (wet_r - dry_r);
        }
    }

    fn process_fallback_stereo(&mut self, l: &mut [f32], r: &mut [f32]) {
        let space = self.space.clamp(0.0, 1.0);
        let pan = self.fallback_pan.clamp(-1.0, 1.0);
        let pan_amount = pan.abs();
        let n = l.len().min(r.len());
        for i in 0..n {
            let dry_l = l[i];
            let dry_r = r[i];
            let mono = 0.5 * (dry_l + dry_r);

            self.fallback_mono_history[self.fallback_mono_write_idx] = mono;
            let mut read_idx = self.fallback_mono_write_idx;
            let mut shadow = 0.0;
            for &coeff in &self.fallback_shadow_ir {
                shadow += coeff * self.fallback_mono_history[read_idx];
                read_idx = if read_idx == 0 {
                    self.fallback_mono_history.len() - 1
                } else {
                    read_idx - 1
                };
            }
            self.fallback_mono_write_idx =
                (self.fallback_mono_write_idx + 1) % self.fallback_mono_history.len();

            let lead = mono * FALLBACK_QRIGHT90_R_GAIN;
            let (extreme_l, extreme_r) = if pan >= 0.0 {
                (shadow, lead)
            } else {
                (lead, shadow)
            };
            let wet_l = mono + pan_amount * (extreme_l - mono);
            let wet_r = mono + pan_amount * (extreme_r - mono);
            l[i] = dry_l + space * (wet_l - dry_l);
            r[i] = dry_r + space * (wet_r - dry_r);
        }
    }
}
