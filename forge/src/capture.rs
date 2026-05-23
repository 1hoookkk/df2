//! WASAPI loopback capture — records system audio output as mono f64.
//!
//! Opening an input stream on the default *output* device gives WASAPI
//! shared-mode loopback (whatever the speakers are playing).

use std::sync::{Arc, Mutex};
use std::time::Instant;

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};

pub const CAPTURE_SECS: f32 = 3.0;

pub struct Capture {
    _stream: cpal::Stream,
    pub buffer: Arc<Mutex<Vec<f32>>>,
    pub sample_rate: f64,
    pub started: Instant,
}

impl Capture {
    pub fn start() -> Result<Self, String> {
        let host = cpal::default_host();
        let device = host
            .default_output_device()
            .ok_or_else(|| "No default output device".to_string())?;

        let supported = device
            .default_output_config()
            .map_err(|e| format!("Output config: {e}"))?;

        let sample_rate = supported.sample_rate().0 as f64;
        let channels = supported.channels() as usize;
        let fmt = supported.sample_format();
        let config: cpal::StreamConfig = supported.into();

        let buffer: Arc<Mutex<Vec<f32>>> = Arc::new(Mutex::new(Vec::with_capacity(
            (sample_rate * (CAPTURE_SECS as f64 + 1.0)) as usize,
        )));

        let stream = build_stream(&device, &config, channels, fmt, buffer.clone())
            .map_err(|e| format!("Build loopback: {e}"))?;
        stream.play().map_err(|e| format!("Start capture: {e}"))?;

        Ok(Self {
            _stream: stream,
            buffer,
            sample_rate,
            started: Instant::now(),
        })
    }

    pub fn elapsed_secs(&self) -> f32 {
        self.started.elapsed().as_secs_f32()
    }

    pub fn drain_mono_f64(&self) -> Vec<f64> {
        self.buffer
            .lock()
            .map(|g| g.iter().map(|&s| s as f64).collect())
            .unwrap_or_default()
    }
}

fn err_fn(e: cpal::StreamError) {
    eprintln!("loopback: {e}");
}

fn build_stream(
    device: &cpal::Device,
    config: &cpal::StreamConfig,
    channels: usize,
    fmt: cpal::SampleFormat,
    buffer: Arc<Mutex<Vec<f32>>>,
) -> Result<cpal::Stream, cpal::BuildStreamError> {
    let ch = channels.max(1);
    match fmt {
        cpal::SampleFormat::F32 => device.build_input_stream(
            config,
            move |data: &[f32], _| push_mono_f32(&buffer, data, ch),
            err_fn,
            None,
        ),
        cpal::SampleFormat::I16 => device.build_input_stream(
            config,
            move |data: &[i16], _| {
                let float: Vec<f32> = data.iter().map(|&s| s as f32 / 32_768.0).collect();
                push_mono_f32(&buffer, &float, ch);
            },
            err_fn,
            None,
        ),
        cpal::SampleFormat::I32 => device.build_input_stream(
            config,
            move |data: &[i32], _| {
                let float: Vec<f32> = data.iter().map(|&s| s as f32 / 2_147_483_648.0).collect();
                push_mono_f32(&buffer, &float, ch);
            },
            err_fn,
            None,
        ),
        cpal::SampleFormat::U16 => device.build_input_stream(
            config,
            move |data: &[u16], _| {
                let float: Vec<f32> = data.iter().map(|&s| s as f32 / 32_768.0 - 1.0).collect();
                push_mono_f32(&buffer, &float, ch);
            },
            err_fn,
            None,
        ),
        _ => {
            // Fallback: treat as f32 (format may not match but beats crashing)
            device.build_input_stream(
                config,
                move |data: &[f32], _| push_mono_f32(&buffer, data, ch),
                err_fn,
                None,
            )
        }
    }
}

fn push_mono_f32(buffer: &Arc<Mutex<Vec<f32>>>, data: &[f32], channels: usize) {
    if let Ok(mut g) = buffer.lock() {
        for chunk in data.chunks(channels) {
            let mono = chunk.iter().sum::<f32>() / channels as f32;
            g.push(mono);
        }
    }
}
