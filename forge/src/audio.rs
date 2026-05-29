//! Live audition. A cpal output stream runs the 6-actor cascade on the audio
//! thread at the E-mu coefficient rate (39062.5 Hz) via linear resampling, so
//! the morph sounds at its true authored frequencies regardless of the device
//! clock. Coefficients are RAMPED (not swapped) so dragging the pad is smooth,
//! never a click.
//!
//! Source = pink noise OR a looped sample (drop a drum loop / vocal to hear
//! YOUR material morph). Works with any device sample format.

use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{FromSample, SizedSample};

const EMU: f64 = 39062.5;
const NS: usize = 6;
const SCOPE_LEN: usize = 2048; // recent output samples for the live response
const DEFAULT_LEVEL: f32 = 0.85;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SourceMode {
    Pink = 0,
    Tone = 1,
    Saw = 2,
}

impl SourceMode {
    fn from_bits(bits: u32) -> Self {
        match bits {
            1 => Self::Tone,
            2 => Self::Saw,
            _ => Self::Pink,
        }
    }
}

/// Per-stage biquad coefficients [b0, b1, b2, a1, a2].
pub type Biquads = [[f64; 5]; NS];

fn passthru() -> Biquads {
    [[1.0, 0.0, 0.0, 0.0, 0.0]; NS]
}

pub struct Audio {
    _stream: cpal::Stream,
    pub target: Arc<Mutex<Biquads>>,
    pub playing: Arc<AtomicBool>,
    pub level: Arc<AtomicU32>,
    pub peak: Arc<AtomicU32>,
    pub scope: Arc<Mutex<Vec<f32>>>,
    pub source_mode: Arc<AtomicU32>,
    pub rate: f64,
    pub device_name: String,
}

impl Audio {
    pub fn set_target(&self, b: Biquads) {
        if let Ok(mut g) = self.target.lock() {
            *g = b;
        }
    }
    pub fn clear_target(&self) {
        self.set_target(passthru());
    }
    pub fn set_playing(&self, on: bool) {
        self.playing.store(on, Ordering::Relaxed);
    }
    pub fn is_playing(&self) -> bool {
        self.playing.load(Ordering::Relaxed)
    }
    pub fn set_level(&self, v: f32) {
        self.level.store(v.to_bits(), Ordering::Relaxed);
    }
    pub fn level(&self) -> f32 {
        f32::from_bits(self.level.load(Ordering::Relaxed))
    }
    pub fn meter(&self) -> f32 {
        f32::from_bits(self.peak.load(Ordering::Relaxed))
    }
    pub fn scope_copy(&self) -> Vec<f32> {
        self.scope.lock().map(|g| g.clone()).unwrap_or_default()
    }
    pub fn set_source_mode(&self, mode: SourceMode) {
        self.source_mode.store(mode as u32, Ordering::Relaxed);
    }
    pub fn source_mode(&self) -> SourceMode {
        SourceMode::from_bits(self.source_mode.load(Ordering::Relaxed))
    }
}

// Resampler + ramped cascade. The dry input is supplied per host sample.
struct Voice {
    ratio: f64,
    cur: Biquads,
    s1: [f64; NS],
    s2: [f64; NS],
    host_idx: u64,
    emu_idx: u64,
    x_prev: f64,
    x_cur: f64,
    ey_prev: f64,
    ey_cur: f64,
}
impl Voice {
    fn new(sr: f64) -> Self {
        Self {
            ratio: EMU / sr,
            cur: passthru(),
            s1: [0.0; NS],
            s2: [0.0; NS],
            host_idx: 0,
            emu_idx: 0,
            x_prev: 0.0,
            x_cur: 0.0,
            ey_prev: 0.0,
            ey_cur: 0.0,
        }
    }
    fn sample(&mut self, tgt: &Biquads, x_dry: f64, lvl: f64) -> f32 {
        self.x_prev = self.x_cur;
        self.x_cur = x_dry;
        self.host_idx += 1;
        while (self.emu_idx as f64) / self.ratio <= self.host_idx as f64 {
            let hm = self.emu_idx as f64 / self.ratio;
            let frac = (hm - (self.host_idx as f64 - 1.0)).clamp(0.0, 1.0);
            let xs = self.x_prev + (self.x_cur - self.x_prev) * frac;
            for i in 0..NS {
                for j in 0..5 {
                    self.cur[i][j] += (tgt[i][j] - self.cur[i][j]) * 0.004;
                }
            }
            let mut y = xs;
            for i in 0..NS {
                let [b0, b1, b2, a1, a2] = self.cur[i];
                let yo = b0 * y + self.s1[i];
                self.s1[i] = b1 * y - a1 * yo + self.s2[i];
                self.s2[i] = b2 * y - a2 * yo;
                y = yo;
                if !y.is_finite() {
                    y = 0.0;
                    self.s1[i] = 0.0;
                    self.s2[i] = 0.0;
                }
            }
            self.ey_prev = self.ey_cur;
            self.ey_cur = y;
            self.emu_idx += 1;
        }
        let et = (self.host_idx as f64 - 1.0) * self.ratio;
        let f = (et - (self.emu_idx as f64 - 2.0)).clamp(0.0, 1.0);
        let yv = self.ey_prev + (self.ey_cur - self.ey_prev) * f;
        (yv * lvl * 4.0).tanh() as f32
    }
}

