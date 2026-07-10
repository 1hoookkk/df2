//! FORGE ZERO — iteration 0 of the from-zero design surface.
//!
//! One window. One mode: a pole pair you can grab, a zero pair you can grab.
//! Your loop (drop a WAV) playing through the REAL engine (trench-core:
//! pack_body -> Cartridge -> FilterEngine). The dot lands where your cursor is.
//!
//! The internal model is MODAL (modes with identity), and the 240-byte packed
//! body is its PROJECTION — the A/B baseline is built in from birth.
//! Ladder: it1 native modal render beside the projection · it2 anchors/morph ·
//! it3 mode activation · it4 adaptive order · it5 dual-cascade transitions.

use eframe::egui::{self, Color32, Pos2, Rect, Sense, Stroke, Vec2};
use std::path::Path;
use std::sync::{Arc, Mutex};

const SR_AUTHOR: f32 = 39062.5; // packed-domain rate: drawing + packing
const F_MIN: f32 = 30.0;
const F_MAX: f32 = 16_000.0;
const DB_MIN: f32 = -36.0;
const DB_MAX: f32 = 24.0;
const RP_MAX: f32 = 0.9989;

/// One mode of the design model. Today: a conjugate pole pair plus a paired
/// zero. (Residue/activation arrive with the native render in it1.)
#[derive(Clone, Copy)]
struct Mode {
    pole_hz: f32,
    pole_r: f32,
    zero_hz: f32,
    zero_r: f32,
}

impl Default for Mode {
    fn default() -> Self {
        Self {
            pole_hz: 740.0,
            pole_r: 0.97,
            zero_hz: 1480.0,
            zero_r: 0.90,
        }
    }
}

// ---- response math (single section, conjugate pairs, unity gain) ------------

fn quad_mag(cf: f32, r: f32, w: f32) -> f32 {
    // |1 + a1 z^-1 + a2 z^-2| on the unit circle for a conjugate pair at (cf, r)
    let wc = std::f32::consts::TAU * cf / SR_AUTHOR;
    let (a1, a2) = (-2.0 * r * wc.cos(), r * r);
    let (zr, zi) = (w.cos(), -w.sin());
    let (z2r, z2i) = (zr * zr - zi * zi, 2.0 * zr * zi);
    let re = 1.0 + a1 * zr + a2 * z2r;
    let im = a1 * zi + a2 * z2i;
    (re * re + im * im).sqrt().max(1e-9)
}

fn mode_db(m: &Mode, f: f32) -> f32 {
    let w = std::f32::consts::TAU * f / SR_AUTHOR;
    20.0 * (quad_mag(m.zero_hz, m.zero_r, w) / quad_mag(m.pole_hz, m.pole_r, w)).log10()
}

