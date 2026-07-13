//! Post-cascade QSound-style spatial stage: ITD + ILD + band-law shelves,
//! crossfaded with the dry signal by a `SPACE` parameter.
//!
//! Re-capture provenance (2026-07-02): the ITD/ILD/shelf-corner constants
//! below were re-fit from a CLEAN 31-point pan-grid capture of the vendor
//! `QMixer.dll` (SHA-256 0d3784…b110e) rendered offline by `Qcreator.exe`.
//! The pan process was verified LINEAR (out@1.0 == 2·out@0.5, −90 dB).
//! Fit gates all pass: ITD 11.2 µs
//! (≤30), ILD 0.78 dB (≤1.0), spectral 0.134 dB (≤1.5). Parameters are fitted
//! from measurements only — no bytes/tables were lifted from the DLL. Source
//! capture records remain outside this product branch.

use crate::cartridge::{BandChannelCoeffs, BandLawCoeffs12, LawCoeffs6, SpatialProfile};

/// Maximum per-channel delay line length in samples. Caps the fractional
/// ITD at ~2.7 ms (well beyond the largest real head-side ITD) so the ring
/// buffer remains cheap to allocate per instance.
const MAX_DELAY_SAMPLES: usize = 128;

/// Microseconds-to-seconds scale for the ITD law. After the clean QCreator
/// pan-grid re-capture (2026-07-02) the ITD law `dot6(itd_coeffs, features)`
/// evaluates directly to MICROSECONDS of inter-aural delay, fit from the
/// vendor QMixer.dll offline renders over −90..+90° (ITD MAE 11.2 µs,
/// gate ≤30 µs).
/// Converting microseconds to samples is sample-rate dependent, so this
/// scalar is µs→s and is multiplied by the runtime sample rate in
/// `recompute` (fixes the sample-rate-independence defect of the old
/// placeholder `1/533.2`).
pub const ITD_SAMPLES_PER_LAW_UNIT: f32 = 1.0e-6;

/// Low-shelf corner (Hz). Fitted from the clean re-capture: the QSound
/// shadow-ear head-shadow filter transitions at ≈513 Hz (2-shelf model,
/// spectral MAE 0.134 dB vs the measured per-ear magnitude, gate ≤1.5 dB).
pub const LOW_SHELF_CORNER_HZ: f32 = 513.2;

/// High-shelf corner (Hz). Fitted from the clean re-capture (≈1816 Hz).
pub const HIGH_SHELF_CORNER_HZ: f32 = 1_816.4;

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

fn eval_itd_ild_features(az: f32, _el: f32) -> [f32; 6] {
    // QSound (QMixer.dll) is a pure azimuth panner: the offline pan grid has
    // no elevation degree of freedom, so the model's former 6th feature (an
    // elevation cross-term `sin(az)*|el|/30`, identically zero for every
    // capture and never measured) is repurposed to a 6th azimuth harmonic.
    // This is what lets the fixed 6-coefficient ILD law track QSound's sharp
    // ±54° "beyond-the-speakers" ILD peak: 5 harmonics gave 1.52 dB MAE
    // (fail), 6 harmonics give 0.78 dB (gate ≤1.0 dB). See fit_report.md.
    let s1 = az.sin();
    let s2 = (2.0 * az).sin();
    let s3 = (3.0 * az).sin();
    let s4 = (4.0 * az).sin();
    let s5 = (5.0 * az).sin();
    let s6 = (6.0 * az).sin();
    [s1, s2, s3, s4, s5, s6]
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

        // ITD: the law now evaluates to microseconds (measurement-grounded);
        // convert to samples at the runtime rate. Positive → L lags R;
        // negative → R lags L. One-sided: only the lagging ear sees delay,
        // the leading ear passes straight through.
        let itd_law_us = dot6(&p.itd_coeffs, &itd_ild_features);
        let itd_samples = itd_law_us * ITD_SAMPLES_PER_LAW_UNIT * self.sample_rate;
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
        // and residual biquad startup. Raised 1.0 → 2.0 dB after the
        // 2026-07-02 re-fit: the fitted shelf corners (≈513/1816 Hz) sit
        // closer together than the old 400/2500 Hz placeholders, so their
        // passband ripple stacks with the Lagrange overshoot on the
        // near-unity-gain leading ear (measured peak 1.055 at az=−30°
        // before this bump). 2 dB is an inaudible global pan-stage trim
        // that keeps `peak ≤ +0 dBFS` strict on full-scale noise across
        // the full ±60° sweep.
        const PEAK_SAFETY_DB: f32 = 2.0;
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