#[allow(clippy::too_many_arguments)]
fn run<T>(
    device: &cpal::Device,
    config: &cpal::StreamConfig,
    channels: usize,
    target: Arc<Mutex<Biquads>>,
    playing: Arc<AtomicBool>,
    level: Arc<AtomicU32>,
    peak: Arc<AtomicU32>,
    scope: Arc<Mutex<Vec<f32>>>,
    source_mode: Arc<AtomicU32>,
) -> Option<cpal::Stream>
where
    T: SizedSample + FromSample<f32>,
{
    let mut voice = Voice::new(config.sample_rate.0 as f64);
    let host_rate = config.sample_rate.0 as f64;
    let mut meter = 0f32;
    let mut pb = [0f64; 7];
    let mut rng = 0x2545_F491_4F6C_DD1Du64;
    let mut phase = 0.0f64;
    device
        .build_output_stream(
            config,
            move |data: &mut [T], _| {
                let tgt = *target.lock().unwrap();
                let on = playing.load(Ordering::Relaxed);
                let lvl = f32::from_bits(level.load(Ordering::Relaxed)) as f64;
                let mode = SourceMode::from_bits(source_mode.load(Ordering::Relaxed));
                let mut block: Vec<f32> = Vec::with_capacity(data.len() / channels.max(1) + 1);
                for frame in data.chunks_mut(channels.max(1)) {
                    let x = if !on {
                        0.0
                    } else {
                        match mode {
                            SourceMode::Tone => {
                                let v = (std::f64::consts::TAU * phase).sin() * 0.45;
                                phase = (phase + 110.0 / host_rate).fract();
                                v
                            }
                            SourceMode::Saw => {
                                let v = (phase * 2.0 - 1.0) * 0.36;
                                phase = (phase + 110.0 / host_rate).fract();
                                v
                            }
                            SourceMode::Pink => {
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
                                let pink = (pb[0]
                                    + pb[1]
                                    + pb[2]
                                    + pb[3]
                                    + pb[4]
                                    + pb[5]
                                    + pb[6]
                                    + white * 0.5362)
                                    * 0.11;
                                pb[6] = white * 0.115926;
                                pink
                            }
                        }
                    };
                    let out = voice.sample(&tgt, x, lvl);
                    meter = meter.max(out.abs());
                    block.push(out);
                    let s = T::from_sample(out);
                    for xx in frame.iter_mut() {
                        *xx = s;
                    }
                }
                peak.store(meter.to_bits(), Ordering::Relaxed);
                meter *= 0.55;
                if let Ok(mut sc) = scope.lock() {
                    sc.extend_from_slice(&block);
                    let n = sc.len();
                    if n > SCOPE_LEN {
                        sc.drain(0..n - SCOPE_LEN);
                    }
                }
            },
            move |e| eprintln!("audio stream error: {e}"),
            None,
        )
        .ok()
}

/// Names of available output devices (for the device picker).
pub fn list_output_devices() -> Vec<String> {
    let host = cpal::default_host();
    let mut names = Vec::new();
    if let Ok(devs) = host.output_devices() {
        for d in devs {
            if let Ok(n) = d.name() {
                names.push(n);
            }
        }
    }
    names
}