/// Solve the radius so the curve at the handle's own frequency meets target_db.
/// Monotonic in r -> bisection. This is what makes the dot follow the cursor.
fn solve_radius(m: &Mode, pole: bool, target_db: f32) -> f32 {
    let (mut lo, mut hi) = if pole { (0.05, RP_MAX) } else { (0.0, 1.0) };
    for _ in 0..28 {
        let mid = 0.5 * (lo + hi);
        let mut probe = *m;
        let (f, rising) = if pole {
            probe.pole_r = mid;
            (m.pole_hz, true)
        } else {
            probe.zero_r = mid;
            (m.zero_hz, false)
        };
        if (mode_db(&probe, f) < target_db) == rising {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    0.5 * (lo + hi)
}

// ---- projection: the mode packed into the 240-byte body (all 4 corners) -----

fn pack(m: &Mode) -> [u8; 240] {
    let mut params = Vec::with_capacity(168);
    for _corner in 0..4 {
        // stage 0 = the mode; stages 1-5 off
        params.extend_from_slice(&[
            1.0,
            m.pole_hz as f64,
            m.pole_r as f64,
            1.0, // unity gain — levels are the roots
            if m.zero_r > 0.0001 { 1.0 } else { 0.0 },
            m.zero_hz as f64,
            m.zero_r as f64,
        ]);
        for _ in 1..6 {
            params.extend_from_slice(&[0.0, 1000.0, 0.5, 1.0, 0.0, 1000.0, 0.0]);
        }
    }
    trench_core::compiler::pack_body(&params)
}

// ---- audio: source -> FilterEngine (the shipped chain) -> device ------------

struct AudioCtl {
    playing: bool,
    pending_cart: Option<trench_core::cartridge::Cartridge>,
    pending_loop: Option<Arc<Vec<f32>>>,
}

struct Audio {
    _stream: cpal::Stream,
    ctl: Arc<Mutex<AudioCtl>>,
    sr: f64,
}

fn start_audio(body: [u8; 240]) -> Result<Audio, String> {
    use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
    let device = cpal::default_host()
        .default_output_device()
        .ok_or("no audio output device")?;
    let config = device.default_output_config().map_err(|e| e.to_string())?;
    let sr = config.sample_rate().0 as f64;
    let channels = config.channels() as usize;
    let cart = trench_core::cartridge::Cartridge::from_body_bytes("zero", &body, 1.0)
        .map_err(|e| format!("cartridge: {e}"))?;
    let ctl = Arc::new(Mutex::new(AudioCtl {
        playing: false,
        pending_cart: Some(cart),
        pending_loop: None,
    }));
    let ctl_cb = ctl.clone();
    let mut engine = trench_core::engine::FilterEngine::new();
    engine.prepare(sr);
    let mut loop_buf: Option<Arc<Vec<f32>>> = None;
    let mut loop_pos = 0usize;
    let mut saw_phase = 0.0f32;
    let mut left = vec![0.0f32; 256];
    let mut right = vec![0.0f32; 256];
    let stream = device
        .build_output_stream(
            &config.into(),
            move |data: &mut [f32], _| {
                let (playing, cart, lp) = {
                    let mut c = ctl_cb.lock().unwrap();
                    (c.playing, c.pending_cart.take(), c.pending_loop.take())
                };
                if let Some(cart) = cart {
                    engine.load_cartridge(cart);
                }
                if let Some(lp) = lp {
                    loop_buf = Some(lp);
                    loop_pos = 0;
                }
                if !playing {
                    data.fill(0.0);
                    return;
                }
                let frames = data.len() / channels;
                let mut done = 0;
                while done < frames {
                    let n = (frames - done).min(256);
                    if let Some(buf) = &loop_buf {
                        for v in left[..n].iter_mut() {
                            *v = buf[loop_pos];
                            loop_pos = (loop_pos + 1) % buf.len();
                        }
                    } else {
                        // A1 saw until a loop is dropped
                        let f = 55.0 / sr as f32;
                        for v in left[..n].iter_mut() {
                            saw_phase = (saw_phase + f).fract();
                            *v = (saw_phase * 2.0 - 1.0) * 0.30;
                        }
                    }
                    right[..n].copy_from_slice(&left[..n]);
                    engine.process_block(&mut left[..n], &mut right[..n], 0.0, 0.0);
                    for i in 0..n {
                        let base = (done + i) * channels;
                        data[base] = left[i];
                        if channels > 1 {
                            data[base + 1] = right[i];
                        }
                        for ch in 2..channels {
                            data[base + ch] = 0.0;
                        }
                    }
                    done += n;
                }
            },
            |err| eprintln!("audio: {err}"),
            None,
        )
        .map_err(|e| e.to_string())?;
    stream.play().map_err(|e| e.to_string())?;
    Ok(Audio {
        _stream: stream,
        ctl,
        sr,
    })
}

// ---- minimal WAV reader (PCM16 + float32, first channel) ---------------------

fn read_wav(path: &Path) -> Option<(Vec<f32>, f64)> {
    let b = std::fs::read(path).ok()?;
    if b.len() < 44 || &b[0..4] != b"RIFF" || &b[8..12] != b"WAVE" {
        return None;
    }
    let (mut pos, mut fmt, mut data) = (12usize, None, None);
    while pos + 8 <= b.len() {
        let id = &b[pos..pos + 4];
        let sz = u32::from_le_bytes(b[pos + 4..pos + 8].try_into().ok()?) as usize;
        let body = pos + 8;
        if id == b"fmt " {
            fmt = Some((
                u16::from_le_bytes(b[body..body + 2].try_into().ok()?),
                u16::from_le_bytes(b[body + 2..body + 4].try_into().ok()?),
                u32::from_le_bytes(b[body + 4..body + 8].try_into().ok()?),
                u16::from_le_bytes(b[body + 14..body + 16].try_into().ok()?),
            ));
        } else if id == b"data" {
            data = Some((body, sz.min(b.len().saturating_sub(body))));
        }
        pos = body + sz + (sz & 1);
    }
    let ((tag, ch, sr, bits), (off, len)) = (fmt?, data?);
    let ch = ch.max(1) as usize;
    let mut out = Vec::new();
    match (tag, bits) {
        (1, 16) => {
            let step = 2 * ch;
            for i in (off..off + len).step_by(step) {
                if i + 2 > b.len() {
                    break;
                }
                out.push(i16::from_le_bytes([b[i], b[i + 1]]) as f32 / 32768.0);
            }
        }
        (3, 32) => {
            let step = 4 * ch;
            for i in (off..off + len).step_by(step) {
                if i + 4 > b.len() {
                    break;
                }
                out.push(f32::from_le_bytes([b[i], b[i + 1], b[i + 2], b[i + 3]]));
            }
        }
        _ => return None,
    }
    if out.is_empty() {
        return None;
    }
    Some((out, sr as f64))
}

// ---- the app -----------------------------------------------------------------

#[derive(Clone, Copy, PartialEq)]
enum Grab {
    Pole,
    Zero,
}

struct Zero {
    mode: Mode,
    audio: Option<Audio>,
    playing: bool,
    grab: Option<Grab>,
    status: String,
}

impl Zero {
    fn push_body(&mut self) {
        if let Some(a) = &self.audio {
            if let Ok(cart) =
                trench_core::cartridge::Cartridge::from_body_bytes("zero", &pack(&self.mode), 1.0)
            {
                if let Ok(mut c) = a.ctl.lock() {
                    c.pending_cart = Some(cart);
                }
            }
        }
    }
}

fn x_of(rect: Rect, f: f32) -> f32 {
    rect.left() + (f / F_MIN).log2() / (F_MAX / F_MIN).log2() * rect.width()
}
fn f_of(rect: Rect, x: f32) -> f32 {
    let t = ((x - rect.left()) / rect.width()).clamp(0.0, 1.0);
    F_MIN * (F_MAX / F_MIN).powf(t)
}
fn y_of(rect: Rect, db: f32) -> f32 {
    rect.bottom() - (db - DB_MIN) / (DB_MAX - DB_MIN) * rect.height()
}
fn db_of(rect: Rect, y: f32) -> f32 {
    DB_MIN + ((rect.bottom() - y) / rect.height()).clamp(0.0, 1.0) * (DB_MAX - DB_MIN)
}

impl eframe::App for Zero {
    fn update(&mut self, ctx: &egui::Context, _f: &mut eframe::Frame) {
        // drop a WAV anywhere = the loop
        let dropped = ctx.input(|i| i.raw.dropped_files.clone());
        if let Some(path) = dropped.first().and_then(|d| d.path.clone()) {
            if let Some((samples, wav_sr)) = read_wav(&path) {
                let dev_sr = self.audio.as_ref().map(|a| a.sr).unwrap_or(48_000.0);
                let n_out = ((samples.len() as f64) * dev_sr / wav_sr).max(1.0) as usize;
                let mut buf = Vec::with_capacity(n_out);
                for i in 0..n_out {
                    let x = i as f64 * wav_sr / dev_sr;
                    let j = x as usize;
                    let fr = (x - j as f64) as f32;
                    let a = samples[j.min(samples.len() - 1)];
                    let b = samples[(j + 1).min(samples.len() - 1)];
                    buf.push(a + (b - a) * fr);
                }
                let peak = buf.iter().fold(0.0f32, |m, v| m.max(v.abs())).max(1e-9);
                for v in &mut buf {
                    *v *= 0.5 / peak;
                }
                if let Some(a) = &self.audio {
                    if let Ok(mut c) = a.ctl.lock() {
                        c.pending_loop = Some(Arc::new(buf));
                    }
                }
                self.status = format!(
                    "loop: {}",
                    path.file_name().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default()
                );
            } else {
                self.status = "not a readable WAV (PCM16 / float32)".into();
            }
        }

        egui::CentralPanel::default()
            .frame(egui::Frame::none().fill(Color32::from_rgb(8, 10, 10)))
            .show(ctx, |ui| {
                let full = ui.available_rect_before_wrap();
                let bar = Rect::from_min_size(full.min, Vec2::new(full.width(), 34.0));
                let plot = Rect::from_min_max(
                    Pos2::new(full.left() + 8.0, bar.bottom() + 4.0),
                    Pos2::new(full.right() - 8.0, full.bottom() - 26.0),
                );
                let p = ui.painter();

                // top bar: PLAY + status
                let play_r = Rect::from_min_size(
                    Pos2::new(bar.left() + 10.0, bar.top() + 5.0),
                    Vec2::new(70.0, 24.0),
                );
                p.rect_filled(play_r, 4.0, Color32::from_rgb(20, 30, 26));
                p.rect_stroke(
                    play_r,
                    4.0,
                    Stroke::new(1.0, Color32::from_rgb(70, 200, 120)),
                );
                p.text(
                    play_r.center(),
                    egui::Align2::CENTER_CENTER,
                    if self.playing { "STOP" } else { "PLAY" },
                    egui::FontId::monospace(13.0),
                    Color32::from_rgb(120, 240, 160),
                );
                p.text(
                    Pos2::new(play_r.right() + 14.0, bar.center().y),
                    egui::Align2::LEFT_CENTER,
                    "FORGE ZERO — one mode · drag the dots · drop a WAV",
                    egui::FontId::monospace(12.0),
                    Color32::from_rgb(140, 160, 150),
                );

                // grid
                p.rect_filled(plot, 4.0, Color32::from_rgb(12, 15, 15));
                for f in [100.0, 1000.0, 10000.0] {
                    let x = x_of(plot, f);
                    p.line_segment(
                        [Pos2::new(x, plot.top()), Pos2::new(x, plot.bottom())],
                        Stroke::new(0.6, Color32::from_rgb(30, 38, 36)),
                    );
                }
                let y0 = y_of(plot, 0.0);
                p.line_segment(
                    [Pos2::new(plot.left(), y0), Pos2::new(plot.right(), y0)],
                    Stroke::new(0.8, Color32::from_rgb(45, 55, 52)),
                );

                // the curve — this IS the mode; nothing else exists yet
                let n = 360;
                let pts: Vec<Pos2> = (0..n)
                    .map(|i| {
                        let f = F_MIN * (F_MAX / F_MIN).powf(i as f32 / (n - 1) as f32);
                        Pos2::new(x_of(plot, f), y_of(plot, mode_db(&self.mode, f)))
                    })
                    .collect();
                p.add(egui::Shape::line(
                    pts,
                    Stroke::new(2.4, Color32::from_rgb(235, 245, 240)),
                ));

                // the two dots, ON the curve at their own frequencies
                let pole_pos = Pos2::new(
                    x_of(plot, self.mode.pole_hz),
                    y_of(plot, mode_db(&self.mode, self.mode.pole_hz)),
                );
                let zero_pos = Pos2::new(
                    x_of(plot, self.mode.zero_hz),
                    y_of(plot, mode_db(&self.mode, self.mode.zero_hz)),
                );
                p.circle_filled(pole_pos, 8.0, Color32::from_rgb(255, 178, 92));
                p.circle_stroke(zero_pos, 8.0, Stroke::new(2.4, Color32::from_rgb(127, 212, 255)));

                // interaction
                let resp = ui.interact(full, ui.id().with("z"), Sense::click_and_drag());
                let pointer = ctx.input(|i| i.pointer.interact_pos());
                if resp.drag_started() {
                    if let Some(pos) = pointer {
                        if play_r.contains(pos) {
                            // fall through: click handled on release
                        } else {
                            let dp = pos.distance(pole_pos);
                            let dz = pos.distance(zero_pos);
                            if dp.min(dz) < 30.0 {
                                self.grab = Some(if dp <= dz { Grab::Pole } else { Grab::Zero });
                            }
                        }
                    }
                }
                if resp.clicked() {
                    if let Some(pos) = pointer {
                        if play_r.contains(pos) {
                            self.playing = !self.playing;
                            if self.playing && self.audio.is_none() {
                                match start_audio(pack(&self.mode)) {
                                    Ok(a) => self.audio = Some(a),
                                    Err(e) => {
                                        self.playing = false;
                                        self.status = format!("audio failed: {e}");
                                    }
                                }
                            }
                            if let Some(a) = &self.audio {
                                if let Ok(mut c) = a.ctl.lock() {
                                    c.playing = self.playing;
                                }
                            }
                        }
                    }
                }
                if let (Some(g), Some(pos)) = (self.grab, pointer) {
                    if resp.dragged() {
                        let f = f_of(plot, pos.x).clamp(F_MIN, F_MAX);
                        let db_t = db_of(plot, pos.y);
                        match g {
                            Grab::Pole => {
                                self.mode.pole_hz = f;
                                self.mode.pole_r = solve_radius(&self.mode, true, db_t);
                            }
                            Grab::Zero => {
                                self.mode.zero_hz = f;
                                self.mode.zero_r = solve_radius(&self.mode, false, db_t);
                            }
                        }
                        self.push_body();
                    }
                }
                if resp.drag_stopped() {
                    self.grab = None;
                }

                // footer: the mode, in plain words
                p.text(
                    Pos2::new(plot.left(), full.bottom() - 18.0),
                    egui::Align2::LEFT_TOP,
                    format!(
                        "pole {:.0} Hz r{:.3}   ·   zero {:.0} Hz r{:.3}   ·   {}",
                        self.mode.pole_hz,
                        self.mode.pole_r,
                        self.mode.zero_hz,
                        self.mode.zero_r,
                        self.status
                    ),
                    egui::FontId::monospace(11.0),
                    Color32::from_rgb(120, 140, 132),
                );
            });
    }
}

fn main() -> eframe::Result<()> {
    eframe::run_native(
        "FORGE ZERO",
        eframe::NativeOptions {
            viewport: egui::ViewportBuilder::default().with_inner_size([980.0, 560.0]),
            ..Default::default()
        },
        Box::new(|_| {
            Ok(Box::new(Zero {
                mode: Mode::default(),
                audio: None,
                playing: false,
                grab: None,
                status: "drop a WAV to replace the saw".into(),
            }))
        }),
    )
}