pub fn start() -> Option<Audio> {
    start_on(None)
}

/// Start on a named output device (or the default if `None`).
pub fn start_on(name: Option<&str>) -> Option<Audio> {
    let host = cpal::default_host();
    let device = match name {
        Some(n) => host
            .output_devices()
            .ok()
            .and_then(|mut ds| ds.find(|d| d.name().map(|x| x == n).unwrap_or(false)))
            .or_else(|| host.default_output_device())?,
        None => host.default_output_device()?,
    };
    let device_name = device.name().unwrap_or_else(|_| "default".into());
    let supported = device.default_output_config().ok()?;
    let sample_format = supported.sample_format();
    let sr = supported.sample_rate().0 as f64;
    let channels = supported.channels() as usize;
    let config: cpal::StreamConfig = supported.into();

    let target = Arc::new(Mutex::new(passthru()));
    let playing = Arc::new(AtomicBool::new(false));
    let level = Arc::new(AtomicU32::new(DEFAULT_LEVEL.to_bits()));
    let peak = Arc::new(AtomicU32::new(0));
    let scope = Arc::new(Mutex::new(Vec::with_capacity(SCOPE_LEN)));
    let source_mode = Arc::new(AtomicU32::new(SourceMode::Saw as u32));

    let stream = match sample_format {
        cpal::SampleFormat::F32 => run::<f32>(
            &device,
            &config,
            channels,
            target.clone(),
            playing.clone(),
            level.clone(),
            peak.clone(),
            scope.clone(),
            source_mode.clone(),
        ),
        cpal::SampleFormat::F64 => run::<f64>(
            &device,
            &config,
            channels,
            target.clone(),
            playing.clone(),
            level.clone(),
            peak.clone(),
            scope.clone(),
            source_mode.clone(),
        ),
        cpal::SampleFormat::I8 => run::<i8>(
            &device,
            &config,
            channels,
            target.clone(),
            playing.clone(),
            level.clone(),
            peak.clone(),
            scope.clone(),
            source_mode.clone(),
        ),
        cpal::SampleFormat::I16 => run::<i16>(
            &device,
            &config,
            channels,
            target.clone(),
            playing.clone(),
            level.clone(),
            peak.clone(),
            scope.clone(),
            source_mode.clone(),
        ),
        cpal::SampleFormat::U16 => run::<u16>(
            &device,
            &config,
            channels,
            target.clone(),
            playing.clone(),
            level.clone(),
            peak.clone(),
            scope.clone(),
            source_mode.clone(),
        ),
        cpal::SampleFormat::I32 => run::<i32>(
            &device,
            &config,
            channels,
            target.clone(),
            playing.clone(),
            level.clone(),
            peak.clone(),
            scope.clone(),
            source_mode.clone(),
        ),
        cpal::SampleFormat::I64 => run::<i64>(
            &device,
            &config,
            channels,
            target.clone(),
            playing.clone(),
            level.clone(),
            peak.clone(),
            scope.clone(),
            source_mode.clone(),
        ),
        cpal::SampleFormat::U8 => run::<u8>(
            &device,
            &config,
            channels,
            target.clone(),
            playing.clone(),
            level.clone(),
            peak.clone(),
            scope.clone(),
            source_mode.clone(),
        ),
        cpal::SampleFormat::U32 => run::<u32>(
            &device,
            &config,
            channels,
            target.clone(),
            playing.clone(),
            level.clone(),
            peak.clone(),
            scope.clone(),
            source_mode.clone(),
        ),
        cpal::SampleFormat::U64 => run::<u64>(
            &device,
            &config,
            channels,
            target.clone(),
            playing.clone(),
            level.clone(),
            peak.clone(),
            scope.clone(),
            source_mode.clone(),
        ),
        other => {
            eprintln!("audio: unsupported sample format {other:?}");
            None
        }
    }?;
    stream.play().ok()?;
    Some(Audio {
        _stream: stream,
        target,
        playing,
        level,
        peak,
        scope,
        source_mode,
        rate: sr,
        device_name,
    })
}
